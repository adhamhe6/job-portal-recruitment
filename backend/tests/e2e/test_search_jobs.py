"""Public job search: full-text relevance, fuzzy matching, filters, sorting, paging, visibility and caching."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.cache.redis_cache import get_cache
from tests.helpers import create_job, fill_backend_profile, register_candidate, register_employer
from tests.helpers_spine import (  # noqa: F401
    API,
    apply_job,
    assert_error,
    expire_deadline,
    fast_argon,
    seed_search_corpus,
    set_job_status,
    sql,
    walk,
)

pytestmark = pytest.mark.e2e

SEARCH = f"{API}/search/jobs"


async def search(client: AsyncClient, who: dict[str, Any] | None = None, **params: Any) -> dict[str, Any]:
    r = await client.get(SEARCH, params=params, headers=who["h"] if who else None)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def titles(body: dict[str, Any]) -> list[str]:
    return [j["title"] for j in body["items"]]


async def ids_for(client: AsyncClient, corpus: dict[str, Any], **params: Any) -> set[str]:
    body = await search(client, page_size=100, **params)
    by_id = {corpus[k]["id"]: k for k in corpus if isinstance(corpus[k], dict) and "id" in corpus[k] and "status" in corpus[k]}
    return {by_id[j["id"]] for j in body["items"]}


# --- keyword relevance ---------------------------------------------------------------------------------------------------------------------


async def test_title_match_outranks_description_match(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    body = await search(client, q="python")
    assert titles(body)[0] == "Python Developer", titles(body)
    assert "Office Manager" in titles(body), "description-only matches are still found"
    assert titles(body).index("Python Developer") < titles(body).index("Office Manager")
    assert c["python"]["id"] == body["items"][0]["id"]


async def test_skills_are_searchable_keywords(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, q="kubernetes") == {"devops"}
    assert await ids_for(client, c, q="spring boot") == {"java"}


async def test_typos_are_tolerated_on_titles(client: AsyncClient) -> None:
    await seed_search_corpus(client)
    assert titles(await search(client, q="pyton developr"))[0] == "Python Developer"
    assert "Senior Java Engineer" in titles(await search(client, q="senor java enginer"))
    assert titles(await search(client, q="qwertyuiop zxcvbnm"))== []


async def test_stemming_and_websearch_syntax(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert "python" in await ids_for(client, c, q="developers")  # "Developer" stems to the same lexeme
    assert "python" in await ids_for(client, c, q='"python developer"')
    without = await ids_for(client, c, q="engineer -java")
    assert "java" not in without and "devops" in without
    either = await ids_for(client, c, q="nurse or analyst")
    assert {"nurse", "analyst"} <= either


@pytest.mark.parametrize("q", ["'", '"', "&", "|", "!", "(", ")", ":*", "a:b", "\\", "%", "_", "<->", "' OR 1=1 --", "; DROP TABLE jobs;", "\x00x", "😀", "a" * 200])
async def test_hostile_or_odd_queries_never_error(client: AsyncClient, q: str) -> None:
    await seed_search_corpus(client)
    r = await client.get(SEARCH, params={"q": q})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert set(r.json()) == {"items", "page", "page_size", "total", "pages"}


async def test_blank_query_is_no_query(client: AsyncClient) -> None:
    await seed_search_corpus(client)
    assert (await search(client, q="   "))["total"] == 8
    assert (await search(client, q=""))["total"] == 8


# --- filters ------------------------------------------------------------------------------------------------------------------------------------


async def test_skill_filters_by_id_any_and_all(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    ids = {n: (await client.get(f"{API}/skills", params={"q": n})).json()["items"][0]["id"] for n in ("Python", "Docker", "Django")}
    anyp = await ids_for(client, c, skill_id=[ids["Python"]])
    assert anyp == {"python", "devops"}, "required and preferred skills both count"
    any2 = await ids_for(client, c, skill_id=[ids["Docker"], ids["Django"]], skills_mode="any")
    assert any2 == {"python", "devops"}
    all2 = await ids_for(client, c, skill_id=[ids["Python"], ids["Docker"]], skills_mode="all")
    assert all2 == {"devops"}
    assert await ids_for(client, c, skill_id=[ids["Django"], ids["Docker"]], skills_mode="all") == set()
    assert await ids_for(client, c, skill_id=[str(uuid.uuid4())]) == set()


async def test_skill_filters_by_name_and_alias(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, skill=["python"]) == {"python", "devops"}
    assert await ids_for(client, c, skill=["k8s"]) == {"devops"}  # alias
    assert await ids_for(client, c, skill=["Python", "kubernetes"], skills_mode="all") == {"devops"}
    assert await ids_for(client, c, skill=["Python", "kubernetes"], skills_mode="any") == {"python", "devops"}
    # an unknown name can never be satisfied by "all" ...
    assert await ids_for(client, c, skill=["Python", "No Such Skill"], skills_mode="all") == set()
    assert (await search(client, skill=["No Such Skill"], skills_mode="all"))["items"] == []
    # ... and an "any" over only-unknown names matches nothing rather than silently dropping the filter
    assert (await search(client, skill=["No Such Skill"], skills_mode="any"))["total"] == 0
    assert await ids_for(client, c, skill=["No Such Skill", "Kubernetes"], skills_mode="any") == {"devops"}
    # names and ids combine
    pid = (await client.get(f"{API}/skills", params={"q": "Docker"})).json()["items"][0]["id"]
    assert await ids_for(client, c, skill_id=[pid], skill=["Kubernetes"], skills_mode="all") == {"devops"}


async def test_location_filter_is_a_case_insensitive_substring(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, location="berlin") == {"python", "analyst"}
    assert await ids_for(client, c, location="GERMANY") == {"python", "java", "frontend", "analyst", "nurse"}
    assert await ids_for(client, c, location="  hamburg  ") == {"frontend", "nurse"}
    assert await ids_for(client, c, location="atlantis") == set()


@pytest.mark.parametrize(("needle", "expected"), [("%", {"pct"}), ("100%", {"pct"}), ("_", {"pct"}), ("Remote_Work", {"pct"}), ("%%", set()), ("_erlin", set()), ("B%n", set()), ("\\", set())])
async def test_location_wildcards_are_literal(client: AsyncClient, needle: str, expected: set[str]) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, location=needle) == expected


async def test_enum_filters_are_multi_select(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, employment_type="INTERNSHIP") == {"analyst"}
    assert await ids_for(client, c, employment_type=["INTERNSHIP", "PART_TIME"]) == {"analyst", "frontend"}
    assert await ids_for(client, c, workplace_type=["REMOTE"]) == {"python", "devops", "pct"}
    assert await ids_for(client, c, workplace_type=["REMOTE", "HYBRID"]) == {"python", "devops", "pct", "java"}
    assert await ids_for(client, c, experience_level=["SENIOR", "ENTRY"]) == {"java", "devops", "analyst", "pct"}
    assert await ids_for(client, c, employment_type="CONTRACT", workplace_type="ONSITE") == {"office"}, "different filters combine with AND"


async def test_max_experience_filters_on_the_required_minimum(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, max_experience=0) == {"frontend", "analyst", "pct"}
    assert await ids_for(client, c, max_experience=2) == {"frontend", "analyst", "pct", "python", "nurse"}
    assert await ids_for(client, c, max_experience=6) == {"python", "java", "frontend", "analyst", "office", "nurse", "devops", "pct"}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"salary_min": 85000}, {"java", "devops", "analyst", "nurse"}),   # jobs whose range reaches 85k; open-ended ranges count, jobs without any pay info do not
        ({"salary_max": 35000}, {"frontend", "pct", "nurse", "devops", "python"} - {"python"}),
        ({"salary_min": 50000, "salary_max": 60000}, {"python", "office", "nurse", "devops"}),
        ({"salary_min": 120000}, {"java", "nurse"}),
        ({"salary_min": 120001}, {"nurse"}),
        ({"salary_max": 20000}, {"pct", "devops", "nurse"} - {"nurse"}),
        ({"salary_min": 0}, {"python", "java", "frontend", "office", "nurse", "devops", "pct"}),
    ],
)
async def test_salary_range_overlap(client: AsyncClient, params: dict[str, Any], expected: set[str]) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, **params) == expected, params


async def test_posted_within_days(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    await sql("UPDATE jobs SET published_at = now() - interval '10 days' WHERE id = :i", i=uuid.UUID(c["java"]["id"]))
    await sql("UPDATE jobs SET published_at = now() - interval '40 days' WHERE id = :i", i=uuid.UUID(c["nurse"]["id"]))
    assert (await search(client, posted_within_days=7))["total"] == 6
    assert (await search(client, posted_within_days=30))["total"] == 7
    assert (await search(client, posted_within_days=365))["total"] == 8
    assert "Senior Java Engineer" not in titles(await search(client, posted_within_days=7, page_size=100))


async def test_company_filter(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, company_id=c["rec1"]["company_id"]) == {"python", "java", "frontend", "analyst"}
    assert await ids_for(client, c, company_id=c["rec2"]["company_id"]) == {"office", "nurse", "devops", "pct"}
    assert (await search(client, company_id=str(uuid.uuid4())))["total"] == 0


async def test_filters_combine_with_the_keyword_query(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    assert await ids_for(client, c, q="engineer", workplace_type="REMOTE") == {"devops"}
    assert await ids_for(client, c, q="python", employment_type="FULL_TIME", location="berlin") == {"python"}


# --- visibility -------------------------------------------------------------------------------------------------------------------------------------------


async def test_only_published_and_still_open_jobs_are_listed(client: AsyncClient) -> None:
    rec = await register_employer(client)
    live = await create_job(client, rec, title="Live Role", publish=True)
    hidden = {}
    for status in ("DRAFT", "PAUSED", "CLOSED", "ARCHIVED"):
        hidden[status] = await create_job(client, rec, title=f"{status.title()} Role")
        await set_job_status(hidden[status]["id"], status)
    expired = await create_job(client, rec, title="Expired Role", publish=True)
    await expire_deadline(expired["id"])
    today = await create_job(client, rec, title="Deadline Today Role", publish=True)
    await expire_deadline(today["id"], days_ago=0)
    body = await search(client, page_size=100)
    assert sorted(titles(body)) == ["Deadline Today Role", "Live Role"], titles(body)
    assert {j["status"] for j in body["items"]} == {"PUBLISHED"}
    assert (await search(client, q="role"))["total"] == 2
    assert live["id"] in {j["id"] for j in body["items"]}


async def test_items_have_a_stable_public_shape(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    item = (await search(client, q="python developer"))["items"][0]
    assert set(item) == {
        "id", "title", "company_id", "company_name", "company_logo_url", "department", "location", "employment_type", "workplace_type", "experience_level",
        "min_experience_years", "salary_min", "salary_max", "salary_currency", "skills", "status", "published_at", "application_deadline", "created_at", "updated_at",
        "is_saved", "has_applied", "match_score", "application_count",
    }
    assert item["company_name"] == "Alpine Software" and item["skills"] == ["Django", "Python"], "only required skills, alphabetically"
    assert item["is_saved"] is None and item["has_applied"] is None and item["match_score"] is None and item["application_count"] is None
    assert not {"description", "created_by_id", "hiring_manager_id", "embedding"} & {k for k, _ in walk(item)}
    assert c["python"]["id"] == item["id"]


# --- sorting ------------------------------------------------------------------------------------------------------------------------------------------------


async def test_sorts(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    order = ["python", "java", "frontend", "analyst", "office", "nurse", "devops", "pct"]  # publication order
    for i, key in enumerate(order):
        await sql("UPDATE jobs SET published_at = now() - make_interval(days => :d) WHERE id = :i", d=len(order) - i, i=uuid.UUID(c[key]["id"]))
    newest = [j["id"] for j in (await search(client, sort="newest", page_size=100))["items"]]
    assert newest == [c[k]["id"] for k in reversed(order)]
    title_sorted = titles(await search(client, sort="title", page_size=100))
    assert title_sorted == sorted(title_sorted, key=str.lower)
    desc = (await search(client, sort="salary_desc", page_size=100))["items"]
    tops = [j["salary_max"] or j["salary_min"] for j in desc]
    known = [float(t) for t in tops if t is not None]
    assert known == sorted(known, reverse=True) and tops[-1] is None, "unknown salaries sort last"
    asc = (await search(client, sort="salary_asc", page_size=100))["items"]
    lows = [j["salary_min"] or j["salary_max"] for j in asc]
    known = [float(t) for t in lows if t is not None]
    assert known == sorted(known) and lows[-1] is None
    # deadline: sooner first, jobs without a deadline last
    await sql("UPDATE jobs SET application_deadline = NULL")
    await sql("UPDATE jobs SET application_deadline = current_date + 3 WHERE id = :i", i=uuid.UUID(c["java"]["id"]))
    await sql("UPDATE jobs SET application_deadline = current_date + 9 WHERE id = :i", i=uuid.UUID(c["python"]["id"]))
    dl = [j["id"] for j in (await search(client, sort="deadline", page_size=100))["items"]]
    assert dl[:2] == [c["java"]["id"], c["python"]["id"]]


async def test_relevance_without_a_query_falls_back_to_newest_and_match_needs_a_candidate(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    await sql("UPDATE jobs SET published_at = now() - interval '5 days' WHERE id = :i", i=uuid.UUID(c["python"]["id"]))
    base = [j["id"] for j in (await search(client, sort="newest"))["items"]]
    assert [j["id"] for j in (await search(client, sort="relevance"))["items"]] == base
    assert [j["id"] for j in (await search(client, sort="match"))["items"]] == base, "anonymous callers have no match scores"
    assert base[-1] == c["python"]["id"]


async def test_sort_by_match_for_a_signed_in_candidate(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand, years=4)  # Python/PostgreSQL/Docker/Redis backend profile
    body = await search(client, cand, sort="match", page_size=100)
    scores = [j["match_score"] for j in body["items"]]
    known = [s for s in scores if s is not None]
    assert known and known == sorted(known, reverse=True), scores
    assert body["items"][0]["id"] in {c["python"]["id"], c["devops"]["id"]}, "the best match is a backend-ish job"
    assert scores.index(None) >= len(known) if None in scores else True, "unscored jobs sort last"
    assert titles(body)[-1] in {"ICU Nurse", "Sales Representative 100% Commission", "Junior Frontend Developer", "Office Manager", "Data Analyst Intern"}


async def test_ties_are_broken_deterministically(client: AsyncClient) -> None:
    await seed_search_corpus(client)
    first = [j["id"] for j in (await search(client, q="engineer", sort="relevance", page_size=100))["items"]]
    for _ in range(3):
        assert [j["id"] for j in (await search(client, q="engineer", sort="relevance", page_size=100))["items"]] == first


# --- pagination ---------------------------------------------------------------------------------------------------------------------------------------------------


async def test_pagination_envelope(client: AsyncClient) -> None:
    await seed_search_corpus(client)
    p1 = await search(client, page_size=3)
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"], len(p1["items"])) == (1, 3, 8, 3, 3)
    p3 = await search(client, page_size=3, page=3)
    assert len(p3["items"]) == 2 and p3["page"] == 3
    beyond = await search(client, page_size=3, page=4)
    assert beyond["items"] == [] and beyond["total"] == 8 and beyond["pages"] == 3
    exact = await search(client, page_size=4)
    assert exact["pages"] == 2 and len(exact["items"]) == 4
    seen = [j["id"] for p in (1, 2, 3) for j in (await search(client, page_size=3, page=p))["items"]]
    assert len(seen) == len(set(seen)) == 8, "no row is skipped or repeated across pages"
    empty = await search(client, q="qqqqqqqq")
    assert (empty["items"], empty["total"], empty["pages"]) == ([], 0, 0)
    assert (await search(client, page_size=100))["page_size"] == 100


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0}, {"page": -1}, {"page": "x"}, {"page": 100001}, {"page_size": 0}, {"page_size": 101}, {"employment_type": "SLAVERY"}, {"workplace_type": "MOON"},
        {"experience_level": "GOD"}, {"sort": "random"}, {"skills_mode": "some"}, {"posted_within_days": 0}, {"posted_within_days": 366}, {"max_experience": -1},
        {"max_experience": 71}, {"salary_min": -1}, {"company_id": "nope"}, {"skill_id": "nope"}, {"q": "x" * 201}, {"location": "x" * 101},
    ],
)
async def test_invalid_parameters_get_the_standard_422(client: AsyncClient, params: dict[str, Any]) -> None:
    err = assert_error(await client.get(SEARCH, params=params), 422, "VALIDATION_ERROR")
    assert err["details"] and all({"field", "message", "type"} <= set(d) for d in err["details"])


async def test_inverted_salary_range_is_rejected(client: AsyncClient) -> None:
    err = assert_error(await client.get(SEARCH, params={"salary_min": 90000, "salary_max": 50000}), 422, "INVALID_SALARY_RANGE")
    assert "salary_min" in err["message"]
    assert (await client.get(SEARCH, params={"salary_min": 50000, "salary_max": 50000})).status_code == 200


# --- caching ---------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_identical_anonymous_queries_are_served_from_cache_until_jobs_change(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    cache = get_cache()
    hits, misses = cache.hits, cache.misses
    first = await search(client, q="python")
    assert (cache.hits, cache.misses) == (hits, misses + 1)
    second = await search(client, q="python")
    assert second == first and (cache.hits, cache.misses) == (hits + 1, misses + 1)
    # a different query is a different entry
    await search(client, q="java")
    assert cache.misses == misses + 2
    # pagination parameters are part of the key
    assert (await search(client, q="python", page_size=1))["page_size"] == 1
    # editing a job invalidates the namespace
    await client.patch(f"{API}/jobs/{c['python']['id']}", headers=c["rec1"]["h"], json={"title": "Python Wizard"})
    after = await search(client, q="python")
    assert "Python Wizard" in titles(after) and "Python Developer" not in titles(after)


async def test_publishing_and_closing_invalidate_the_cache(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec)
    assert (await search(client, q="backend"))["total"] == 0
    assert (await search(client, q="backend"))["total"] == 0  # cached
    await client.post(f"{API}/jobs/{job['id']}/publish", headers=rec["h"])
    assert (await search(client, q="backend"))["total"] == 1
    assert (await search(client, q="backend"))["total"] == 1  # cached
    await client.post(f"{API}/jobs/{job['id']}/close", headers=rec["h"])
    assert (await search(client, q="backend"))["total"] == 0


async def test_company_changes_invalidate_cached_listings(client: AsyncClient) -> None:
    rec = await register_employer(client, "Old Name Ltd")
    await create_job(client, rec, publish=True)
    assert (await search(client))["items"][0]["company_name"] == "Old Name Ltd"
    await client.patch(f"{API}/companies/{rec['company_id']}", headers=rec["h"], json={"name": "New Name Ltd"})
    assert (await search(client))["items"][0]["company_name"] == "New Name Ltd"


async def test_personalised_results_are_never_shared_through_the_cache(client: AsyncClient) -> None:
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand, other = await register_candidate(client), await register_candidate(client)
    anon_first = await search(client)
    await client.put(f"{API}/jobs/{job['id']}/save", headers=cand["h"])
    await apply_job(client, cand, job["id"])
    mine = (await search(client, cand))["items"][0]
    assert (mine["is_saved"], mine["has_applied"]) == (True, True)
    # the personalised answer neither leaked into the shared entry ...
    anon_again = (await search(client))["items"][0]
    assert anon_again["is_saved"] is None and anon_again["has_applied"] is None and anon_first["items"][0]["is_saved"] is None
    # ... nor is it served to a different candidate
    theirs = (await search(client, other))["items"][0]
    assert (theirs["is_saved"], theirs["has_applied"]) == (False, False)
    # and a candidate query does not touch the shared cache counters
    cache = get_cache()
    before = (cache.hits, cache.misses)
    await search(client, cand)
    assert (cache.hits, cache.misses) == before


async def test_search_fails_open_without_a_cache(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_search_corpus(client)
    monkeypatch.setattr(get_cache(), "enabled", False)
    assert (await search(client))["total"] == 8
    assert (await search(client, q="python"))["items"][0]["title"] == "Python Developer"
