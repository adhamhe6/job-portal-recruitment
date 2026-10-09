"""Who sees what of a job: public vs staff representations, candidate-aware fields and saved jobs."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import (
    add_staff,
    create_admin,
    create_job,
    fill_backend_profile,
    register_candidate,
    register_employer,
)
from tests.helpers_spine import (
    API,
    apply_job,
    assert_error,
    expire_deadline,
    scalar,
    set_job_status,
    walk,
)

pytestmark = pytest.mark.e2e

INTERNAL = {
    "created_by_id",
    "hiring_manager_id",
    "hiring_manager_name",
    "application_count",
    "embedding_ready",
    "allowed_transitions",
    "closed_at",
    "company_id",
}
STAFF_ONLY = INTERNAL


async def get_job(client: AsyncClient, job_id: str, who: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    return await client.get(f"{API}/jobs/{job_id}", headers=who["h"] if who else None)


# --- anonymous / public representation ----------------------------------------------------------------------------------------------------


async def test_anonymous_visitors_see_only_published_jobs(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec)
    url = job["id"]
    assert_error(await get_job(client, url), 404, "JOB_NOT_FOUND")  # draft
    await client.post(f"{API}/jobs/{url}/publish", headers=rec["h"])
    assert (await get_job(client, url)).status_code == 200
    for action, expected in (("pause", 404), ("resume", 200), ("close", 404), ("archive", 404)):
        await client.post(f"{API}/jobs/{url}/{action}", headers=rec["h"])
        r = await get_job(client, url)
        assert r.status_code == expected, (action, r.text)
        if expected == 404:
            assert_error(r, 404, "JOB_NOT_FOUND")
    assert_error(await get_job(client, str(uuid.uuid4())), 404, "JOB_NOT_FOUND")
    assert_error(await get_job(client, "nope"), 422, "VALIDATION_ERROR")


async def test_public_representation_hides_internal_fields(client: AsyncClient) -> None:
    rec = await register_employer(client, "Public View Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    job = await create_job(client, rec, publish=True, hiring_manager_id=hm["id"])
    r = await get_job(client, job["id"])
    body = r.json()
    assert (
        r.status_code == 200
        and body["status"] == "PUBLISHED"
        and body["can_apply"] is True
        and body["apply_blocked_reason"] is None
    )
    keys = {k for k, _ in walk(body)}
    assert not keys & STAFF_ONLY, keys & STAFF_ONLY
    assert set(body["company"]) == {
        "id",
        "name",
        "slug",
        "description",
        "industry",
        "website",
        "location",
        "size",
        "logo_url",
    }
    assert body["is_saved"] is None and body["my_application_id"] is None and body["match"] is None
    assert (
        rec["email"] not in r.text
        and hm["email"] not in r.text
        and rec["user"]["id"] not in r.text
        and hm["id"] not in r.text
    )
    assert {s["skill"]["name"] for s in body["skills"]} >= {"Python", "FastAPI"}


async def test_expired_deadline_keeps_the_job_visible_but_closed_to_applications(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    await expire_deadline(job["id"])
    body = (await get_job(client, job["id"])).json()
    assert body["can_apply"] is False and "deadline" in body["apply_blocked_reason"]
    # an inclusive deadline: today is still open
    await expire_deadline(job["id"], days_ago=0)
    assert (await get_job(client, job["id"])).json()["can_apply"] is True


# --- staff representation ---------------------------------------------------------------------------------------------------------------------


async def test_owning_staff_see_the_internal_representation(client: AsyncClient) -> None:
    rec = await register_employer(client)
    rec2 = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    job = await create_job(client, rec, publish=True, hiring_manager_id=hm["id"])
    await apply_job(client, cand, job["id"])
    for who in (rec, rec2):
        body = (await get_job(client, job["id"], who)).json()
        assert set(body) >= INTERNAL
        assert (
            body["application_count"] == 1
            and body["allowed_transitions"] == ["CLOSED", "PAUSED"]
            and body["hiring_manager_id"] == hm["id"]
        )
        assert body["created_by_id"] == rec["user"]["id"] and body["embedding_ready"] is True
    assigned = (await get_job(client, job["id"], hm)).json()
    assert set(assigned) >= INTERNAL and assigned["allowed_transitions"] == [], (
        "a hiring manager may read but not transition"
    )


async def test_drafts_are_visible_to_their_company_and_to_nobody_else(client: AsyncClient) -> None:
    rec = await register_employer(client)
    outsider = await register_employer(client)
    hm_assigned = await add_staff(client, rec, "HIRING_MANAGER")
    hm_other = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    admin = await create_admin(client)
    draft = await create_job(client, rec, hiring_manager_id=hm_assigned["id"])
    for who in (rec, hm_assigned, admin):
        assert (await get_job(client, draft["id"], who)).json()["status"] == "DRAFT"
    for who in (hm_other, outsider, cand, None):
        assert_error(await get_job(client, draft["id"], who), 404, "JOB_NOT_FOUND")


async def test_published_jobs_look_public_to_everyone_outside_the_owning_team(client: AsyncClient) -> None:
    rec = await register_employer(client)
    outsider = await register_employer(client)
    hm_other = await add_staff(client, rec, "HIRING_MANAGER")
    job = await create_job(client, rec, publish=True)
    for who in (outsider, hm_other):
        body = (await get_job(client, job["id"], who)).json()
        assert not set(body) & STAFF_ONLY and body["status"] == "PUBLISHED"


# --- candidate-aware fields ------------------------------------------------------------------------------------------------------------------------------


async def test_candidate_sees_saved_application_and_match_state(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    fresh = (await get_job(client, job["id"], cand)).json()
    assert (
        fresh["is_saved"],
        fresh["my_application_id"],
        fresh["my_application_status"],
        fresh["match"],
        fresh["can_apply"],
    ) == (False, None, None, None, True)
    await fill_backend_profile(client, cand)
    matched = (await get_job(client, job["id"], cand)).json()
    assert matched["match"]["band"] in {"STRONG", "GOOD"} and 0.5 < matched["match"]["overall_score"] <= 1
    assert set(matched["match"]) == {"overall_score", "band"}
    await client.put(f"{API}/jobs/{job['id']}/save", headers=cand["h"])
    assert (await get_job(client, job["id"], cand)).json()["is_saved"] is True
    app = await apply_job(client, cand, job["id"])
    applied = (await get_job(client, job["id"], cand)).json()
    assert applied["my_application_id"] == app["id"] and applied["my_application_status"] == "APPLIED"
    assert (
        applied["can_apply"] is False
        and applied["apply_blocked_reason"] == "You have already applied to this job"
    )
    # after withdrawing, the candidate may apply again
    await client.post(f"{API}/applications/{app['id']}/withdraw", headers=cand["h"])
    again = (await get_job(client, job["id"], cand)).json()
    assert again["my_application_id"] is None and again["can_apply"] is True
    # other candidates are unaffected
    other = (await get_job(client, job["id"], await register_candidate(client))).json()
    assert other["is_saved"] is False and other["my_application_id"] is None


# --- saving jobs ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_save_and_unsave_are_idempotent(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    url = f"{API}/jobs/{job['id']}/save"
    for _ in range(3):
        r = await client.put(url, headers=cand["h"])
        assert r.status_code == 200 and r.json() == {"message": "Saved"}
    assert await scalar("SELECT count(*) FROM saved_jobs WHERE job_id = :j", j=uuid.UUID(job["id"])) == 1
    for _ in range(2):
        r = await client.delete(url, headers=cand["h"])
        assert r.status_code == 200 and r.json() == {"message": "Removed"}
    assert await scalar("SELECT count(*) FROM saved_jobs") == 0
    assert (
        await client.delete(f"{API}/jobs/{uuid.uuid4()}/save", headers=cand["h"])
    ).status_code == 200  # unsaving something unknown is a no-op


async def test_only_published_jobs_can_be_saved(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec)
    cand = await register_candidate(client)
    url = f"{API}/jobs/{job['id']}/save"
    for status in ("DRAFT", "PAUSED", "CLOSED", "ARCHIVED"):
        await set_job_status(job["id"], status)
        assert_error(await client.put(url, headers=cand["h"]), 404, "JOB_NOT_FOUND")
    assert_error(await client.put(f"{API}/jobs/{uuid.uuid4()}/save", headers=cand["h"]), 404, "JOB_NOT_FOUND")
    assert await scalar("SELECT count(*) FROM saved_jobs") == 0


async def test_only_candidates_can_save_jobs(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    admin = await create_admin(client)
    job = await create_job(client, rec, publish=True)
    for who in (rec, hm, admin):
        assert_error(await client.put(f"{API}/jobs/{job['id']}/save", headers=who["h"]), 403, "FORBIDDEN")
        assert_error(await client.delete(f"{API}/jobs/{job['id']}/save", headers=who["h"]), 403, "FORBIDDEN")
    assert_error(await client.put(f"{API}/jobs/{job['id']}/save"), 401, "UNAUTHORIZED")


async def test_saved_jobs_list(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand, other = await register_candidate(client), await register_candidate(client)
    jobs = [await create_job(client, rec, publish=True, title=f"Saved Candidate Role {i}") for i in range(3)]
    for j in jobs[:2]:
        await client.put(f"{API}/jobs/{j['id']}/save", headers=cand["h"])
    await client.put(f"{API}/jobs/{jobs[2]['id']}/save", headers=other["h"])
    r = await client.get(f"{API}/candidates/me/saved-jobs", headers=cand["h"])
    assert r.status_code == 200
    body = r.json()
    assert (
        body["total"] == 2
        and {i["id"] for i in body["items"]} == {jobs[0]["id"], jobs[1]["id"]}
        and all(i["is_saved"] is True for i in body["items"])
    )
    assert (
        await client.get(f"{API}/candidates/me/saved-jobs", headers=cand["h"], params={"page_size": 1})
    ).json()["pages"] == 2
    # jobs that stop being live drop out of the list (the saved row itself is kept)
    await client.post(f"{API}/jobs/{jobs[0]['id']}/close", headers=rec["h"])
    assert [
        i["id"]
        for i in (await client.get(f"{API}/candidates/me/saved-jobs", headers=cand["h"])).json()["items"]
    ] == [jobs[1]["id"]]
    assert (
        await scalar(
            "SELECT count(*) FROM saved_jobs WHERE candidate_id = :c", c=uuid.UUID(cand["candidate_id"])
        )
        == 2
    )
    assert_error(await client.get(f"{API}/candidates/me/saved-jobs", headers=rec["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(f"{API}/candidates/me/saved-jobs"), 401, "UNAUTHORIZED")
