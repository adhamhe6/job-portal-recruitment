"""Résumés: upload, status, authorized download, review of extracted data, and recruiter bulk import.

Uploads are never served statically: the file is only reachable through ``GET /resumes/{id}/file``, which re-checks
authorization on every request. Route handlers stay thin — validation, storage and access rules live in
``app.resume.*`` and ``app.services.resumes``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute

from app.api.dependencies import CacheDep, DispatcherDep, Pagination, SessionDep, require, upload_limit
from app.core.errors import AuthenticationError, PayloadTooLargeError
from app.core.security import Permission
from app.db.models import User
from app.resume.validation import bulk_body_limit, iter_upload, single_body_limit
from app.schemas.common import COMMON_ERRORS, ErrorResponse, Page, TaskRef
from app.schemas.resume import (
    ApplyRequest,
    ApplyResult,
    BulkImportAccepted,
    BulkImportBatchDetail,
    BulkImportBatchOut,
    ExtractedPatch,
    ExtractedResume,
    ResumeOut,
    ResumeUploadOut,
)
from app.services.resumes import ResumeService

router = APIRouter(prefix="/resumes", tags=["Resumes"], responses=COMMON_ERRORS)

UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    **COMMON_ERRORS,
    413: {"model": ErrorResponse, "description": "PAYLOAD_TOO_LARGE: the file (or its decompressed size) exceeds the limit"},
    415: {
        "model": ErrorResponse,
        "description": "UNSUPPORTED_MEDIA_TYPE: only PDF and DOCX are accepted; the content, extension and declared type must agree",
    },
    429: {"model": ErrorResponse, "description": "RATE_LIMITED: too many uploads"},
}

Uploader = Annotated[User, Depends(require(Permission.UPLOAD_RESUME))]
Importer = Annotated[User, Depends(require(Permission.IMPORT_RESUMES))]
Viewer = Annotated[User, Depends(require())]
RateLimit = Annotated[None, Depends(upload_limit)]


def _svc(session: SessionDep, dispatcher: DispatcherDep, cache: CacheDep) -> ResumeService:
    return ResumeService(session, dispatcher, cache)


Svc = Annotated[ResumeService, Depends(_svc)]


# --- request-body cap ------------------------------------------------------------------------------------------------


class _BodyTooLarge(Exception):
    pass


class _LimitedReceive:
    """ASGI ``receive`` wrapper that refuses more than ``limit`` body bytes, whatever the client declares."""

    def __init__(self, receive: Callable[[], Coroutine[Any, Any, Any]], limit: int) -> None:
        self._receive, self._limit, self._seen = receive, limit, 0
        self.exceeded = False

    async def __call__(self) -> Any:
        message = await self._receive()
        if message["type"] == "http.request":
            self._seen += len(message.get("body", b""))
            if self._seen > self._limit:
                self.exceeded = True
                raise _BodyTooLarge
        return message


def capped_route(limit: Callable[[], int]) -> type[APIRoute]:
    """Route class that rejects over-sized multipart bodies *before* the framework spools them.

    FastAPI parses ``UploadFile`` parameters before dependencies run, so without this an anonymous client could make the
    server buffer an arbitrarily large body. Anonymous requests are refused up front, ``Content-Length`` is checked, and the
    bytes actually received are counted (covers chunked uploads that declare no length).
    """

    class CappedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original = super().get_route_handler()

            async def handler(request: Request) -> Response:
                cap = limit()
                if "authorization" not in request.headers:
                    raise AuthenticationError("Not authenticated")
                declared = request.headers.get("content-length", "")
                too_large = PayloadTooLargeError(
                    "The upload is larger than allowed.", code="PAYLOAD_TOO_LARGE", details={"reason": "REQUEST_TOO_LARGE", "max_bytes": cap}
                )
                if declared.isdigit() and int(declared) > cap:
                    raise too_large
                guarded = _LimitedReceive(request.receive, cap)
                try:
                    return await original(Request(request.scope, guarded))
                except Exception:
                    if guarded.exceeded:
                        raise too_large from None
                    raise

            return handler

    return CappedRoute


def capped_post(path: str, limit: Callable[[], int], **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``@router.post`` for multipart endpoints, using :func:`capped_route` (decorators cannot set a route class)."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        router.add_api_route(path, fn, methods=["POST"], route_class_override=capped_route(limit), **kwargs)
        return fn

    return decorator


# --- bulk import (declared first: `/bulk-imports` must not be parsed as a `{resume_id}`) ----------------------------


@capped_post(
    "/bulk-imports",
    bulk_body_limit,
    response_model=BulkImportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk-import résumés (recruiters)",
    description=(
        "Upload up to `MAX_BULK_IMPORT_FILES` PDF / DOCX files as `multipart/form-data` (`files`, repeated; `files[]` is accepted too). "
        "Every file is validated like a single upload; **invalid files are reported per file in `rejected` and the valid ones are "
        "accepted**. A background task then creates one company-private candidate per new résumé, skipping duplicates (same file or "
        "same e-mail) and recording unreadable files as failed. Poll `GET /resumes/bulk-imports/{batch_id}`."
    ),
    responses={
        **UPLOAD_ERRORS,
        202: {
            "description": "Accepted",
            "content": {
                "application/json": {
                    "example": {
                        "batch_id": "3f2b8c0e-5c1a-4f64-9b6e-0d6d1b0a9f10",
                        "task_id": "7a1d2d0e-1f2b-4c33-b1f0-0d3f5f6a7b88",
                        "accepted": 2,
                        "rejected": [{"filename": "old-cv.doc", "reason": "Legacy Word (.doc) files are not supported.", "code": "UNSUPPORTED_MEDIA_TYPE"}],
                        "message": None,
                    }
                }
            },
        },
    },
)
async def bulk_import(
    user: Importer,
    _: RateLimit,
    svc: Svc,
    files: Annotated[list[UploadFile] | None, File(description="Résumé files (PDF or DOCX)")] = None,
    files_brackets: Annotated[list[UploadFile] | None, File(alias="files[]", include_in_schema=False)] = None,
) -> BulkImportAccepted:
    body, _code = await svc.bulk_create(user, [*(files or []), *(files_brackets or [])])
    return body


@router.get(
    "/bulk-imports",
    response_model=Page[BulkImportBatchOut],
    summary="My company's import batches",
    description="Newest first. Company-scoped: batches of other companies are never listed.",
)
async def list_bulk_imports(user: Importer, svc: Svc, p: Pagination) -> Page[BulkImportBatchOut]:
    items, total = await svc.bulk_list(user, page=p.page, page_size=p.page_size)
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.get(
    "/bulk-imports/{batch_id}",
    response_model=BulkImportBatchDetail,
    summary="Import batch with per-file outcomes",
    description="Counts by outcome (`pending` / `created` / `duplicate` / `failed`) and one item per accepted file. 404 for other companies' batches.",
)
async def get_bulk_import(batch_id: uuid.UUID, user: Importer, svc: Svc) -> BulkImportBatchDetail:
    return await svc.bulk_get(user, batch_id)


@router.post(
    "/bulk-imports/{batch_id}/process",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-queue an import that has not finished",
    description="Use when the queue was unavailable at upload time or a worker was lost. Only items still `pending` are processed (idempotent).",
)
async def reprocess_bulk_import(batch_id: uuid.UUID, user: Importer, svc: Svc) -> TaskRef:
    return await svc.bulk_reprocess(user, batch_id)


# --- single résumé ---------------------------------------------------------------------------------------------------------


@capped_post(
    "",
    single_body_limit,
    response_model=ResumeUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a résumé (candidates)",
    description=(
        "`multipart/form-data` with `file` (PDF or DOCX, size-limited while streaming) and optional `set_primary` (default `true`). "
        "The file type is decided by its **content** (magic bytes), not by the client's `Content-Type`; mismatching extension / "
        "content / declared type is rejected with 415, empty files with 422, oversize files with 413.\n\n"
        "Returns **202** with the résumé (`status = UPLOADED`) and a `task_id` to poll — processing (text extraction, parsing, skills, "
        "embedding) runs in the background. If the queue is unavailable the upload is still saved: `task_id` is `null`, `message` "
        "explains, and `POST /resumes/{id}/process` retries. Uploading the **identical file again** returns the existing résumé "
        "with **200** (`duplicate = true`) instead of creating another; a previously FAILED one is re-queued."
    ),
    responses={**UPLOAD_ERRORS, 200: {"model": ResumeUploadOut, "description": "The identical file was already uploaded; the existing résumé is returned"}},
)
async def upload_resume(
    user: Uploader,
    _: RateLimit,
    svc: Svc,
    response: Response,
    file: Annotated[UploadFile, File(description="The résumé: PDF (.pdf) or Word (.docx)")],
    set_primary: Annotated[bool, Form(description="Make this the primary résumé (used for matching and as the default for applications)")] = True,
) -> ResumeUploadOut:
    body, status_code = await svc.upload(
        user, iter_upload(file), filename=file.filename, content_type=file.content_type, set_primary=set_primary
    )
    response.status_code = status_code
    return body


@router.get(
    "",
    response_model=Page[ResumeOut],
    summary="My résumés",
    description="The signed-in candidate's résumés, primary first, with live processing status.",
)
async def list_resumes(user: Uploader, svc: Svc, p: Pagination) -> Page[ResumeOut]:
    items, total = await svc.list_mine(user, page=p.page, page_size=p.page_size)
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.get(
    "/{resume_id}",
    response_model=ResumeOut,
    summary="Résumé with processing status",
    description=(
        "Visible to the owner and to staff with **full** access to the candidate (applicants to your company's jobs, or candidates your "
        "company sourced). Marketplace-only access reveals nothing; everyone else gets 404. Includes the task stage / progress, "
        "`error_code` / `error_message` (safe, never document content), parser version, embedding model / version, durations, "
        "page and character counts and `was_truncated`."
    ),
)
async def get_resume(resume_id: uuid.UUID, user: Viewer, svc: Svc) -> ResumeOut:
    return await svc.get(user, resume_id)


@router.get(
    "/{resume_id}/file",
    summary="Download the résumé file",
    description=(
        "Streams the stored file after re-checking authorization. Served as an attachment with the sniffed content type, "
        "`X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`. `inline=true` previews a PDF in the browser; "
        "other types are always downloaded."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "The file",
            "content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}},
        }
    },
)
async def download_resume(
    resume_id: uuid.UUID, user: Viewer, svc: Svc, inline: Annotated[bool, Query(description="Preview PDFs inline")] = False
) -> StreamingResponse:
    dl = await svc.download(user, resume_id, inline=inline)
    return StreamingResponse(dl.chunks, media_type=dl.media_type, headers=dl.headers)


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a résumé (owner)",
    description=(
        "Deletes the rows and the stored file. **409 `RESUME_IN_USE`** if an application references it. If it was the primary "
        "résumé the newest remaining one becomes primary."
    ),
    responses={409: {"model": ErrorResponse, "description": "RESUME_IN_USE"}},
)
async def delete_resume(resume_id: uuid.UUID, user: Uploader, svc: Svc) -> Response:
    await svc.delete(user, resume_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{resume_id}/primary", response_model=ResumeOut, summary="Make this my primary résumé (owner)")
async def make_primary(resume_id: uuid.UUID, user: Uploader, svc: Svc) -> ResumeOut:
    return await svc.set_primary(user, resume_id)


@router.post(
    "/{resume_id}/process",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="(Re)process a résumé",
    description=(
        "Queues processing again (e.g. after a failure or when the queue was down at upload). Deduplicated: if a run is already "
        "pending or running its task is returned. Reprocessing is idempotent — suggestions are never duplicated. "
        "Owner, or the sourcing company's recruiter for an imported candidate."
    ),
    responses={503: {"model": ErrorResponse, "description": "The job queue is unavailable"}},
)
async def reprocess_resume(resume_id: uuid.UUID, user: Viewer, svc: Svc) -> TaskRef:
    return await svc.reprocess(user, resume_id)


# --- extracted data (review) ---------------------------------------------------------------------------------------------------


@router.get(
    "/{resume_id}/extracted",
    response_model=ExtractedResume,
    summary="Suggestions extracted from the résumé",
    description=(
        "What the parser found — contact details, summary, skills, experience, education, certifications, languages and years of "
        "experience — each with a confidence score, plus whether it is already on the profile. These are **suggestions**: nothing "
        "except unconfirmed skill suggestions touches the profile until you call `/apply`. Owner, or the sourcing company's recruiter "
        "for imported candidates (and only those). 409 `RESUME_NOT_PROCESSED` until processing has finished."
    ),
    responses={409: {"model": ErrorResponse, "description": "RESUME_NOT_PROCESSED"}},
)
async def get_extracted(resume_id: uuid.UUID, user: Viewer, svc: Svc) -> ExtractedResume:
    return await svc.extracted(user, resume_id)


@router.patch(
    "/{resume_id}/extracted",
    response_model=ExtractedResume,
    summary="Correct or remove suggestions before applying",
    description=(
        "Edit individual suggestions by `index` (`remove: true` hides one, other fields correct it). Only the stored suggestions "
        "change — the raw extracted text is never altered — and edited items are flagged `corrected`."
    ),
    responses={409: {"model": ErrorResponse, "description": "RESUME_NOT_PROCESSED"}},
)
async def patch_extracted(resume_id: uuid.UUID, data: ExtractedPatch, user: Viewer, svc: Svc) -> ExtractedResume:
    return await svc.patch_extracted(user, resume_id, data)


@router.post(
    "/{resume_id}/extracted/apply",
    response_model=ApplyResult,
    summary="Copy selected suggestions into the profile",
    description=(
        "Select suggestion indices per section (or `all`) and scalar `fields` to fill. Created rows have `source = RESUME`; skills "
        "are confirmed; duplicates are skipped; scalar profile fields are only filled when empty unless listed in `overwrite`. "
        "The response says what was applied and what was skipped (and why). The profile index and matches are refreshed afterwards."
    ),
    responses={409: {"model": ErrorResponse, "description": "RESUME_NOT_PROCESSED"}},
)
async def apply_extracted(resume_id: uuid.UUID, data: ApplyRequest, user: Viewer, svc: Svc) -> ApplyResult:
    return await svc.apply_extracted(user, resume_id, data)
