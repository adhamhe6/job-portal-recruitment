"""The résumé processing pipeline (worker side).

``loading document → extracting text → parsing → resolving skills → embedding → saving → refreshing candidate profile
index``. The same building blocks serve single-résumé processing (``handle_process_resume``) and the bulk importer
(``app.resume.bulk``).

Failure model: expected failures raise :class:`~app.workers.tasks.TaskFailure` with a safe code / message (never document
content); the résumé and its processing result are marked ``FAILED`` and the owner is notified. Embedding trouble is
different — the extracted data is still valuable, so it is saved and the task is retried a bounded number of times
(``task_max_attempts``); after the last attempt the résumé is kept as processed *without* an embedding.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheDomain
from app.core.config import get_settings
from app.db.models import (
    CandidateProfile,
    NotificationType,
    ProcessingStatus,
    Resume,
    ResumeDocument,
    ResumeProcessingResult,
    ResumeStatus,
    Skill,
)
from app.matching.embedder import EmbeddingError, get_embedder
from app.matching.representation import clean, embed_components
from app.resume import profile as profile_ops
from app.resume.extract import ExtractedText, ExtractionError, extract_document
from app.resume.parsed import PARSER_VERSION, ParsedResume
from app.resume.parser import parse_resume
from app.resume.storage import StorageError, StorageNotFoundError, get_storage, read_bounded
from app.resume.validation import CONTENT_TYPES, MIB, DocumentKind
from app.services.common import utcnow
from app.services.notifications import NotificationService
from app.workers.tasks import RetryableError, TaskContext, TaskFailure

logger = logging.getLogger(__name__)

E_EMBEDDING = "EMBEDDING_UNAVAILABLE"
EMBEDDING_ROLE_CHARS = 200
EMBEDDING_SKILL_CHARS = 400
EMBEDDING_PROSE_CHARS = 1200
RETRY_DELAY_SECONDS = 3.0

_KIND_BY_CONTENT_TYPE = {v: k for k, v in CONTENT_TYPES.items()}


@dataclass(slots=True)
class Analysis:
    """Result of the CPU-bound part of the pipeline (no database involved)."""

    extracted: ExtractedText
    parsed: ParsedResume

    @property
    def parsed_data(self) -> dict[str, Any]:
        return self.parsed.to_dict()


@dataclass(slots=True)
class LoadedResume:
    resume_id: uuid.UUID
    document_id: uuid.UUID
    storage_key: str
    kind: DocumentKind
    candidate_id: uuid.UUID
    candidate_user_id: uuid.UUID | None


def kind_for_content_type(content_type: str) -> DocumentKind:
    try:
        return _KIND_BY_CONTENT_TYPE[content_type]
    except KeyError as exc:
        raise TaskFailure("UNSUPPORTED_DOCUMENT", "The stored file type is not supported.") from exc


# --- CPU-bound steps ---------------------------------------------------------------------------------------------------


async def analyze(
    data: bytes, kind: DocumentKind, on_stage: Callable[[str], Awaitable[None]] | None = None
) -> Analysis:
    """Extract text (thread + timeout) and parse it. ``on_stage`` is told when each step starts. Raises
    :class:`ExtractionError` with a safe code / message."""
    settings = get_settings()
    if on_stage:
        await on_stage("extracting text")
    extracted = await extract_document(data, kind, max_chars=settings.max_resume_text_chars)
    if on_stage:
        await on_stage("parsing")
    parsed = await asyncio.to_thread(parse_resume, extracted.text, links=extracted.links)
    return Analysis(extracted=extracted, parsed=parsed)


def embedding_components(parsed: ParsedResume, text: str) -> dict[str, str]:
    """Bounded role / skills / prose components (same three aligned components as the candidate representation)."""
    titles = [e.title for e in parsed.experiences if e.title][:4]
    role = clean(". ".join(p for p in (parsed.headline, ", ".join(titles)) if p), EMBEDDING_ROLE_CHARS)
    skills = clean(", ".join(s.name for s in parsed.skills), EMBEDDING_SKILL_CHARS)
    descriptions = " ".join(e.description or "" for e in parsed.experiences[:4])
    edu = " ".join(" ".join(p for p in (ed.degree, ed.field_of_study) if p) for ed in parsed.educations[:3])
    prose = clean(f"{parsed.summary or ''} {descriptions} {edu}", EMBEDDING_PROSE_CHARS)
    if not (role or skills or prose):  # the layout defeated the parser: fall back to the head of the raw text
        prose = clean(text, EMBEDDING_PROSE_CHARS)
    return {"role": role, "skills": skills, "prose": prose}


async def embed_resume(parsed: ParsedResume, text: str) -> list[float]:
    """Embedding of the bounded excerpt. Raises :class:`EmbeddingError` if the model cannot produce one."""
    vector = await embed_components(embedding_components(parsed, text))
    return [float(x) for x in vector.tolist()]


# --- persistence ------------------------------------------------------------------------------------------------------------


def result_values(
    analysis: Analysis, *, embedding: list[float] | None, duration_ms: int, embedding_error: bool
) -> dict[str, Any]:
    emb = get_embedder() if embedding is not None else None
    return {
        "status": ProcessingStatus.COMPLETED,
        "finished_at": utcnow(),
        "duration_ms": duration_ms,
        "parser_version": PARSER_VERSION,
        "extracted_text": analysis.extracted.text,
        "text_char_count": len(analysis.extracted.text),
        "page_count": analysis.extracted.page_count,
        "was_truncated": analysis.extracted.was_truncated,
        "parsed_data": analysis.parsed_data,
        "embedding": embedding,
        "embedding_model": emb.name if emb else None,
        "embedding_version": emb.version if emb else None,
        "error_code": E_EMBEDDING if embedding_error else None,
        "error_message": (
            "The text was extracted, but the semantic embedding could not be generated; matching will use your profile data."
            if embedding_error
            else None
        ),
    }


async def upsert_result(
    session: AsyncSession,
    resume_id: uuid.UUID,
    document_id: uuid.UUID,
    values: dict[str, Any],
    *,
    bump_attempts: bool = False,
) -> None:
    """Insert-or-update the single processing result of a résumé (idempotent)."""
    insert_values = {"resume_id": resume_id, "document_id": document_id, "attempts": 1, **values}
    stmt = pg_insert(ResumeProcessingResult).values(insert_values)
    update_set: dict[str, Any] = {"document_id": document_id, **{k: stmt.excluded[k] for k in values}}
    if bump_attempts:
        update_set["attempts"] = ResumeProcessingResult.attempts + 1
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[ResumeProcessingResult.resume_id], set_=update_set)
    )


async def load_resume(session: AsyncSession, resume_id: uuid.UUID) -> LoadedResume:
    row = (
        await session.execute(
            select(Resume.id, Resume.candidate_id, CandidateProfile.user_id)
            .join(CandidateProfile, CandidateProfile.id == Resume.candidate_id)
            .where(Resume.id == resume_id)
        )
    ).first()
    if row is None:
        raise TaskFailure("RESUME_NOT_FOUND", "This résumé no longer exists.")
    doc = (
        await session.execute(
            select(ResumeDocument)
            .where(ResumeDocument.resume_id == resume_id)
            .order_by(ResumeDocument.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise TaskFailure("DOCUMENT_MISSING", "No file is attached to this résumé.")
    return LoadedResume(
        resume_id, doc.id, doc.storage_key, kind_for_content_type(doc.content_type), row[1], row[2]
    )


async def mark_started(session: AsyncSession, loaded: LoadedResume) -> None:
    await session.execute(
        update(Resume).where(Resume.id == loaded.resume_id).values(status=ResumeStatus.PROCESSING)
    )
    await upsert_result(
        session,
        loaded.resume_id,
        loaded.document_id,
        {
            "status": ProcessingStatus.PROCESSING,
            "started_at": utcnow(),
            "finished_at": None,
            "error_code": None,
            "error_message": None,
        },
        bump_attempts=True,
    )
    await session.commit()


async def record_failure(
    ctx: TaskContext, loaded: LoadedResume, code: str, message: str, started: float, *, notify: bool = True
) -> None:
    """Persist FAILED state + notify the owner. Must never raise (it runs while another error is propagating)."""
    try:
        async with ctx.sessionmaker() as s:
            await s.execute(
                update(Resume).where(Resume.id == loaded.resume_id).values(status=ResumeStatus.FAILED)
            )
            await upsert_result(
                s,
                loaded.resume_id,
                loaded.document_id,
                {
                    "status": ProcessingStatus.FAILED,
                    "finished_at": utcnow(),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error_code": code[:50],
                    "error_message": message[:500],
                },
            )
            if notify and loaded.candidate_user_id is not None:
                await NotificationService(s).stage(
                    loaded.candidate_user_id,
                    NotificationType.RESUME_FAILED,
                    "Résumé could not be processed",
                    message,
                    resume_id=loaded.resume_id,
                    dedupe_key=f"resume-failed:{loaded.resume_id}:{ctx.task_id}",
                )
            await s.commit()
    except Exception as exc:  # pragma: no cover - last-resort guard
        logger.error(
            "could not record résumé failure",
            extra={"resume_id": str(loaded.resume_id), "error": type(exc).__name__},
        )


async def get_dispatcher(ctx: TaskContext) -> tuple[Any, Any]:
    """``(dispatcher, close)`` for enqueueing follow-up tasks from inside a task."""
    existing = ctx.extra.get("dispatcher")
    if existing is not None:
        return existing, _noop
    from app.workers.dispatch import build_dispatcher

    return await build_dispatcher()


async def _noop() -> None:
    return None


# --- the handler -----------------------------------------------------------------------------------------------------------------


async def run_process_resume(ctx: TaskContext) -> dict[str, Any]:
    settings = get_settings()
    resume_id = uuid.UUID(str(ctx.params["resume_id"]))
    started = time.monotonic()

    await ctx.progress(5, "loading document")
    async with ctx.sessionmaker() as s:
        loaded = await load_resume(s, resume_id)
        await mark_started(s, loaded)

    try:
        try:
            data = await read_bounded(
                get_storage(), loaded.storage_key, int(settings.max_resume_mb * MIB * 1.05)
            )
        except StorageNotFoundError as exc:
            raise TaskFailure(
                "FILE_MISSING", "The stored file could not be found. Please upload the résumé again."
            ) from exc
        except StorageError as exc:
            raise TaskFailure("FILE_UNREADABLE", "The stored file could not be read.") from exc
        except OSError as exc:
            raise RetryableError("storage temporarily unavailable") from exc

        stages = {"extracting text": 20, "parsing": 45}

        async def on_stage(stage: str) -> None:
            await ctx.progress(stages[stage], stage)

        try:
            analysis = await analyze(data, loaded.kind, on_stage)
        except ExtractionError as exc:
            raise TaskFailure(exc.code, exc.message) from exc

        await ctx.progress(60, "resolving skills")
        async with ctx.sessionmaker() as s:
            resolved = await profile_ops.resolve_skills(s, (sk.name for sk in analysis.parsed.skills))

        await ctx.progress(75, "embedding")
        embedding: list[float] | None = None
        embedding_failed = False
        try:
            embedding = await embed_resume(analysis.parsed, analysis.extracted.text)
        except EmbeddingError:
            embedding_failed = True

        await ctx.progress(88, "saving")
        will_retry = embedding_failed and ctx.attempt < settings.task_max_attempts
        duration_ms = int((time.monotonic() - started) * 1000)
        suggested = await _save_success(
            ctx, loaded, analysis, resolved, embedding, embedding_failed, duration_ms, notify=not will_retry
        )
        if will_retry:
            raise RetryableError("embedding model unavailable", delay_seconds=RETRY_DELAY_SECONDS)

        await ctx.progress(95, "refreshing candidate profile index")
        index_refreshed = await _refresh_index(ctx, loaded)
    except TaskFailure as exc:
        await record_failure(ctx, loaded, exc.code, exc.message, started)
        raise
    except RetryableError:
        if (
            ctx.attempt >= settings.task_max_attempts
        ):  # the worker is about to give up: do not leave the résumé "processing"
            await record_failure(
                ctx,
                loaded,
                "TEMPORARY_FAILURE",
                "Processing could not be completed because a required service was unavailable. Please try again later.",
                started,
            )
        raise
    except asyncio.CancelledError:
        await asyncio.shield(
            record_failure(ctx, loaded, "TIMEOUT", "The operation took too long and was stopped.", started)
        )
        raise
    except Exception:
        await record_failure(
            ctx,
            loaded,
            "INTERNAL_ERROR",
            "An unexpected error occurred while processing this résumé.",
            started,
        )
        raise

    return {
        "resume_id": str(resume_id),
        "status": ResumeStatus.PROCESSED.value,
        "skills_found": len(analysis.parsed.skills),
        "skills_suggested": suggested,
        "pages": analysis.extracted.page_count,
        "characters": len(analysis.extracted.text),
        "truncated": analysis.extracted.was_truncated,
        "embedding": embedding is not None,
        "index_refreshed": index_refreshed,
        "warnings": analysis.parsed.warnings,
    }


async def _save_success(
    ctx: TaskContext,
    loaded: LoadedResume,
    analysis: Analysis,
    resolved: dict[str, Skill],
    embedding: list[float] | None,
    embedding_failed: bool,
    duration_ms: int,
    *,
    notify: bool,
) -> int:
    """One transaction: result row, résumé status, skill suggestions and the in-app notification."""
    suggestions = [(resolved[sk.name], sk.confidence) for sk in analysis.parsed.skills if sk.name in resolved]
    async with ctx.sessionmaker() as s:
        exists = await s.scalar(select(Resume.id).where(Resume.id == loaded.resume_id).with_for_update())
        if exists is None:
            raise TaskFailure("RESUME_NOT_FOUND", "This résumé was deleted while it was being processed.")
        await upsert_result(
            s,
            loaded.resume_id,
            loaded.document_id,
            result_values(
                analysis, embedding=embedding, duration_ms=duration_ms, embedding_error=embedding_failed
            ),
        )
        await s.execute(
            update(Resume).where(Resume.id == loaded.resume_id).values(status=ResumeStatus.PROCESSED)
        )
        suggested = await profile_ops.merge_skill_suggestions(s, loaded.candidate_id, suggestions)
        if notify and loaded.candidate_user_id is not None:
            await NotificationService(s).stage(
                loaded.candidate_user_id,
                NotificationType.RESUME_PROCESSED,
                "Résumé processed",
                "Your résumé was analysed. Review the suggested skills and details before applying them to your profile.",
                resume_id=loaded.resume_id,
                dedupe_key=f"resume-processed:{loaded.resume_id}:{loaded.document_id}",
            )
        await s.commit()
    return suggested


async def _refresh_index(ctx: TaskContext, loaded: LoadedResume) -> bool:
    """Update the candidate's embedding / search text and queue matching. Failure here must not fail the résumé."""
    dispatcher, close = await get_dispatcher(ctx)
    try:
        async with ctx.sessionmaker() as s:
            candidate = await s.get(CandidateProfile, loaded.candidate_id)
            if candidate is None:
                return False
            await profile_ops.refresh_after_change(
                s, candidate, dispatcher=dispatcher, cache=None, user_id=ctx.created_by_id
            )
        await ctx.cache.invalidate(CacheDomain.CANDIDATES, CacheDomain.MATCHES)
        return True
    except Exception as exc:
        logger.error(
            "candidate index refresh failed",
            extra={"candidate_id": str(loaded.candidate_id), "error": type(exc).__name__},
        )
        return False
    finally:
        await close()
