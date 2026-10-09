"""Listing applications: scoping per role, filters, sorting, paging and score visibility (shared read-only world)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import (
    add_staff,
    create_admin,
    create_job,
    fill_backend_profile,
    fill_frontend_profile,
    register_candidate,
    register_employer,
)
from tests.helpers_spine import (
    API,
    apply_job,
    assert_error,
    nurse_profile,
    set_application_status,
    shared_world,
    sql,
)

pytestmark = pytest.mark.e2e

APPS = f"{API}/applications"


async def build_world(client: AsyncClient) -> dict[str, Any]:
    rec_a, rec_b = await register_employer(client, "List Co A"), await register_employer(client, "List Co B")
    hm_a = await add_staff(client, rec_a, "HIRING_MANAGER")
    j1 = await create_job(client, rec_a, publish=True, title="Backend Engineer", hiring_manager_id=hm_a["id"])
    j2 = await create_job(client, rec_a, publish=True, title="Platform Engineer")
    j3 = await create_job(client, rec_b, publish=True, title="Backend Engineer")
    c1 = await register_candidate(client, first="Alex", last="Backend")
    c2 = await register_candidate(client, first="Bianca", last="Frontend")
    c3 = await register_candidate(client, first="Julia", last="Nurse")
    c4 = await register_candidate(client, first="Dana", last="Bare")
    c5 = await register_candidate(client, first="Eli", last="Extra")
    await fill_backend_profile(client, c1)
    await fill_frontend_profile(client, c2)
    await nurse_profile(client, c3)
    apps = {
        "a1": await apply_job(client, c1, j1["id"]),
        "a2": await apply_job(client, c2, j1["id"]),
        "a3": await apply_job(client, c3, j1["id"]),
        "a4": await apply_job(client, c4, j2["id"]),
        "a5": await apply_job(client, c1, j2["id"]),
        "a6": await apply_job(client, c5, j3["id"]),
        "a7": await apply_job(client, c1, j3["id"]),
        "a8": await apply_job(client, c2, j2["id"]),
    }
    for key, status in (
        ("a2", "SCREENING"),
        ("a3", "REJECTED"),
        ("a4", "SHORTLISTED"),
        ("a5", "HIRED"),
        ("a8", "WITHDRAWN"),
    ):
        await set_application_status(apps[key]["id"], status)
    # deterministic chronology: a1 is the oldest ... a8 the newest; status_changed_at reversed for the "updated" sort
    for i, key in enumerate(apps):
        await sql(
            "UPDATE applications SET applied_at = now() - make_interval(hours => :h), status_changed_at = now() - make_interval(mins => :m) WHERE id = :i",
            h=100 - i * 10,
            m=i * 7 + 1,
            i=uuid.UUID(apps[key]["id"]),
        )
    return {
        "rec_a": rec_a,
        "rec_b": rec_b,
        "hm_a": hm_a,
        "j1": j1,
        "j2": j2,
        "j3": j3,
        "c": [c1, c2, c3, c4, c5],
        "apps": apps,
        "admin": await create_admin(client),
    }


@pytest.fixture(scope="module")
async def _world(migrated_db: None, seeded_ontology: None):  # type: ignore[no-untyped-def]
    async with shared_world(build_world) as world:
        yield world


@pytest.fixture
def client(_world):  # type: ignore[no-untyped-def]  # no per-test database reset: these tests only read
    return _world[0]


@pytest.fixture
def w(_world):  # type: ignore[no-untyped-def]
    return _world[1]


async def listing(client: AsyncClient, who: dict[str, Any], **params: Any) -> dict[str, Any]:
    r = await client.get(APPS, headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def ids(body: dict[str, Any]) -> list[str]:
    return [i["id"] for i in body["items"]]


def keys(w: dict[str, Any], body: dict[str, Any]) -> set[str]:
    by_id = {a["id"]: k for k, a in w["apps"].items()}
    return {by_id[i] for i in ids(body)}


# --- scoping ------------------------------------------------------------------------------------------------------------------------------------


async def test_each_role_sees_only_its_own_slice(client: AsyncClient, w: dict[str, Any]) -> None:
    c1, c2, _c3, _c4, c5 = w["c"]
    assert keys(w, await listing(client, w["rec_a"], page_size=100)) == {"a1", "a2", "a3", "a4", "a5", "a8"}
    assert keys(w, await listing(client, w["rec_b"], page_size=100)) == {"a6", "a7"}
    assert keys(w, await listing(client, w["hm_a"], page_size=100)) == {"a1", "a2", "a3"}, (
        "hiring managers see applications to jobs assigned to them"
    )
    assert keys(w, await listing(client, c1, page_size=100)) == {"a1", "a5", "a7"}, (
        "a candidate sees their own applications to every company"
    )
    assert keys(w, await listing(client, c2, page_size=100)) == {"a2", "a8"}, (
        "withdrawn applications stay in the candidate's history"
    )
    assert keys(w, await listing(client, c5, page_size=100)) == {"a6"}
    assert keys(w, await listing(client, w["admin"], page_size=100)) == set(w["apps"])


async def test_a_new_staff_member_without_assignments_sees_nothing(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    from tests.helpers import add_staff

    hm = await add_staff(client, w["rec_a"], "HIRING_MANAGER")
    assert (await listing(client, hm))["total"] == 0


async def test_authentication_is_required(client: AsyncClient) -> None:
    assert_error(await client.get(APPS), 401, "UNAUTHORIZED")


# --- item shape + score visibility -----------------------------------------------------------------------------------------------------------------------


async def test_item_shape_and_staff_only_scores(client: AsyncClient, w: dict[str, Any]) -> None:
    staff = (await listing(client, w["rec_a"], job_id=w["j1"]["id"], page_size=100))["items"]
    assert set(staff[0]) == {
        "id",
        "job_id",
        "job_title",
        "company_id",
        "company_name",
        "candidate_id",
        "candidate_name",
        "candidate_headline",
        "status",
        "applied_at",
        "status_changed_at",
        "match_score",
        "match_band",
        "has_resume",
        "next_interview_at",
    }
    by_name = {i["candidate_name"]: i for i in staff}
    alex = by_name["Alex Backend"]
    assert (
        alex["match_score"] is not None
        and 0.5 < alex["match_score"] <= 1
        and alex["match_band"] in {"STRONG", "GOOD"}
        and alex["candidate_headline"] == "Backend engineer"
    )
    assert by_name["Julia Nurse"]["match_score"] < alex["match_score"]
    assert all(i["next_interview_at"] is None and i["has_resume"] is False for i in staff)
    mine = (await listing(client, w["c"][0], page_size=100))["items"]
    assert len(mine) == 3
    for item in mine:
        assert (
            item["match_score"] is None and item["match_band"] is None and item["candidate_headline"] is None
        ), "candidates never see scores"
    assert {i["company_name"] for i in mine} == {"List Co A", "List Co B"}


# --- filters ------------------------------------------------------------------------------------------------------------------------------------------------------


async def test_job_and_status_filters(client: AsyncClient, w: dict[str, Any]) -> None:
    rec = w["rec_a"]
    assert keys(w, await listing(client, rec, job_id=w["j1"]["id"])) == {"a1", "a2", "a3"}
    assert keys(w, await listing(client, rec, job_id=w["j3"]["id"])) == set(), (
        "another company's job yields nothing, not an error"
    )
    assert keys(w, await listing(client, rec, status="APPLIED")) == {"a1"}
    assert keys(w, await listing(client, rec, status=["APPLIED", "SCREENING"])) == {"a1", "a2"}
    assert keys(w, await listing(client, rec, status=["REJECTED", "HIRED", "WITHDRAWN"])) == {
        "a3",
        "a5",
        "a8",
    }
    assert keys(w, await listing(client, rec, status="SHORTLISTED", job_id=w["j2"]["id"])) == {"a4"}
    assert keys(w, await listing(client, rec, status="SHORTLISTED", job_id=w["j1"]["id"])) == set()
    assert keys(w, await listing(client, w["hm_a"], job_id=w["j2"]["id"])) == set(), (
        "unassigned jobs stay invisible to the hiring manager"
    )


async def test_active_only_excludes_finished_applications(client: AsyncClient, w: dict[str, Any]) -> None:
    assert keys(w, await listing(client, w["rec_a"], active_only=True)) == {"a1", "a2", "a4"}
    assert keys(w, await listing(client, w["c"][0], active_only=True)) == {"a1", "a7"}
    assert keys(w, await listing(client, w["rec_a"], active_only=True, status="REJECTED")) == set()


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("alex", {"a1", "a5"}),
        ("ALEX BACK", {"a1", "a5"}),
        ("nurse", {"a3"}),
        ("platform", {"a4", "a5", "a8"}),
        ("engineer", {"a1", "a2", "a3", "a4", "a5", "a8"}),
        ("  bianca  ", {"a2", "a8"}),
        ("nobody-matches", set()),
        ("%", set()),
        ("_", set()),
        ("a%x", set()),
    ],
)
async def test_text_search_on_candidate_and_job_titles(
    client: AsyncClient, w: dict[str, Any], q: str, expected: set[str]
) -> None:
    assert keys(w, await listing(client, w["rec_a"], q=q, page_size=100)) == expected


# --- sorting + paging ----------------------------------------------------------------------------------------------------------------------------------------------


async def test_sorts(client: AsyncClient, w: dict[str, Any]) -> None:
    rec, apps = w["rec_a"], w["apps"]
    order = ["a1", "a2", "a3", "a4", "a5", "a8"]  # applied_at ascending
    newest = ids(await listing(client, rec, sort="newest"))
    assert newest == [apps[k]["id"] for k in reversed(order)]
    assert ids(await listing(client, rec, sort="oldest")) == [apps[k]["id"] for k in order]
    assert ids(await listing(client, rec, sort="updated")) == [apps[k]["id"] for k in order], (
        "most recently changed first (a1 was changed last in the fixture)"
    )
    by_match = (await listing(client, rec, sort="match", page_size=100))["items"]
    scores = [i["match_score"] for i in by_match]
    known = [s for s in scores if s is not None]
    assert known == sorted(known, reverse=True) and by_match[0]["candidate_name"] == "Alex Backend"
    assert scores[len(known) :] == [None] * (len(scores) - len(known)), (
        "applications without a score sort last"
    )


async def test_pagination_envelope_and_stability(client: AsyncClient, w: dict[str, Any]) -> None:
    rec = w["rec_a"]
    p1 = await listing(client, rec, page_size=4)
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"], len(p1["items"])) == (1, 4, 6, 2, 4)
    p2 = await listing(client, rec, page_size=4, page=2)
    assert len(p2["items"]) == 2 and not set(ids(p1)) & set(ids(p2))
    assert (await listing(client, rec, page_size=4, page=3))["items"] == []
    assert (await listing(client, rec, page_size=100))["pages"] == 1
    assert (await listing(client, rec, job_id=str(uuid.uuid4())))["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "random"},
        {"status": "DONE"},
        {"page": 0},
        {"page_size": 101},
        {"job_id": "nope"},
        {"active_only": "maybe"},
        {"q": "x" * 101},
    ],
)
async def test_invalid_parameters(client: AsyncClient, w: dict[str, Any], params: dict[str, Any]) -> None:
    assert_error(await client.get(APPS, headers=w["rec_a"]["h"], params=params), 422, "VALIDATION_ERROR")
