"""Matching under change: re-scoring, staleness, model upgrades, failures and idempotency (real database, inline worker)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.db.database import get_sessionmaker
from app.db.models import BackgroundTask, TaskStatus, TaskType
from app.matching.embedder import EmbeddingError, WordLlamaEmbedder, get_embedder
from app.services.tasks import TaskService
from app.workers.tasks import execute_task
from tests.helpers import create_job, fill_backend_profile, job_payload, register_candidate, register_employer
from tests.helpers_spine import (  # noqa: F401
    API,
    apply_job,
    assert_error,
    fast_argon,
    publish,
    scalar,
    sql,
    tasks,
)

pytestmark = pytest.mark.integration

RANK = f"{API}/matches/jobs"
ME = f"{API}/candidates/me"


async def ranked(client: AsyncClient, rec: dict[str, Any], job_id: str, **params: Any) -> dict[str, Any]:
    r = await client.get(f"{RANK}/{job_id}/candidates", headers=rec["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def small_world(client: AsyncClient, *, profile: bool = True, years: float = 5.0) -> dict[str, Any]:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client, first="Alex", last="Backend")
    if profile:
        await fill_backend_profile(client, cand, years=years)
    return {"rec": rec, "job": job, "cand": cand}


async def match_row(job_id: str, cand_id: str) -> Any:
    rows = await sql(
        "SELECT overall_score, required_skill_score, preferred_skill_score, job_hash, candidate_hash, embedding_version, embedding_model, generated_at, raw_cosine "
        "FROM candidate_job_matches WHERE job_id = :j AND candidate_id = :c",
        j=uuid.UUID(job_id),
        c=uuid.UUID(cand_id),
    )
    return rows[0] if rows else None


# --- re-scoring after changes -----------------------------------------------------------------------------------------------------------------------------


async def test_a_profile_change_rescores_the_candidate_against_live_jobs(client: AsyncClient) -> None:
    w = await small_world(client)
    before = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    assert before is not None and before.preferred_skill_score == 0.5
    r = await client.post(f"{ME}/skills", headers=w["cand"]["h"], json={"name": "Kubernetes"})
    assert r.status_code == 201
    after = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    assert (
        after.preferred_skill_score == 1.0
        and after.candidate_hash != before.candidate_hash
        and after.job_hash == before.job_hash
    )
    assert after.overall_score >= before.overall_score and after.generated_at > before.generated_at


async def test_editing_a_jobs_skills_rescores_every_candidate(client: AsyncClient) -> None:
    w = await small_world(client)
    before = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    assert before.required_skill_score == 1.0
    r = await client.patch(
        f"{API}/jobs/{w['job']['id']}",
        headers=w["rec"]["h"],
        json={"skills": [{"name": "Rust"}, {"name": "Go"}, {"name": "Python"}]},
    )
    assert r.status_code == 200
    after = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    assert after.required_skill_score == pytest.approx(1 / 3, abs=1e-3)
    assert after.job_hash != before.job_hash and after.overall_score < before.overall_score
    top = (await ranked(client, w["rec"], w["job"]["id"]))["items"][0]
    assert set(top["missing_required"]) == {"Rust", "Go"} and top["stale"] is False


async def test_a_non_matching_edit_leaves_scores_alone(client: AsyncClient) -> None:
    w = await small_world(client)
    before = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    await client.patch(
        f"{API}/jobs/{w['job']['id']}",
        headers=w["rec"]["h"],
        json={"department": "Platform", "benefits": "Free lunch", "salary_max": 99000},
    )
    await client.patch(ME, headers=w["cand"]["h"], json={"expected_salary": 70000})
    after = await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    assert (after.job_hash, after.candidate_hash, after.overall_score) == (
        before.job_hash,
        before.candidate_hash,
        before.overall_score,
    )


# --- staleness -----------------------------------------------------------------------------------------------------------------------------------------------


async def test_stale_rows_are_reported_and_repaired_in_the_background(client: AsyncClient) -> None:
    w = await small_world(client)
    cid, jid = w["cand"]["candidate_id"], w["job"]["id"]
    fresh = await ranked(client, w["rec"], jid)
    assert (
        fresh["meta"]["stale_rows"] == 0
        and fresh["items"][0]["stale"] is False
        and fresh["meta"]["computing_task_id"] is None
    )
    base_tasks = len(await tasks("MATCH_JOB"))
    # change the profile behind the application's back (no API, so no refresh was queued)
    await sql(
        "UPDATE candidate_profiles SET headline = 'Quantum chef', summary = 'Cooks with qubits.' WHERE id = :c",
        c=uuid.UUID(cid),
    )
    stale = await ranked(client, w["rec"], jid)
    assert stale["items"][0]["stale"] is True and stale["meta"]["stale_rows"] == 1
    assert stale["meta"]["computing_task_id"], "a background refresh was queued"
    assert len(await tasks("MATCH_JOB")) == base_tasks + 1
    repaired = await ranked(client, w["rec"], jid)
    assert (
        repaired["items"][0]["stale"] is False
        and repaired["meta"]["stale_rows"] == 0
        and repaired["meta"]["computing_task_id"] is None
    )
    assert len(await tasks("MATCH_JOB")) == base_tasks + 1, "a fresh ranking queues nothing"
    assert (await match_row(jid, cid)).candidate_hash != (await match_row(jid, cid)).job_hash


async def test_a_job_that_was_never_matched_gets_scored_on_first_read(client: AsyncClient) -> None:
    w = await small_world(client)
    await sql("DELETE FROM candidate_job_matches")
    empty = await ranked(client, w["rec"], w["job"]["id"])
    assert empty["items"] == [] and empty["meta"]["total_scored"] == 0 and empty["meta"]["computing_task_id"]
    again = await ranked(client, w["rec"], w["job"]["id"])
    assert [i["display_name"] for i in again["items"]] == ["Alex Backend"] and again["meta"][
        "computing_task_id"
    ] is None


async def test_stale_detail_is_recomputed_on_read(client: AsyncClient) -> None:
    w = await small_world(client)
    cid, jid = w["cand"]["candidate_id"], w["job"]["id"]
    before = await match_row(jid, cid)
    await sql("UPDATE candidate_profiles SET years_experience = 1 WHERE id = :c", c=uuid.UUID(cid))
    d = (await client.get(f"{RANK}/{jid}/candidates/{cid}", headers=w["rec"]["h"])).json()
    assert d["explanation"]["experience"]["status"] == "BELOW" and d["breakdown"]["experience"] < 1.0
    after = await match_row(jid, cid)
    assert after.candidate_hash != before.candidate_hash and after.overall_score < before.overall_score
    again = (await client.get(f"{RANK}/{jid}/candidates/{cid}", headers=w["rec"]["h"])).json()
    assert (
        again["explanation"] == d["explanation"]
        and again["overall_score"] == d["overall_score"] == after.overall_score
    )


async def test_embedding_version_bump_marks_everything_stale_and_re_embeds(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await small_world(client)
    cid, jid = w["cand"]["candidate_id"], w["job"]["id"]
    assert (await match_row(jid, cid)).embedding_version == "v1"
    emb = get_embedder()
    monkeypatch.setattr(emb, "version", "v2")
    stale = await ranked(client, w["rec"], jid)
    assert stale["items"][0]["stale"] is True and stale["meta"]["stale_rows"] == 1
    fresh = await ranked(
        client, w["rec"], jid
    )  # the queued run (inline) has re-scored with the new model version
    assert fresh["items"][0]["stale"] is False
    assert (await match_row(jid, cid)).embedding_version == "v2"
    assert await scalar("SELECT embedding_version FROM jobs WHERE id = :j", j=uuid.UUID(jid)) == "v2"
    assert (
        await scalar("SELECT embedding_version FROM candidate_profiles WHERE id = :c", c=uuid.UUID(cid))
        == "v2"
    )
    monkeypatch.setattr(emb, "version", "v1")  # rolling back flags the rows again
    assert (await ranked(client, w["rec"], jid))["items"][0]["stale"] is True


async def test_embedding_model_name_change_is_also_detected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await small_world(client)
    monkeypatch.setattr(get_embedder(), "name", "some-other-model")
    assert (await ranked(client, w["rec"], w["job"]["id"]))["items"][0]["stale"] is True
    assert (
        await match_row(w["job"]["id"], w["cand"]["candidate_id"])
    ).embedding_model == "some-other-model", "re-scored under the new model name"


async def run_task(task_type: TaskType, params: dict[str, Any] | None = None) -> BackgroundTask:
    from app.cache.redis_cache import get_cache

    async with get_sessionmaker()() as s:
        task, _ = await TaskService(s).create(
            task_type, params or {}, dedupe_key=f"test:{task_type.value}:{uuid.uuid4()}"
        )
    await execute_task(task.id, get_sessionmaker(), get_cache())
    async with get_sessionmaker()() as s:
        done = await s.get(BackgroundTask, task.id)
        assert done is not None
        return done


async def test_refresh_embeddings_task_re_embeds_only_what_changed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await small_world(client)
    await register_candidate(client)  # a second profile with no content: nothing to embed
    first = await run_task(TaskType.REFRESH_EMBEDDINGS)
    assert first.status == TaskStatus.COMPLETED and first.result == {
        "jobs_reembedded": 0,
        "candidates_reembedded": 0,
        "jobs_total": 1,
        "candidates_total": 2,
    }
    monkeypatch.setattr(get_embedder(), "version", "v9")
    second = await run_task(TaskType.REFRESH_EMBEDDINGS)
    assert second.status == TaskStatus.COMPLETED and second.result == {
        "jobs_reembedded": 1,
        "candidates_reembedded": 1,
        "jobs_total": 1,
        "candidates_total": 2,
    }
    assert second.progress == 100 and second.stage == "done"
    assert await scalar("SELECT count(*) FROM jobs WHERE embedding_version = 'v9'") == 1
    assert await scalar("SELECT count(*) FROM candidate_profiles WHERE embedding_version = 'v9'") == 1
    third = await run_task(TaskType.REFRESH_EMBEDDINGS)
    assert third.result["jobs_reembedded"] == 0 and third.result["candidates_reembedded"] == 0, (
        "re-running is cheap and idempotent"
    )
    assert w["rec"]


# --- who is in the pool -----------------------------------------------------------------------------------------------------------------------------------------


async def test_marketplace_opt_outs_are_excluded_unless_they_applied(client: AsyncClient) -> None:
    w = await small_world(client)
    jid, cid = w["job"]["id"], w["cand"]["candidate_id"]
    assert [i["has_applied"] for i in (await ranked(client, w["rec"], jid))["items"]] == [False]
    await client.patch(ME, headers=w["cand"]["h"], json={"is_searchable": False})
    assert (await ranked(client, w["rec"], jid))["items"] == [], "hidden from the recruiter's ranking at once"
    app = await apply_job(client, w["cand"], jid)
    row = (await ranked(client, w["rec"], jid))["items"][0]
    assert (
        row["has_applied"] is True
        and row["application_id"] == app["id"]
        and row["application_status"] == "APPLIED"
        and row["access"] == "FULL"
    )
    assert (await ranked(client, w["rec"], jid, applicants_only=True))["total"] == 1
    # withdrawing removes them from the pool again: the next match run deletes the stale row
    await client.post(f"{API}/applications/{app['id']}/withdraw", headers=w["cand"]["h"])
    await client.post(f"{RANK}/{jid}/refresh", headers=w["rec"]["h"])
    assert await match_row(jid, cid) is None
    assert (await ranked(client, w["rec"], jid))["items"] == []


async def test_applicants_are_always_scored_even_without_an_embedding(client: AsyncClient) -> None:
    w = await small_world(client, profile=False)
    await apply_job(client, w["cand"], w["job"]["id"])
    row = (await ranked(client, w["rec"], w["job"]["id"]))["items"][0]
    assert (
        row["has_applied"] is True
        and row["semantic_band"] == "UNKNOWN"
        and row["breakdown"]["semantic"] == 0.0
    )
    assert row["breakdown"]["required_skills"] == 0.0 and row["band"] == "WEAK"
    assert (
        await scalar(
            "SELECT embedding IS NULL FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(w["cand"]["candidate_id"]),
        )
        is True
    )


async def test_other_companies_imported_candidates_never_enter_the_pool(client: AsyncClient) -> None:
    from tests.helpers_spine import insert_imported_candidate

    w = await small_world(client, profile=False)
    other = await register_employer(client)
    mine = await insert_imported_candidate(w["rec"]["company_id"], name="Mine Imported", skills="Python")
    theirs = await insert_imported_candidate(other["company_id"], name="Theirs Imported", skills="Python")
    # imported profiles have no embedding yet: give them one by re-embedding, then re-match the job
    await run_task(TaskType.REFRESH_EMBEDDINGS)
    await client.post(f"{RANK}/{w['job']['id']}/refresh", headers=w["rec"]["h"])
    ids = {i["candidate_id"] for i in (await ranked(client, w["rec"], w["job"]["id"]))["items"]}
    assert mine in ids and theirs not in ids
    assert await match_row(w["job"]["id"], theirs) is None


# --- failure handling --------------------------------------------------------------------------------------------------------------------------------------------------


async def test_embedding_failures_never_corrupt_records_or_break_the_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await small_world(client)
    cid, jid = w["cand"]["candidate_id"], w["job"]["id"]
    snapshot = (
        await sql(
            "SELECT embedding::text, embedding_source_hash, embedding_generated_at FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(cid),
        )
    )[0]
    job_snapshot = (
        await sql("SELECT embedding::text, embedding_source_hash FROM jobs WHERE id = :j", j=uuid.UUID(jid))
    )[0]
    assert snapshot[0] and job_snapshot[0]

    def boom(self: WordLlamaEmbedder, texts: Any) -> Any:
        raise EmbeddingError("model exploded")

    monkeypatch.setattr(WordLlamaEmbedder, "embed", boom)
    # a profile edit still succeeds, the background run completes and the old vector is left exactly as it was
    r = await client.patch(
        ME,
        headers=w["cand"]["h"],
        json={
            "headline": "Backend engineer and gardener",
            "summary": "Now also growing tomatoes alongside Python APIs.",
        },
    )
    assert r.status_code == 200, r.text
    assert (
        await sql(
            "SELECT embedding::text, embedding_source_hash, embedding_generated_at FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(cid),
        )
    )[0] == snapshot
    last = (await tasks("MATCH_CANDIDATE"))[-1]
    assert last.status == "COMPLETED" and last.error_code is None
    # a job edit and a publish behave the same
    await client.patch(
        f"{API}/jobs/{jid}",
        headers=w["rec"]["h"],
        json={"title": "Backend Engineer II", "skills": [{"name": "Python"}]},
    )
    assert (
        await sql("SELECT embedding::text, embedding_source_hash FROM jobs WHERE id = :j", j=uuid.UUID(jid))
    )[0] == job_snapshot
    assert (await tasks("MATCH_JOB"))[-1].status == "COMPLETED"
    fresh_job = await create_job(client, w["rec"], title="Published While Broken", publish=True)
    assert (
        fresh_job["status"] == "PUBLISHED"
        and await scalar("SELECT embedding IS NULL FROM jobs WHERE id = :j", j=uuid.UUID(fresh_job["id"]))
        is True
    )
    # reads keep working
    assert (await ranked(client, w["rec"], jid))["total"] == 1
    assert (await client.get(f"{API}/recommendations/jobs", headers=w["cand"]["h"])).status_code == 200
    assert (await client.get(f"{API}/matches/me/jobs/{jid}", headers=w["cand"]["h"])).status_code == 200
    # once the model is back everything heals by itself
    monkeypatch.undo()
    await client.patch(ME, headers=w["cand"]["h"], json={"headline": "Backend engineer and gardener again"})
    assert (
        await sql("SELECT embedding_source_hash FROM candidate_profiles WHERE id = :c", c=uuid.UUID(cid))
    )[0][0] != snapshot[1]
    await client.post(f"{RANK}/{fresh_job['id']}/refresh", headers=w["rec"]["h"])
    assert (
        await scalar("SELECT embedding IS NOT NULL FROM jobs WHERE id = :j", j=uuid.UUID(fresh_job["id"]))
        is True
    )


async def test_refresh_embeddings_survives_a_broken_model(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await small_world(client)

    def boom(self: WordLlamaEmbedder, texts: Any) -> Any:
        raise EmbeddingError("model exploded")

    monkeypatch.setattr(get_embedder(), "version", "v3")
    monkeypatch.setattr(WordLlamaEmbedder, "embed", boom)
    done = await run_task(TaskType.REFRESH_EMBEDDINGS)
    assert (
        done.status == TaskStatus.COMPLETED
        and done.result["jobs_reembedded"] == 0
        and done.result["candidates_reembedded"] == 0
    )
    assert await scalar("SELECT count(*) FROM jobs WHERE embedding_version = 'v3'") == 0, (
        "nothing was half-updated"
    )


async def test_a_profile_without_enough_data_gets_no_embedding_and_no_crash(client: AsyncClient) -> None:
    rec = await register_employer(client)
    await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    r = await client.patch(ME, headers=cand["h"], json={"is_searchable": True, "salary_currency": "EUR"})
    assert r.status_code == 200
    task = (await tasks("MATCH_CANDIDATE"))[-1]
    assert task.status == "COMPLETED" and task.result == {"scored": 0, "top_score": None}
    assert (
        await scalar(
            "SELECT embedding IS NULL FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(cand["candidate_id"]),
        )
        is True
    )
    recs = (await client.get(f"{API}/recommendations/jobs", headers=cand["h"])).json()
    assert recs["items"] == [] and recs["meta"]["profile_ready"] is False and recs["meta"]["hint"]
    # as soon as there is something to say, the candidate is embedded and ranked
    await client.patch(ME, headers=cand["h"], json={"headline": "Backend engineer"})
    assert (
        await scalar(
            "SELECT embedding IS NOT NULL FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(cand["candidate_id"]),
        )
        is True
    )


# --- idempotency + the refresh endpoints -------------------------------------------------------------------------------------------------------------------------------


async def test_re_running_the_match_changes_nothing_but_the_timestamp(client: AsyncClient) -> None:
    w = await small_world(client)
    jid, cid = w["job"]["id"], w["cand"]["candidate_id"]
    first = await match_row(jid, cid)
    n_notifications = await scalar("SELECT count(*) FROM notifications")
    for _ in range(2):
        r = await client.post(f"{RANK}/{jid}/refresh", headers=w["rec"]["h"])
        assert r.status_code == 202
    again = await match_row(jid, cid)
    assert (again.overall_score, again.job_hash, again.candidate_hash, again.required_skill_score) == (
        first.overall_score,
        first.job_hash,
        first.candidate_hash,
        first.required_skill_score,
    )
    assert again.generated_at >= first.generated_at
    assert await scalar("SELECT count(*) FROM candidate_job_matches WHERE job_id = :j", j=uuid.UUID(jid)) == 1
    assert await scalar("SELECT count(*) FROM notifications") == n_notifications, "no duplicate notifications"
    for _ in range(2):
        await run_task(TaskType.MATCH_JOB, {"job_id": jid, "notify": True})
    assert await scalar("SELECT count(*) FROM notifications WHERE type = 'NEW_JOB_RECOMMENDATION'") <= 1


async def test_refresh_returns_a_task_reference_that_completes(client: AsyncClient) -> None:
    w = await small_world(client)
    r = await client.post(f"{RANK}/{w['job']['id']}/refresh", headers=w["rec"]["h"])
    assert r.status_code == 202
    ref = r.json()
    assert set(ref) == {"task_id", "status"} and ref["status"] == "PENDING"
    t = await client.get(f"{API}/tasks/{ref['task_id']}", headers=w["rec"]["h"])
    assert t.status_code == 200
    body = t.json()
    assert (body["type"], body["status"], body["progress"], body["stage"], body["error_code"]) == (
        "MATCH_JOB",
        "COMPLETED",
        100,
        "done",
        None,
    )
    assert body["result"]["scored"] == 1 and body["result"]["top_score"] > 0.5 and body["attempts"] == 1
    assert body["started_at"] and body["finished_at"] and body["created_at"]


async def test_refresh_while_a_run_is_active_returns_the_same_task(client: AsyncClient) -> None:
    w = await small_world(client)
    jid = w["job"]["id"]
    active = uuid.uuid4()
    await sql(
        "INSERT INTO background_tasks (id, type, status, params, dedupe_key) VALUES (:i, 'MATCH_JOB', 'PENDING', CAST(:p AS jsonb), :k)",
        i=active,
        p='{"job_id": "x"}',
        k=f"match-job:{jid}",
    )
    r = await client.post(f"{RANK}/{jid}/refresh", headers=w["rec"]["h"])
    assert r.status_code == 202 and r.json()["task_id"] == str(active)
    assert await scalar("SELECT status FROM background_tasks WHERE id = :i", i=active) == "PENDING", (
        "the existing task was not re-run or replaced"
    )


async def test_candidates_can_refresh_their_own_recommendations(client: AsyncClient) -> None:
    w = await small_world(client)
    r = await client.post(f"{API}/recommendations/refresh", headers=w["cand"]["h"])
    assert r.status_code == 202
    t = (await client.get(f"{API}/tasks/{r.json()['task_id']}", headers=w["cand"]["h"])).json()
    assert t["type"] == "MATCH_CANDIDATE" and t["status"] == "COMPLETED" and t["result"]["scored"] >= 1
    assert_error(await client.post(f"{API}/recommendations/refresh", headers=w["rec"]["h"]), 403, "FORBIDDEN")
    assert_error(await client.post(f"{API}/recommendations/refresh"), 401, "UNAUTHORIZED")


# --- notifications raised by matching -------------------------------------------------------------------------------------------------------------------------------------


async def test_publishing_a_job_tells_strong_candidates_and_the_owner_once(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand, years=5)
    draft = (
        await client.post(f"{API}/jobs", headers=rec["h"], json=job_payload("Notifiable Backend Role"))
    ).json()
    await publish(client, rec, draft["id"])
    mine = await sql(
        "SELECT title, job_id FROM notifications WHERE user_id = :u AND type = 'NEW_JOB_RECOMMENDATION'",
        u=uuid.UUID(cand["user"]["id"]),
    )
    assert len(mine) == 1 and mine[0][0] == "New job matches your profile" and str(mine[0][1]) == draft["id"]
    owner = await sql(
        "SELECT message FROM notifications WHERE user_id = :u AND type = 'NEW_CANDIDATE_MATCH'",
        u=uuid.UUID(rec["user"]["id"]),
    )
    assert len(owner) >= 1 and "match" in owner[0][0].lower()
    # pausing and resuming does not re-announce the job
    await client.post(f"{API}/jobs/{draft['id']}/pause", headers=rec["h"])
    await client.post(f"{API}/jobs/{draft['id']}/resume", headers=rec["h"])
    assert (
        await scalar(
            "SELECT count(*) FROM notifications WHERE user_id = :u AND type = 'NEW_JOB_RECOMMENDATION'",
            u=uuid.UUID(cand["user"]["id"]),
        )
        == 1
    )


async def test_a_weak_candidate_is_not_notified(client: AsyncClient) -> None:
    from tests.helpers_spine import nurse_profile

    rec = await register_employer(client)
    nurse = await register_candidate(client)
    await nurse_profile(client, nurse)
    await create_job(client, rec, publish=True)
    assert (
        await scalar(
            "SELECT count(*) FROM notifications WHERE user_id = :u AND type = 'NEW_JOB_RECOMMENDATION'",
            u=uuid.UUID(nurse["user"]["id"]),
        )
        == 0
    )
