"""Job recommendations for candidates: ranking, filters, explanations, caching and exclusion rules."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.cache.redis_cache import get_cache
from tests.helpers import (
    fill_backend_profile,
    fill_frontend_profile,
    job_payload,
    register_candidate,
    register_employer,
)
from tests.helpers_spine import (  # noqa: F401
    API,
    apply_job,
    assert_error,
    expire_deadline,
    fast_argon,
    nurse_profile,
    publish,
    scalar,
    set_job_status,
    shared_world,
    sql,
    walk,
)

pytestmark = pytest.mark.integration

RECS = f"{API}/recommendations/jobs"


def spec(
    title: str, location: str, workplace: str, employment: str, skills: list[str], **extra: Any
) -> dict[str, Any]:
    return job_payload(
        title,
        location=location,
        workplace_type=workplace,
        employment_type=employment,
        skills=[{"name": s} for s in skills],
        **extra,
    )


async def build_jobs(client: AsyncClient, rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = {}
    for key, payload in {
        "backend": spec(
            "Backend Engineer",
            "Berlin, Germany",
            "HYBRID",
            "FULL_TIME",
            ["Python", "FastAPI", "PostgreSQL", "Docker"],
            min_experience_years=3,
        ),
        "frontend": spec(
            "Frontend Developer",
            "Madrid, Spain",
            "REMOTE",
            "FULL_TIME",
            ["React", "TypeScript", "CSS"],
            min_experience_years=2,
        ),
        "ml": spec(
            "Machine Learning Engineer",
            "Lisbon, Portugal",
            "REMOTE",
            "CONTRACT",
            ["Python", "PyTorch", "Machine Learning"],
            min_experience_years=3,
        ),
        "icu": spec(
            "ICU Nurse",
            "Hamburg, Germany",
            "ONSITE",
            "PART_TIME",
            ["Critical Care", "BLS"],
            min_experience_years=2,
        ),
    }.items():
        r = await client.post(f"{API}/jobs", headers=rec["h"], json=payload)
        assert r.status_code == 201, r.text
        jobs[key] = await publish(client, rec, r.json()["id"])
    return jobs


async def build_world(client: AsyncClient) -> dict[str, Any]:
    rec = await register_employer(client, "Recs Co")
    w: dict[str, Any] = {"rec": rec}
    w["backend_cand"] = await register_candidate(client, first="Alex", last="Backend")
    w["front_cand"] = await register_candidate(client, first="Bianca", last="Frontend")
    await fill_backend_profile(client, w["backend_cand"], years=5)
    await fill_frontend_profile(client, w["front_cand"], years=3)
    w["jobs"] = await build_jobs(
        client, rec
    )  # published after the profiles exist: scored by the job-side runs
    for i, key in enumerate(
        ("backend", "frontend", "ml", "icu")
    ):  # deterministic "newest" order: icu newest ... backend oldest
        await sql(
            "UPDATE jobs SET published_at = now() - make_interval(days => :d) WHERE id = :i",
            d=10 - i,
            i=uuid.UUID(w["jobs"][key]["id"]),
        )
    return w


@pytest.fixture(scope="module")
async def _world(migrated_db: None, seeded_ontology: None):  # type: ignore[no-untyped-def]
    async with shared_world(build_world) as world:
        yield world


@pytest.fixture
def client(_world):  # type: ignore[no-untyped-def]
    return _world[0]


@pytest.fixture
def w(_world):  # type: ignore[no-untyped-def]
    return _world[1]


async def recs(client: AsyncClient, who: dict[str, Any], **params: Any) -> dict[str, Any]:
    r = await client.get(RECS, headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def titles(body: dict[str, Any]) -> list[str]:
    return [i["job"]["title"] for i in body["items"]]


# --- ranking + shape -----------------------------------------------------------------------------------------------------------------------------------------


async def test_recommendations_are_ranked_by_fit_for_each_candidate(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    mine = await recs(client, w["backend_cand"])
    assert titles(mine)[0] == "Backend Engineer" and titles(mine)[-1] == "ICU Nurse" and mine["total"] == 4
    scores = [i["job"]["match_score"] for i in mine["items"]]
    assert scores == sorted(scores, reverse=True)
    theirs = await recs(client, w["front_cand"])
    assert titles(theirs)[0] == "Frontend Developer" and titles(theirs)[-1] == "ICU Nurse"


async def test_item_shape_and_candidate_facing_explanation(client: AsyncClient, w: dict[str, Any]) -> None:
    body = await recs(client, w["backend_cand"])
    item = body["items"][0]
    assert set(item) == {"job", "match"}
    assert (
        item["job"]["company_name"] == "Recs Co"
        and item["job"]["is_saved"] is False
        and item["job"]["has_applied"] is False
        and item["job"]["status"] == "PUBLISHED"
    )
    assert item["job"]["skills"] == ["Docker", "FastAPI", "PostgreSQL", "Python"]
    m = item["match"]
    assert m["overall_percent"] == round(item["job"]["match_score"] * 100) and m["band"] in {"STRONG", "GOOD"}
    assert (
        set(m["matched_skills"]) >= {"Python", "FastAPI", "PostgreSQL", "Docker"}
        and m["missing_required"] == []
    )
    assert m["experience_status"] == "MEETS" and m["semantic_band"] in {"HIGH", "MEDIUM"}
    leaked = {k for k, _ in walk(body)} & {
        "cosine",
        "raw_cosine",
        "weights",
        "semantic_score",
        "breakdown",
        "candidate_hash",
        "job_hash",
        "embedding_model",
        "explanation",
        "overall_score",
    }
    assert not leaked, leaked
    assert "weight" not in json.dumps(body).lower() and "cosine" not in json.dumps(body).lower()
    assert set(body["meta"]) == {"last_generated_at", "computing", "task_id", "profile_ready", "hint"}
    assert (
        body["meta"]["profile_ready"] is True
        and body["meta"]["computing"] is False
        and body["meta"]["last_generated_at"]
    )
    nurse_job = body["items"][-1]
    assert nurse_job["match"]["matched_skills"] == [] and set(nurse_job["match"]["missing_required"]) == {
        "Critical Care",
        "BLS",
    }


# --- filters ------------------------------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"workplace_type": "REMOTE"}, {"Frontend Developer", "Machine Learning Engineer"}),
        (
            {"workplace_type": ["REMOTE", "ONSITE"]},
            {"Frontend Developer", "Machine Learning Engineer", "ICU Nurse"},
        ),
        ({"employment_type": "CONTRACT"}, {"Machine Learning Engineer"}),
        ({"employment_type": ["CONTRACT", "PART_TIME"]}, {"Machine Learning Engineer", "ICU Nurse"}),
        ({"location": "lisbon"}, {"Machine Learning Engineer"}),
        ({"location": "GERMANY"}, {"Backend Engineer", "ICU Nurse"}),
        ({"location": "%"}, set()),
        ({"location": "_"}, set()),
        ({"workplace_type": "REMOTE", "employment_type": "FULL_TIME"}, {"Frontend Developer"}),
    ],
)
async def test_filters(
    client: AsyncClient, w: dict[str, Any], params: dict[str, Any], expected: set[str]
) -> None:
    assert set(titles(await recs(client, w["backend_cand"], page_size=100, **params))) == expected


async def test_skill_and_score_filters_and_sorting(client: AsyncClient, w: dict[str, Any]) -> None:
    react = (await client.get(f"{API}/skills", params={"q": "React"})).json()["items"][0]["id"]
    python = (await client.get(f"{API}/skills", params={"q": "Python"})).json()["items"][0]["id"]
    assert titles(await recs(client, w["backend_cand"], skill_id=react)) == ["Frontend Developer"]
    assert set(titles(await recs(client, w["backend_cand"], skill_id=python))) == {
        "Backend Engineer",
        "Machine Learning Engineer",
    }
    assert titles(await recs(client, w["backend_cand"], skill_id=[python, react])) == [], (
        "all listed skills must be required by the job"
    )
    top = (await recs(client, w["backend_cand"]))["items"][0]["job"]["match_score"]
    assert titles(await recs(client, w["backend_cand"], min_score=top - 0.001)) == ["Backend Engineer"]
    assert all(
        i["job"]["match_score"] >= 0.999
        for i in (await recs(client, w["backend_cand"], min_score=0.999))["items"]
    )
    assert titles(await recs(client, w["backend_cand"], sort="newest")) == [
        "ICU Nurse",
        "Machine Learning Engineer",
        "Frontend Developer",
        "Backend Engineer",
    ]
    assert titles(await recs(client, w["backend_cand"], sort="score"))[0] == "Backend Engineer"


async def test_pagination_envelope(client: AsyncClient, w: dict[str, Any]) -> None:
    p1 = await recs(client, w["backend_cand"], page_size=3)
    p2 = await recs(client, w["backend_cand"], page_size=3, page=2)
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"], len(p1["items"])) == (
        1,
        3,
        4,
        2,
        3,
    ) and len(p2["items"]) == 1
    assert not set(titles(p1)) & set(titles(p2))
    assert (await recs(client, w["backend_cand"], page=9))["items"] == []
    assert (await recs(client, w["backend_cand"], page_size=12))["page_size"] == 12
    default = await recs(client, w["backend_cand"])
    assert default["page_size"] == 20


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"min_score": 1.1},
        {"min_score": -0.1},
        {"sort": "random"},
        {"skill_id": "nope"},
        {"location": "x" * 101},
        {"workplace_type": "MOON"},
        {"employment_type": "SLAVERY"},
    ],
)
async def test_invalid_parameters(client: AsyncClient, w: dict[str, Any], params: dict[str, Any]) -> None:
    assert_error(
        await client.get(RECS, headers=w["backend_cand"]["h"], params=params), 422, "VALIDATION_ERROR"
    )


async def test_only_candidates_get_recommendations(client: AsyncClient, w: dict[str, Any]) -> None:
    assert_error(await client.get(RECS, headers=w["rec"]["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(RECS), 401, "UNAUTHORIZED")


async def test_results_are_cached_per_candidate(client: AsyncClient, w: dict[str, Any]) -> None:
    cache = get_cache()
    await recs(client, w["backend_cand"], page_size=7)
    hits = cache.hits
    again = await recs(client, w["backend_cand"], page_size=7)
    assert cache.hits == hits + 1 and titles(again)[0] == "Backend Engineer"
    other = await recs(client, w["front_cand"], page_size=7)
    assert titles(other)[0] == "Frontend Developer", (
        "another candidate never receives a cached list built for someone else"
    )
    assert cache.hits == hits + 1
