"""Applications and their workflow."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CacheDep, CurrentUser, DispatcherDep, Pagination, SessionDep, require
from app.core.security import Permission
from app.db.models import ApplicationStatus, User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationListItem,
    HistoryEntry,
    NoteCreate,
    NoteOut,
    StatusChange,
    WithdrawRequest,
)
from app.schemas.common import COMMON_ERRORS, ErrorResponse, Page
from app.services.applications import ApplicationService

router = APIRouter(prefix="/applications", tags=["Applications"], responses=COMMON_ERRORS)


def _svc(session: SessionDep, dispatcher: DispatcherDep, cache: CacheDep) -> ApplicationService:
    return ApplicationService(session, dispatcher, cache)


Svc = Annotated[ApplicationService, Depends(_svc)]


@router.post(
    "",
    response_model=ApplicationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Apply to a job (candidates)",
    responses={**COMMON_ERRORS, 409: {"model": ErrorResponse, "description": "APPLICATION_ALREADY_EXISTS"}},
)
async def apply(
    data: ApplicationCreate, user: Annotated[User, Depends(require(Permission.APPLY_TO_JOBS))], svc: Svc
) -> ApplicationDetail:
    app = await svc.apply(user, data)
    return await svc.detail(user, app.id)


@router.get(
    "",
    response_model=Page[ApplicationListItem],
    summary="List applications visible to me",
    description="Candidates: their own. Recruiters: their company's. Hiring managers: for jobs assigned to them.",
)
async def list_applications(
    user: CurrentUser,
    svc: Svc,
    p: Pagination,
    job_id: uuid.UUID | None = None,
    status_: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: Annotated[str, Query(pattern="^(newest|oldest|updated|match)$")] = "newest",
    active_only: bool = False,
) -> Page[ApplicationListItem]:
    items, total = await svc.list(
        user,
        job_id=job_id,
        statuses=status_,
        q=q,
        sort=sort,
        page=p.page,
        page_size=p.page_size,
        active_only=active_only,
    )
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.get("/{application_id}", response_model=ApplicationDetail, summary="Application detail with history")
async def get_application(application_id: uuid.UUID, user: CurrentUser, svc: Svc) -> ApplicationDetail:
    return await svc.detail(user, application_id)


@router.get("/{application_id}/history", response_model=list[HistoryEntry], summary="Status timeline")
async def application_history(application_id: uuid.UUID, user: CurrentUser, svc: Svc) -> list[HistoryEntry]:
    return (await svc.detail(user, application_id)).history


@router.post(
    "/{application_id}/status",
    response_model=ApplicationDetail,
    summary="Move an application to another stage (recruiters)",
    description="Valid transitions: APPLIED→SCREENING→SHORTLISTED→INTERVIEW→OFFER→HIRED; any live stage → REJECTED. "
    "Invalid moves return 409 INVALID_STATE_TRANSITION with the allowed targets.",
)
async def change_status(
    application_id: uuid.UUID,
    data: StatusChange,
    user: Annotated[User, Depends(require(Permission.MANAGE_APPLICATIONS))],
    svc: Svc,
) -> ApplicationDetail:
    await svc.change_status(user, application_id, data.status, data.comment)
    return await svc.detail(user, application_id)


@router.post(
    "/{application_id}/withdraw",
    response_model=ApplicationDetail,
    summary="Withdraw my application (candidates, before shortlisting)",
)
async def withdraw(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(require(Permission.APPLY_TO_JOBS))],
    svc: Svc,
    data: WithdrawRequest | None = None,
) -> ApplicationDetail:
    await svc.withdraw(user, application_id, data.comment if data else None)
    return await svc.detail(user, application_id)


@router.get(
    "/{application_id}/notes", response_model=list[NoteOut], summary="Internal notes (hiring staff only)"
)
async def list_notes(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(require(Permission.REVIEW_APPLICATIONS))],
    svc: Svc,
) -> list[NoteOut]:
    return await svc.list_notes(user, application_id)


@router.post(
    "/{application_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an internal note",
)
async def add_note(
    application_id: uuid.UUID,
    data: NoteCreate,
    user: Annotated[User, Depends(require(Permission.REVIEW_APPLICATIONS))],
    svc: Svc,
) -> NoteOut:
    return await svc.add_note(user, application_id, data.body)
