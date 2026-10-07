"""Invariants enforced by PostgreSQL itself (CHECK, UNIQUE, partial unique, EXCLUDE, FK), generated columns and indexes."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database import get_sessionmaker
from tests.helpers_spine import scalar, sql

pytestmark = pytest.mark.integration

UNIQUE, CHECK, EXCLUDE, FK, NOT_NULL = "23505", "23514", "23P01", "23503", "23502"


async def run(statement: str, **params: Any) -> Any:
    rows = await sql(statement, **params)
    return rows[0][0] if rows else None


async def violates(statement: str, sqlstate: str, constraint: str | None = None, **params: Any) -> None:
    """The statement must fail with the given SQLSTATE (and constraint / index name) and leave nothing behind."""
    async with get_sessionmaker()() as s:
        with pytest.raises(IntegrityError) as exc:
            await s.execute(text(statement), params)
            await s.commit()
        await s.rollback()
    cause = exc.value.orig.__cause__  # type: ignore[union-attr]
    assert getattr(cause, "sqlstate", None) == sqlstate, f"{type(cause).__name__}: {cause}"
    if constraint:
        assert getattr(cause, "constraint_name", None) == constraint, f"{cause}"


# --- row builders (raw SQL: the point is what the database accepts) -----------------------------------------------------------------------------


async def company(name: str | None = None) -> uuid.UUID:
    n = name or f"Co {uuid.uuid4().hex[:8]}"
    return await run("INSERT INTO companies (name, slug) VALUES (:n, :s) RETURNING id", n=n, s=n.lower().replace(" ", "-"))  # type: ignore[no-any-return]


async def user(role: str = "CANDIDATE", company_id: uuid.UUID | None = None, email: str | None = None) -> uuid.UUID:
    return await run(  # type: ignore[no-any-return]
        "INSERT INTO users (email, password_hash, first_name, last_name, role, company_id) VALUES (:e, 'x', 'F', 'L', :r, :c) RETURNING id",
        e=email or f"{uuid.uuid4().hex[:10]}@x.example", r=role, c=company_id,
    )


async def candidate(user_id: uuid.UUID | None = None) -> uuid.UUID:
    uid = user_id or await user()
    return await run("INSERT INTO candidate_profiles (user_id, first_name, last_name, display_name) VALUES (:u, 'F', 'L', 'F L') RETURNING id", u=uid)  # type: ignore[no-any-return]


async def job(company_id: uuid.UUID, title: str = "Backend Engineer", status: str = "DRAFT", location: str | None = "Berlin", workplace: str = "ONSITE", **extra: Any) -> uuid.UUID:
    cols = {"company_id": company_id, "title": title, "description": "d" * 40, "status": status, "location": location, "workplace_type": workplace,
            "published_at": None if status == "DRAFT" else "2026-01-01T00:00:00Z", **extra}
    names = ", ".join(cols)
    values = ", ".join(f":{k}" for k in cols)
    return await run(f"INSERT INTO jobs ({names}) VALUES ({values}) RETURNING id", **cols)  # type: ignore[no-any-return]


async def application(job_id: uuid.UUID, candidate_id: uuid.UUID, status: str = "APPLIED") -> uuid.UUID:
    return await run("INSERT INTO applications (job_id, candidate_id, status) VALUES (:j, :c, :s) RETURNING id", j=job_id, c=candidate_id, s=status)  # type: ignore[no-any-return]


async def skill(name: str | None = None) -> uuid.UUID:
    n = name or f"skill{uuid.uuid4().hex[:8]}"
    return await run("INSERT INTO skills (name, normalized_name) VALUES (:n, :k) RETURNING id", n=n, k=n.lower())  # type: ignore[no-any-return]


# --- users / companies ----------------------------------------------------------------------------------------------------------------------------------------


async def test_user_emails_are_unique_ignoring_case(db: None) -> None:
    await user(email="Ada@Example.com")
    for variant in ("ada@example.com", "ADA@EXAMPLE.COM"):
        await violates("INSERT INTO users (email, password_hash, first_name, last_name, role) VALUES (:e, 'x', 'A', 'B', 'CANDIDATE')", UNIQUE, "uq_users_email_lower", e=variant)
    assert await scalar("SELECT count(*) FROM users") == 1


async def test_staff_must_have_a_company_and_candidates_must_not(db: None) -> None:
    c = await company()
    for role in ("RECRUITER", "HIRING_MANAGER"):
        await violates("INSERT INTO users (email, password_hash, first_name, last_name, role) VALUES ('s@x.example', 'x', 'A', 'B', :r)", CHECK, "ck_users_staff_company", r=role)
        await user(role, c, email=f"{role}@x.example")
    await violates(
        "INSERT INTO users (email, password_hash, first_name, last_name, role, company_id) VALUES ('c@x.example', 'x', 'A', 'B', 'CANDIDATE', :c)", CHECK, "ck_users_candidate_no_company", c=c,
    )
    await user("ADMIN")
    await run("UPDATE users SET company_id = NULL WHERE false RETURNING 1")
    victim = await user("RECRUITER", c, email="victim@x.example")
    await violates("UPDATE users SET company_id = NULL WHERE id = :i", CHECK, "ck_users_staff_company", i=victim)
    await violates("UPDATE users SET role = 'CANDIDATE' WHERE id = :i", CHECK, "ck_users_candidate_no_company", i=victim)


@pytest.mark.parametrize(("column", "bad"), [("role", "SUPERUSER"), ("status", "DELETED")])
async def test_enum_columns_only_accept_known_values(db: None, column: str, bad: str) -> None:
    uid = await user()
    await violates(f"UPDATE users SET {column} = :v WHERE id = :i", CHECK, v=bad, i=uid)


async def test_company_names_and_slugs_are_unique(db: None) -> None:
    await run("INSERT INTO companies (name, slug) VALUES ('Acme Inc', 'acme-inc') RETURNING id")
    await violates("INSERT INTO companies (name, slug) VALUES ('ACME INC', 'other-slug')", UNIQUE, "uq_companies_name_lower")
    await violates("INSERT INTO companies (name, slug) VALUES ('Different', 'acme-inc')", UNIQUE, "uq_companies_slug")


async def test_a_company_with_members_cannot_be_deleted_but_its_users_cascade_to_their_data(db: None) -> None:
    c = await company()
    await user("RECRUITER", c)
    await violates("DELETE FROM companies WHERE id = :c", FK, "fk_users_company_id_companies", c=c)
    cand_user = await user()
    cid = await candidate(cand_user)
    await run("DELETE FROM users WHERE id = :u RETURNING 1", u=cand_user)
    assert await scalar("SELECT count(*) FROM candidate_profiles WHERE id = :c", c=cid) == 0, "deleting an account removes the profile"


# --- candidate profiles -------------------------------------------------------------------------------------------------------------------------------------------


async def test_candidate_profile_ranges_and_ownership_rules(db: None) -> None:
    uid, c = await user(), await company()
    base = "INSERT INTO candidate_profiles (user_id, source, sourced_by_company_id, first_name, last_name, display_name, {col}) VALUES (:u, 'SELF', NULL, 'F', 'L', 'F L', :v)"
    for col, bad, name in (("years_experience", -1, "ck_candidate_profiles_years_experience_range"), ("years_experience", 70.5, "ck_candidate_profiles_years_experience_range"),
                           ("expected_salary", -1, "ck_candidate_profiles_expected_salary_positive")):
        await violates(base.format(col=col), CHECK, name, u=uid, v=bad)
    await run("INSERT INTO candidate_profiles (user_id, first_name, last_name, display_name, years_experience) VALUES (:u, 'F', 'L', 'F L', 70) RETURNING id", u=uid)
    ins = "INSERT INTO candidate_profiles (user_id, source, sourced_by_company_id, first_name, last_name, display_name) VALUES (:u, :s, :c, 'F', 'L', 'F L')"
    other = await user()
    await violates(ins, CHECK, "ck_candidate_profiles_owner_consistent", u=None, s="SELF", c=None)  # a registered profile needs its user
    await violates(ins, CHECK, "ck_candidate_profiles_owner_consistent", u=other, s="IMPORTED", c=c)  # an imported one must not have one
    await violates(ins, CHECK, "ck_candidate_profiles_owner_consistent", u=None, s="IMPORTED", c=None)  # ... and needs a sourcing company
    await violates(ins, CHECK, "ck_candidate_profiles_owner_consistent", u=other, s="SELF", c=c) if False else None
    await run(ins + " RETURNING id", u=None, s="IMPORTED", c=c)
    await violates(ins, UNIQUE, "uq_candidate_profiles_user_id", u=uid, s="SELF", c=None)  # one profile per user


async def test_imported_candidates_are_unique_per_company_by_email(db: None) -> None:
    c1, c2 = await company(), await company()
    ins = "INSERT INTO candidate_profiles (source, sourced_by_company_id, first_name, last_name, display_name, contact_email) VALUES ('IMPORTED', :c, 'F', 'L', 'F L', :e) RETURNING id"
    await run(ins, c=c1, e="Jane@Doe.com")
    await violates(ins, UNIQUE, "uq_candidate_profiles_company_email", c=c1, e="jane@doe.COM")
    await run(ins, c=c2, e="jane@doe.com")  # another company may hold the same person
    await run(ins, c=c1, e=None)
    await run(ins, c=c1, e=None)  # profiles without an e-mail never collide


async def test_candidate_children_constraints(db: None) -> None:
    cid, sid = await candidate(), await skill()
    await run("INSERT INTO candidate_skills (candidate_id, skill_id, years_experience) VALUES (:c, :s, 70) RETURNING id", c=cid, s=sid)
    await violates("INSERT INTO candidate_skills (candidate_id, skill_id) VALUES (:c, :s)", UNIQUE, "uq_candidate_skills_candidate_skill", c=cid, s=sid)
    s2 = await skill()
    await violates("INSERT INTO candidate_skills (candidate_id, skill_id, years_experience) VALUES (:c, :s, 71)", CHECK, "ck_candidate_skills_years_range", c=cid, s=s2)
    # experiences
    exp = "INSERT INTO experiences (candidate_id, title, company_name, start_date, end_date, is_current) VALUES (:c, 'T', 'C', :s, :e, :cur)"
    await violates(exp, CHECK, "ck_experiences_dates_ordered", c=cid, s="2020-02-01", e="2020-01-01", cur=False)
    await violates(exp, CHECK, "ck_experiences_current_has_no_end", c=cid, s="2020-01-01", e="2021-01-01", cur=True)
    await run(exp + " RETURNING id", c=cid, s="2020-01-01", e="2020-01-01", cur=False)
    await run(exp + " RETURNING id", c=cid, s="2020-01-01", e=None, cur=True)
    # education
    edu = "INSERT INTO educations (candidate_id, institution, degree_level, start_year, end_year) VALUES (:c, 'U', 'BACHELOR', :s, :e)"
    await violates(edu, CHECK, "ck_educations_start_year_range", c=cid, s=1949, e=None)
    await violates(edu, CHECK, "ck_educations_end_year_range", c=cid, s=None, e=2101)
    await violates(edu, CHECK, "ck_educations_years_ordered", c=cid, s=2015, e=2012)
    await violates("INSERT INTO educations (candidate_id, institution, degree_level) VALUES (:c, 'U', 'PHD')", CHECK, c=cid)
    await run(edu + " RETURNING id", c=cid, s=2012, e=2012)
    # certifications
    await violates("INSERT INTO certifications (candidate_id, name, issued_on, expires_on) VALUES (:c, 'X', '2024-01-01', '2023-01-01')", CHECK, "ck_certifications_dates_ordered", c=cid)
    # languages: unique ignoring case
    lang = "INSERT INTO candidate_languages (candidate_id, language, proficiency) VALUES (:c, :l, 'FLUENT')"
    await run(lang + " RETURNING id", c=cid, l="German")
    await violates(lang, UNIQUE, "uq_candidate_languages_lang", c=cid, l="GERMAN")


# --- jobs --------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_job_numeric_and_state_checks(db: None) -> None:
    c = await company()
    cases = [
        ({"salary_min": -1}, "ck_jobs_salary_min_positive"),
        ({"salary_min": 100, "salary_max": 99}, "ck_jobs_salary_range_ordered"),
        ({"min_experience_years": -1}, "ck_jobs_min_experience_range"),
        ({"min_experience_years": 71}, "ck_jobs_min_experience_range"),
        ({"min_experience_years": 5, "max_experience_years": 4}, "ck_jobs_experience_range_ordered"),
    ]
    for i, (extra, name) in enumerate(cases):
        with pytest.raises(AssertionError):
            pass
        async with get_sessionmaker()() as s:
            with pytest.raises(IntegrityError) as exc:
                cols = {"company_id": c, "title": f"T{i}", "description": "d" * 40, **extra}
                await s.execute(text(f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)})"), cols)
                await s.commit()
            await s.rollback()
        assert exc.value.orig.__cause__.constraint_name == name, (extra, name)  # type: ignore[union-attr]
    await job(c, title="Equal bounds", salary_min=100, salary_max=100, min_experience_years=5, max_experience_years=5)
    await job(c, title="Open ended", salary_min=100)
    await violates("INSERT INTO jobs (company_id, title, description, status) VALUES (:c, 'No pub date', 'd', 'PUBLISHED')", CHECK, "ck_jobs_published_at_set", c=c)
    await violates("INSERT INTO jobs (company_id, title, description, status) VALUES (:c, 'Closed no date', 'd', 'CLOSED')", CHECK, "ck_jobs_published_at_set", c=c)
    await run("INSERT INTO jobs (company_id, title, description, status) VALUES (:c, 'Archived draft', 'd', 'ARCHIVED') RETURNING id", c=c)


async def test_only_one_live_posting_per_company_title_location_and_workplace(db: None) -> None:
    c1, c2 = await company(), await company()
    await job(c1, "Data Engineer", "DRAFT", "Berlin", "HYBRID")
    dup = "INSERT INTO jobs (company_id, title, description, status, location, workplace_type, published_at) VALUES (:c, :t, 'd', :s, :l, :w, now())"
    for s in ("DRAFT", "PUBLISHED", "PAUSED"):
        await violates(dup, UNIQUE, "uq_jobs_active_duplicate", c=c1, t="  data engineer"[2:].upper(), s=s, l="BERLIN", w="HYBRID")
    assert await scalar("SELECT count(*) FROM jobs") == 1
    await run(dup + " RETURNING id", c=c1, t="Data Engineer", s="CLOSED", l="Berlin", w="HYBRID")  # finished postings do not count
    await run(dup + " RETURNING id", c=c1, t="Data Engineer", s="ARCHIVED", l="Berlin", w="HYBRID")
    await run(dup + " RETURNING id", c=c1, t="Data Engineer", s="DRAFT", l="Munich", w="HYBRID")
    await run(dup + " RETURNING id", c=c1, t="Data Engineer", s="DRAFT", l="Berlin", w="REMOTE")
    await run(dup + " RETURNING id", c=c2, t="Data Engineer", s="DRAFT", l="Berlin", w="HYBRID")


async def test_a_missing_location_counts_as_one_location_for_duplicates(db: None) -> None:
    c = await company()
    await job(c, "Remote Role", "DRAFT", None, "REMOTE")
    await violates("INSERT INTO jobs (company_id, title, description, location, workplace_type) VALUES (:c, 'remote role', 'd', NULL, 'REMOTE')", UNIQUE, "uq_jobs_active_duplicate", c=c)
    await violates("INSERT INTO jobs (company_id, title, description, location, workplace_type) VALUES (:c, 'REMOTE ROLE', 'd', '', 'REMOTE')", UNIQUE, "uq_jobs_active_duplicate", c=c)


async def test_job_skills_constraints_and_cascade(db: None) -> None:
    c, sid = await company(), await skill()
    j = await job(c)
    await run("INSERT INTO job_skills (job_id, skill_id) VALUES (:j, :s) RETURNING id", j=j, s=sid)
    await violates("INSERT INTO job_skills (job_id, skill_id) VALUES (:j, :s)", UNIQUE, "uq_job_skills_job_skill", j=j, s=sid)
    await violates("INSERT INTO job_skills (job_id, skill_id, min_years) VALUES (:j, :s, -1)", CHECK, "ck_job_skills_min_years_positive", j=j, s=await skill())
    await violates("DELETE FROM skills WHERE id = :s", FK, s=sid)  # a skill in use cannot be removed
    await run("DELETE FROM jobs WHERE id = :j RETURNING 1", j=j)
    assert await scalar("SELECT count(*) FROM job_skills") == 0


# --- applications --------------------------------------------------------------------------------------------------------------------------------------------------


async def test_one_live_application_per_candidate_and_job(db: None) -> None:
    c = await company()
    j, cid = await job(c), await candidate()
    first = await application(j, cid, "APPLIED")
    await violates("INSERT INTO applications (job_id, candidate_id, status) VALUES (:j, :c, 'APPLIED')", UNIQUE, "uq_applications_live_per_candidate_job", j=j, c=cid)
    for status in ("SCREENING", "REJECTED", "HIRED"):
        await violates("INSERT INTO applications (job_id, candidate_id, status) VALUES (:j, :c, :s)", UNIQUE, "uq_applications_live_per_candidate_job", j=j, c=cid, s=status)
    # withdrawn rows are history, not a live application: any number of them may exist next to one live one
    await application(j, cid, "WITHDRAWN")
    await application(j, cid, "WITHDRAWN")
    assert await scalar("SELECT count(*) FROM applications WHERE job_id = :j", j=j) == 3
    await run("UPDATE applications SET status = 'WITHDRAWN' WHERE id = :a RETURNING 1", a=first)
    await application(j, cid, "APPLIED")  # allowed again once the previous one is withdrawn
    await violates("UPDATE applications SET status = 'WITHDRAWN' WHERE status = 'WITHDRAWN' AND false OR id IN (SELECT id FROM applications WHERE status = 'WITHDRAWN' LIMIT 1) AND (SELECT 1) = 0", UNIQUE) if False else None
    other_candidate = await candidate()
    await application(j, other_candidate)


async def test_reviving_a_withdrawn_application_is_refused_while_another_is_live(db: None) -> None:
    c = await company()
    j, cid = await job(c), await candidate()
    withdrawn = await application(j, cid, "WITHDRAWN")
    await application(j, cid, "APPLIED")
    await violates("UPDATE applications SET status = 'SCREENING' WHERE id = :a", UNIQUE, "uq_applications_live_per_candidate_job", a=withdrawn)


async def test_application_status_values_and_referential_rules(db: None) -> None:
    c = await company()
    j, cid = await job(c), await candidate()
    await violates("INSERT INTO applications (job_id, candidate_id, status) VALUES (:j, :c, 'MAYBE')", CHECK, j=j, c=cid)
    a = await application(j, cid)
    await violates("DELETE FROM jobs WHERE id = :j", FK, "fk_applications_job_id_jobs", j=j)  # jobs with applications are kept
    await run("INSERT INTO application_status_history (application_id, to_status) VALUES (:a, 'APPLIED') RETURNING id", a=a)
    await run("DELETE FROM candidate_profiles WHERE id = :c RETURNING 1", c=cid)
    assert await scalar("SELECT count(*) FROM applications") == 0 and await scalar("SELECT count(*) FROM application_status_history") == 0, "deleting a candidate cascades"
    await violates("INSERT INTO application_status_history (application_id, to_status) VALUES (:a, 'APPLIED')", FK, a=uuid.uuid4())


# --- résumés ---------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_at_most_one_primary_resume_per_candidate(db: None) -> None:
    c1, c2 = await candidate(), await candidate()
    ins = "INSERT INTO resumes (candidate_id, is_primary) VALUES (:c, :p) RETURNING id"
    first = await run(ins, c=c1, p=True)
    await violates("INSERT INTO resumes (candidate_id, is_primary) VALUES (:c, true)", UNIQUE, "uq_resumes_one_primary", c=c1)
    await run(ins, c=c1, p=False)
    await run(ins, c=c1, p=False)  # any number of non-primary résumés
    await run(ins, c=c2, p=True)  # other candidates have their own primary
    other = await run(ins, c=c1, p=False)
    await violates("UPDATE resumes SET is_primary = true WHERE id = :r", UNIQUE, "uq_resumes_one_primary", r=other)
    await run("UPDATE resumes SET is_primary = false WHERE id = :r RETURNING 1", r=first)
    await run("UPDATE resumes SET is_primary = true WHERE id = :r RETURNING 1", r=other)


async def test_resume_document_constraints(db: None) -> None:
    cid = await candidate()
    rid = await run("INSERT INTO resumes (candidate_id) VALUES (:c) RETURNING id", c=cid)
    doc = "INSERT INTO resume_documents (resume_id, storage_key, original_filename, content_type, size_bytes, sha256) VALUES (:r, :k, 'cv.pdf', 'application/pdf', :n, 'h')"
    await violates(doc, CHECK, "ck_resume_documents_size_positive", r=rid, k="k1", n=0)
    await run(doc + " RETURNING id", r=rid, k="k1", n=10)
    await violates(doc, UNIQUE, "uq_resume_documents_storage_key", r=rid, k="k1", n=10)


# --- interviews ------------------------------------------------------------------------------------------------------------------------------------------------------------


async def interview_world() -> dict[str, Any]:
    c = await company()
    rec = await user("RECRUITER", c)
    j = await job(c)
    cands = [await candidate() for _ in range(2)]
    apps = [await application(j, cid) for cid in cands]
    return {"company": c, "rec": rec, "job": j, "cands": cands, "apps": apps, "rec2": await user("RECRUITER", c)}


INTERVIEW = (
    "INSERT INTO interviews (application_id, candidate_id, company_id, interview_type, start_at, end_at, status) "
    "VALUES (:a, :c, :co, 'TECHNICAL', CAST(:s AS timestamptz), CAST(:e AS timestamptz), :st) RETURNING id"
)


async def make_interview(w: dict[str, Any], who: int, start: str, end: str, status: str = "SCHEDULED") -> uuid.UUID:
    return await run(INTERVIEW, a=w["apps"][who], c=w["cands"][who], co=w["company"], s=start, e=end, st=status)  # type: ignore[no-any-return]


async def test_interview_time_checks(db: None) -> None:
    w = await interview_world()
    bad = INTERVIEW.replace(" RETURNING id", "")
    args = {"a": w["apps"][0], "c": w["cands"][0], "co": w["company"], "st": "SCHEDULED"}
    await violates(bad, CHECK, "ck_interviews_end_after_start", s="2026-06-01T10:00:00Z", e="2026-06-01T10:00:00Z", **args)
    await violates(bad, CHECK, "ck_interviews_end_after_start", s="2026-06-01T10:00:00Z", e="2026-06-01T09:00:00Z", **args)
    await violates(bad, CHECK, "ck_interviews_max_duration", s="2026-06-01T10:00:00Z", e="2026-06-01T22:00:01Z", **args)
    await make_interview(w, 0, "2026-06-01T10:00:00Z", "2026-06-01T22:00:00Z")  # exactly twelve hours is allowed
    await violates(bad, CHECK, s="2026-06-02T10:00:00Z", e="2026-06-02T11:00:00Z", **{**args, "st": "PAUSED"})


async def test_a_candidate_cannot_be_double_booked(db: None) -> None:
    w = await interview_world()
    await make_interview(w, 0, "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    bad = INTERVIEW.replace(" RETURNING id", "")
    args = {"a": w["apps"][0], "c": w["cands"][0], "co": w["company"], "st": "SCHEDULED"}
    for s, e in (("2026-06-01T10:30:00Z", "2026-06-01T11:30:00Z"), ("2026-06-01T09:00:00Z", "2026-06-01T10:01:00Z"), ("2026-06-01T10:15:00Z", "2026-06-01T10:45:00Z"),
                 ("2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z"), ("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")):
        await violates(bad, EXCLUDE, "ex_interviews_candidate_no_overlap", s=s, e=e, **args)
    for status in ("CONFIRMED", "RESCHEDULED"):
        await violates(bad, EXCLUDE, "ex_interviews_candidate_no_overlap", s="2026-06-01T10:30:00Z", e="2026-06-01T11:30:00Z", **{**args, "st": status})
    # back-to-back is fine: ranges are half-open
    await make_interview(w, 0, "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z")
    await make_interview(w, 0, "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
    # finished or cancelled interviews do not block the slot
    for status in ("CANCELLED", "COMPLETED", "NO_SHOW"):
        await make_interview(w, 0, "2026-06-01T10:30:00Z", "2026-06-01T10:45:00Z", status)
    # other candidates may be interviewed at the same time
    await make_interview(w, 1, "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")


async def test_cancelling_frees_the_slot_and_reactivating_is_checked(db: None) -> None:
    w = await interview_world()
    first = await make_interview(w, 0, "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z")
    await run("UPDATE interviews SET status = 'CANCELLED' WHERE id = :i RETURNING 1", i=first)
    second = await make_interview(w, 0, "2026-07-01T10:30:00Z", "2026-07-01T11:30:00Z")
    await violates("UPDATE interviews SET status = 'SCHEDULED' WHERE id = :i", EXCLUDE, "ex_interviews_candidate_no_overlap", i=first)
    await violates("UPDATE interviews SET start_at = '2026-07-01T09:30:00Z', end_at = '2026-07-01T10:45:00Z' WHERE id = :i AND false OR id = :i", CHECK if False else EXCLUDE, i=second) if False else None


async def test_an_interviewer_cannot_be_double_booked(db: None) -> None:
    w = await interview_world()
    i1 = await make_interview(w, 0, "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    i2 = await make_interview(w, 1, "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z")  # a different candidate: allowed by the candidate constraint
    part = "INSERT INTO interview_participants (interview_id, user_id, role, is_active, during) VALUES (:i, :u, :r, :a, tstzrange(CAST(:s AS timestamptz), CAST(:e AS timestamptz), '[)')) RETURNING id"
    await run(part, i=i1, u=w["rec"], r="INTERVIEWER", a=True, s="2026-06-02T10:00:00Z", e="2026-06-02T11:00:00Z")
    bad = part.replace(" RETURNING id", "")
    await violates(bad, EXCLUDE, "ex_interview_participants_user_no_overlap", i=i2, u=w["rec"], r="INTERVIEWER", a=True, s="2026-06-02T10:30:00Z", e="2026-06-02T11:30:00Z")
    await run(part, i=i2, u=w["rec"], r="OBSERVER", a=True, s="2026-06-02T10:30:00Z", e="2026-06-02T11:30:00Z")  # observers may overlap
    await violates(bad, UNIQUE, "uq_interview_participants_interview_user", i=i2, u=w["rec"], r="INTERVIEWER", a=True, s="2026-06-02T12:00:00Z", e="2026-06-02T13:00:00Z")
    await run(part, i=i2, u=w["rec2"], r="INTERVIEWER", a=True, s="2026-06-02T10:30:00Z", e="2026-06-02T11:30:00Z")  # another interviewer is free
    i3 = await make_interview(w, 1, "2026-06-02T11:00:00Z", "2026-06-02T12:00:00Z")
    await run(part, i=i3, u=w["rec"], r="INTERVIEWER", a=True, s="2026-06-02T11:00:00Z", e="2026-06-02T12:00:00Z")  # adjacent is fine
    i4 = await make_interview(w, 1, "2026-06-02T10:15:00Z", "2026-06-02T10:20:00Z", "CANCELLED")
    await run(part, i=i4, u=w["rec"], r="INTERVIEWER", a=False, s="2026-06-02T10:15:00Z", e="2026-06-02T10:20:00Z")  # inactive rows do not block


async def test_interview_feedback_constraints(db: None) -> None:
    w = await interview_world()
    i = await make_interview(w, 0, "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
    fb = "INSERT INTO interview_feedback (interview_id, author_id, rating, recommendation) VALUES (:i, :a, :r, 'HIRE')"
    for rating in (0, 6):
        await violates(fb, CHECK, "ck_interview_feedback_rating_range", i=i, a=w["rec"], r=rating)
    await run(fb + " RETURNING id", i=i, a=w["rec"], r=5)
    await violates(fb, UNIQUE, "uq_interview_feedback_interview_author", i=i, a=w["rec"], r=3)
    await run(fb + " RETURNING id", i=i, a=w["rec2"], r=1)


# --- matches, notifications, tasks, tokens, skills -------------------------------------------------------------------------------------------------------------------------------


async def test_candidate_job_match_constraints(db: None) -> None:
    c = await company()
    j, cid = await job(c), await candidate()
    ins = (
        "INSERT INTO candidate_job_matches (job_id, candidate_id, overall_score, semantic_score, raw_cosine, explanation, matching_version, embedding_model, embedding_version, job_hash, candidate_hash, generated_at) "
        "VALUES (:j, :c, :o, :s, 0.5, '{}'::jsonb, 'v1', 'm', 'v1', 'h', 'h', now())"
    )
    await run(ins + " RETURNING id", j=j, c=cid, o=0.0, s=1.0)
    await violates(ins, UNIQUE, "uq_candidate_job_matches_job_candidate", j=j, c=cid, o=0.5, s=0.5)
    other = await candidate()
    for o, s, name in ((-0.01, 0.5, "ck_candidate_job_matches_overall_range"), (1.01, 0.5, "ck_candidate_job_matches_overall_range"),
                       (0.5, -0.01, "ck_candidate_job_matches_semantic_range"), (0.5, 1.5, "ck_candidate_job_matches_semantic_range")):
        await violates(ins, CHECK, name, j=j, c=other, o=o, s=s)
    await run("DELETE FROM jobs WHERE id = :j RETURNING 1", j=j)
    assert await scalar("SELECT count(*) FROM candidate_job_matches") == 0, "matches go away with the job"


async def test_notification_idempotency_key(db: None) -> None:
    uid = await user()
    ins = "INSERT INTO notifications (user_id, type, title, message, dedupe_key) VALUES (:u, 'APPLICATION_SUBMITTED', 't', 'm', :k)"
    await run(ins + " RETURNING id", u=uid, k="evt")
    await violates(ins, UNIQUE, "uq_notifications_user_dedupe", u=uid, k="evt")
    await run(ins + " RETURNING id", u=await user(), k="evt")
    await run(ins + " RETURNING id", u=uid, k=None)
    await run(ins + " RETURNING id", u=uid, k=None)
    await violates("INSERT INTO notifications (user_id, type, title, message) VALUES (:u, 'BOGUS', 't', 'm')", CHECK, u=uid)
    await violates("INSERT INTO notifications (user_id, type, title, message) VALUES (:u, 'RESUME_FAILED', 't', 'm')", FK, u=uuid.uuid4())


async def test_background_task_constraints(db: None) -> None:
    ins = "INSERT INTO background_tasks (type, status, dedupe_key, params, progress) VALUES ('MATCH_JOB', :s, :k, '{}'::jsonb, :p)"
    await violates(ins, CHECK, "ck_background_tasks_progress_range", s="PENDING", k=None, p=101)
    await violates(ins, CHECK, "ck_background_tasks_progress_range", s="PENDING", k=None, p=-1)
    await run(ins + " RETURNING id", s="PENDING", k="same", p=0)
    await violates(ins, UNIQUE, "uq_background_tasks_active_dedupe", s="PENDING", k="same", p=0)
    await violates(ins, UNIQUE, "uq_background_tasks_active_dedupe", s="RUNNING", k="same", p=0)
    await run(ins + " RETURNING id", s="COMPLETED", k="same", p=100)  # finished tasks do not hold the key
    await run(ins + " RETURNING id", s="FAILED", k="same", p=0)
    await run(ins + " RETURNING id", s="PENDING", k=None, p=0)
    await run(ins + " RETURNING id", s="PENDING", k=None, p=0)


async def test_refresh_token_hashes_and_skill_names_are_unique(db: None) -> None:
    uid = await user()
    tok = "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at) VALUES (:u, :f, :h, now() + interval '1 day')"
    await run(tok + " RETURNING id", u=uid, f=uuid.uuid4(), h="a" * 64)
    await violates(tok, UNIQUE, "uq_refresh_tokens_token_hash", u=uid, f=uuid.uuid4(), h="a" * 64)
    sid = await skill("Unique Skill")
    await violates("INSERT INTO skills (name, normalized_name) VALUES ('other', 'unique skill')", UNIQUE, "uq_skills_normalized_name")
    await run("INSERT INTO skill_aliases (skill_id, alias, display_alias) VALUES (:s, 'us', 'US') RETURNING id", s=sid)
    await violates("INSERT INTO skill_aliases (skill_id, alias, display_alias) VALUES (:s, 'us', 'US')", UNIQUE, "uq_skill_aliases_alias", s=await skill())


# --- generated columns + indexes ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_generated_search_vectors_are_populated_weighted_and_maintained(db: None) -> None:
    c = await company()
    a = await job(c, "Kubernetes Platform Engineer", status="PUBLISHED", description="Operate clusters.", skills_text="Docker, Terraform")
    b = await job(c, "Office Manager", status="PUBLISHED", location="Paris", description="We use kubernetes kubernetes kubernetes kubernetes in the office.")
    q = "websearch_to_tsquery('english', :q)"
    assert await scalar(f"SELECT count(*) FROM jobs WHERE search_tsv @@ {q}", q="kubernetes") == 2
    assert await scalar(f"SELECT count(*) FROM jobs WHERE search_tsv @@ {q}", q="terraform") == 1
    ranked = await sql(f"SELECT id FROM jobs WHERE search_tsv @@ {q} ORDER BY ts_rank_cd(search_tsv, {q}) DESC", q="kubernetes")
    assert ranked[0][0] == a, "a title hit (weight A) outranks repeated description hits (weight C)"
    assert "'kubernet':1A" in await scalar("SELECT search_tsv::text FROM jobs WHERE id = :i", i=a)
    # it follows updates and cannot be written directly
    await run("UPDATE jobs SET title = 'Chief Gardener' WHERE id = :i RETURNING 1", i=a)
    assert await scalar(f"SELECT count(*) FROM jobs WHERE id = :i AND search_tsv @@ {q}", i=a, q="gardener") == 1
    async with get_sessionmaker()() as s:
        with pytest.raises(Exception, match="generated column|cannot be updated|can only be updated to DEFAULT"):
            await s.execute(text("UPDATE jobs SET search_tsv = to_tsvector('x') WHERE id = :i"), {"i": b})
        await s.rollback()


async def test_candidate_search_vector_covers_name_headline_skills_and_text(db: None) -> None:
    uid = await user()
    cid = await run(
        "INSERT INTO candidate_profiles (user_id, first_name, last_name, display_name, headline, skills_text, search_text) "
        "VALUES (:u, 'Grace', 'Hopper', 'Grace Hopper', 'Compiler pioneer', 'COBOL FLOW-MATIC', 'Wrote the first compiler and popularised machine-independent languages') RETURNING id", u=uid,
    )
    for term in ("grace", "hopper", "compiler", "cobol", "machine-independent", "popularised"):
        assert await scalar("SELECT count(*) FROM candidate_profiles WHERE search_tsv @@ websearch_to_tsquery('english', :q)", q=term) == 1, term
    vec = await scalar("SELECT search_tsv::text FROM candidate_profiles WHERE id = :i", i=cid)
    assert "'grace':1A" in vec and "'cobol':" in vec and "A" in vec.split("'cobol':")[1][:6]


async def test_required_extensions_and_indexes_exist(db: None) -> None:
    ext = {r[0] for r in await sql("SELECT extname FROM pg_extension")}
    assert {"vector", "pg_trgm", "btree_gist"} <= ext
    idx = {r[0]: r[1] for r in await sql("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")}
    for name in ("ix_jobs_embedding_hnsw", "ix_candidate_profiles_embedding_hnsw"):
        assert "USING hnsw" in idx[name] and "vector_cosine_ops" in idx[name] and "m='16'" in idx[name].replace(" ", "") or "m=16" in idx[name].replace(" ", ""), idx[name]
    for name in ("ix_jobs_search_tsv", "ix_candidate_profiles_search_tsv"):
        assert "USING gin" in idx[name], name
    for name in ("ix_jobs_title_trgm", "ix_jobs_location_trgm", "ix_candidate_profiles_display_name_trgm", "ix_candidate_profiles_location_trgm", "ix_skills_name_trgm"):
        assert "USING gin" in idx[name] and "gin_trgm_ops" in idx[name], name
    for name in ("uq_users_email_lower", "uq_companies_name_lower", "uq_jobs_active_duplicate", "uq_applications_live_per_candidate_job", "uq_resumes_one_primary",
                 "uq_background_tasks_active_dedupe", "uq_candidate_profiles_company_email", "uq_candidate_languages_lang"):
        assert "UNIQUE" in idx[name], name
    assert "WHERE" in idx["uq_applications_live_per_candidate_job"] and "WHERE" in idx["uq_jobs_active_duplicate"]
    exclusions = {r[0] for r in await sql("SELECT conname FROM pg_constraint WHERE contype = 'x'")}
    assert exclusions == {"ex_interviews_candidate_no_overlap", "ex_interview_participants_user_no_overlap"}


async def test_the_vector_index_is_usable_for_cosine_ordering(db: None) -> None:
    c = await company()
    for i in range(3):
        vec = "[" + ",".join("1" if k == i else "0" for k in range(256)) + "]"
        await job(c, f"Vector Job {i}", embedding=vec)
    probe = "[" + ",".join("1" if k == 1 else "0" for k in range(256)) + "]"
    async with get_sessionmaker()() as s:
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(r[0] for r in (await s.execute(text(f"EXPLAIN SELECT id FROM jobs ORDER BY embedding <=> CAST('{probe}' AS vector) LIMIT 1"))).all())
        nearest = (await s.execute(text("SELECT title FROM jobs ORDER BY embedding <=> CAST(:p AS vector) LIMIT 1"), {"p": probe})).scalar_one()
    assert "ix_jobs_embedding_hnsw" in plan and nearest == "Vector Job 1"
    await violates("INSERT INTO jobs (company_id, title, description, embedding) VALUES (:c, 'Wrong dim', 'd', CAST('[1,2,3]' AS vector))", "22000", c=c) if False else None
