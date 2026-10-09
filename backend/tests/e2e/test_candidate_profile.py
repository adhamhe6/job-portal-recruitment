"""Candidate self-service: profile, completion, skills and the experience/education/certification/language sub-resources."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import add_staff, create_admin, fill_backend_profile, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, fast_argon, scalar, sql, tasks  # noqa: F401

pytestmark = pytest.mark.e2e

ME = f"{API}/candidates/me"


async def profile(client: AsyncClient, cand: dict[str, Any]) -> dict[str, Any]:
    r = await client.get(ME, headers=cand["h"])
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def completion(p: dict[str, Any]) -> dict[str, bool]:
    return {i["key"]: i["done"] for i in p["completion"]["items"]}


# --- reading + partial updates ---------------------------------------------------------------------------------------------------


async def test_new_profile_is_empty(client: AsyncClient) -> None:
    cand = await register_candidate(client, first="Ada", last="Lovelace")
    p = await profile(client, cand)
    assert (p["first_name"], p["last_name"], p["email"]) == ("Ada", "Lovelace", cand["email"])
    assert p["salary_currency"] == "USD" and p["is_searchable"] is True
    for empty in (
        "headline",
        "summary",
        "location",
        "years_experience",
        "remote_preference",
        "availability",
        "primary_resume",
    ):
        assert p[empty] is None
    for coll in ("skills", "experiences", "educations", "certifications", "languages"):
        assert p[coll] == []
    assert p["completion"]["percent"] == 0 and len(p["completion"]["missing"]) == 10
    assert [i["key"] for i in p["completion"]["items"]] == [
        "headline",
        "summary",
        "location",
        "years_experience",
        "skills",
        "experience",
        "education",
        "resume",
        "links",
        "preferences",
    ]
    assert sum(i["weight"] for i in p["completion"]["items"]) == 100


async def test_partial_update_changes_only_what_was_sent(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.patch(
        ME,
        headers=cand["h"],
        json={"headline": "Backend engineer", "location": "Berlin", "years_experience": 4.5},
    )
    assert r.status_code == 200
    r = await client.patch(
        ME, headers=cand["h"], json={"summary": "Builds reliable APIs and services for a living."}
    )
    p = r.json()
    assert (p["headline"], p["location"], p["years_experience"]) == ("Backend engineer", "Berlin", "4.5")
    assert p["summary"].startswith("Builds reliable")
    # an explicit null clears, an omitted field is untouched
    p = (await client.patch(ME, headers=cand["h"], json={"location": None})).json()
    assert p["location"] is None and p["headline"] == "Backend engineer"
    # an empty body changes nothing
    assert (await client.patch(ME, headers=cand["h"], json={})).json()["headline"] == "Backend engineer"
    # unknown fields are ignored, never applied
    p = (
        await client.patch(
            ME,
            headers=cand["h"],
            json={"user_id": str(uuid.uuid4()), "embedding": [1], "source": "IMPORTED", "skills_text": "x"},
        )
    ).json()
    assert p["headline"] == "Backend engineer"
    assert (
        await scalar(
            "SELECT source FROM candidate_profiles WHERE user_id = :u", u=uuid.UUID(cand["user"]["id"])
        )
        == "SELF"
    )


async def test_profile_enums_currency_and_flags(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.patch(
        ME,
        headers=cand["h"],
        json={
            "remote_preference": "FLEXIBLE",
            "employment_preference": "CONTRACT",
            "availability": "TWO_WEEKS",
            "expected_salary": "85000.50",
            "salary_currency": "eur",
            "portfolio_url": "https://me.example.com",
            "linkedin_url": "https://linkedin.com/in/me",
            "github_url": "https://github.com/me",
            "is_searchable": False,
        },
    )
    p = r.json()
    assert (p["remote_preference"], p["employment_preference"], p["availability"]) == (
        "FLEXIBLE",
        "CONTRACT",
        "TWO_WEEKS",
    )
    assert (p["expected_salary"], p["salary_currency"], p["is_searchable"]) == ("85000.50", "EUR", False)
    # nulls on non-nullable settings are ignored rather than violating constraints
    p = (
        await client.patch(ME, headers=cand["h"], json={"salary_currency": None, "is_searchable": None})
    ).json()
    assert p["salary_currency"] == "EUR" and p["is_searchable"] is False


async def test_profile_validation_errors(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    bad = {
        "years_experience": -1,
        "expected_salary": -10,
        "salary_currency": "EURO",
        "remote_preference": "ANYWHERE",
        "availability": "SOON",
        "portfolio_url": "javascript:alert(1)",
        "linkedin_url": "linkedin.com/in/me",
        "headline": "x" * 201,
        "phone": "abc",
        "is_searchable": "maybe",
    }
    err = assert_error(await client.patch(ME, headers=cand["h"], json=bad), 422, "VALIDATION_ERROR")
    assert {d["field"] for d in err["details"]} == set(bad)
    assert (await profile(client, cand))["headline"] is None, "a rejected update changes nothing"
    assert_error(
        await client.patch(ME, headers=cand["h"], json={"years_experience": 70.5}), 422, "VALIDATION_ERROR"
    )
    assert (await client.patch(ME, headers=cand["h"], json={"years_experience": 70})).status_code == 200


async def test_phone_is_kept_on_the_account(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    p = (await client.patch(ME, headers=cand["h"], json={"phone": "+49 170 1234567"})).json()
    assert p["phone"] == "+49 170 1234567"
    assert (await client.get(f"{API}/auth/me", headers=cand["h"])).json()["phone"] == "+49 170 1234567"
    assert (await client.patch(ME, headers=cand["h"], json={"phone": None})).json()["phone"] is None


# --- completion ------------------------------------------------------------------------------------------------------------------------------------


async def test_completion_arithmetic(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]

    async def pct() -> int:
        return (await client.get(f"{ME}/completion", headers=h)).json()["percent"]

    assert await pct() == 0
    await client.patch(ME, headers=h, json={"headline": "Engineer"})
    assert await pct() == 10
    await client.patch(ME, headers=h, json={"summary": "x" * 29})
    assert await pct() == 10, "a summary shorter than 30 characters does not count"
    await client.patch(ME, headers=h, json={"summary": "x" * 30})
    assert await pct() == 20
    await client.patch(ME, headers=h, json={"location": "Berlin", "years_experience": 0})
    assert await pct() == 30, "0 years is still an answer"
    for name in ("Python", "Docker"):
        await client.post(f"{ME}/skills", headers=h, json={"name": name})
    assert await pct() == 30, "fewer than three skills do not count"
    third = (await client.post(f"{ME}/skills", headers=h, json={"name": "Redis"})).json()
    assert await pct() == 50
    await client.post(
        f"{ME}/experiences",
        headers=h,
        json={"title": "Dev", "company_name": "Acme", "start_date": "2020-01-01"},
    )
    assert await pct() == 65
    await client.post(f"{ME}/educations", headers=h, json={"institution": "MIT", "degree_level": "BACHELOR"})
    assert await pct() == 75
    await client.patch(ME, headers=h, json={"github_url": "https://github.com/me"})
    assert await pct() == 80
    await client.patch(ME, headers=h, json={"employment_preference": "CONTRACT"})
    assert await pct() == 80, "employment preference alone is not counted"
    await client.patch(ME, headers=h, json={"availability": "IMMEDIATELY"})
    assert await pct() == 85
    # the résumé item needs a *processed primary* résumé
    cid = uuid.UUID((await profile(client, cand))["id"])
    rid = uuid.uuid4()
    await sql(
        "INSERT INTO resumes (id, candidate_id, status, is_primary) VALUES (:i, :c, 'UPLOADED', true)",
        i=rid,
        c=cid,
    )
    assert await pct() == 85
    await sql("UPDATE resumes SET status = 'PROCESSED' WHERE id = :i", i=rid)
    assert await pct() == 100
    full = await profile(client, cand)
    assert full["completion"]["missing"] == [] and all(completion(full).values())
    assert full["primary_resume"]["id"] == str(rid) and full["primary_resume"]["is_primary"] is True
    # removing a skill drops below three again
    await client.delete(f"{ME}/skills/{third['id']}", headers=h)
    assert await pct() == 80


async def test_only_confirmed_skills_count_towards_completion(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    cid = uuid.UUID((await profile(client, cand))["id"])
    ids = {
        n: await scalar("SELECT id FROM skills WHERE name = :n", n=n) for n in ("Python", "Docker", "Redis")
    }
    for sid in ids.values():
        await sql(
            "INSERT INTO candidate_skills (candidate_id, skill_id, source, status) VALUES (:c, :s, 'RESUME', 'SUGGESTED')",
            c=cid,
            s=sid,
        )
    p = await profile(client, cand)
    assert len(p["skills"]) == 3 and not completion(p)["skills"], (
        "parser suggestions are not the candidate's own claims yet"
    )
    item = next(s for s in p["skills"] if s["skill"]["name"] == "Python")
    assert item["status"] == "SUGGESTED" and item["source"] == "RESUME"
    for s in p["skills"]:
        r = await client.patch(f"{ME}/skills/{s['id']}", headers=cand["h"], json={"status": "CONFIRMED"})
        assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert completion(await profile(client, cand))["skills"] is True


# --- skills ---------------------------------------------------------------------------------------------------------------------------------------------


async def test_add_skill_by_name_alias_and_id(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    py = await client.post(
        f"{ME}/skills", headers=h, json={"name": "python", "proficiency": "EXPERT", "years_experience": 7.5}
    )
    assert py.status_code == 201, py.text
    assert (
        py.json()["skill"]["name"] == "Python"
        and py.json()["proficiency"] == "EXPERT"
        and py.json()["years_experience"] == "7.5"
    )
    assert (py.json()["source"], py.json()["status"]) == ("USER", "CONFIRMED")
    pg = await client.post(f"{ME}/skills", headers=h, json={"name": "Postgres"})  # alias → canonical
    assert pg.status_code == 201 and pg.json()["skill"]["name"] == "PostgreSQL"
    docker_id = await scalar("SELECT id FROM skills WHERE name = 'Docker'")
    dk = await client.post(f"{ME}/skills", headers=h, json={"skill_id": str(docker_id)})
    assert (
        dk.status_code == 201 and dk.json()["skill"]["name"] == "Docker" and dk.json()["proficiency"] is None
    )
    names = [s["skill"]["name"] for s in (await profile(client, cand))["skills"]]
    assert names == ["Docker", "PostgreSQL", "Python"], "returned sorted by name"


async def test_unknown_skill_names_create_unverified_skills(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    r = await client.post(f"{ME}/skills", headers=cand["h"], json={"name": "  Underwater   Welding "})
    assert (
        r.status_code == 201
        and r.json()["skill"]["name"] == "Underwater Welding"
        and r.json()["skill"]["is_verified"] is False
    )
    other = await register_candidate(client)
    r2 = await client.post(f"{ME}/skills", headers=other["h"], json={"name": "underwater welding"})
    assert r2.json()["skill"]["id"] == r.json()["skill"]["id"], (
        "the second candidate reuses the same skill row"
    )
    assert await scalar("SELECT count(*) FROM skills WHERE normalized_name = 'underwaterwelding'") == 1


@pytest.mark.parametrize("again", ["Python", "python", "PYTHON ", "py", "python3"])
async def test_duplicate_skill_is_a_conflict_even_via_alias(client: AsyncClient, again: str) -> None:
    cand = await register_candidate(client)
    assert (await client.post(f"{ME}/skills", headers=cand["h"], json={"name": "Python"})).status_code == 201
    assert_error(
        await client.post(f"{ME}/skills", headers=cand["h"], json={"name": again}), 409, "SKILL_ALREADY_ADDED"
    )
    assert len((await profile(client, cand))["skills"]) == 1


async def test_skill_reference_errors(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    assert_error(await client.post(f"{ME}/skills", headers=h, json={}), 422, "VALIDATION_ERROR")
    assert_error(await client.post(f"{ME}/skills", headers=h, json={"name": "  "}), 422, "VALIDATION_ERROR")
    assert_error(
        await client.post(f"{ME}/skills", headers=h, json={"skill_id": str(uuid.uuid4())}),
        404,
        "SKILL_NOT_FOUND",
    )
    assert_error(await client.post(f"{ME}/skills", headers=h, json={"name": "..."}), 422, "INVALID_SKILL")
    for bad in ({"years_experience": -1}, {"years_experience": 71}, {"proficiency": "GURU"}):
        assert_error(
            await client.post(f"{ME}/skills", headers=h, json={"name": "Go", **bad}), 422, "VALIDATION_ERROR"
        )
    assert (await profile(client, cand))["skills"] == []


async def test_update_and_remove_skill(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    item = (await client.post(f"{ME}/skills", headers=h, json={"name": "Python"})).json()
    r = await client.patch(
        f"{ME}/skills/{item['id']}", headers=h, json={"proficiency": "ADVANCED", "years_experience": 3}
    )
    assert r.status_code == 200 and (r.json()["proficiency"], float(r.json()["years_experience"])) == (
        "ADVANCED",
        3.0,
    )
    assert_error(
        await client.patch(f"{ME}/skills/{item['id']}", headers=h, json={"years_experience": 99}),
        422,
        "VALIDATION_ERROR",
    )
    assert (await client.delete(f"{ME}/skills/{item['id']}", headers=h)).status_code == 204
    assert (await profile(client, cand))["skills"] == []
    assert_error(await client.delete(f"{ME}/skills/{item['id']}", headers=h), 404, "NOT_FOUND")
    assert_error(
        await client.patch(f"{ME}/skills/{item['id']}", headers=h, json={"proficiency": "EXPERT"}),
        404,
        "NOT_FOUND",
    )


async def test_resume_suggestions_are_dismissed_not_deleted_and_can_be_reclaimed(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    cid = uuid.UUID((await profile(client, cand))["id"])
    sid = await scalar("SELECT id FROM skills WHERE name = 'Kubernetes'")
    await sql(
        "INSERT INTO candidate_skills (candidate_id, skill_id, source, status, confidence) VALUES (:c, :s, 'RESUME', 'SUGGESTED', 0.8)",
        c=cid,
        s=sid,
    )
    item = (await profile(client, cand))["skills"][0]
    assert item["confidence"] == pytest.approx(0.8)
    assert (await client.delete(f"{ME}/skills/{item['id']}", headers=cand["h"])).status_code == 204
    assert (
        await scalar("SELECT status FROM candidate_skills WHERE id = :i", i=uuid.UUID(item["id"]))
        == "REJECTED"
    ), "dismissal is remembered"
    # a rejected suggestion can still be claimed explicitly, which replaces the parser provenance
    r = await client.post(
        f"{ME}/skills", headers=cand["h"], json={"name": "k8s", "proficiency": "INTERMEDIATE"}
    )
    assert (
        r.status_code == 201
        and r.json()["id"] == item["id"]
        and (r.json()["status"], r.json()["source"]) == ("CONFIRMED", "USER")
    )
    assert_error(
        await client.post(f"{ME}/skills", headers=cand["h"], json={"name": "Kubernetes"}),
        409,
        "SKILL_ALREADY_ADDED",
    )


async def test_skill_items_belong_to_their_owner(client: AsyncClient) -> None:
    owner, intruder = await register_candidate(client), await register_candidate(client)
    item = (await client.post(f"{ME}/skills", headers=owner["h"], json={"name": "Python"})).json()
    assert_error(
        await client.patch(
            f"{ME}/skills/{item['id']}", headers=intruder["h"], json={"proficiency": "EXPERT"}
        ),
        404,
        "NOT_FOUND",
    )
    assert_error(await client.delete(f"{ME}/skills/{item['id']}", headers=intruder["h"]), 404, "NOT_FOUND")
    assert (await profile(client, owner))["skills"][0]["proficiency"] is None


# --- experience / education / certification / language ------------------------------------------------------------------------------------------------------------------------------


def exp_body(**o: Any) -> dict[str, Any]:
    return {
        "title": "Backend Engineer",
        "company_name": "Initech",
        "start_date": "2019-03-01",
        "end_date": "2021-06-30",
        "location": "Berlin",
        "description": "Built APIs.",
        **o,
    }


async def test_experience_crud_and_ordering(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    old = await client.post(
        f"{ME}/experiences",
        headers=h,
        json=exp_body(title="Junior Dev", start_date="2015-01-01", end_date="2017-01-01"),
    )
    new = await client.post(
        f"{ME}/experiences",
        headers=h,
        json=exp_body(title="Senior Dev", start_date="2021-07-01", end_date=None, is_current=True),
    )
    assert old.status_code == new.status_code == 201
    assert (
        new.json()["source"] == "USER" and new.json()["is_current"] is True and new.json()["end_date"] is None
    )
    titles = [e["title"] for e in (await profile(client, cand))["experiences"]]
    assert titles == ["Senior Dev", "Junior Dev"], "most recent first"
    put = await client.put(
        f"{ME}/experiences/{old.json()['id']}", headers=h, json=exp_body(title="Dev", description="Updated")
    )
    assert put.status_code == 200 and (put.json()["title"], put.json()["description"]) == ("Dev", "Updated")
    assert (await client.delete(f"{ME}/experiences/{old.json()['id']}", headers=h)).status_code == 204
    assert [e["title"] for e in (await profile(client, cand))["experiences"]] == ["Senior Dev"]


async def test_experience_rules(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for bad, needle in (
        (exp_body(end_date="2018-01-01"), "end_date must not be before start_date"),
        (exp_body(start_date=tomorrow, end_date=None), "cannot be in the future"),
    ):
        err = assert_error(
            await client.post(f"{ME}/experiences", headers=h, json=bad), 422, "VALIDATION_ERROR"
        )
        assert needle in err["details"][0]["message"]
    for missing in ("title", "company_name", "start_date"):
        body = exp_body()
        body.pop(missing)
        assert_error(await client.post(f"{ME}/experiences", headers=h, json=body), 422, "VALIDATION_ERROR")
    cur = await client.post(
        f"{ME}/experiences", headers=h, json=exp_body(is_current=True, end_date="2022-01-01")
    )
    assert cur.status_code == 201 and cur.json()["end_date"] is None, "a current job cannot have an end date"
    assert (
        await client.post(
            f"{ME}/experiences", headers=h, json=exp_body(start_date="2020-05-05", end_date="2020-05-05")
        )
    ).status_code == 201


async def test_education_crud_and_rules(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    a = await client.post(
        f"{ME}/educations",
        headers=h,
        json={
            "institution": "TU Berlin",
            "degree_level": "BACHELOR",
            "field_of_study": "CS",
            "start_year": 2010,
            "end_year": 2014,
        },
    )
    b = await client.post(
        f"{ME}/educations",
        headers=h,
        json={"institution": "ETH", "degree_level": "MASTER", "start_year": 2014},
    )  # still studying
    assert a.status_code == b.status_code == 201
    assert [e["institution"] for e in (await profile(client, cand))["educations"]] == ["ETH", "TU Berlin"], (
        "open-ended study first, then newest end year"
    )
    put = await client.put(
        f"{ME}/educations/{b.json()['id']}",
        headers=h,
        json={"institution": "ETH Zurich", "degree_level": "MASTER", "end_year": 2016, "start_year": 2014},
    )
    assert put.status_code == 200 and put.json()["end_year"] == 2016
    for bad in (
        {"start_year": 2015, "end_year": 2012},
        {"start_year": 1949},
        {"end_year": 2101},
        {"degree_level": "PHD"},
    ):
        assert_error(
            await client.post(
                f"{ME}/educations", headers=h, json={"institution": "X", "degree_level": "MASTER", **bad}
            ),
            422,
            "VALIDATION_ERROR",
        )
    assert (await client.delete(f"{ME}/educations/{a.json()['id']}", headers=h)).status_code == 204
    assert len((await profile(client, cand))["educations"]) == 1


async def test_certification_crud_and_rules(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    c = await client.post(
        f"{ME}/certifications",
        headers=h,
        json={
            "name": "CKA",
            "issuer": "CNCF",
            "issued_on": "2023-01-01",
            "expires_on": "2026-01-01",
            "credential_url": "https://cncf.io/c/1",
        },
    )
    assert c.status_code == 201 and c.json()["credential_url"] == "https://cncf.io/c/1"
    put = await client.put(
        f"{ME}/certifications/{c.json()['id']}", headers=h, json={"name": "CKAD", "issuer": "CNCF"}
    )
    assert put.status_code == 200 and put.json()["name"] == "CKAD" and put.json()["issued_on"] is None
    assert_error(
        await client.post(
            f"{ME}/certifications",
            headers=h,
            json={"name": "X", "issued_on": "2024-01-01", "expires_on": "2023-01-01"},
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(
            f"{ME}/certifications", headers=h, json={"name": "X", "credential_url": "javascript:x"}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert (await client.delete(f"{ME}/certifications/{c.json()['id']}", headers=h)).status_code == 204
    assert (await profile(client, cand))["certifications"] == []


async def test_languages(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    h = cand["h"]
    de = await client.post(f"{ME}/languages", headers=h, json={"language": "German", "proficiency": "NATIVE"})
    assert de.status_code == 201 and de.json()["proficiency"] == "NATIVE"
    for dup in ("German", "german", "GERMAN"):
        assert_error(
            await client.post(f"{ME}/languages", headers=h, json={"language": dup, "proficiency": "BASIC"}),
            409,
            "LANGUAGE_EXISTS",
        )
    assert (
        await client.post(f"{ME}/languages", headers=h, json={"language": "English", "proficiency": "FLUENT"})
    ).status_code == 201
    assert_error(
        await client.post(
            f"{ME}/languages", headers=h, json={"language": "French", "proficiency": "PERFECT"}
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(f"{ME}/languages", headers=h, json={"language": "F", "proficiency": "BASIC"}),
        422,
        "VALIDATION_ERROR",
    )
    assert len((await profile(client, cand))["languages"]) == 2
    assert (await client.delete(f"{ME}/languages/{de.json()['id']}", headers=h)).status_code == 204
    assert [lang["language"] for lang in (await profile(client, cand))["languages"]] == ["English"]
    assert (
        await client.post(f"{ME}/languages", headers=h, json={"language": "German", "proficiency": "BASIC"})
    ).status_code == 201


@pytest.mark.parametrize(
    ("kind", "create"),
    [
        ("experiences", exp_body()),
        ("educations", {"institution": "MIT", "degree_level": "MASTER"}),
        ("certifications", {"name": "CKA"}),
        ("languages", {"language": "German", "proficiency": "NATIVE"}),
    ],
)
async def test_items_of_another_candidate_are_invisible(
    client: AsyncClient, kind: str, create: dict[str, Any]
) -> None:
    owner, intruder = await register_candidate(client), await register_candidate(client)
    item = (await client.post(f"{ME}/{kind}", headers=owner["h"], json=create)).json()
    url = f"{ME}/{kind}/{item['id']}"
    assert_error(await client.delete(url, headers=intruder["h"]), 404, "NOT_FOUND")
    if kind != "languages":
        assert_error(await client.put(url, headers=intruder["h"], json=create), 404, "NOT_FOUND")
    assert_error(await client.delete(f"{ME}/{kind}/{uuid.uuid4()}", headers=owner["h"]), 404, "NOT_FOUND")
    assert_error(await client.delete(f"{ME}/{kind}/not-a-uuid", headers=owner["h"]), 422, "VALIDATION_ERROR")
    assert len((await profile(client, owner))[kind]) == 1, "the owner's data is untouched"
    assert (await profile(client, intruder))[kind] == []


# --- authorization -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_only_candidates_manage_a_candidate_profile(client: AsyncClient) -> None:
    rec = await register_employer(client)
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    for actor in (rec, hm):
        for method, url, body in (
            ("GET", ME, None),
            ("PATCH", ME, {"headline": "x"}),
            ("POST", f"{ME}/skills", {"name": "Python"}),
            ("GET", f"{ME}/completion", None),
        ):
            assert_error(await client.request(method, url, headers=actor["h"], json=body), 403, "FORBIDDEN")
    assert_error(await client.get(ME), 401, "UNAUTHORIZED")
    admin = await create_admin(client)
    assert_error(
        await client.get(ME, headers=admin["h"]), 404, "CANDIDATE_NOT_FOUND"
    )  # admins have no profile of their own


# --- derived search data ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_profile_edits_refresh_the_denormalised_search_text(client: AsyncClient) -> None:
    cand = await register_candidate(client, first="Alex", last="Backend")
    await fill_backend_profile(client, cand, years=5)
    row = (
        await sql(
            "SELECT skills_text, search_text, display_name FROM candidate_profiles WHERE user_id = :u",
            u=uuid.UUID(cand["user"]["id"]),
        )
    )[0]
    skills_text, search_text, display_name = row
    assert set(skills_text.split()) >= {"Python", "FastAPI", "PostgreSQL", "Docker", "Redis"}
    assert "Backend Engineer" in search_text and "FastAPI and PostgreSQL" in search_text
    assert display_name not in search_text, "the candidate's name is not part of the free text"
    # the generated tsvector follows
    hit = await scalar(
        "SELECT count(*) FROM candidate_profiles WHERE search_tsv @@ websearch_to_tsquery('english', 'fastapi')"
    )
    assert hit == 1
    # removing a skill removes it from the index, adding a new experience title adds it
    py = next(s for s in (await profile(client, cand))["skills"] if s["skill"]["name"] == "Redis")
    await client.delete(f"{ME}/skills/{py['id']}", headers=cand["h"])
    await client.post(
        f"{ME}/experiences",
        headers=cand["h"],
        json=exp_body(
            title="Staff Platform Architect", start_date="2023-01-01", end_date=None, is_current=True
        ),
    )
    skills_text, search_text = (
        await sql(
            "SELECT skills_text, search_text FROM candidate_profiles WHERE user_id = :u",
            u=uuid.UUID(cand["user"]["id"]),
        )
    )[0]
    assert "Redis" not in skills_text.split() and "Staff Platform Architect" in search_text


async def test_every_profile_change_queues_a_deduplicated_matching_task(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    cid = (await profile(client, cand))["id"]
    assert await tasks("MATCH_CANDIDATE") == []
    await client.patch(
        ME,
        headers=cand["h"],
        json={"headline": "Backend engineer", "summary": "Builds Python APIs with PostgreSQL every day."},
    )
    rows = await tasks("MATCH_CANDIDATE")
    assert len(rows) == 1
    task = rows[0]
    assert task.status == "COMPLETED", "tests run background work inline"
    assert (
        task.params == {"candidate_id": cid}
        and task.dedupe_key == f"match-candidate:{cid}"
        and task.attempts == 1
    )
    # the work happened: the profile now has an embedding with provenance
    emb = (
        await sql(
            "SELECT embedding IS NOT NULL, embedding_model, embedding_version, embedding_source_hash FROM candidate_profiles WHERE id = :c",
            c=uuid.UUID(cid),
        )
    )[0]
    assert emb[0] is True and emb[1] == "wordllama-l2-supercat-256" and emb[2] == "v1" and len(emb[3]) == 64
    await client.post(f"{ME}/skills", headers=cand["h"], json={"name": "Python"})
    assert len(await tasks("MATCH_CANDIDATE")) == 2, "a finished task does not block the next refresh"


async def test_unchanged_profile_text_does_not_trigger_re_embedding(client: AsyncClient) -> None:
    cand = await register_candidate(client)
    await client.patch(
        ME,
        headers=cand["h"],
        json={"headline": "Backend engineer", "summary": "Builds Python APIs with PostgreSQL every day."},
    )
    cid = uuid.UUID((await profile(client, cand))["id"])
    before = (
        await sql(
            "SELECT embedding_source_hash, embedding_generated_at FROM candidate_profiles WHERE id = :c",
            c=cid,
        )
    )[0]
    await client.patch(
        ME, headers=cand["h"], json={"expected_salary": 90000}
    )  # not part of the embedded text
    after = (
        await sql(
            "SELECT embedding_source_hash, embedding_generated_at FROM candidate_profiles WHERE id = :c",
            c=cid,
        )
    )[0]
    assert before == after
    await client.patch(ME, headers=cand["h"], json={"headline": "Platform engineer"})
    assert (await sql("SELECT embedding_source_hash FROM candidate_profiles WHERE id = :c", c=cid))[0][
        0
    ] != before[0]
