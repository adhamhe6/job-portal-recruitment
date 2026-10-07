"""Workflows 1 & 2 (without résumé): recruiter publishes a job, candidate finds it and applies, recruiter sees it."""

import pytest

from tests.helpers import create_job, fill_backend_profile, register_candidate, register_employer

pytestmark = pytest.mark.e2e


async def test_recruiter_creates_publishes_and_job_is_publicly_searchable(client):
    rec = await register_employer(client, "Acme Robotics")
    assert rec["user"]["role"] == "RECRUITER" and rec["user"]["company"]["name"] == "Acme Robotics"

    job = await create_job(client, rec)  # DRAFT
    assert job["status"] == "DRAFT"
    assert {s["skill"]["name"] for s in job["skills"]} >= {"Python", "FastAPI", "PostgreSQL"}

    # drafts are invisible to the public
    anon = await client.get(f"/api/v1/jobs/{job['id']}")
    assert anon.status_code == 404
    res = await client.get("/api/v1/search/jobs", params={"q": "backend"})
    assert res.status_code == 200 and res.json()["total"] == 0

    pub = await client.post(f"/api/v1/jobs/{job['id']}/publish", headers=rec["h"])
    assert pub.status_code == 200 and pub.json()["status"] == "PUBLISHED" and pub.json()["published_at"]

    res = await client.get("/api/v1/search/jobs", params={"q": "backend engineer"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1 and body["items"][0]["id"] == job["id"] and body["items"][0]["company_name"] == "Acme Robotics"
    detail = await client.get(f"/api/v1/jobs/{job['id']}")
    assert detail.status_code == 200
    assert "created_by_id" not in detail.json() and "hiring_manager_id" not in detail.json()  # public view hides internals


async def test_candidate_applies_and_recruiter_sees_application_ranked(client):
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)

    r = await client.post("/api/v1/applications", headers=cand["h"], json={"job_id": job["id"], "cover_letter": "Hello"})
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["status"] == "APPLIED" and app["history"][0]["to_status"] == "APPLIED"

    dup = await client.post("/api/v1/applications", headers=cand["h"], json={"job_id": job["id"]})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "APPLICATION_ALREADY_EXISTS"

    lst = await client.get("/api/v1/applications", headers=rec["h"], params={"job_id": job["id"]})
    assert lst.status_code == 200 and lst.json()["total"] == 1
    item = lst.json()["items"][0]
    assert item["candidate_name"] == "Casey Candidate"
    assert item["match_score"] is not None and item["match_score"] > 0.5  # matching ran (inline worker) and ranked the applicant

    # recruiter walks the pipeline; invalid jumps are rejected
    bad = await client.post(f"/api/v1/applications/{app['id']}/status", headers=rec["h"], json={"status": "HIRED"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    for st in ("SCREENING", "SHORTLISTED"):
        ok = await client.post(f"/api/v1/applications/{app['id']}/status", headers=rec["h"], json={"status": st})
        assert ok.status_code == 200, ok.text
    hist = await client.get(f"/api/v1/applications/{app['id']}/history", headers=rec["h"])
    assert [h["to_status"] for h in hist.json()] == ["APPLIED", "SCREENING", "SHORTLISTED"]

    # the candidate got notified of both stage changes + submission
    n = await client.get("/api/v1/notifications", headers=cand["h"])
    assert n.json()["total"] >= 3


async def test_tenant_isolation_and_authorization(client):
    rec_a = await register_employer(client, "Company A")
    rec_b = await register_employer(client, "Company B")
    job = await create_job(client, rec_a, publish=True)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    app = (await client.post("/api/v1/applications", headers=cand["h"], json={"job_id": job["id"]})).json()

    # Company B cannot see, edit or manage Company A's job/application
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=rec_b["h"])).json().get("created_by_id") is None  # public view only
    assert (await client.patch(f"/api/v1/jobs/{job['id']}", headers=rec_b["h"], json={"title": "Hacked title"})).status_code == 404
    assert (await client.post(f"/api/v1/jobs/{job['id']}/close", headers=rec_b["h"])).status_code == 404
    assert (await client.get(f"/api/v1/applications/{app['id']}", headers=rec_b["h"])).status_code == 404
    assert (await client.post(f"/api/v1/applications/{app['id']}/status", headers=rec_b["h"], json={"status": "SCREENING"})).status_code == 404

    # Another candidate cannot read the application; candidates cannot manage stages or use recruiter endpoints
    other = await register_candidate(client)
    assert (await client.get(f"/api/v1/applications/{app['id']}", headers=other["h"])).status_code == 404
    assert (await client.post(f"/api/v1/applications/{app['id']}/status", headers=cand["h"], json={"status": "SCREENING"})).status_code == 403
    assert (await client.post("/api/v1/jobs", headers=cand["h"], json={"title": "x" * 5})).status_code in (403, 422)
    assert (await client.get("/api/v1/users", headers=rec_a["h"])).status_code == 403
    assert (await client.get("/api/v1/jobs")).status_code == 401
