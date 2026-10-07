"""Durable background tasks: dedupe, atomic claiming, execution outcomes, visibility, the reaper and the heartbeat wrapper."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import RedisError

from app.cache.redis_cache import get_cache, get_redis
from app.core.config import get_settings
from app.core.logging import job_id_ctx
from app.db.database import get_sessionmaker
from app.db.models import BackgroundTask, TaskStatus, TaskType
from app.services.tasks import TaskService, TaskStore
from app.workers import tasks as T
from app.workers import worker as W
from app.workers.tasks import RetryableError, TaskContext, TaskFailure, execute_task, register_handler
from tests.helpers import add_staff, create_admin, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, fast_argon, scalar, sql  # noqa: F401

pytestmark = pytest.mark.integration

TYPE = TaskType.MATCH_JOB  # the type used to host injected test handlers


@pytest.fixture(autouse=True)
def _restore_handlers() -> Any:
    yield
    register_handler(TYPE, None)


async def new_task(*, key: str | None = None, params: dict[str, Any] | None = None, created_by: uuid.UUID | None = None, company: uuid.UUID | None = None,
                   task_type: TaskType = TYPE) -> BackgroundTask:
    async with get_sessionmaker()() as s:
        task, created = await TaskService(s).create(task_type, params or {}, created_by_id=created_by, company_id=company, dedupe_key=key)
        assert created
        return task


async def fetch(task_id: uuid.UUID) -> BackgroundTask:
    async with get_sessionmaker()() as s:
        row = await s.get(BackgroundTask, task_id)
        assert row is not None
        return row


async def run(task: BackgroundTask) -> float | None:
    return await execute_task(task.id, get_sessionmaker(), get_cache())


# --- dedupe ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_an_active_task_with_the_same_key_is_returned_instead_of_a_duplicate(db: None) -> None:
    async with get_sessionmaker()() as s:
        svc = TaskService(s)
        first, created1 = await svc.create(TYPE, {"a": 1}, dedupe_key="k1")
        again, created2 = await svc.create(TYPE, {"a": 2}, dedupe_key="k1")
        other, created3 = await svc.create(TYPE, {}, dedupe_key="k2")
        nokey1, c4 = await svc.create(TYPE, {})
        nokey2, c5 = await svc.create(TYPE, {})
    assert (created1, created2, created3, c4, c5) == (True, False, True, True, True)
    assert again.id == first.id and again.params == {"a": 1}, "the original request wins"
    assert len({first.id, other.id, nokey1.id, nokey2.id}) == 4
    assert await scalar("SELECT count(*) FROM background_tasks") == 4


@pytest.mark.parametrize("final", ["COMPLETED", "FAILED"])
async def test_a_finished_task_no_longer_blocks_its_key(db: None, final: str) -> None:
    first = await new_task(key="k")
    await sql("UPDATE background_tasks SET status = :s WHERE id = :i", s=final, i=first.id)
    second = await new_task(key="k")
    assert second.id != first.id
    await sql("UPDATE background_tasks SET status = 'RUNNING' WHERE id = :i", i=second.id)
    async with get_sessionmaker()() as s:
        again, created = await TaskService(s).create(TYPE, {}, dedupe_key="k")
    assert created is False and again.id == second.id, "RUNNING counts as active"


async def test_concurrent_creations_with_one_key_produce_one_task(db: None) -> None:
    async def create() -> tuple[uuid.UUID, bool]:
        async with get_sessionmaker()() as s:
            task, created = await TaskService(s).create(TYPE, {}, dedupe_key="race")
            return task.id, created

    results = await asyncio.gather(*(create() for _ in range(6)))
    assert sum(1 for _, created in results if created) == 1
    assert len({tid for tid, _ in results}) == 1
    assert await scalar("SELECT count(*) FROM background_tasks WHERE dedupe_key = 'race'") == 1


async def test_submit_runs_new_tasks_and_skips_existing_ones(db: None) -> None:
    runs: list[int] = []

    async def handler(ctx: TaskContext) -> dict[str, Any]:
        runs.append(1)
        return {"ok": True}

    register_handler(TYPE, handler)
    from app.workers.dispatch import InlineDispatcher

    async with get_sessionmaker()() as s:
        svc = TaskService(s)
        task, created = await svc.submit(TYPE, {}, InlineDispatcher(), dedupe_key="once")
        assert created and task.status == TaskStatus.COMPLETED and task.result == {"ok": True}
        again, created2 = await svc.submit(TYPE, {}, InlineDispatcher(), dedupe_key="once")  # the first is finished: a new run is allowed
        assert created2 and again.id != task.id
    assert len(runs) == 2


# --- claiming ----------------------------------------------------------------------------------------------------------------------------------------------------


async def test_only_one_of_two_concurrent_claims_wins(db: None) -> None:
    task = await new_task()
    store = TaskStore(get_sessionmaker())
    results = await asyncio.gather(*(store.claim(task.id) for _ in range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    row = await fetch(task.id)
    assert (row.status, row.attempts, row.progress, row.stage) == (TaskStatus.RUNNING, 1, 0, "starting") and row.started_at is not None
    assert await store.claim(task.id) is None, "a RUNNING task cannot be claimed again"
    assert await store.claim(uuid.uuid4()) is None


async def test_claiming_resets_previous_error_state_and_counts_attempts(db: None) -> None:
    task = await new_task()
    await sql("UPDATE background_tasks SET error_code = 'X', error_message = 'old', progress = 77, stage = 'retrying', attempts = 1 WHERE id = :i", i=task.id)
    claimed = await TaskStore(get_sessionmaker()).claim(task.id)
    assert claimed is not None and (claimed.attempts, claimed.progress, claimed.error_code, claimed.error_message, claimed.stage) == (2, 0, None, None, "starting")


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED", "FAILED"])
async def test_only_pending_tasks_can_be_claimed(db: None, status: str) -> None:
    task = await new_task()
    await sql("UPDATE background_tasks SET status = :s WHERE id = :i", s=status, i=task.id)
    assert await TaskStore(get_sessionmaker()).claim(task.id) is None
    assert (await fetch(task.id)).attempts == 0


# --- execution outcomes ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_success_stores_the_result(db: None) -> None:
    seen: dict[str, Any] = {}

    async def handler(ctx: TaskContext) -> dict[str, Any]:
        seen.update(params=ctx.params, attempt=ctx.attempt, user=ctx.created_by_id, company=ctx.company_id, type=ctx.type, job_ctx=job_id_ctx.get(), task=ctx.task_id)
        await ctx.progress(40, "halfway")
        mid = await fetch(ctx.task_id)
        seen["mid"] = (mid.status, mid.progress, mid.stage)
        return {"answer": 42}

    register_handler(TYPE, handler)
    uid, cid = uuid.uuid4(), uuid.uuid4()
    async with get_sessionmaker()() as s:  # real owners so the foreign keys hold
        from app.db.models import Company, User
        from app.core.security import Role

        company = Company(name="Task Co", slug="task-co")
        s.add(company)
        await s.flush()
        user = User(email="t@test.example", password_hash="x", first_name="T", last_name="U", role=Role.RECRUITER, company_id=company.id)
        s.add(user)
        await s.commit()
        uid, cid = user.id, company.id
    task = await new_task(params={"x": 1}, created_by=uid, company=cid)
    assert await run(task) is None
    row = await fetch(task.id)
    assert (row.status, row.progress, row.stage, row.result, row.error_code, row.error_message) == (TaskStatus.COMPLETED, 100, "done", {"answer": 42}, None, None)
    assert row.started_at and row.finished_at and row.finished_at >= row.started_at and row.attempts == 1
    assert seen["params"] == {"x": 1} and seen["attempt"] == 1 and seen["user"] == uid and seen["company"] == cid and seen["type"] == TYPE
    assert seen["mid"] == (TaskStatus.RUNNING, 40, "halfway") and seen["job_ctx"] == str(task.id) and seen["task"] == task.id
    assert job_id_ctx.get() is None, "the correlation id is reset afterwards"


async def test_handlers_may_return_nothing(db: None) -> None:
    async def handler(ctx: TaskContext) -> None:
        return None

    register_handler(TYPE, handler)
    task = await new_task()
    await run(task)
    row = await fetch(task.id)
    assert row.status == TaskStatus.COMPLETED and row.result is None


async def test_progress_is_clamped_and_stages_truncated(db: None) -> None:
    async def handler(ctx: TaskContext) -> None:
        await ctx.progress(150, "x" * 200)
        row = await fetch(ctx.task_id)
        assert (row.progress, len(row.stage or "")) == (100, 60)
        await ctx.progress(-20, "low")
        assert (await fetch(ctx.task_id)).progress == 0

    register_handler(TYPE, handler)
    task = await new_task()
    await run(task)
    assert (await fetch(task.id)).status == TaskStatus.COMPLETED


async def test_task_failure_records_its_safe_message_and_does_not_retry(db: None) -> None:
    async def handler(ctx: TaskContext) -> None:
        raise TaskFailure("BAD_DOCUMENT", "The file could not be read")

    register_handler(TYPE, handler)
    task = await new_task()
    assert await run(task) is None
    row = await fetch(task.id)
    assert (row.status, row.error_code, row.error_message, row.stage, row.attempts) == (TaskStatus.FAILED, "BAD_DOCUMENT", "The file could not be read", "failed", 1)
    assert row.finished_at is not None and row.result is None


async def test_unexpected_exceptions_become_a_generic_internal_error_without_leaking_text(db: None, caplog: pytest.LogCaptureFixture) -> None:
    secret = "SECRET-DOCUMENT-CONTENT jane.doe@example.com"

    async def handler(ctx: TaskContext) -> None:
        raise ValueError(secret)

    register_handler(TYPE, handler)
    task = await new_task()
    assert await run(task) is None
    row = await fetch(task.id)
    assert (row.status, row.error_code) == (TaskStatus.FAILED, "INTERNAL_ERROR")
    assert row.error_message == "An unexpected error occurred while processing"
    dump = str(await sql("SELECT * FROM background_tasks WHERE id = :i", i=task.id))
    assert "SECRET-DOCUMENT" not in dump and "jane.doe" not in dump
    crashed = [r for r in caplog.records if r.getMessage() == "task crashed"]
    assert crashed and crashed[0].exc_info, "the traceback goes to the log, never into the task record"


async def test_retryable_errors_are_retried_a_bounded_number_of_times(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def handler(ctx: TaskContext) -> None:
        calls.append(ctx.attempt)
        raise RetryableError("embedding model unavailable", delay_seconds=7)

    register_handler(TYPE, handler)
    monkeypatch.setattr(get_settings(), "task_max_attempts", 3)
    task = await new_task()
    delay1 = await run(task)
    mid = await fetch(task.id)
    assert delay1 == 7 and (mid.status, mid.stage, mid.attempts, mid.error_message) == (TaskStatus.PENDING, "retrying", 1, "embedding model unavailable")
    delay2 = await run(task)
    assert delay2 == 14, "back-off grows with the attempt number"
    delay3 = await run(task)
    assert delay3 is None
    row = await fetch(task.id)
    assert (row.status, row.error_code, row.attempts) == (TaskStatus.FAILED, "RETRIES_EXHAUSTED", 3)
    assert row.error_message == "The operation kept failing; please try again later"
    assert calls == [1, 2, 3]
    assert await run(task) is None and calls == [1, 2, 3], "a failed task is never run again"


async def test_the_inline_dispatcher_honours_the_retry_bound(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers.dispatch import InlineDispatcher

    calls: list[int] = []

    async def handler(ctx: TaskContext) -> None:
        calls.append(ctx.attempt)
        raise RetryableError("flaky", delay_seconds=0)

    register_handler(TYPE, handler)
    monkeypatch.setattr(get_settings(), "task_max_attempts", 2)
    task = await new_task()
    await InlineDispatcher().dispatch(str(task.id))
    row = await fetch(task.id)
    assert calls == [1, 2] and (row.status, row.error_code) == (TaskStatus.FAILED, "RETRIES_EXHAUSTED")


async def test_a_retry_that_eventually_succeeds_completes_cleanly(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(ctx: TaskContext) -> dict[str, int]:
        if ctx.attempt < 2:
            raise RetryableError("try again", delay_seconds=1)
        return {"attempt": ctx.attempt}

    register_handler(TYPE, handler)
    monkeypatch.setattr(get_settings(), "task_max_attempts", 3)
    task = await new_task()
    assert await run(task) == 1
    assert await run(task) is None
    row = await fetch(task.id)
    assert (row.status, row.result, row.attempts, row.error_code, row.error_message) == (TaskStatus.COMPLETED, {"attempt": 2}, 2, None, None)


async def test_timeouts_fail_the_task(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(ctx: TaskContext) -> None:
        await asyncio.sleep(30)  # cancelled by the timeout long before this elapses

    register_handler(TYPE, handler)
    monkeypatch.setitem(T.TASK_TIMEOUTS, TYPE, 0.05)
    task = await new_task()
    assert await run(task) is None
    row = await fetch(task.id)
    assert (row.status, row.error_code, row.error_message) == (TaskStatus.FAILED, "TIMEOUT", "The operation took too long and was stopped")


async def test_duplicate_delivery_runs_the_handler_once(db: None) -> None:
    runs: list[int] = []
    gate = asyncio.Event()

    async def handler(ctx: TaskContext) -> None:
        runs.append(1)
        await gate.wait()

    register_handler(TYPE, handler)
    task = await new_task()
    first = asyncio.create_task(run(task))
    for _ in range(200):  # wait until the first delivery has claimed the task
        if (await fetch(task.id)).status == TaskStatus.RUNNING:
            break
        await asyncio.sleep(0)
    assert await run(task) is None  # the duplicate is skipped while the first is running
    gate.set()
    await first
    assert await run(task) is None  # ... and after it finished
    assert runs == [1] and (await fetch(task.id)).status == TaskStatus.COMPLETED


async def test_every_task_type_has_a_handler_path_and_a_timeout() -> None:
    assert set(T.HANDLER_PATHS) == set(TaskType) == set(T.TASK_TIMEOUTS)
    assert all(":" in path for path in T.HANDLER_PATHS.values())
    for t in (TaskType.MATCH_JOB, TaskType.MATCH_CANDIDATE, TaskType.REFRESH_EMBEDDINGS):
        assert callable(T.resolve_handler(t))

    async def override(ctx: TaskContext) -> None:
        return None

    register_handler(TYPE, override)
    assert T.resolve_handler(TYPE) is override
    register_handler(TYPE, None)
    assert T.resolve_handler(TYPE) is not override


# --- visibility through the API ---------------------------------------------------------------------------------------------------------------------------------------


async def test_task_status_is_visible_to_creator_admin_and_company_recruiters_only(client: AsyncClient) -> None:
    rec = await register_employer(client)
    rec2 = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    outsider = await register_employer(client)
    cand, other_cand = await register_candidate(client), await register_candidate(client)
    admin = await create_admin(client)
    uid, cid = uuid.UUID(rec["user"]["id"]), uuid.UUID(rec["company_id"])
    company_task = await new_task(created_by=uid, company=cid, params={"secret": "internal"}, key="vis-1")
    personal = await new_task(created_by=uuid.UUID(cand["user"]["id"]), key="vis-2")
    orphan = await new_task(key="vis-3")
    url = lambda t: f"{API}/tasks/{t.id}"  # noqa: E731
    for viewer in (rec, rec2, admin):
        assert (await client.get(url(company_task), headers=viewer["h"])).status_code == 200, viewer["user"]["role"]
    for viewer in (hm, outsider, cand, other_cand):
        assert_error(await client.get(url(company_task), headers=viewer["h"]), 404, "TASK_NOT_FOUND")
    assert (await client.get(url(personal), headers=cand["h"])).status_code == 200
    assert (await client.get(url(personal), headers=admin["h"])).status_code == 200
    for viewer in (other_cand, rec, outsider):
        assert_error(await client.get(url(personal), headers=viewer["h"]), 404, "TASK_NOT_FOUND")
    assert (await client.get(url(orphan), headers=admin["h"])).status_code == 200
    assert_error(await client.get(url(orphan), headers=rec["h"]), 404, "TASK_NOT_FOUND")
    assert_error(await client.get(url(company_task)), 401, "UNAUTHORIZED")
    assert_error(await client.get(f"{API}/tasks/{uuid.uuid4()}", headers=admin["h"]), 404, "TASK_NOT_FOUND")
    assert_error(await client.get(f"{API}/tasks/nope", headers=admin["h"]), 422, "VALIDATION_ERROR")


async def test_task_status_payload_shape(client: AsyncClient) -> None:
    rec = await register_employer(client)
    task = await new_task(created_by=uuid.UUID(rec["user"]["id"]), company=uuid.UUID(rec["company_id"]), params={"private": "x"}, key="shape")
    body = (await client.get(f"{API}/tasks/{task.id}", headers=rec["h"])).json()
    assert set(body) == {"id", "type", "status", "progress", "stage", "result", "error_code", "error_message", "attempts", "created_at", "started_at", "finished_at"}
    assert body["status"] == "PENDING" and body["progress"] == 0 and body["attempts"] == 0 and body["started_at"] is None
    assert "private" not in str(body) and "shape" not in str(body)


# --- the reaper ----------------------------------------------------------------------------------------------------------------------------------------------------------------


class Ctx(dict):  # type: ignore[type-arg]
    pass


def reaper_ctx() -> Ctx:
    return Ctx(redis=get_redis(), sessionmaker=get_sessionmaker())


async def aged_task(status: str, *, started_ago: int | None = None, created_ago: int = 0) -> uuid.UUID:
    tid = uuid.uuid4()
    await sql(
        "INSERT INTO background_tasks (id, type, status, params, created_at, started_at) VALUES (:i, 'MATCH_JOB', :s, '{}'::jsonb, now() - make_interval(secs => :c), "
        "CASE WHEN CAST(:st AS integer) IS NULL THEN NULL ELSE now() - make_interval(secs => CAST(:st AS integer)) END)",
        i=tid, s=status, c=created_ago, st=started_ago,
    )
    return tid


async def test_running_tasks_without_a_heartbeat_are_failed_as_worker_lost(db: None) -> None:
    dead = await aged_task("RUNNING", started_ago=W.ORPHAN_GRACE_SECONDS + 30)
    alive = await aged_task("RUNNING", started_ago=W.ORPHAN_GRACE_SECONDS + 30)
    fresh = await aged_task("RUNNING", started_ago=5)
    await get_redis().set(W.heartbeat_key(str(alive)), b"1", ex=30)
    await W.reap_stale_tasks(reaper_ctx())
    d = await fetch(dead)
    assert (d.status, d.error_code, d.error_message) == (TaskStatus.FAILED, "WORKER_LOST", "The worker stopped while processing; please retry") and d.finished_at is not None
    assert (await fetch(alive)).status == TaskStatus.RUNNING, "a live heartbeat protects the task"
    assert (await fetch(fresh)).status == TaskStatus.RUNNING, "inside the grace period nothing is concluded yet"


async def test_running_past_the_absolute_maximum_is_failed_even_with_a_heartbeat(db: None) -> None:
    runaway = await aged_task("RUNNING", started_ago=W.MAX_TASK_SECONDS + 120)
    await get_redis().set(W.heartbeat_key(str(runaway)), b"1", ex=30)
    await W.reap_stale_tasks(reaper_ctx())
    assert (await fetch(runaway)).error_code == "WORKER_LOST"


async def test_pending_tasks_whose_queue_message_is_gone_are_failed(db: None) -> None:
    lost = await aged_task("PENDING", created_ago=W.QUEUED_GRACE_SECONDS + 60)
    queued = await aged_task("PENDING", created_ago=W.QUEUED_GRACE_SECONDS + 60)
    young = await aged_task("PENDING", created_ago=30)
    await get_redis().set(f"arq:job:{queued}:abc123", b"payload")  # the ARQ message for this task still exists
    await W.reap_stale_tasks(reaper_ctx())
    row = await fetch(lost)
    assert (row.status, row.error_code, row.error_message) == (TaskStatus.FAILED, "WORKER_LOST", "The job queue lost this task before it started; please retry")
    assert (await fetch(queued)).status == TaskStatus.PENDING
    assert (await fetch(young)).status == TaskStatus.PENDING


async def test_finished_tasks_are_left_alone_and_a_second_pass_is_a_no_op(db: None) -> None:
    done = await aged_task("COMPLETED", started_ago=10_000, created_ago=10_000)
    failed = await aged_task("FAILED", started_ago=10_000, created_ago=10_000)
    dead = await aged_task("RUNNING", started_ago=W.ORPHAN_GRACE_SECONDS + 30)
    await W.reap_stale_tasks(reaper_ctx())
    before = [(await fetch(t)).finished_at for t in (done, failed, dead)]
    await W.reap_stale_tasks(reaper_ctx())
    assert [(await fetch(t)).finished_at for t in (done, failed, dead)] == before
    assert (await fetch(done)).status == TaskStatus.COMPLETED and (await fetch(failed)).error_code is None


async def test_nothing_is_reaped_when_redis_cannot_be_asked(db: None) -> None:
    from redis.asyncio import Redis

    dead = await aged_task("RUNNING", started_ago=W.ORPHAN_GRACE_SECONDS + 30)
    lost = await aged_task("PENDING", created_ago=W.QUEUED_GRACE_SECONDS + 60)
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    try:
        await W.reap_stale_tasks(Ctx(redis=broken, sessionmaker=get_sessionmaker()))
    finally:
        await broken.aclose()
    assert (await fetch(dead)).status == TaskStatus.RUNNING and (await fetch(lost)).status == TaskStatus.PENDING, "no evidence of a dead worker is not evidence of one"


# --- the run_task wrapper ---------------------------------------------------------------------------------------------------------------------------------------------------------


class RecordingRedis:
    """A stand-in for ARQ's pool: real Redis for the heartbeat keys, a recorder for ``enqueue_job``."""

    def __init__(self, *, fail_enqueue: bool = False) -> None:
        self.real = get_redis()
        self.sets: list[str] = []
        self.enqueued: list[tuple[Any, ...]] = []
        self.fail_enqueue = fail_enqueue
        self.beat = asyncio.Event()

    async def set(self, key: str, value: Any, ex: int | None = None) -> Any:
        self.sets.append(key)
        if len(self.sets) >= 3:
            self.beat.set()
        return await self.real.set(key, value, ex=ex)

    async def exists(self, key: str) -> int:
        return int(await self.real.exists(key))

    async def delete(self, key: str) -> int:
        return int(await self.real.delete(key))

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_enqueue:
            raise RedisError("queue down")
        self.enqueued.append((args, kwargs))


def worker_ctx(redis: Any) -> Ctx:
    return Ctx(redis=redis, sessionmaker=get_sessionmaker(), cache=get_cache())


async def test_run_task_keeps_a_heartbeat_while_the_handler_runs(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    redis = RecordingRedis()
    monkeypatch.setattr(W, "HEARTBEAT_INTERVAL_SECONDS", 0.005)
    observed: dict[str, Any] = {}

    async def handler(ctx: TaskContext) -> dict[str, bool]:
        key = W.heartbeat_key(str(ctx.task_id))
        observed["during"] = bool(await redis.exists(key))
        await asyncio.wait_for(redis.beat.wait(), timeout=5)  # returns once the heartbeat has been refreshed twice more
        return {"done": True}

    register_handler(TYPE, handler)
    task = await new_task()
    await W.run_task(worker_ctx(redis), str(task.id))
    key = W.heartbeat_key(str(task.id))
    assert observed["during"] is True and len(redis.sets) >= 3 and set(redis.sets) == {key}
    assert not await redis.exists(key), "the heartbeat disappears with the task"
    assert (await fetch(task.id)).status == TaskStatus.COMPLETED and redis.enqueued == []
    assert not [t for t in asyncio.all_tasks() if getattr(t.get_coro(), "__qualname__", "").endswith("run_task.<locals>.beat")], "the heartbeat coroutine was cancelled"


async def test_run_task_requeues_retryable_failures_with_a_delay(db: None) -> None:
    redis = RecordingRedis()

    async def handler(ctx: TaskContext) -> None:
        raise RetryableError("later", delay_seconds=12)

    register_handler(TYPE, handler)
    task = await new_task()
    await W.run_task(worker_ctx(redis), str(task.id))
    assert (await fetch(task.id)).status == TaskStatus.PENDING
    [(args, kwargs)] = redis.enqueued
    assert args == ("run_task", str(task.id)) and kwargs["_defer_by"] == 12 and kwargs["_job_id"].startswith(f"{task.id}:12:")


async def test_run_task_fails_the_task_when_the_requeue_is_impossible(db: None) -> None:
    redis = RecordingRedis(fail_enqueue=True)

    async def handler(ctx: TaskContext) -> None:
        raise RetryableError("later", delay_seconds=3)

    register_handler(TYPE, handler)
    task = await new_task()
    await W.run_task(worker_ctx(redis), str(task.id))
    row = await fetch(task.id)
    assert (row.status, row.error_code, row.error_message) == (TaskStatus.FAILED, "QUEUE_UNAVAILABLE", "Could not re-queue the task") and row.finished_at is not None


async def test_run_task_survives_a_dead_heartbeat_store(db: None) -> None:
    from redis.asyncio import Redis

    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)

    async def handler(ctx: TaskContext) -> dict[str, int]:
        return {"ok": 1}

    register_handler(TYPE, handler)
    task = await new_task()
    try:
        await W.run_task(worker_ctx(broken), str(task.id))
    finally:
        await broken.aclose()
    assert (await fetch(task.id)).status == TaskStatus.COMPLETED, "losing the heartbeat must not lose the work"


# --- housekeeping + sweep --------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_cleanup_removes_only_old_finished_tasks_and_expired_tokens(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    uid = uuid.UUID(cand["user"]["id"])
    old = datetime.now(UTC) - timedelta(days=45)
    recent = datetime.now(UTC) - timedelta(days=2)
    rows = {}
    for name, status, finished in (("old_done", "COMPLETED", old), ("old_failed", "FAILED", old), ("recent_done", "COMPLETED", recent), ("old_running", "RUNNING", None)):
        rows[name] = uuid.uuid4()
        await sql("INSERT INTO background_tasks (id, type, status, params, finished_at) VALUES (:i, 'MATCH_JOB', :s, '{}'::jsonb, :f)", i=rows[name], s=status, f=finished)
    await sql("INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at) VALUES (:u, :f, 'h-old', :e), (:u, :f, 'h-new', :n)", u=uid, f=uuid.uuid4(), e=old, n=datetime.now(UTC) + timedelta(days=5))
    await W.cleanup_old_records(reaper_ctx())
    remaining = {r[0] for r in await sql("SELECT id FROM background_tasks")}
    assert remaining == {rows["recent_done"], rows["old_running"]}
    assert {r[0] for r in await sql("SELECT token_hash FROM refresh_tokens WHERE token_hash IN ('h-old', 'h-new')")} == {"h-new"}


async def test_the_nightly_sweep_queues_one_deduplicated_match_per_live_job(client: AsyncClient) -> None:
    from arq import create_pool
    from arq.connections import RedisSettings

    from tests.helpers import create_job

    rec = await register_employer(client)
    live = [await create_job(client, rec, title=f"Sweep Role {i}", publish=True) for i in range(2)]
    await create_job(client, rec, title="Sweep Draft")
    await sql("DELETE FROM background_tasks")
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await W.sweep_matches(Ctx(redis=pool, sessionmaker=get_sessionmaker()))
        rows = await tasks_by_type("MATCH_JOB")
        assert sorted(r[1] for r in rows) == sorted(f"match-job:{j['id']}" for j in live) and {r[0] for r in rows} == {"PENDING"}
        queued = [k async for k in get_redis().scan_iter(match="arq:job:*")]
        assert len(queued) == 2, "one queue message per job"
        await W.sweep_matches(Ctx(redis=pool, sessionmaker=get_sessionmaker()))
        assert len(await tasks_by_type("MATCH_JOB")) == 2, "running the sweep again while the first batch is pending adds nothing"
    finally:
        await pool.aclose()


async def tasks_by_type(task_type: str) -> list[Any]:
    return await sql("SELECT status, dedupe_key FROM background_tasks WHERE type = :t", t=task_type)
