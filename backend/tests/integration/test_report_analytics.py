"""Analytics reports checked against the hand-computed dataset (tests.helpers_ops.build_pipeline)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.cache.redis_cache import get_cache
from tests.helpers import create_admin, create_job, register_candidate, register_employer
from tests.helpers_ops import (
    API,
    apply_to,
    build_pipeline,
    bust_cache,
    company_with_staff,
    put_match,
    schedule,
    set_status,
    shortlisted,
    sql,
    utc_slot,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(client):
    w = await build_pipeline(client)
    w["client"] = client
    return w


async def get(client, path, account, **params):
    return await client.get(f"{API}/reports/{path}", headers=account["h"], params=params)


async def set_history(app_id: str, to_status: str, *, days_after_apply: float) -> None:
    await sql(
        "UPDATE application_status_history h SET created_at = a.applied_at + make_interval(secs => :s) "
        "FROM applications a WHERE a.id = h.application_id AND h.application_id = :id AND h.to_status = :st",
        s=days_after_apply * 86400, id=uuid.UUID(app_id), st=to_status,
    )  # fmt: skip


# --------------------------------------------------------------------------------------------------------------------
async def test_applications_by_job_and_status(world):
    c, rec = world["client"], world["rec"]
    r = await get(c, "applications-by-job", rec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["page"] == 1 and body["pages"] == 1
    j2, j1 = body["items"]
    assert (j2["title"], j2["applications"], j2["job_status"]) == ("Dash Job Two", 4, "PUBLISHED")
    assert j2["by_status"] == {"APPLIED": 1, "SCREENING": 0, "SHORTLISTED": 1, "INTERVIEW": 1, "OFFER": 0, "HIRED": 0, "REJECTED": 0, "WITHDRAWN": 1}
    assert (j1["title"], j1["applications"]) == ("Dash Job One", 3)
    assert j1["by_status"]["HIRED"] == 1 and j1["by_status"]["REJECTED"] == 1 and j1["by_status"]["SCREENING"] == 1
    # sorting and pagination
    asc = (await get(c, "applications-by-job", rec, sort="title", order="asc")).json()["items"]
    assert [i["title"] for i in asc] == ["Dash Job One", "Dash Job Two"]
    by_hired = (await get(c, "applications-by-job", rec, sort="hired")).json()["items"]
    assert by_hired[0]["title"] == "Dash Job One"
    p2 = (await get(c, "applications-by-job", rec, page_size=1, page=2)).json()
    assert p2["pages"] == 2 and [i["title"] for i in p2["items"]] == ["Dash Job One"]
    # nothing in the future
    none = (await get(c, "applications-by-job", rec, from_date=(datetime.now(UTC) + timedelta(days=1)).date().isoformat())).json()
    assert none["total"] == 0 and none["items"] == []

    st = (await get(c, "applications-by-status", rec)).json()
    assert st["total"] == 7 and {i["status"]: i["count"] for i in st["items"]} == {
        "APPLIED": 1, "SCREENING": 1, "SHORTLISTED": 1, "INTERVIEW": 1, "OFFER": 0, "HIRED": 1, "REJECTED": 1, "WITHDRAWN": 1,
    }  # fmt: skip
    assert [i["status"] for i in st["items"]][:2] == ["APPLIED", "SCREENING"]
    one = (await get(c, "applications-by-status", rec, job_id=world["j1"]["id"])).json()
    assert one["total"] == 3 and one["job_id"] == world["j1"]["id"] and {i["status"]: i["count"] for i in one["items"]}["HIRED"] == 1


async def test_funnel_overall_and_per_job(world):
    c, rec = world["client"], world["rec"]
    f = (await get(c, "funnel", rec)).json()
    assert f["applications"] == 7
    assert [(s["stage"], s["count"], s["is_branch"]) for s in f["stages"]] == [
        ("APPLIED", 7, False), ("SCREENING", 5, False), ("SHORTLISTED", 4, False), ("INTERVIEW", 3, False), ("OFFER", 1, False),
        ("HIRED", 1, False), ("REJECTED", 1, True), ("WITHDRAWN", 1, True),
    ]  # fmt: skip
    j1 = (await get(c, "funnel", rec, job_id=world["j1"]["id"])).json()
    assert [s["count"] for s in j1["stages"]] == [3, 3, 2, 2, 1, 1, 1, 0] and j1["applications"] == 3
    j2 = (await get(c, "funnel", rec, job_id=world["j2"]["id"])).json()
    assert [s["count"] for s in j2["stages"]] == [4, 2, 2, 1, 0, 0, 0, 1]
    assert j2["stages"][4]["pct_of_previous"] == 0.0 and j2["stages"][5]["pct_of_previous"] is None  # nobody reached OFFER -> HIRED undefined
    # a job of another company is simply empty for me
    other = await register_employer(c)
    assert (await get(c, "funnel", other, job_id=world["j1"]["id"])).json()["applications"] == 0


async def test_job_performance(world):
    c, rec = world["client"], world["rec"]
    a = world["apps"]
    for key, days in (("c1", 10), ("c2", 6), ("c3", 4)):
        await sql("UPDATE applications SET applied_at = now() - make_interval(days => :d) WHERE id = :id", d=days, id=uuid.UUID(a[key]))
    await set_history(a["c1"], "SCREENING", days_after_apply=1)  # first change after 1 day
    await set_history(a["c1"], "HIRED", days_after_apply=8)
    await set_history(a["c2"], "SCREENING", days_after_apply=3)
    await set_history(a["c3"], "SCREENING", days_after_apply=2)
    await bust_cache()
    r = await get(c, "job-performance", rec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and "views are not tracked" in body["note"]
    by_title = {i["title"]: i for i in body["items"]}
    j1, j2 = by_title["Dash Job One"], by_title["Dash Job Two"]
    assert (j1["applications"], j1["reached_shortlist"], j1["hires"]) == (3, 2, 1)
    assert j1["shortlist_rate"] == 0.6667 and j1["hire_rate"] == 0.3333
    assert j1["avg_days_to_first_status_change"] == 2.0 and j1["avg_days_to_hire"] == 8.0  # (1+3+2)/3 and (8)
    assert j1["avg_match_score"] == 0.7767 and j1["applicants_scored"] == 3  # mean(.91, .80, .62)
    assert (j2["applications"], j2["reached_shortlist"], j2["hires"]) == (4, 2, 0)
    assert j2["shortlist_rate"] == 0.5 and j2["hire_rate"] == 0.0 and j2["avg_days_to_hire"] is None
    assert j2["avg_days_to_first_status_change"] < 0.01  # everything happened within seconds
    assert j2["avg_match_score"] == 0.42 and j2["applicants_scored"] == 3  # mean(.40, .20, .66); c7 has no score
    # sorting (NULLs always last)
    def titles(**kw):
        return [i["title"] for i in kw["items"]]

    assert titles(items=(await get(c, "job-performance", rec, sort="avg_match_score")).json()["items"]) == ["Dash Job One", "Dash Job Two"]
    assert titles(items=(await get(c, "job-performance", rec, sort="avg_match_score", order="asc")).json()["items"]) == ["Dash Job Two", "Dash Job One"]
    assert titles(items=(await get(c, "job-performance", rec, sort="hire_rate")).json()["items"])[0] == "Dash Job One"
    assert titles(items=(await get(c, "job-performance", rec, sort="avg_days_to_hire", order="asc")).json()["items"]) == ["Dash Job One", "Dash Job Two"]
    assert titles(items=(await get(c, "job-performance", rec, sort="avg_days_to_hire", order="desc")).json()["items"]) == ["Dash Job One", "Dash Job Two"]
    assert titles(items=(await get(c, "job-performance", rec, sort="title", order="desc")).json()["items"]) == ["Dash Job Two", "Dash Job One"]
    assert (await get(c, "job-performance", rec, sort="views")).status_code == 422


async def test_recruiter_activity(world, monkeypatch):
    c, rec, rec2 = world["client"], world["rec"], world["rec2"]
    for text in ("first remark", "second remark"):
        assert (await c.post(f"{API}/applications/{world['apps']['c3']}/notes", headers=rec2["h"], json={"body": text})).status_code == 201
    start = datetime.fromisoformat(world["interview"]["start_at"])
    monkeypatch.setattr("app.services.interviews._now", lambda: start + timedelta(minutes=5))
    fb = await c.post(f"{API}/interviews/{world['interview']['id']}/feedback", headers=rec2["h"], json={"rating": 4, "recommendation": "HIRE"})
    assert fb.status_code == 201, fb.text
    r = await get(c, "recruiter-activity", rec)
    assert r.status_code == 200, r.text
    rows = {i["name"]: i for i in r.json()["items"]}
    assert r.json()["total"] == 3  # only my company's staff
    riley, sam_r = rows["Riley Recruiter"], rows["Sam Recruiter"]
    assert (riley["status_changes"], riley["interviews_scheduled"], riley["notes_added"], riley["feedback_submitted"]) == (15, 1, 0, 0)
    assert riley["total_actions"] == 16 and riley["role"] == "RECRUITER"
    assert (sam_r["status_changes"], sam_r["interviews_scheduled"], sam_r["notes_added"], sam_r["feedback_submitted"], sam_r["total_actions"]) == (0, 0, 2, 1, 3)
    hm_row = rows["Sam Hiring_Manager"]
    assert hm_row["total_actions"] == 0 and hm_row["role"] == "HIRING_MANAGER"
    assert [i["name"] for i in r.json()["items"]] == ["Riley Recruiter", "Sam Recruiter", "Sam Hiring_Manager"]  # by total, desc
    asc = (await get(c, "recruiter-activity", rec, sort="notes", order="desc")).json()["items"]
    assert asc[0]["name"] == "Sam Recruiter"
    # the candidate's own withdrawal is not staff activity; a future window finds nothing
    future = (await get(c, "recruiter-activity", rec, from_date=(datetime.now(UTC) + timedelta(days=2)).date().isoformat())).json()
    assert sum(i["total_actions"] for i in future["items"]) == 0
    # hiring managers may not see colleagues' activity; admins see all companies
    assert (await get(c, "recruiter-activity", world["hm"])).status_code == 403
    admin = await create_admin(c)
    other = await register_employer(c)
    allrows = (await get(c, "recruiter-activity", admin)).json()
    assert allrows["total"] == 4 and {i["company_id"] for i in allrows["items"]} == {world["rec"]["company_id"], other["company_id"]}
    assert (await get(c, "recruiter-activity", admin, company_id=world["rec"]["company_id"])).json()["total"] == 3
    assert (await get(c, "recruiter-activity", other)).json()["total"] == 1


async def test_source_statistics(world):
    c, rec = world["client"], world["rec"]
    body = (await get(c, "source-statistics", rec)).json()
    rows = {i["source"]: i for i in body["items"]}
    assert [i["source"] for i in body["items"]] == ["DIRECT", "REFERRAL", "SEARCH"] and body["total"] == 3
    d, ref, srch = rows["DIRECT"], rows["REFERRAL"], rows["SEARCH"]
    assert (d["applications"], d["reached_shortlist"], d["hires"]) == (5, 3, 1)
    assert d["share"] == 0.7143 and d["shortlist_rate"] == 0.6 and d["hire_rate"] == 0.2
    assert (ref["applications"], ref["reached_shortlist"], ref["hires"], ref["shortlist_rate"], ref["hire_rate"]) == (1, 1, 0, 1.0, 0.0)
    assert (srch["applications"], srch["reached_shortlist"], srch["shortlist_rate"]) == (1, 0, 0.0)
    assert sum(i["share"] for i in body["items"]) == pytest.approx(1.0, abs=0.001)
    asc = (await get(c, "source-statistics", rec, sort="source", order="asc")).json()["items"]
    assert [i["source"] for i in asc] == ["DIRECT", "REFERRAL", "SEARCH"]
    assert (await get(c, "source-statistics", rec, page_size=2, page=2)).json()["items"][0]["source"] == "SEARCH"


async def test_matching_performance(world):
    c, rec = world["client"], world["rec"]
    r = await get(c, "matching-performance", rec)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["scored_pairs"] == 10
    assert {b["band"]: b["count"] for b in m["all_scored_distribution"]} == {"STRONG": 5, "GOOD": 3, "PARTIAL": 1, "WEAK": 1}
    assert [b["band"] for b in m["all_scored_distribution"]] == ["STRONG", "GOOD", "PARTIAL", "WEAK"]
    assert {b["band"]: b["count"] for b in m["applicant_distribution"]} == {"STRONG": 2, "GOOD": 2, "PARTIAL": 1, "WEAK": 1}
    assert sum(b["percent"] for b in m["applicant_distribution"]) == pytest.approx(100, abs=0.5)
    out = {o["outcome"]: o for o in m["avg_score_by_outcome"]}
    assert (out["HIRED"]["applications"], out["HIRED"]["avg_score"]) == (1, 0.91)
    assert (out["REJECTED"]["applications"], out["REJECTED"]["avg_score"]) == (1, 0.8)
    assert (out["WITHDRAWN"]["applications"], out["WITHDRAWN"]["avg_score"]) == (1, 0.66)
    assert (out["IN_PROGRESS"]["applications"], out["IN_PROGRESS"]["avg_score"]) == (3, 0.4067)  # mean(.62, .40, .20)
    assert m["hired_minus_rejected"] == 0.11
    assert m["top10"] == {"applicants": 7, "applicants_with_score": 6, "applicants_in_top10": 6, "pct_in_top10": 100.0}
    notes = " ".join(m["notes"])
    assert "not a prediction of hiring success" in notes and "samples this small say little" in notes and "1 of 7 applicants have no stored match score" in notes
    # an empty company says so instead of inventing numbers
    other = await register_employer(c)
    empty = (await get(c, "matching-performance", other)).json()
    assert empty["scored_pairs"] == 0 and empty["hired_minus_rejected"] is None and empty["top10"]["pct_in_top10"] is None
    assert any("No match scores" in n for n in empty["notes"])
    assert all(o["avg_score"] is None for o in empty["avg_score_by_outcome"])


async def test_matching_top10_share_uses_rank_among_all_scored_candidates(client):
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True, title="Top ten probe")
    company_id, job_id = uuid.UUID(rec["company_id"]), uuid.UUID(job["id"])

    async def imported(n: int) -> uuid.UUID:
        row = await sql(
            "INSERT INTO candidate_profiles (id, source, sourced_by_company_id, first_name, last_name, display_name) "
            "VALUES (gen_random_uuid(), 'IMPORTED', :c, 'Imp', :n, :d) RETURNING id", c=company_id, n=str(n), d=f"Imp {n}",
        )  # fmt: skip
        return row[0][0]

    ids = [await imported(i) for i in range(1, 14)]  # 12 scored candidates + 1 unscored
    for i, cid in enumerate(ids[:12]):
        await put_match(str(job_id), str(cid), round(0.99 - i * 0.01, 2))
    for cid in (ids[2], ids[10], ids[12]):  # ranks 3 and 11 are scored; the last one has no score
        await sql("INSERT INTO applications (id, job_id, candidate_id) VALUES (gen_random_uuid(), :j, :c)", j=job_id, c=cid)
    await bust_cache()
    m = (await get(client, "matching-performance", rec)).json()
    assert m["scored_pairs"] == 12
    assert m["top10"] == {"applicants": 3, "applicants_with_score": 2, "applicants_in_top10": 1, "pct_in_top10": 50.0}
    assert any("1 of 3 applicants have no stored match score" in n for n in m["notes"])


async def test_band_edges_match_the_matching_module(client):
    from sqlalchemy import literal, select

    from app.db.database import get_sessionmaker
    from app.matching.scoring import overall_band
    from app.services.reports import band_case

    async with get_sessionmaker()() as s:
        for x in (0.0, 0.2, 0.34999, 0.35, 0.5, 0.54999, 0.55, 0.7, 0.74999, 0.75, 0.9, 1.0):
            assert await s.scalar(select(band_case(literal(x)))) == overall_band(x), x


async def test_top_skills(client):
    co = await company_with_staff(client)
    rec = co["rec"]
    job = await create_job(client, rec, publish=True, title="Skill demand A")
    job_b = await create_job(client, rec, publish=True, title="Skill demand B", skills=[{"name": "Python", "requirement": "REQUIRED"}, {"name": "Terraform", "requirement": "PREFERRED"}])
    await create_job(client, rec, title="Draft with Haskell", skills=[{"name": "Haskell", "requirement": "REQUIRED"}])  # drafts do not count
    skills_of = {"c1": ["Python", "Docker"], "c2": ["Python"], "c3": ["Python", "Redis"]}
    cands = {}
    for key, names in skills_of.items():
        cand = await register_candidate(client, first=key.upper(), last="Skilled")
        for n in names:
            assert (await client.post(f"{API}/candidates/me/skills", headers=cand["h"], json={"name": n})).status_code == 201
        cands[key] = cand
    for key, cand in cands.items():
        await apply_to(client, cand, (job if key != "c3" else job_b)["id"])
    outsider = await register_candidate(client, first="Out", last="Sider")  # has skills but never applied
    await client.post(f"{API}/candidates/me/skills", headers=outsider["h"], json={"name": "Python"})
    withdrawn = await register_candidate(client, first="With", last="Drawn")
    await client.post(f"{API}/candidates/me/skills", headers=withdrawn["h"], json={"name": "Kubernetes"})
    wd = await apply_to(client, withdrawn, job["id"])
    assert (await client.post(f"{API}/applications/{wd['id']}/withdraw", headers=withdrawn["h"])).status_code == 200
    await bust_cache()

    r = await get(client, "top-skills", rec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "company" and body["jobs_considered"] == 2 and body["applicants_considered"] == 3
    req = {d["skill"]: d for d in body["requested"]}
    assert req["Python"]["jobs"] == 2 and req["Python"]["required_in_jobs"] == 2 and req["Python"]["preferred_in_jobs"] == 0
    assert req["Docker"]["jobs"] == 1 and req["Redis"]["preferred_in_jobs"] == 1 and req["Terraform"]["jobs"] == 1
    assert "Haskell" not in req
    assert body["requested"][0]["skill"] == "Python"  # most requested first
    avail = {d["skill"]: d["candidates"] for d in body["available"]}
    assert avail == {"Python": 3, "Docker": 1, "Redis": 1}  # not the outsider, not the withdrawn applicant's Kubernetes
    assert body["available"][0]["skill"] == "Python"
    limited = (await get(client, "top-skills", rec, limit=1)).json()
    assert len(limited["requested"]) == 1 and len(limited["available"]) == 1
    assert (await get(client, "top-skills", rec, limit=0)).status_code == 422
    # admins may look at the whole platform or one company; a hiring manager sees only assigned jobs (none here)
    admin = await create_admin(client)
    plat = (await get(client, "top-skills", admin)).json()
    assert plat["scope"] == "platform" and plat["jobs_considered"] == 2
    hm = (await get(client, "top-skills", co["hm"])).json()
    assert hm["scope"] == "assigned_jobs" and hm["jobs_considered"] == 0 and hm["requested"] == []


async def test_pipeline_summary(world):
    c, rec = world["client"], world["rec"]
    await sql("UPDATE applications SET status_changed_at = now() - interval '20 days' WHERE id = :id", id=uuid.UUID(world["apps"]["c5"]))
    await sql("UPDATE applications SET status_changed_at = now() - interval '3 days' WHERE id = :id", id=uuid.UUID(world["apps"]["c3"]))
    await bust_cache()
    p = (await get(c, "pipeline-summary", rec)).json()
    assert (p["total"], p["live"], p["closed"], p["stale"], p["stale_after_days"]) == (7, 4, 3, 1, 14)
    st = {s["stage"]: s for s in p["stages"]}
    assert [s["stage"] for s in p["stages"]] == ["APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN"]
    assert (st["APPLIED"]["count"], st["APPLIED"]["stale"]) == (1, 1) and 19.9 <= st["APPLIED"]["avg_days_in_stage"] <= 20.1
    assert st["APPLIED"]["max_days_in_stage"] == st["APPLIED"]["avg_days_in_stage"]
    assert st["SCREENING"]["count"] == 1 and st["SCREENING"]["stale"] == 0 and 2.9 <= st["SCREENING"]["avg_days_in_stage"] <= 3.1
    assert st["HIRED"]["count"] == 1 and st["HIRED"]["avg_days_in_stage"] is None and st["REJECTED"]["stale"] == 0
    assert st["OFFER"]["count"] == 0 and st["OFFER"]["avg_days_in_stage"] is None
    one = (await get(c, "pipeline-summary", rec, job_id=world["j1"]["id"])).json()
    assert (one["total"], one["live"], one["stale"]) == (3, 1, 0)


async def test_interview_statistics(client, monkeypatch):
    co = await company_with_staff(client)
    rec, rec2 = co["rec"], co["rec2"]
    job = await create_job(client, rec, publish=True, title="Interview stats role")
    sls = [await shortlisted(client, rec, job=job) for _ in range(4)]
    s2 = utc_slot(days=2, hour=9)[0]
    day2 = datetime.fromisoformat(s2)
    day3 = day2 + timedelta(days=1)

    def slot(day, hour, minutes):
        start = day.replace(hour=hour)
        return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()

    plan = [("TECHNICAL", slot(day2, 9, 60)), ("PHONE_SCREEN", slot(day2, 11, 30)), ("PANEL", slot(day2, 13, 90)), ("TECHNICAL", slot(day3, 9, 60))]
    ivs = []
    for sl, (kind, (s, e)) in zip(sls, plan, strict=True):
        r = await schedule(client, rec, sl["app"]["id"], [rec2], start=s, end=e, interview_type=kind)
        assert r.status_code == 201, r.text
        ivs.append(r.json())
    assert (await client.post(f"{API}/interviews/{ivs[2]['id']}/cancel", headers=rec["h"], json={"reason": "Panel unavailable"})).status_code == 200
    monkeypatch.setattr("app.services.interviews._now", lambda: day2.replace(hour=20))
    assert (await client.post(f"{API}/interviews/{ivs[0]['id']}/complete", headers=rec["h"])).status_code == 200
    assert (await client.post(f"{API}/interviews/{ivs[1]['id']}/no-show", headers=rec["h"])).status_code == 200
    for who, rating, rec_ in ((rec, 4, "HIRE"), (rec2, 2, "NO_HIRE")):
        r = await client.post(f"{API}/interviews/{ivs[0]['id']}/feedback", headers=who["h"], json={"rating": rating, "recommendation": rec_})
        assert r.status_code == 201, r.text

    r = await get(client, "interview-statistics", rec)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["total"] == 4
    assert s["by_status"] == {"SCHEDULED": 1, "CONFIRMED": 0, "RESCHEDULED": 0, "COMPLETED": 1, "CANCELLED": 1, "NO_SHOW": 1}
    assert s["by_type"] == {"PHONE_SCREEN": 1, "TECHNICAL": 2, "BEHAVIORAL": 0, "PANEL": 1, "ONSITE": 0, "FINAL": 0}
    assert s["avg_duration_minutes"] == 60.0  # (60 + 30 + 90 + 60) / 4
    assert (s["held_or_missed"], s["no_show_rate"], s["cancellation_rate"]) == (2, 0.5, 0.25)
    assert s["feedback"] == {
        "entries": 2, "interviews_with_feedback": 1, "average_rating": 3.0,
        "recommendations": {"STRONG_HIRE": 0, "HIRE": 1, "NO_HIRE": 1, "STRONG_NO_HIRE": 0},
    }  # fmt: skip
    day3_only = (await get(client, "interview-statistics", rec, from_date=day3.date().isoformat())).json()
    assert day3_only["total"] == 1 and day3_only["by_status"]["SCHEDULED"] == 1 and day3_only["no_show_rate"] is None
    day2_only = (await get(client, "interview-statistics", rec, to_date=day2.date().isoformat())).json()
    assert day2_only["total"] == 3 and day2_only["avg_duration_minutes"] == 60.0
    # the hiring manager of no job sees nothing, another company sees nothing
    assert (await get(client, "interview-statistics", co["hm"])).json()["total"] == 0
    other = await register_employer(client)
    zero = (await get(client, "interview-statistics", other)).json()
    assert zero["total"] == 0 and zero["avg_duration_minutes"] is None and zero["no_show_rate"] is None and zero["cancellation_rate"] is None


async def test_analytics_are_cached_and_invalidated_by_writes(world):
    c, rec = world["client"], world["rec"]
    cache = get_cache()
    path_params = [("applications-by-status", {}), ("funnel", {}), ("applications-by-job", {}), ("source-statistics", {}), ("pipeline-summary", {})]
    first = {}
    for path, params in path_params:
        first[path] = (await get(c, path, rec, **params)).json()
    hits = cache.hits
    for path, params in path_params:
        assert (await get(c, path, rec, **params)).json() == first[path]
    assert cache.hits == hits + len(path_params)  # all five served from Redis
    moved = await c.post(f"{API}/applications/{world['apps']['c5']}/status", headers=rec["h"], json={"status": "SCREENING"})
    assert moved.status_code == 200
    st = (await get(c, "applications-by-status", rec)).json()
    assert {i["status"]: i["count"] for i in st["items"]}["APPLIED"] == 0 and {i["status"]: i["count"] for i in st["items"]}["SCREENING"] == 2
    assert (await get(c, "funnel", rec)).json()["stages"][1]["count"] == 6
    assert (await get(c, "pipeline-summary", rec)).json()["stages"][1]["count"] == 2
    assert (await get(c, "applications-by-job", rec)).json() != first["applications-by-job"]
    # a closed job still reports its history
    assert (await c.post(f"{API}/jobs/{world['j1']['id']}/close", headers=rec["h"])).status_code == 200
    items = {i["title"]: i for i in (await get(c, "applications-by-job", rec)).json()["items"]}
    assert items["Dash Job One"]["job_status"] == "CLOSED"


async def test_authorization_matrix(world):
    c = world["client"]
    admin = await create_admin(c)
    other = await register_employer(c)
    paths = [
        "applications-by-job", "applications-by-status", "funnel", "interview-statistics", "job-performance", "source-statistics",
        "matching-performance", "top-skills", "pipeline-summary", "recruiter-dashboard",
    ]  # fmt: skip
    for p in [*paths, "recruiter-activity"]:
        assert (await c.get(f"{API}/reports/{p}")).status_code == 401, p
        assert (await get(c, p, world["cands"]["c1"])).status_code == 403, p  # candidates never see company analytics
        assert (await get(c, p, other, company_id=world["rec"]["company_id"])).status_code == 403, p  # nor staff of another tenant
        assert (await get(c, p, admin)).status_code == 200, p  # platform-wide
        assert (await get(c, p, admin, company_id=world["rec"]["company_id"])).status_code == 200, p
        assert (await get(c, p, admin, company_id=str(uuid.uuid4()))).status_code == 404, p
        assert (await get(c, p, world["rec"], company_id=world["rec"]["company_id"])).status_code == 200, p  # own id is fine
    for p in paths:
        assert (await get(c, p, world["hm"])).status_code == 200, p  # hiring managers: assigned jobs only
    assert (await get(c, "recruiter-activity", world["hm"])).status_code == 403
    # hiring-manager scoping of the analytics: only Job Two
    hm_jobs = (await get(c, "applications-by-job", world["hm"])).json()
    assert [i["title"] for i in hm_jobs["items"]] == ["Dash Job Two"]
    assert (await get(c, "funnel", world["hm"])).json()["applications"] == 4
    assert (await get(c, "source-statistics", world["hm"])).json()["total"] == 2  # DIRECT, REFERRAL
    assert (await get(c, "applications-by-status", world["hm"])).json()["total"] == 4
    assert (await get(c, "pipeline-summary", world["hm"])).json()["total"] == 4
    assert (await get(c, "matching-performance", world["hm"])).json()["scored_pairs"] == 3  # only J2's rows
    # another tenant sees none of my data
    assert (await get(c, "applications-by-job", other)).json()["total"] == 0
    assert (await get(c, "funnel", other)).json()["applications"] == 0
    assert (await get(c, "job-performance", other)).json()["total"] == 0


async def test_parameter_validation(world):
    c, rec = world["client"], world["rec"]
    bad = [
        {"from_date": "2026-03-02", "to_date": "2026-03-01"},
        {"from_date": "2010-01-01", "to_date": "2026-01-01"},
        {"from_date": "yesterday"},
        {"sort": "nope"},
        {"order": "sideways"},
        {"page": 0},
        {"page_size": 101},
        {"format": "xml"},
    ]
    for params in bad:
        r = await get(c, "applications-by-job", rec, **params)
        assert r.status_code == 422, (params, r.text)
        assert r.json()["error"]["code"] in ("VALIDATION_ERROR", "INVALID_DATE_RANGE", "DATE_RANGE_TOO_LARGE")
