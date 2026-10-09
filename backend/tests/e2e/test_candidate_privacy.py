"""What hiring staff may see of a candidate: marketplace visibility, applicant access, sourcing and assignment rules."""

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
from tests.helpers_spine import (  # noqa: F401
    API,
    apply_job,
    assert_error,
    fast_argon,
    insert_imported_candidate,
    scalar,
    sql,
)

pytestmark = pytest.mark.e2e


async def view(client: AsyncClient, viewer: dict[str, Any], candidate_id: str, **params: Any) -> Any:
    return await client.get(f"{API}/candidates/{candidate_id}", headers=viewer["h"], params=params)


async def opt_out(client: AsyncClient, cand: dict[str, Any], searchable: bool = False) -> None:
    r = await client.patch(f"{API}/candidates/me", headers=cand["h"], json={"is_searchable": searchable})
    assert r.status_code == 200 and r.json()["is_searchable"] is searchable


async def with_phone(client: AsyncClient, cand: dict[str, Any]) -> None:
    await client.patch(
        f"{API}/candidates/me",
        headers=cand["h"],
        json={"phone": "+49 170 5551234", "headline": "Backend engineer"},
    )


async def test_marketplace_candidate_is_visible_without_contact_details(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client, first="Mira", last="Marketplace")
    await fill_backend_profile(client, cand)
    await with_phone(client, cand)
    r = await view(client, rec, cand["candidate_id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["access"] == "PROFILE"
        and body["display_name"] == "Mira Marketplace"
        and body["source"] == "SELF"
    )
    assert (
        body["email"] is None
        and body["phone"] is None
        and body["resumes"] == []
        and body["applications"] == []
    )
    assert {s["skill"]["name"] for s in body["skills"]} >= {"Python", "FastAPI"}
    assert cand["email"] not in r.text and "5551234" not in r.text
    assert body["experiences"] and body["educations"]


async def test_opting_out_hides_the_candidate_immediately(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    assert (await view(client, rec, cand["candidate_id"])).status_code == 200
    await opt_out(client, cand, False)
    assert_error(await view(client, rec, cand["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")
    await opt_out(client, cand, True)
    assert (await view(client, rec, cand["candidate_id"])).status_code == 200


async def test_applicants_are_fully_visible_to_the_hiring_company_only(client: AsyncClient) -> None:
    rec_a, rec_b = await register_employer(client, "Company A"), await register_employer(client, "Company B")
    job = await create_job(client, rec_a, publish=True)
    cand = await register_candidate(client, first="Anna", last="Applicant")
    await with_phone(client, cand)
    await apply_job(client, cand, job["id"])
    # searchable: company A gets FULL (contact details + applications), company B only the marketplace PROFILE
    full = (await view(client, rec_a, cand["candidate_id"])).json()
    assert full["access"] == "FULL" and full["email"] == cand["email"] and full["phone"] == "+49 170 5551234"
    assert [(a["job_id"], a["status"]) for a in full["applications"]] == [(job["id"], "APPLIED")]
    market = (await view(client, rec_b, cand["candidate_id"])).json()
    assert (
        market["access"] == "PROFILE"
        and market["email"] is None
        and market["phone"] is None
        and market["applications"] == []
    )
    # opted out: still FULL for A (they hold the application), invisible to B
    await opt_out(client, cand, False)
    assert (await view(client, rec_a, cand["candidate_id"])).json()["access"] == "FULL"
    assert_error(await view(client, rec_b, cand["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")


async def test_applications_listed_on_a_candidate_are_only_those_to_the_callers_company(
    client: AsyncClient,
) -> None:
    rec_a, rec_b = (
        await register_employer(client, "Alpha Hiring"),
        await register_employer(client, "Beta Hiring"),
    )
    job_a = await create_job(client, rec_a, publish=True)
    job_b = await create_job(client, rec_b, publish=True, title="Platform Engineer")
    cand = await register_candidate(client)
    await apply_job(client, cand, job_a["id"])
    await apply_job(client, cand, job_b["id"])
    for rec, job in ((rec_a, job_a), (rec_b, job_b)):
        body = (await view(client, rec, cand["candidate_id"])).json()
        assert body["access"] == "FULL" and [a["job_id"] for a in body["applications"]] == [job["id"]]


async def test_other_companys_staff_cannot_reach_resume_files_of_a_marketplace_candidate(
    client: AsyncClient,
) -> None:
    rec_a, rec_b = await register_employer(client), await register_employer(client)
    job = await create_job(client, rec_a, publish=True)
    cand = await register_candidate(client)
    cid = uuid.UUID(cand["candidate_id"])
    await sql("INSERT INTO resumes (candidate_id, status, is_primary) VALUES (:c, 'PROCESSED', true)", c=cid)
    assert (await view(client, rec_b, cand["candidate_id"])).json()["resumes"] == []
    assert (await view(client, rec_a, cand["candidate_id"])).json()["resumes"] == [], (
        "no relationship yet: marketplace view only"
    )
    await apply_job(client, cand, job["id"])
    resumes = (await view(client, rec_a, cand["candidate_id"])).json()["resumes"]
    assert len(resumes) == 1 and resumes[0]["is_primary"] is True and resumes[0]["status"] == "PROCESSED"
    assert (await view(client, rec_b, cand["candidate_id"])).json()["resumes"] == []


async def test_hiring_manager_sees_only_applicants_of_jobs_assigned_to_them(client: AsyncClient) -> None:
    rec = await register_employer(client, "Managed Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    other_hm = await add_staff(client, rec, "HIRING_MANAGER")
    mine = await create_job(client, rec, publish=True, title="Assigned Role", hiring_manager_id=hm["id"])
    other = await create_job(client, rec, publish=True, title="Unassigned Role")
    applicant = await register_candidate(client)
    other_applicant = await register_candidate(client)
    browser = await register_candidate(client)
    await with_phone(client, applicant)
    await apply_job(client, applicant, mine["id"])
    await apply_job(client, other_applicant, other["id"])
    seen = await view(client, hm, applicant["candidate_id"])
    assert (
        seen.status_code == 200
        and seen.json()["access"] == "FULL"
        and seen.json()["email"] == applicant["email"]
    )
    assert [a["job_id"] for a in seen.json()["applications"]] == [mine["id"]]
    # applicants of other jobs, and marketplace browsers, are off limits to a hiring manager
    assert_error(await view(client, hm, other_applicant["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")
    assert_error(await view(client, hm, browser["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")
    assert_error(await view(client, other_hm, applicant["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")
    # while the recruiter sees them all
    for c in (applicant, other_applicant):
        assert (await view(client, rec, c["candidate_id"])).json()["access"] == "FULL"


async def test_hiring_manager_view_requires_the_application_to_be_for_an_assigned_job_of_their_own_company(
    client: AsyncClient,
) -> None:
    rec_a, rec_b = await register_employer(client), await register_employer(client)
    hm_a = await add_staff(client, rec_a, "HIRING_MANAGER")
    job_b = await create_job(client, rec_b, publish=True)
    cand = await register_candidate(client)
    await apply_job(client, cand, job_b["id"])
    assert_error(await view(client, hm_a, cand["candidate_id"]), 404, "CANDIDATE_NOT_FOUND")


async def test_imported_candidates_belong_to_the_sourcing_company(client: AsyncClient) -> None:
    rec_a, rec_b = await register_employer(client, "Sourcer A"), await register_employer(client, "Sourcer B")
    hm_a = await add_staff(client, rec_a, "HIRING_MANAGER")
    imported = await insert_imported_candidate(
        rec_a["company_id"], name="Ines Imported", email="ines@sourced.example"
    )
    own = await view(client, rec_a, imported)
    assert own.status_code == 200
    body = own.json()
    assert (
        body["access"] == "FULL"
        and body["source"] == "IMPORTED"
        and body["email"] == "ines@sourced.example"
        and body["phone"] == "+49 170 0000000"
    )
    assert_error(await view(client, rec_b, imported), 404, "CANDIDATE_NOT_FOUND")
    assert_error(
        await view(client, hm_a, imported), 404, "CANDIDATE_NOT_FOUND"
    )  # sourcing does not extend to hiring managers
    # an application by an imported candidate to another company's job does not leak them either
    admin = await create_admin(client)
    assert (await view(client, admin, imported)).json()["access"] == "FULL"


async def test_candidates_and_anonymous_users_cannot_use_the_staff_view(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand, peer = await register_candidate(client), await register_candidate(client)
    assert_error(await view(client, cand, peer["candidate_id"]), 403, "FORBIDDEN")
    assert_error(await view(client, cand, cand["candidate_id"]), 403, "FORBIDDEN")
    assert_error(await client.get(f"{API}/candidates/{peer['candidate_id']}"), 401, "UNAUTHORIZED")
    assert_error(await view(client, rec, str(uuid.uuid4())), 404, "CANDIDATE_NOT_FOUND")
    assert_error(await view(client, rec, "not-a-uuid"), 422, "VALIDATION_ERROR")


async def test_platform_admin_sees_everything_in_full(client: AsyncClient) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    await opt_out(client, cand, False)
    body = (await view(client, admin, cand["candidate_id"])).json()
    assert body["access"] == "FULL" and body["email"] == cand["email"]


async def test_withdrawn_applications_are_still_listed_for_the_company(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    app = await apply_job(client, cand, job["id"])
    assert (
        await client.post(f"{API}/applications/{app['id']}/withdraw", headers=cand["h"])
    ).status_code == 200
    body = (await view(client, rec, cand["candidate_id"])).json()
    assert [a["status"] for a in body["applications"]] == ["WITHDRAWN"]


async def test_match_explanation_with_job_id(client: AsyncClient) -> None:
    rec, other = await register_employer(client), await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand, years=5)
    body = (await view(client, rec, cand["candidate_id"], job_id=job["id"])).json()
    match = body["match"]
    assert match["job_id"] == job["id"] and 0.5 < match["overall_score"] <= 1
    assert match["explanation"]["skills"]["required"]["total"] == 4 and match["generated_at"]
    assert (await view(client, rec, cand["candidate_id"])).json()["match"] is None
    # a job the caller cannot see is reported as missing, not forbidden
    foreign = await create_job(client, other, publish=True)
    assert_error(await view(client, rec, cand["candidate_id"], job_id=foreign["id"]), 404, "JOB_NOT_FOUND")
    assert_error(
        await view(client, rec, cand["candidate_id"], job_id=str(uuid.uuid4())), 404, "JOB_NOT_FOUND"
    )


async def test_match_explanation_requires_access_to_the_job_for_hiring_managers(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    assigned = await create_job(client, rec, publish=True, hiring_manager_id=hm["id"])
    unassigned = await create_job(client, rec, publish=True, title="Another Role")
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    await apply_job(client, cand, assigned["id"])
    assert (await view(client, hm, cand["candidate_id"], job_id=assigned["id"])).json()["match"][
        "job_id"
    ] == assigned["id"]
    assert_error(await view(client, hm, cand["candidate_id"], job_id=unassigned["id"]), 404, "JOB_NOT_FOUND")


async def test_contact_details_use_the_account_values_for_registered_candidates(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    await apply_job(client, cand, job["id"])
    new_phone = "+44 20 7946 0958"
    await client.patch(f"{API}/auth/me", headers=cand["h"], json={"phone": new_phone})
    body = (await view(client, rec, cand["candidate_id"])).json()
    assert body["phone"] == new_phone and body["email"] == cand["email"]
    assert (
        await scalar(
            "SELECT contact_email FROM candidate_profiles WHERE id = :c", c=uuid.UUID(cand["candidate_id"])
        )
        is None
    ), "no second copy of the e-mail"
