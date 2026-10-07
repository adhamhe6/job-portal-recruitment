"""Task execution core, shared by the ARQ worker and the inline (test) dispatcher.

Handler contract (``app.<package>.tasks``): ``async def handle_x(ctx: TaskContext) -> dict | None``.
* return a JSON-serialisable dict (stored as the task ``result``) or ``None``;
* raise ``RetryableError`` for transient problems (bounded by ``TASK_MAX_ATTEMPTS``);
* raise ``TaskFailure(code, safe_message)`` for expected failures (message is shown to users: no document content);
* any other exception is logged with a traceback and recorded as ``INTERNAL_ERROR`` with a generic message.
Handlers must be idempotent: the same task may be delivered more than once.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cache.redis_cache import Cache
from app.core.config import get_settings
from app.core.logging import job_id_ctx
from app.db.models import TaskType
from app.services.tasks import TaskStore

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """Transient failure; the task is re-queued (with back-off) until ``task_max_attempts`` is reached."""

    def __init__(self, message: str, *, delay_seconds: float = 5.0) -> None:
        super().__init__(message)
        self.delay_seconds = delay_seconds


class TaskFailure(Exception):  # noqa: N818 - reads as a domain term, not an error type
    """Expected, non-retryable failure with a *safe* user-facing message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class TaskContext:
    task_id: uuid.UUID
    type: TaskType
    params: dict[str, Any]
    created_by_id: uuid.UUID | None
    company_id: uuid.UUID | None
    attempt: int
    sessionmaker: async_sessionmaker[AsyncSession]
    cache: Cache
    store: TaskStore
    extra: dict[str, Any] = field(default_factory=dict)

    async def progress(self, pct: int, stage: str) -> None:
        await self.store.progress(self.task_id, pct, stage)


HANDLER_PATHS: dict[TaskType, str] = {
    TaskType.PROCESS_RESUME: "app.resume.tasks:handle_process_resume",
    TaskType.BULK_RESUME_IMPORT: "app.resume.tasks:handle_bulk_import",
    TaskType.MATCH_JOB: "app.matching.tasks:handle_match_job",
    TaskType.MATCH_CANDIDATE: "app.matching.tasks:handle_match_candidate",
    TaskType.REFRESH_EMBEDDINGS: "app.matching.tasks:handle_refresh_embeddings",
    TaskType.EXPORT_REPORT: "app.services.report_tasks:handle_export_report",
}
TASK_TIMEOUTS: dict[TaskType, float] = {
    TaskType.PROCESS_RESUME: 180.0,
    TaskType.BULK_RESUME_IMPORT: 3600.0,
    TaskType.MATCH_JOB: 600.0,
    TaskType.MATCH_CANDIDATE: 300.0,
    TaskType.REFRESH_EMBEDDINGS: 3600.0,
    TaskType.EXPORT_REPORT: 300.0,
}

Handler = Callable[[TaskContext], Awaitable[dict[str, Any] | None]]
_overrides: dict[TaskType, Handler] = {}


def register_handler(task_type: TaskType, handler: Handler | None) -> None:
    """Override a handler (tests: inject failures). ``None`` removes the override."""
    if handler is None:
        _overrides.pop(task_type, None)
    else:
        _overrides[task_type] = handler


def resolve_handler(task_type: TaskType) -> Handler:
    if task_type in _overrides:
        return _overrides[task_type]
    module_name, func_name = HANDLER_PATHS[task_type].split(":")
    return getattr(importlib.import_module(module_name), func_name)  # type: ignore[no-any-return]


async def execute_task(
    task_id: str | uuid.UUID, sessionmaker: async_sessionmaker[AsyncSession], cache: Cache
) -> float | None:
    """Run one task to a terminal state. Returns a delay (seconds) if the task must be re-delivered, else ``None``."""
    tid = uuid.UUID(str(task_id))
    store = TaskStore(sessionmaker)
    token = job_id_ctx.set(str(tid))
    try:
        task = await store.claim(tid)
        if task is None:
            logger.info("task skipped (not pending)", extra={"task_id": str(tid)})
            return None
        settings = get_settings()
        ctx = TaskContext(
            task_id=tid,
            type=task.type,
            params=task.params or {},
            created_by_id=task.created_by_id,
            company_id=task.company_id,
            attempt=task.attempts,
            sessionmaker=sessionmaker,
            cache=cache,
            store=store,
        )
        logger.info("task started", extra={"task_id": str(tid), "task_type": task.type.value, "attempt": task.attempts})
        try:
            result = await asyncio.wait_for(resolve_handler(task.type)(ctx), timeout=TASK_TIMEOUTS.get(task.type, 300.0))
        except TaskFailure as exc:
            await store.fail(tid, exc.code, exc.message)
            logger.warning("task failed", extra={"task_id": str(tid), "code": exc.code})
        except RetryableError as exc:
            if task.attempts < settings.task_max_attempts:
                await store.requeue(tid, str(exc))
                logger.warning("task will be retried", extra={"task_id": str(tid), "attempt": task.attempts})
                return exc.delay_seconds * task.attempts
            await store.fail(tid, "RETRIES_EXHAUSTED", "The operation kept failing; please try again later")
            logger.error("task failed after retries", extra={"task_id": str(tid)})
        except TimeoutError:
            await store.fail(tid, "TIMEOUT", "The operation took too long and was stopped")
            logger.error("task timed out", extra={"task_id": str(tid)})
        except Exception as exc:
            # Never put exception text in the record: it may embed document content.
            logger.exception("task crashed", extra={"task_id": str(tid), "error": type(exc).__name__})
            await store.fail(tid, "INTERNAL_ERROR", "An unexpected error occurred while processing")
        else:
            await store.complete(tid, result)
            logger.info("task completed", extra={"task_id": str(tid)})
        return None
    finally:
        job_id_ctx.reset(token)
