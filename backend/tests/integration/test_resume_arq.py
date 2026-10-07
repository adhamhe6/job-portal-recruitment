"""Résumé processing and bulk import through the real queue: API → Redis → ARQ worker → handler → PostgreSQL."""

from __future__ import annotations

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker

from app.cache.redis_cache import get_cache
from app.core.config import get_settings
from app.db.database import get_sessionmaker
from app.workers import worker as W
from app.workers.dispatch import ArqDispatcher
from tests import fixtures_resumes as fx
from tests.helpers import register_candidate, register_employer
from tests.resume_helpers import PDF, bulk_upload, upload

pytestmark = pytest.mark.integration


async def run_worker_burst() -> None:
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


async def test_resume_upload_is_processed_by_a_real_arq_worker(client):
    from app.main import app

    dispatcher = ArqDispatcher(None)
    app.state.dispatcher = dispatcher
    try:
        cand = await register_candidate(client)
        r = await upload(client, cand, fx.backend_pdf(), "cv.pdf", PDF)
        assert r.status_code == 202, r.text
        body = r.json()
        # queued, not run: the API returned before any processing happened
        assert body["status"] == "UPLOADED" and body["task_id"] and body["processing"]["task_status"] == "PENDING"
        assert (await client.get(f"/api/v1/resumes/{body['id']}/extracted", headers=cand["h"])).status_code == 409

        await run_worker_burst()

        done = (await client.get(f"/api/v1/resumes/{body['id']}", headers=cand["h"])).json()
        assert done["status"] == "PROCESSED" and done["processing"]["task_status"] == "COMPLETED" and done["processing"]["progress"] == 100
        assert done["processing"]["has_embedding"] is True
        task = (await client.get(f"/api/v1/tasks/{body['task_id']}", headers=cand["h"])).json()
        assert task["status"] == "COMPLETED" and task["result"]["skills_found"] >= 10
        ex = await client.get(f"/api/v1/resumes/{body['id']}/extracted", headers=cand["h"])
        assert ex.status_code == 200 and ex.json()["contact"]["name"] == "Jane Doe"
        prof = (await client.get("/api/v1/candidates/me", headers=cand["h"])).json()
        assert {s["skill"]["name"] for s in prof["skills"]} >= {"Python", "FastAPI"}
    finally:
        if dispatcher.pool is not None:
            await dispatcher.pool.aclose()


async def test_bulk_import_runs_in_the_arq_worker(client):
    from app.main import app

    dispatcher = ArqDispatcher(None)
    app.state.dispatcher = dispatcher
    try:
        rec = await register_employer(client)
        r = await bulk_upload(client, rec, [("a.pdf", fx.backend_pdf(), PDF), ("b.pdf", fx.malformed_pdf(), PDF)])
        assert r.status_code == 202 and r.json()["accepted"] == 2
        batch_id = r.json()["batch_id"]
        before = (await client.get(f"/api/v1/resumes/bulk-imports/{batch_id}", headers=rec["h"])).json()
        assert before["status"] == "PENDING" and before["counts"]["pending"] == 2

        await run_worker_burst()

        after = (await client.get(f"/api/v1/resumes/bulk-imports/{batch_id}", headers=rec["h"])).json()
        assert after["status"] == "COMPLETED" and after["counts"] == {"pending": 0, "created": 1, "duplicate": 0, "failed": 1}
        task = (await client.get(f"/api/v1/tasks/{r.json()['task_id']}", headers=rec["h"])).json()
        assert task["status"] == "COMPLETED" and task["progress"] == 100
    finally:
        if dispatcher.pool is not None:
            await dispatcher.pool.aclose()
