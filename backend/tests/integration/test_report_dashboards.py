"""Dashboards with hand-computed numbers (see tests.helpers_ops.build_pipeline for the dataset), scoping and caching."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.cache.redis_cache import get_cache
from tests.helpers import create_admin, register_candidate, register_employer
from tests.helpers_ops import API, age_application, build_pipeline, bust_cache, put_match, sql

pytestmark = pytest.mark.integration

TODAY = date.today


@pytest.fixture
async def world(client):
    w = await build_pipeline(client)
    w["client"] = client
    return w


def stage_counts(dash):
    return {s["stage"]: s["count"] for s in dash["funnel"]}


async def get(client, path, account, **params):
    r = await client.get(f"{API}{path}", headers=account["h"], params=params)
    return r


async def test_recruiter_dashboard_numbers(world):
    r = await get(world["client"], "/reports/recruiter-dashboard", world["rec"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["scope"] == "company" and d["company_id"] == world["rec"]["company_id"]
    k = d["kpis"]
    assert k == {
        "active_jobs": 2, "total_applications": 7, "applications_in_screening": 1, "shortlisted": 1, "upcoming_interviews": 1,
        "jobs_nearing_deadline": 1, "avg_applications_per_job": 3.5, "hires_in_period": 1,
    }  # fmt: skip
    # funnel = stages ever reached according to the history (not the current status)
    assert stage_counts(d) == {
        "APPLIED": 7, "SCREENING": 5, "SHORTLISTED": 4, "INTERVIEW": 3, "OFFER": 1, "HIRED": 1, "REJECTED": 1, "WITHDRAWN": 1,
    }  # fmt: skip
    funnel = {s["stage"]: s for s in d["funnel"]}
    assert funnel["SCREENING"]["pct_of_previous"] == 71.4 and funnel["SHORTLISTED"]["pct_of_previous"] == 80.0
    assert funnel["INTERVIEW"]["pct_of_previous"] == 75.0 and funnel["OFFER"]["pct_of_previous"] == 33.3
    assert funnel["HIRED"]["pct_of_applied"] == 14.3 and funnel["REJECTED"]["is_branch"] and not funnel["HIRED"]["is_branch"]
    # the current-status distribution differs from the funnel (c2 was rejected after the interview stage, c1 was hired)
    dist = {s["status"]: s["count"] for s in d["status_distribution"]}
    assert dist == {"APPLIED": 1, "SCREENING": 1, "SHORTLISTED": 1, "INTERVIEW": 1, "OFFER": 0, "HIRED": 1, "REJECTED": 1, "WITHDRAWN": 1}
    assert sum(s["percent"] for s in d["status_distribution"]) == pytest.approx(100, abs=0.5)
    # per job
    assert [(j["title"], j["applications"]) for j in d["applications_by_job"]] == [("Dash Job Two", 4), ("Dash Job One", 3)]
    # time series: 30 daily buckets, everything applied today
    series = d["applications_over_time"]
    assert d["period"]["granularity"] == "day" and len(series) == 30
    assert series[-1] == {"bucket": TODAY().isoformat(), "count": 7} and sum(p["count"] for p in series) == 7
    # the interview is two days ahead: outside the default window, inside an extended one
    assert sum(p["total"] for p in d["interview_activity"]) == 0
    ext = (await get(world["client"], "/reports/recruiter-dashboard", world["rec"], to_date=(TODAY() + timedelta(days=5)).isoformat())).json()
    act = [p for p in ext["interview_activity"] if p["total"]]
    assert len(act) == 1 and act[0]["scheduled"] == 1 and act[0]["bucket"] == (TODAY() + timedelta(days=2)).isoformat()
    # best semantic matches of PUBLISHED jobs among visible candidates (draft J3 rows and the hidden candidate are excluded)
    top = d["top_matching_candidates"]
    assert [(t["candidate_name"], t["job_title"], t["score"], t["band"]) for t in top] == [
        ("Cand1 Tester", "Dash Job One", 0.91, "STRONG"),
        ("Cand2 Tester", "Dash Job One", 0.80, "STRONG"),
        ("Cand5 Tester", "Dash Job One", 0.70, "GOOD"),
        ("Cand6 Tester", "Dash Job Two", 0.66, "GOOD"),
        ("Cand3 Tester", "Dash Job One", 0.62, "GOOD"),
    ]
    assert top[0]["application_id"] == world["apps"]["c1"] and top[2]["application_id"] is None  # c5 never applied to J1
    assert top[3]["application_id"] is None  # c6 withdrew
    assert "Zed" not in r.text
    # latest applications first (c7 applied last), with the stored score and band
    recent = d["recent_applications"]
    assert [x["candidate_name"] for x in recent] == [f"Cand{i} Tester" for i in range(7, 0, -1)]
    assert recent[-1]["match_score"] == 0.91 and recent[-1]["match_band"] == "STRONG" and recent[0]["match_score"] is None


async def test_period_filters_and_granularity(world):
    c = world["client"]
    # c3 and c5 applied 5 days ago, c1 applied 40 days ago (all history shifted with them)
    for key, days in (("c3", 5), ("c5", 5), ("c1", 40)):
        await age_application(world["apps"][key], applied_days_ago=days)
    await bust_cache()
    d = (await get(c, "/reports/recruiter-dashboard", world["rec"])).json()  # default window: last 30 days
    assert d["kpis"]["total_applications"] == 6 and stage_counts(d)["APPLIED"] == 6
    assert stage_counts(d)["HIRED"] == 0  # c1 is outside the window ...
    assert d["kpis"]["hires_in_period"] == 0  # ... and so is its hire event
    assert d["kpis"]["applications_in_screening"] == 1  # snapshot KPIs ignore the window
    pts = {p["bucket"]: p["count"] for p in d["applications_over_time"]}
    assert pts[(TODAY() - timedelta(days=5)).isoformat()] == 2 and pts[TODAY().isoformat()] == 4
    # an explicit window
    old = (await get(c, "/reports/recruiter-dashboard", world["rec"], from_date=(TODAY() - timedelta(days=10)).isoformat(), to_date=(TODAY() - timedelta(days=3)).isoformat())).json()
    assert old["kpis"]["total_applications"] == 2
    assert stage_counts(old)["APPLIED"] == 2 and stage_counts(old)["SCREENING"] == 1 and stage_counts(old)["SHORTLISTED"] == 0
    assert len(old["applications_over_time"]) == 8
    wide = (await get(c, "/reports/recruiter-dashboard", world["rec"], from_date=(TODAY() - timedelta(days=60)).isoformat())).json()
    # c1's hire event (history shifted by 40 days with the application) is inside a 60-day window
    assert wide["kpis"]["total_applications"] == 7 and wide["kpis"]["hires_in_period"] == 1
    assert stage_counts(wide)["HIRED"] == 1
    weekly = (await get(c, "/reports/recruiter-dashboard", world["rec"], from_date=(TODAY() - timedelta(days=60)).isoformat(), granularity="week")).json()
    assert weekly["period"]["granularity"] == "week" and sum(p["count"] for p in weekly["applications_over_time"]) == 7
    assert all(date.fromisoformat(p["bucket"]).weekday() == 0 for p in weekly["applications_over_time"])  # buckets start on Mondays
    monthly = (await get(c, "/reports/recruiter-dashboard", world["rec"], from_date=(TODAY() - timedelta(days=100)).isoformat(), granularity="month")).json()
    assert sum(p["count"] for p in monthly["applications_over_time"]) == 7 and all(p["bucket"].endswith("-01") for p in monthly["applications_over_time"])


async def test_hiring_manager_sees_only_assigned_jobs(world):
    d = (await get(world["client"], "/reports/recruiter-dashboard", world["hm"])).json()
    assert d["scope"] == "assigned_jobs"
    assert d["kpis"] == {
        "active_jobs": 1, "total_applications": 4, "applications_in_screening": 0, "shortlisted": 1, "upcoming_interviews": 1,
        "jobs_nearing_deadline": 1, "avg_applications_per_job": 4.0, "hires_in_period": 0,
    }  # fmt: skip
    assert stage_counts(d) == {"APPLIED": 4, "SCREENING": 2, "SHORTLISTED": 2, "INTERVIEW": 1, "OFFER": 0, "HIRED": 0, "REJECTED": 0, "WITHDRAWN": 1}
    assert [j["title"] for j in d["applications_by_job"]] == ["Dash Job Two"]
    assert {t["job_title"] for t in d["top_matching_candidates"]} == {"Dash Job Two"}
    assert {a["job_title"] for a in d["recent_applications"]} == {"Dash Job Two"} and len(d["recent_applications"]) == 4
    # a colleague recruiter sees exactly what the first recruiter sees
    a = (await get(world["client"], "/reports/recruiter-dashboard", world["rec"])).json()
    b = (await get(world["client"], "/reports/recruiter-dashboard", world["rec2"])).json()
    for key in ("kpis", "funnel", "status_distribution", "applications_by_job", "top_matching_candidates"):
        assert a[key] == b[key]


async def test_other_company_and_scope_rules(world):
    c = world["client"]
    other = await register_employer(c)
    empty = (await get(c, "/reports/recruiter-dashboard", other)).json()
    assert empty["kpis"]["total_applications"] == 0 and empty["kpis"]["active_jobs"] == 0 and empty["top_matching_candidates"] == []
    assert stage_counts(empty)["APPLIED"] == 0 and empty["recent_applications"] == [] and empty["applications_by_job"] == []
    # staff cannot peek into another tenant by passing its id
    r = await get(c, "/reports/recruiter-dashboard", other, company_id=world["rec"]["company_id"])
    assert r.status_code == 403
    # admins may look at one company or at everything
    admin = await create_admin(c)
    one = (await get(c, "/reports/recruiter-dashboard", admin, company_id=world["rec"]["company_id"])).json()
    assert one["scope"] == "company" and one["kpis"]["total_applications"] == 7
    everything = (await get(c, "/reports/recruiter-dashboard", admin)).json()
    assert everything["scope"] == "platform" and everything["kpis"]["total_applications"] == 7
    assert (await get(c, "/reports/recruiter-dashboard", admin, company_id="00000000-0000-0000-0000-000000000000")).status_code == 404
    # candidates are not allowed
    assert (await get(c, "/reports/recruiter-dashboard", world["cands"]["c1"])).status_code == 403
    assert (await c.get(f"{API}/reports/recruiter-dashboard")).status_code == 401


async def test_dashboard_parameter_validation(world):
    c, h = world["client"], world["rec"]
    r = await get(c, "/reports/recruiter-dashboard", h, from_date="2026-02-10", to_date="2026-02-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_DATE_RANGE"
    r = await get(c, "/reports/recruiter-dashboard", h, from_date="2015-01-01", to_date="2026-01-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "DATE_RANGE_TOO_LARGE"
    r = await get(c, "/reports/recruiter-dashboard", h, from_date="2022-01-01", to_date="2026-01-01", granularity="day")
    assert r.status_code == 422 and r.json()["error"]["code"] == "GRANULARITY_TOO_FINE"
    assert (await get(c, "/reports/recruiter-dashboard", h, from_date="not-a-date")).status_code == 422
    assert (await get(c, "/reports/recruiter-dashboard", h, granularity="hour")).status_code == 422


async def test_dashboard_is_cached_and_every_relevant_write_invalidates_it(world):
    c, rec = world["client"], world["rec"]
    cache = get_cache()
    first = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    hits = cache.hits
    second = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert second == first and second["generated_at"] == first["generated_at"] and cache.hits == hits + 1  # served from Redis

    # an application stage change (APPLICATIONS domain) is visible immediately
    moved = await c.post(f"{API}/applications/{world['apps']['c3']}/status", headers=rec["h"], json={"status": "SHORTLISTED"})
    assert moved.status_code == 200
    after = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert after["generated_at"] != first["generated_at"]
    assert after["kpis"]["applications_in_screening"] == 0 and after["kpis"]["shortlisted"] == 2
    assert stage_counts(after)["SHORTLISTED"] == 5

    # an interview (INTERVIEWS domain)
    from tests.helpers_ops import schedule, utc_slot

    s, e = utc_slot(days=1, hour=14)
    assert (await schedule(c, rec, world["apps"]["c7"], [world["rec2"]], start=s, end=e)).status_code == 201
    assert (await get(c, "/reports/recruiter-dashboard", rec)).json()["kpis"]["upcoming_interviews"] == 2
    assert (await get(c, "/reports/recruiter-dashboard", rec)).json()["generated_at"] != after["generated_at"]

    # a job lifecycle change (JOBS domain)
    assert (await c.post(f"{API}/jobs/{world['j2']['id']}/close", headers=rec["h"])).status_code == 200
    closed = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert closed["kpis"]["active_jobs"] == 1 and closed["kpis"]["jobs_nearing_deadline"] == 0

    # new match scores (MATCHES domain) via the same invalidation the worker performs
    await put_match(world["j1"]["id"], world["cands"]["c4"]["candidate_id"], 0.97)
    stale = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert stale["top_matching_candidates"][0]["score"] == 0.91  # SQL alone does not bump a domain ...
    from app.cache.redis_cache import CacheDomain

    await cache.invalidate(CacheDomain.MATCHES)
    fresh = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert fresh["top_matching_candidates"][0]["score"] == 0.97  # ... the worker's invalidate does

    # different callers / parameters never share an entry
    hm = (await get(c, "/reports/recruiter-dashboard", world["hm"])).json()
    assert hm["scope"] == "assigned_jobs" and hm["kpis"]["total_applications"] != fresh["kpis"]["total_applications"]
    narrow = (await get(c, "/reports/recruiter-dashboard", rec, from_date=TODAY().isoformat())).json()
    assert len(narrow["applications_over_time"]) == 1


async def test_new_application_shows_up_immediately(world):
    c, rec = world["client"], world["rec"]
    before = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    newbie = await register_candidate(c, first="Newbie", last="Late")
    ap = await c.post(f"{API}/applications", headers=newbie["h"], json={"job_id": world["j1"]["id"]})
    assert ap.status_code == 201
    after = (await get(c, "/reports/recruiter-dashboard", rec)).json()
    assert before["kpis"]["total_applications"] == 7 and after["kpis"]["total_applications"] == 8
    assert after["recent_applications"][0]["candidate_name"] == "Newbie Late" and after["recent_applications"][0]["status"] == "APPLIED"
    assert after["applications_over_time"][-1]["count"] == 8
    assert {s["stage"]: s["count"] for s in after["funnel"]}["APPLIED"] == 8
    assert after["kpis"]["avg_applications_per_job"] == 4.0
    # the applicant sees it on their own dashboard, which was never computed before
    mine = (await get(c, "/reports/candidate-dashboard", newbie)).json()
    assert mine["total_applications"] == 1 and mine["active_applications"] == 1


async def test_candidate_dashboard(world):
    c = world["client"]
    c5 = world["cands"]["c5"]  # applied (APPLIED) to J2 only
    d = (await get(c, "/reports/candidate-dashboard", c5)).json()
    assert d["total_applications"] == 1 and d["active_applications"] == 1
    assert {s["status"]: s["count"] for s in d["applications_by_status"]}["APPLIED"] == 1
    # recommended: J1 (.70) only - J2 is already applied to, J3 is a draft (even though it scores .99)
    rec_jobs = d["recommended_jobs"]
    assert [(j["title"], j["score"], j["percent"], j["band"], j["summary"]) for j in rec_jobs] == [("Dash Job One", 0.7, 70, "GOOD", "Good overall fit")]
    assert d["upcoming_interviews"] == [] and d["resume"] == {"has_resume": False, "resume_id": None, "filename": None, "status": None, "processing_status": None, "error_code": None, "uploaded_at": None}
    assert d["saved_jobs"] == 0
    me = (await c.get(f"{API}/candidates/me", headers=c5["h"])).json()
    assert d["profile_completion"]["percent"] == me["completion"]["percent"] and d["profile_completion"]["missing"] == me["completion"]["missing"]

    # c4 has the interview two days ahead and is at the INTERVIEW stage
    d4 = (await get(c, "/reports/candidate-dashboard", world["cands"]["c4"])).json()
    assert len(d4["upcoming_interviews"]) == 1 and d4["upcoming_interviews"][0]["id"] == world["interview"]["id"]
    assert d4["upcoming_interviews"][0]["company_name"] and d4["upcoming_interviews"][0]["interview_type"] == "TECHNICAL"
    assert "notes" not in d4["upcoming_interviews"][0]
    # c1 was hired: no longer active
    d1 = (await get(c, "/reports/candidate-dashboard", world["cands"]["c1"])).json()
    assert d1["total_applications"] == 1 and d1["active_applications"] == 0
    # c6 withdrew from J2, so J2 is recommendable again (.66)
    d6 = (await get(c, "/reports/candidate-dashboard", world["cands"]["c6"])).json()
    assert [(j["title"], j["score"]) for j in d6["recommended_jobs"]] == [("Dash Job Two", 0.66)]
    assert d6["active_applications"] == 0 and {s["status"]: s["count"] for s in d6["applications_by_status"]}["WITHDRAWN"] == 1
    # a candidate without any application
    z = (await get(c, "/reports/candidate-dashboard", world["zed"])).json()
    assert z["total_applications"] == 0 and [j["title"] for j in z["recommended_jobs"]] == ["Dash Job One"] and z["recommended_jobs"][0]["score"] == 0.95


async def test_candidate_dashboard_live_parts_and_resume(world):
    c, cand = world["client"], world["cands"]["c3"]
    d = (await get(c, "/reports/candidate-dashboard", cand)).json()
    unread = (await c.get(f"{API}/notifications/unread-count", headers=cand["h"])).json()["unread"]
    assert d["unread_notifications"] == unread and unread >= 2  # submission + screening
    # unread / saved / résumé are read live (no cache domain tracks them)
    assert (await c.post(f"{API}/notifications/read-all", headers=cand["h"])).status_code in (200, 204)
    assert (await c.put(f"{API}/jobs/{world['j2']['id']}/save", headers=cand["h"])).status_code == 200
    candidate_id = cand["candidate_id"]
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (gen_random_uuid(), :c, 'PROCESSED', true)",
        c=uuid.UUID(candidate_id),
    )
    rid = (await sql("SELECT id FROM resumes WHERE candidate_id = :c", c=uuid.UUID(candidate_id)))[0][0]
    await sql(
        "INSERT INTO resume_documents (id, resume_id, storage_key, original_filename, content_type, size_bytes, sha256) "
        "VALUES (gen_random_uuid(), :r, 'key-1', 'cv.pdf', 'application/pdf', 1234, 'abc')", r=rid,
    )  # fmt: skip
    doc = (await sql("SELECT id FROM resume_documents WHERE resume_id = :r", r=rid))[0][0]
    await sql(
        "INSERT INTO resume_processing_results (id, resume_id, document_id, status, attempts) VALUES (gen_random_uuid(), :r, :d, 'COMPLETED', 1)",
        r=rid, d=doc,
    )  # fmt: skip
    after = (await get(c, "/reports/candidate-dashboard", cand)).json()
    assert after["unread_notifications"] == 0 and after["saved_jobs"] == 1
    assert after["resume"]["has_resume"] and after["resume"]["filename"] == "cv.pdf" and after["resume"]["status"] == "PROCESSED"
    assert after["resume"]["processing_status"] == "COMPLETED" and after["resume"]["error_code"] is None
    # a new notification shows up immediately
    mv = await c.post(f"{API}/applications/{world['apps']['c3']}/status", headers=world["rec"]["h"], json={"status": "SHORTLISTED"})
    assert mv.status_code == 200
    assert (await get(c, "/reports/candidate-dashboard", cand)).json()["unread_notifications"] == 1


async def test_candidate_dashboard_is_candidate_only(world):
    c = world["client"]
    admin = await create_admin(c)
    for who in (world["rec"], world["hm"], admin):
        assert (await get(c, "/reports/candidate-dashboard", who)).status_code == 403
    assert (await c.get(f"{API}/reports/candidate-dashboard")).status_code == 401


async def test_admin_dashboard(world):
    c = world["client"]
    admin = await create_admin(c)
    r = await get(c, "/reports/admin-dashboard", admin)
    assert r.status_code == 200, r.text
    d = r.json()
    # users: admin 1, recruiters 2 (rec, rec2), hiring manager 1, candidates 7 + Zed
    assert d["users_by_role"] == {"ADMIN": 1, "RECRUITER": 2, "HIRING_MANAGER": 1, "CANDIDATE": 8} and d["users_total"] == 12
    assert d["users_by_status"] == {"ACTIVE": 12, "SUSPENDED": 0}
    assert d["companies"] == {"total": 1, "active": 1, "suspended": 0}
    assert d["jobs_by_status"] == {"DRAFT": 1, "PUBLISHED": 2, "PAUSED": 0, "CLOSED": 0, "ARCHIVED": 0}
    assert d["applications_by_status"] == {"APPLIED": 1, "SCREENING": 1, "SHORTLISTED": 1, "INTERVIEW": 1, "OFFER": 0, "HIRED": 1, "REJECTED": 1, "WITHDRAWN": 1}
    assert d["interviews_by_status"]["SCHEDULED"] == 1 and sum(d["interviews_by_status"].values()) == 1
    assert d["resumes_by_status"] == {"UPLOADED": 0, "PROCESSING": 0, "PROCESSED": 0, "FAILED": 0}
    assert d["matches"]["pairs"] == 10 and d["matches"]["jobs_with_matches"] == 3 and d["matches"]["candidates_with_matches"] == 7
    assert d["matches"]["last_generated_at"]
    db_tasks = await sql("SELECT status, count(*) FROM background_tasks WHERE created_at > now() - interval '24 hours' GROUP BY status")
    assert d["tasks_last_24h_by_status"] == {"PENDING": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0} | {s: int(n) for s, n in db_tasks}
    assert len(d["signups_over_time"]) == 30 and d["signups_over_time"][-1]["count"] == 12 and sum(p["count"] for p in d["signups_over_time"]) == 12
    assert 1 <= len(d["recent_audit_events"]) <= 10
    assert d["recent_audit_events"][0]["created_at"] >= d["recent_audit_events"][-1]["created_at"]
    for who in (world["rec"], world["hm"], world["cands"]["c1"]):
        assert (await get(c, "/reports/admin-dashboard", who)).status_code == 403
    assert (await c.get(f"{API}/reports/admin-dashboard")).status_code == 401
