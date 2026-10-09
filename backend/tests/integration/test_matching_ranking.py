"""Ranked candidates, match explanations and persistence of scores (shared read-only world)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.db.database import get_sessionmaker
from app.matching.embedder import get_embedder
from app.matching.loaders import load_candidate_features, load_job_features
from app.matching.representation import embed_components
from tests.helpers import add_staff, create_job, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, backend_world, shared_world, sql, walk

pytestmark = pytest.mark.integration

RANK = f"{API}/matches/jobs"


async def build(client: AsyncClient) -> dict[str, Any]:
    w = await backend_world(client)
    w["outsider"] = await register_employer(client, "Outsider Matching Co")
    w["hm"] = await add_staff(client, w["rec"], "HIRING_MANAGER")
    w["hm_assigned"] = None
    # a second, unassigned colleague and an applicant who opted out of the marketplace
    return w


@pytest.fixture(scope="module")
async def _world(migrated_db: None, seeded_ontology: None):  # type: ignore[no-untyped-def]
    async with shared_world(build) as world:
        yield world


@pytest.fixture
def client(_world):  # type: ignore[no-untyped-def]
    return _world[0]


@pytest.fixture
def w(_world):  # type: ignore[no-untyped-def]
    return _world[1]


async def ranked(client: AsyncClient, who: dict[str, Any], job_id: str, **params: Any) -> dict[str, Any]:
    r = await client.get(f"{RANK}/{job_id}/candidates", headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def first_names(body: dict[str, Any]) -> list[str]:
    return [i["display_name"].split()[0] for i in body["items"]]


# --- ranking -----------------------------------------------------------------------------------------------------------------------------------


async def test_a_strong_backend_candidate_outranks_a_frontend_candidate_and_a_nurse(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    body = await ranked(client, w["rec"], w["job"]["id"])
    assert first_names(body) == ["Alex", "Bianca", "Julia"]
    scores = [i["overall_score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True) and all(0.0 <= s <= 1.0 for s in scores)
    alex, bianca, julia = body["items"]
    assert alex["overall_score"] > 0.7 and alex["band"] in {"STRONG", "GOOD"}
    assert julia["overall_score"] < 0.45 and julia["band"] == "WEAK"
    assert alex["overall_score"] - bianca["overall_score"] > 0.15
    assert alex["overall_percent"] == round(alex["overall_score"] * 100)
    assert body["total"] == 3 and body["page"] == 1 and body["meta"]["total_scored"] == 3


async def test_explanation_fields_for_the_strong_candidate(client: AsyncClient, w: dict[str, Any]) -> None:
    alex = (await ranked(client, w["rec"], w["job"]["id"]))["items"][0]
    assert set(alex["strong_skills"]) == {"Python", "FastAPI", "PostgreSQL", "Docker", "Redis"}
    assert (
        alex["missing_required"] == []
        and alex["missing_preferred"] == ["Kubernetes"]
        and alex["related_skills"] == []
    )
    assert alex["experience_text"] == "5 years vs 3+ years required"
    assert alex["semantic_band"] in {"HIGH", "MEDIUM"}
    assert alex["summary"].startswith(alex["band"].title() + " match; covers 4 of 4 required skills")
    assert (
        alex["breakdown"]["required_skills"] == 1.0
        and alex["breakdown"]["preferred_skills"] == 0.5
        and alex["breakdown"]["experience"] == 1.0
    )
    assert 0.0 <= alex["breakdown"]["semantic"] <= 1.0 and alex["breakdown"]["education"] is None, (
        "no education requirement on this job"
    )
    assert (
        alex["has_applied"] is False
        and alex["application_id"] is None
        and alex["access"] == "PROFILE"
        and alex["stale"] is False
    )


async def test_explanation_for_the_candidate_with_nothing_in_common(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    julia = (await ranked(client, w["rec"], w["job"]["id"]))["items"][2]
    assert julia["strong_skills"] == [] and set(julia["missing_required"]) == {
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
    }
    assert julia["breakdown"]["required_skills"] == 0.0
    detail = (
        await client.get(
            f"{RANK}/{w['job']['id']}/candidates/{w['nurse']['candidate_id']}", headers=w["rec"]["h"]
        )
    ).json()
    assert detail["explanation"]["qualification_floor_applied"] is True and detail["overall_score"] <= 0.45


async def test_the_scores_are_persisted_with_versions_and_hashes(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    await ranked(client, w["rec"], w["job"]["id"])
    rows = await sql(
        "SELECT overall_score, semantic_score, raw_cosine, required_skill_score, matching_version, embedding_model, embedding_version, job_hash, candidate_hash, generated_at, explanation "
        "FROM candidate_job_matches WHERE job_id = :j",
        j=uuid.UUID(w["job"]["id"]),
    )
    assert len(rows) == 3
    emb = get_embedder()
    for r in rows:
        assert 0 <= r[0] <= 1 and 0 <= r[1] <= 1 and -1 <= r[2] <= 1
        assert (r[4], r[5], r[6]) == (get_settings().matching_version, emb.name, emb.version)
        assert len(r[7]) == 64 and len(r[8]) == 64 and r[9] is not None
        assert r[10]["band"] and set(r[10]) >= {
            "skills",
            "experience",
            "education",
            "semantic",
            "weights",
            "summary",
        }
    assert len({r[7] for r in rows}) == 1, "one job hash for the job"
    assert len({r[8] for r in rows}) == 3, "one candidate hash per candidate"
    # the stored hashes are what the loaders compute right now
    async with get_sessionmaker()() as s:
        jf = (await load_job_features(s, [uuid.UUID(w["job"]["id"])]))[uuid.UUID(w["job"]["id"])]
    assert rows[0][7] == jf.feature_hash()


async def test_match_detail_for_staff_carries_the_full_explanation(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    r = await client.get(
        f"{RANK}/{w['job']['id']}/candidates/{w['backend']['candidate_id']}", headers=w["rec"]["h"]
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert (
        d["job_title"] == "Backend Engineer"
        and d["candidate_name"] == "Alex Backend"
        and d["matching_version"] == "v1"
    )
    assert d["embedding_model"] == get_embedder().name and d["embedding_version"] == get_embedder().version
    e = d["explanation"]
    assert set(e["weights"]) == {"semantic", "required", "preferred", "experience", "education", "preference"}
    assert e["semantic"]["cosine"] is not None and e["skills"]["required"]["coverage"] == 1.0
    assert set(d["breakdown"]) == {
        "semantic",
        "required_skills",
        "preferred_skills",
        "experience",
        "education",
        "preferences",
    }


async def test_filters_and_pagination_on_ranked_candidates(client: AsyncClient, w: dict[str, Any]) -> None:
    job = w["job"]["id"]
    assert first_names(await ranked(client, w["rec"], job, min_score=0.6)) == ["Alex"]
    assert first_names(await ranked(client, w["rec"], job, min_experience=4)) == ["Alex", "Julia"]
    assert first_names(await ranked(client, w["rec"], job, location="hamburg")) == ["Julia"]
    assert first_names(await ranked(client, w["rec"], job, location="%")) == []
    assert first_names(await ranked(client, w["rec"], job, availability="IMMEDIATELY")) == []
    sid = (await client.get(f"{API}/skills", params={"q": "React"})).json()["items"][0]["id"]
    assert first_names(await ranked(client, w["rec"], job, skill_id=sid)) == ["Bianca"]
    p1 = await ranked(client, w["rec"], job, page_size=2)
    p2 = await ranked(client, w["rec"], job, page_size=2, page=2)
    assert (
        first_names(p1) == ["Alex", "Bianca"]
        and first_names(p2) == ["Julia"]
        and p1["pages"] == 2
        and p2["total"] == 3
    )
    assert first_names(await ranked(client, w["rec"], job, page=5)) == []
    for bad in (
        {"min_score": 1.2},
        {"min_experience": -1},
        {"page_size": 101},
        {"skill_id": "x"},
        {"availability": "SOON"},
    ):
        assert_error(
            await client.get(f"{RANK}/{job}/candidates", headers=w["rec"]["h"], params=bad),
            422,
            "VALIDATION_ERROR",
        )


# --- authorization -------------------------------------------------------------------------------------------------------------------------------------


async def test_other_tenants_cannot_see_rankings_or_details(client: AsyncClient, w: dict[str, Any]) -> None:
    job, cand = w["job"]["id"], w["backend"]["candidate_id"]
    assert_error(
        await client.get(f"{RANK}/{job}/candidates", headers=w["outsider"]["h"]), 404, "JOB_NOT_FOUND"
    )
    assert_error(
        await client.get(f"{RANK}/{job}/candidates/{cand}", headers=w["outsider"]["h"]), 404, "JOB_NOT_FOUND"
    )
    assert_error(await client.post(f"{RANK}/{job}/refresh", headers=w["outsider"]["h"]), 404, "JOB_NOT_FOUND")
    assert_error(
        await client.get(f"{RANK}/{uuid.uuid4()}/candidates", headers=w["rec"]["h"]), 404, "JOB_NOT_FOUND"
    )
    assert_error(
        await client.get(f"{RANK}/{job}/candidates/{uuid.uuid4()}", headers=w["rec"]["h"]),
        404,
        "CANDIDATE_NOT_FOUND",
    )


async def test_candidates_and_anonymous_users_have_no_access_to_rankings(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    job, cand = w["job"]["id"], w["backend"]["candidate_id"]
    for who in (w["backend"], w["frontend"]):
        for url in (f"{RANK}/{job}/candidates", f"{RANK}/{job}/candidates/{cand}"):
            assert_error(await client.get(url, headers=who["h"]), 403, "FORBIDDEN")
        assert_error(await client.post(f"{RANK}/{job}/refresh", headers=who["h"]), 403, "FORBIDDEN")
    assert_error(await client.get(f"{RANK}/{job}/candidates"), 401, "UNAUTHORIZED")


async def test_hiring_managers_see_rankings_only_for_their_jobs_and_cannot_run_matching(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    rec = w["rec"]
    mine = await create_job(
        client, rec, title="Assigned To HM", publish=True, hiring_manager_id=w["hm"]["id"]
    )
    body = await ranked(client, w["hm"], mine["id"])
    assert body["meta"]["job_id"] == mine["id"]
    assert_error(
        await client.get(f"{RANK}/{w['job']['id']}/candidates", headers=w["hm"]["h"]), 404, "JOB_NOT_FOUND"
    )
    assert_error(await client.post(f"{RANK}/{mine['id']}/refresh", headers=w["hm"]["h"]), 403, "FORBIDDEN")
    detail = await client.get(
        f"{RANK}/{mine['id']}/candidates/{w['backend']['candidate_id']}", headers=w["hm"]["h"]
    )
    assert_error(
        detail, 404, "CANDIDATE_NOT_FOUND"
    )  # a marketplace candidate is not reachable for a hiring manager without an application


# --- candidate-facing explanation --------------------------------------------------------------------------------------------------------------------------


async def test_the_candidate_facing_explanation_hides_internals(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    r = await client.get(f"{API}/matches/me/jobs/{w['job']['id']}", headers=w["backend"]["h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "overall_percent",
        "band",
        "summary",
        "matched_skills",
        "related_skills",
        "missing_required",
        "missing_preferred",
        "experience_text",
        "experience_status",
        "semantic_band",
        "generated_at",
    }
    assert set(body["matched_skills"]) == {"Python", "FastAPI", "PostgreSQL", "Docker", "Redis"} and body[
        "missing_preferred"
    ] == ["Kubernetes"]
    assert body["experience_status"] == "MEETS"
    leaked = {k for k, _ in walk(body)} & {
        "cosine",
        "raw_cosine",
        "weights",
        "semantic_score",
        "breakdown",
        "candidate_hash",
        "job_hash",
        "embedding_model",
        "score",
        "overall_score",
    }
    assert not leaked, leaked
    assert "cosine" not in json.dumps(body).lower() and "weight" not in json.dumps(body).lower()
    other = (await client.get(f"{API}/matches/me/jobs/{w['job']['id']}", headers=w["nurse"]["h"])).json()
    assert other["missing_required"] and other["matched_skills"] == []
    assert_error(
        await client.get(f"{API}/matches/me/jobs/{w['job']['id']}", headers=w["rec"]["h"]), 403, "FORBIDDEN"
    )
    assert_error(
        await client.get(f"{API}/matches/me/jobs/{uuid.uuid4()}", headers=w["backend"]["h"]),
        404,
        "JOB_NOT_FOUND",
    )


# --- what is (not) embedded --------------------------------------------------------------------------------------------------------------------------------------


async def test_no_identity_or_contact_data_reaches_the_embedded_text(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    cand = await register_candidate(client, first="Maria", last="Gonzalez-Schmidt")
    await client.patch(
        f"{API}/auth/me",
        headers=cand["h"],
        json={"phone": "+49 170 5559999"},
    )
    await client.patch(
        f"{API}/candidates/me",
        headers=cand["h"],
        json={
            "headline": "Backend engineer",
            "summary": "Backend engineer building Python services with PostgreSQL for seven years.",
            "location": "Berlin, Germany",
            "years_experience": 7,
            "linkedin_url": "https://linkedin.com/in/maria-gonzalez",
            "github_url": "https://github.com/maria",
            "portfolio_url": "https://maria.example.com",
            "expected_salary": 123456,
            "availability": "IMMEDIATELY",
            "remote_preference": "HYBRID",
        },
    )
    await client.post(f"{API}/candidates/me/skills", headers=cand["h"], json={"name": "Python"})
    cid = uuid.UUID(cand["candidate_id"])
    async with get_sessionmaker()() as s:
        features = (await load_candidate_features(s, [cid]))[cid]
    blob = " ".join(features.components().values()).lower()
    for needle in (
        "maria",
        "gonzalez",
        "schmidt",
        cand["email"].lower(),
        "5559999",
        "linkedin",
        "github",
        "maria.example",
        "123456",
        "immediately",
        "berlin",
    ):
        assert needle not in blob, needle
    assert "python" in blob and "backend engineer" in blob
    # ... and the stored vector is exactly the embedding of that text, i.e. nothing else was mixed in
    stored = np.array(
        (await sql("SELECT embedding::text FROM candidate_profiles WHERE id = :c", c=cid))[0][0]
        .strip("[]")
        .split(","),
        dtype=np.float32,
    )
    expected = await embed_components(features.components())
    assert np.allclose(stored, expected, atol=1e-5)


async def test_job_text_contains_no_recruiter_or_company_identity(
    client: AsyncClient, w: dict[str, Any]
) -> None:
    jid = uuid.UUID(w["job"]["id"])
    async with get_sessionmaker()() as s:
        features = (await load_job_features(s, [jid]))[jid]
    blob = " ".join(features.components().values()).lower()
    assert w["rec"]["email"].lower() not in blob and "riley" not in blob and "recruiter" not in blob
    assert "backend engineer" in blob and "python" in blob
