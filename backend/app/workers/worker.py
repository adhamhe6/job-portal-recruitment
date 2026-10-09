"""ARQ worker entrypoint: ``arq app.workers.worker.WorkerSettings``.

Why ARQ: the API is asyncio-native (FastAPI + asyncpg). ARQ is a small asyncio queue on Redis, so the worker reuses the
exact same async services, sessions and cache code — no sync/async bridge, no extra broker abstraction. Celery would add a
sync-first runtime and considerable operational surface for no benefit at this scale; RQ is synchronous.

Durability: the queue only delivers messages. Task state lives in PostgreSQL (``background_tasks``), so a lost Redis queue
or a crashed worker is detectable and recoverable by the reaper below.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from redis.exceptions import RedisError
from sqlalchemy import delete, select, update

from app.cache.redis_cache import close_redis, get_cache
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import dispose_engine, get_sessionmaker
from app.db.models import BackgroundTask, Job, JobStatus, RefreshToken, TaskStatus, TaskType
from app.services.common import utcnow
from app.services.scheduling import schedule_job_match
from app.workers.tasks import execute_task

logger = logging.getLogger(__name__)
settings = get_settings()

HEARTBEAT_INTERVAL_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 45
ORPHAN_GRACE_SECONDS = 60
QUEUED_GRACE_SECONDS = 600
MAX_TASK_SECONDS = 3600


def heartbeat_key(task_id: str) -> str:
    return f"task:heartbeat:{task_id}"


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level, settings.log_json)
    ctx["sessionmaker"] = get_sessionmaker()
    ctx["cache"] = get_cache()
    # Load the embedding model once, up front, so the first résumé does not pay for it (and a broken install fails loudly).
    try:
        from app.matching.embedder import get_embedder

        emb = await asyncio.to_thread(get_embedder)
        logger.info(
            "embedding model ready", extra={"model": emb.name, "version": emb.version, "dim": emb.dim}
        )
    except Exception as exc:
        logger.error("embedding model failed to load", extra={"error": type(exc).__name__})
    await reap_stale_tasks(ctx)
    logger.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()
    await close_redis()
    logger.info("worker stopped")


async def run_task(ctx: dict[str, Any], task_id: str) -> None:
    """Execute one durable task, refreshing a liveness heartbeat while it runs; re-queue it when it asked for a retry."""
    redis = ctx["redis"]
    key = heartbeat_key(task_id)

    async def touch() -> None:
        with contextlib.suppress(RedisError):
            await redis.set(key, b"1", ex=HEARTBEAT_TTL_SECONDS)

    async def beat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await touch()

    await touch()
    heartbeat = asyncio.create_task(beat())
    delay: float | None = None
    try:
        delay = await execute_task(task_id, ctx["sessionmaker"], ctx["cache"])
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        with contextlib.suppress(RedisError):
            await redis.delete(key)
    if delay is not None:
        try:
            await redis.enqueue_job(
                "run_task",
                task_id,
                _job_id=f"{task_id}:{int(delay)}:{int(utcnow().timestamp())}",
                _defer_by=delay,
            )
        except RedisError:
            async with ctx["sessionmaker"]() as s:
                await s.execute(
                    update(BackgroundTask)
                    .where(BackgroundTask.id == task_id)
                    .values(
                        status=TaskStatus.FAILED,
                        error_code="QUEUE_UNAVAILABLE",
                        error_message="Could not re-queue the task",
                        finished_at=utcnow(),
                    )
                )
                await s.commit()


async def reap_stale_tasks(ctx: dict[str, Any]) -> None:
    """Fail tasks whose work can no longer happen so none stays in progress forever.

    * RUNNING with an expired heartbeat (the executing worker refreshes it every few seconds), or running past the maximum.
    * PENDING for longer than the grace period whose queue message is gone (e.g. Redis restarted without persistence).
    If Redis is unreachable nothing is reaped: no evidence of a dead worker is not evidence of one.
    """
    now = utcnow()
    redis = ctx["redis"]
    async with ctx["sessionmaker"]() as s:
        rows = (
            await s.execute(
                select(BackgroundTask.id, BackgroundTask.status, BackgroundTask.started_at).where(
                    (
                        (BackgroundTask.status == TaskStatus.RUNNING)
                        & (BackgroundTask.started_at < now - timedelta(seconds=ORPHAN_GRACE_SECONDS))
                    )
                    | (
                        (BackgroundTask.status == TaskStatus.PENDING)
                        & (BackgroundTask.created_at < now - timedelta(seconds=QUEUED_GRACE_SECONDS))
                    )
                )
            )
        ).all()
        dead_running: list[Any] = []
        lost_pending: list[Any] = []
        try:
            for tid, status, started_at in rows:
                if status == TaskStatus.RUNNING:
                    if started_at < now - timedelta(seconds=MAX_TASK_SECONDS + 60) or not await redis.exists(
                        heartbeat_key(str(tid))
                    ):
                        dead_running.append(tid)
                else:
                    queued = False
                    async for _ in redis.scan_iter(match=f"arq:job:{tid}:*", count=100):
                        queued = True
                        break
                    if not queued:
                        lost_pending.append(tid)
        except RedisError:
            logger.warning("reaper skipped: redis unavailable")
            return
        for ids, status, msg in (
            (dead_running, TaskStatus.RUNNING, "The worker stopped while processing; please retry"),
            (
                lost_pending,
                TaskStatus.PENDING,
                "The job queue lost this task before it started; please retry",
            ),
        ):
            if ids:
                await s.execute(
                    update(BackgroundTask)
                    .where(BackgroundTask.id.in_(ids), BackgroundTask.status == status)
                    .values(
                        status=TaskStatus.FAILED, error_code="WORKER_LOST", error_message=msg, finished_at=now
                    )
                )
        if dead_running or lost_pending:
            await s.commit()
            logger.warning(
                "failed orphaned tasks", extra={"running": len(dead_running), "pending": len(lost_pending)}
            )


async def sweep_matches(ctx: dict[str, Any]) -> None:
    """Nightly: re-score every live job (deduplicated tasks). Picks up new candidates and profile edits whose individual
    refresh was lost, and lets expired-deadline jobs drop out of recommendations."""
    from app.workers.dispatch import ArqDispatcher

    dispatcher = ArqDispatcher(ctx["redis"])
    async with ctx["sessionmaker"]() as s:
        job_ids = [
            r for (r,) in (await s.execute(select(Job.id).where(Job.status == JobStatus.PUBLISHED))).all()
        ]
        for jid in job_ids:
            await schedule_job_match(s, dispatcher, jid)
    logger.info("nightly match sweep queued", extra={"jobs": len(job_ids)})


async def cleanup_old_records(ctx: dict[str, Any]) -> None:
    """Housekeeping: expired refresh tokens and finished tasks older than 30 days."""
    cutoff = utcnow() - timedelta(days=30)
    async with ctx["sessionmaker"]() as s:
        t = await s.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
        k = await s.execute(
            delete(BackgroundTask).where(
                BackgroundTask.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED]),
                BackgroundTask.finished_at < cutoff,
            )
        )
        await s.commit()
    logger.info("housekeeping done", extra={"refresh_tokens": t.rowcount, "tasks": k.rowcount})


class WorkerSettings:
    functions = [run_task]
    cron_jobs = [
        cron(reap_stale_tasks, minute=set(range(0, 60, 2)), run_at_startup=False),
        cron(sweep_matches, hour={3}, minute={15}, run_at_startup=False),
        cron(cleanup_old_records, hour={4}, minute={30}, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = MAX_TASK_SECONDS
    max_tries = 1  # retries are explicit and bounded in execute_task
    keep_result = 300
    health_check_interval = 30


_ = TaskType
