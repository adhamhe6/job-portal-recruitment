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
