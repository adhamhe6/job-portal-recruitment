"""Helpers for the interview / reporting / admin test modules (built on tests.helpers; nothing is mocked)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text

from app.db.database import get_sessionmaker
from tests.helpers import add_staff, create_job, register_candidate, register_employer

API = "/api/v1"


def utc_slot(
    days: int = 2, hour: int = 9, minutes: int = 60, *, base: datetime | None = None
) -> tuple[str, str]:
    """(start, end) ISO strings in UTC, ``days`` from today at ``hour``:00."""
    ref = base or datetime.now(UTC)
    start = ref.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


async def set_status(client: AsyncClient, rec: dict[str, Any], application_id: str, *statuses: str) -> None:
    for st in statuses:
        r = await client.post(
            f"{API}/applications/{application_id}/status", headers=rec["h"], json={"status": st}
        )
        assert r.status_code == 200, r.text


async def apply_to(client: AsyncClient, cand: dict[str, Any], job_id: str, **extra: Any) -> dict[str, Any]:
    r = await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def company_with_staff(client: AsyncClient) -> dict[str, Any]:
    """A company with: admin recruiter ``rec``, a second recruiter ``rec2`` and a hiring manager ``hm``."""
    rec = await register_employer(client)
    rec2 = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    return {"rec": rec, "rec2": rec2, "hm": hm}


async def shortlisted(
    client: AsyncClient,
    rec: dict[str, Any],
    *,
    job: dict[str, Any] | None = None,
    cand: dict[str, Any] | None = None,
    advance: bool = True,
) -> dict[str, Any]:
    """Returns {job, cand, app}; the application is SHORTLISTED unless ``advance`` is False."""
    job = job or await create_job(client, rec, publish=True, title=f"Role {uuid.uuid4().hex[:8]}")
    cand = cand or await register_candidate(client)
    app = await apply_to(client, cand, job["id"])
    if advance:
        await set_status(client, rec, app["id"], "SCREENING", "SHORTLISTED")
    return {"job": job, "cand": cand, "app": app}


async def schedule(
    client: AsyncClient,
    rec: dict[str, Any],
    application_id: str,
    interviewers: list[dict[str, Any]],
    *,
    start: str | None = None,
    end: str | None = None,
    **overrides: Any,
) -> Response:
    s, e = utc_slot()
    body: dict[str, Any] = {
        "application_id": application_id,
        "interview_type": "TECHNICAL",
        "start_at": start or s,
        "end_at": end or e,
        "timezone": "UTC",
        "meeting_url": "https://meet.example.com/room-1",
        "participants": [
            {"user_id": u["id"] if "id" in u else u["user"]["id"], "role": "INTERVIEWER"}
            for u in interviewers
        ],
    }
    body.update(overrides)
    return await client.post(f"{API}/interviews", headers=rec["h"], json=body)


def uid(account: dict[str, Any]) -> str:
    return str(account["id"] if "id" in account else account["user"]["id"])


async def sql(statement: str, **params: Any) -> list[Any]:
    """Direct SQL against the test database (used only to age data deterministically)."""
    async with get_sessionmaker()() as s:
        result = await s.execute(text(statement), params)
        rows = list(result.all()) if result.returns_rows else []
        await s.commit()
        return rows


async def age_application(application_id: str, *, applied_days_ago: int) -> None:
    """Move an application (and its history) back in time so period filters are deterministic."""
    await sql(
        "UPDATE applications SET applied_at = applied_at - make_interval(days => :d), "
        "status_changed_at = status_changed_at - make_interval(days => :d) WHERE id = :id",
        d=applied_days_ago,
        id=uuid.UUID(application_id),
    )
    await sql(
        "UPDATE application_status_history SET created_at = created_at - make_interval(days => :d) WHERE application_id = :id",
        d=applied_days_ago,
        id=uuid.UUID(application_id),
    )


# --------------------------------------------------------------------------------------------------------------------
# deterministic reporting dataset
# --------------------------------------------------------------------------------------------------------------------
async def bust_cache() -> None:
    """Direct SQL changes bypass the cache domains; drop Redis so the next report is recomputed."""
    from app.cache.redis_cache import get_redis

    await get_redis().flushdb()


async def put_match(job_id: str, candidate_id: str, score: float, summary: str = "Good overall fit") -> None:
    await sql(
        "INSERT INTO candidate_job_matches (id, job_id, candidate_id, overall_score, semantic_score, raw_cosine, explanation, "
        "matching_version, embedding_model, embedding_version, job_hash, candidate_hash, generated_at) "
        "VALUES (gen_random_uuid(), :j, :c, :s, :s, :s, CAST(:e AS jsonb), 'v1', 'wordllama-l2-supercat-256', 'v1', 'h', 'h', now())",
        j=uuid.UUID(job_id), c=uuid.UUID(candidate_id), s=score, e='{"summary": "%s"}' % summary,
    )  # fmt: skip


async def build_pipeline(client: AsyncClient) -> dict[str, Any]:
    """A small company pipeline whose report numbers can be computed by hand.

    Jobs (company A): J1 + J2 PUBLISHED (J2 deadline in 3 days, assigned to the hiring manager), J3 DRAFT.
    Applications, all received today (current status in brackets):
      c1 J1 SCREENING>SHORTLISTED>INTERVIEW>OFFER>HIRED   (HIRED)
      c2 J1 SCREENING>SHORTLISTED>INTERVIEW>REJECTED      (REJECTED)
      c3 J1 SCREENING                                     (SCREENING, source SEARCH)
      c4 J2 SCREENING>SHORTLISTED, interview in 2 days    (INTERVIEW)
      c5 J2                                               (APPLIED)
      c6 J2 withdrawn by the candidate                    (WITHDRAWN)
      c7 J2 SCREENING>SHORTLISTED                         (SHORTLISTED, source REFERRAL)
    Stored match scores: c1/J1 .91, c2/J1 .80, c3/J1 .62, c5/J1 .70, c4/J2 .40, c5/J2 .20, c6/J2 .66, c1/J3 .99 (draft),
    c5/J3 .99 (draft) and z/J1 .95 where z never applied and opted out of the marketplace.
    """
    co = await company_with_staff(client)
    rec = co["rec"]
    j1 = await create_job(client, rec, publish=True, title="Dash Job One")
    j2 = await create_job(
        client, rec, publish=True, title="Dash Job Two", hiring_manager_id=co["hm"]["id"],
        application_deadline=(datetime.now().date() + timedelta(days=3)).isoformat(),
    )  # fmt: skip
    j3 = await create_job(client, rec, title="Dash Draft")
    cands = {f"c{i}": await register_candidate(client, first=f"Cand{i}", last="Tester") for i in range(1, 8)}
    apps: dict[str, str] = {}
    plan = {
        "c1": (j1, "DIRECT", ["SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER", "HIRED"]),
        "c2": (j1, "DIRECT", ["SCREENING", "SHORTLISTED", "INTERVIEW", "REJECTED"]),
        "c3": (j1, "SEARCH", ["SCREENING"]),
        "c4": (j2, "DIRECT", ["SCREENING", "SHORTLISTED"]),
        "c5": (j2, "DIRECT", []),
        "c6": (j2, "DIRECT", []),
        "c7": (j2, "REFERRAL", ["SCREENING", "SHORTLISTED"]),
    }
    for key, (job, source, path) in plan.items():
        apps[key] = (await apply_to(client, cands[key], job["id"], source=source))["id"]
        if path:
            await set_status(client, rec, apps[key], *path)
    wd = await client.post(f"{API}/applications/{apps['c6']}/withdraw", headers=cands["c6"]["h"])
    assert wd.status_code == 200, wd.text
    s, e = utc_slot(days=2, hour=10)
    iv = await schedule(client, rec, apps["c4"], [co["rec2"]], start=s, end=e)
    assert iv.status_code == 201, iv.text
    zed = await register_candidate(client, first="Zed", last="Hidden")
    opt_out = await client.patch(f"{API}/candidates/me", headers=zed["h"], json={"is_searchable": False})
    assert opt_out.status_code == 200, opt_out.text
    cid = {k: v["candidate_id"] for k, v in cands.items()}
    for job, who, score in (
        (j1, "c1", 0.91), (j1, "c2", 0.80), (j1, "c3", 0.62), (j1, "c5", 0.70), (j2, "c4", 0.40), (j2, "c5", 0.20),
        (j2, "c6", 0.66), (j3, "c1", 0.99), (j3, "c5", 0.99),
    ):  # fmt: skip
        await put_match(job["id"], cid[who], score)
    await put_match(j1["id"], zed["candidate_id"], 0.95)
    await bust_cache()
    return {"co": co, "rec": rec, "rec2": co["rec2"], "hm": co["hm"], "j1": j1, "j2": j2, "j3": j3, "cands": cands, "apps": apps, "zed": zed, "interview": iv.json()}
