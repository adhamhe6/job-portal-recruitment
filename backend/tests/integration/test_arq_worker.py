"""The real queue path: API → ArqDispatcher → Redis → ARQ Worker → handler → PostgreSQL (no inline shortcut)."""

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker
from sqlalchemy import select

from app.cache.redis_cache import get_cache
from app.core.config import get_settings
from app.db.database import get_sessionmaker
from app.db.models import BackgroundTask, CandidateProfile, TaskStatus, TaskType
from app.workers import worker as W
from app.workers.dispatch import ArqDispatcher
from tests.helpers import fill_backend_profile, register_candidate

pytestmark = pytest.mark.integration


async def _run_worker_burst() -> None:
    async def startup(ctx: dict) -> None:
        ctx["sessionmaker"] = get_sessionmaker()
        ctx["cache"] = get_cache()

    w = Worker(
        functions=W.WorkerSettings.functions,
        redis_settings=RedisSettings.from_dsn(get_settings().redis_url),
        on_startup=startup,
        burst=True,
        handle_signals=False,
        max_jobs=4,
        poll_delay=0.05,
    )
    try:
        await w.main()
    finally:
        await w.close()


async def test_profile_edit_is_processed_by_a_real_arq_worker(client):
    from app.main import app

    dispatcher = ArqDispatcher(None)
    app.state.dispatcher = dispatcher
    try:
        cand = await register_candidate(client)
        await fill_backend_profile(client, cand)

        async with get_sessionmaker()() as s:
            pending = (
                (
                    await s.execute(
                        select(BackgroundTask).where(BackgroundTask.type == TaskType.MATCH_CANDIDATE)
                    )
                )
                .scalars()
                .all()
            )
            assert pending, "profile edits must enqueue a task"
            assert all(t.status == TaskStatus.PENDING for t in pending), (
                "nothing runs until a worker picks the message up"
            )
            embedding_before = (
                await s.execute(
                    select(CandidateProfile.embedding).where(CandidateProfile.user_id.is_not(None))
                )
            ).scalar_one()
            assert embedding_before is None

        await _run_worker_burst()

        async with get_sessionmaker()() as s:
            tasks = (
                (
                    await s.execute(
                        select(BackgroundTask).where(BackgroundTask.type == TaskType.MATCH_CANDIDATE)
                    )
                )
                .scalars()
                .all()
            )
            assert [t.status for t in tasks] == [TaskStatus.COMPLETED]
            assert tasks[0].progress == 100 and tasks[0].started_at and tasks[0].finished_at
            profile = (await s.execute(select(CandidateProfile))).scalar_one()
            assert (
                profile.embedding is not None and profile.embedding_model
            )  # the worker generated the embedding
        r = await client.get(f"/api/v1/tasks/{tasks[0].id}", headers=cand["h"])
        assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    finally:
        if dispatcher.pool is not None:
            await dispatcher.pool.aclose()


async def test_duplicate_delivery_is_harmless(client):
    """Two queue messages for one task: exactly one execution (atomic PENDING → RUNNING claim)."""
    from app.main import app

    dispatcher = ArqDispatcher(None)
    app.state.dispatcher = dispatcher
    try:
        cand = await register_candidate(client)
        await fill_backend_profile(client, cand)
        async with get_sessionmaker()() as s:
            task = (
                (
                    await s.execute(
                        select(BackgroundTask).where(BackgroundTask.type == TaskType.MATCH_CANDIDATE)
                    )
                )
                .scalars()
                .first()
            )
            assert task is not None
            await dispatcher.dispatch(str(task.id))  # a second, duplicate message
        await _run_worker_burst()
        async with get_sessionmaker()() as s:
            done = (await s.execute(select(BackgroundTask).where(BackgroundTask.id == task.id))).scalar_one()
            assert done.status == TaskStatus.COMPLETED and done.attempts == 1
    finally:
        if dispatcher.pool is not None:
            await dispatcher.pool.aclose()
