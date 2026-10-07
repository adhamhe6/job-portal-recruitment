"""Double-booking protection: friendly pre-check, race-safe database fallback, reschedule and cancel semantics."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest

from app.services.interviews import InterviewService
from tests.helpers import create_job, register_candidate, register_employer
from tests.helpers_ops import API, company_with_staff, schedule, shortlisted, sql, uid, utc_slot

pytestmark = pytest.mark.integration


async def _jobs_and_apps(client, rec, cand, n=2):
    out = []
    for i in range(n):
        job = await create_job(client, rec, publish=True, title=f"Role {i} {uuid.uuid4().hex[:4]}")
        out.append(await shortlisted(client, rec, job=job, cand=cand))
    return out


async def test_candidate_cannot_be_double_booked(client):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    cand = await register_candidate(client)
    a, b = await _jobs_and_apps(client, rec, cand)
    s, e = utc_slot(days=4, hour=9)
    first = await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)
    assert first.status_code == 201
    # overlapping window for the same candidate but a *different* application and interviewer
    start2 = datetime.fromisoformat(s).replace(minute=30).isoformat()
    end2 = datetime.fromisoformat(e).replace(hour=10, minute=30).isoformat()
    r = await schedule(client, rec, b["app"]["id"], [co["rec"]], start=start2, end=end2)
    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["code"] == "INTERVIEW_CONFLICT"
    conflict = err["details"]["conflicts"][0]
    assert conflict["kind"] == "candidate" and conflict["interview_id"] == first.json()["id"]
    assert datetime.fromisoformat(conflict["start_at"]) == datetime.fromisoformat(s)
    assert datetime.fromisoformat(conflict["end_at"]) == datetime.fromisoformat(e)
    assert "already has an interview" in err["message"] and "09:00 to 10:00 UTC" in err["message"]
    # back-to-back is fine (half-open ranges)
    s3 = e
    e3 = datetime.fromisoformat(e).replace(hour=11).isoformat()
    assert (await schedule(client, rec, b["app"]["id"], [rec], start=s3, end=e3)).status_code == 201


async def test_interviewer_cannot_be_double_booked_but_observers_can(client):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    a = await shortlisted(client, rec)
    b = await shortlisted(client, rec)
    s, e = utc_slot(days=4, hour=14)
    assert (await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)).status_code == 201
    r = await schedule(client, rec, b["app"]["id"], [rec2], start=s, end=e)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INTERVIEW_CONFLICT"
    c = r.json()["error"]["details"]["conflicts"][0]
    assert c["kind"] == "interviewer" and c["participant"] == "Sam Recruiter"
    assert "Sam Recruiter is already booked from" in r.json()["error"]["message"]
    # the same person as an OBSERVER does not block, and a different interviewer is free
    ok = await schedule(
        client,
        rec,
        b["app"]["id"],
        [rec],
        start=s,
        end=e,
        participants=[
            {"user_id": uid(rec), "role": "INTERVIEWER"},
            {"user_id": uid(rec2), "role": "OBSERVER"},
        ],
    )
    assert ok.status_code == 201, ok.text


async def test_cancel_frees_the_slot_for_candidate_and_interviewer(client):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    a = await shortlisted(client, rec)
    s, e = utc_slot(days=5, hour=9)
    iv = (await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)).json()
    assert (await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)).status_code == 409
    c = await client.post(
        f"{API}/interviews/{iv['id']}/cancel", headers=rec["h"], json={"reason": "Panel unavailable"}
    )
    assert c.status_code == 200 and c.json()["status"] == "CANCELLED"
    assert await sql(
        "SELECT is_active FROM interview_participants WHERE interview_id = :i", i=uuid.UUID(iv["id"])
    ) == [(False,)]
    again = await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)
    assert again.status_code == 201, again.text  # same candidate + interviewer + window works again
    assert again.json()["id"] != iv["id"]


async def test_reschedule_into_a_conflict_is_rejected_and_leaves_the_interview_untouched(client):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    a = await shortlisted(client, rec)
    b = await shortlisted(client, rec)
    s1, e1 = utc_slot(days=5, hour=9)
    s2, e2 = utc_slot(days=5, hour=13)
    first = (await schedule(client, rec, a["app"]["id"], [rec2], start=s1, end=e1)).json()
    second = (await schedule(client, rec, b["app"]["id"], [rec2], start=s2, end=e2)).json()
    r = await client.patch(
        f"{API}/interviews/{second['id']}", headers=rec["h"], json={"start_at": s1, "end_at": e1}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "INTERVIEW_CONFLICT"
    assert r.json()["error"]["details"]["conflicts"][0]["interview_id"] == first["id"]
    cur = (await client.get(f"{API}/interviews/{second['id']}", headers=rec["h"])).json()
    assert cur["status"] == "SCHEDULED" and datetime.fromisoformat(cur["start_at"]) == datetime.fromisoformat(
        s2
    )
    # an interview may overlap *its own* old slot when it is moved a little
    s3 = datetime.fromisoformat(s2).replace(minute=30).isoformat()
    moved = await client.patch(f"{API}/interviews/{second['id']}", headers=rec["h"], json={"start_at": s3})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "RESCHEDULED" and moved.json()["duration_minutes"] == 60


async def test_candidate_busy_with_another_company_is_a_conflict_without_leaking_details(client):
    co = await company_with_staff(client)
    other = await register_employer(client)
    other2 = await register_employer(client)  # a recruiter of a different company as the second interviewer
    cand = await register_candidate(client)
    a = await shortlisted(client, co["rec"], cand=cand)
    job_b = await create_job(client, other, publish=True, title="Competitor role")
    b = await shortlisted(client, other, job=job_b, cand=cand)
    s, e = utc_slot(days=6, hour=9)
    assert (
        await schedule(client, co["rec"], a["app"]["id"], [co["rec2"]], start=s, end=e)
    ).status_code == 201
    r = await schedule(client, other, b["app"]["id"], [other], start=s, end=e)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INTERVIEW_CONFLICT"
    err = r.json()["error"]
    assert err["message"] == "The candidate is not available at the requested time"
    assert err["details"]["conflicts"] == [
        {"kind": "candidate", "interview_id": None, "start_at": None, "end_at": None, "participant": None}
    ]
    assert other2 is not None


async def test_concurrent_requests_exactly_one_wins_same_candidate_different_applications(client):
    co = await company_with_staff(client)
    rec = co["rec"]
    cand = await register_candidate(client)
    a, b = await _jobs_and_apps(client, rec, cand)
    s, e = utc_slot(days=7, hour=9)
    # two different interviewers so only the candidate exclusion constraint can arbitrate
    rs = await asyncio.gather(
        schedule(client, rec, a["app"]["id"], [co["rec2"]], start=s, end=e),
        schedule(client, rec, b["app"]["id"], [rec], start=s, end=e),
    )
    assert sorted(r.status_code for r in rs) == [201, 409], [r.text for r in rs]
    loser = next(r for r in rs if r.status_code == 409)
    assert loser.json()["error"]["code"] == "INTERVIEW_CONFLICT"
    count = await sql(
        "SELECT count(*) FROM interviews WHERE candidate_id = :c AND status = 'SCHEDULED'",
        c=uuid.UUID(cand["candidate_id"]),
    )
    assert count == [(1,)]


async def test_concurrent_requests_exactly_one_wins_same_interviewer_different_candidates(client):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    sls = [await shortlisted(client, rec) for _ in range(4)]
    s, e = utc_slot(days=7, hour=15)
    rs = await asyncio.gather(*[schedule(client, rec, sl["app"]["id"], [rec2], start=s, end=e) for sl in sls])
    codes = sorted(r.status_code for r in rs)
    assert codes == [201, 409, 409, 409], [r.text for r in rs]
    assert {r.json()["error"]["code"] for r in rs if r.status_code == 409} == {"INTERVIEW_CONFLICT"}
    assert await sql(
        "SELECT count(*) FROM interview_participants WHERE user_id = :u AND is_active", u=uuid.UUID(uid(rec2))
    ) == [(1,)]
    # losers were rolled back completely: their applications did not advance to INTERVIEW
    stages = sorted(
        [
            (await client.get(f"{API}/applications/{sl['app']['id']}", headers=rec["h"])).json()["status"]
            for sl in sls
        ]
    )
    assert stages == ["INTERVIEW", "SHORTLISTED", "SHORTLISTED", "SHORTLISTED"]


async def test_concurrent_requests_for_the_same_application(client):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"])
    s, e = utc_slot(days=8, hour=9)
    rs = await asyncio.gather(
        *[schedule(client, co["rec"], sl["app"]["id"], [co["rec2"]], start=s, end=e) for _ in range(3)]
    )
    assert sorted(r.status_code for r in rs) == [201, 409, 409]
    hist = (await client.get(f"{API}/applications/{sl['app']['id']}/history", headers=co["rec"]["h"])).json()
    assert [h["to_status"] for h in hist].count("INTERVIEW") == 1


async def test_database_exclusion_constraint_is_the_race_safe_fallback(client, monkeypatch):
    """Force the pre-check to miss the clash (as in a real race): the exclusion violation must surface as the same 409."""
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    cand = await register_candidate(client)
    a, b = await _jobs_and_apps(client, rec, cand)
    s, e = utc_slot(days=9, hour=9)
    first = await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)
    assert first.status_code == 201

    real = InterviewService._find_conflicts
    state = {"blind": True}

    async def blind_once(self, **kw):
        if state["blind"]:
            state["blind"] = False
            return []
        return await real(self, **kw)

    monkeypatch.setattr(InterviewService, "_find_conflicts", blind_once)
    r = await schedule(client, rec, b["app"]["id"], [rec], start=s, end=e)
    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["code"] == "INTERVIEW_CONFLICT"
    assert (
        err["details"]["conflicts"][0]["interview_id"] == first.json()["id"]
    )  # friendly detail rebuilt after the rollback
    # the failed attempt left no partial state behind
    assert (await client.get(f"{API}/applications/{b['app']['id']}", headers=rec["h"])).json()[
        "status"
    ] == "SHORTLISTED"
    assert await sql(
        "SELECT count(*) FROM interviews WHERE application_id = :a", a=uuid.UUID(b["app"]["id"])
    ) == [(0,)]

    # same for the interviewer constraint
    state["blind"] = True
    c = await shortlisted(client, rec)
    r2 = await schedule(client, rec, c["app"]["id"], [rec2], start=s, end=e)
    assert r2.status_code == 409 and r2.json()["error"]["details"]["conflicts"][0]["kind"] == "interviewer"


async def test_participant_slots_stay_in_sync_after_reschedule_complete_and_no_show(client, monkeypatch):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    a = await shortlisted(client, rec)
    s, e = utc_slot(days=3, hour=9)
    iv = (await schedule(client, rec, a["app"]["id"], [rec2], start=s, end=e)).json()
    ns = datetime.fromisoformat(s).replace(hour=15)
    ne = datetime.fromisoformat(e).replace(hour=16)
    r = await client.patch(
        f"{API}/interviews/{iv['id']}",
        headers=rec["h"],
        json={"start_at": ns.isoformat(), "end_at": ne.isoformat()},
    )
    assert r.status_code == 200
    rows = await sql(
        "SELECT is_active, lower(during), upper(during) FROM interview_participants WHERE interview_id = :i",
        i=uuid.UUID(iv["id"]),
    )
    assert rows == [(True, ns, ne)]
    # the old slot is free again, the new one is taken
    b = await shortlisted(client, rec)
    assert (await schedule(client, rec, b["app"]["id"], [rec2], start=s, end=e)).status_code == 201
    assert (
        await schedule(client, rec, b["app"]["id"], [rec2], start=ns.isoformat(), end=ne.isoformat())
    ).status_code == 409
    monkeypatch.setattr("app.services.interviews._now", lambda: ne)
    assert (await client.post(f"{API}/interviews/{iv['id']}/no-show", headers=rec["h"])).json()[
        "status"
    ] == "NO_SHOW"
    assert await sql(
        "SELECT is_active FROM interview_participants WHERE interview_id = :i", i=uuid.UUID(iv["id"])
    ) == [(False,)]
