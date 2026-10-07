"""Admin: system health, background tasks, audit log, embeddings and matching maintenance. ADMIN only."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CacheDep, DispatcherDep, Pagination, SessionDep, require
from app.core.security import Permission
from app.db.models import TaskStatus, TaskType, User
from app.schemas.admin import (
    AdminTaskOut,
    AuditEventOut,
    EmbeddingRefreshOut,
    EmbeddingsStatus,
    MatchingStatus,
    SystemStatus,
)
from app.schemas.common import COMMON_ERRORS, ErrorResponse, Page
from app.services.admin import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"], responses=COMMON_ERRORS)


def _svc(session: SessionDep, cache: CacheDep) -> AdminService:
    return AdminService(session, cache)


Svc = Annotated[AdminService, Depends(_svc)]
Admin = Annotated[User, Depends(require(Permission.MONITOR_SYSTEM))]


@router.get(
    "/system",
    response_model=SystemStatus,
    summary="System health",
    description=(
        "Database (latency, pgvector and migration revision), Redis (latency, ARQ queue depth), the embedding model (does it load and "
        "produce vectors of the configured size), worker liveness (ARQ health-check key), task counts and stale tasks. "
        "`status` is `down` when the database is unreachable, `degraded` when anything else is wrong. No secrets are exposed."
    ),
)
async def system_status(user: Admin, svc: Svc) -> SystemStatus:
    return await svc.system_status(user)


@router.get(
    "/tasks",
    response_model=Page[AdminTaskOut],
    summary="Background tasks",
    description="All tasks, newest first. Filter by `status` and `type`. Results are omitted (use `GET /tasks/{id}`).",
)
async def list_tasks(
    user: Admin,
    svc: Svc,
    p: Pagination,
    status_: Annotated[TaskStatus | None, Query(alias="status")] = None,
    type_: Annotated[TaskType | None, Query(alias="type")] = None,
) -> Page[AdminTaskOut]:
    items, total = await svc.list_tasks(user, status=status_, type_=type_, page=p.page, page_size=p.page_size)
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.post(
    "/tasks/{task_id}/retry",
    response_model=AdminTaskOut,
    summary="Retry a failed task",
    description="Only FAILED tasks: resets the attempt counter, sets the task back to PENDING and re-enqueues it. "
    "`409 TASK_NOT_RETRYABLE` for any other state, `409 TASK_ALREADY_ACTIVE` if an equivalent task is running.",
    responses={
        **COMMON_ERRORS,
        409: {"model": ErrorResponse, "description": "TASK_NOT_RETRYABLE / TASK_ALREADY_ACTIVE"},
    },
)
async def retry_task(task_id: uuid.UUID, user: Admin, svc: Svc, dispatcher: DispatcherDep) -> AdminTaskOut:
    return await svc.retry_task(user, task_id, dispatcher)


@router.get(
    "/audit",
    response_model=Page[AuditEventOut],
    summary="Audit log",
    description="Append-only record of business-relevant actions, newest first. `action` is an exact name or a prefix ending in `*` "
    "(e.g. `interview.*`). `from_date` / `to_date` are inclusive UTC dates.",
)
async def audit_log(
    user: Admin,
    svc: Svc,
    p: Pagination,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> Page[AuditEventOut]:
    items, total = await svc.list_audit(
        user,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        page=p.page,
        page_size=p.page_size,
    )
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.post(
    "/embeddings/refresh",
    response_model=EmbeddingRefreshOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-embed everything that is stale",
    description="Queues a `REFRESH_EMBEDDINGS` task (deduplicated: while one is pending or running the same task is returned with `created=false`). "
    "Unchanged items are skipped by their source hash, so it is cheap to run after a model change.",
)
async def refresh_embeddings(user: Admin, svc: Svc, dispatcher: DispatcherDep) -> EmbeddingRefreshOut:
    task, created = await svc.refresh_embeddings(user, dispatcher)
    return EmbeddingRefreshOut(task_id=task.id, status=task.status, created=created)


@router.get(
    "/embeddings/status",
    response_model=EmbeddingsStatus,
    summary="Embedding coverage",
    description="For jobs, candidate profiles and résumé results: how many have an embedding from the configured model/version (`current`), "
    "from another one (`outdated`) or none (`missing`), plus the latest refresh task.",
)
async def embeddings_status(user: Admin, svc: Svc) -> EmbeddingsStatus:
    return await svc.embeddings_status(user)


@router.get(
    "/matching/status",
    response_model=MatchingStatus,
    summary="Matching coverage",
    description="Stored candidate-job match pairs, how many were computed with an outdated matching / embedding version, published jobs "
    "without any match yet and the match tasks of the last 24 hours.",
)
async def matching_status(user: Admin, svc: Svc) -> MatchingStatus:
    return await svc.matching_status(user)
