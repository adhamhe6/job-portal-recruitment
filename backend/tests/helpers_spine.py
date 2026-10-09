"""Helpers for the spine test-suite (auth, users, companies, skills, candidates, jobs, search, applications,
matching, tasks, cache). Built on ``tests.helpers``; nothing here mocks the database or Redis.

Import the ``fast_argon`` fixture into a test module to make password hashing cheap (Argon2 with minimal cost) -
every API test registers several accounts and the production parameters would dominate the run time:

    from tests.helpers_spine import fast_argon  # noqa: F401  (autouse fixture)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

from app.core import security
from app.db.database import get_sessionmaker
from tests.helpers import PASSWORD, add_staff, create_job, register_candidate, register_employer

API = "/api/v1"
ERROR_KEYS = {"code", "message", "details", "request_id"}


@pytest.fixture(autouse=True)
def fast_argon(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cheap Argon2 parameters for API tests (unit tests of the real parameters live in tests/unit/test_security.py)."""
    monkeypatch.setattr(security, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    return


# --- raw database access ---------------------------------------------------------------------------------------------


async def sql(statement: str, **params: Any) -> list[Any]:
    """Run SQL against the test database and commit (used to arrange states the API deliberately cannot reach)."""
    async with get_sessionmaker()() as s:
        result = await s.execute(text(statement), params)
        rows = list(result.all()) if result.returns_rows else []
        await s.commit()
        return rows


async def scalar(statement: str, **params: Any) -> Any:
    rows = await sql(statement, **params)
    return rows[0][0] if rows else None


def U(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def set_job_status(job_id: str, status: str) -> None:
    """Force a job into a status, keeping the ``published_at_set`` invariant intact."""
    sets = ["status = :s"]
    if status != "DRAFT":
        sets.append("published_at = COALESCE(published_at, now())")
    if status in ("CLOSED", "ARCHIVED"):
        sets.append("closed_at = COALESCE(closed_at, now())")
    await sql(f"UPDATE jobs SET {', '.join(sets)} WHERE id = :id", s=status, id=U(job_id))


async def expire_deadline(job_id: str, days_ago: int = 1) -> None:
    await sql(
        "UPDATE jobs SET application_deadline = current_date - CAST(:d AS integer) WHERE id = :id",
        d=days_ago,
        id=U(job_id),
    )


async def set_application_status(application_id: str, status: str) -> None:
    await sql("UPDATE applications SET status = :s WHERE id = :id", s=status, id=U(application_id))


async def tasks(task_type: str | None = None) -> list[Any]:
    where = "WHERE type = :t" if task_type else ""
    return await sql(
        "SELECT id, type, status, error_code, error_message, attempts, dedupe_key, params, result FROM background_tasks "
        f"{where} ORDER BY created_at, id",
        **({"t": task_type} if task_type else {}),
    )


# --- HTTP conveniences -------------------------------------------------------------------------------------------------


def assert_error(resp: Response, status: int, code: str | None = None) -> dict[str, Any]:
    """Every error response uses the same envelope: ``{"error": {code, message, details, request_id}}``."""
    assert resp.status_code == status, f"{resp.status_code} != {status}: {resp.text}"
    body = resp.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) == ERROR_KEYS, err
    assert isinstance(err["code"], str) and isinstance(err["message"], str) and err["message"]
    assert resp.headers.get("x-request-id")
    assert err["request_id"] == resp.headers["x-request-id"]
    if code is not None:
        assert err["code"] == code, err
    return err  # type: ignore[no-any-return]


def set_cookie_headers(resp: Response) -> list[str]:
    return resp.headers.get_list("set-cookie")


def refresh_cookie(resp: Response, name: str = "tl_refresh") -> str:
    for header in set_cookie_headers(resp):
        if header.startswith(f"{name}="):
            return header.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no {name} cookie in {set_cookie_headers(resp)}")


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> Response:
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


async def refresh(client: AsyncClient, token: str) -> Response:
    return await client.post(f"{API}/auth/refresh", headers={"Cookie": f"tl_refresh={token}"})


@asynccontextmanager
async def client_from(ip: str) -> AsyncIterator[AsyncClient]:
    """An ASGI client that appears to come from ``ip`` (rate limits are per client address)."""
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    app.state.dispatcher = InlineDispatcher()
    async with AsyncClient(transport=ASGITransport(app=app, client=(ip, 5000)), base_url="http://test") as c:
        yield c


def walk(value: Any) -> Iterator[tuple[str, Any]]:
    """Yield every ``(key, value)`` pair in a JSON document."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def future(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# --- scenario builders ---------------------------------------------------------------------------------------------------


async def nurse_profile(client: AsyncClient, cand: dict[str, Any], years: float = 6.0) -> None:
    """A clinical profile: nothing in common with the engineering jobs."""
    h = cand["h"]
    r = await client.patch(
        f"{API}/candidates/me",
        headers=h,
        json={
            "headline": "ICU nurse",
            "summary": "Registered nurse in an intensive care unit: patient care, medication administration and life support.",
            "location": "Hamburg, Germany",
            "years_experience": years,
            "remote_preference": "ONSITE",
        },
    )
    assert r.status_code == 200, r.text
    for name in ("Patient Care", "Critical Care", "BLS", "ACLS", "Medication Administration"):
        sr = await client.post(f"{API}/candidates/me/skills", headers=h, json={"name": name})
        assert sr.status_code == 201, sr.text
    er = await client.post(
        f"{API}/candidates/me/experiences",
        headers=h,
        json={
            "title": "ICU Nurse",
            "company_name": "City Hospital",
            "start_date": (date.today() - timedelta(days=int(years * 365))).isoformat(),
            "is_current": True,
            "description": "Cared for critically ill patients, administered medication and managed ventilators.",
        },
    )
    assert er.status_code == 201, er.text


async def company_team(client: AsyncClient, company: str | None = None) -> dict[str, Any]:
    """A company with an admin recruiter ``rec``, a second recruiter ``rec2`` and a hiring manager ``hm``."""
    rec = await register_employer(client, company)
    rec2 = await add_staff(client, rec, "RECRUITER")
    hm = await add_staff(client, rec, "HIRING_MANAGER")
    return {"rec": rec, "rec2": rec2, "hm": hm}


async def publish(client: AsyncClient, rec: dict[str, Any], job_id: str) -> dict[str, Any]:
    r = await client.post(f"{API}/jobs/{job_id}/publish", headers=rec["h"])
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def apply_job(client: AsyncClient, cand: dict[str, Any], job_id: str, **extra: Any) -> dict[str, Any]:
    r = await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def backend_world(client: AsyncClient) -> dict[str, Any]:
    """Company + published backend job + three candidates (backend, frontend, nurse) with realistic profiles."""
    from tests.helpers import fill_backend_profile, fill_frontend_profile

    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    backend = await register_candidate(client, first="Alex", last="Backend")
    frontend = await register_candidate(client, first="Bianca", last="Frontend")
    nurse = await register_candidate(client, first="Julia", last="Nurse")
    await fill_backend_profile(client, backend, years=5)
    await fill_frontend_profile(client, frontend, years=3)
    await nurse_profile(client, nurse)
    return {"rec": rec, "job": job, "backend": backend, "frontend": frontend, "nurse": nurse}


async def insert_imported_candidate(
    company_id: str,
    *,
    name: str = "Imported Person",
    email: str | None = "imported@sourced.example",
    skills: str | None = None,
    headline: str = "Backend developer",
    years: float = 6.0,
    location: str = "Berlin, Germany",
) -> str:
    """A company-sourced (IMPORTED) candidate profile, inserted directly (the import pipeline is another module)."""
    first, _, last = name.partition(" ")
    cid = uuid.uuid4()
    await sql(
        "INSERT INTO candidate_profiles (id, source, sourced_by_company_id, first_name, last_name, display_name, contact_email, contact_phone,"
        " headline, summary, location, years_experience, skills_text, is_searchable) VALUES (:id, 'IMPORTED', :c, :f, :l, :d, :e, '+49 170 0000000',"
        " :h, :s, :loc, :y, :sk, true)",
        id=cid,
        c=U(company_id),
        f=first,
        l=last or "Person",
        d=name,
        e=email,
        h=headline,
        s="Imported résumé summary with Python and PostgreSQL.",
        loc=location,
        y=years,
        sk=skills,
    )
    return str(cid)


__all__ = [
    "API",
    "PASSWORD",
    "U",
    "apply_job",
    "assert_error",
    "backend_world",
    "client_from",
    "company_team",
    "expire_deadline",
    "fast_argon",
    "future",
    "insert_imported_candidate",
    "login",
    "nurse_profile",
    "publish",
    "refresh",
    "refresh_cookie",
    "reset_database",
    "scalar",
    "seed_search_corpus",
    "set_application_status",
    "set_cookie_headers",
    "set_job_status",
    "shared_world",
    "sql",
    "tasks",
    "walk",
]


async def seed_search_corpus(client: AsyncClient) -> dict[str, Any]:
    """Eight published jobs across two companies with deliberately varied attributes. Returns ``{key: job}`` + the recruiters."""
    from tests.helpers import job_payload

    rec1 = await register_employer(client, "Alpine Software")
    rec2 = await register_employer(client, "Boreal Health")

    specs: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        (
            "python",
            rec1,
            {
                "title": "Python Developer",
                "location": "Berlin, Germany",
                "workplace_type": "REMOTE",
                "employment_type": "FULL_TIME",
                "experience_level": "MID",
                "salary_min": 60000,
                "salary_max": 80000,
                "min_experience_years": 2,
                "department": "Engineering",
                "skills": [
                    {"name": "Python"},
                    {"name": "Django"},
                    {"name": "PostgreSQL", "requirement": "PREFERRED"},
                ],
            },
        ),
        (
            "java",
            rec1,
            {
                "title": "Senior Java Engineer",
                "location": "Munich, Germany",
                "workplace_type": "HYBRID",
                "employment_type": "FULL_TIME",
                "experience_level": "SENIOR",
                "salary_min": 90000,
                "salary_max": 120000,
                "min_experience_years": 6,
                "skills": [{"name": "Java"}, {"name": "Spring Boot"}],
            },
        ),
        (
            "frontend",
            rec1,
            {
                "title": "Junior Frontend Developer",
                "location": "Hamburg, Germany",
                "workplace_type": "ONSITE",
                "employment_type": "PART_TIME",
                "experience_level": "JUNIOR",
                "salary_min": 30000,
                "salary_max": 40000,
                "min_experience_years": 0,
                "skills": [{"name": "React"}, {"name": "CSS"}],
            },
        ),
        (
            "analyst",
            rec1,
            {
                "title": "Data Analyst Intern",
                "location": "Berlin, Germany",
                "workplace_type": "ONSITE",
                "employment_type": "INTERNSHIP",
                "experience_level": "ENTRY",
                "salary_min": None,
                "salary_max": None,
                "min_experience_years": 0,
                "skills": [{"name": "SQL"}, {"name": "Excel"}],
            },
        ),
        (
            "office",
            rec2,
            {
                "title": "Office Manager",
                "location": "Paris, France",
                "workplace_type": "ONSITE",
                "employment_type": "CONTRACT",
                "experience_level": "MID",
                "salary_min": 50000,
                "salary_max": 60000,
                "min_experience_years": 3,
                "description": "Coordinate the office, vendors and travel. Some Python scripting, Python reports and Python automation are a plus, Python Python Python.",
                "skills": [{"name": "Project Management"}],
            },
        ),
        (
            "nurse",
            rec2,
            {
                "title": "ICU Nurse",
                "location": "Hamburg, Germany",
                "workplace_type": "ONSITE",
                "employment_type": "FULL_TIME",
                "experience_level": "MID",
                "salary_min": 45000,
                "salary_max": None,
                "min_experience_years": 2,
                "skills": [{"name": "Critical Care"}, {"name": "BLS"}],
            },
        ),
        (
            "devops",
            rec2,
            {
                "title": "DevOps Engineer",
                "location": "Remote - Europe",
                "workplace_type": "REMOTE",
                "employment_type": "CONTRACT",
                "experience_level": "SENIOR",
                "salary_min": None,
                "salary_max": 100000,
                "min_experience_years": 5,
                "skills": [
                    {"name": "Kubernetes"},
                    {"name": "Docker"},
                    {"name": "Python", "requirement": "PREFERRED"},
                ],
            },
        ),
        (
            "pct",
            rec2,
            {
                "title": "Sales Representative 100% Commission",
                "location": "100% Remote_Work",
                "workplace_type": "REMOTE",
                "employment_type": "FULL_TIME",
                "experience_level": "ENTRY",
                "salary_min": 20000,
                "salary_max": 30000,
                "min_experience_years": 0,
                "skills": [{"name": "Negotiation"}],
            },
        ),
    ]
    out: dict[str, Any] = {"rec1": rec1, "rec2": rec2}
    for key, rec, over in specs:
        payload = job_payload(**over)
        r = await client.post(f"{API}/jobs", headers=rec["h"], json=payload)
        assert r.status_code == 201, r.text
        out[key] = await publish(client, rec, r.json()["id"])
    return out


async def reset_database() -> None:
    """What the ``db`` fixture does before every test (kept in sync with tests/conftest.py)."""
    from app.cache.redis_cache import get_cache, get_redis
    from app.db.database import Base, get_engine

    keep = {"skills", "skill_aliases"}
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name not in keep)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM skills WHERE NOT is_verified"))
    await get_redis().flushdb()
    get_cache()._down_until = 0.0


@asynccontextmanager
async def shared_world(builder: Any) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """A clean database holding one world, built once for a whole module of *read-only* tests (much cheaper than rebuilding it
    per test). Modules using this must not also use the per-test ``db``/``client`` fixtures, which would wipe the data."""
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    patch = pytest.MonkeyPatch()
    patch.setattr(security, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    await reset_database()
    app.state.dispatcher = InlineDispatcher()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, await builder(c)
    finally:
        patch.undo()
