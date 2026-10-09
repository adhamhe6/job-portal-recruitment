"""Scheduling validation: times, timezone, location/link, participants and the application stage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import create_job, register_candidate, register_employer
from tests.helpers_ops import (
    API,
    company_with_staff,
    schedule,
    set_status,
    shortlisted,
    uid,
    utc_slot,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def ctx(client):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"])
    return {"client": client, "co": co, "sl": sl, "rec": co["rec"], "app_id": sl["app"]["id"]}


async def _expect(ctx, status, code=None, **overrides):
    r = await schedule(ctx["client"], ctx["rec"], ctx["app_id"], [ctx["co"]["rec2"]], **overrides)
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    return r


async def test_end_must_be_after_start(ctx):
    s, _ = utc_slot()
    await _expect(ctx, 422, "INVALID_TIME_RANGE", start=s, end=s)
    earlier = (datetime.fromisoformat(s) - timedelta(hours=1)).isoformat()
    await _expect(ctx, 422, "INVALID_TIME_RANGE", start=s, end=earlier)


async def test_start_in_the_past_is_rejected_with_small_tolerance(ctx):
    past = datetime.now(UTC) - timedelta(days=1)
    await _expect(
        ctx, 422, "INTERVIEW_IN_PAST", start=past.isoformat(), end=(past + timedelta(hours=1)).isoformat()
    )
    just_now = datetime.now(UTC) - timedelta(minutes=2)  # within the 5 minute tolerance
    await _expect(ctx, 201, start=just_now.isoformat(), end=(just_now + timedelta(hours=1)).isoformat())


async def test_duration_limit_is_twelve_hours(ctx):
    s, _ = utc_slot(days=5)
    start = datetime.fromisoformat(s)
    await _expect(
        ctx, 422, "INTERVIEW_TOO_LONG", start=s, end=(start + timedelta(hours=12, minutes=1)).isoformat()
    )
    await _expect(ctx, 201, start=s, end=(start + timedelta(hours=12)).isoformat())


@pytest.mark.parametrize("tz", ["Mars/Olympus", "", "../etc/passwd", "Europe\\Berlin", "utc+2"])
async def test_invalid_timezone(ctx, tz):
    r = await _expect(ctx, 422, "VALIDATION_ERROR", timezone=tz)
    assert any(d["field"] == "timezone" for d in r.json()["error"]["details"])


async def test_location_or_link_required_and_link_must_be_https(ctx):
    await _expect(ctx, 422, "LOCATION_OR_LINK_REQUIRED", meeting_url=None, location=None)
    await _expect(ctx, 422, "LOCATION_OR_LINK_REQUIRED", meeting_url="  ", location="   ")
    for bad in (
        "http://meet.example.com/x",
        "javascript:alert(1)",
        "ftp://files.example.com/x",
        "https://",
        "meet.example.com/x",
        "https://a b.example.com",
    ):
        r = await _expect(ctx, 422, "VALIDATION_ERROR", meeting_url=bad, location="HQ")
        assert any(d["field"] == "meeting_url" for d in r.json()["error"]["details"]), bad
    await _expect(ctx, 201, meeting_url=None, location="Berlin HQ, room 4")  # a location alone is enough


async def test_unknown_interview_type_and_missing_participants(ctx):
    await _expect(ctx, 422, "VALIDATION_ERROR", interview_type="COFFEE_CHAT")
    r = await ctx["client"].post(
        f"{API}/interviews",
        headers=ctx["rec"]["h"],
        json={
            "application_id": ctx["app_id"],
            "interview_type": "PANEL",
            "start_at": utc_slot()[0],
            "end_at": utc_slot()[1],
            "meeting_url": "https://x.example.com/y",
            "participants": [],
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_participants_must_be_active_same_company_staff(ctx):
    client, co = ctx["client"], ctx["co"]
    other_rec = await register_employer(client)
    cand = await register_candidate(client)
    for bad in (other_rec, cand, {"id": str(uuid.uuid4())}):
        r = await schedule(client, ctx["rec"], ctx["app_id"], [bad])
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARTICIPANT", r.text
    # a hiring manager who is not assigned to the job
    r = await schedule(client, ctx["rec"], ctx["app_id"], [co["hm"]])
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARTICIPANT"
    # a suspended colleague
    sus = await client.patch(
        f"{API}/companies/{ctx['rec']['company_id']}/members/{uid(co['rec2'])}",
        headers=ctx["rec"]["h"],
        json={"status": "SUSPENDED"},
    )
    assert sus.status_code == 200, sus.text
    r = await schedule(client, ctx["rec"], ctx["app_id"], [co["rec2"]])
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARTICIPANT"


async def test_participant_rules_interviewer_required_and_unique(ctx):
    client, co = ctx["client"], ctx["co"]
    r = await schedule(
        client,
        ctx["rec"],
        ctx["app_id"],
        [co["rec2"]],
        participants=[{"user_id": uid(co["rec2"]), "role": "OBSERVER"}],
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INTERVIEWER_REQUIRED"
    dup = [
        {"user_id": uid(co["rec2"]), "role": "INTERVIEWER"},
        {"user_id": uid(co["rec2"]), "role": "OBSERVER"},
    ]
    r = await schedule(client, ctx["rec"], ctx["app_id"], [co["rec2"]], participants=dup)
    assert r.status_code == 422 and r.json()["error"]["code"] == "DUPLICATE_PARTICIPANT"


async def test_assigned_hiring_manager_and_recruiters_can_take_part(client):
    co = await company_with_staff(client)
    job = await create_job(
        client, co["rec"], publish=True, title="HM-owned role", hiring_manager_id=co["hm"]["id"]
    )
    sl = await shortlisted(client, co["rec"], job=job)
    r = await schedule(
        client,
        co["rec"],
        sl["app"]["id"],
        [co["hm"], co["rec2"]],
        participants=[
            {"user_id": uid(co["hm"]), "role": "INTERVIEWER"},
            {"user_id": uid(co["rec2"]), "role": "OBSERVER"},
            {"user_id": uid(co["rec"]), "role": "INTERVIEWER"},
        ],
    )
    assert r.status_code == 201, r.text
    assert {p["name"] for p in r.json()["participants"]} >= {"Sam Hiring_Manager"}


@pytest.mark.parametrize("stage", ["APPLIED", "SCREENING", "REJECTED", "OFFER", "HIRED"])
async def test_only_shortlisted_or_interview_applications_are_interviewable(client, stage):
    co = await company_with_staff(client)
    sl = await shortlisted(client, co["rec"], advance=False)
    path = {
        "APPLIED": [],
        "SCREENING": ["SCREENING"],
        "REJECTED": ["REJECTED"],
        "OFFER": ["SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER"],
        "HIRED": ["SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED"],
    }[stage]
    if path:
        await set_status(client, co["rec"], sl["app"]["id"], *path)
    r = await schedule(client, co["rec"], sl["app"]["id"], [co["rec2"]])
    assert r.status_code == 422 and r.json()["error"]["code"] == "APPLICATION_NOT_INTERVIEWABLE", r.text
    assert r.json()["error"]["details"]["status"] == stage


async def test_unknown_and_foreign_applications(client):
    co = await company_with_staff(client)
    r = await schedule(client, co["rec"], str(uuid.uuid4()), [co["rec2"]])
    assert r.status_code == 404 and r.json()["error"]["code"] == "APPLICATION_NOT_FOUND"
    other = await register_employer(client)
    job = await create_job(client, other, publish=True, title="Other co job")
    foreign = await shortlisted(client, other, job=job)
    r = await schedule(client, co["rec"], foreign["app"]["id"], [co["rec2"]])
    assert r.status_code == 404  # another tenant's application is not found, not forbidden
