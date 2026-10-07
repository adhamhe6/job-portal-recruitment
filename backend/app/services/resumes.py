"""Résumé service: upload (stream → validate → store), status, authorized download, delete / primary / reprocess,
extracted-data review and bulk import. Authorization lives here (never in the routes): a résumé is visible to its owner
and to staff with FULL access to the candidate (applicant / sourced); marketplace-only access reveals nothing and every
other caller gets 404.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import quote

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache
from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError, ServiceUnavailableError, ValidationFailure
from app.core.security import Role
from app.db.models import (
    Application,
    BackgroundTask,
    BulkImportBatch,
    BulkImportItem,
    CandidateProfile,
    CandidateSource,
    ImportItemStatus,
    ProcessingStatus,
    Resume,
    ResumeDocument,
    ResumeProcessingResult,
    ResumeStatus,
    TaskStatus,
    TaskType,
    User,
)
from app.resume import profile as profile_ops
from app.resume import review
from app.resume.storage import StorageError, get_storage, iter_chunks, new_resume_key
from app.resume.validation import iter_upload, receive_upload, sanitize_filename
from app.schemas.common import TaskRef
from app.schemas.resume import (
    ApplyRequest,
    ApplyResult,
    BulkImportAccepted,
    BulkImportBatchDetail,
    BulkImportBatchOut,
    BulkImportCounts,
    BulkImportItemOut,
    ExtractedPatch,
    ExtractedResume,
    ProcessingOut,
    RejectedFile,
    ResumeOut,
    ResumeUploadOut,
)
from app.services.access import CandidateAccess, candidate_access_for, is_admin, require_company
from app.services.common import paginate, record_audit
from app.services.tasks import Dispatcher, TaskService

logger = logging.getLogger(__name__)

MAX_RESUMES_PER_CANDIDATE = 25
QUEUE_DOWN_MESSAGE = (
    "Your file was saved, but processing could not be started right now. "
    "Use POST /resumes/{id}/process to try again in a moment."
)

Mode = Literal["view", "owner", "edit"]


class UploadLike(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1, /) -> bytes: ...


@dataclass(slots=True)
class Download:
    media_type: str
    headers: dict[str, str]
    chunks: AsyncIterator[bytes]


@dataclass(slots=True)
class _Loaded:
    resume: Resume
    candidate: CandidateProfile
    is_owner: bool


def content_disposition(filename: str, *, inline: bool) -> str:
    """RFC 6266 header with an ASCII fallback and the UTF-8 form of the (already sanitised) display name."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", ascii_name).strip() or "resume"
    return f"{'inline' if inline else 'attachment'}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


class ResumeService:
    def __init__(
        self, session: AsyncSession, dispatcher: Dispatcher | None = None, cache: Cache | None = None
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.cache = cache

    # --- loading + authorization ---------------------------------------------------------------------------------------------
    async def _own_profile(self, user: User) -> CandidateProfile:
        profile = (
            await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
        ).scalar_one_or_none()
        if profile is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        return profile

    async def _load(self, user: User, resume_id: uuid.UUID, *, mode: Mode) -> _Loaded:
        """Everything that is not allowed reads as *not found*: ids cannot be probed."""
        not_found = NotFoundError("Résumé not found", code="RESUME_NOT_FOUND")
        resume = await self.session.get(Resume, resume_id)
        if resume is None:
            raise not_found
        candidate = await self.session.get(CandidateProfile, resume.candidate_id)
        if candidate is None:
            raise not_found
        is_owner = candidate.user_id is not None and candidate.user_id == user.id
        if mode == "owner":
            allowed = is_owner
        elif mode == "edit":
            allowed = is_owner or (
                user.role == Role.RECRUITER
                and candidate.source == CandidateSource.IMPORTED
                and candidate.sourced_by_company_id is not None
                and candidate.sourced_by_company_id == user.company_id
            )
        else:
            allowed = (
                is_owner or await candidate_access_for(self.session, user, candidate) == CandidateAccess.FULL
            )
        if not allowed:
            raise not_found
        return _Loaded(resume, candidate, is_owner)

    # --- read models -----------------------------------------------------------------------------------------------------------------
    async def _outs(self, loaded: Sequence[tuple[Resume, CandidateProfile]]) -> list[ResumeOut]:
        if not loaded:
            return []
        ids = [r.id for r, _ in loaded]
        docs: dict[uuid.UUID, ResumeDocument] = {}
        for d in (
            await self.session.execute(
                select(ResumeDocument)
                .where(ResumeDocument.resume_id.in_(ids))
                .order_by(ResumeDocument.created_at.desc())
            )
        ).scalars():
            docs.setdefault(d.resume_id, d)
        res = ResumeProcessingResult
        results = {
            row.resume_id: row
            for row in (
                await self.session.execute(
                    select(
                        res.resume_id,
                        res.status,
                        res.attempts,
                        res.started_at,
                        res.finished_at,
                        res.duration_ms,
                        res.parser_version,
                        res.page_count,
                        res.text_char_count,
                        res.was_truncated,
                        res.embedding.is_not(None).label("has_embedding"),
                        res.embedding_model,
                        res.embedding_version,
                        res.error_code,
                        res.error_message,
                    ).where(res.resume_id.in_(ids))
                )
            ).all()
        }
        keys = {f"process-resume:{i}": i for i in ids}
        stmt = select(BackgroundTask).where(
            BackgroundTask.type == TaskType.PROCESS_RESUME, BackgroundTask.dedupe_key.in_(list(keys))
        )
        creators = {c.user_id for _, c in loaded if c.user_id is not None}
        if creators and all(c.user_id is not None for _, c in loaded):
            stmt = stmt.where(
                BackgroundTask.created_by_id.in_(creators)
            )  # registered candidates' tasks: use the creator index
        tasks: dict[uuid.UUID, BackgroundTask] = {}
        for t in (await self.session.execute(stmt.order_by(BackgroundTask.created_at.desc()))).scalars():
            tasks.setdefault(keys[t.dedupe_key or ""], t)

        outs: list[ResumeOut] = []
        for resume, _ in loaded:
            doc = docs[resume.id]
            task = tasks.get(resume.id)
            outs.append(
                ResumeOut(
                    id=resume.id,
                    candidate_id=resume.candidate_id,
                    status=resume.status.value,
                    is_primary=resume.is_primary,
                    original_filename=doc.original_filename,
                    content_type=doc.content_type,
                    size_bytes=doc.size_bytes,
                    sha256=doc.sha256,
                    created_at=resume.created_at,
                    updated_at=resume.updated_at,
                    task_id=self._queued_id(task),
                    processing=self._processing(results.get(resume.id), task),
                )
            )
        return outs

    @staticmethod
    def _queued_id(task: BackgroundTask | None) -> uuid.UUID | None:
        """A task that never reached the queue cannot be polled to completion, so it is not offered as ``task_id``."""
        if task is None or (task.status == TaskStatus.FAILED and task.error_code == "QUEUE_UNAVAILABLE"):
            return None
        return task.id

    @classmethod
    def _processing(cls, result: Any, task: BackgroundTask | None) -> ProcessingOut:
        out = ProcessingOut()
        if task is not None:
            out.task_id, out.task_status, out.stage, out.progress = (
                cls._queued_id(task),
                task.status.value,
                task.stage,
                task.progress,
            )
            out.started_at, out.finished_at = task.started_at, task.finished_at
            out.attempts = task.attempts
            if task.status == TaskStatus.FAILED:
                out.error_code, out.error_message = task.error_code, task.error_message
        if result is not None:
            out.attempts = result.attempts
            out.started_at, out.finished_at = (
                result.started_at or out.started_at,
                result.finished_at or out.finished_at,
            )
            out.duration_ms, out.parser_version, out.page_count = (
                result.duration_ms,
                result.parser_version,
                result.page_count,
            )
            out.text_char_count, out.was_truncated = result.text_char_count, bool(result.was_truncated)
            out.has_embedding, out.embedding_model, out.embedding_version = (
                bool(result.has_embedding),
                result.embedding_model,
                result.embedding_version,
            )
            if result.error_code or result.status == ProcessingStatus.FAILED:
                out.error_code, out.error_message = result.error_code, result.error_message
        return out

    async def _out(self, resume: Resume, candidate: CandidateProfile) -> ResumeOut:
        return (await self._outs([(resume, candidate)]))[0]

    # --- upload ---------------------------------------------------------------------------------------------------------------------------
    async def upload(
        self,
        user: User,
        chunks: AsyncIterator[bytes],
        *,
        filename: str | None,
        content_type: str | None,
        set_primary: bool = True,
    ) -> tuple[ResumeUploadOut, int]:
        """Validate while streaming, store, create the rows and queue processing. Returns ``(body, http_status)``:
        202 for a new upload, 200 when the identical file already exists for this candidate."""
        candidate = await self._own_profile(user)
        upload = await receive_upload(chunks, filename=filename, declared_content_type=content_type)
        storage = get_storage()
        key: str | None = None
        try:
            existing = (
                await self.session.execute(
                    select(Resume)
                    .join(ResumeDocument, ResumeDocument.resume_id == Resume.id)
                    .where(Resume.candidate_id == candidate.id, ResumeDocument.sha256 == upload.sha256)
                    .order_by(Resume.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return await self._duplicate(user, candidate, existing, set_primary)

            count = await self.session.scalar(
                select(func.count()).select_from(Resume).where(Resume.candidate_id == candidate.id)
            )
            if (count or 0) >= MAX_RESUMES_PER_CANDIDATE:
                raise ConflictError(
                    f"You can keep at most {MAX_RESUMES_PER_CANDIDATE} résumés. Delete one you no longer need first.",
                    code="RESUME_LIMIT_REACHED",
                )
            key = new_resume_key()
            await storage.put(key, upload.file)
            try:
                resume = await self._create_rows(user, candidate, key, upload, set_primary)
            except BaseException:
                await self.session.rollback()
                await storage.delete(key)
                raise
        finally:
            upload.close()

        _, message = await self._enqueue(user, resume)
        await self.session.refresh(resume)
        out = await self._out(resume, candidate)
        return ResumeUploadOut(**out.model_dump(), message=message, duplicate=False), 202

    async def _create_rows(
        self, user: User, candidate: CandidateProfile, key: str, upload: Any, set_primary: bool
    ) -> Resume:
        await self.session.execute(
            select(CandidateProfile.id).where(CandidateProfile.id == candidate.id).with_for_update()
        )  # serialise per candidate
        has_primary = await self.session.scalar(
            select(exists().where(Resume.candidate_id == candidate.id, Resume.is_primary.is_(True)))
        )
        make_primary = set_primary or not has_primary
        if make_primary:
            await self.session.execute(
                update(Resume)
                .where(Resume.candidate_id == candidate.id, Resume.is_primary.is_(True))
                .values(is_primary=False)
            )
        resume = Resume(
            candidate_id=candidate.id,
            uploaded_by_id=user.id,
            status=ResumeStatus.UPLOADED,
            is_primary=make_primary,
        )
        self.session.add(resume)
        await self.session.flush()
        self.session.add(
            ResumeDocument(
                resume_id=resume.id,
                storage_key=key,
                original_filename=upload.filename,
                content_type=upload.content_type,
                size_bytes=upload.size,
                sha256=upload.sha256,
            )
        )
        await self.session.commit()
        return resume

    async def _duplicate(
        self, user: User, candidate: CandidateProfile, existing: Resume, set_primary: bool
    ) -> tuple[ResumeUploadOut, int]:
        """The identical file was uploaded before: no second copy. A FAILED one is retried; a processed one is returned as is."""
        if set_primary and not existing.is_primary:
            await self._make_primary(candidate, existing)
        message: str | None = None
        status = 200
        if existing.status == ResumeStatus.FAILED:
            _, message = await self._enqueue(user, existing)
            status = 202
        await self.session.refresh(existing)
        out = await self._out(existing, candidate)
        return ResumeUploadOut(**out.model_dump(), message=message, duplicate=True), status

    async def _enqueue(self, user: User, resume: Resume) -> tuple[uuid.UUID | None, str | None]:
        """Queue processing. If the queue is down the résumé stays as it is and the caller gets a clear message."""
        if self.dispatcher is None:
            return None, QUEUE_DOWN_MESSAGE
        try:
            task, _ = await TaskService(self.session).submit(
                TaskType.PROCESS_RESUME,
                {"resume_id": str(resume.id)},
                self.dispatcher,
                created_by_id=user.id,
                dedupe_key=f"process-resume:{resume.id}",
            )
        except ServiceUnavailableError:
            logger.warning(
                "résumé processing not queued (queue unavailable)", extra={"resume_id": str(resume.id)}
            )
            return None, QUEUE_DOWN_MESSAGE
        return task.id, None

    # --- reads ---------------------------------------------------------------------------------------------------------------------------------
    async def list_mine(self, user: User, *, page: int, page_size: int) -> tuple[list[ResumeOut], int]:
        candidate = await self._own_profile(user)
        stmt = (
            select(Resume)
            .where(Resume.candidate_id == candidate.id)
            .order_by(Resume.is_primary.desc(), Resume.created_at.desc(), Resume.id)
        )
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size)
        return await self._outs([(r, candidate) for r in rows]), total

    async def get(self, user: User, resume_id: uuid.UUID) -> ResumeOut:
        loaded = await self._load(user, resume_id, mode="view")
        return await self._out(loaded.resume, loaded.candidate)

    async def download(self, user: User, resume_id: uuid.UUID, *, inline: bool = False) -> Download:
        loaded = await self._load(user, resume_id, mode="view")
        doc = (
            await self.session.execute(
                select(ResumeDocument)
                .where(ResumeDocument.resume_id == resume_id)
                .order_by(ResumeDocument.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise NotFoundError("Résumé file not found", code="RESUME_FILE_NOT_FOUND")
        try:
            handle = get_storage().open(doc.storage_key)
        except StorageError as exc:
            raise NotFoundError("Résumé file not found", code="RESUME_FILE_NOT_FOUND") from exc
        if not loaded.is_owner:  # releasing a candidate's file to staff is an auditable event
            record_audit(
                self.session,
                actor_id=user.id,
                action="resume.downloaded",
                entity_type="resume",
                entity_id=resume_id,
                company_id=user.company_id,
            )
            await self.session.commit()
        as_inline = (
            inline and doc.content_type == "application/pdf"
        )  # only PDFs are ever previewed in the browser
        headers = {
            "Content-Disposition": content_disposition(doc.original_filename, inline=as_inline),
            "Content-Length": str(doc.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        }
        return Download(media_type=doc.content_type, headers=headers, chunks=iter_chunks(handle))

    # --- owner operations ----------------------------------------------------------------------------------------------------------------------------
    async def _make_primary(self, candidate: CandidateProfile, resume: Resume) -> None:
        await self.session.execute(
            select(CandidateProfile.id).where(CandidateProfile.id == candidate.id).with_for_update()
        )
        await self.session.execute(
            update(Resume)
            .where(Resume.candidate_id == candidate.id, Resume.is_primary.is_(True))
            .values(is_primary=False)
        )
        await self.session.execute(update(Resume).where(Resume.id == resume.id).values(is_primary=True))
        await self.session.commit()
        await self.session.refresh(resume)
        await self._after_change(candidate)

    async def _after_change(self, candidate: CandidateProfile, user: User | None = None) -> None:
        await profile_ops.refresh_after_change(
            self.session,
            candidate,
            dispatcher=self.dispatcher,
            cache=self.cache,
            user_id=user.id if user else None,
        )

    async def set_primary(self, user: User, resume_id: uuid.UUID) -> ResumeOut:
        loaded = await self._load(user, resume_id, mode="owner")
        if not loaded.resume.is_primary:
            await self._make_primary(loaded.candidate, loaded.resume)
        return await self._out(loaded.resume, loaded.candidate)

    async def reprocess(self, user: User, resume_id: uuid.UUID) -> TaskRef:
        loaded = await self._load(user, resume_id, mode="edit")
        task, _ = await TaskService(self.session).submit(
            TaskType.PROCESS_RESUME,
            {"resume_id": str(resume_id)},
            self._require_dispatcher(),
            created_by_id=user.id,
            company_id=user.company_id if not loaded.is_owner else None,
            dedupe_key=f"process-resume:{resume_id}",
        )
        return TaskRef(task_id=str(task.id), status=task.status.value)

    def _require_dispatcher(self) -> Dispatcher:
        if self.dispatcher is None:
            raise ServiceUnavailableError("Job queue unavailable")
        return self.dispatcher

    async def delete(self, user: User, resume_id: uuid.UUID) -> None:
        loaded = await self._load(user, resume_id, mode="owner")
        candidate, resume = loaded.candidate, loaded.resume
        in_use = await self.session.scalar(select(exists().where(Application.resume_id == resume_id)))
        if in_use:
            raise ConflictError(
                "This résumé is attached to one or more applications and cannot be deleted.",
                code="RESUME_IN_USE",
            )
        keys = list(
            (
                await self.session.execute(
                    select(ResumeDocument.storage_key).where(ResumeDocument.resume_id == resume_id)
                )
            ).scalars()
        )
        was_primary = resume.is_primary
        try:
            await self.session.execute(
                select(CandidateProfile.id).where(CandidateProfile.id == candidate.id).with_for_update()
            )
            await self.session.execute(
                delete(Resume).where(Resume.id == resume_id)
            )  # documents + result cascade in the database
            if was_primary:
                newest = await self.session.scalar(
                    select(Resume.id)
                    .where(Resume.candidate_id == candidate.id)
                    .order_by(Resume.created_at.desc(), Resume.id)
                    .limit(1)
                )
                if newest is not None:
                    await self.session.execute(
                        update(Resume).where(Resume.id == newest).values(is_primary=True)
                    )
            await self.session.commit()
        except (
            IntegrityError
        ) as exc:  # an application referenced it between the check and the delete (FK is RESTRICT)
            await self.session.rollback()
            raise ConflictError(
                "This résumé is attached to one or more applications and cannot be deleted.",
                code="RESUME_IN_USE",
            ) from exc
        storage = get_storage()
        for key in keys:
            try:
                await storage.delete(key)
            except StorageError:
                logger.error("stored résumé file could not be removed", extra={"resume_id": str(resume_id)})
        await self._after_change(candidate, user)

    # --- extracted data -------------------------------------------------------------------------------------------------------------------------------
    async def _processed(self, loaded: _Loaded) -> ResumeProcessingResult:
        result = (
            await self.session.execute(
                select(ResumeProcessingResult).where(ResumeProcessingResult.resume_id == loaded.resume.id)
            )
        ).scalar_one_or_none()
        if result is None or result.parsed_data is None or loaded.resume.status != ResumeStatus.PROCESSED:
            raise ConflictError("This résumé has not been processed yet.", code="RESUME_NOT_PROCESSED")
        return result

    async def extracted(self, user: User, resume_id: uuid.UUID) -> ExtractedResume:
        loaded = await self._load(user, resume_id, mode="edit")
        result = await self._processed(loaded)
        assert result.parsed_data is not None
        return await review.build_extracted(
            self.session, resume_id=resume_id, candidate_id=loaded.candidate.id, parsed=result.parsed_data
        )

    async def patch_extracted(
        self, user: User, resume_id: uuid.UUID, patch: ExtractedPatch
    ) -> ExtractedResume:
        loaded = await self._load(user, resume_id, mode="edit")
        result = await self._processed(loaded)
        assert result.parsed_data is not None
        result.parsed_data = await review.apply_patch(self.session, result.parsed_data, patch)
        record_audit(
            self.session,
            actor_id=user.id,
            action="resume.extracted_corrected",
            entity_type="resume",
            entity_id=resume_id,
            company_id=user.company_id,
        )
        await self.session.commit()
        return await review.build_extracted(
            self.session, resume_id=resume_id, candidate_id=loaded.candidate.id, parsed=result.parsed_data
        )

    async def apply_extracted(self, user: User, resume_id: uuid.UUID, request: ApplyRequest) -> ApplyResult:
        loaded = await self._load(user, resume_id, mode="edit")
        result = await self._processed(loaded)
        assert result.parsed_data is not None
        outcome = await review.apply_extracted(
            self.session, candidate=loaded.candidate, parsed=result.parsed_data, request=request
        )
        record_audit(
            self.session,
            actor_id=user.id,
            action="resume.extracted_applied",
            entity_type="resume",
            entity_id=resume_id,
            company_id=user.company_id,
            meta={"applied": outcome.applied, "fields": outcome.fields_applied},
        )
        await self.session.commit()
        await self._after_change(loaded.candidate, user)
        return outcome

    # --- bulk import ----------------------------------------------------------------------------------------------------------------------------------
    async def bulk_create(self, user: User, uploads: Sequence[UploadLike]) -> tuple[BulkImportAccepted, int]:
        company_id = require_company(user)
        settings = get_settings()
        if not uploads:
            raise ValidationFailure("Attach at least one file in the `files` field.", code="NO_FILES")
        if len(uploads) > settings.max_bulk_import_files:
            raise ValidationFailure(
                f"At most {settings.max_bulk_import_files} files can be imported at once.",
                code="TOO_MANY_FILES",
                details={"max_files": settings.max_bulk_import_files, "received": len(uploads)},
            )
        storage = get_storage()
        rejected: list[RejectedFile] = []
        items: list[BulkImportItem] = []
        stored: list[str] = []
        try:
            for up in uploads:  # one file at a time: spooled to disk, validated, stored — never all in memory
                display = sanitize_filename(up.filename)
                try:
                    valid = await receive_upload(
                        iter_upload(up), filename=up.filename, declared_content_type=up.content_type
                    )
                except AppError as exc:
                    rejected.append(RejectedFile(filename=display, reason=exc.message, code=exc.code))
                    continue
                try:
                    key = new_resume_key()
                    await storage.put(key, valid.file)
                    stored.append(key)
                    items.append(
                        BulkImportItem(
                            filename=valid.filename,
                            sha256=valid.sha256,
                            size_bytes=valid.size,
                            storage_key=key,
                        )
                    )
                finally:
                    valid.close()
            if not items:
                raise ValidationFailure(
                    "None of the files could be accepted.",
                    code="NO_VALID_FILES",
                    details={"rejected": [r.model_dump() for r in rejected]},
                )
            batch = BulkImportBatch(
                company_id=company_id, created_by_id=user.id, total_files=len(items), items=items
            )
            self.session.add(batch)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            for key in stored:
                await storage.delete(key)
            raise

        message: str | None = None
        tasks = TaskService(self.session)
        task, _ = await tasks.create(
            TaskType.BULK_RESUME_IMPORT,
            {"batch_id": str(batch.id)},
            created_by_id=user.id,
            company_id=company_id,
            dedupe_key=f"bulk-import:{batch.id}",
        )
        batch.task_id = task.id
        await self.session.commit()
        task_id: uuid.UUID | None = task.id
        try:
            await tasks.enqueue(task, self._require_dispatcher())
        except ServiceUnavailableError:
            task_id = None
            message = "The files were saved, but the import could not be queued right now. Retry with POST /resumes/bulk-imports/{id}/process."
        return BulkImportAccepted(
            batch_id=batch.id, task_id=task_id, accepted=len(items), rejected=rejected, message=message
        ), 202

    async def _load_batch(self, user: User, batch_id: uuid.UUID) -> BulkImportBatch:
        batch = await self.session.get(BulkImportBatch, batch_id)
        if batch is None or not (
            is_admin(user) or (user.company_id is not None and batch.company_id == user.company_id)
        ):
            raise NotFoundError("Import batch not found", code="BATCH_NOT_FOUND")
        return batch

    async def _batch_outs(self, batches: Sequence[BulkImportBatch]) -> list[BulkImportBatchOut]:
        if not batches:
            return []
        ids = [b.id for b in batches]
        counts: dict[uuid.UUID, dict[ImportItemStatus, int]] = defaultdict(dict)
        for bid, item_status, n in (
            await self.session.execute(
                select(BulkImportItem.batch_id, BulkImportItem.status, func.count())
                .where(BulkImportItem.batch_id.in_(ids))
                .group_by(BulkImportItem.batch_id, BulkImportItem.status)
            )
        ).all():
            counts[bid][item_status] = int(n)
        task_ids = [b.task_id for b in batches if b.task_id]
        tasks = (
            {
                t.id: t
                for t in (
                    await self.session.execute(select(BackgroundTask).where(BackgroundTask.id.in_(task_ids)))
                ).scalars()
            }
            if task_ids
            else {}
        )
        outs: list[BulkImportBatchOut] = []
        for b in batches:
            c = counts[b.id]
            task = tasks.get(b.task_id) if b.task_id else None
            if b.finished_at is not None:
                status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"] = "COMPLETED"
            elif task is not None and task.status == TaskStatus.FAILED:
                status = "FAILED"
            elif task is not None and task.status == TaskStatus.RUNNING:
                status = "RUNNING"
            else:
                status = "PENDING"
            outs.append(
                BulkImportBatchOut(
                    id=b.id,
                    status=status,
                    total_files=b.total_files,
                    counts=BulkImportCounts(
                        pending=c.get(ImportItemStatus.PENDING, 0),
                        created=c.get(ImportItemStatus.CREATED, 0),
                        duplicate=c.get(ImportItemStatus.DUPLICATE, 0),
                        failed=c.get(ImportItemStatus.FAILED, 0),
                    ),
                    task_id=b.task_id,
                    progress=task.progress if task else None,
                    created_by_id=b.created_by_id,
                    created_at=b.created_at,
                    finished_at=b.finished_at,
                )
            )
        return outs

    async def bulk_list(
        self, user: User, *, page: int, page_size: int
    ) -> tuple[list[BulkImportBatchOut], int]:
        stmt = select(BulkImportBatch).order_by(BulkImportBatch.created_at.desc(), BulkImportBatch.id)
        if not is_admin(user):
            stmt = stmt.where(BulkImportBatch.company_id == require_company(user))
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size)
        return await self._batch_outs(rows), total

    async def bulk_get(self, user: User, batch_id: uuid.UUID) -> BulkImportBatchDetail:
        batch = await self._load_batch(user, batch_id)
        (base,) = await self._batch_outs([batch])
        items = (
            await self.session.execute(
                select(BulkImportItem)
                .where(BulkImportItem.batch_id == batch_id)
                .order_by(BulkImportItem.created_at, BulkImportItem.id)
            )
        ).scalars()
        return BulkImportBatchDetail(
            **base.model_dump(),
            items=[
                BulkImportItemOut(
                    id=i.id,
                    filename=i.filename,
                    size_bytes=i.size_bytes,
                    status=i.status,
                    candidate_id=i.candidate_id,
                    resume_id=i.resume_id,
                    error_code=i.error_code,
                    error_message=i.error_message,
                )
                for i in items
            ],
        )

    async def bulk_reprocess(self, user: User, batch_id: uuid.UUID) -> TaskRef:
        batch = await self._load_batch(user, batch_id)
        if batch.finished_at is not None:
            raise ConflictError("This import has already finished.", code="BATCH_ALREADY_COMPLETED")
        tasks = TaskService(self.session)
        task, created = await tasks.create(
            TaskType.BULK_RESUME_IMPORT,
            {"batch_id": str(batch.id)},
            created_by_id=user.id,
            company_id=batch.company_id,
            dedupe_key=f"bulk-import:{batch.id}",
        )
        if created:
            batch.task_id = task.id
            await self.session.commit()
            await tasks.enqueue(task, self._require_dispatcher())
            await self.session.refresh(task)
        return TaskRef(task_id=str(task.id), status=task.status.value)
