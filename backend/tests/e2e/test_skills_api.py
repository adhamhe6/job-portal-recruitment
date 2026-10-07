"""The skill taxonomy API: autocomplete, creation, administration and cache behaviour."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.cache.redis_cache import get_cache
from tests.helpers import add_staff, create_admin, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, fast_argon, scalar  # noqa: F401

pytestmark = pytest.mark.e2e


async def names(client: AsyncClient, **params: object) -> list[str]:
    r = await client.get(f"{API}/skills", params=params)
    assert r.status_code == 200, r.text
    return [s["name"] for s in r.json()["items"]]


async def skill_id(client: AsyncClient, name: str) -> str:
    r = await client.get(f"{API}/skills", params={"q": name, "page_size": 100})
    return next(s["id"] for s in r.json()["items"] if s["name"] == name)


# --- reading ---------------------------------------------------------------------------------------------------------------


async def test_list_is_public_paginated_and_alphabetical(client: AsyncClient) -> None:
    r = await client.get(f"{API}/skills", params={"page_size": 10})
    body = r.json()
    assert r.status_code == 200 and set(body) == {"items", "page", "page_size", "total", "pages"}
    assert body["total"] >= 150 and len(body["items"]) == 10 and body["pages"] == -(-body["total"] // 10)
    assert set(body["items"][0]) == {"id", "name", "category", "family", "is_verified"}
    listed = [s["name"] for s in body["items"]]
    assert listed == sorted(listed)
    p2 = (await client.get(f"{API}/skills", params={"page_size": 10, "page": 2})).json()["items"]
    assert not {s["id"] for s in p2} & {s["id"] for s in body["items"]}
    beyond = (await client.get(f"{API}/skills", params={"page": 9999, "page_size": 10})).json()
    assert beyond["items"] == [] and beyond["total"] == body["total"]


async def test_autocomplete_matches_names_and_aliases(client: AsyncClient) -> None:
    assert "PostgreSQL" in await names(client, q="postgres")  # alias "postgres" and substring of the name
    assert "PostgreSQL" in await names(client, q="psql")  # pure alias
    assert (await names(client, q="k8s")) == ["Kubernetes"]
    assert "Node.js" in await names(client, q="nodejs")  # spelling variants collapse
    assert "Node.js" in await names(client, q="node js")
    assert "C++" in await names(client, q="cpp")
    assert "CI/CD" in await names(client, q="ci cd")
    assert "Machine Learning" in await names(client, q="MACHINE")  # case-insensitive
    assert await names(client, q="zzzz-no-such-skill") == []


async def test_autocomplete_ranks_prefix_matches_first(client: AsyncClient) -> None:
    result = await names(client, q="java")
    assert result[0] == "Java" and result.index("JavaScript") < len(result)
    prefix = [n for n in result if n.lower().startswith("java")]
    assert result[: len(prefix)] == prefix, "prefix matches come before contains-matches"


async def test_autocomplete_treats_wildcards_and_punctuation_literally(client: AsyncClient) -> None:
    assert await names(client, q="%") == []
    assert await names(client, q="_") == []
    assert await names(client, q="\\") == []
    assert await names(client, q="...") == [], "punctuation-only input has an empty key and must not match every skill"
    assert await names(client, q="a%b") == []
    assert "Objective-C" in await names(client, q="objective-c")


async def test_category_filter(client: AsyncClient) -> None:
    dbs = await names(client, category="Databases", page_size=100)
    assert {"PostgreSQL", "MySQL", "Redis"} <= set(dbs) and "Python" not in dbs
    assert await names(client, category="Databases", q="postgres") == ["PostgreSQL"]
    assert await names(client, category="No Such Category") == []


async def test_list_parameter_validation(client: AsyncClient) -> None:
    for params in ({"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}, {"q": "x" * 61}):
        assert_error(await client.get(f"{API}/skills", params=params), 422, "VALIDATION_ERROR")


async def test_skill_detail_lists_aliases(client: AsyncClient) -> None:
    sid = await skill_id(client, "PostgreSQL")
    r = await client.get(f"{API}/skills/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "PostgreSQL" and body["family"] == "relational-database" and body["is_verified"] is True
    assert {"postgres", "psql"} <= set(body["aliases"]) and body["aliases"] == sorted(body["aliases"])
    assert_error(await client.get(f"{API}/skills/{uuid.uuid4()}"), 404, "SKILL_NOT_FOUND")
    assert_error(await client.get(f"{API}/skills/nope"), 422, "VALIDATION_ERROR")


# --- creating -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["candidate", "recruiter"])
async def test_candidates_and_recruiters_can_propose_new_skills(client: AsyncClient, role: str) -> None:
    actor = await (register_candidate(client) if role == "candidate" else register_employer(client))
    r = await client.post(f"{API}/skills", headers=actor["h"], json={"name": "  Quantum   Computing ", "category": "Science"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["name"], body["category"], body["is_verified"]) == ("Quantum Computing", "Science", False)
    assert "Quantum Computing" in await names(client, q="quantum")


async def test_hiring_managers_and_anonymous_users_cannot_create_skills(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    assert_error(await client.post(f"{API}/skills", headers=hm["h"], json={"name": "Underwater Basket Weaving"}), 403, "FORBIDDEN")
    assert_error(await client.post(f"{API}/skills", json={"name": "Underwater Basket Weaving"}), 401, "UNAUTHORIZED")
    assert await scalar("SELECT count(*) FROM skills WHERE NOT is_verified") == 0


@pytest.mark.parametrize("name", ["Python", "python", "  PYTHON ", "PYTHON3", "py", "postgres", "Postgre SQL", "node js", "Golang", "K8S"])
async def test_duplicates_and_aliases_are_rejected(client: AsyncClient, name: str) -> None:
    cand = await register_candidate(client)
    r = await client.post(f"{API}/skills", headers=cand["h"], json={"name": name})
    assert_error(r, 409, "SKILL_EXISTS")
    assert await scalar("SELECT count(*) FROM skills WHERE NOT is_verified") == 0


async def test_a_new_skill_cannot_be_created_twice_even_with_different_spelling(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    assert (await client.post(f"{API}/skills", headers=cand["h"], json={"name": "Foo-Bar.js"})).status_code == 201
    for variant in ("foo bar js", "FooBar.JS", "foo_bar_js"):
        assert_error(await client.post(f"{API}/skills", headers=cand["h"], json={"name": variant}), 409, "SKILL_EXISTS")


@pytest.mark.parametrize("payload", [{"name": ""}, {"name": "   "}, {"name": "x" * 101}, {}, {"name": "ok", "category": "c" * 51}])
async def test_create_validation(client: AsyncClient, payload: dict) -> None:
    cand = await register_candidate(client)
    assert_error(await client.post(f"{API}/skills", headers=cand["h"], json=payload), 422, "VALIDATION_ERROR")


async def test_punctuation_only_skill_names_are_rejected(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    assert_error(await client.post(f"{API}/skills", headers=cand["h"], json={"name": "..."}), 422, "INVALID_SKILL")


# --- administration ------------------------------------------------------------------------------------------------------------------


async def test_admin_edits_verifies_and_adds_aliases(client: AsyncClient) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    created = (await client.post(f"{API}/skills", headers=cand["h"], json={"name": "Rustlang Tooling"})).json()
    sid = created["id"]
    r = await client.patch(
        f"{API}/skills/{sid}", headers=admin["h"],
        json={"is_verified": True, "category": "Programming Languages", "family": "systems-programming", "add_aliases": ["Rust Tools", "rt-tooling"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_verified"] is True and body["category"] == "Programming Languages" and body["family"] == "systems-programming"
    assert body["aliases"] == ["Rust Tools", "rt-tooling"]
    # the alias now resolves: autocomplete finds it and adding it by alias lands on the canonical skill
    assert "Rustlang Tooling" in await names(client, q="rt tooling")
    added = await client.post(f"{API}/candidates/me/skills", headers=cand["h"], json={"name": "rust tools"})
    assert added.status_code == 201 and added.json()["skill"]["id"] == sid
    # renaming
    r = await client.patch(f"{API}/skills/{sid}", headers=admin["h"], json={"name": "Rust Tooling"})
    assert r.status_code == 200 and r.json()["name"] == "Rust Tooling"
    assert await names(client, q="rustlang tooling") == [] or "Rustlang Tooling" not in await names(client, q="rustlang tooling")


async def test_admin_edit_conflicts(client: AsyncClient) -> None:
    admin = await create_admin(client)
    py, pg = await skill_id(client, "Python"), await skill_id(client, "PostgreSQL")
    assert_error(await client.patch(f"{API}/skills/{py}", headers=admin["h"], json={"name": "PostgreSQL"}), 409, "SKILL_EXISTS")
    assert_error(await client.patch(f"{API}/skills/{py}", headers=admin["h"], json={"name": "postgres"}), 409, "SKILL_EXISTS")  # an alias of another skill
    assert_error(await client.patch(f"{API}/skills/{py}", headers=admin["h"], json={"add_aliases": ["psql"]}), 409, "SKILL_EXISTS")
    assert_error(await client.patch(f"{API}/skills/{uuid.uuid4()}", headers=admin["h"], json={"name": "X Y Z"}), 404, "SKILL_NOT_FOUND")
    assert_error(await client.patch(f"{API}/skills/{py}", headers=admin["h"], json={"add_aliases": ["a"] * 21}), 422, "VALIDATION_ERROR")
    # re-adding an alias that already points at this skill is harmless
    ok = await client.patch(f"{API}/skills/{pg}", headers=admin["h"], json={"add_aliases": ["Postgres"]})
    assert ok.status_code == 200 and ok.json()["aliases"].count("postgres") == 1
    assert (await client.get(f"{API}/skills/{py}")).json()["name"] == "Python"


async def test_only_admins_can_edit_skills(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    cand = await register_candidate(client)
    sid = await skill_id(client, "Python")
    for actor in (rec, hm, cand):
        assert_error(await client.patch(f"{API}/skills/{sid}", headers=actor["h"], json={"is_verified": False}), 403, "FORBIDDEN")
    assert_error(await client.patch(f"{API}/skills/{sid}", json={"is_verified": False}), 401, "UNAUTHORIZED")
    assert (await client.get(f"{API}/skills/{sid}")).json()["is_verified"] is True


# --- cache --------------------------------------------------------------------------------------------------------------------------------


async def test_list_is_cached_and_invalidated_by_changes(client: AsyncClient) -> None:
    admin = await create_admin(client)
    cand = await register_candidate(client)
    cache = get_cache()
    url, params = f"{API}/skills", {"q": "cache probe"}
    base_hits = cache.hits
    assert (await client.get(url, params=params)).json()["total"] == 0  # miss
    assert (await client.get(url, params=params)).json()["total"] == 0  # hit
    assert cache.hits == base_hits + 1
    # creating the skill bumps the namespace: the next read must see it
    created = (await client.post(f"{API}/skills", headers=cand["h"], json={"name": "Cache Probe Tool"})).json()
    after = (await client.get(url, params=params)).json()
    assert [s["name"] for s in after["items"]] == ["Cache Probe Tool"]
    assert (await client.get(url, params=params)).json() == after  # cached again, same payload
    # admin edits invalidate too
    await client.patch(f"{API}/skills/{created['id']}", headers=admin["h"], json={"name": "Cache Probe Renamed", "is_verified": True})
    renamed = (await client.get(url, params=params)).json()
    assert [(s["name"], s["is_verified"]) for s in renamed["items"]] == [("Cache Probe Renamed", True)]
    # different parameters never share an entry
    assert (await client.get(url, params={"q": "cache probe", "page_size": 1})).json()["page_size"] == 1
    assert (await client.get(url, params={"q": "cache probe", "page_size": 5})).json()["page_size"] == 5
