"""Durable background-task records.

The queue (Redis/ARQ) only *delivers* work; PostgreSQL holds the truth about it. That makes enqueueing idempotent
(partial unique index on ``dedupe_key`` for active tasks), status pollable, and recovery from lost queue messages
or crashed workers possible (see ``workers.worker.reap_stale_tasks``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFoundError, ServiceUnavailableError
from app.db.models import ACTIVE_TASK_STATUSES, BackgroundTask, TaskStatus, TaskType, User
from app.services.access import is_admin
from app.services.common import utcnow

logger = logging.getLogger(__name__)


class Dispatcher(Protocol):
    async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None: ...


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- API side -----------------------------------------------------------------------------------
    async def create(
        self,
        task_type: TaskType,
        params: dict[str, Any],
        *,
        created_by_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
    ) -> tuple[BackgroundTask, bool]:
        """Insert a PENDING task. Returns ``(task, created)``; if an *active* task with the same dedupe key exists it
        is returned instead (``created=False``) so repeated requests do not pile up duplicate work."""
        if dedupe_key:
            existing = await self._active_by_key(dedupe_key)
            if existing:
                return existing, False
        task = BackgroundTask(
            type=task_type,
            params=params,
            created_by_id=created_by_id,
            company_id=company_id,
            dedupe_key=dedupe_key,
        )
        self.session.add(task)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._active_by_key(dedupe_key) if dedupe_key else None
            if existing:
                return existing, False
            raise
        return task, True

    async def _active_by_key(self, key: str) -> BackgroundTask | None:
        return (
            await self.session.execute(
                select(BackgroundTask).where(
                    BackgroundTask.dedupe_key == key, BackgroundTask.status.in_(ACTIVE_TASK_STATUSES)
                )
            )
        ).scalar_one_or_none()

    async def enqueue(self, task: BackgroundTask, dispatcher: Dispatcher) -> None:
        """Hand the (already committed) task to the queue; on failure mark it FAILED instead of leaving it PENDING forever."""
        try:
            await dispatcher.dispatch(str(task.id))
        except ServiceUnavailableError:
            await self.fail(
                task.id, "QUEUE_UNAVAILABLE", "The job queue is unavailable; please retry shortly"
            )
            raise

    async def submit(
        self,
        task_type: TaskType,
        params: dict[str, Any],
        dispatcher: Dispatcher,
        *,
        created_by_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
    ) -> tuple[BackgroundTask, bool]:
        task, created = await self.create(
            task_type, params, created_by_id=created_by_id, company_id=company_id, dedupe_key=dedupe_key
        )
        if created:
            await self.enqueue(task, dispatcher)
            await self.session.refresh(task)  # inline dispatch may already have finished it
        return task, created

    async def get_for_user(self, user: User, task_id: uuid.UUID) -> BackgroundTask:
        task = await self.session.get(BackgroundTask, task_id)
        visible = task is not None and (
            is_admin(user)
            or task.created_by_id == user.id
            or (
                user.company_id is not None
                and task.company_id == user.company_id
                and user.role.value == "RECRUITER"
            )
        )
        if task is None or not visible:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND")
        return task

    async def fail(self, task_id: uuid.UUID | str, code: str, message: str) -> None:
        await self.session.execute(
            update(BackgroundTask)
            .where(
                BackgroundTask.id == uuid.UUID(str(task_id)), BackgroundTask.status.in_(ACTIVE_TASK_STATUSES)
            )
            .values(
                status=TaskStatus.FAILED, error_code=code, error_message=message[:500], finished_at=utcnow()
            )
        )
        await self.session.commit()


# --- worker side: each call uses its own short transaction so progress is visible while a task runs -----------


class TaskStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def claim(self, task_id: uuid.UUID) -> BackgroundTask | None:
        """Atomically move PENDING → RUNNING. Returns None if another worker already took it or it is finished
        (duplicate delivery of the same queue message is therefore harmless)."""
        async with self.sessionmaker() as s:
            row = (
                await s.execute(
                    update(BackgroundTask)
                    .where(BackgroundTask.id == task_id, BackgroundTask.status == TaskStatus.PENDING)
                    .values(
                        status=TaskStatus.RUNNING,
                        started_at=utcnow(),
                        attempts=BackgroundTask.attempts + 1,
                        progress=0,
                        stage="starting",
                        error_code=None,
                        error_message=None,
                    )
                    .returning(BackgroundTask.id)
                )
            ).scalar_one_or_none()
            await s.commit()
            if row is None:
                return None
            return await s.get(BackgroundTask, task_id)

    async def progress(self, task_id: uuid.UUID, pct: int, stage: str) -> None:
        async with self.sessionmaker() as s:
            await s.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id, BackgroundTask.status == TaskStatus.RUNNING)
                .values(progress=max(0, min(100, pct)), stage=stage[:60])
            )
            await s.commit()

    async def complete(self, task_id: uuid.UUID, result: dict[str, Any] | None) -> None:
        async with self.sessionmaker() as s:
            await s.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(
                    status=TaskStatus.COMPLETED,
                    progress=100,
                    stage="done",
                    result=result,
                    finished_at=utcnow(),
                )
            )
            await s.commit()

    async def fail(self, task_id: uuid.UUID, code: str, message: str) -> None:
        async with self.sessionmaker() as s:
            await s.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(
                    status=TaskStatus.FAILED,
                    error_code=code,
                    error_message=message[:500],
                    stage="failed",
                    finished_at=utcnow(),
                )
            )
            await s.commit()

    async def requeue(self, task_id: uuid.UUID, reason: str) -> None:
        async with self.sessionmaker() as s:
            await s.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(status=TaskStatus.PENDING, stage="retrying", error_message=reason[:500])
            )
            await s.commit()
