"""Applications: submission rules, withdrawal, the stage workflow, history, visibility and internal notes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient

from app.db.models import ApplicationStatus as A
from app.services.applications import TRANSITIONS
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
    expire_deadline,
    fast_argon,
    scalar,
    set_application_status,
    set_job_status,
    sql,
)

pytestmark = pytest.mark.e2e

APPS = f"{API}/applications"


async def world(client: AsyncClient, *, staff: bool = False) -> dict[str, Any]:
    """Company, published job and one candidate; ``staff=True`` adds a second recruiter and a hiring manager assigned to the job."""
    rec = await register_employer(client, "Apply Co")
    hm = await add_staff(client, rec, "HIRING_MANAGER") if staff else None
    rec2 = await add_staff(client, rec, "RECRUITER") if staff else None
    job = await create_job(client, rec, publish=True, **({"hiring_manager_id": hm["id"]} if hm else {}))
    cand = await register_candidate(client, first="Casey", last="Candidate")
    return {"rec": rec, "hm": hm, "rec2": rec2, "job": job, "cand": cand}


async def move(
    client: AsyncClient, rec: dict[str, Any], app_id: str, status: str, comment: str | None = None
):  # type: ignore[no-untyped-def]
    return await client.post(
        f"{APPS}/{app_id}/status",
        headers=rec["h"],
        json={"status": status, **({"comment": comment} if comment else {})},
    )


# --- applying -----------------------------------------------------------------------------------------------------------------------------------


async def test_apply_happy_path(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    r = await client.post(
        APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"], "cover_letter": "I would love to join."}
    )
    assert r.status_code == 201, r.text
    app = r.json()
    assert (app["status"], app["cover_letter"], app["source"], app["job_title"], app["company_name"]) == (
        "APPLIED",
        "I would love to join.",
        "DIRECT",
        "Backend Engineer",
        "Apply Co",
    )
    assert (
        app["candidate_name"] == "Casey Candidate"
        and app["resume_id"] is None
        and app["rejection_reason"] is None
    )
    assert app["allowed_next_statuses"] == [] and app["match"] is None, (
        "candidates get neither stage controls nor a score"
    )
    assert [(h["from_status"], h["to_status"], h["actor_name"]) for h in app["history"]] == [
        (None, "APPLIED", "You")
    ]
    aid = uuid.UUID(app["id"])
    assert (
        await scalar("SELECT count(*) FROM application_status_history WHERE application_id = :a", a=aid) == 1
    )
    assert (
        await scalar(
            "SELECT count(*) FROM audit_events WHERE action = 'application.submitted' AND entity_id = :a",
            a=aid,
        )
        == 1
    )
    # notifications: the candidate and the people responsible for the job (creator + hiring manager), nobody else
    rows = await sql(
        "SELECT user_id, type, title, application_id, job_id FROM notifications WHERE type = 'APPLICATION_SUBMITTED'"
    )
    assert {str(r[0]) for r in rows} == {w["cand"]["user"]["id"], w["rec"]["user"]["id"], w["hm"]["id"]}
    assert all(r[3] == aid and str(r[4]) == w["job"]["id"] for r in rows)
    titles = {str(r[0]): r[2] for r in rows}
    assert (
        titles[w["cand"]["user"]["id"]] == "Application submitted"
        and titles[w["rec"]["user"]["id"]] == "New application"
    )
    assert (
        await scalar("SELECT count(*) FROM notifications WHERE user_id = :u", u=uuid.UUID(w["rec2"]["id"]))
        == 0
    )


async def test_applying_queues_a_match_run_so_the_applicant_is_ranked(client: AsyncClient) -> None:
    w = await world(client)
    await fill_backend_profile(client, w["cand"])
    app = await apply_job(client, w["cand"], w["job"]["id"])
    row = (
        await sql(
            "SELECT overall_score, job_hash, candidate_hash FROM candidate_job_matches WHERE job_id = :j AND candidate_id = :c",
            j=uuid.UUID(w["job"]["id"]),
            c=uuid.UUID(w["cand"]["candidate_id"]),
        )
    )[0]
    assert row[0] > 0.5 and len(row[1]) == 64 and len(row[2]) == 64
    staff = (await client.get(f"{APPS}/{app['id']}", headers=w["rec"]["h"])).json()
    assert (
        staff["match"]["overall_score"] == pytest.approx(row[0])
        and staff["match"]["band"] in {"STRONG", "GOOD"}
        and staff["match"]["summary"]
    )


async def test_duplicate_application_is_a_conflict(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    await apply_job(client, w["cand"], w["job"]["id"])
    err = assert_error(
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}),
        409,
        "APPLICATION_ALREADY_EXISTS",
    )
    assert "already applied" in err["message"]
    assert await scalar("SELECT count(*) FROM applications") == 1
    assert await scalar("SELECT count(*) FROM notifications WHERE type = 'APPLICATION_SUBMITTED'") == 3, (
        "the failed attempt notified nobody"
    )


async def test_concurrent_double_submit_creates_exactly_one_application(client: AsyncClient) -> None:
    w = await world(client)
    results = await asyncio.gather(
        *(client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}) for _ in range(5))
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in results]
    assert all(
        r.json()["error"]["code"] == "APPLICATION_ALREADY_EXISTS" for r in results if r.status_code == 409
    )
    assert await scalar("SELECT count(*) FROM applications") == 1
    assert await scalar("SELECT count(*) FROM application_status_history") == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("DRAFT", (404, "JOB_NOT_FOUND")),
        ("ARCHIVED", (404, "JOB_NOT_FOUND")),
        ("PAUSED", (422, "JOB_NOT_ACCEPTING_APPLICATIONS")),
        ("CLOSED", (422, "JOB_NOT_ACCEPTING_APPLICATIONS")),
    ],
)
async def test_jobs_that_do_not_accept_applications(
    client: AsyncClient, status: str, expected: tuple[int, str]
) -> None:
    w = await world(client)
    await set_job_status(w["job"]["id"], status)
    assert_error(await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}), *expected)
    assert await scalar("SELECT count(*) FROM applications") == 0


async def test_unknown_job_and_deadline_rules(client: AsyncClient) -> None:
    w = await world(client)
    assert_error(
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": str(uuid.uuid4())}),
        404,
        "JOB_NOT_FOUND",
    )
    await expire_deadline(w["job"]["id"])
    err = assert_error(
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}),
        422,
        "JOB_NOT_ACCEPTING_APPLICATIONS",
    )
    assert "deadline" in err["message"]
    await expire_deadline(w["job"]["id"], days_ago=0)  # the deadline day itself is still open
    assert (
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]})
    ).status_code == 201
    assert date.today().isoformat()


async def test_only_candidates_can_apply(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    for who in (w["rec"], w["hm"], await create_admin(client)):
        assert_error(
            await client.post(APPS, headers=who["h"], json={"job_id": w["job"]["id"]}), 403, "FORBIDDEN"
        )
    assert_error(await client.post(APPS, json={"job_id": w["job"]["id"]}), 401, "UNAUTHORIZED")


async def test_application_payload_validation(client: AsyncClient) -> None:
    w = await world(client)
    h, jid = w["cand"]["h"], w["job"]["id"]
    for bad in (
        {"job_id": "nope"},
        {},
        {"job_id": jid, "cover_letter": "x" * 8001},
        {"job_id": jid, "source": "HACK"},
        {"job_id": jid, "resume_id": "nope"},
    ):
        assert_error(await client.post(APPS, headers=h, json=bad), 422, "VALIDATION_ERROR")
    for source in ("RECOMMENDATION", "SEARCH", "REFERRAL"):
        job = await create_job(client, w["rec"], title=f"Source {source}", publish=True)
        r = await client.post(APPS, headers=h, json={"job_id": job["id"], "source": source})
        assert r.status_code == 201 and r.json()["source"] == source


async def test_resume_selection(client: AsyncClient) -> None:
    w = await world(client)
    other = await register_candidate(client)
    mine, primary, theirs = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (:i, :c, 'PROCESSED', false)",
        i=mine,
        c=uuid.UUID(w["cand"]["candidate_id"]),
    )
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (:i, :c, 'PROCESSED', true)",
        i=primary,
        c=uuid.UUID(w["cand"]["candidate_id"]),
    )
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (:i, :c, 'PROCESSED', true)",
        i=theirs,
        c=uuid.UUID(other["candidate_id"]),
    )
    assert_error(
        await client.post(
            APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"], "resume_id": str(theirs)}
        ),
        404,
        "RESUME_NOT_FOUND",
    )
    assert_error(
        await client.post(
            APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"], "resume_id": str(uuid.uuid4())}
        ),
        404,
        "RESUME_NOT_FOUND",
    )
    default = await apply_job(client, w["cand"], w["job"]["id"])
    assert default["resume_id"] == str(primary), "defaults to the primary résumé"
    job2 = await create_job(client, w["rec"], title="Explicit Resume Role", publish=True)
    explicit = await apply_job(client, w["cand"], job2["id"], resume_id=str(mine))
    assert explicit["resume_id"] == str(mine)


# --- withdrawal ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["APPLIED", "SCREENING"])
async def test_candidates_can_withdraw_early_applications(client: AsyncClient, stage: str) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    if stage != "APPLIED":
        await move(client, w["rec"], app["id"], stage)
    r = await client.post(
        f"{APPS}/{app['id']}/withdraw", headers=w["cand"]["h"], json={"comment": "Accepted another offer"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "WITHDRAWN" and body["allowed_next_statuses"] == []
    last = body["history"][-1]
    assert (last["to_status"], last["actor_name"], last["comment"]) == (
        "WITHDRAWN",
        "You",
        "Accepted another offer",
    )
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'application.withdrawn'") == 1


@pytest.mark.parametrize("stage", ["SHORTLISTED", "INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN"])
async def test_late_or_finished_applications_cannot_be_withdrawn(client: AsyncClient, stage: str) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    await set_application_status(app["id"], stage)
    err = assert_error(
        await client.post(f"{APPS}/{app['id']}/withdraw", headers=w["cand"]["h"]), 422, "CANNOT_WITHDRAW"
    )
    assert err["details"] == {"status": stage}
    assert await scalar("SELECT status FROM applications WHERE id = :a", a=uuid.UUID(app["id"])) == stage


async def test_only_the_owner_can_withdraw(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    other = await register_candidate(client)
    assert_error(
        await client.post(f"{APPS}/{app['id']}/withdraw", headers=other["h"]), 404, "APPLICATION_NOT_FOUND"
    )
    for staff in (w["rec"], w["hm"], await create_admin(client)):
        assert_error(await client.post(f"{APPS}/{app['id']}/withdraw", headers=staff["h"]), 403, "FORBIDDEN")
    assert_error(await client.post(f"{APPS}/{app['id']}/withdraw"), 401, "UNAUTHORIZED")
    assert_error(
        await client.post(f"{APPS}/{uuid.uuid4()}/withdraw", headers=w["cand"]["h"]),
        404,
        "APPLICATION_NOT_FOUND",
    )
    assert await scalar("SELECT status FROM applications WHERE id = :a", a=uuid.UUID(app["id"])) == "APPLIED"


async def test_reapplying_after_a_withdrawal_creates_a_fresh_application(client: AsyncClient) -> None:
    w = await world(client)
    first = await apply_job(client, w["cand"], w["job"]["id"])
    await client.post(f"{APPS}/{first['id']}/withdraw", headers=w["cand"]["h"])
    second = await apply_job(client, w["cand"], w["job"]["id"])
    assert second["id"] != first["id"] and second["status"] == "APPLIED" and len(second["history"]) == 1
    assert sorted(r[0] for r in await sql("SELECT status FROM applications")) == ["APPLIED", "WITHDRAWN"]
    # the live one blocks a third attempt; the withdrawn one is still reachable
    assert_error(
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}),
        409,
        "APPLICATION_ALREADY_EXISTS",
    )
    assert (await client.get(f"{APPS}/{first['id']}", headers=w["cand"]["h"])).json()["status"] == "WITHDRAWN"
    # a withdraw -> re-apply cycle works repeatedly
    await client.post(f"{APPS}/{second['id']}/withdraw", headers=w["cand"]["h"])
    assert (
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]})
    ).status_code == 201
    assert await scalar("SELECT count(*) FROM applications WHERE status <> 'WITHDRAWN'") == 1


@pytest.mark.parametrize("final", ["REJECTED", "HIRED"])
async def test_reapplying_after_a_final_decision_is_refused(client: AsyncClient, final: str) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    await set_application_status(app["id"], final)
    assert_error(
        await client.post(APPS, headers=w["cand"]["h"], json={"job_id": w["job"]["id"]}),
        409,
        "APPLICATION_ALREADY_EXISTS",
    )


# --- the stage workflow -------------------------------------------------------------------------------------------------------------------------------------


async def test_the_happy_path_from_application_to_hire(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    expected_next = {
        "SCREENING": ["REJECTED", "SHORTLISTED"],
        "SHORTLISTED": ["INTERVIEW", "REJECTED"],
        "INTERVIEW": ["OFFER", "REJECTED"],
        "OFFER": ["HIRED", "REJECTED"],
        "HIRED": [],
    }
    for stage, nxt in expected_next.items():
        r = await move(client, w["rec"], app["id"], stage, comment=f"moved to {stage}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == stage and r.json()["allowed_next_statuses"] == nxt
    hist = (await client.get(f"{APPS}/{app['id']}/history", headers=w["rec"]["h"])).json()
    assert [(h["from_status"], h["to_status"]) for h in hist] == [
        (None, "APPLIED"),
        ("APPLIED", "SCREENING"),
        ("SCREENING", "SHORTLISTED"),
        ("SHORTLISTED", "INTERVIEW"),
        ("INTERVIEW", "OFFER"),
        ("OFFER", "HIRED"),
    ]
    assert [h["actor_name"] for h in hist] == ["Casey Candidate"] + ["You"] * 5, (
        "staff see their own actions as 'You' and the candidate by name"
    )
    assert hist[2]["comment"] == "moved to SHORTLISTED"
    stamps = [h["created_at"] for h in hist]
    assert stamps == sorted(stamps)
    assert await scalar("SELECT count(*) FROM audit_events WHERE action = 'application.status_changed'") == 5


@pytest.mark.parametrize("source", list(A))
async def test_every_status_pair_through_the_api(client: AsyncClient, source: A) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    for target in A:
        await set_application_status(app["id"], source.value)
        r = await move(client, w["rec"], app["id"], target.value)
        if target == A.WITHDRAWN:
            assert_error(r, 422, "WITHDRAW_BY_CANDIDATE_ONLY")
        elif target in TRANSITIONS[source]:
            assert r.status_code == 200 and r.json()["status"] == target.value, (source, target, r.text)
        else:
            err = assert_error(r, 409, "INVALID_STATE_TRANSITION")
            assert err["details"] == {
                "from": source.value,
                "to": target.value,
                "allowed": sorted(s.value for s in TRANSITIONS[source]),
            }
            assert (
                await scalar("SELECT status FROM applications WHERE id = :a", a=uuid.UUID(app["id"]))
                == source.value
            )


async def test_terminal_states_cannot_be_left_and_leave_no_history(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    assert (await move(client, w["rec"], app["id"], "REJECTED", "not a fit")).status_code == 200
    for target in ("SCREENING", "APPLIED", "REJECTED", "HIRED"):
        assert_error(await move(client, w["rec"], app["id"], target), 409, "INVALID_STATE_TRANSITION")
    assert (
        await scalar(
            "SELECT count(*) FROM application_status_history WHERE application_id = :a",
            a=uuid.UUID(app["id"]),
        )
        == 2
    )


async def test_status_change_payload_validation_and_unknown_application(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    for bad in ({}, {"status": "DONE"}, {"status": "SCREENING", "comment": "x" * 2001}):
        assert_error(
            await client.post(f"{APPS}/{app['id']}/status", headers=w["rec"]["h"], json=bad),
            422,
            "VALIDATION_ERROR",
        )
    assert_error(await move(client, w["rec"], str(uuid.uuid4()), "SCREENING"), 404, "APPLICATION_NOT_FOUND")
    assert_error(
        await client.post(f"{APPS}/{app['id']}/status", json={"status": "SCREENING"}), 401, "UNAUTHORIZED"
    )


async def test_rejection_reason_is_visible_to_staff_only(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    await move(client, w["rec"], app["id"], "REJECTED", "Salary expectations far above budget")
    staff = (await client.get(f"{APPS}/{app['id']}", headers=w["rec"]["h"])).json()
    assert staff["rejection_reason"] == "Salary expectations far above budget"
    mine = (await client.get(f"{APPS}/{app['id']}", headers=w["cand"]["h"])).json()
    assert mine["rejection_reason"] is None and "Salary" not in str(mine)
    n = await sql(
        "SELECT message FROM notifications WHERE user_id = :u AND type = 'APPLICATION_STATUS_CHANGED'",
        u=uuid.UUID(w["cand"]["user"]["id"]),
    )
    assert n and "Salary" not in n[0][0], "the internal comment never leaks into the candidate notification"


async def test_stage_changes_notify_the_candidate_once_each(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    for stage in ("SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED"):
        await move(client, w["rec"], app["id"], stage)
    rows = await sql(
        "SELECT title, message, dedupe_key FROM notifications WHERE user_id = :u AND type = 'APPLICATION_STATUS_CHANGED' ORDER BY dedupe_key",
        u=uuid.UUID(w["cand"]["user"]["id"]),
    )
    assert len(rows) == 5 and all(r[0] == "Application update" and "Backend Engineer" in r[1] for r in rows)
    assert {r[2] for r in rows} == {
        f"app-status:{app['id']}:{s}" for s in ("SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED")
    }


async def test_closing_a_job_does_not_freeze_its_applications(client: AsyncClient) -> None:
    w = await world(client)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    await client.post(f"{API}/jobs/{w['job']['id']}/close", headers=w["rec"]["h"])
    assert (await move(client, w["rec"], app["id"], "SCREENING")).status_code == 200
    assert (await client.post(f"{APPS}/{app['id']}/withdraw", headers=w["cand"]["h"])).status_code == 200


# --- who sees what ----------------------------------------------------------------------------------------------------------------------------------------------


async def test_candidates_see_the_timeline_but_not_staff_identities_or_comments(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    await move(client, w["rec"], app["id"], "SCREENING", "Internal: referral from the CTO")
    await move(client, w["rec2"], app["id"], "SHORTLISTED", "Internal: salary is a risk")
    mine = (await client.get(f"{APPS}/{app['id']}", headers=w["cand"]["h"])).json()
    assert [h["actor_name"] for h in mine["history"]] == ["You", "Hiring team", "Hiring team"]
    assert [h["comment"] for h in mine["history"]] == [None, None, None]
    blob = str(mine)
    for secret in ("Riley", "Sam", "CTO", "salary is a risk", w["rec"]["user"]["id"], w["rec"]["email"]):
        assert secret not in blob, secret
    assert [
        h["to_status"]
        for h in (await client.get(f"{APPS}/{app['id']}/history", headers=w["cand"]["h"])).json()
    ] == ["APPLIED", "SCREENING", "SHORTLISTED"]
    staff = (await client.get(f"{APPS}/{app['id']}", headers=w["rec"]["h"])).json()
    assert [h["actor_name"] for h in staff["history"]] == ["Casey Candidate", "You", "Sam Recruiter"]
    colleague = (await client.get(f"{APPS}/{app['id']}", headers=w["rec2"]["h"])).json()
    assert [h["actor_name"] for h in colleague["history"]] == ["Casey Candidate", "Riley Recruiter", "You"]
    assert [h["comment"] for h in staff["history"]][1:] == [
        "Internal: referral from the CTO",
        "Internal: salary is a risk",
    ]


async def test_internal_notes_are_for_hiring_staff_only(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    url = f"{APPS}/{app['id']}/notes"
    admin = await create_admin(client)
    for author, text in (
        (w["rec"], "Strong portfolio."),
        (w["hm"], "I like the system-design answers."),
        (w["rec2"], "Check references."),
        (admin, "Flagged by platform ops."),
    ):
        r = await client.post(url, headers=author["h"], json={"body": f"  {text}  "})
        assert r.status_code == 201, r.text
        assert r.json()["body"] == text and r.json()["author_id"] == author["user"]["id"]
    listed = (await client.get(url, headers=w["rec"]["h"])).json()
    assert [n["body"] for n in listed] == [
        "Flagged by platform ops.",
        "Check references.",
        "I like the system-design answers.",
        "Strong portfolio.",
    ], "newest first"
    assert {n["author_name"] for n in listed} == {
        "Riley Recruiter",
        "Sam Hiring_Manager",
        "Sam Recruiter",
        "Ada Admin",
    }
    # the candidate can neither read nor write them, and they never show up in the candidate's view
    assert_error(await client.get(url, headers=w["cand"]["h"]), 403, "FORBIDDEN")
    assert_error(await client.post(url, headers=w["cand"]["h"], json={"body": "hi"}), 403, "FORBIDDEN")
    assert "Strong portfolio" not in (await client.get(f"{APPS}/{app['id']}", headers=w["cand"]["h"])).text
    assert_error(await client.get(url), 401, "UNAUTHORIZED")
    for bad in ({}, {"body": ""}, {"body": "x" * 4001}):
        assert_error(await client.post(url, headers=w["rec"]["h"], json=bad), 422, "VALIDATION_ERROR")


async def test_notes_respect_tenant_and_assignment_boundaries(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    outsider = await register_employer(client)
    other_hm = await add_staff(client, w["rec"], "HIRING_MANAGER")
    url = f"{APPS}/{app['id']}/notes"
    for who in (outsider, other_hm):
        assert_error(await client.get(url, headers=who["h"]), 404, "APPLICATION_NOT_FOUND")
        assert_error(
            await client.post(url, headers=who["h"], json={"body": "intruder"}), 404, "APPLICATION_NOT_FOUND"
        )
    assert await scalar("SELECT count(*) FROM application_notes") == 0


async def test_hiring_managers_review_but_do_not_decide(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    detail = await client.get(f"{APPS}/{app['id']}", headers=w["hm"]["h"])
    assert detail.status_code == 200 and detail.json()["allowed_next_statuses"] == [], (
        "no stage controls for a hiring manager"
    )
    assert (await client.get(f"{APPS}/{app['id']}/history", headers=w["hm"]["h"])).status_code == 200
    assert (
        await client.post(
            f"{APPS}/{app['id']}/notes", headers=w["hm"]["h"], json={"body": "Looks promising."}
        )
    ).status_code == 201
    assert_error(await move(client, w["hm"], app["id"], "SCREENING"), 403, "FORBIDDEN")
    assert_error(await client.post(f"{APPS}/{app['id']}/withdraw", headers=w["hm"]["h"]), 403, "FORBIDDEN")
    assert await scalar("SELECT status FROM applications WHERE id = :a", a=uuid.UUID(app["id"])) == "APPLIED"


async def test_tenant_isolation_on_single_applications(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    outsider = await register_employer(client)
    other = await register_candidate(client)
    other_hm = await add_staff(
        client, w["rec"], "HIRING_MANAGER"
    )  # same company, but not assigned to this job
    for viewer in (outsider, other, other_hm):
        assert_error(
            await client.get(f"{APPS}/{app['id']}", headers=viewer["h"]), 404, "APPLICATION_NOT_FOUND"
        )
        assert_error(
            await client.get(f"{APPS}/{app['id']}/history", headers=viewer["h"]), 404, "APPLICATION_NOT_FOUND"
        )
    assert_error(await move(client, outsider, app["id"], "SCREENING"), 404, "APPLICATION_NOT_FOUND")
    assert_error(await client.get(f"{APPS}/{app['id']}"), 401, "UNAUTHORIZED")
    assert_error(await client.get(f"{APPS}/nope", headers=w["rec"]["h"]), 422, "VALIDATION_ERROR")
    admin = await create_admin(client)
    assert (await client.get(f"{APPS}/{app['id']}", headers=admin["h"])).status_code == 200
    assert (await move(client, admin, app["id"], "SCREENING")).status_code == 200


async def test_application_belongs_to_the_company_not_the_individual_recruiter(client: AsyncClient) -> None:
    w = await world(client, staff=True)
    app = await apply_job(client, w["cand"], w["job"]["id"])
    assert (await move(client, w["rec2"], app["id"], "SCREENING")).status_code == 200, (
        "any recruiter of the owning company can act"
    )
    assert (await client.get(f"{APPS}/{app['id']}", headers=w["rec2"]["h"])).json()["status"] == "SCREENING"
