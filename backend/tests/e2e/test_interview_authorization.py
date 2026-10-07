"""Authorization matrix for interviews: tenant isolation, ownership, hiring-manager scope, candidate privacy."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.helpers import add_staff, create_admin, create_job, register_candidate, register_employer
from tests.helpers_ops import API, schedule, shortlisted, uid, utc_slot

pytestmark = pytest.mark.e2e

FB = {"rating": 4, "recommendation": "HIRE"}


@pytest.fixture
async def world(client):
    rec = await register_employer(client)
    rec2 = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")  # assigned to the job below and an interviewer
    hm_viewer = await add_staff(client, rec, "HIRING_MANAGER")  # assigned to the job, not a participant
    hm_other = await add_staff(client, rec, "HIRING_MANAGER")  # unrelated hiring manager
    rec_b = await register_employer(client)
    admin = await create_admin(client)
    job = await create_job(client, rec, publish=True, title="Scoped role", hiring_manager_id=hm["id"])
    other_job = await create_job(
        client, rec, publish=True, title="Other role", hiring_manager_id=hm_viewer["id"]
    )
    sl = await shortlisted(client, rec, job=job)
    sl2 = await shortlisted(client, rec, job=other_job)
    other_cand = await register_candidate(client)
    s, e = utc_slot(days=3, hour=11)
    iv = (
        await schedule(
            client, rec, sl["app"]["id"], [hm, rec2], start=s, end=e, notes="secret internal remark"
        )
    ).json()
    s2, e2 = utc_slot(days=3, hour=15)
    iv2 = (await schedule(client, rec, sl2["app"]["id"], [rec2], start=s2, end=e2)).json()
    return {
        "client": client,
        "rec": rec,
        "rec2": rec2,
        "hm": hm,
        "hm_viewer": hm_viewer,
        "hm_other": hm_other,
        "rec_b": rec_b,
        "admin": admin,
        "other_cand": other_cand,
        "iv": iv,
        "iv2": iv2,
        "job": job,
    }


async def test_anonymous_requests_are_rejected(world):
    c, iid = world["client"], world["iv"]["id"]
    for method, path, kw in (
        ("get", "/interviews", {}),
        ("get", f"/interviews/{iid}", {}),
        ("post", "/interviews", {"json": {}}),
        ("patch", f"/interviews/{iid}", {"json": {}}),
        ("post", f"/interviews/{iid}/cancel", {"json": {"reason": "abc"}}),
        ("post", f"/interviews/{iid}/confirm", {}),
        ("post", f"/interviews/{iid}/complete", {}),
        ("post", f"/interviews/{iid}/no-show", {}),
        ("get", f"/interviews/{iid}/feedback", {}),
        ("post", f"/interviews/{iid}/feedback", {"json": FB}),
        ("put", f"/interviews/{iid}/feedback", {"json": FB}),
    ):
        r = await getattr(c, method)(f"{API}{path}", **kw)
        assert r.status_code == 401, (method, path, r.status_code)


async def test_other_tenants_get_404_everywhere(world):
    c, iid, h = world["client"], world["iv"]["id"], world["rec_b"]["h"]
    for method, path, kw in (
        ("get", f"/interviews/{iid}", {}),
        ("patch", f"/interviews/{iid}", {"json": {"location": "elsewhere"}}),
        ("post", f"/interviews/{iid}/cancel", {"json": {"reason": "sabotage"}}),
        ("post", f"/interviews/{iid}/complete", {}),
        ("post", f"/interviews/{iid}/no-show", {}),
        ("get", f"/interviews/{iid}/feedback", {}),
        ("post", f"/interviews/{iid}/feedback", {"json": FB}),
        ("put", f"/interviews/{iid}/feedback", {"json": FB}),
    ):
        r = await getattr(c, method)(f"{API}{path}", headers=h, **kw)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
        assert r.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"
    assert (
        await c.post(f"{API}/interviews/{iid}/confirm", headers=h)
    ).status_code == 403  # staff never confirm
    lst = (await c.get(f"{API}/interviews", headers=h)).json()
    assert lst["total"] == 0
    # nor can they schedule against someone else's application
    r = await schedule(c, world["rec_b"], world["iv"]["application_id"], [world["rec_b"]])
    assert r.status_code == 404
    # the interview is untouched
    cur = (await c.get(f"{API}/interviews/{iid}", headers=world["rec"]["h"])).json()
    assert cur["status"] == "SCHEDULED" and cur["location"] is None


async def test_candidates_see_and_confirm_only_their_own_interviews(world):
    c, iid = world["client"], world["iv"]["id"]
    other = world["other_cand"]["h"]
    assert (await c.get(f"{API}/interviews/{iid}", headers=other)).status_code == 404
    assert (await c.post(f"{API}/interviews/{iid}/confirm", headers=other)).status_code == 404
    assert (await c.get(f"{API}/interviews", headers=other)).json()["total"] == 0
    # nothing can be read through the feedback endpoints either: always 403 for candidates, including the interviewee
    for h in (other, world["cand"]["h"]):
        assert (await c.get(f"{API}/interviews/{iid}/feedback", headers=h)).status_code == 403
        assert (await c.post(f"{API}/interviews/{iid}/feedback", headers=h, json=FB)).status_code == 403
        assert (await c.put(f"{API}/interviews/{iid}/feedback", headers=h, json=FB)).status_code == 403
    mine = (await c.get(f"{API}/interviews", headers=world["cand"]["h"])).json()
    assert (
        mine["total"] == 1 and mine["items"][0]["id"] == iid and mine["items"][0]["audience"] == "candidate"
    )
    assert (
        "secret internal remark"
        not in (await c.get(f"{API}/interviews/{iid}", headers=world["cand"]["h"])).text
    )


async def test_candidates_cannot_use_staff_actions(world):
    c, iid, h = world["client"], world["iv"]["id"], world["cand"]["h"]
    r = await c.post(
        f"{API}/interviews",
        headers=h,
        json={
            "application_id": world["iv"]["application_id"],
            "interview_type": "PANEL",
            "start_at": world["start"],
            "end_at": world["start"],
            "meeting_url": "https://x.example.com/z",
            "participants": [],
        },
    )
    assert r.status_code == 403
    assert (
        await c.patch(f"{API}/interviews/{iid}", headers=h, json={"location": "my house"})
    ).status_code == 403
    assert (
        await c.post(f"{API}/interviews/{iid}/cancel", headers=h, json={"reason": "no thanks"})
    ).status_code == 403
    assert (await c.post(f"{API}/interviews/{iid}/complete", headers=h)).status_code == 403
    assert (await c.post(f"{API}/interviews/{iid}/no-show", headers=h)).status_code == 403


async def test_hiring_manager_scope(world, monkeypatch):
    c, iid, iid2 = world["client"], world["iv"]["id"], world["iv2"]["id"]
    hm, viewer, unrelated = world["hm"]["h"], world["hm_viewer"]["h"], world["hm_other"]["h"]
    # the participating HM and the HM assigned to the other job each see exactly their interview
    assert [i["id"] for i in (await c.get(f"{API}/interviews", headers=hm)).json()["items"]] == [iid]
    assert [i["id"] for i in (await c.get(f"{API}/interviews", headers=viewer)).json()["items"]] == [iid2]
    assert (await c.get(f"{API}/interviews", headers=unrelated)).json()["total"] == 0
    assert (await c.get(f"{API}/interviews/{iid}", headers=hm)).status_code == 200
    assert (await c.get(f"{API}/interviews/{iid}", headers=viewer)).status_code == 404
    assert (await c.get(f"{API}/interviews/{iid}", headers=unrelated)).status_code == 404
    assert (await c.get(f"{API}/interviews/{iid}/feedback", headers=unrelated)).status_code == 404
    assert (await c.post(f"{API}/interviews/{iid}/feedback", headers=unrelated, json=FB)).status_code == 404
    # hiring managers cannot schedule, edit or cancel (no SCHEDULE_INTERVIEWS permission) ...
    assert (await schedule(c, world["hm"], world["iv"]["application_id"], [world["hm"]])).status_code == 403
    assert (
        await c.patch(f"{API}/interviews/{iid}", headers=hm, json={"location": "mine"})
    ).status_code == 403
    assert (
        await c.post(f"{API}/interviews/{iid}/cancel", headers=hm, json={"reason": "I disagree"})
    ).status_code == 403
    # ... but the participating HM can finish the interview and give feedback; a non-participant cannot finish it
    monkeypatch.setattr(
        "app.services.interviews._now", lambda: datetime.fromisoformat(world["start"]) + timedelta(minutes=30)
    )
    assert (await c.post(f"{API}/interviews/{iid2}/complete", headers=viewer)).status_code == 403
    done = await c.post(f"{API}/interviews/{iid}/complete", headers=hm)
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    # HMs see the application stage but get no stage buttons (only recruiters move applications)
    assert done.json()["application"]["allowed_next_statuses"] == []
    fb = await c.post(f"{API}/interviews/{iid}/feedback", headers=hm, json=FB)
    assert fb.status_code == 201
    # the HM assigned to the job (not a participant) may read the interview's feedback too
    assert (await c.get(f"{API}/interviews/{iid2}/feedback", headers=viewer)).status_code == 200


async def test_recruiters_of_the_company_and_admins(world, monkeypatch):
    c, iid = world["client"], world["iv"]["id"]
    # another recruiter of the same company (here: also an interviewer) and a recruiter who is not a participant both manage it
    assert (await c.get(f"{API}/interviews/{iid}", headers=world["rec2"]["h"])).status_code == 200
    r = await c.patch(
        f"{API}/interviews/{iid}", headers=world["rec2"]["h"], json={"notes": "updated by colleague"}
    )
    assert r.status_code == 200 and r.json()["notes"] == "updated by colleague"
    # admin: read access to everything, no authoring of feedback
    adm = world["admin"]["h"]
    assert (await c.get(f"{API}/interviews", headers=adm)).json()["total"] == 2
    assert (await c.get(f"{API}/interviews/{iid}", headers=adm)).json()["audience"] == "staff"
    monkeypatch.setattr(
        "app.services.interviews._now", lambda: datetime.fromisoformat(world["start"]) + timedelta(minutes=30)
    )
    assert (await c.post(f"{API}/interviews/{iid}/feedback", headers=adm, json=FB)).status_code == 403
    assert (await c.get(f"{API}/interviews/{iid}/feedback", headers=adm)).status_code == 200
    assert uid(world["rec"]) != uid(world["rec2"])
