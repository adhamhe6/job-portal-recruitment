"""Job postings: creation, validation, skills, the lifecycle state machine, editing and deletion."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.db.models import JobStatus
from app.services.jobs import EDITABLE_STATUSES, JOB_TRANSITIONS
from tests.helpers import add_staff, create_admin, create_job, job_payload, register_candidate, register_employer
from tests.helpers_spine import (  # noqa: F401
    API,
    assert_error,
    expire_deadline,
    fast_argon,
    future,
    scalar,
    set_job_status,
    sql,
    tasks,
)

pytestmark = pytest.mark.e2e

JOBS = f"{API}/jobs"
ENDPOINTS = {"publish": JobStatus.PUBLISHED, "pause": JobStatus.PAUSED, "resume": JobStatus.PUBLISHED, "close": JobStatus.CLOSED, "archive": JobStatus.ARCHIVED}


def skills_of(job: dict[str, Any]) -> dict[str, str]:
    return {s["skill"]["name"]: s["requirement"] for s in job["skills"]}


async def post_job(client: AsyncClient, rec: dict[str, Any], **overrides: Any):  # type: ignore[no-untyped-def]
    return await client.post(JOBS, headers=rec["h"], json=job_payload(**overrides))


# --- create -----------------------------------------------------------------------------------------------------------------------


async def test_create_starts_as_a_draft_owned_by_the_creator(client: AsyncClient) -> None:
    rec = await register_employer(client, "Draft Co")
    r = await post_job(client, rec, title="  Senior   Backend   Engineer ")
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "DRAFT" and job["title"] == "Senior Backend Engineer" and job["published_at"] is None and job["closed_at"] is None
    assert job["company_id"] == rec["company_id"] and job["created_by_id"] == rec["user"]["id"] and job["company"]["name"] == "Draft Co"
    assert job["allowed_transitions"] == ["ARCHIVED", "PUBLISHED"] and job["application_count"] == 0 and job["can_apply"] is False
    assert skills_of(job) == {"Python": "REQUIRED", "FastAPI": "REQUIRED", "PostgreSQL": "REQUIRED", "Docker": "REQUIRED", "Redis": "PREFERRED", "Kubernetes": "PREFERRED"}
    assert [s["skill"]["name"] for s in job["skills"]][:4] == ["Docker", "FastAPI", "PostgreSQL", "Python"], "required first, then alphabetical"
    assert job["salary_currency"] == "USD" and float(job["min_experience_years"]) == 3.0
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'job.created' AND entity_id = :i", i=uuid.UUID(job["id"])) == 1
    assert await scalar("SELECT skills_text FROM jobs WHERE id = :i", i=uuid.UUID(job["id"])) == "Docker, FastAPI, Kubernetes, PostgreSQL, Python, Redis"


async def test_minimal_job_and_defaults(client: AsyncClient) -> None:
    rec = await register_employer(client)
    r = await client.post(JOBS, headers=rec["h"], json={"title": "Office Manager", "description": "Keep the office running smoothly every day."})
    assert r.status_code == 201
    job = r.json()
    assert (job["employment_type"], job["workplace_type"], float(job["min_experience_years"]), job["skills"], job["location"]) == ("FULL_TIME", "ONSITE", 0.0, [], None)


async def test_who_can_create_jobs(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    admin = await create_admin(client)
    assert_error(await post_job(client, hm), 403, "FORBIDDEN")
    assert_error(await post_job(client, cand), 403, "FORBIDDEN")
    assert_error(await client.post(JOBS, json=job_payload()), 401, "UNAUTHORIZED")
    # platform admins act on behalf of a company
    assert_error(await client.post(JOBS, headers=admin["h"], json=job_payload()), 422, "COMPANY_REQUIRED")
    assert_error(await client.post(JOBS, headers=admin["h"], params={"company_id": str(uuid.uuid4())}, json=job_payload()), 404, "COMPANY_NOT_FOUND")
    r = await client.post(JOBS, headers=admin["h"], params={"company_id": rec["company_id"]}, json=job_payload("Admin Created Role"))
    assert r.status_code == 201 and r.json()["company_id"] == rec["company_id"] and r.json()["created_by_id"] == admin["user"]["id"]
    # a recruiter cannot smuggle a different tenant in through the query string
    other = await register_employer(client)
    r = await client.post(JOBS, headers=other["h"], params={"company_id": rec["company_id"]}, json=job_payload("Tenant Hop"))
    assert r.status_code == 201 and r.json()["company_id"] == other["company_id"]


# --- duplicates --------------------------------------------------------------------------------------------------------------------


async def test_duplicate_live_jobs_are_rejected_until_the_first_is_out_of_play(client: AsyncClient) -> None:
    rec = await register_employer(client)
    first = (await post_job(client, rec, title="Data Engineer", location="Berlin, Germany", workplace_type="HYBRID")).json()
    for variant in ({"title": "data engineer"}, {"title": "DATA   ENGINEER"}, {"location": "BERLIN, GERMANY"}):
        assert_error(await post_job(client, rec, **{"title": "Data Engineer", "location": "Berlin, Germany", "workplace_type": "HYBRID", **variant}), 409, "DUPLICATE_JOB")
    # a genuinely different posting is fine
    assert (await post_job(client, rec, title="Data Engineer", location="Munich, Germany", workplace_type="HYBRID")).status_code == 201
    assert (await post_job(client, rec, title="Data Engineer", location="Berlin, Germany", workplace_type="REMOTE")).status_code == 201
    # duplicates are detected for every live status ...
    await set_job_status(first["id"], "PUBLISHED")
    assert_error(await post_job(client, rec, title="Data Engineer", location="Berlin, Germany", workplace_type="HYBRID"), 409, "DUPLICATE_JOB")
    await set_job_status(first["id"], "PAUSED")
    assert_error(await post_job(client, rec, title="Data Engineer", location="Berlin, Germany", workplace_type="HYBRID"), 409, "DUPLICATE_JOB")
    # ... and the slot is released when the original is closed
    await set_job_status(first["id"], "CLOSED")
    assert (await post_job(client, rec, title="Data Engineer", location="Berlin, Germany", workplace_type="HYBRID")).status_code == 201


async def test_a_duplicate_is_allowed_once_the_first_is_archived(client: AsyncClient) -> None:
    rec = await register_employer(client)
    first = (await post_job(client, rec, title="Site Reliability Engineer")).json()
    assert_error(await post_job(client, rec, title="Site Reliability Engineer"), 409, "DUPLICATE_JOB")
    assert (await client.post(f"{JOBS}/{first['id']}/archive", headers=rec["h"])).status_code == 200  # DRAFT -> ARCHIVED
    again = await post_job(client, rec, title="Site Reliability Engineer")
    assert again.status_code == 201 and again.json()["id"] != first["id"]


async def test_duplicate_detection_is_per_company(client: AsyncClient) -> None:
    a, b = await register_employer(client), await register_employer(client)
    assert (await post_job(client, a, title="Product Designer")).status_code == 201
    assert (await post_job(client, b, title="Product Designer")).status_code == 201


async def test_renaming_into_a_duplicate_is_rejected(client: AsyncClient) -> None:
    rec = await register_employer(client)
    await post_job(client, rec, title="Role One")
    two = (await post_job(client, rec, title="Role Two")).json()
    assert_error(await client.patch(f"{JOBS}/{two['id']}", headers=rec["h"], json={"title": "role one"}), 409, "DUPLICATE_JOB")
    assert (await client.get(f"{JOBS}/{two['id']}", headers=rec["h"])).json()["title"] == "Role Two"
    assert (await client.patch(f"{JOBS}/{two['id']}", headers=rec["h"], json={"title": "Role Two"})).status_code == 200  # unchanged value is no conflict


# --- validation matrix --------------------------------------------------------------------------------------------------------------


VALIDATION_CASES: list[tuple[dict[str, Any], str]] = [
    ({"salary_min": 100000, "salary_max": 90000}, "__root__"),
    ({"min_experience_years": 8, "max_experience_years": 5}, "__root__"),
    ({"application_deadline": (date.today() - timedelta(days=1)).isoformat()}, "application_deadline"),
    ({"title": "ab"}, "title"),
    ({"title": "      "}, "title"),
    ({"description": "too short"}, "description"),
    ({"employment_type": "SLAVE"}, "employment_type"),
    ({"workplace_type": "ORBIT"}, "workplace_type"),
    ({"experience_level": "WIZARD"}, "experience_level"),
    ({"min_education_level": "PHD"}, "min_education_level"),
    ({"salary_min": -5}, "salary_min"),
    ({"min_experience_years": 71}, "min_experience_years"),
    ({"salary_currency": "DOLLARS"}, "salary_currency"),
    ({"skills": [{"name": f"Skill {i}"} for i in range(41)]}, "skills"),
    ({"skills": [{"requirement": "REQUIRED"}]}, "skills"),
    ({"skills": [{"name": "Python", "requirement": "MAYBE"}]}, "skills"),
    ({"hiring_manager_id": "xyz"}, "hiring_manager_id"),
]


async def test_create_validation_matrix(client: AsyncClient) -> None:
    rec = await register_employer(client)
    for overrides, field in VALIDATION_CASES:
        err = assert_error(await post_job(client, rec, **overrides), 422, "VALIDATION_ERROR")
        assert err["details"], err
        if field != "__root__":
            assert field in {d["field"].split(".")[0] for d in err["details"]}, (overrides, err)
    assert await scalar("SELECT count(*) FROM jobs") == 0


async def test_unknown_skill_id_is_not_found(client: AsyncClient) -> None:
    rec = await register_employer(client)
    r = await post_job(client, rec, skills=[{"skill_id": str(uuid.uuid4()), "requirement": "REQUIRED"}])
    assert_error(r, 404, "SKILL_NOT_FOUND")
    assert await scalar("SELECT count(*) FROM jobs") == 0, "the job must not be half-created"


async def test_boundary_values_are_accepted(client: AsyncClient) -> None:
    rec = await register_employer(client)
    r = await post_job(
        client, rec, salary_min=0, salary_max=0, min_experience_years=0, max_experience_years=0, application_deadline=date.today().isoformat(),
        skills=[{"name": f"Boundary Skill {i}"} for i in range(40)],
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["skills"]) == 40


# --- skills ------------------------------------------------------------------------------------------------------------------------------


async def test_skills_by_id_name_and_alias_resolve_to_the_same_skill(client: AsyncClient) -> None:
    rec = await register_employer(client)
    pg_id = str(await scalar("SELECT id FROM skills WHERE name = 'PostgreSQL'"))
    job = (await post_job(client, rec, skills=[{"skill_id": pg_id}, {"name": "node js"}, {"name": "K8s", "requirement": "PREFERRED", "min_years": 2}])).json()
    assert skills_of(job) == {"PostgreSQL": "REQUIRED", "Node.js": "REQUIRED", "Kubernetes": "PREFERRED"}
    k8s = next(s for s in job["skills"] if s["skill"]["name"] == "Kubernetes")
    assert float(k8s["min_years"]) == 2.0


@pytest.mark.parametrize("order", [("PREFERRED", "REQUIRED"), ("REQUIRED", "PREFERRED")])
async def test_required_beats_preferred_for_repeated_skills(client: AsyncClient, order: tuple[str, str]) -> None:
    rec = await register_employer(client)
    listing = [{"name": "PostgreSQL", "requirement": order[0]}, {"name": "postgres", "requirement": order[1]}, {"name": "Docker", "requirement": "PREFERRED"}, {"name": "docker", "requirement": "PREFERRED"}]
    job = (await post_job(client, rec, skills=listing)).json()
    assert skills_of(job) == {"PostgreSQL": "REQUIRED", "Docker": "PREFERRED"}
    assert await scalar("SELECT count(*) FROM job_skills WHERE job_id = :j", j=uuid.UUID(job["id"])) == 2


async def test_updating_skills_replaces_the_list_and_omitting_them_keeps_it(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec)).json()
    url = f"{JOBS}/{job['id']}"
    kept = await client.patch(url, headers=rec["h"], json={"department": "Platform"})
    assert kept.status_code == 200 and len(kept.json()["skills"]) == 6 and kept.json()["department"] == "Platform"
    replaced = await client.patch(url, headers=rec["h"], json={"skills": [{"name": "Go"}, {"name": "Rust", "requirement": "PREFERRED"}]})
    assert skills_of(replaced.json()) == {"Go": "REQUIRED", "Rust": "PREFERRED"}
    assert await scalar("SELECT skills_text FROM jobs WHERE id = :i", i=uuid.UUID(job["id"])) == "Go, Rust"
    cleared = await client.patch(url, headers=rec["h"], json={"skills": []})
    assert cleared.json()["skills"] == [] and await scalar("SELECT skills_text FROM jobs WHERE id = :i", i=uuid.UUID(job["id"])) is None
    bad = await client.patch(url, headers=rec["h"], json={"skills": [{"skill_id": str(uuid.uuid4())}]})
    assert_error(bad, 404, "SKILL_NOT_FOUND")
    assert (await client.get(url, headers=rec["h"])).json()["skills"] == [], "a failed replacement leaves the previous list alone"


async def test_new_skill_names_on_a_job_are_created_unverified(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec, skills=[{"name": "Quantum Annealing"}])).json()
    skill = job["skills"][0]["skill"]
    assert skill["name"] == "Quantum Annealing" and skill["is_verified"] is False


# --- publishing ---------------------------------------------------------------------------------------------------------------------


async def test_publish_validation_reports_every_problem(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec, description="Short but valid description.", skills=[{"name": "Redis", "requirement": "PREFERRED"}])).json()
    err = assert_error(await client.post(f"{JOBS}/{job['id']}/publish", headers=rec["h"]), 422, "PUBLISH_VALIDATION_FAILED")
    assert sorted(err["details"]) == ["Add at least one required skill", "Description must be at least 30 characters"]
    assert (await client.get(f"{JOBS}/{job['id']}", headers=rec["h"])).json()["status"] == "DRAFT"
    # fix both problems and it publishes
    fixed = await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"description": "A sufficiently long description of the role.", "skills": [{"name": "Redis"}]})
    assert fixed.status_code == 200
    assert (await client.post(f"{JOBS}/{job['id']}/publish", headers=rec["h"])).json()["status"] == "PUBLISHED"


async def test_publish_refuses_a_deadline_that_has_since_passed(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec)).json()
    await expire_deadline(job["id"])
    err = assert_error(await client.post(f"{JOBS}/{job['id']}/publish", headers=rec["h"]), 422, "PUBLISH_VALIDATION_FAILED")
    assert err["details"] == ["The application deadline is in the past"]
    moved = await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"application_deadline": future(10)})
    assert moved.status_code == 200
    assert (await client.post(f"{JOBS}/{job['id']}/publish", headers=rec["h"])).status_code == 200


async def test_whitespace_only_descriptions_do_not_pass_the_publish_check(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec)).json()
    assert_error(await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"description": " " * 40}), 422, "VALIDATION_ERROR")


async def test_full_lifecycle_with_timestamps_and_allowed_transitions(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec)).json()
    url = f"{JOBS}/{job['id']}"

    async def step(action: str, expect: str) -> dict[str, Any]:
        r = await client.post(f"{url}/{action}", headers=rec["h"], json={"reason": f"because {action}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == expect
        return r.json()  # type: ignore[no-any-return]

    published = await step("publish", "PUBLISHED")
    assert published["published_at"] and published["allowed_transitions"] == ["CLOSED", "PAUSED"] and published["can_apply"] is True
    paused = await step("pause", "PAUSED")
    assert paused["allowed_transitions"] == ["CLOSED", "PUBLISHED"] and paused["can_apply"] is False and paused["apply_blocked_reason"]
    resumed = await step("resume", "PUBLISHED")
    assert resumed["published_at"] == published["published_at"], "published_at is set once"
    again = await client.post(f"{url}/publish", headers=rec["h"])  # publish on a paused job also resumes it
    assert again.status_code == 409  # ... but not when it is already published
    closed = await step("close", "CLOSED")
    assert closed["closed_at"] and closed["allowed_transitions"] == ["ARCHIVED"] and closed["published_at"] == published["published_at"]
    archived = await step("archive", "ARCHIVED")
    assert archived["allowed_transitions"] == [] and archived["closed_at"] == closed["closed_at"]
    # audit trail with the reason and previous status
    events = await sql("SELECT action, metadata FROM audit_events WHERE entity_id = :i AND action LIKE 'job.%' ORDER BY created_at, id", i=uuid.UUID(job["id"]))
    assert [e[0] for e in events] == ["job.created", "job.published", "job.paused", "job.published", "job.closed", "job.archived"]
    assert events[2][1] == {"from": "PUBLISHED", "reason": "because pause"} and events[5][1] == {"from": "CLOSED", "reason": "because archive"}


async def test_publish_from_paused_resumes_the_job(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    await client.post(f"{JOBS}/{job['id']}/pause", headers=rec["h"])
    assert (await client.post(f"{JOBS}/{job['id']}/publish", headers=rec["h"])).json()["status"] == "PUBLISHED"


@pytest.mark.parametrize("source", list(JobStatus))
async def test_transition_matrix(client: AsyncClient, source: JobStatus) -> None:
    """Every (source status, action) pair: accepted exactly when the target is in the transition table."""
    rec = await register_employer(client)
    for action, target in ENDPOINTS.items():
        job = await create_job(client, rec, title=f"Matrix {source.value} {action}")
        await set_job_status(job["id"], source.value)
        r = await client.post(f"{JOBS}/{job['id']}/{action}", headers=rec["h"])
        if target in JOB_TRANSITIONS[source]:
            assert r.status_code == 200, (source, action, r.text)
            assert r.json()["status"] == target.value
        else:
            err = assert_error(r, 409, "INVALID_STATE_TRANSITION")
            assert err["details"] == {"from": source.value, "to": target.value, "allowed": sorted(s.value for s in JOB_TRANSITIONS[source])}
            assert await scalar("SELECT status FROM jobs WHERE id = :i", i=uuid.UUID(job["id"])) == source.value, "a refused transition changes nothing"


# --- editing / deleting -------------------------------------------------------------------------------------------------------------------


async def test_only_open_statuses_are_editable(client: AsyncClient) -> None:
    rec = await register_employer(client)
    for status in JobStatus:
        job = await create_job(client, rec, title=f"Editable {status.value}")
        await set_job_status(job["id"], status.value)
        r = await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"department": "Changed"})
        if status in EDITABLE_STATUSES:
            assert r.status_code == 200 and r.json()["department"] == "Changed", status
        else:
            assert_error(r, 422, "JOB_NOT_EDITABLE")
            assert (await client.get(f"{JOBS}/{job['id']}", headers=rec["h"])).json()["department"] == "Engineering"


async def test_update_semantics(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = (await post_job(client, rec, salary_min=50000, salary_max=60000, min_experience_years=2, max_experience_years=5)).json()
    url = f"{JOBS}/{job['id']}"
    r = await client.patch(url, headers=rec["h"], json={"title": "  Renamed   Role ", "salary_currency": "eur", "benefits": "Free coffee", "employment_type": "CONTRACT"})
    body = r.json()
    assert (body["title"], body["salary_currency"], body["benefits"], body["employment_type"]) == ("Renamed Role", "EUR", "Free coffee", "CONTRACT")
    # cross-field rules are checked against the stored values, not just the request
    assert_error(await client.patch(url, headers=rec["h"], json={"salary_max": 40000}), 422, "INVALID_SALARY_RANGE")
    assert_error(await client.patch(url, headers=rec["h"], json={"max_experience_years": 1}), 422, "INVALID_EXPERIENCE_RANGE")
    assert_error(await client.patch(url, headers=rec["h"], json={"application_deadline": (date.today() - timedelta(days=2)).isoformat()}), 422, "INVALID_DEADLINE")
    # nulls clear optional fields but are ignored for required ones
    r = await client.patch(url, headers=rec["h"], json={"salary_min": None, "salary_max": None, "title": None, "employment_type": None, "benefits": None})
    body = r.json()
    assert body["salary_min"] is None and body["salary_max"] is None and body["benefits"] is None
    assert body["title"] == "Renamed Role" and body["employment_type"] == "CONTRACT"
    assert (await client.patch(url, headers=rec["h"], json={})).status_code == 200
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'job.updated'") == 3  # rejected updates are not audited


async def test_editing_a_live_job_requeues_matching_and_other_edits_do_not(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    base = len(await tasks("MATCH_JOB"))
    assert base >= 1, "publishing queues a match run"
    await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"department": "Platform"})  # not match-relevant
    assert len(await tasks("MATCH_JOB")) == base
    await client.patch(f"{JOBS}/{job['id']}", headers=rec["h"], json={"skills": [{"name": "Go"}]})
    assert len(await tasks("MATCH_JOB")) == base + 1
    draft = await create_job(client, rec, title="Draft Only Role")
    await client.patch(f"{JOBS}/{draft['id']}", headers=rec["h"], json={"title": "Draft Only Role v2"})
    assert len(await tasks("MATCH_JOB")) == base + 1, "drafts are not matched"


async def test_only_drafts_can_be_deleted(client: AsyncClient) -> None:
    rec = await register_employer(client)
    draft = await create_job(client, rec, title="Throwaway Draft")
    live = await create_job(client, rec, title="Live Role", publish=True)
    assert (await client.delete(f"{JOBS}/{draft['id']}", headers=rec["h"])).status_code == 204
    assert_error(await client.get(f"{JOBS}/{draft['id']}", headers=rec["h"]), 404, "JOB_NOT_FOUND")
    assert await scalar("SELECT count(*) FROM job_skills WHERE job_id = :j", j=uuid.UUID(draft["id"])) == 0, "skills are removed with the job"
    assert_error(await client.delete(f"{JOBS}/{live['id']}", headers=rec["h"]), 422, "JOB_NOT_DELETABLE")
    for status in ("PAUSED", "CLOSED", "ARCHIVED"):
        await set_job_status(live["id"], status)
        assert_error(await client.delete(f"{JOBS}/{live['id']}", headers=rec["h"]), 422, "JOB_NOT_DELETABLE")
    assert_error(await client.delete(f"{JOBS}/{draft['id']}", headers=rec["h"]), 404, "JOB_NOT_FOUND")
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'job.deleted'") == 1
    # the title can be reused after deleting the draft
    assert (await post_job(client, rec, title="Throwaway Draft")).status_code == 201


# --- hiring manager assignment ----------------------------------------------------------------------------------------------------------------


async def test_hiring_manager_assignment_rules(client: AsyncClient) -> None:
    rec = await register_employer(client, "Assign Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    colleague = await add_staff(client, rec, "RECRUITER")
    outsider = await register_employer(client, "Other Assign Co")
    cand = await register_candidate(client)
    admin = await create_admin(client)
    suspended = await add_staff(client, rec, "HIRING_MANAGER")
    await sql("UPDATE users SET status = 'SUSPENDED' WHERE id = :i", i=uuid.UUID(suspended["id"]))
    for bad in (outsider["user"]["id"], cand["user"]["id"], admin["user"]["id"], suspended["id"], str(uuid.uuid4())):
        assert_error(await post_job(client, rec, hiring_manager_id=bad), 422, "INVALID_HIRING_MANAGER")
    job = (await post_job(client, rec, hiring_manager_id=hm["id"])).json()
    assert job["hiring_manager_id"] == hm["id"] and job["hiring_manager_name"] == "Sam Hiring_Manager"
    url = f"{JOBS}/{job['id']}"
    assert (await client.patch(url, headers=rec["h"], json={"hiring_manager_id": colleague["id"]})).json()["hiring_manager_id"] == colleague["id"]
    assert_error(await client.patch(url, headers=rec["h"], json={"hiring_manager_id": outsider["user"]["id"]}), 422, "INVALID_HIRING_MANAGER")
    cleared = await client.patch(url, headers=rec["h"], json={"hiring_manager_id": None})
    assert cleared.json()["hiring_manager_id"] is None and cleared.json()["hiring_manager_name"] is None


# --- authorization ------------------------------------------------------------------------------------------------------------------------------


async def test_tenant_isolation_for_every_mutating_endpoint(client: AsyncClient) -> None:
    owner, intruder = await register_employer(client), await register_employer(client)
    live = await create_job(client, owner, publish=True)
    draft = await create_job(client, owner, title="Private Draft")
    requests: list[tuple[str, str, dict[str, Any] | None]] = [
        ("PATCH", f"{JOBS}/{live['id']}", {"title": "Hijacked Title"}),
        ("DELETE", f"{JOBS}/{draft['id']}", None),
        *[("POST", f"{JOBS}/{live['id']}/{a}", None) for a in ENDPOINTS],
        ("GET", f"{JOBS}/{live['id']}/stats", None),
    ]
    for method, url, body in requests:
        assert_error(await client.request(method, url, headers=intruder["h"], json=body), 404, "JOB_NOT_FOUND")
    # the draft does not exist for them at all, even read-only
    assert_error(await client.get(f"{JOBS}/{draft['id']}", headers=intruder["h"]), 404, "JOB_NOT_FOUND")
    assert (await client.get(f"{JOBS}/{live['id']}", headers=owner["h"])).json()["title"] == "Backend Engineer"
    assert (await client.get(f"{JOBS}/{live['id']}", headers=owner["h"])).json()["status"] == "PUBLISHED"


async def test_hiring_managers_and_candidates_cannot_modify_jobs(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    job = await create_job(client, rec, publish=True, hiring_manager_id=hm["id"])
    for actor in (hm, cand):
        for method, url, body in (
            ("PATCH", f"{JOBS}/{job['id']}", {"title": "Nope Nope"}),
            ("DELETE", f"{JOBS}/{job['id']}", None),
            *[("POST", f"{JOBS}/{job['id']}/{a}", None) for a in ENDPOINTS],
        ):
            assert_error(await client.request(method, url, headers=actor["h"], json=body), 403, "FORBIDDEN")
    for method, url in (("PATCH", f"{JOBS}/{job['id']}"), ("DELETE", f"{JOBS}/{job['id']}"), ("POST", f"{JOBS}/{job['id']}/close")):
        assert_error(await client.request(method, url), 401, "UNAUTHORIZED")
    assert (await client.get(f"{JOBS}/{job['id']}", headers=rec["h"])).json()["status"] == "PUBLISHED"


async def test_platform_admin_can_manage_any_companys_jobs(client: AsyncClient) -> None:
    rec = await register_employer(client)
    admin = await create_admin(client)
    job = await create_job(client, rec)
    assert (await client.patch(f"{JOBS}/{job['id']}", headers=admin["h"], json={"department": "By Admin"})).status_code == 200
    assert (await client.post(f"{JOBS}/{job['id']}/publish", headers=admin["h"])).json()["status"] == "PUBLISHED"
    detail = (await client.get(f"{JOBS}/{job['id']}", headers=admin["h"])).json()
    assert "created_by_id" in detail and detail["allowed_transitions"] == ["CLOSED", "PAUSED"]


# --- reading: company list, stats ------------------------------------------------------------------------------------------------------------


async def test_company_job_list_scoping_filters_and_counts(client: AsyncClient) -> None:
    rec = await register_employer(client, "Lister Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    other = await register_employer(client, "Foreign Lister")
    assigned = await create_job(client, rec, title="Assigned Opening", publish=True, hiring_manager_id=hm["id"])
    unassigned_draft = await create_job(client, rec, title="Hidden Draft Opening")
    paused = await create_job(client, rec, title="Paused Opening", publish=True)
    await client.post(f"{JOBS}/{paused['id']}/pause", headers=rec["h"])
    await create_job(client, other, title="Foreign Opening", publish=True)
    cand = await register_candidate(client)
    await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": assigned["id"]})

    everything = (await client.get(JOBS, headers=rec["h"])).json()
    assert everything["total"] == 3 and {j["title"] for j in everything["items"]} == {"Assigned Opening", "Hidden Draft Opening", "Paused Opening"}
    counts = {j["title"]: j["application_count"] for j in everything["items"]}
    assert counts == {"Assigned Opening": 1, "Hidden Draft Opening": 0, "Paused Opening": 0}
    drafts = (await client.get(JOBS, headers=rec["h"], params={"status": "DRAFT"})).json()
    assert [j["id"] for j in drafts["items"]] == [unassigned_draft["id"]]
    multi = (await client.get(JOBS, headers=rec["h"], params=[("status", "DRAFT"), ("status", "PAUSED")])).json()
    assert {j["title"] for j in multi["items"]} == {"Hidden Draft Opening", "Paused Opening"}
    assert (await client.get(JOBS, headers=rec["h"], params={"q": "assigned"})).json()["total"] == 1
    assert [j["title"] for j in (await client.get(JOBS, headers=rec["h"], params={"sort": "title"})).json()["items"]] == sorted(counts, key=str.lower)
    # a hiring manager only sees what is assigned to them
    hm_list = (await client.get(JOBS, headers=hm["h"])).json()
    assert [j["id"] for j in hm_list["items"]] == [assigned["id"]]
    # candidates and anonymous callers have no company list
    assert_error(await client.get(JOBS, headers=cand["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(JOBS), 401, "UNAUTHORIZED")
    assert_error(await client.get(JOBS, headers=rec["h"], params={"status": "BOGUS"}), 422, "VALIDATION_ERROR")
    assert_error(await client.get(JOBS, headers=rec["h"], params={"page_size": 101}), 422, "VALIDATION_ERROR")


async def test_admin_company_job_list(client: AsyncClient) -> None:
    a, b = await register_employer(client), await register_employer(client)
    admin = await create_admin(client)
    await create_job(client, a, title="Admin Seen A")
    await create_job(client, b, title="Admin Seen B")
    assert (await client.get(JOBS, headers=admin["h"])).json()["total"] == 2
    assert (await client.get(JOBS, headers=admin["h"], params={"company_id": a["company_id"]})).json()["total"] == 1


async def test_job_stats(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    job = await create_job(client, rec, publish=True, hiring_manager_id=hm["id"])
    unassigned = await create_job(client, rec, publish=True, title="Not Mine Role")
    from tests.helpers import fill_backend_profile

    c1, c2 = await register_candidate(client), await register_candidate(client)
    await fill_backend_profile(client, c1)
    a1 = (await client.post(f"{API}/applications", headers=c1["h"], json={"job_id": job["id"]})).json()
    await client.post(f"{API}/applications", headers=c2["h"], json={"job_id": job["id"]})
    await client.post(f"{API}/applications/{a1['id']}/status", headers=rec["h"], json={"status": "SCREENING"})
    stats = (await client.get(f"{JOBS}/{job['id']}/stats", headers=rec["h"])).json()
    assert stats["job_id"] == job["id"] and stats["applications_total"] == 2 and stats["applications_by_status"] == {"APPLIED": 1, "SCREENING": 1}
    assert stats["matches_computed"] >= 2 and stats["last_matched_at"]
    assert (await client.get(f"{JOBS}/{job['id']}/stats", headers=hm["h"])).status_code == 200
    assert_error(await client.get(f"{JOBS}/{unassigned['id']}/stats", headers=hm["h"]), 404, "JOB_NOT_FOUND")
    assert_error(await client.get(f"{JOBS}/{job['id']}/stats", headers=c1["h"]), 403, "FORBIDDEN")
