"""Recruiter candidate search over a shared, read-only world: visibility, full-text, filters, ranking, paging, RBAC."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import add_staff, create_admin, create_job, register_candidate, register_employer
from tests.helpers_spine import (
    API,
    apply_job,
    assert_error,
    insert_imported_candidate,
    shared_world,
    sql,
    walk,
)

pytestmark = pytest.mark.e2e

SEARCH = f"{API}/search/candidates"
ME = f"{API}/candidates/me"


async def build(
    client: AsyncClient,
    key: str,
    first: str,
    last: str,
    *,
    headline: str,
    summary: str,
    location: str,
    years: float,
    skills: list[str],
    remote: str | None = None,
    availability: str | None = None,
    education: str | None = None,
    cert: str | None = None,
    searchable: bool = True,
    title: str | None = None,
) -> dict[str, Any]:
    cand = await register_candidate(client, first=first, last=last)
    h = cand["h"]
    body: dict[str, Any] = {
        "headline": headline,
        "summary": summary,
        "location": location,
        "years_experience": years,
        "is_searchable": searchable,
    }
    if remote:
        body["remote_preference"] = remote
    if availability:
        body["availability"] = availability
    assert (await client.patch(ME, headers=h, json=body)).status_code == 200
    for name in skills:
        assert (await client.post(f"{ME}/skills", headers=h, json={"name": name})).status_code == 201
    if education:
        await client.post(
            f"{ME}/educations",
            headers=h,
            json={"institution": "University", "degree_level": education, "field_of_study": "Studies"},
        )
    if cert:
        await client.post(f"{ME}/certifications", headers=h, json={"name": cert})
    if title:
        await client.post(
            f"{ME}/experiences",
            headers=h,
            json={
                "title": title,
                "company_name": "Somewhere",
                "start_date": "2018-01-01",
                "is_current": True,
            },
        )
    cand["key"] = key
    return cand


async def build_world(client: AsyncClient) -> dict[str, Any]:
    rec_a, rec_b = (
        await register_employer(client, "Search Co A"),
        await register_employer(client, "Search Co B"),
    )
    w: dict[str, Any] = {"rec_a": rec_a, "rec_b": rec_b}
    w["alex"] = await build(
        client,
        "alex",
        "Alex",
        "Backend",
        headline="Backend engineer",
        summary="Builds Python services with FastAPI and PostgreSQL.",
        location="Berlin, Germany",
        years=5,
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        remote="HYBRID",
        availability="TWO_WEEKS",
        education="BACHELOR",
        cert="AWS Certified Developer",
        title="Senior Backend Engineer",
    )
    w["bianca"] = await build(
        client,
        "bianca",
        "Bianca",
        "Frontend",
        headline="Frontend engineer",
        summary="Crafts responsive React interfaces with TypeScript.",
        location="Berlin, Germany",
        years=3,
        skills=["React", "TypeScript", "CSS"],
        remote="REMOTE",
        availability="IMMEDIATELY",
        education="MASTER",
        title="Frontend Developer",
    )
    w["chen"] = await build(
        client,
        "chen",
        "Chen",
        "Learner",
        headline="Machine learning engineer",
        summary="Trains PyTorch models for search ranking.",
        location="Munich, Germany",
        years=8,
        skills=["Python", "PyTorch", "Machine Learning"],
        remote="FLEXIBLE",
        availability="ONE_MONTH",
        education="DOCTORATE",
        title="Research Scientist",
    )
    w["julia"] = await build(
        client,
        "julia",
        "Julia",
        "Nurse",
        headline="ICU nurse",
        summary="Intensive care nursing with patient care focus.",
        location="Hamburg, Germany",
        years=6,
        skills=["Critical Care", "BLS"],
        remote="ONSITE",
        availability="THREE_MONTHS",
        education="HIGH_SCHOOL",
        title="ICU Nurse",
    )
    w["hidden"] = await build(
        client,
        "hidden",
        "Hidden",
        "Opted",
        headline="Backend developer",
        summary="Python and PostgreSQL developer, not on the marketplace.",
        location="Berlin, Germany",
        years=4,
        skills=["Python", "PostgreSQL"],
        searchable=False,
    )
    w["applicant_a"] = await build(
        client,
        "applicant_a",
        "Anna",
        "ApplicantA",
        headline="Python developer",
        summary="Applied to company A.",
        location="Cologne, Germany",
        years=2,
        skills=["Python"],
        searchable=False,
    )
    w["applicant_b"] = await build(
        client,
        "applicant_b",
        "Bruno",
        "ApplicantB",
        headline="Python developer",
        summary="Applied to company B.",
        location="Cologne, Germany",
        years=2,
        skills=["Python"],
        searchable=False,
    )
    job_a = await create_job(client, rec_a, publish=True)
    job_b = await create_job(client, rec_b, publish=True, title="Platform Engineer")
    await apply_job(client, w["applicant_a"], job_a["id"])
    await apply_job(client, w["alex"], job_a["id"])
    await apply_job(client, w["applicant_b"], job_b["id"])
    w["job_a"], w["job_b"] = job_a, job_b
    w["imported_a"] = await insert_imported_candidate(
        rec_a["company_id"],
        name="Ines ImportedA",
        email="ines@a.example",
        skills="Python PostgreSQL",
        headline="Imported backend dev",
    )
    w["imported_b"] = await insert_imported_candidate(
        rec_b["company_id"],
        name="Ivan ImportedB",
        email="ivan@b.example",
        skills="Python PostgreSQL",
        headline="Imported backend dev",
    )
    # a processed primary résumé for Alex whose text contains a rare word
    resume_id, doc_id = uuid.uuid4(), uuid.uuid4()
    cid = uuid.UUID(w["alex"]["candidate_id"])
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (:r, :c, 'PROCESSED', true)",
        r=resume_id,
        c=cid,
    )
    await sql(
        "INSERT INTO resume_documents (id, resume_id, storage_key, original_filename, content_type, size_bytes, sha256) VALUES (:d, :r, :k, 'cv.pdf', 'application/pdf', 10, :h)",
        d=doc_id,
        r=resume_id,
        k=f"k-{doc_id}",
        h="0" * 64,
    )
    await sql(
        "INSERT INTO resume_processing_results (resume_id, document_id, status, extracted_text) VALUES (:r, :d, 'COMPLETED', :t)",
        r=resume_id,
        d=doc_id,
        t="Led the Zanzibar migration programme and mentored junior engineers.",
    )
    await client.patch(
        ME, headers=w["alex"]["h"], json={"headline": "Backend engineer"}
    )  # triggers an index refresh that picks the résumé up
    return w


@pytest.fixture(scope="module")
async def _world(migrated_db: None, seeded_ontology: None):  # type: ignore[no-untyped-def]
    async with shared_world(build_world) as world:
        yield world


@pytest.fixture
def client(_world):  # type: ignore[no-untyped-def]  # overrides the per-test fixture: no database reset between these read-only tests
    return _world[0]


@pytest.fixture
def w(_world):  # type: ignore[no-untyped-def]
    return _world[1]


async def run(client: AsyncClient, who: dict[str, Any], **params: Any) -> dict[str, Any]:
    r = await client.get(SEARCH, params=params, headers=who["h"])
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def names(body: dict[str, Any]) -> set[str]:
    return {i["display_name"].split()[0] for i in body["items"]}


MARKETPLACE = {"Alex", "Bianca", "Chen", "Julia"}


# --- visibility ---------------------------------------------------------------------------------------------------------------------------------


async def test_each_company_sees_marketplace_plus_its_own_applicants_and_imports(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    a = await run(client, w["rec_a"], page_size=100)
    b = await run(client, w["rec_b"], page_size=100)
    assert names(a) == MARKETPLACE | {"Anna", "Ines"}
    assert names(b) == MARKETPLACE | {"Bruno", "Ivan"}
    for hidden in ("Hidden",):
        assert hidden not in names(a) | names(b), "opted-out candidates without a relationship are invisible"


async def test_access_level_in_list_rows(client: AsyncClient, w: dict[str, Any]) -> None:
    items = {i["display_name"].split()[0]: i for i in (await run(client, w["rec_a"], page_size=100))["items"]}
    assert items["Alex"]["access"] == "FULL" and items["Alex"]["has_applied"] is False, (
        "Alex applied to company A's job"
    )
    assert (
        items["Anna"]["access"] == "FULL"
        and items["Ines"]["access"] == "FULL"
        and items["Ines"]["source"] == "IMPORTED"
    )
    assert (
        items["Bianca"]["access"] == "PROFILE"
        and items["Chen"]["access"] == "PROFILE"
        and items["Bianca"]["source"] == "SELF"
    )


async def test_admin_sees_every_candidate(client: AsyncClient, w: dict[str, Any]) -> None:
    admin = await create_admin_cached(client)
    body = await run(client, admin, page_size=100)
    assert names(body) == MARKETPLACE | {"Hidden", "Anna", "Bruno", "Ines", "Ivan"}
    assert {i["access"] for i in body["items"]} == {"FULL"}
    assert w


_ADMIN: dict[str, Any] = {}


async def create_admin_cached(client: AsyncClient) -> dict[str, Any]:
    if not _ADMIN:
        _ADMIN.update(await create_admin(client))
    return _ADMIN


async def test_contact_details_never_appear_in_list_items(client: AsyncClient, w: dict[str, Any]) -> None:
    r = await client.get(SEARCH, params={"page_size": 100}, headers=w["rec_a"]["h"])
    text = r.text
    assert "@" not in text and "170 0000000" not in text
    keys = {k for k, _ in walk(r.json())}
    assert not keys & {
        "email",
        "phone",
        "contact_email",
        "contact_phone",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "expected_salary",
        "summary",
    }
    assert set(r.json()["items"][0]) == {
        "id",
        "display_name",
        "headline",
        "location",
        "years_experience",
        "availability",
        "remote_preference",
        "source",
        "access",
        "top_skills",
        "skill_matches",
        "match_score",
        "match_band",
        "has_applied",
        "updated_at",
    }


# --- full text -------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("fastapi", {"Alex"}),  # skills
        ("react", {"Bianca"}),
        ("pytorch", {"Chen"}),
        ("python", {"Alex", "Chen", "Anna", "Ines"}),
        ("nurse", {"Julia"}),  # headline
        ("senior backend engineer", {"Alex"}),  # recent job title (summary text)
        ("zanzibar", {"Alex"}),  # résumé text
        ("intensive care", {"Julia"}),  # summary
        ("alex", {"Alex"}),  # name
        ("alex backnd", {"Alex"}),  # typo, name-sized query
        ("python -react", {"Alex", "Chen", "Anna", "Ines"}),
        ("python -pytorch", {"Alex", "Anna", "Ines"}),
        ("fastapi or pytorch", {"Alex", "Chen"}),
        ("qwertyzzz", set()),
    ],
)
async def test_keyword_search(client: AsyncClient, w: dict[str, Any], q: str, expected: set[str]) -> None:
    assert names(await run(client, w["rec_a"], q=q, page_size=100)) == expected


async def test_relevance_ranks_the_name_and_skill_hits_first(client: AsyncClient, w: dict[str, Any]) -> None:
    body = await run(client, w["rec_a"], q="python", sort="relevance", page_size=100)
    assert body["items"][0]["display_name"].split()[0] in {"Alex", "Chen", "Anna", "Ines"}
    assert (await run(client, w["rec_a"], q="alex"))["items"][0]["display_name"] == "Alex Backend"


async def test_hostile_queries_are_harmless(client: AsyncClient, w: dict[str, Any]) -> None:
    for q in ("'", '"', "&|!", "% _ \\", "'; DROP TABLE candidate_profiles; --", "😀", "x" * 200):
        r = await client.get(SEARCH, params={"q": q}, headers=w["rec_a"]["h"])
        assert r.status_code == 200, (q, r.text)
    assert_error(
        await client.get(SEARCH, params={"q": "\x00"}, headers=w["rec_a"]["h"]), 422, "VALIDATION_ERROR"
    )


# --- filters -----------------------------------------------------------------------------------------------------------------------------------------


async def test_skill_filters(client: AsyncClient, w: dict[str, Any]) -> None:
    rec = w["rec_a"]
    assert names(await run(client, rec, skill=["python"], page_size=100)) == {"Alex", "Chen", "Anna"}, (
        "skills are matched on profile skills, not on imported free text"
    )
    assert names(await run(client, rec, skill=["Python", "PostgreSQL"], page_size=100)) == {"Alex"}, (
        "default mode is ALL"
    )
    assert names(await run(client, rec, skill=["React", "PyTorch"], skills_mode="any", page_size=100)) == {
        "Bianca",
        "Chen",
    }
    assert (
        names(await run(client, rec, skill=["React", "PyTorch"], skills_mode="all", page_size=100)) == set()
    )
    assert names(await run(client, rec, skill=["postgres"], page_size=100)) == {"Alex"}  # alias
    assert names(await run(client, rec, skill=["No Such Skill"], page_size=100)) == set()
    assert names(await run(client, rec, skill=["No Such Skill"], skills_mode="any", page_size=100)) == set()
    assert names(
        await run(client, rec, skill=["No Such Skill", "React"], skills_mode="any", page_size=100)
    ) == {"Bianca"}
    pid = (await client.get(f"{API}/skills", params={"q": "PyTorch"})).json()["items"][0]["id"]
    body = await run(client, rec, skill_id=[pid])
    assert names(body) == {"Chen"} and body["items"][0]["skill_matches"] == ["PyTorch"]
    both = await run(client, rec, skill=["Python"], skill_id=[pid], page_size=100)
    assert names(both) == {"Chen"}


async def test_top_skills_and_skill_matches(client: AsyncClient, w: dict[str, Any]) -> None:
    alex = next(i for i in (await run(client, w["rec_a"], skill=["fastapi", "docker"]))["items"])
    assert alex["top_skills"] == ["Docker", "FastAPI", "PostgreSQL", "Python", "Redis"] and alex[
        "skill_matches"
    ] == ["Docker", "FastAPI"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"min_experience": 5}, {"Alex", "Chen", "Julia", "Ines"}),
        ({"min_experience": 6.5}, {"Chen"}),
        ({"max_experience": 3}, {"Bianca", "Anna"}),
        ({"min_experience": 3, "max_experience": 5}, {"Alex", "Bianca"}),
        ({"min_experience": 100 // 2}, set()),
        ({"location": "berlin"}, {"Alex", "Bianca", "Ines"}),
        ({"location": "GERMANY"}, {"Alex", "Bianca", "Chen", "Julia", "Anna", "Ines"}),
        ({"location": "%"}, set()),
        ({"location": "_"}, set()),
        ({"min_education": "BACHELOR"}, {"Alex", "Bianca", "Chen"}),
        ({"min_education": "MASTER"}, {"Bianca", "Chen"}),
        ({"min_education": "DOCTORATE"}, {"Chen"}),
        ({"min_education": "HIGH_SCHOOL"}, {"Alex", "Bianca", "Chen", "Julia"}),
        ({"certification": "aws"}, {"Alex"}),
        ({"certification": "AWS Certified"}, {"Alex"}),
        ({"certification": "%"}, set()),
        ({"availability": "IMMEDIATELY"}, {"Bianca"}),
        ({"availability": ["IMMEDIATELY", "TWO_WEEKS"]}, {"Bianca", "Alex"}),
        ({"remote_preference": "REMOTE"}, {"Bianca"}),
        ({"remote_preference": ["REMOTE", "FLEXIBLE", "ONSITE"]}, {"Bianca", "Chen", "Julia"}),
        ({"skill": ["python"], "min_experience": 6}, {"Chen"}),
    ],
)
async def test_filters(
    client: AsyncClient, w: dict[str, Any], params: dict[str, Any], expected: set[str]
) -> None:
    assert names(await run(client, w["rec_a"], page_size=100, **params)) == expected, params


# --- job-aware ranking ------------------------------------------------------------------------------------------------------------------------------------


async def test_job_id_adds_match_scores_and_sorts_by_them(client: AsyncClient, w: dict[str, Any]) -> None:
    body = await run(client, w["rec_a"], job_id=w["job_a"]["id"], sort="match", page_size=100)
    scored = [
        (i["display_name"].split()[0], i["match_score"], i["match_band"], i["has_applied"])
        for i in body["items"]
    ]
    values = [s for _, s, _, _ in scored if s is not None]
    assert values == sorted(values, reverse=True) and scored[0][0] == "Alex" and scored[0][1] > 0.6
    assert [n for n, s, _, _ in scored if s is None] == [n for n, *_ in scored][len(values) :], (
        "unscored candidates sort last"
    )
    applied = {n for n, _, _, ap in scored if ap}
    assert applied == {"Alex", "Anna"}
    assert all(b in {"STRONG", "GOOD", "PARTIAL", "WEAK"} for _, s, b, _ in scored if s is not None)
    # the relevance default switches to the job's match ordering when there is no keyword
    default = await run(client, w["rec_a"], job_id=w["job_a"]["id"], page_size=100)
    assert [i["id"] for i in default["items"]] == [i["id"] for i in body["items"]]


async def test_min_match_score_and_applicants_only(client: AsyncClient, w: dict[str, Any]) -> None:
    rec, job = w["rec_a"], w["job_a"]["id"]
    full = await run(client, rec, job_id=job, page_size=100)
    top = max(i["match_score"] for i in full["items"] if i["match_score"] is not None)
    assert names(await run(client, rec, job_id=job, min_match_score=top - 0.0001, page_size=100)) == {"Alex"}
    strong = await run(client, rec, job_id=job, min_match_score=0.5, page_size=100)
    assert strong["total"] < full["total"] and all(i["match_score"] >= 0.5 for i in strong["items"])
    assert (await run(client, rec, job_id=job, min_match_score=1.0, page_size=100))["items"] == []
    assert names(await run(client, rec, job_id=job, applicants_only=True, page_size=100)) == {"Alex", "Anna"}
    assert names(await run(client, rec, applicants_only=True, page_size=100)) == names(
        await run(client, rec, page_size=100)
    ), "applicants_only needs a job_id"
    combined = await run(client, rec, job_id=job, applicants_only=True, q="python", page_size=100)
    assert names(combined) == {"Alex", "Anna"}


async def test_job_filter_requires_a_job_of_the_callers_company(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    assert_error(
        await client.get(SEARCH, params={"job_id": w["job_b"]["id"]}, headers=w["rec_a"]["h"]),
        404,
        "JOB_NOT_FOUND",
    )
    assert_error(
        await client.get(SEARCH, params={"job_id": str(uuid.uuid4())}, headers=w["rec_a"]["h"]),
        404,
        "JOB_NOT_FOUND",
    )
    assert (
        await client.get(SEARCH, params={"job_id": w["job_b"]["id"]}, headers=w["rec_b"]["h"])
    ).status_code == 200


# --- sorting + paging ----------------------------------------------------------------------------------------------------------------------------------------


async def test_sorts(client: AsyncClient, w: dict[str, Any]) -> None:
    rec = w["rec_a"]
    exp = [i["years_experience"] for i in (await run(client, rec, sort="experience", page_size=100))["items"]]
    assert [float(x) for x in exp] == sorted((float(x) for x in exp), reverse=True)
    by_name = [i["display_name"] for i in (await run(client, rec, sort="name", page_size=100))["items"]]
    assert by_name == sorted(by_name, key=str.lower)
    recent = (await run(client, rec, sort="recent", page_size=100))["items"]
    stamps = [i["updated_at"] for i in recent]
    assert stamps == sorted(stamps, reverse=True)
    assert [i["id"] for i in (await run(client, rec, sort="match", page_size=100))["items"]] == [
        i["id"] for i in (await run(client, rec, sort="recent", page_size=100))["items"]
    ]


async def test_pagination_envelope(client: AsyncClient, w: dict[str, Any]) -> None:
    rec = w["rec_a"]
    total = (await run(client, rec, page_size=100))["total"]
    assert total == 6
    p1 = await run(client, rec, page_size=4, page=1, sort="name")
    p2 = await run(client, rec, page_size=4, page=2, sort="name")
    p3 = await run(client, rec, page_size=4, page=3, sort="name")
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"], len(p1["items"])) == (1, 4, 6, 2, 4)
    assert len(p2["items"]) == 2 and p3["items"] == [] and p3["total"] == 6 and p3["pages"] == 2
    ids = [i["id"] for i in p1["items"] + p2["items"]]
    assert len(ids) == len(set(ids)) == 6
    empty = await run(client, rec, q="qwertyzzz")
    assert (empty["items"], empty["total"], empty["pages"]) == ([], 0, 0)


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"min_education": "PHD"},
        {"sort": "random"},
        {"min_match_score": 1.5},
        {"min_match_score": -0.1},
        {"skills_mode": "some"},
        {"availability": "SOMEDAY"},
        {"remote_preference": "ANYWHERE"},
        {"min_experience": -1},
        {"max_experience": 71},
        {"job_id": "nope"},
        {"skill_id": "nope"},
        {"q": "x" * 201},
        {"certification": "x" * 101},
        {"location": "x" * 101},
    ],
)
async def test_invalid_parameters_get_the_standard_422(
    client: AsyncClient, w: dict[str, Any], params: dict[str, Any]
) -> None:
    assert_error(await client.get(SEARCH, params=params, headers=w["rec_a"]["h"]), 422, "VALIDATION_ERROR")


async def test_inverted_experience_range(client: AsyncClient, w: dict[str, Any]) -> None:
    assert_error(
        await client.get(SEARCH, params={"min_experience": 8, "max_experience": 2}, headers=w["rec_a"]["h"]),
        422,
        "INVALID_EXPERIENCE_RANGE",
    )
    assert (
        await client.get(SEARCH, params={"min_experience": 5, "max_experience": 5}, headers=w["rec_a"]["h"])
    ).status_code == 200


# --- RBAC ------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_only_recruiters_and_admins_may_search_candidates(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    assert_error(await client.get(SEARCH, headers=w["alex"]["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(SEARCH), 401, "UNAUTHORIZED")
    assert_error(await client.get(SEARCH, headers={"Authorization": "Bearer nope"}), 401, "INVALID_TOKEN")


async def test_hiring_managers_cannot_search_candidates(client: AsyncClient, w: dict[str, Any]) -> None:
    hm = await add_staff(client, w["rec_a"], "HIRING_MANAGER", email="search.hm@test.example")
    assert_error(await client.get(SEARCH, headers=hm["h"]), 403, "FORBIDDEN")
