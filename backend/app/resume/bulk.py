"""Bulk résumé import (worker side).

Each uploaded file is already validated and stored; this module turns ``PENDING`` items into company-sourced
(``IMPORTED``) candidates, one item at a time:

* a file whose SHA-256 the company already imported, or whose contact e-mail belongs to an existing imported candidate of
  the company / a registered candidate account, is reported as ``DUPLICATE`` (and linked when the importer may see it);
* an unreadable / scanned / non-résumé file is ``FAILED`` with a safe code — it never fails the batch;
* a new candidate is created, together with its résumé, processing result and the structured profile data the parser
  found (``source = RESUME``; there is no account owner to review it — the recruiter can correct it through the
  ``extracted`` endpoints), in **one transaction** with the item's status, so a redelivered task never double-imports.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheDomain
from app.core.config import get_settings
from app.db.models import (
    BulkImportBatch,
    BulkImportItem,
    CandidateProfile,
    CandidateSource,
    ImportItemStatus,
    NotificationType,
    ProcessingStatus,
    Resume,
    ResumeDocument,
    ResumeStatus,
    Skill,
    User,
)
from app.matching.embedder import EmbeddingError
from app.matching.service import MatchingService
from app.resume import profile as profile_ops
from app.resume.extract import ExtractionError
from app.resume.pipeline import Analysis, analyze, embed_resume, get_dispatcher, result_values, upsert_result
from app.resume.storage import StorageError, StorageNotFoundError, get_storage, read_bounded
from app.resume.validation import CONTENT_TYPES, MIB, DocumentKind, sniff_head
from app.services.access import CandidateAccess, candidate_access_for
from app.services.common import utcnow
from app.services.notifications import NotificationService
from app.workers.tasks import TaskContext, TaskFailure

logger = logging.getLogger(__name__)

E_DUP_FILE = "DUPLICATE_FILE"
E_DUP_CANDIDATE = "DUPLICATE_CANDIDATE"
E_NO_IDENTITY = "NO_CANDIDATE_IDENTIFIED"


@dataclass(slots=True)
class _Item:
    id: uuid.UUID
    storage_key: str
    filename: str
    sha256: str
    size_bytes: int


@dataclass(slots=True)
class _Outcome:
    status: ImportItemStatus
    code: str | None = None
    message: str | None = None
    candidate_id: uuid.UUID | None = None
    resume_id: uuid.UUID | None = None
    keep_blob: bool = False


def _kind_from_bytes(data: bytes) -> DocumentKind | None:
    sniffed = sniff_head(data[:8])
    return {"pdf": DocumentKind.PDF, "zip": DocumentKind.DOCX}.get(sniffed)


async def _find_duplicate(
    session: AsyncSession, importer: User | None, company_id: uuid.UUID, sha256: str, email: str | None
) -> _Outcome | None:
    row = (
        await session.execute(
            select(Resume.candidate_id, Resume.id)
            .join(ResumeDocument, ResumeDocument.resume_id == Resume.id)
            .join(CandidateProfile, CandidateProfile.id == Resume.candidate_id)
            .where(
                ResumeDocument.sha256 == sha256,
                CandidateProfile.source == CandidateSource.IMPORTED,
                CandidateProfile.sourced_by_company_id == company_id,
            )
            .limit(1)
        )
    ).first()
    if row:
        return _Outcome(
            ImportItemStatus.DUPLICATE, E_DUP_FILE, "This exact file was already imported.", row[0], row[1]
        )
    if not email:
        return None
    existing = await session.scalar(
        select(CandidateProfile.id).where(
            CandidateProfile.source == CandidateSource.IMPORTED,
            CandidateProfile.sourced_by_company_id == company_id,
            func.lower(CandidateProfile.contact_email) == email,
        )
    )
    if existing:
        primary = await session.scalar(
            select(Resume.id).where(Resume.candidate_id == existing, Resume.is_primary.is_(True))
        )
        return _Outcome(
            ImportItemStatus.DUPLICATE,
            E_DUP_CANDIDATE,
            "A candidate with this e-mail address already exists in your talent pool.",
            existing,
            primary,
        )
    registered = (
        await session.execute(
            select(CandidateProfile)
            .join(User, User.id == CandidateProfile.user_id)
            .where(func.lower(User.email) == email)
        )
    ).scalar_one_or_none()
    if registered is not None:
        # Existence is confirmed, but the profile is only linked when the importer may already see it.
        visible = (
            importer is not None
            and await candidate_access_for(session, importer, registered) != CandidateAccess.NONE
        )
        return _Outcome(
            ImportItemStatus.DUPLICATE,
            E_DUP_CANDIDATE,
            "A candidate with this e-mail address is already registered on the platform.",
            registered.id if visible else None,
        )
    return None


def _fill_profile(cand: CandidateProfile, parsed: dict[str, Any]) -> None:
    contact = parsed.get("contact") or {}
    cand.headline = (parsed.get("headline") or None) and str(parsed["headline"])[:200]
    cand.summary = parsed.get("summary") or None
    cand.location = (contact.get("location") or None) and str(contact["location"])[:200]
    cand.years_experience = profile_ops.years_value(parsed)
    for attr in ("linkedin_url", "github_url", "portfolio_url"):
        value = contact.get(attr)
        if isinstance(value, str) and value and len(value) <= 500:
            setattr(cand, attr, value)


def _add_children(session: AsyncSession, candidate_id: uuid.UUID, parsed: dict[str, Any]) -> None:
    today = date.today()
    seen_exp: set[tuple[str, str, str]] = set()
    for item in parsed.get("experiences") or []:
        row, _ = profile_ops.build_experience(candidate_id, item, today)
        if row is not None:
            key = profile_ops.experience_key(row.title, row.company_name, row.start_date)
            if key not in seen_exp:
                seen_exp.add(key)
                session.add(row)
    seen_edu: set[tuple[str, str]] = set()
    for item in parsed.get("educations") or []:
        edu, _ = profile_ops.build_education(candidate_id, item)
        if edu is not None:
            edu_key = profile_ops.education_key(edu.institution, edu.degree_level.value)
            if edu_key not in seen_edu:
                seen_edu.add(edu_key)
                session.add(edu)
    seen_cert: set[str] = set()
    for item in parsed.get("certifications") or []:
        cert, _ = profile_ops.build_certification(candidate_id, item)
        if cert is not None and profile_ops.norm(cert.name) not in seen_cert:
            seen_cert.add(profile_ops.norm(cert.name))
            session.add(cert)
    seen_lang: set[str] = set()
    for item in parsed.get("languages") or []:
        lang, _ = profile_ops.build_language(candidate_id, item)
        if lang is not None and profile_ops.norm(lang.language) not in seen_lang:
            seen_lang.add(profile_ops.norm(lang.language))
            session.add(lang)


async def _create_candidate(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None,
    item: _Item,
    kind: DocumentKind,
    analysis: Analysis,
    resolved: dict[str, Skill],
    embedding: list[float] | None,
    duration_ms: int,
) -> _Outcome:
    parsed = analysis.parsed_data
    contact = parsed["contact"]
    first, last = profile_ops.split_name(contact.get("name"))
    display = (contact.get("name") or "Unnamed candidate")[:210]
    cand = CandidateProfile(
        user_id=None,
        source=CandidateSource.IMPORTED,
        sourced_by_company_id=company_id,
        first_name=first,
        last_name=last,
        display_name=display,
        contact_email=contact.get("email"),
        contact_phone=contact.get("phone"),
        is_searchable=False,
    )
    _fill_profile(cand, parsed)
    session.add(cand)
    await session.flush()
    resume = Resume(
        candidate_id=cand.id, uploaded_by_id=user_id, status=ResumeStatus.PROCESSED, is_primary=True
    )
    session.add(resume)
    await session.flush()
    doc = ResumeDocument(
        resume_id=resume.id,
        storage_key=item.storage_key,
        original_filename=item.filename,
        content_type=CONTENT_TYPES[kind],
        size_bytes=item.size_bytes,
        sha256=item.sha256,
    )
    session.add(doc)
    await session.flush()
    values = result_values(
        analysis, embedding=embedding, duration_ms=duration_ms, embedding_error=embedding is None
    )
    values.update(started_at=utcnow(), status=ProcessingStatus.COMPLETED)
    await upsert_result(session, resume.id, doc.id, values)
    _add_children(session, cand.id, parsed)
    await profile_ops.merge_skill_suggestions(
        session,
        cand.id,
        [(resolved[s.name], s.confidence) for s in analysis.parsed.skills if s.name in resolved],
    )
    return _Outcome(ImportItemStatus.CREATED, None, None, cand.id, resume.id, keep_blob=True)


async def _finish_item(session: AsyncSession, item_id: uuid.UUID, outcome: _Outcome) -> None:
    await session.execute(
        update(BulkImportItem)
        .where(BulkImportItem.id == item_id, BulkImportItem.status == ImportItemStatus.PENDING)
        .values(
            status=outcome.status,
            candidate_id=outcome.candidate_id,
            resume_id=outcome.resume_id,
            error_code=outcome.code,
            error_message=(outcome.message or None) and outcome.message[:500],
        )
    )


async def _import_one(
    ctx: TaskContext, company_id: uuid.UUID, user_id: uuid.UUID | None, item: _Item
) -> _Outcome:
    settings = get_settings()
    storage = get_storage()
    try:
        data = await read_bounded(storage, item.storage_key, int(settings.max_resume_mb * MIB * 1.05))
    except StorageNotFoundError:
        return _Outcome(ImportItemStatus.FAILED, "FILE_MISSING", "The uploaded file could not be found.")
    except StorageError:
        return _Outcome(ImportItemStatus.FAILED, "FILE_UNREADABLE", "The uploaded file could not be read.")
    kind = _kind_from_bytes(data)
    if kind is None:
        return _Outcome(ImportItemStatus.FAILED, "UNSUPPORTED_DOCUMENT", "The file type is not supported.")

    async with ctx.sessionmaker() as s:
        importer = await s.get(User, user_id) if user_id else None
        dup = await _find_duplicate(s, importer, company_id, item.sha256, None)
    if dup:
        return dup

    started = time.monotonic()
    try:
        analysis = await analyze(data, kind)
    except ExtractionError as exc:
        return _Outcome(ImportItemStatus.FAILED, exc.code, exc.message)
    email = analysis.parsed.contact.email
    if not (analysis.parsed.contact.name or email):
        return _Outcome(
            ImportItemStatus.FAILED,
            E_NO_IDENTITY,
            "No name or e-mail address could be found in this document; it may not be a résumé.",
        )

    async with ctx.sessionmaker() as s:
        importer = await s.get(User, user_id) if user_id else None
        dup = await _find_duplicate(s, importer, company_id, item.sha256, email)
        if dup:
            return dup
        resolved = await profile_ops.resolve_skills(s, (sk.name for sk in analysis.parsed.skills))
    try:
        embedding = await embed_resume(analysis.parsed, analysis.extracted.text)
    except EmbeddingError:
        embedding = None

    duration_ms = int((time.monotonic() - started) * 1000)
    async with ctx.sessionmaker() as s:
        try:
            outcome = await _create_candidate(
                s,
                company_id=company_id,
                user_id=user_id,
                item=item,
                kind=kind,
                analysis=analysis,
                resolved=resolved,
                embedding=embedding,
                duration_ms=duration_ms,
            )
            await _finish_item(s, item.id, outcome)
            await s.commit()
        except IntegrityError:
            # Lost a race against another import of the same e-mail (uq_candidate_profiles_company_email).
            await s.rollback()
            importer = await s.get(User, user_id) if user_id else None
            dup = await _find_duplicate(s, importer, company_id, item.sha256, email)
            if dup:
                return dup
            raise
    if outcome.candidate_id is not None:
        try:
            async with ctx.sessionmaker() as s:
                await MatchingService(s).refresh_candidate_index(outcome.candidate_id)
        except (
            Exception
        ) as exc:  # the candidate exists and is searchable by text; the embedding is rebuilt on next change
            logger.warning(
                "imported candidate embedding failed",
                extra={"candidate_id": str(outcome.candidate_id), "error": type(exc).__name__},
            )
    return outcome


async def run_bulk_import(ctx: TaskContext) -> dict[str, Any]:
    batch_id = uuid.UUID(str(ctx.params["batch_id"]))
    await ctx.progress(2, "loading batch")
    async with ctx.sessionmaker() as s:
        batch = await s.get(BulkImportBatch, batch_id)
        if batch is None:
            raise TaskFailure("BATCH_NOT_FOUND", "This import batch no longer exists.")
        company_id, user_id = batch.company_id, batch.created_by_id
        items = [
            _Item(i.id, i.storage_key, i.filename, i.sha256, i.size_bytes)
            for i in (
                await s.execute(
                    select(BulkImportItem)
                    .where(
                        BulkImportItem.batch_id == batch_id, BulkImportItem.status == ImportItemStatus.PENDING
                    )
                    .order_by(BulkImportItem.created_at, BulkImportItem.id)
                )
            ).scalars()
        ]
        total = int(
            await s.scalar(
                select(func.count()).select_from(BulkImportItem).where(BulkImportItem.batch_id == batch_id)
            )
            or 0
        )
        already = total - len(items)

    storage = get_storage()
    for n, item in enumerate(items, start=1):
        try:
            outcome = await _import_one(ctx, company_id, user_id, item)
            if outcome.status != ImportItemStatus.CREATED:
                async with ctx.sessionmaker() as s:
                    await _finish_item(s, item.id, outcome)
                    await s.commit()
        except Exception as exc:  # one bad file must never fail the batch
            logger.error(
                "bulk import item failed",
                extra={"batch_id": str(batch_id), "item_id": str(item.id), "error": type(exc).__name__},
            )
            outcome = _Outcome(
                ImportItemStatus.FAILED,
                "INTERNAL_ERROR",
                "An unexpected error occurred while importing this file.",
            )
            async with ctx.sessionmaker() as s:
                await _finish_item(s, item.id, outcome)
                await s.commit()
        if not outcome.keep_blob:  # duplicates / failures are not kept on disk
            try:
                await storage.delete(item.storage_key)
            except StorageError:
                logger.warning("could not remove rejected import file", extra={"item_id": str(item.id)})
        await ctx.progress(
            min(95, int((already + n) * 95 / max(total, 1))), f"importing {already + n}/{total}"
        )

    return await _finalize(ctx, batch_id, company_id, user_id)


async def _finalize(
    ctx: TaskContext, batch_id: uuid.UUID, company_id: uuid.UUID, user_id: uuid.UUID | None
) -> dict[str, Any]:
    async with ctx.sessionmaker() as s:
        counts = {
            status: int(n)
            for status, n in (
                await s.execute(
                    select(BulkImportItem.status, func.count())
                    .where(BulkImportItem.batch_id == batch_id)
                    .group_by(BulkImportItem.status)
                )
            ).all()
        }
        await s.execute(
            update(BulkImportBatch).where(BulkImportBatch.id == batch_id).values(finished_at=utcnow())
        )
        created = counts.get(ImportItemStatus.CREATED, 0)
        duplicates = counts.get(ImportItemStatus.DUPLICATE, 0)
        failed = counts.get(ImportItemStatus.FAILED, 0)
        if user_id is not None:
            await NotificationService(s).stage(
                user_id,
                NotificationType.BULK_IMPORT_COMPLETED,
                "Résumé import finished",
                f"{created} candidate{'s' if created != 1 else ''} imported, {duplicates} duplicate{'s' if duplicates != 1 else ''}, {failed} failed.",
                dedupe_key=f"bulk-import:{batch_id}",
            )
        await s.commit()
    await ctx.cache.invalidate(CacheDomain.CANDIDATES, CacheDomain.MATCHES)
    if created:
        dispatcher, close = await get_dispatcher(ctx)
        try:
            async with ctx.sessionmaker() as s:
                await profile_ops.schedule_company_job_matches(s, dispatcher, company_id, user_id=user_id)
        except Exception as exc:
            logger.warning(
                "could not queue matching after import",
                extra={"batch_id": str(batch_id), "error": type(exc).__name__},
            )
        finally:
            await close()
    return {
        "batch_id": str(batch_id),
        "created": created,
        "duplicates": duplicates,
        "failed": failed,
        "total": sum(counts.values()),
    }
