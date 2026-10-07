"""Who may see, download and edit a résumé: owner, staff with a real relationship, nobody else (404, never 403)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import AuditEvent
from tests import fixtures_resumes as fx
from tests.helpers import add_staff, create_admin, create_job, register_candidate, register_employer
from tests.resume_helpers import upload_ok

pytestmark = pytest.mark.e2e

PDF_BYTES = fx.backend_pdf()


async def apply_with(client, cand, job, resume_id):
    r = await client.post(
        "/api/v1/applications", headers=cand["h"], json={"job_id": job["id"], "resume_id": resume_id}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def all_access_statuses(client, who, rid):
    h = who["h"]
    return {
        "get": (await client.get(f"/api/v1/resumes/{rid}", headers=h)).status_code,
        "file": (await client.get(f"/api/v1/resumes/{rid}/file", headers=h)).status_code,
        "extracted": (await client.get(f"/api/v1/resumes/{rid}/extracted", headers=h)).status_code,
        "patch": (
            await client.patch(f"/api/v1/resumes/{rid}/extracted", headers=h, json={"summary": "x"})
        ).status_code,
        "apply": (
            await client.post(f"/api/v1/resumes/{rid}/extracted/apply", headers=h, json={"skills": "all"})
        ).status_code,
        "process": (await client.post(f"/api/v1/resumes/{rid}/process", headers=h)).status_code,
        "primary": (await client.post(f"/api/v1/resumes/{rid}/primary", headers=h)).status_code,
        "delete": (await client.delete(f"/api/v1/resumes/{rid}", headers=h)).status_code,
    }


async def test_other_candidates_see_nothing_and_ids_cannot_be_probed(client):
    owner = await register_candidate(client)
    other = await register_candidate(client)
    body = await upload_ok(client, owner, PDF_BYTES)
    statuses = await all_access_statuses(client, other, body["id"])
    assert set(statuses.values()) == {404}, statuses
    # indistinguishable from a résumé that does not exist
    missing = await all_access_statuses(client, other, str(uuid.uuid4()))
    assert missing == statuses
    r = await client.get(f"/api/v1/resumes/{body['id']}", headers=other["h"])
    assert r.json()["error"]["code"] == "RESUME_NOT_FOUND"
    assert (await client.get("/api/v1/resumes", headers=other["h"])).json()["total"] == 0
    # the owner is unaffected
    assert (await client.get(f"/api/v1/resumes/{body['id']}", headers=owner["h"])).status_code == 200


async def test_malformed_ids_and_anonymous_access(client):
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, PDF_BYTES)
    assert (await client.get("/api/v1/resumes/not-a-uuid", headers=cand["h"])).status_code == 422
    for method, path in (
        ("GET", ""),
        ("GET", "/file"),
        ("GET", "/extracted"),
        ("POST", "/process"),
        ("POST", "/primary"),
        ("DELETE", ""),
    ):
        r = await client.request(method, f"/api/v1/resumes/{body['id']}{path}")
        assert r.status_code == 401, (method, path)
    assert (await client.get("/api/v1/resumes")).status_code == 401
    assert (await client.get("/api/v1/resumes/bulk-imports")).status_code == 401


async def test_marketplace_only_recruiter_cannot_even_tell_that_a_resume_exists(client):
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, PDF_BYTES)
    rec = await register_employer(client, "Browsing Corp")
    statuses = await all_access_statuses(client, rec, body["id"])
    assert set(statuses.values()) == {404}, statuses
    # ... although the candidate IS visible in the marketplace (profile only, no résumé files)
    view = await client.get(f"/api/v1/candidates/{cand['candidate_id']}", headers=rec["h"])
    assert view.status_code == 200 and view.json()["access"] == "PROFILE" and view.json()["resumes"] == []
    assert view.json()["email"] is None


async def test_applicants_resume_is_available_to_the_hiring_company_only(client, session):
    rec_a = await register_employer(client, "Hiring Co")
    rec_b = await register_employer(client, "Other Co")
    hm_assigned = await add_staff(client, rec_a, "HIRING_MANAGER")
    hm_other = await add_staff(client, rec_a, "HIRING_MANAGER")
    job = await create_job(client, rec_a, publish=True, hiring_manager_id=hm_assigned["id"])
    other_job = await create_job(
        client, rec_a, publish=True, title="Other role", hiring_manager_id=hm_other["id"]
    )
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, PDF_BYTES, "cv.pdf")
    rid = body["id"]
    await apply_with(client, cand, job, rid)

    # the hiring company's recruiter: may view and download (read-only)
    got = await client.get(f"/api/v1/resumes/{rid}", headers=rec_a["h"])
    assert got.status_code == 200 and got.json()["id"] == rid and got.json()["status"] == "PROCESSED"
    dl = await client.get(f"/api/v1/resumes/{rid}/file", headers=rec_a["h"])
    assert (
        dl.status_code == 200
        and dl.content == PDF_BYTES
        and dl.headers["cache-control"] == "private, no-store"
    )
    # ... but not edit someone else's candidate data
    s = await all_access_statuses(client, rec_a, rid)
    assert (s["get"], s["file"]) == (200, 200)
    assert {s[k] for k in ("extracted", "patch", "apply", "process", "primary", "delete")} == {404}

    # a hiring manager sees the résumé only for a job assigned to them
    assert (await client.get(f"/api/v1/resumes/{rid}/file", headers=hm_assigned["h"])).status_code == 200
    assert (await client.get(f"/api/v1/resumes/{rid}", headers=hm_other["h"])).status_code == 404
    assert (await client.get(f"/api/v1/resumes/{rid}/file", headers=hm_other["h"])).status_code == 404
    _ = other_job

    # another company learns nothing, even though the candidate applied elsewhere
    assert set((await all_access_statuses(client, rec_b, rid)).values()) == {404}

    # releasing the file to staff is audited
    events = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "resume.downloaded", AuditEvent.entity_id == uuid.UUID(rid)
                )
            )
        )
        .scalars()
        .all()
    )
    assert {e.actor_id for e in events} == {
        uuid.UUID(rec_a["user"]["id"]),
        uuid.UUID(hm_assigned["user"]["id"]),
    }


async def test_withdrawn_or_absent_application_means_no_access_for_a_different_job_owner(client):
    rec_a = await register_employer(client, "Co A")
    rec_b = await register_employer(client, "Co B")
    job_b = await create_job(client, rec_b, publish=True)
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, PDF_BYTES)
    assert (await client.get(f"/api/v1/resumes/{body['id']}", headers=rec_a["h"])).status_code == 404
    await apply_with(client, cand, job_b, body["id"])
    assert (await client.get(f"/api/v1/resumes/{body['id']}", headers=rec_b["h"])).status_code == 200
    assert (
        await client.get(f"/api/v1/resumes/{body['id']}", headers=rec_a["h"])
    ).status_code == 404  # Co A still has no relationship


async def test_admin_can_read_but_not_edit(client):
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, PDF_BYTES)
    admin = await create_admin(client)
    s = await all_access_statuses(client, admin, body["id"])
    assert (s["get"], s["file"]) == (200, 200)
    assert {s[k] for k in ("extracted", "patch", "apply", "process", "primary", "delete")} == {404}


async def test_role_gates_on_upload_list_and_bulk_endpoints(client):
    cand = await register_candidate(client)
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    assert (
        await client.get("/api/v1/resumes", headers=rec["h"])
    ).status_code == 403  # list is candidates-only
    assert (await client.get("/api/v1/resumes/bulk-imports", headers=cand["h"])).status_code == 403
    assert (await client.get("/api/v1/resumes/bulk-imports", headers=hm["h"])).status_code == 403
    files = [("files", ("a.pdf", PDF_BYTES, "application/pdf"))]
    assert (
        await client.post("/api/v1/resumes/bulk-imports", headers=cand["h"], files=files)
    ).status_code == 403
    assert (
        await client.post("/api/v1/resumes/bulk-imports", headers=hm["h"], files=files)
    ).status_code == 403
    assert (await client.post("/api/v1/resumes/bulk-imports", files=files)).status_code == 401
