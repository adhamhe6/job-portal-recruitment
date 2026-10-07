"""Job recommendations for candidates: ranking, filters, explanations, caching and exclusion rules."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.cache.redis_cache import get_cache
from tests.helpers import create_job, fill_backend_profile, fill_frontend_profile, job_payload, register_candidate, register_employer
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


def spec(title: str, location: str, workplace: str, employment: str, skills: list[str], **extra: Any) -> dict[str, Any]:
    return job_payload(title, location=location, workplace_type=workplace, employment_type=employment, skills=[{"name": s} for s in skills], **extra)


async def build_jobs(client: AsyncClient, rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = {}
    for key, payload in {
        "backend": spec("Backend Engineer", "Berlin, Germany", "HYBRID", "FULL_TIME", ["Python", "FastAPI", "PostgreSQL", "Docker"], min_experience_years=3),
        "frontend": spec("Frontend Developer", "Madrid, Spain", "REMOTE", "FULL_TIME", ["React", "TypeScript", "CSS"], min_experience_years=2),
        "ml": spec("Machine Learning Engineer", "Lisbon, Portugal", "REMOTE", "CONTRACT", ["Python", "PyTorch", "Machine Learning"], min_experience_years=3),
        "icu": spec("ICU Nurse", "Hamburg, Germany", "ONSITE", "PART_TIME", ["Critical Care", "BLS"], min_experience_years=2),
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
    w["jobs"] = await build_jobs(client, rec)  # published after the profiles exist: scored by the job-side runs
    for i, key in enumerate(("backend", "frontend", "ml", "icu")):  # deterministic "newest" order: icu newest ... backend oldest
        await sql("UPDATE jobs SET published_at = now() - make_interval(days => :d) WHERE id = :i", d=10 - i, i=uuid.UUID(w["jobs"][key]["id"]))
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


async def test_recommendations_are_ranked_by_fit_for_each_candidate(client: AsyncClient, w: dict[str, Any]) -> None:
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
    assert item["job"]["company_name"] == "Recs Co" and item["job"]["is_saved"] is False and item["job"]["has_applied"] is False and item["job"]["status"] == "PUBLISHED"
    assert item["job"]["skills"] == ["Docker", "FastAPI", "PostgreSQL", "Python"]
    m = item["match"]
    assert m["overall_percent"] == round(item["job"]["match_score"] * 100) and m["band"] in {"STRONG", "GOOD"}
    assert set(m["matched_skills"]) >= {"Python", "FastAPI", "PostgreSQL", "Docker"} and m["missing_required"] == []
    assert m["experience_status"] == "MEETS" and m["semantic_band"] in {"HIGH", "MEDIUM"}
    leaked = {k for k, _ in walk(body)} & {"cosine", "raw_cosine", "weights", "semantic_score", "breakdown", "candidate_hash", "job_hash", "embedding_model", "explanation", "overall_score"}
    assert not leaked, leaked
    assert "weight" not in json.dumps(body).lower() and "cosine" not in json.dumps(body).lower()
    assert set(body["meta"]) == {"last_generated_at", "computing", "task_id", "profile_ready", "hint"}
    assert body["meta"]["profile_ready"] is True and body["meta"]["computing"] is False and body["meta"]["last_generated_at"]
    nurse_job = body["items"][-1]
    assert nurse_job["match"]["matched_skills"] == [] and set(nurse_job["match"]["missing_required"]) == {"Critical Care", "BLS"}


# --- filters ------------------------------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"workplace_type": "REMOTE"}, {"Frontend Developer", "Machine Learning Engineer"}),
        ({"workplace_type": ["REMOTE", "ONSITE"]}, {"Frontend Developer", "Machine Learning Engineer", "ICU Nurse"}),
        ({"employment_type": "CONTRACT"}, {"Machine Learning Engineer"}),
        ({"employment_type": ["CONTRACT", "PART_TIME"]}, {"Machine Learning Engineer", "ICU Nurse"}),
        ({"location": "lisbon"}, {"Machine Learning Engineer"}),
        ({"location": "GERMANY"}, {"Backend Engineer", "ICU Nurse"}),
        ({"location": "%"}, set()),
        ({"location": "_"}, set()),
        ({"workplace_type": "REMOTE", "employment_type": "FULL_TIME"}, {"Frontend Developer"}),
        ({"workplace_type": "MOON"}, set()),
    ],
)
async def test_filters(client: AsyncClient, w: dict[str, Any], params: dict[str, Any], expected: set[str]) -> None:
    assert set(titles(await recs(client, w["backend_cand"], page_size=100, **params))) == expected


async def test_skill_and_score_filters_and_sorting(client: AsyncClient, w: dict[str, Any]) -> None:
    react = (await client.get(f"{API}/skills", params={"q": "React"})).json()["items"][0]["id"]
    python = (await client.get(f"{API}/skills", params={"q": "Python"})).json()["items"][0]["id"]
    assert titles(await recs(client, w["backend_cand"], skill_id=react)) == ["Frontend Developer"]
    assert set(titles(await recs(client, w["backend_cand"], skill_id=python))) == {"Backend Engineer", "Machine Learning Engineer"}
    assert titles(await recs(client, w["backend_cand"], skill_id=[python, react])) == [], "all listed skills must be required by the job"
    top = (await recs(client, w["backend_cand"]))["items"][0]["job"]["match_score"]
    assert titles(await recs(client, w["backend_cand"], min_score=top - 0.001)) == ["Backend Engineer"]
    assert (await recs(client, w["backend_cand"], min_score=1.0))["items"] == []
    assert titles(await recs(client, w["backend_cand"], sort="newest")) == ["ICU Nurse", "Machine Learning Engineer", "Frontend Developer", "Backend Engineer"]
    assert titles(await recs(client, w["backend_cand"], sort="score"))[0] == "Backend Engineer"


async def test_pagination_envelope(client: AsyncClient, w: dict[str, Any]) -> None:
    p1 = await recs(client, w["backend_cand"], page_size=3)
    p2 = await recs(client, w["backend_cand"], page_size=3, page=2)
    assert (p1["page"], p1["page_size"], p1["total"], p1["pages"], len(p1["items"])) == (1, 3, 4, 2, 3) and len(p2["items"]) == 1
    assert not set(titles(p1)) & set(titles(p2))
    assert (await recs(client, w["backend_cand"], page=9))["items"] == []
    assert (await recs(client, w["backend_cand"], page_size=12))["page_size"] == 12
    default = await recs(client, w["backend_cand"])
    assert default["page_size"] == 20


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"min_score": 1.1}, {"min_score": -0.1}, {"sort": "random"}, {"skill_id": "nope"}, {"location": "x" * 101}])
async def test_invalid_parameters(client: AsyncClient, w: dict[str, Any], params: dict[str, Any]) -> None:
    assert_error(await client.get(RECS, headers=w["backend_cand"]["h"], params=params), 422, "VALIDATION_ERROR")


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
    assert titles(other)[0] == "Frontend Developer", "another candidate never receives a cached list built for someone else"
    assert cache.hits == hits + 1


# --- exclusions (each test builds its own small world) -------------------------------------------------------------------------------------------------------------------


async def mini_world(client: AsyncClient) -> dict[str, Any]:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    live = await create_job(client, rec, title="Live Backend Role", publish=True)
    other = await create_job(client, rec, title="Second Backend Role", publish=True)
    return {"rec": rec, "cand": cand, "live": live, "other": other}


async def test_closing_a_job_removes_it_from_recommendations(client: AsyncClient) -> None:
    w = await mini_world(client)
    assert set(titles(await recs(client, w["cand"]))) == {"Live Backend Role", "Second Backend Role"}
    await client.post(f"{API}/jobs/{w['live']['id']}/close", headers=w["rec"]["h"])
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]


@pytest.mark.parametrize("status", ["PAUSED", "CLOSED", "ARCHIVED", "DRAFT"])
async def test_unpublished_jobs_are_never_recommended(client: AsyncClient, status: str) -> None:
    w = await mini_world(client)
    await set_job_status(w["live"]["id"], status)  # leaves the (now stale) match row behind on purpose
    assert await scalar("SELECT count(*) FROM candidate_job_matches WHERE job_id = :j", j=uuid.UUID(w["live"]["id"])) == 1
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]


async def test_jobs_past_their_deadline_are_not_recommended(client: AsyncClient) -> None:
    w = await mini_world(client)
    await expire_deadline(w["live"]["id"])
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]


async def test_pausing_and_resuming_toggles_recommendations(client: AsyncClient) -> None:
    w = await mini_world(client)
    await client.post(f"{API}/jobs/{w['live']['id']}/pause", headers=w["rec"]["h"])
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]
    await client.post(f"{API}/jobs/{w['live']['id']}/resume", headers=w["rec"]["h"])
    assert set(titles(await recs(client, w["cand"]))) == {"Live Backend Role", "Second Backend Role"}


async def test_applied_jobs_are_not_recommended_until_the_application_is_withdrawn(client: AsyncClient) -> None:
    w = await mini_world(client)
    app = await apply_job(client, w["cand"], w["live"]["id"])
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]
    await client.post(f"{API}/applications/{app['id']}/withdraw", headers=w["cand"]["h"])
    assert set(titles(await recs(client, w["cand"]))) == {"Live Backend Role", "Second Backend Role"}
    await apply_job(client, w["cand"], w["live"]["id"])
    assert titles(await recs(client, w["cand"])) == ["Second Backend Role"]


async def test_opting_out_of_the_marketplace_does_not_switch_recommendations_off(client: AsyncClient) -> None:
    w = await mini_world(client)
    await client.patch(f"{API}/candidates/me", headers=w["cand"]["h"], json={"is_searchable": False})
    assert set(titles(await recs(client, w["cand"]))) == {"Live Backend Role", "Second Backend Role"}


async def test_jobs_published_after_the_profile_and_profiles_created_after_the_jobs_both_get_scored(client: AsyncClient) -> None:
    rec = await register_employer(client)
    early_job = await create_job(client, rec, title="Early Backend Role", publish=True)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)  # profile completed after the job exists -> candidate-side run
    late_job = await create_job(client, rec, title="Late Backend Role", publish=True)  # job published after the profile -> job-side run
    assert set(titles(await recs(client, cand))) == {"Early Backend Role", "Late Backend Role"}
    assert early_job["id"] != late_job["id"]


async def test_a_candidate_without_matches_yet_gets_a_helpful_hint(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    body = await recs(client, cand)  # profile ready, but there is no job at all
    assert body["items"] == [] and body["total"] == 0 and body["meta"]["profile_ready"] is True and body["meta"]["hint"]
    assert rec


async def test_unrelated_candidates_still_see_everything_but_ranked_low(client: AsyncClient) -> None:
    rec = await register_employer(client)
    await create_job(client, rec, title="Backend Role For Nurses", publish=True)
    nurse = await register_candidate(client)
    await nurse_profile(client, nurse)
    body = await recs(client, nurse)
    assert titles(body) == ["Backend Role For Nurses"] and body["items"][0]["match"]["band"] == "WEAK"
