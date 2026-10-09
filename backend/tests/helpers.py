"""Shared test helpers: everything goes through the real API (no direct ORM writes except bootstrapping an admin)."""

from __future__ import annotations

import itertools
import uuid
from datetime import date, timedelta
from typing import Any

from httpx import AsyncClient

from app.core.security import Role, hash_password
from app.db.database import get_sessionmaker
from app.db.models import User

PASSWORD = "CorrectHorse42"
_counter = itertools.count(1)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_counter)}-{uuid.uuid4().hex[:6]}@test.example"


async def register_candidate(
    client: AsyncClient, email: str | None = None, first: str = "Casey", last: str = "Candidate"
) -> dict[str, Any]:
    email = email or unique_email("cand")
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "first_name": first, "last_name": last},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "token": body["access_token"],
        "user": body["user"],
        "email": email,
        "candidate_id": body["user"]["candidate_id"],
        "h": auth(body["access_token"]),
    }


async def register_employer(
    client: AsyncClient, company: str | None = None, email: str | None = None
) -> dict[str, Any]:
    email = email or unique_email("rec")
    company = company or f"Company {uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/auth/register/employer",
        json={
            "email": email,
            "password": PASSWORD,
            "first_name": "Riley",
            "last_name": "Recruiter",
            "company_name": company,
            "company_industry": "Software",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "token": body["access_token"],
        "user": body["user"],
        "email": email,
        "company_id": body["user"]["company_id"],
        "h": auth(body["access_token"]),
    }


async def add_staff(
    client: AsyncClient, recruiter: dict[str, Any], role: str = "HIRING_MANAGER", email: str | None = None
) -> dict[str, Any]:
    email = email or unique_email("staff")
    r = await client.post(
        f"/api/v1/companies/{recruiter['company_id']}/members",
        headers=recruiter["h"],
        json={
            "email": email,
            "password": PASSWORD,
            "first_name": "Sam",
            "last_name": role.title(),
            "role": role,
        },
    )
    assert r.status_code == 201, r.text
    member = r.json()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    tok = login.json()["access_token"]
    return {
        "token": tok,
        "user": login.json()["user"],
        "id": member["id"],
        "email": email,
        "company_id": recruiter["company_id"],
        "h": auth(tok),
    }


async def create_admin(client: AsyncClient) -> dict[str, Any]:
    email = unique_email("admin")
    async with get_sessionmaker()() as s:
        s.add(
            User(
                email=email,
                password_hash=hash_password(PASSWORD),
                first_name="Ada",
                last_name="Admin",
                role=Role.ADMIN,
            )
        )
        await s.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {
        "token": r.json()["access_token"],
        "user": r.json()["user"],
        "email": email,
        "h": auth(r.json()["access_token"]),
    }


def job_payload(title: str = "Backend Engineer", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": title,
        "department": "Engineering",
        "description": "Build and operate Python services that power our recruiting platform, working with PostgreSQL and Redis.",
        "responsibilities": "Design APIs, write tests, review code, run services in production with Docker.",
        "qualifications": "Experience building REST APIs.",
        "location": "Berlin, Germany",
        "employment_type": "FULL_TIME",
        "workplace_type": "HYBRID",
        "salary_min": 70000,
        "salary_max": 95000,
        "min_experience_years": 3,
        "experience_level": "MID",
        "application_deadline": (date.today() + timedelta(days=30)).isoformat(),
        "skills": [
            {"name": "Python", "requirement": "REQUIRED"},
            {"name": "FastAPI", "requirement": "REQUIRED"},
            {"name": "PostgreSQL", "requirement": "REQUIRED"},
            {"name": "Docker", "requirement": "REQUIRED"},
            {"name": "Redis", "requirement": "PREFERRED"},
            {"name": "Kubernetes", "requirement": "PREFERRED"},
        ],
    }
    body.update(overrides)
    return body


async def create_job(
    client: AsyncClient, recruiter: dict[str, Any], publish: bool = False, **overrides: Any
) -> dict[str, Any]:
    r = await client.post("/api/v1/jobs", headers=recruiter["h"], json=job_payload(**overrides))
    assert r.status_code == 201, r.text
    job = r.json()
    if publish:
        p = await client.post(f"/api/v1/jobs/{job['id']}/publish", headers=recruiter["h"])
        assert p.status_code == 200, p.text
        job = p.json()
    return job


async def fill_backend_profile(client: AsyncClient, cand: dict[str, Any], years: float = 4.0) -> None:
    """A strong backend-engineer profile entered through the profile API."""
    h = cand["h"]
    r = await client.patch(
        "/api/v1/candidates/me",
        headers=h,
        json={
            "headline": "Backend engineer",
            "summary": "Backend engineer building Python APIs with FastAPI and PostgreSQL, deployed with Docker.",
            "location": "Berlin, Germany",
            "years_experience": years,
            "remote_preference": "HYBRID",
        },
    )
    assert r.status_code == 200, r.text
    for name in ("Python", "FastAPI", "PostgreSQL", "Docker", "Redis"):
        sr = await client.post("/api/v1/candidates/me/skills", headers=h, json={"name": name})
        assert sr.status_code == 201, sr.text
    er = await client.post(
        "/api/v1/candidates/me/experiences",
        headers=h,
        json={
            "title": "Backend Engineer",
            "company_name": "Initech",
            "start_date": (date.today() - timedelta(days=int(years * 365))).isoformat(),
            "is_current": True,
            "description": "Built REST APIs in Python with FastAPI backed by PostgreSQL and Redis; containerised with Docker.",
        },
    )
    assert er.status_code == 201, er.text
    ed = await client.post(
        "/api/v1/candidates/me/educations",
        headers=h,
        json={"institution": "TU Berlin", "degree_level": "BACHELOR", "field_of_study": "Computer Science"},
    )
    assert ed.status_code == 201, ed.text


async def fill_frontend_profile(client: AsyncClient, cand: dict[str, Any], years: float = 3.0) -> None:
    h = cand["h"]
    r = await client.patch(
        "/api/v1/candidates/me",
        headers=h,
        json={
            "headline": "Frontend engineer",
            "summary": "Frontend engineer crafting responsive React and TypeScript interfaces with Tailwind CSS.",
            "location": "Berlin, Germany",
            "years_experience": years,
            "remote_preference": "REMOTE",
        },
    )
    assert r.status_code == 200, r.text
    for name in ("React", "TypeScript", "Next.js", "Tailwind CSS", "CSS"):
        sr = await client.post("/api/v1/candidates/me/skills", headers=h, json={"name": name})
        assert sr.status_code == 201, sr.text
    er = await client.post(
        "/api/v1/candidates/me/experiences",
        headers=h,
        json={
            "title": "Frontend Developer",
            "company_name": "Globex",
            "start_date": (date.today() - timedelta(days=int(years * 365))).isoformat(),
            "is_current": True,
            "description": "Built component libraries and single-page apps with React, TypeScript and Tailwind.",
        },
    )
    assert er.status_code == 201, er.text
