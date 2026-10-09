"""Job postings: management (recruiters) and public detail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    CacheDep,
    CurrentUser,
    DispatcherDep,
    OptionalUser,
    Pagination,
    SessionDep,
    require,
)
from app.core.errors import PermissionDeniedError
from app.core.security import Permission, Role
from app.db.models import JobStatus, User
from app.schemas.common import COMMON_ERRORS, ErrorResponse, MessageResponse, Page
from app.schemas.job import JobCreate, JobDetail, JobListItem, JobPublic, JobStats, JobTransition, JobUpdate
from app.search.jobs import JobFilters, JobSearch, JobSort
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])

Manager = Annotated[User, Depends(require(Permission.MANAGE_JOBS))]


def _svc(session: SessionDep, dispatcher: DispatcherDep, cache: CacheDep) -> JobService:
    return JobService(session, dispatcher, cache)


Svc = Annotated[JobService, Depends(_svc)]


async def _detail(svc: JobService, user: User, job_id: uuid.UUID) -> JobDetail:
    result = await svc.public_detail(job_id, user)
    assert isinstance(result, JobDetail)
    return result


@router.get(
    "",
    response_model=Page[JobListItem],
    summary="List my company's jobs (all statuses)",
    description="Recruiters see every job of their company; hiring managers only jobs assigned to them; admins all jobs.",
    responses=COMMON_ERRORS,
)
async def list_company_jobs(
    user: Annotated[User, Depends(require(Permission.VIEW_COMPANY_JOBS))],
    session: SessionDep,
    p: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_: Annotated[list[JobStatus] | None, Query(alias="status")] = None,
    sort: JobSort = JobSort.NEWEST,
    company_id: uuid.UUID | None = None,
) -> Page[JobListItem]:
    filters = JobFilters(q=q, statuses=status_ or [], sort=sort)
    scope_company = user.company_id
    if user.role == Role.ADMIN:
        scope_company = company_id
    items, total = await JobSearch(session).run(
        filters,
        public=False,
        page=p.page,
        page_size=p.page_size,
        company_id=scope_company,
        hiring_manager_id=user.id if user.role == Role.HIRING_MANAGER else None,
        with_counts=True,
    )
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.post(
    "",
    response_model=JobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a job (as DRAFT)",
    description="Skills may be referenced by `skill_id` or `name`. Publish with `POST /jobs/{id}/publish`.",
    responses={**COMMON_ERRORS, 409: {"model": ErrorResponse, "description": "DUPLICATE_JOB"}},
)
async def create_job(
    data: JobCreate, user: Manager, svc: Svc, company_id: uuid.UUID | None = None
) -> JobDetail:
    job = await svc.create(user, data, company_id=company_id)
    return await _detail(svc, user, job.id)


@router.get(
    "/{job_id}",
    response_model=JobDetail | JobPublic,
    summary="Job detail",
    description="Anonymous and candidate callers get the public representation of PUBLISHED jobs (404 otherwise). "
    "The owning company's staff get the full representation, including drafts.",
    responses={404: COMMON_ERRORS[404]},
)
async def get_job(job_id: uuid.UUID, svc: Svc, viewer: OptionalUser) -> JobDetail | JobPublic:
    return await svc.public_detail(job_id, viewer)


@router.patch("/{job_id}", response_model=JobDetail, summary="Edit a job", responses=COMMON_ERRORS)
async def update_job(job_id: uuid.UUID, data: JobUpdate, user: Manager, svc: Svc) -> JobDetail:
    await svc.update(user, job_id, data)
    return await _detail(svc, user, job_id)


@router.delete(
    "/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft job", responses=COMMON_ERRORS
)
async def delete_job(job_id: uuid.UUID, user: Manager, svc: Svc) -> Response:
    await svc.delete_draft(user, job_id)
    return Response(status_code=204)


def _transition_route(path: str, target: JobStatus, summary: str) -> None:
    @router.post(
        f"/{{job_id}}/{path}",
        response_model=JobDetail,
        summary=summary,
        name=f"job_{path}",
        responses=COMMON_ERRORS,
    )
    async def _transition(
        job_id: uuid.UUID, user: Manager, svc: Svc, body: JobTransition | None = None
    ) -> JobDetail:
        await svc.transition(user, job_id, target, body.reason if body else None)
        return await _detail(svc, user, job_id)


_transition_route("publish", JobStatus.PUBLISHED, "Publish a draft (or resume a paused job)")
_transition_route("pause", JobStatus.PAUSED, "Temporarily stop accepting applications")
_transition_route("resume", JobStatus.PUBLISHED, "Resume a paused job")
_transition_route("close", JobStatus.CLOSED, "Close the job")
_transition_route("archive", JobStatus.ARCHIVED, "Archive a closed (or draft) job")


@router.get(
    "/{job_id}/stats",
    response_model=JobStats,
    summary="Application counts and match coverage for a job",
    responses=COMMON_ERRORS,
)
async def job_stats(
    job_id: uuid.UUID, user: Annotated[User, Depends(require(Permission.VIEW_COMPANY_JOBS))], svc: Svc
) -> JobStats:
    return await svc.stats(user, job_id)


@router.put(
    "/{job_id}/save",
    response_model=MessageResponse,
    summary="Save a job (candidates)",
    responses=COMMON_ERRORS,
)
async def save_job(job_id: uuid.UUID, user: CurrentUser, svc: Svc) -> MessageResponse:
    if user.role != Role.CANDIDATE:
        raise PermissionDeniedError("Only candidates can save jobs")
    await svc.save(user, job_id)
    return MessageResponse(message="Saved")


@router.delete(
    "/{job_id}/save", response_model=MessageResponse, summary="Unsave a job", responses=COMMON_ERRORS
)
async def unsave_job(job_id: uuid.UUID, user: CurrentUser, svc: Svc) -> MessageResponse:
    if user.role != Role.CANDIDATE:
        raise PermissionDeniedError("Only candidates can save jobs")
    await svc.unsave(user, job_id)
    return MessageResponse(message="Removed")
