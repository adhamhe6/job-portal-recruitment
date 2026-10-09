"""Which jobs are never recommended (closed, paused, expired, already applied ...) - each test builds its own small world."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import create_job, fill_backend_profile, register_candidate, register_employer
from tests.helpers_spine import (  # noqa: F401
    API,
    apply_job,
    expire_deadline,
    fast_argon,
    nurse_profile,
    scalar,
    set_job_status,
)

pytestmark = pytest.mark.integration

RECS = f"{API}/recommendations/jobs"


async def recs(client: AsyncClient, who: dict[str, Any], **params: Any) -> dict[str, Any]:
    r = await client.get(RECS, headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def titles(body: dict[str, Any]) -> list[str]:
    return [i["job"]["title"] for i in body["items"]]


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
    assert (
        await scalar(
            "SELECT count(*) FROM candidate_job_matches WHERE job_id = :j", j=uuid.UUID(w["live"]["id"])
        )
        == 1
    )
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


async def test_applied_jobs_are_not_recommended_until_the_application_is_withdrawn(
    client: AsyncClient,
) -> None:
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


async def test_jobs_published_after_the_profile_and_profiles_created_after_the_jobs_both_get_scored(
    client: AsyncClient,
) -> None:
    rec = await register_employer(client)
    early_job = await create_job(client, rec, title="Early Backend Role", publish=True)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)  # profile completed after the job exists -> candidate-side run
    late_job = await create_job(
        client, rec, title="Late Backend Role", publish=True
    )  # job published after the profile -> job-side run
    assert set(titles(await recs(client, cand))) == {"Early Backend Role", "Late Backend Role"}
    assert early_job["id"] != late_job["id"]


async def test_a_candidate_without_matches_yet_gets_a_helpful_hint(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    await fill_backend_profile(client, cand)
    body = await recs(client, cand)  # profile ready, but there is no job at all
    assert (
        body["items"] == []
        and body["total"] == 0
        and body["meta"]["profile_ready"] is True
        and body["meta"]["hint"]
    )
    assert rec


async def test_unrelated_candidates_still_see_everything_but_ranked_low(client: AsyncClient) -> None:
    rec = await register_employer(client)
    await create_job(client, rec, title="Backend Role For Nurses", publish=True)
    nurse = await register_candidate(client)
    await nurse_profile(client, nurse)
    body = await recs(client, nurse)
    assert titles(body) == ["Backend Role For Nurses"] and body["items"][0]["match"]["band"] == "WEAK"
