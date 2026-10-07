"""Workflow 6: application -> shortlist -> schedule -> candidate notified -> candidate views (no internal data) ->
confirm -> complete -> feedback -> recruiter advances the application."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import register_candidate
from tests.helpers_ops import API, company_with_staff, schedule, shortlisted, sql, uid, utc_slot

pytestmark = pytest.mark.e2e

FORBIDDEN_KEYS = {
    "notes",
    "feedback",
    "rating",
    "recommendation",
    "strengths",
    "weaknesses",
    "cancelled_reason",
    "created_by_id",
    "created_by_name",
    "participants",
    "feedback_count",
    "email",
}


def _walk_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            keys |= _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            keys |= _walk_keys(v)
    return keys


def freeze_now(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr("app.services.interviews._now", lambda: moment)


async def test_full_interview_workflow(client, monkeypatch):
    co = await company_with_staff(client)
    rec, interviewer = co["rec"], co["rec2"]
    sl = await shortlisted(client, rec)
    app_id, cand = sl["app"]["id"], sl["cand"]
    start, end = utc_slot(days=3, hour=10)

    # --- schedule: the shortlisted application advances to INTERVIEW (history comment "Interview scheduled")
    r = await schedule(
        client,
        rec,
        app_id,
        [interviewer],
        start=start,
        end=end,
        notes="Probe distributed systems; salary expectations are high",
        location="HQ, room 4",
    )
    assert r.status_code == 201, r.text
    iv = r.json()
    assert iv["status"] == "SCHEDULED" and iv["audience"] == "staff"
    assert iv["application"]["status"] == "INTERVIEW"
    assert iv["application"]["allowed_next_statuses"] == ["OFFER", "REJECTED"]
    assert [p["name"] for p in iv["participants"]] == ["Sam Recruiter"]
    hist = (await client.get(f"{API}/applications/{app_id}/history", headers=rec["h"])).json()
    assert [h["to_status"] for h in hist] == ["APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW"]
    assert hist[-1]["comment"] == "Interview scheduled"

    # --- notifications: the candidate and the interviewer (not the actor) were notified exactly once
    notes = (await client.get(f"{API}/notifications", headers=cand["h"])).json()["items"]
    sched = [n for n in notes if n["type"] == "INTERVIEW_SCHEDULED"]
    assert (
        len(sched) == 1
        and sched[0]["interview_id"] == iv["id"]
        and "Technical interview" in sched[0]["message"]
    )
    assert any(n["type"] == "APPLICATION_STATUS_CHANGED" and "interview stage" in n["message"] for n in notes)
    staff_notes = (await client.get(f"{API}/notifications", headers=interviewer["h"])).json()["items"]
    assert [n["type"] for n in staff_notes] == ["INTERVIEW_SCHEDULED"]
    assert not [
        n
        for n in (await client.get(f"{API}/notifications", headers=rec["h"])).json()["items"]
        if n["type"] == "INTERVIEW_SCHEDULED"
    ]

    # --- candidate view: logistics only, never internal data
    cv = await client.get(f"{API}/interviews/{iv['id']}", headers=cand["h"])
    assert cv.status_code == 200
    body = cv.json()
    assert body["audience"] == "candidate" and body["can_confirm"] is True
    assert body["job_title"] == "Backend Engineer" and body["interviewers"] == ["Sam Recruiter"]
    assert body["location"] == "HQ, room 4" and body["timezone"] == "UTC" and body["status"] == "SCHEDULED"
    assert not (_walk_keys(body) & FORBIDDEN_KEYS), _walk_keys(body) & FORBIDDEN_KEYS
    assert "Probe distributed systems" not in cv.text and "salary expectations" not in cv.text
    lst = (await client.get(f"{API}/interviews", headers=cand["h"])).json()
    assert lst["total"] == 1 and not (_walk_keys(lst) & FORBIDDEN_KEYS)

    # --- candidate confirms (idempotent); staff cannot confirm on their behalf
    assert (await client.post(f"{API}/interviews/{iv['id']}/confirm", headers=rec["h"])).status_code == 403
    c1 = await client.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])
    assert c1.status_code == 200 and c1.json()["status"] == "CONFIRMED" and c1.json()["can_confirm"] is False
    assert (await client.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])).json()[
        "status"
    ] == "CONFIRMED"

    # --- feedback is not possible before the interview started, nor can it be completed
    fb = {
        "rating": 4,
        "recommendation": "HIRE",
        "strengths": "Strong SQL",
        "weaknesses": "Queues",
        "notes": "Pair with platform",
    }
    early = await client.post(f"{API}/interviews/{iv['id']}/feedback", headers=interviewer["h"], json=fb)
    assert early.status_code == 422 and early.json()["error"]["code"] == "FEEDBACK_TOO_EARLY"
    early_c = await client.post(f"{API}/interviews/{iv['id']}/complete", headers=rec["h"])
    assert early_c.status_code == 422 and early_c.json()["error"]["code"] == "INTERVIEW_NOT_STARTED"

    # --- the interview takes place
    start_dt = datetime.fromisoformat(start)
    freeze_now(monkeypatch, start_dt + timedelta(minutes=75))
    done = await client.post(f"{API}/interviews/{iv['id']}/complete", headers=rec["h"])
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    assert done.json()["can_submit_feedback"] is True
    assert await sql(
        "SELECT is_active FROM interview_participants WHERE interview_id = :i", i=uuid.UUID(iv["id"])
    ) == [(False,)]

    f1 = await client.post(f"{API}/interviews/{iv['id']}/feedback", headers=interviewer["h"], json=fb)
    assert f1.status_code == 201 and f1.json()["is_mine"] is True and f1.json()["rating"] == 4
    f2 = await client.post(
        f"{API}/interviews/{iv['id']}/feedback",
        headers=rec["h"],
        json={"rating": 5, "recommendation": "STRONG_HIRE", "notes": "Great"},
    )
    assert f2.status_code == 201

    # candidates can never read, write or update feedback
    for method, kw in (("get", {}), ("post", {"json": fb}), ("put", {"json": fb})):
        resp = await getattr(client, method)(f"{API}/interviews/{iv['id']}/feedback", headers=cand["h"], **kw)
        assert resp.status_code == 403, (method, resp.text)
    summary = (await client.get(f"{API}/interviews/{iv['id']}/feedback", headers=rec["h"])).json()
    assert summary["count"] == 2 and summary["average_rating"] == 4.5
    assert summary["recommendations"]["HIRE"] == 1 and summary["recommendations"]["STRONG_HIRE"] == 1
    assert {i["author_name"] for i in summary["items"]} == {"Sam Recruiter", "Riley Recruiter"}
    # the candidate representation still contains nothing internal after feedback exists
    after = await client.get(f"{API}/interviews/{iv['id']}", headers=cand["h"])
    assert not (_walk_keys(after.json()) & FORBIDDEN_KEYS) and "Strong SQL" not in after.text

    # --- recording feedback did not silently move the application; the recruiter advances it explicitly
    detail = (await client.get(f"{API}/interviews/{iv['id']}", headers=rec["h"])).json()
    assert detail["feedback_count"] == 2 and detail["application"]["status"] == "INTERVIEW"
    assert detail["application"]["allowed_next_statuses"] == ["OFFER", "REJECTED"]
    adv = await client.post(f"{API}/applications/{app_id}/status", headers=rec["h"], json={"status": "OFFER"})
    assert adv.status_code == 200 and adv.json()["status"] == "OFFER"
    assert (await client.get(f"{API}/interviews/{iv['id']}", headers=rec["h"])).json()["application"][
        "allowed_next_statuses"
    ] == ["HIRED", "REJECTED"]

    # --- audit trail
    actions = {
        r[0]
        for r in await sql(
            "SELECT action FROM audit_events WHERE entity_type = 'interview' AND entity_id = :i",
            i=uuid.UUID(iv["id"]),
        )
    }
    assert {
        "interview.scheduled",
        "interview.confirmed",
        "interview.completed",
        "interview.feedback_submitted",
    } <= actions


async def test_timezone_is_honoured_and_naive_times_are_read_in_that_zone(client):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"])
    day = (datetime.now(UTC) + timedelta(days=10)).date()
    r = await schedule(
        client,
        co["rec"],
        sl["app"]["id"],
        [co["rec2"]],
        start=f"{day}T09:00:00",
        end=f"{day}T10:30:00",
        timezone="Europe/Berlin",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["timezone"] == "Europe/Berlin" and body["duration_minutes"] == 90
    assert body["start_at"].endswith("Z") and body["start_local"].startswith(f"{day}T09:00:00")
    assert datetime.fromisoformat(body["start_at"]).hour in (7, 8)  # Berlin is UTC+1 / UTC+2
    cv = (await client.get(f"{API}/interviews/{body['id']}", headers=sl["cand"]["h"])).json()
    assert cv["timezone"] == "Europe/Berlin" and cv["start_local"].startswith(f"{day}T09:00:00")


async def test_application_advances_only_once_and_second_interview_keeps_stage(client):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"])
    s1, e1 = utc_slot(days=3, hour=9)
    s2, e2 = utc_slot(days=3, hour=13)
    assert (
        await schedule(client, co["rec"], sl["app"]["id"], [co["rec2"]], start=s1, end=e1)
    ).status_code == 201
    r = await schedule(
        client, co["rec"], sl["app"]["id"], [co["rec2"]], start=s2, end=e2, interview_type="FINAL"
    )
    assert r.status_code == 201 and r.json()["application"]["status"] == "INTERVIEW"
    hist = (await client.get(f"{API}/applications/{sl['app']['id']}/history", headers=co["rec"]["h"])).json()
    assert [h["to_status"] for h in hist].count("INTERVIEW") == 1
    lst = (
        await client.get(
            f"{API}/interviews", headers=co["rec"]["h"], params={"application_id": sl["app"]["id"]}
        )
    ).json()
    assert lst["total"] == 2 and [i["interview_type"] for i in lst["items"]] == [
        "TECHNICAL",
        "FINAL",
    ]  # sorted by start


async def test_unregistered_candidate_is_skipped_without_error(client):
    """Imported candidates have no user: scheduling must not fail because there is nobody to notify."""
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"], cand=await register_candidate(client))
    await sql(
        "UPDATE candidate_profiles SET user_id = NULL, source = 'IMPORTED', sourced_by_company_id = :c WHERE id = :p",
        c=uuid.UUID(co["rec"]["company_id"]),
        p=uuid.UUID(sl["cand"]["candidate_id"]),
    )
    r = await schedule(client, co["rec"], sl["app"]["id"], [co["rec2"]])
    assert r.status_code == 201, r.text
    assert json.loads(r.text)["participants"][0]["user_id"] == uid(co["rec2"])
