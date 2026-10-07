"""CSV export: content type, attachment header, proper escaping and CSV-injection protection, and the background export task."""

from __future__ import annotations

import csv
import io
import re
import uuid

import pytest

from app.db.database import get_sessionmaker
from app.db.models import TaskType
from app.services.report_tasks import RESULT_MAX_ROWS, handle_export_report
from app.services.tasks import TaskStore
from app.workers.tasks import TaskContext, TaskFailure
from tests.helpers import add_staff, create_admin, create_job, register_candidate, register_employer
from tests.helpers_ops import API, apply_to, build_pipeline, bust_cache, sql

pytestmark = pytest.mark.integration

EVIL_TITLES = [
    '=HYPERLINK("http://evil.example/steal","click me")',
    "+1+1",
    "-2+3",
    "@SUM(A1:A9)",
    'Senior "Rockstar", Backend',
    "Plain title",
]


@pytest.fixture
async def evil(client):
    """A company whose job titles try every spreadsheet-injection prefix; each job has one applicant."""
    rec = await register_employer(client)
    jobs = {}
    for title in EVIL_TITLES:
        job = await create_job(client, rec, publish=True, title=title)
        cand = await register_candidate(client, first="Csv", last="Candidate")
        await apply_to(client, cand, job["id"])
        jobs[title] = job
    return {"client": client, "rec": rec, "jobs": jobs}


def parse(resp) -> list[list[str]]:
    return list(csv.reader(io.StringIO(resp.text)))


async def test_csv_is_escaped_and_neutralises_formula_injection(evil):
    c, rec = evil["client"], evil["rec"]
    r = await c.get(f"{API}/reports/job-performance", headers=rec["h"], params={"format": "csv", "page_size": 2})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(r'attachment; filename="talentlens-job-performance-\d{8}\.csv"', r.headers["content-disposition"])
    assert r.headers["cache-control"] == "no-store"
    rows = parse(r)
    header, body = rows[0], rows[1:]
    assert header[:5] == ["job_id", "title", "job_status", "published_at", "applications"]
    assert len(body) == 6  # the CSV ignores pagination (page_size=2) and exports everything
    titles = {row[1] for row in body}
    assert titles == {
        "'=HYPERLINK(\"http://evil.example/steal\",\"click me\")", "'+1+1", "'-2+3", "'@SUM(A1:A9)", 'Senior "Rockstar", Backend', "Plain title",
    }
    # raw quoting: commas / quotes are escaped the RFC 4180 way
    assert '"Senior ""Rockstar"", Backend"' in r.text
    assert "\r\n" in r.text
    # no cell may start with a formula trigger character
    for row in body:
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@", "\t", "\r")), cell
    assert {row[4] for row in body} == {"1"}  # numbers stay numbers
    # JSON and CSV agree
    js = (await c.get(f"{API}/reports/job-performance", headers=rec["h"], params={"page_size": 100})).json()
    assert {i["title"] for i in js["items"]} == set(EVIL_TITLES)


@pytest.mark.parametrize(
    ("path", "expected_header"),
    [
        ("applications-by-job", ["job_id", "title", "job_status", "department", "applications"]),
        ("applications-by-status", ["status", "count", "percent"]),
        ("funnel", ["stage", "kind", "count", "pct_of_applied", "pct_of_previous"]),
        ("interview-statistics", ["section", "key", "value"]),
        ("recruiter-activity", ["user_id", "name", "role", "company", "status_changes"]),
        ("source-statistics", ["source", "applications", "share", "reached_shortlist"]),
        ("matching-performance", ["section", "key", "count", "value"]),
        ("top-skills", ["list", "skill", "count", "required_in_jobs", "preferred_in_jobs"]),
        ("pipeline-summary", ["stage", "count", "avg_days_in_stage", "max_days_in_stage", "stale"]),
    ],
)
async def test_every_report_can_be_exported_as_csv(evil, path, expected_header):
    r = await evil["client"].get(f"{API}/reports/{path}", headers=evil["rec"]["h"], params={"format": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv") and f"talentlens-{path}-" in r.headers["content-disposition"]
    rows = parse(r)
    assert rows[0][: len(expected_header)] == expected_header and len(rows) >= 2
    assert all(len(row) == len(rows[0]) for row in rows)


async def test_csv_respects_authorization_and_sorting(evil):
    c, rec = evil["client"], evil["rec"]
    other = await register_employer(c)
    r = await c.get(f"{API}/reports/job-performance", headers=other["h"], params={"format": "csv"})
    assert r.status_code == 200 and len(parse(r)) == 1  # header only: nothing of mine leaks
    cand = await register_candidate(c)
    assert (await c.get(f"{API}/reports/job-performance", headers=cand["h"], params={"format": "csv"})).status_code == 403
    assert (await c.get(f"{API}/reports/job-performance", params={"format": "csv"})).status_code == 401
    asc = parse(await c.get(f"{API}/reports/job-performance", headers=rec["h"], params={"format": "csv", "sort": "title", "order": "asc"}))
    titles = [row[1] for row in asc[1:]]
    assert titles == sorted(titles, key=str.lower)


# --------------------------------------------------------------------------------------------------------------------
# background export (TaskType.EXPORT_REPORT -> app.services.report_tasks:handle_export_report)
# --------------------------------------------------------------------------------------------------------------------
async def test_export_task_produces_the_csv_in_the_task_result(evil):
    c, rec = evil["client"], evil["rec"]
    r = await c.post(f"{API}/reports/job-performance/export", headers=rec["h"], params={"sort": "title", "order": "asc"})
    assert r.status_code == 202, r.text
    task_id = r.json()["task_id"]
    task = (await c.get(f"{API}/tasks/{task_id}", headers=rec["h"])).json()  # the inline dispatcher already ran it
    assert task["type"] == "EXPORT_REPORT" and task["status"] == "COMPLETED" and task["progress"] == 100, task
    res = task["result"]
    assert res["report"] == "job-performance" and res["rows"] == 6 and res["total_rows"] == 6 and res["truncated"] is False
    assert res["content_type"] == "text/csv" and re.fullmatch(r"talentlens-job-performance-\d{8}\.csv", res["filename"])
    rows = list(csv.reader(io.StringIO(res["csv"])))
    assert rows[0][1] == "title" and len(rows) == 7
    assert "'=HYPERLINK" in res["csv"] and all(not row[1].startswith(("=", "+", "-", "@")) for row in rows[1:])
    titles = [row[1] for row in rows[1:]]
    assert titles == sorted(titles, key=str.lower)
    # the task belongs to the requester's company: a colleague may read it, another tenant may not
    colleague = await add_staff(c, rec, "RECRUITER")
    assert (await c.get(f"{API}/tasks/{task_id}", headers=colleague["h"])).status_code == 200
    other = await register_employer(c)
    assert (await c.get(f"{API}/tasks/{task_id}", headers=other["h"])).status_code == 404
    # parameters are validated before anything is queued; candidates cannot export
    bad = await c.post(f"{API}/reports/job-performance/export", headers=rec["h"], params={"from_date": "2026-05-02", "to_date": "2026-05-01"})
    assert bad.status_code == 422
    cand = await register_candidate(c)
    assert (await c.post(f"{API}/reports/job-performance/export", headers=cand["h"])).status_code == 403
    assert (await c.post(f"{API}/reports/job-performance/export")).status_code == 401
    assert (await c.post(f"{API}/reports/job-performance/export", headers=other["h"], params={"company_id": rec["company_id"]})).status_code == 403


async def test_export_task_scope_follows_the_requesting_user(client):
    w = await build_pipeline(client)
    hm = await client.post(f"{API}/reports/job-performance/export", headers=w["hm"]["h"])
    assert hm.status_code == 202, hm.text
    res = (await client.get(f"{API}/tasks/{hm.json()['task_id']}", headers=w["hm"]["h"])).json()["result"]
    assert res["rows"] == 1 and "Dash Job Two" in res["csv"] and "Dash Job One" not in res["csv"]  # assigned jobs only
    admin = await create_admin(client)
    full = await client.post(f"{API}/reports/job-performance/export", headers=admin["h"])
    result = (await client.get(f"{API}/tasks/{full.json()['task_id']}", headers=admin["h"])).json()["result"]
    assert result["rows"] == 2 and "Dash Job One" in result["csv"]


async def test_export_task_is_deduplicated_while_active(client):
    rec = await register_employer(client)
    await create_job(client, rec, publish=True, title="Only job")
    first = (await client.post(f"{API}/reports/job-performance/export", headers=rec["h"])).json()["task_id"]
    # force the finished task back to PENDING to simulate "still queued": an identical request returns the same task
    await sql("UPDATE background_tasks SET status = 'PENDING', started_at = NULL, finished_at = NULL WHERE id = :i", i=uuid.UUID(first))
    again = await client.post(f"{API}/reports/job-performance/export", headers=rec["h"])
    assert again.status_code == 202 and again.json()["task_id"] == first and again.json()["status"] == "PENDING"
    other_params = await client.post(f"{API}/reports/job-performance/export", headers=rec["h"], params={"sort": "title"})
    assert other_params.json()["task_id"] != first


async def _ctx(params: dict, created_by: uuid.UUID | None, company_id: uuid.UUID | None = None) -> TaskContext:
    from app.cache.redis_cache import get_cache

    sm = get_sessionmaker()
    return TaskContext(
        task_id=uuid.uuid4(), type=TaskType.EXPORT_REPORT, params=params, created_by_id=created_by, company_id=company_id, attempt=1,
        sessionmaker=sm, cache=get_cache(), store=TaskStore(sm),
    )  # fmt: skip


async def test_export_handler_contract_and_failures(client):
    rec = await register_employer(client)
    await create_job(client, rec, publish=True, title="Handler job")
    cand = await register_candidate(client)
    uid = uuid.UUID(rec["user"]["id"])
    # the handler can run without the HTTP layer; progress updates on a non-existent task row are harmless no-ops
    ok = await handle_export_report(await _ctx({"report": "job-performance"}, uid))
    assert ok["rows"] == 0 and ok["csv"].splitlines()[0].startswith("job_id,title") and ok["truncated"] is False  # no applications yet
    with pytest.raises(TaskFailure) as e1:
        await handle_export_report(await _ctx({"report": "salary-benchmarks"}, uid))
    assert e1.value.code == "UNSUPPORTED_REPORT"
    with pytest.raises(TaskFailure) as e2:
        await handle_export_report(await _ctx({"report": "job-performance"}, None))
    assert e2.value.code == "EXPORT_FORBIDDEN"
    with pytest.raises(TaskFailure) as e3:
        await handle_export_report(await _ctx({"report": "job-performance"}, uuid.uuid4()))
    assert e3.value.code == "EXPORT_FORBIDDEN"
    with pytest.raises(TaskFailure) as e4:  # a candidate account can never be the owner of a company export
        await handle_export_report(await _ctx({"report": "job-performance"}, uuid.UUID(cand["user"]["id"])))
    assert e4.value.code == "FORBIDDEN"
    with pytest.raises(TaskFailure) as e5:
        await handle_export_report(await _ctx({"report": "job-performance", "from_date": "garbage"}, uid))
    assert e5.value.code == "INVALID_PARAMETERS"
    with pytest.raises(TaskFailure) as e6:  # params can not widen the scope: a recruiter naming another company is refused
        other = await register_employer(client)
        await handle_export_report(await _ctx({"report": "job-performance", "company_id": other["company_id"]}, uid))
    assert e6.value.code == "FORBIDDEN"
    # a suspended requester no longer exports
    await sql("UPDATE users SET status = 'SUSPENDED' WHERE id = :u", u=uid)
    with pytest.raises(TaskFailure) as e7:
        await handle_export_report(await _ctx({"report": "job-performance"}, uid))
    assert e7.value.code == "EXPORT_FORBIDDEN"
    assert RESULT_MAX_ROWS == 1000


async def test_export_task_truncates_large_results(client):
    rec = await register_employer(client)
    await create_job(client, rec, publish=True, title="One")
    company = uuid.UUID(rec["company_id"])
    # many jobs with an application each, inserted directly (the cap is about the task result size)
    await sql(
        "INSERT INTO jobs (id, company_id, title, description, status, published_at) "
        "SELECT gen_random_uuid(), :c, 'Bulk job ' || g, 'A description that is long enough', 'PUBLISHED', now() FROM generate_series(1, 1005) g",
        c=company,
    )
    await sql(
        "INSERT INTO candidate_profiles (id, source, sourced_by_company_id, first_name, last_name, display_name) "
        "VALUES (gen_random_uuid(), 'IMPORTED', :c, 'Bulk', 'Candidate', 'Bulk Candidate')", c=company,
    )  # fmt: skip
    await sql(
        "INSERT INTO applications (id, job_id, candidate_id) SELECT gen_random_uuid(), j.id, (SELECT id FROM candidate_profiles WHERE source = 'IMPORTED' LIMIT 1) "
        "FROM jobs j WHERE j.title LIKE 'Bulk job %'",
    )
    await bust_cache()
    res = await handle_export_report(await _ctx({"report": "job-performance", "sort": "title", "order": "asc"}, uuid.UUID(rec["user"]["id"])))
    assert res["total_rows"] == 1005 and res["rows"] == RESULT_MAX_ROWS and res["truncated"] is True
    assert len(list(csv.reader(io.StringIO(res["csv"])))) == RESULT_MAX_ROWS + 1
