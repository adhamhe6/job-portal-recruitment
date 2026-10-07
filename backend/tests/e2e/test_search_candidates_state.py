"""Candidate search reacts immediately to privacy toggles, applications and profile edits."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import create_job, fill_backend_profile, register_candidate, register_employer
from tests.helpers_spine import API, apply_job, fast_argon  # noqa: F401

pytestmark = pytest.mark.e2e

SEARCH = f"{API}/search/candidates"
ME = f"{API}/candidates/me"


async def found(client: AsyncClient, rec: dict[str, Any], **params: Any) -> set[str]:
    r = await client.get(SEARCH, params=params, headers=rec["h"])
    assert r.status_code == 200, r.text
    return {i["id"] for i in r.json()["items"]}


async def test_opting_out_and_back_in_is_reflected_immediately(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client, first="Toggle", last="Person")
    await fill_backend_profile(client, cand)
    assert cand["candidate_id"] in await found(client, rec, q="fastapi")
    await client.patch(ME, headers=cand["h"], json={"is_searchable": False})
    assert cand["candidate_id"] not in await found(client, rec, q="fastapi")
    assert cand["candidate_id"] not in await found(client, rec)
    await client.patch(ME, headers=cand["h"], json={"is_searchable": True})
    assert cand["candidate_id"] in await found(client, rec, q="fastapi")


async def test_an_application_makes_an_opted_out_candidate_visible_to_that_company_only(client: AsyncClient) -> None:
    rec, other = await register_employer(client), await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    await client.patch(ME, headers=cand["h"], json={"is_searchable": False, "headline": "Quiet specialist"})
    assert cand["candidate_id"] not in await found(client, rec)
    await apply_job(client, cand, job["id"])
    assert cand["candidate_id"] in await found(client, rec)
    assert cand["candidate_id"] not in await found(client, other)
    row = (await client.get(SEARCH, headers=rec["h"])).json()["items"][0]
    assert row["access"] == "FULL"


async def test_profile_edits_change_what_the_candidate_can_be_found_by(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    skill = (await client.post(f"{ME}/skills", headers=cand["h"], json={"name": "Kubernetes"})).json()
    assert cand["candidate_id"] in await found(client, rec, q="kubernetes")
    assert cand["candidate_id"] in await found(client, rec, skill=["k8s"])
    await client.delete(f"{ME}/skills/{skill['id']}", headers=cand["h"])
    assert cand["candidate_id"] not in await found(client, rec, q="kubernetes")
    assert cand["candidate_id"] not in await found(client, rec, skill=["k8s"])
    await client.patch(ME, headers=cand["h"], json={"headline": "Zymurgy specialist"})
    assert cand["candidate_id"] in await found(client, rec, q="zymurgy")


async def test_rejected_resume_suggestions_are_not_searchable_skills(client: AsyncClient) -> None:
    from tests.helpers_spine import scalar, sql
    import uuid

    rec = await register_employer(client)
    cand = await register_candidate(client)
    cid = uuid.UUID(cand["candidate_id"])
    sid = await scalar("SELECT id FROM skills WHERE name = 'Terraform'")
    await sql("INSERT INTO candidate_skills (candidate_id, skill_id, source, status) VALUES (:c, :s, 'RESUME', 'REJECTED')", c=cid, s=sid)
    assert cand["candidate_id"] not in await found(client, rec, skill=["terraform"])
