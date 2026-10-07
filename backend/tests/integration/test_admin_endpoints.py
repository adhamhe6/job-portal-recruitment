"""Admin & monitoring: RBAC, system status, tasks (list / retry), audit log, embeddings and matching status."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from app import __version__
from app.cache.redis_cache import get_redis
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.db.models import TaskType
from app.workers.tasks import TaskFailure, register_handler
from tests.helpers import (
    create_admin,
    create_job,
    fill_backend_profile,
    register_candidate,
    register_employer,
)
from tests.helpers_ops import (
    API,
    apply_to,
    company_with_staff,
    put_match,
    schedule,
    shortlisted,
    sql,
    utc_slot,
)

pytestmark = pytest.mark.integration

ADMIN_ENDPOINTS = [
    ("get", "/admin/system"),
    ("get", "/admin/tasks"),
    ("post", f"/admin/tasks/{uuid.uuid4()}/retry"),
    ("get", "/admin/audit"),
    ("post", "/admin/embeddings/refresh"),
    ("get", "/admin/embeddings/status"),
    ("get", "/admin/matching/status"),
]


@pytest.fixture(autouse=True)
def _reset_handlers():
    yield
    for t in TaskType:
        register_handler(t, None)


async def insert_task(
    type_: str, status: str, *, created_min_ago: float = 0, updated_min_ago: float | None = None, dedupe: str | None = None,
    error_code: str | None = None, company_id: str | None = None,
) -> uuid.UUID:  # fmt: skip
    upd = created_min_ago if updated_min_ago is None else updated_min_ago
    rows = await sql(
        "INSERT INTO background_tasks (id, type, status, progress, params, created_at, updated_at, dedupe_key, error_code, company_id) "
        "VALUES (gen_random_uuid(), :t, :s, 0, '{}'::jsonb, now() - make_interval(mins => :c), now() - make_interval(mins => :u), :d, :e, :co) RETURNING id",
        t=type_, s=status, c=created_min_ago, u=upd, d=dedupe, e=error_code, co=uuid.UUID(company_id) if company_id else None,
    )  # fmt: skip
    return rows[0][0]


@pytest.fixture
async def admin(client):
    return await create_admin(client)


async def test_everything_is_admin_only(client, admin):
    co = await company_with_staff(client)
    cand = await register_candidate(client)
    for method, path in ADMIN_ENDPOINTS:
        r = await getattr(client, method)(f"{API}{path}")
        assert r.status_code == 401, (path, r.status_code)
        for who in (co["rec"], co["hm"], cand):
            r = await getattr(client, method)(f"{API}{path}", headers=who["h"])
            assert r.status_code == 403, (path, who["user"]["role"], r.status_code, r.text)
    for method, path in ADMIN_ENDPOINTS[:2] + ADMIN_ENDPOINTS[3:]:
        r = await getattr(client, method)(f"{API}{path}", headers=admin["h"])
        assert r.status_code in (200, 202), (path, r.status_code, r.text)
    assert (
        await client.post(f"{API}{ADMIN_ENDPOINTS[2][1]}", headers=admin["h"])
    ).status_code == 404  # unknown task


# --------------------------------------------------------------------------------------------------------------------
# system
# --------------------------------------------------------------------------------------------------------------------
async def test_system_status_content(client, admin):
    r = await client.get(f"{API}/admin/system", headers=admin["h"])
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["status"] == "ok" and s["app"]["version"] == __version__ and s["app"]["environment"] == "test"
    assert s["app"]["job_backend"] == "inline" and s["app"]["python_version"].count(".") >= 1
    db = s["database"]
    assert db["ok"] is True and db["latency_ms"] >= 0 and db["pgvector_version"]
    assert (
        db["migration_revision"] == "0001"
        and db["migration_head"] == "0001"
        and db["migrations_current"] is True
    )
    rd = s["redis"]
    assert rd["ok"] is True and rd["latency_ms"] >= 0 and rd["queue_depth"] == 0
    emb = s["embedding"]
    st = get_settings()
    assert emb["model_name"] == st.embedding_model_name and emb["model_version"] == st.embedding_version
    assert (
        emb["dimension"] == st.embedding_dim == 256
        and emb["loaded"] is True
        and emb["error"] is None
        and emb["backend"] == "wordllama"
    )
    assert (
        s["worker"]["mode"] == "inline"
        and s["worker"]["alive"] is None
        and s["worker"]["health_key"] == "arq:queue:health-check"
    )
    assert (
        s["tasks"]["by_status"] == {"PENDING": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0}
        and s["tasks"]["stale_count"] == 0
    )
    # no secrets anywhere in the payload
    text = r.text
    for secret in (
        st.secret_key.get_secret_value(),
        "postgres:postgres",
        st.redis_url,
        st.database_url,
        st.first_admin_password.get_secret_value(),
    ):
        assert secret not in text


async def test_system_status_worker_liveness_and_queue_depth(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_backend", "arq")
    redis = get_redis()
    dead = (await client.get(f"{API}/admin/system", headers=admin["h"])).json()
    assert (
        dead["worker"]["mode"] == "arq" and dead["worker"]["alive"] is False and dead["status"] == "degraded"
    )
    # the real ARQ worker writes this key (see arq.worker.Worker.record_health) with a TTL of health_check_interval + 1
    await redis.set(
        "arq:queue:health-check",
        "Oct-07 12:00:00 j_complete=7 j_failed=2 j_retried=1 j_ongoing=3 queued=5",
        px=60_000,
    )
    await redis.zadd("arq:queue", {"job-a": 1, "job-b": 2, "job-c": 3})
    live = (await client.get(f"{API}/admin/system", headers=admin["h"])).json()
    w = live["worker"]
    assert w["alive"] is True and (
        w["jobs_complete"],
        w["jobs_failed"],
        w["jobs_retried"],
        w["jobs_ongoing"],
        w["queued"],
    ) == (7, 2, 1, 3, 5)
    assert 0 < w["health_ttl_seconds"] <= 60 and "j_complete=7" in w["last_check"]
    assert live["redis"]["queue_depth"] == 3 and live["status"] == "ok"
    await redis.delete("arq:queue:health-check")
    assert (await client.get(f"{API}/admin/system", headers=admin["h"])).json()["worker"]["alive"] is False


async def test_system_status_stale_tasks(client, admin):
    company = (await register_employer(client))["company_id"]
    old_pending = await insert_task("MATCH_JOB", "PENDING", created_min_ago=25, company_id=company)
    await insert_task("MATCH_JOB", "PENDING", created_min_ago=2)  # fresh
    stuck = await insert_task("PROCESS_RESUME", "RUNNING", created_min_ago=90, updated_min_ago=45)
    healthy = await insert_task("MATCH_CANDIDATE", "RUNNING", created_min_ago=90, updated_min_ago=1)
    await insert_task("MATCH_JOB", "COMPLETED", created_min_ago=300)
    await insert_task("MATCH_JOB", "FAILED", created_min_ago=300, error_code="BOOM")
    await get_redis().set(f"task:heartbeat:{stuck}", b"1", ex=30)  # its worker is still beating
    s = (await client.get(f"{API}/admin/system", headers=admin["h"])).json()
    t = s["tasks"]
    assert t["by_status"] == {"PENDING": 2, "RUNNING": 2, "COMPLETED": 1, "FAILED": 1}
    assert t["last_24h_by_status"] == t["by_status"]
    assert t["stale_pending_after_minutes"] == 10 and t["stale_running_after_minutes"] == 30
    assert t["stale_count"] == 2 and s["status"] == "degraded"
    ids = [x["id"] for x in t["stale"]]
    assert ids == [str(stuck), str(old_pending)]  # oldest first
    by_id = {x["id"]: x for x in t["stale"]}
    assert (
        by_id[str(old_pending)]["age_minutes"] == pytest.approx(25, abs=0.5)
        and by_id[str(old_pending)]["worker_heartbeat"] is None
    )
    assert (
        by_id[str(stuck)]["age_minutes"] == pytest.approx(45, abs=0.5)
        and by_id[str(stuck)]["worker_heartbeat"] is True
    )
    assert str(healthy) not in ids


async def test_system_status_degrades_gracefully_when_redis_or_embedder_fail(client, admin, monkeypatch):
    import app.services.admin as admin_service

    monkeypatch.setattr(
        admin_service,
        "get_redis",
        lambda: Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2),
    )

    def boom():
        raise RuntimeError("model file missing")

    monkeypatch.setattr("app.matching.embedder.get_embedder", boom)
    r = await client.get(f"{API}/admin/system", headers=admin["h"])
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["status"] == "degraded" and s["database"]["ok"] is True
    assert s["redis"]["ok"] is False and s["redis"]["latency_ms"] is None and s["redis"]["error"]
    assert (
        s["embedding"]["loaded"] is False
        and s["embedding"]["error"] == "RuntimeError"
        and "missing" not in r.text
    )  # no raw messages


# --------------------------------------------------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------------------------------------------------
async def test_task_listing_filters_and_pagination(client, admin):
    ids = [await insert_task("MATCH_JOB", "COMPLETED", created_min_ago=50 - i) for i in range(3)]
    await insert_task("PROCESS_RESUME", "FAILED", created_min_ago=5, error_code="PARSE_ERROR")
    await insert_task("MATCH_JOB", "PENDING", created_min_ago=1)
    await sql('UPDATE background_tasks SET result = \'{"secret": "payload"}\'::jsonb WHERE id = :i', i=ids[0])
    r = await client.get(f"{API}/admin/tasks", headers=admin["h"])
    body = r.json()
    assert (
        body["total"] == 5
        and body["items"][0]["status"] == "PENDING"
        and body["items"][1]["error_code"] == "PARSE_ERROR"
    )  # newest first
    created = [i["created_at"] for i in body["items"]]
    assert created == sorted(created, reverse=True)
    assert "payload" not in r.text and {i["id"]: i["has_result"] for i in body["items"]}[str(ids[0])] is True
    failed = (await client.get(f"{API}/admin/tasks", headers=admin["h"], params={"status": "FAILED"})).json()
    assert failed["total"] == 1 and failed["items"][0]["type"] == "PROCESS_RESUME"
    jobs = (
        await client.get(
            f"{API}/admin/tasks", headers=admin["h"], params={"type": "MATCH_JOB", "status": "COMPLETED"}
        )
    ).json()
    assert jobs["total"] == 3
    page2 = (
        await client.get(f"{API}/admin/tasks", headers=admin["h"], params={"page_size": 2, "page": 2})
    ).json()
    assert page2["pages"] == 3 and len(page2["items"]) == 2
    assert (
        await client.get(f"{API}/admin/tasks", headers=admin["h"], params={"status": "BOGUS"})
    ).status_code == 422
    assert (
        await client.get(f"{API}/admin/tasks", headers=admin["h"], params={"type": "BOGUS"})
    ).status_code == 422


async def test_retry_failed_task(client, admin):
    calls = []

    async def failing(ctx):
        calls.append("fail")
        raise TaskFailure("UPSTREAM_DOWN", "The upstream service was down")

    async def working(ctx):
        calls.append("ok")
        return {"recovered": True}

    register_handler(TaskType.MATCH_JOB, failing)
    from app.db.database import get_sessionmaker
    from app.services.tasks import TaskService
    from app.workers.dispatch import InlineDispatcher

    async with get_sessionmaker()() as s:
        task, _ = await TaskService(s).submit(
            TaskType.MATCH_JOB, {"job_id": str(uuid.uuid4())}, InlineDispatcher(), dedupe_key="retry-me"
        )
    row = (await sql("SELECT status, error_code, attempts FROM background_tasks WHERE id = :i", i=task.id))[0]
    assert tuple(row) == ("FAILED", "UPSTREAM_DOWN", 1)

    register_handler(TaskType.MATCH_JOB, working)
    r = await client.post(f"{API}/admin/tasks/{task.id}/retry", headers=admin["h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["status"] == "COMPLETED"
        and body["error_code"] is None
        and body["attempts"] == 1
        and body["has_result"] is True
    )
    assert calls == ["fail", "ok"]
    audit = await sql(
        "SELECT action, actor_id FROM audit_events WHERE entity_type = 'task' AND entity_id = :i", i=task.id
    )
    assert [tuple(a) for a in audit] == [("task.retried", uuid.UUID(admin["user"]["id"]))]
    # only FAILED tasks can be retried
    again = await client.post(f"{API}/admin/tasks/{task.id}/retry", headers=admin["h"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "TASK_NOT_RETRYABLE"
    pending = await insert_task("MATCH_JOB", "PENDING")
    running = await insert_task("MATCH_JOB", "RUNNING")
    for tid in (pending, running):
        r2 = await client.post(f"{API}/admin/tasks/{tid}/retry", headers=admin["h"])
        assert r2.status_code == 409 and r2.json()["error"]["code"] == "TASK_NOT_RETRYABLE"
    assert (await client.post(f"{API}/admin/tasks/{uuid.uuid4()}/retry", headers=admin["h"])).json()["error"][
        "code"
    ] == "TASK_NOT_FOUND"


async def test_retry_refuses_when_an_equivalent_task_is_active(client, admin):
    failed = await insert_task("MATCH_JOB", "FAILED", dedupe="match-job:42", error_code="X")
    await insert_task(
        "MATCH_JOB", "PENDING", dedupe="match-job:42"
    )  # someone already re-queued the same work
    r = await client.post(f"{API}/admin/tasks/{failed}/retry", headers=admin["h"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "TASK_ALREADY_ACTIVE"
    assert (await sql("SELECT status FROM background_tasks WHERE id = :i", i=failed))[0][
        0
    ] == "FAILED"  # untouched


async def test_retry_when_the_queue_is_down_marks_the_task_failed_again(client, admin):
    failed = await insert_task("MATCH_JOB", "FAILED", error_code="OLD")

    class Down:
        async def dispatch(self, task_id, *, defer_seconds=0):
            raise ServiceUnavailableError("Job queue unavailable")

    from app.main import app

    previous = app.state.dispatcher
    app.state.dispatcher = Down()
    try:
        r = await client.post(f"{API}/admin/tasks/{failed}/retry", headers=admin["h"])
    finally:
        app.state.dispatcher = previous
    assert r.status_code == 503
    row = (await sql("SELECT status, error_code FROM background_tasks WHERE id = :i", i=failed))[0]
    assert tuple(row) == ("FAILED", "QUEUE_UNAVAILABLE")


async def test_concurrent_retries_run_the_task_once(client, admin):
    runs = []

    async def work(ctx):
        runs.append(1)
        await asyncio.sleep(0.2)
        return {"n": 1}

    register_handler(TaskType.MATCH_JOB, work)
    failed = await insert_task("MATCH_JOB", "FAILED", error_code="OLD")
    rs = await asyncio.gather(
        *[client.post(f"{API}/admin/tasks/{failed}/retry", headers=admin["h"]) for _ in range(3)]
    )
    assert sorted(r.status_code for r in rs) == [200, 409, 409], [r.text for r in rs]
    assert len(runs) == 1


# --------------------------------------------------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------------------------------------------------
async def test_audit_log_filters(client, admin):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    other = await register_employer(client)
    await create_job(client, other, title="Other tenant job")
    sl = await shortlisted(client, rec)
    s, e = utc_slot(days=3)
    iv = (await schedule(client, rec, sl["app"]["id"], [rec2], start=s, end=e)).json()

    async def audit(**params):
        r = await client.get(f"{API}/admin/audit", headers=admin["h"], params=params)
        assert r.status_code == 200, r.text
        return r.json()

    everything = await audit(page_size=100)
    n_db = (await sql("SELECT count(*) FROM audit_events"))[0][0]
    assert everything["total"] == n_db and n_db >= 6
    stamps = [x["created_at"] for x in everything["items"]]
    assert stamps == sorted(stamps, reverse=True)  # newest first
    top = everything["items"][0]
    assert (
        top["action"] == "interview.scheduled"
        and top["entity_type"] == "interview"
        and top["entity_id"] == iv["id"]
    )
    assert (
        top["actor_id"] == rec["user"]["id"]
        and top["actor_name"] == "Riley Recruiter"
        and top["actor_email"] == rec["email"]
    )
    assert top["company_id"] == rec["company_id"] and top["metadata"]["application_id"] == sl["app"]["id"]

    assert [x["action"] for x in (await audit(action="interview.scheduled"))["items"]] == [
        "interview.scheduled"
    ]
    prefixed = await audit(action="application.*")
    assert prefixed["total"] >= 3 and all(x["action"].startswith("application.") for x in prefixed["items"])
    assert (await audit(action="interview.*"))["total"] == 1
    assert (await audit(action="inter%"))["total"] == 0  # wildcard characters are literal
    assert all(x["entity_type"] == "job" for x in (await audit(entity_type="job", page_size=100))["items"])
    assert (await audit(entity_id=iv["id"]))["total"] == 1
    mine = await audit(actor_id=rec["user"]["id"], page_size=100)
    assert mine["total"] >= 5 and all(x["actor_id"] == rec["user"]["id"] for x in mine["items"])
    tenant = await audit(company_id=other["company_id"])
    assert tenant["total"] >= 1 and all(x["company_id"] == other["company_id"] for x in tenant["items"])
    today = datetime.now(UTC).date()
    assert (await audit(from_date=today.isoformat(), to_date=today.isoformat()))["total"] == n_db
    assert (await audit(from_date=(today + timedelta(days=1)).isoformat()))["total"] == 0
    assert (await audit(to_date=(today - timedelta(days=1)).isoformat()))["total"] == 0
    first = await audit(page_size=2, page=1)
    second = await audit(page_size=2, page=2)
    assert (
        len(first["items"]) == 2
        and first["pages"] == -(-n_db // 2)
        and {x["id"] for x in first["items"]}.isdisjoint({x["id"] for x in second["items"]})
    )
    bad = await client.get(
        f"{API}/admin/audit", headers=admin["h"], params={"from_date": "2026-02-02", "to_date": "2026-02-01"}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_DATE_RANGE"
    assert (
        await client.get(f"{API}/admin/audit", headers=admin["h"], params={"actor_id": "nope"})
    ).status_code == 422


# --------------------------------------------------------------------------------------------------------------------
# embeddings & matching
# --------------------------------------------------------------------------------------------------------------------
async def test_embedding_status_refresh_and_dedupe(client, admin):
    st = get_settings()
    empty = (await client.get(f"{API}/admin/embeddings/status", headers=admin["h"])).json()
    for key in ("jobs", "candidates", "resume_results"):
        assert (
            empty[key]["total"],
            empty[key]["current"],
            empty[key]["outdated"],
            empty[key]["missing"],
        ) == (0, 0, 0, 0)
    assert empty["model_name"] == st.embedding_model_name and empty["dimension"] == 256
    assert empty["active_refresh_task_id"] is None and empty["last_refresh"] is None

    rec = await register_employer(client)
    job = await create_job(
        client, rec, publish=True
    )  # publishing schedules matching, which embeds the job (inline worker)
    draft = await create_job(client, rec, title="Draft role")
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)  # the profile change embeds the candidate
    blank = await register_candidate(client, first="No", last="Profile")  # no text at all: cannot be embedded
    s = (await client.get(f"{API}/admin/embeddings/status", headers=admin["h"])).json()
    assert (s["jobs"]["total"], s["jobs"]["current"], s["jobs"]["outdated"], s["jobs"]["missing"]) == (
        1,
        1,
        0,
        0,
    )  # drafts are not counted
    assert (s["candidates"]["total"], s["candidates"]["current"], s["candidates"]["missing"]) == (2, 1, 1)
    assert "PUBLISHED" in s["jobs"]["population"] and draft["status"] == "DRAFT" and blank["candidate_id"]

    # pretend the model changed: stamp both with an old version (and an old source hash so that a refresh must re-embed them)
    await sql(
        "UPDATE jobs SET embedding_version = 'v0', embedding_source_hash = 'old' WHERE id = :i",
        i=uuid.UUID(job["id"]),
    )
    await sql(
        "UPDATE candidate_profiles SET embedding_model = 'old-model', embedding_source_hash = 'old' WHERE id = :i",
        i=uuid.UUID(cand["candidate_id"]),
    )
    s = (await client.get(f"{API}/admin/embeddings/status", headers=admin["h"])).json()
    assert (s["jobs"]["current"], s["jobs"]["outdated"]) == (0, 1) and (
        s["candidates"]["current"],
        s["candidates"]["outdated"],
        s["candidates"]["missing"],
    ) == (0, 1, 1)

    r = await client.post(f"{API}/admin/embeddings/refresh", headers=admin["h"])
    assert r.status_code == 202, r.text
    assert (
        r.json()["created"] is True and r.json()["status"] == "COMPLETED"
    )  # the inline dispatcher already ran it
    after = (await client.get(f"{API}/admin/embeddings/status", headers=admin["h"])).json()
    assert (after["jobs"]["current"], after["jobs"]["outdated"]) == (1, 0) and (
        after["candidates"]["current"],
        after["candidates"]["outdated"],
    ) == (1, 0)
    last = after["last_refresh"]
    assert (
        last["task_id"] == r.json()["task_id"]
        and last["status"] == "COMPLETED"
        and last["result"]["jobs_reembedded"] == 2
    )
    # (a full refresh embeds the stale published job and also the draft that never had an embedding)
    assert last["result"]["candidates_reembedded"] == 1 and after["active_refresh_task_id"] is None
    audit = await sql("SELECT count(*) FROM audit_events WHERE action = 'embeddings.refresh_requested'")
    assert audit == [(1,)]

    # an active refresh is never duplicated
    active = await insert_task("REFRESH_EMBEDDINGS", "PENDING", dedupe="refresh-embeddings")
    dup = await client.post(f"{API}/admin/embeddings/refresh", headers=admin["h"])
    assert (
        dup.status_code == 202
        and dup.json()["created"] is False
        and dup.json()["task_id"] == str(active)
        and dup.json()["status"] == "PENDING"
    )
    assert (await client.get(f"{API}/admin/embeddings/status", headers=admin["h"])).json()[
        "active_refresh_task_id"
    ] == str(active)
    assert (await sql("SELECT count(*) FROM background_tasks WHERE type = 'REFRESH_EMBEDDINGS'")) == [(2,)]


async def test_matching_status(client, admin):
    st = get_settings()
    empty = (await client.get(f"{API}/admin/matching/status", headers=admin["h"])).json()
    assert (
        empty["pairs"] == 0
        and empty["last_generated_at"] is None
        and empty["by_version"] == []
        and empty["stale_by_version"] == 0
    )
    assert empty["matching_version"] and empty["embedding_model"] == st.embedding_model_name

    rec = await register_employer(client)
    j1 = await create_job(client, rec, publish=True, title="Matched job")
    await create_job(client, rec, publish=True, title="Unmatched job")
    await create_job(client, rec, title="Draft job")
    cands = [await register_candidate(client) for _ in range(3)]
    await apply_to(client, cands[0], j1["id"])
    await sql("DELETE FROM candidate_job_matches")  # start from a known state
    await sql("DELETE FROM background_tasks")
    for c in cands:
        await put_match(j1["id"], c["candidate_id"], 0.5)
    # two pairs computed with an older matching version
    await sql(
        "UPDATE candidate_job_matches SET matching_version = 'v0' WHERE candidate_id <> :c",
        c=uuid.UUID(cands[0]["candidate_id"]),
    )
    await insert_task("MATCH_JOB", "PENDING")
    await insert_task("MATCH_CANDIDATE", "RUNNING")
    await insert_task("MATCH_JOB", "FAILED", error_code="BOOM")
    await insert_task("PROCESS_RESUME", "PENDING")  # not a match task
    s = (await client.get(f"{API}/admin/matching/status", headers=admin["h"])).json()
    assert (s["pairs"], s["jobs_with_matches"], s["candidates_with_matches"]) == (3, 1, 3)
    assert s["stale_by_version"] == 2 and s["last_generated_at"]
    cur = [v for v in s["by_version"] if v["current"]]
    old = [v for v in s["by_version"] if not v["current"]]
    assert [(v["matching_version"], v["pairs"]) for v in cur] == [(s["matching_version"], 1)] and [
        (v["matching_version"], v["pairs"]) for v in old
    ] == [("v0", 2)]
    assert s["published_jobs"] == 2 and s["published_jobs_without_matches"] == 1
    assert s["tasks"]["active"] == 2 and s["tasks"]["last_24h_by_status"] == {
        "PENDING": 1,
        "RUNNING": 1,
        "COMPLETED": 0,
        "FAILED": 1,
    }
