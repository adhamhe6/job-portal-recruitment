"""Reschedule / edit, cancel, complete, no-show, feedback rules, notifications and list filters."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import create_job
from tests.helpers_ops import API, company_with_staff, schedule, shortlisted, sql, uid, utc_slot

pytestmark = pytest.mark.integration

FB = {
    "rating": 3,
    "recommendation": "NO_HIRE",
    "strengths": "Friendly",
    "weaknesses": "Shallow answers",
    "notes": "Revisit later",
}


def at(moment: datetime):
    return lambda: moment


async def _notes(client, account, type_=None):
    items = (
        await client.get(f"{API}/notifications", headers=account["h"], params={"page_size": 100})
    ).json()["items"]
    return [n for n in items if type_ is None or n["type"] == type_]


@pytest.fixture
async def one(client):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"])
    s, e = utc_slot(days=4, hour=9)
    r = await schedule(
        client, co["rec"], sl["app"]["id"], [co["rec2"]], start=s, end=e, notes="internal note"
    )
    assert r.status_code == 201
    return {
        "client": client,
        "co": co,
        "sl": sl,
        "iv": r.json(),
        "start": s,
        "end": e,
        "rec": co["rec"],
        "rec2": co["rec2"],
        "cand": sl["cand"],
    }


async def test_reschedule_resets_confirmation_notifies_and_versions_notifications(one):
    c, iv, rec, cand = one["client"], one["iv"], one["rec"], one["cand"]
    assert (await c.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])).json()[
        "status"
    ] == "CONFIRMED"
    ns = (datetime.fromisoformat(one["start"]) + timedelta(hours=3)).isoformat()
    ne = (datetime.fromisoformat(one["end"]) + timedelta(hours=3)).isoformat()
    r = await c.patch(f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"start_at": ns, "end_at": ne})
    assert r.status_code == 200 and r.json()["status"] == "RESCHEDULED"
    cv = (await c.get(f"{API}/interviews/{iv['id']}", headers=cand["h"])).json()
    assert cv["status"] == "RESCHEDULED" and cv["can_confirm"] is True  # must confirm the new time
    assert len(await _notes(c, cand, "INTERVIEW_RESCHEDULED")) == 1
    assert len(await _notes(c, one["rec2"], "INTERVIEW_RESCHEDULED")) == 1
    # a second reschedule is a new version -> a new notification (not swallowed by the dedupe key)
    ns2 = (datetime.fromisoformat(ns) + timedelta(days=1)).isoformat()
    ne2 = (datetime.fromisoformat(ne) + timedelta(days=1)).isoformat()
    assert (
        await c.patch(f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"start_at": ns2, "end_at": ne2})
    ).status_code == 200
    assert len(await _notes(c, cand, "INTERVIEW_RESCHEDULED")) == 2
    assert (await c.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])).json()[
        "status"
    ] == "CONFIRMED"
    actions = [
        r[0]
        for r in await sql(
            "SELECT action FROM audit_events WHERE entity_id = :i ORDER BY created_at", i=uuid.UUID(iv["id"])
        )
    ]
    assert actions.count("interview.rescheduled") == 2 and "interview.scheduled" in actions


async def test_moving_only_the_start_keeps_the_duration_and_timezone_change_alone_is_not_a_reschedule(one):
    c, iv, rec = one["client"], one["iv"], one["rec"]
    ns = (datetime.fromisoformat(one["start"]) + timedelta(hours=5)).isoformat()
    r = await c.patch(f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"start_at": ns})
    assert r.status_code == 200 and r.json()["duration_minutes"] == 60 and r.json()["status"] == "RESCHEDULED"
    tz = await c.patch(
        f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"timezone": "America/New_York"}
    )
    assert tz.status_code == 200
    body = tz.json()
    assert (
        body["timezone"] == "America/New_York" and body["status"] == "RESCHEDULED"
    )  # status untouched by a display change
    assert datetime.fromisoformat(body["start_at"]) == datetime.fromisoformat(ns)  # same instant
    assert body["start_local"].endswith(("-04:00", "-05:00"))


async def test_details_only_edit_keeps_status_and_notes_only_edit_is_silent(one):
    c, iv, rec, cand = one["client"], one["iv"], one["rec"], one["cand"]
    await c.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])
    before = len(await _notes(c, cand))
    r = await c.patch(
        f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"notes": "only an internal remark"}
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "CONFIRMED"
        and r.json()["notes"] == "only an internal remark"
    )
    assert len(await _notes(c, cand)) == before  # nothing the candidate sees changed
    r = await c.patch(
        f"{API}/interviews/{iv['id']}",
        headers=rec["h"],
        json={"location": "Room 12", "interview_type": "PANEL"},
    )
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED" and r.json()["location"] == "Room 12"
    updated = await _notes(c, cand, "INTERVIEW_RESCHEDULED")
    assert len(updated) == 1 and updated[0]["title"] == "Interview updated"
    noop = await c.patch(f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"location": "Room 12"})
    assert noop.status_code == 200 and len(await _notes(c, cand, "INTERVIEW_RESCHEDULED")) == 1


async def test_patch_validation(one):
    c, iv, rec = one["client"], one["iv"], one["rec"]
    url = f"{API}/interviews/{iv['id']}"
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = await c.patch(url, headers=rec["h"], json={"start_at": past})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INTERVIEW_IN_PAST"
    r = await c.patch(url, headers=rec["h"], json={"end_at": one["start"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TIME_RANGE"
    r = await c.patch(
        url,
        headers=rec["h"],
        json={"end_at": (datetime.fromisoformat(one["start"]) + timedelta(hours=13)).isoformat()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INTERVIEW_TOO_LONG"
    r = await c.patch(url, headers=rec["h"], json={"meeting_url": None})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LOCATION_OR_LINK_REQUIRED"
    assert (await c.patch(url, headers=rec["h"], json={"timezone": "Nowhere/Land"})).status_code == 422
    assert (
        await c.patch(url, headers=rec["h"], json={"meeting_url": "http://insecure.example.com"})
    ).status_code == 422
    assert (await c.patch(url, headers=rec["h"], json={"interview_type": "NOPE"})).status_code == 422
    # nothing above changed the interview
    cur = (await c.get(url, headers=rec["h"])).json()
    assert cur["status"] == "SCHEDULED" and cur["meeting_url"] == "https://meet.example.com/room-1"


async def test_participants_can_be_replaced_with_conflict_checks(one):
    c, iv, rec, rec2, co = one["client"], one["iv"], one["rec"], one["rec2"], one["co"]
    url = f"{API}/interviews/{iv['id']}"
    r = await c.patch(
        url,
        headers=rec["h"],
        json={
            "participants": [
                {"user_id": uid(rec2), "role": "INTERVIEWER"},
                {"user_id": uid(rec), "role": "OBSERVER"},
            ]
        },
    )
    assert r.status_code == 200 and {(p["name"], p["role"]) for p in r.json()["participants"]} == {
        ("Sam Recruiter", "INTERVIEWER"),
        ("Riley Recruiter", "OBSERVER"),
    }
    # rec books another interview in the same window as an interviewer -> promoting them to interviewer here must fail
    other = await shortlisted(client=c, rec=rec)
    assert (
        await schedule(c, rec, other["app"]["id"], [rec], start=one["start"], end=one["end"])
    ).status_code == 201
    r = await c.patch(
        url, headers=rec["h"], json={"participants": [{"user_id": uid(rec), "role": "INTERVIEWER"}]}
    )
    assert (
        r.status_code == 409
        and r.json()["error"]["details"]["conflicts"][0]["participant"] == "Riley Recruiter"
    )
    # replacing the interviewer by the free HM (not assigned to the job) is invalid
    r = await c.patch(
        url, headers=rec["h"], json={"participants": [{"user_id": uid(co["hm"]), "role": "INTERVIEWER"}]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARTICIPANT"
    # removed participants lose their slot
    r = await c.patch(
        url,
        headers=rec["h"],
        json={
            "participants": [
                {"user_id": uid(rec), "role": "OBSERVER"},
                {"user_id": uid(rec2), "role": "OBSERVER"},
            ]
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INTERVIEWER_REQUIRED"


async def test_cancel_rules_notifications_and_privacy(one):
    c, iv, rec, cand = one["client"], one["iv"], one["rec"], one["cand"]
    url = f"{API}/interviews/{iv['id']}/cancel"
    assert (await c.post(url, headers=rec["h"], json={})).status_code == 422
    assert (await c.post(url, headers=rec["h"], json={"reason": "x"})).status_code == 422
    assert (
        await c.post(url, headers=cand["h"], json={"reason": "I can't make it"})
    ).status_code == 403  # candidates cannot cancel
    r = await c.post(url, headers=rec["h"], json={"reason": "Candidate withdrew from the process internally"})
    assert (
        r.status_code == 200
        and r.json()["status"] == "CANCELLED"
        and r.json()["cancelled_reason"].startswith("Candidate withdrew")
    )
    cv = await c.get(f"{API}/interviews/{iv['id']}", headers=cand["h"])
    assert (
        cv.json()["status"] == "CANCELLED"
        and cv.json()["can_confirm"] is False
        and "withdrew" not in cv.text
        and "cancelled_reason" not in cv.text
    )
    cn = await _notes(c, cand, "INTERVIEW_CANCELLED")
    assert len(cn) == 1 and "withdrew" not in cn[0]["message"]
    assert len(await _notes(c, one["rec2"], "INTERVIEW_CANCELLED")) == 1 and not await _notes(
        c, rec, "INTERVIEW_CANCELLED"
    )
    again = await c.post(url, headers=rec["h"], json={"reason": "second time"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert (await c.post(f"{API}/interviews/{iv['id']}/confirm", headers=cand["h"])).status_code == 409
    assert (
        await c.patch(f"{API}/interviews/{iv['id']}", headers=rec["h"], json={"location": "x y"})
    ).status_code == 409
    assert len(await _notes(c, cand, "INTERVIEW_CANCELLED")) == 1


async def test_complete_and_no_show_rules(one, monkeypatch):
    c, iv, rec, cand = one["client"], one["iv"], one["rec"], one["cand"]
    base = f"{API}/interviews/{iv['id']}"
    assert (await c.post(f"{base}/no-show", headers=rec["h"])).json()["error"][
        "code"
    ] == "INTERVIEW_NOT_STARTED"
    assert (await c.post(f"{base}/complete", headers=cand["h"])).status_code == 403
    monkeypatch.setattr(
        "app.services.interviews._now", at(datetime.fromisoformat(one["start"]) + timedelta(minutes=10))
    )
    ns = await c.post(f"{base}/no-show", headers=rec["h"])
    assert ns.status_code == 200 and ns.json()["status"] == "NO_SHOW"
    for action in ("complete", "no-show"):
        again = await c.post(f"{base}/{action}", headers=rec["h"])
        assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    # no feedback for someone who never showed up
    fb = await c.post(f"{base}/feedback", headers=rec["h"], json=FB)
    assert fb.status_code == 422 and fb.json()["error"]["code"] == "FEEDBACK_NOT_ALLOWED"
    # and a finished interview cannot be confirmed or cancelled afterwards
    assert (await c.post(f"{base}/confirm", headers=cand["h"])).status_code == 409
    assert (
        await c.post(f"{base}/cancel", headers=rec["h"], json={"reason": "too late now"})
    ).status_code == 409


async def test_confirm_after_the_interview_ended_is_rejected(one, monkeypatch):
    monkeypatch.setattr(
        "app.services.interviews._now", at(datetime.fromisoformat(one["end"]) + timedelta(minutes=1))
    )
    r = await one["client"].post(f"{API}/interviews/{one['iv']['id']}/confirm", headers=one["cand"]["h"])
    assert r.status_code == 409 and "already taken place" in r.json()["error"]["message"]


async def test_feedback_rules(one, monkeypatch):
    c, iv, rec, rec2 = one["client"], one["iv"], one["rec"], one["rec2"]
    base = f"{API}/interviews/{iv['id']}/feedback"
    start = datetime.fromisoformat(one["start"])
    # too early, even for the interviewer
    r = await c.post(base, headers=rec2["h"], json=FB)
    assert r.status_code == 422 and r.json()["error"]["code"] == "FEEDBACK_TOO_EARLY"
    monkeypatch.setattr(
        "app.services.interviews._now", at(start + timedelta(minutes=5))
    )  # started, not completed yet: allowed
    for bad in (
        {**FB, "rating": 0},
        {**FB, "rating": 6},
        {**FB, "recommendation": "MAYBE"},
        {k: v for k, v in FB.items() if k != "rating"},
    ):
        assert (await c.post(base, headers=rec2["h"], json=bad)).status_code == 422
    assert (await c.put(base, headers=rec2["h"], json=FB)).json()["error"]["code"] == "FEEDBACK_NOT_FOUND"
    ok = await c.post(base, headers=rec2["h"], json=FB)
    assert ok.status_code == 201
    dup = await c.post(base, headers=rec2["h"], json=FB)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "FEEDBACK_ALREADY_SUBMITTED"
    upd = await c.put(
        base, headers=rec2["h"], json={**FB, "rating": 5, "recommendation": "STRONG_HIRE", "notes": None}
    )
    assert upd.status_code == 200 and upd.json()["rating"] == 5 and upd.json()["notes"] is None
    assert upd.json()["id"] == ok.json()["id"] and upd.json()["submitted_at"] == ok.json()["submitted_at"]
    # each author has their own entry and can only change their own
    mine = (await c.post(base, headers=rec["h"], json={**FB, "rating": 2})).json()
    assert mine["is_mine"] is True
    listing = (await c.get(base, headers=rec["h"])).json()
    assert listing["count"] == 2 and listing["average_rating"] == 3.5
    assert {i["is_mine"] for i in listing["items"]} == {True, False}
    detail = (await c.get(f"{API}/interviews/{iv['id']}", headers=rec2["h"])).json()
    assert detail["my_feedback_submitted"] is True and detail["can_submit_feedback"] is False
    assert {p["name"]: p["has_submitted_feedback"] for p in detail["participants"]}["Sam Recruiter"] is True
    # cancelled interviews take no feedback
    assert (
        await c.post(
            f"{API}/interviews/{iv['id']}/cancel", headers=rec["h"], json={"reason": "Position put on hold"}
        )
    ).status_code == 200
    for call in (c.post, c.put):
        r = await call(base, headers=rec["h"], json=FB)
        assert r.status_code == 422 and r.json()["error"]["code"] == "FEEDBACK_NOT_ALLOWED"
    # ... but the existing entries stay readable for the team
    assert (await c.get(base, headers=rec["h"])).json()["count"] == 2


async def test_concurrent_double_submit_of_feedback_creates_one_row(one, monkeypatch):
    monkeypatch.setattr(
        "app.services.interviews._now", at(datetime.fromisoformat(one["start"]) + timedelta(minutes=5))
    )
    base = f"{API}/interviews/{one['iv']['id']}/feedback"
    rs = await asyncio.gather(
        *[one["client"].post(base, headers=one["rec2"]["h"], json=FB) for _ in range(3)]
    )
    assert sorted(r.status_code for r in rs) == [201, 409, 409]
    assert {r.json()["error"]["code"] for r in rs if r.status_code == 409} == {"FEEDBACK_ALREADY_SUBMITTED"}
    assert await sql(
        "SELECT count(*) FROM interview_feedback WHERE interview_id = :i", i=uuid.UUID(one["iv"]["id"])
    ) == [(1,)]


async def test_list_filters_sorting_and_pagination(client, monkeypatch):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    job_a = await create_job(client, rec, publish=True, title="Filter role A")
    job_b = await create_job(client, rec, publish=True, title="Filter role B")
    a1 = await shortlisted(client, rec, job=job_a)
    a2 = await shortlisted(client, rec, job=job_a)
    b1 = await shortlisted(client, rec, job=job_b)
    made = {}
    for key, sl, days in (("a1", a1, 2), ("a2", a2, 4), ("b1", b1, 6)):
        s, e = utc_slot(days=days, hour=10)
        made[key] = (await schedule(client, rec, sl["app"]["id"], [rec2], start=s, end=e)).json()
    cancelled = await client.post(
        f"{API}/interviews/{made['a2']['id']}/cancel", headers=rec["h"], json={"reason": "scheduling error"}
    )
    assert cancelled.status_code == 200

    async def ids(**params):
        r = await client.get(f"{API}/interviews", headers=rec["h"], params=params)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]], r.json()

    all_ids, body = await ids()
    assert (
        all_ids == [made["a1"]["id"], made["a2"]["id"], made["b1"]["id"]] and body["total"] == 3
    )  # sorted by start
    assert (await ids(sort="start_desc"))[0] == [made["b1"]["id"], made["a2"]["id"], made["a1"]["id"]]
    assert (await ids(status="CANCELLED"))[0] == [made["a2"]["id"]]
    assert (await ids(status=["SCHEDULED", "CANCELLED"]))[1]["total"] == 3
    assert (await ids(job_id=job_a["id"]))[1]["total"] == 2
    assert (await ids(application_id=b1["app"]["id"]))[0] == [made["b1"]["id"]]
    assert (await ids(candidate_id=a1["cand"]["candidate_id"]))[0] == [made["a1"]["id"]]
    d3 = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    d5 = (datetime.now(UTC) + timedelta(days=5)).date().isoformat()
    assert (await ids(from_date=d3, to_date=d5))[0] == [made["a2"]["id"]]
    assert (await ids(from_date=d5))[0] == [made["b1"]["id"]]
    assert (await ids(to_date=d3))[0] == [made["a1"]["id"]]
    assert (
        await client.get(f"{API}/interviews", headers=rec["h"], params={"from_date": d5, "to_date": d3})
    ).status_code == 422
    assert (
        await client.get(f"{API}/interviews", headers=rec["h"], params={"status": "BOGUS"})
    ).status_code == 422
    # pagination
    p1, b = await ids(page_size=2, page=1)
    p2, _ = await ids(page_size=2, page=2)
    assert len(p1) == 2 and p2 == [made["b1"]["id"]] and b["pages"] == 2
    # upcoming_only excludes cancelled and finished ones
    assert (await ids(upcoming_only="true"))[0] == [made["a1"]["id"], made["b1"]["id"]]
    monkeypatch.setattr(
        "app.services.interviews._now", at(datetime.fromisoformat(made["a1"]["end_at"]) + timedelta(hours=1))
    )
    assert (await ids(upcoming_only="true"))[0] == [made["b1"]["id"]]
