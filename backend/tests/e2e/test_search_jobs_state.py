"""Job search behaviour that depends on state: visibility rules, sorting on mutated data, candidate personalisation, caching."""

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
    expire_deadline,
    fast_argon,
    seed_search_corpus,
    set_job_status,
    sql,
)

pytestmark = pytest.mark.e2e

SEARCH = f"{API}/search/jobs"


async def search(client: AsyncClient, who: dict[str, Any] | None = None, **params: Any) -> dict[str, Any]:
    r = await client.get(SEARCH, params=params, headers=who["h"] if who else None)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def titles(body: dict[str, Any]) -> list[str]:
    return [j["title"] for j in body["items"]]


async def test_posted_within_days(client: AsyncClient) -> None:
    c = await seed_search_corpus(client)
    await sql("UPDATE jobs SET published_at = now() - interval '10 days' WHERE id = :i", i=uuid.UUID(c["java"]["id"]))
    await sql("UPDATE jobs SET published_at = now() - interval '40 days' WHERE id = :i", i=uuid.UUID(c["nurse"]["id"]))
    assert (await search(client, posted_within_days=7))["total"] == 6
    assert (await search(client, posted_within_days=30))["total"] == 7
    assert (await search(client, posted_within_days=365))["total"] == 8
    assert "Senior Java Engineer" not in titles(await search(client, posted_within_days=7, page_size=100))




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
