"""Task dispatchers: ARQ (production) and inline (tests / no-worker mode)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.exceptions import RedisError

from app.cache.redis_cache import get_cache
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.db.database import get_sessionmaker
from app.workers.tasks import execute_task

logger = logging.getLogger(__name__)


class ArqDispatcher:
    """Enqueues tasks on Redis. Connects lazily so the API can start (and recover) while Redis is down."""

    def __init__(self, pool: ArqRedis | None) -> None:
        self.pool = pool

    async def _ensure_pool(self) -> ArqRedis:
        if self.pool is None:
            try:
                rs = RedisSettings.from_dsn(get_settings().redis_url)
                rs.conn_timeout, rs.conn_retries, rs.conn_retry_delay = 2, 1, 0  # fail fast: the API must not hang on a dead queue
                self.pool = await create_pool(rs)
            except Exception as exc:
                logger.error("job queue unavailable", extra={"error": type(exc).__name__})
                raise ServiceUnavailableError("Job queue unavailable") from exc
        return self.pool

    async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None:
        pool = await self._ensure_pool()
        try:
            # Unique queue-level id per delivery (ARQ would otherwise drop a re-enqueue while the previous result is retained).
            # Duplicate deliveries are harmless: TaskStore.claim() only lets one worker move PENDING → RUNNING.
            await pool.enqueue_job(
                "run_task",
                task_id,
                _job_id=f"{task_id}:{uuid.uuid4().hex[:8]}",
                _defer_by=defer_seconds or None,
            )
        except (RedisError, OSError) as exc:
            logger.error("failed to enqueue task", extra={"task_id": task_id, "error": type(exc).__name__})
            raise ServiceUnavailableError("Job queue unavailable") from exc


class InlineDispatcher:
    """Executes the task immediately in-process (JOB_BACKEND=inline; used by tests)."""

    async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None:
        delay = await execute_task(task_id, get_sessionmaker(), get_cache())
        attempts = 0
        while delay is not None and attempts < get_settings().task_max_attempts:
            attempts += 1
            delay = await execute_task(task_id, get_sessionmaker(), get_cache())


async def build_dispatcher() -> tuple[ArqDispatcher | InlineDispatcher, Callable[[], Awaitable[None]]]:
    settings = get_settings()
    if settings.job_backend == "inline":

        async def _noop() -> None:
            return None

        return InlineDispatcher(), _noop
    dispatcher = ArqDispatcher(None)

    async def _close() -> None:
        if dispatcher.pool is not None:
            await dispatcher.pool.aclose()

    return dispatcher, _close
