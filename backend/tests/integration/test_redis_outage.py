"""Redis outage and queue failures: the API degrades (cache, limits, denylist off) but never fails, and nothing is lost silently."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cache import redis_cache
from app.cache.redis_cache import Cache, get_redis, redis_breaker
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.main import app
from app.workers.dispatch import ArqDispatcher, InlineDispatcher, build_dispatcher
from tests.helpers import create_job, fill_backend_profile, register_candidate, register_employer
from tests.helpers_spine import API, apply_job, assert_error, fast_argon, login, scalar, tasks  # noqa: F401

pytestmark = pytest.mark.integration

DEAD_URL = "redis://127.0.0.1:1/0"


@pytest.fixture
def dead_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[Redis]:
    """Swap the process-wide Redis client for one pointing at a closed port. Request ``client`` first so the database is reset on a live Redis."""
    bad = Redis.from_url(DEAD_URL, socket_connect_timeout=0.3, socket_timeout=0.3)
    monkeypatch.setattr(redis_cache, "_redis_client", bad)
    monkeypatch.setattr(redis_cache, "_cache", Cache(bad))
    yield bad
    redis_breaker.down_until = 0.0


class FailingDispatcher:
    async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None:
        raise ServiceUnavailableError("Job queue unavailable")


# --- Redis down ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_every_core_flow_works_without_redis(client: AsyncClient, dead_redis: Redis) -> None:
    rec = await register_employer(client)  # registration (rate limiter fails open)
    job = await create_job(client, rec)
    assert (
        await client.post(f"{API}/jobs/{job['id']}/publish", headers=rec["h"])
    ).status_code == 200  # cache invalidation fails open
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    # reads that normally hit the cache
    search = await client.get(f"{API}/search/jobs", params={"q": "backend"})
    assert search.status_code == 200 and search.json()["total"] == 1
    assert (await client.get(f"{API}/skills", params={"q": "postgres"})).json()["items"][0][
        "name"
    ] == "PostgreSQL"
    assert (await client.get(f"{API}/recommendations/jobs", headers=cand["h"])).status_code == 200
    # authentication: login, refresh, bearer tokens (denylist cannot be consulted), logout
    sess = await login(client, cand["email"])
    assert sess.status_code == 200
    token = sess.json()["access_token"]
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200
    assert (
        await client.post(f"{API}/auth/refresh", headers={"Cookie": f"tl_refresh={_cookie(sess)}"})
    ).status_code == 200
    # business actions
    app_ = await apply_job(client, cand, job["id"])
    assert (
        await client.post(
            f"{API}/applications/{app_['id']}/status", headers=rec["h"], json={"status": "SCREENING"}
        )
    ).status_code == 200
    assert (await client.get(f"{API}/notifications/unread-count", headers=cand["h"])).status_code == 200
    out = await client.post(
        f"{API}/auth/logout",
        headers={"Authorization": f"Bearer {token}", "Cookie": f"tl_refresh={_cookie(sess)}"},
    )
    assert out.status_code == 200
    assert redis_breaker.is_open()


def _cookie(resp: Any) -> str:
    return (
        next(h for h in resp.headers.get_list("set-cookie") if h.startswith("tl_refresh="))
        .split(";", 1)[0]
        .split("=", 1)[1]
    )


async def test_search_results_are_identical_with_and_without_the_cache(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = await register_employer(client)
    for i in range(3):
        await create_job(client, rec, title=f"Outage Role {i}", publish=True)
    with_cache = (await client.get(f"{API}/search/jobs", params={"q": "outage", "sort": "title"})).json()
    bad = Redis.from_url(DEAD_URL, socket_connect_timeout=0.3, socket_timeout=0.3)
    monkeypatch.setattr(redis_cache, "_redis_client", bad)
    monkeypatch.setattr(redis_cache, "_cache", Cache(bad))
    without = (await client.get(f"{API}/search/jobs", params={"q": "outage", "sort": "title"})).json()
    assert without == with_cache
    await bad.aclose()


async def test_brute_force_protection_is_off_while_redis_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, dead_redis: Redis
) -> None:
    """Documented trade-off of fail-open limiting: with the limiter's store unreachable, attempts are not throttled."""
    cand = await register_candidate(client)
    monkeypatch.setattr(get_settings(), "login_rate_limit_attempts", 2)
    codes = [(await login(client, cand["email"], "WrongPassword99")).status_code for _ in range(6)]
    assert codes == [401] * 6
    assert (await login(client, cand["email"])).status_code == 200


async def test_a_revoked_access_token_stays_valid_while_the_denylist_is_unreachable(
    client: AsyncClient,
) -> None:
    cand = await register_candidate(client)
    sess = await login(client, cand["email"])
    token = sess.json()["access_token"]
    assert (
        await client.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401  # denylisted while Redis is up
    # a token revoked *during* an outage cannot be denylisted; refresh tokens (PostgreSQL) are revoked regardless
    sess2 = await login(client, cand["email"])
    token2, cookie2 = sess2.json()["access_token"], _cookie(sess2)
    bad = Redis.from_url(DEAD_URL, socket_connect_timeout=0.3, socket_timeout=0.3)
    mp = pytest.MonkeyPatch()
    mp.setattr(redis_cache, "_redis_client", bad)
    mp.setattr(redis_cache, "_cache", Cache(bad))
    try:
        await client.post(
            f"{API}/auth/logout",
            headers={"Authorization": f"Bearer {token2}", "Cookie": f"tl_refresh={cookie2}"},
        )
        assert (
            await client.post(f"{API}/auth/refresh", headers={"Cookie": f"tl_refresh={cookie2}"})
        ).status_code == 401, "the long-lived credential is dead"
    finally:
        mp.undo()
        await bad.aclose()
        redis_breaker.down_until = 0.0


async def test_readiness_stays_up_when_only_redis_is_down(client: AsyncClient, dead_redis: Redis) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert (
        body["status"] == "ready"
        and body["checks"]["database"] == "ok"
        and body["checks"]["pgvector"] == "ok"
        and "unavailable" in body["checks"]["redis"]
    )
    assert (await client.get("/health")).status_code == 200


async def test_readiness_fails_when_the_database_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.main as main

    def broken() -> Any:
        raise RuntimeError("no database")

    monkeypatch.setattr(main, "get_engine", broken)
    r = await client.get("/health/ready")
    assert (
        r.status_code == 503
        and r.json()["status"] == "not_ready"
        and r.json()["checks"]["database"] == "unavailable"
    )
    assert (await client.get("/health")).status_code == 200, "liveness does not depend on dependencies"


# --- the queue is down ------------------------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def broken_queue(client: AsyncClient) -> Iterator[None]:
    previous = app.state.dispatcher
    app.state.dispatcher = FailingDispatcher()
    yield
    app.state.dispatcher = previous


async def test_user_actions_succeed_when_the_queue_is_unavailable(
    client: AsyncClient, broken_queue: None
) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    assert (
        await client.patch(
            f"{API}/candidates/me",
            headers=cand["h"],
            json={"headline": "Backend engineer", "summary": "Python and PostgreSQL every day."},
        )
    ).status_code == 200
    job = await create_job(client, rec)
    assert (await client.post(f"{API}/jobs/{job['id']}/publish", headers=rec["h"])).status_code == 200
    app_ = await apply_job(client, cand, job["id"])
    assert app_["status"] == "APPLIED"
    assert (
        await client.patch(f"{API}/jobs/{job['id']}", headers=rec["h"], json={"skills": [{"name": "Go"}]})
    ).status_code == 200
    # nothing was lost: the intents are recorded as FAILED tasks with a retryable code, never left PENDING forever
    rows = await tasks()
    assert {r.type for r in rows} >= {"MATCH_CANDIDATE", "MATCH_JOB"}
    assert {r.status for r in rows} == {"FAILED"} and {r.error_code for r in rows} == {"QUEUE_UNAVAILABLE"}
    assert {r.error_message for r in rows} == {"The job queue is unavailable; please retry shortly"}
    assert await scalar("SELECT count(*) FROM notifications WHERE type = 'APPLICATION_SUBMITTED'") == 2
    # reads still work, and report that nothing is being computed
    ranked = await client.get(f"{API}/matches/jobs/{job['id']}/candidates", headers=rec["h"])
    assert ranked.status_code == 200 and ranked.json()["meta"]["computing_task_id"] is None


async def test_explicit_refreshes_report_503_when_the_queue_is_unavailable_and_work_again_afterwards(
    client: AsyncClient,
) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    job = await create_job(client, rec, publish=True)
    previous = app.state.dispatcher
    app.state.dispatcher = FailingDispatcher()
    try:
        assert_error(
            await client.post(f"{API}/matches/jobs/{job['id']}/refresh", headers=rec["h"]),
            503,
            "SERVICE_UNAVAILABLE",
        )
        assert_error(
            await client.post(f"{API}/recommendations/refresh", headers=cand["h"]), 503, "SERVICE_UNAVAILABLE"
        )
    finally:
        app.state.dispatcher = previous
    failed = [r for r in await tasks() if r.status == "FAILED" and r.error_code == "QUEUE_UNAVAILABLE"]
    assert len(failed) >= 2
    again = await client.post(f"{API}/matches/jobs/{job['id']}/refresh", headers=rec["h"])
    assert again.status_code == 202, "a failed task does not block its dedupe key"
    assert (await client.get(f"{API}/tasks/{again.json()['task_id']}", headers=rec["h"])).json()[
        "status"
    ] == "COMPLETED"
    assert (await client.get(f"{API}/tasks/{failed[0].id}", headers=rec["h"])).status_code in (200, 404), (
        "failed tasks stay inspectable"
    )


async def test_the_real_arq_dispatcher_degrades_the_same_way(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    monkeypatch.setattr(get_settings(), "redis_url", DEAD_URL)
    previous = app.state.dispatcher
    app.state.dispatcher = ArqDispatcher(None)
    try:
        r = await client.patch(
            f"{API}/candidates/me",
            headers=cand["h"],
            json={"headline": "Backend engineer", "summary": "Python and PostgreSQL every day."},
        )
        assert r.status_code == 200
        job = await create_job(client, rec, publish=True)
        assert job["status"] == "PUBLISHED"
        assert_error(
            await client.post(f"{API}/matches/jobs/{job['id']}/refresh", headers=rec["h"]),
            503,
            "SERVICE_UNAVAILABLE",
        )
    finally:
        app.state.dispatcher = previous
    assert {r.error_code for r in await tasks()} == {"QUEUE_UNAVAILABLE"}


async def test_arq_dispatcher_maps_enqueue_failures_to_service_unavailable(db: None) -> None:
    class Pool:
        async def enqueue_job(self, *a: Any, **k: Any) -> None:
            raise RedisError("lost connection")

    with pytest.raises(ServiceUnavailableError):
        await ArqDispatcher(Pool()).dispatch(str(uuid.uuid4()))  # type: ignore[arg-type]


async def test_arq_dispatcher_enqueues_a_uniquely_identified_message_per_delivery(db: None) -> None:
    from arq import create_pool
    from arq.connections import RedisSettings

    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        dispatcher = ArqDispatcher(pool)
        tid = str(uuid.uuid4())
        await dispatcher.dispatch(tid)
        await dispatcher.dispatch(tid)
        await dispatcher.dispatch(tid, defer_seconds=30)
        keys = sorted([k.decode() async for k in get_redis().scan_iter(match=f"arq:job:{tid}:*")])
        assert len(keys) == 3 and len(set(keys)) == 3, (
            "re-delivery is allowed; TaskStore.claim() makes it harmless"
        )
        assert await get_redis().zcard("arq:queue") == 3
    finally:
        await pool.aclose()


async def test_the_app_starts_and_builds_a_dispatcher_without_contacting_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "job_backend", "arq")
    monkeypatch.setattr(get_settings(), "redis_url", DEAD_URL)
    dispatcher, close = await build_dispatcher()
    assert isinstance(dispatcher, ArqDispatcher) and dispatcher.pool is None
    await close()
    monkeypatch.setattr(get_settings(), "job_backend", "inline")
    inline, close2 = await build_dispatcher()
    assert isinstance(inline, InlineDispatcher)
    await close2()
