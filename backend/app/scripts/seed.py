"""Demo data seeder.

Everything is created through the *real application* (in-process ASGI client against the real database, with the task
backend running inline), so seeded rows pass exactly the same validation, state machines, embeddings and matching as live
traffic. Afterwards timestamps are spread over the last weeks so dashboards and charts show a believable history.

    python -m app.scripts.seed            # seed if the demo data is not there yet
    python -m app.scripts.seed --reset    # wipe business data (skills are kept) and re-seed

Refuses to run in production: it creates accounts with a published password.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.cache.redis_cache import get_cache, get_redis
from app.core.config import get_settings
from app.core.security import Role, hash_password
from app.db.database import Base, dispose_engine, get_engine, get_sessionmaker
from app.db.models import User
from app.scripts import seed_data as D
from app.scripts import seed_extras
from app.services.skills import seed_ontology

logger = logging.getLogger("seed")
RNG = random.Random(20260101)  # deterministic: same demo data every run


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _years_ago(y: float) -> str:
    return (date.today() - timedelta(days=int(y * 365.25))).isoformat()


class Seeder:
    def __init__(self, client: AsyncClient) -> None:
        self.c = client
        self.recruiters: dict[str, dict[str, Any]] = {}  # company key → {h, company_id, user}
        self.staff: dict[str, dict[str, Any]] = {}  # email → {h,id}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.applications: list[dict[str, Any]] = []
        self.interviews: list[dict[str, Any]] = []

    async def _ok(self, resp: Any, expected: int | tuple[int, ...] = (200, 201)) -> Any:
        exp = (expected,) if isinstance(expected, int) else expected
        if resp.status_code not in exp:
            raise RuntimeError(
                f"seed request failed: {resp.request.method} {resp.request.url.path} -> {resp.status_code} {resp.text[:300]}"
            )
        return resp.json() if resp.content else None

    async def _login(self, email: str) -> dict[str, Any]:
        body = await self._ok(
            await self.c.post("/api/v1/auth/login", json={"email": email, "password": D.PASSWORD})
        )
        return {"token": body["access_token"], "h": _h(body["access_token"]), "user": body["user"]}

    # --- steps ---------------------------------------------------------------------------------------------
    async def admin(self) -> None:
        async with get_sessionmaker()() as s:
            if not (await s.execute(select(User.id).where(User.email == D.ADMIN["email"]))).first():
                s.add(
                    User(
                        email=D.ADMIN["email"],
                        password_hash=hash_password(D.PASSWORD),
                        first_name=D.ADMIN["first"],
                        last_name=D.ADMIN["last"],
                        role=Role.ADMIN,
                    )
                )
                await s.commit()

    async def companies(self) -> None:
        for co in D.COMPANIES:
            r = co["recruiter"]
            body = await self._ok(
                await self.c.post(
                    "/api/v1/auth/register/employer",
                    json={
                        "email": r["email"],
                        "password": D.PASSWORD,
                        "first_name": r["first"],
                        "last_name": r["last"],
                        "job_title": r["title"],
                        "company_name": co["name"],
                        "company_industry": co["industry"],
                        "company_location": co["location"],
                        "company_size": co["size"],
                        "company_website": co["website"],
                    },
                )
            )
            h = _h(body["access_token"])
            cid = body["user"]["company_id"]
            await self._ok(
                await self.c.patch(
                    f"/api/v1/companies/{cid}", headers=h, json={"description": co["description"]}
                )
            )
            self.recruiters[co["key"]] = {"h": h, "company_id": cid, "user": body["user"]}
            for st in co["staff"]:
                m = await self._ok(
                    await self.c.post(
                        f"/api/v1/companies/{cid}/members",
                        headers=h,
                        json={
                            "email": st["email"],
                            "password": D.PASSWORD,
                            "first_name": st["first"],
                            "last_name": st["last"],
                            "role": st["role"],
                            "job_title": st["title"],
                        },
                    )
                )
                login = await self._login(st["email"])
                self.staff[st["email"]] = {
                    "id": m["id"],
                    "h": login["h"],
                    "company": co["key"],
                    "role": st["role"],
                    "name": f"{st['first']} {st['last']}",
                }
        logger.info("companies seeded: %d", len(self.recruiters))

    async def candidate_profiles(self) -> None:
        for cd in D.CANDIDATES:
            body = await self._ok(
                await self.c.post(
                    "/api/v1/auth/register",
                    json={
                        "email": cd["email"],
                        "password": D.PASSWORD,
                        "first_name": cd["first"],
                        "last_name": cd["last"],
                    },
                )
            )
            h = _h(body["access_token"])
            cid = body["user"]["candidate_id"]
            links = cd.get("links", {})
            await self._ok(
                await self.c.patch(
                    "/api/v1/candidates/me",
                    headers=h,
                    json={
                        "headline": cd["headline"],
                        "summary": cd["summary"],
                        "location": cd["location"],
                        "years_experience": cd["years"],
                        "expected_salary": cd["salary"],
                        "salary_currency": "USD" if cd["location"].endswith("USA") else "EUR",
                        "remote_preference": cd["remote"],
                        "employment_preference": cd["employment"],
                        "availability": cd["availability"],
                        "github_url": links.get("github"),
                        "linkedin_url": links.get("linkedin"),
                        "portfolio_url": links.get("portfolio"),
                        "is_searchable": cd["searchable"],
                    },
                )
            )
            for name, prof, yrs in cd["skills"]:
                await self._ok(
                    await self.c.post(
                        "/api/v1/candidates/me/skills",
                        headers=h,
                        json={"name": name, "proficiency": prof, "years_experience": yrs},
                    )
                )
            for title, company, start, end, desc in cd["experiences"]:
                await self._ok(
                    await self.c.post(
                        "/api/v1/candidates/me/experiences",
                        headers=h,
                        json={
                            "title": title,
                            "company_name": company,
                            "start_date": _years_ago(start),
                            "end_date": _years_ago(end) if end else None,
                            "is_current": end is None,
                            "description": desc,
                        },
                    )
                )
            for inst, level, degree, field, sy, ey in cd["education"]:
                await self._ok(
                    await self.c.post(
                        "/api/v1/candidates/me/educations",
                        headers=h,
                        json={
                            "institution": inst,
                            "degree_level": level,
                            "degree": degree,
                            "field_of_study": field,
                            "start_year": sy,
                            "end_year": ey,
                        },
                    )
                )
            for name, issuer in cd["certifications"]:
                await self._ok(
                    await self.c.post(
                        "/api/v1/candidates/me/certifications",
                        headers=h,
                        json={"name": name, "issuer": issuer},
                    )
                )
            for lang, prof in cd["languages"]:
                await self._ok(
                    await self.c.post(
                        "/api/v1/candidates/me/languages",
                        headers=h,
                        json={"language": lang, "proficiency": prof},
                    )
                )
            self.candidates[cd["key"]] = {"h": h, "candidate_id": cid, "email": cd["email"], "data": cd}
        logger.info("candidates seeded: %d", len(self.candidates))

    async def jobs_(self) -> None:
        for jd in D.JOBS:
            rec = self.recruiters[jd["company"]]
            payload: dict[str, Any] = {
                "title": jd["title"],
                "department": jd["department"],
                "description": jd["description"],
                "responsibilities": jd["responsibilities"],
                "qualifications": jd["qualifications"],
                "benefits": jd["benefits"],
                "location": jd["location"],
                "employment_type": jd["employment"],
                "workplace_type": jd["workplace"],
                "salary_min": jd["salary"][0],
                "salary_max": jd["salary"][1],
                "salary_currency": "USD" if jd["location"].endswith("USA") else "EUR",
                "min_experience_years": jd["min_exp"],
                "max_experience_years": jd["max_exp"],
                "experience_level": jd["level"],
                "min_education_level": jd["education"],
                "application_deadline": (date.today() + timedelta(days=jd["deadline_days"])).isoformat()
                if jd["deadline_days"]
                else None,
                "skills": [{"name": n, "requirement": req} for n, req in jd["skills"]],
            }
            if jd["hiring_manager"]:
                payload["hiring_manager_id"] = self.staff[jd["hiring_manager"]]["id"]
            job = await self._ok(await self.c.post("/api/v1/jobs", headers=rec["h"], json=payload))
            if (
                jd["status"] != "DRAFT"
            ):  # everything except drafts is published first so people can apply; see settle_job_states()
                job = await self._ok(await self.c.post(f"/api/v1/jobs/{job['id']}/publish", headers=rec["h"]))
            self.jobs[jd["key"]] = {"id": job["id"], "company": jd["company"], "data": jd}
        logger.info("jobs seeded: %d", len(self.jobs))

    async def applications_(self) -> None:
        for ad in D.APPLICATIONS:
            cand, job = self.candidates[ad["cand"]], self.jobs[ad["job"]]
            rec = self.recruiters[job["company"]]
            created = await self._ok(
                await self.c.post(
                    "/api/v1/applications",
                    headers=cand["h"],
                    json={"job_id": job["id"], "cover_letter": ad.get("cover"), "source": "DIRECT"},
                )
            )
            rec_app = {"id": created["id"], "cand": ad["cand"], "job": ad["job"], "path": ad["path"]}
            for step in ad["path"]:
                body = {"status": step, "comment": ad.get("reject") if step == "REJECTED" else None}
                await self._ok(
                    await self.c.post(
                        f"/api/v1/applications/{created['id']}/status", headers=rec["h"], json=body
                    )
                )
                if step == "INTERVIEW":
                    await seed_extras.schedule_interview(self, rec_app, len(self.interviews))
            if ad.get("withdraw"):
                await self._ok(
                    await self.c.post(
                        f"/api/v1/applications/{created['id']}/withdraw",
                        headers=cand["h"],
                        json={"comment": "Accepted another offer"},
                    )
                )
            self.applications.append(rec_app)
        # a few internal notes
        for app in self.applications[:6]:
            job = self.jobs[app["job"]]
            await self._ok(
                await self.c.post(
                    f"/api/v1/applications/{app['id']}/notes",
                    headers=self.recruiters[job["company"]]["h"],
                    json={
                        "body": f"Reviewed {self.candidates[app['cand']]['data']['first']}'s profile and résumé — see match explanation."
                    },
                ),
            )
        logger.info("applications seeded: %d", len(self.applications))

    async def settle_job_states(self) -> None:
        """After applications exist, move jobs to their final lifecycle state (paused / closed / archived)."""
        steps = {"PAUSED": ["pause"], "CLOSED": ["close"], "ARCHIVED": ["close", "archive"]}
        for job in self.jobs.values():
            for step in steps.get(job["data"]["status"], []):
                await self._ok(
                    await self.c.post(
                        f"/api/v1/jobs/{job['id']}/{step}", headers=self.recruiters[job["company"]]["h"]
                    )
                )

    async def refresh_matches(self) -> None:
        for _key, job in self.jobs.items():
            if job["data"]["status"] == "PUBLISHED":
                await self._ok(
                    await self.c.post(
                        f"/api/v1/matches/jobs/{job['id']}/refresh",
                        headers=self.recruiters[job["company"]]["h"],
                    ),
                    (200, 202),
                )
        for cand in self.candidates.values():
            await self._ok(
                await self.c.post("/api/v1/recommendations/refresh", headers=cand["h"]), (200, 202)
            )

    # --- history -----------------------------------------------------------------------------------------------------
    async def backdate(self) -> None:
        """Spread created/applied/stage timestamps over the past weeks so reports show a believable time series."""
        now = datetime.now(UTC)
        async with get_engine().begin() as conn:
            for _key, job in self.jobs.items():
                days = job["data"]["days_ago"]
                if days is None:
                    created = now - timedelta(days=RNG.randint(2, 6))
                    await conn.execute(
                        text(
                            "UPDATE jobs SET created_at=CAST(:c AS timestamptz), updated_at=CAST(:c AS timestamptz) WHERE id=CAST(:id AS uuid)"
                        ),
                        {"c": created, "id": job["id"]},
                    )
                    continue
                published = now - timedelta(days=days, hours=RNG.randint(0, 8))
                closed = (
                    published + timedelta(days=min(days - 1, 45))
                    if job["data"]["status"] in ("CLOSED", "ARCHIVED")
                    else None
                )
                await conn.execute(
                    text(
                        "UPDATE jobs SET created_at=CAST(:p AS timestamptz) - interval '2 days', updated_at=CAST(:p AS timestamptz), "
                        "published_at=CAST(:p AS timestamptz), closed_at=CAST(:cl AS timestamptz) WHERE id=CAST(:id AS uuid)"
                    ),
                    {"p": published, "cl": closed, "id": job["id"]},
                )
            for app in self.applications:
                job = self.jobs[app["job"]]
                pub = (
                    await conn.execute(
                        text("SELECT published_at FROM jobs WHERE id=CAST(:id AS uuid)"), {"id": job["id"]}
                    )
                ).scalar_one()
                latest_start = max(pub + timedelta(hours=6), now - timedelta(hours=3))
                span = max((latest_start - (pub + timedelta(hours=6))).total_seconds(), 3600)
                t = pub + timedelta(hours=6, seconds=RNG.uniform(0, span * 0.8))
                hist = (
                    (
                        await conn.execute(
                            text(
                                "SELECT id FROM application_status_history WHERE application_id=CAST(:a AS uuid) ORDER BY created_at, id"
                            ),
                            {"a": app["id"]},
                        )
                    )
                    .scalars()
                    .all()
                )
                first = t
                for hid in hist:
                    await conn.execute(
                        text(
                            "UPDATE application_status_history SET created_at=CAST(:t AS timestamptz) WHERE id=:id"
                        ),
                        {"t": t, "id": hid},
                    )
                    t = min(t + timedelta(hours=RNG.uniform(10, 90)), now - timedelta(hours=1))
                await conn.execute(
                    text(
                        "UPDATE applications SET applied_at=CAST(:a AS timestamptz), status_changed_at=CAST(:s AS timestamptz), created_at=CAST(:a AS timestamptz), updated_at=CAST(:s AS timestamptz) WHERE id=CAST(:id AS uuid)"
                    ),
                    {"a": first, "s": min(t, now - timedelta(hours=1)), "id": app["id"]},
                )
        logger.info("history backdated")

    async def finish(self) -> None:
        await get_redis().flushdb()
        get_cache()._down_until = 0.0


async def reset_business_data() -> None:
    keep = {"skills", "skill_aliases"}
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name not in keep)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM skills WHERE NOT is_verified"))
    try:
        await get_redis().flushdb()
    except Exception:  # Redis may be unavailable during a pure DB reset
        logger.warning("redis not flushed")


async def already_seeded() -> bool:
    async with get_sessionmaker()() as s:
        return bool((await s.execute(select(User.id).where(User.email == D.ADMIN["email"]))).first())


async def run(reset: bool = False, extensions: tuple[Any, ...] = ()) -> bool:
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to seed demo data in production")
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    # Seeding is a burst of registrations from one client: lift the per-IP limits for this process only.
    for attr in (
        "login_rate_limit_attempts",
        "register_rate_limit_attempts",
        "upload_rate_limit_attempts",
        "expensive_rate_limit_attempts",
        "search_rate_limit_attempts",
    ):
        setattr(settings, attr, 10**7)
    async with get_sessionmaker()() as s:
        await seed_ontology(s)
    if reset:
        await reset_business_data()
    elif await already_seeded():
        logger.info("demo data already present; use --reset to rebuild")
        return False
    app.state.dispatcher = InlineDispatcher()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://seed", timeout=60) as client:
        seeder = Seeder(client)
        await seeder.admin()
        await seeder.companies()
        await seeder.candidate_profiles()
        await seeder.jobs_()
        await seed_extras.resumes(seeder)  # before applications, so applying can reference the primary résumé
        for ext in extensions:  # optional extra stages plug in here
            await ext(seeder)
        await seeder.applications_()
        await seed_extras.finish_interviews(seeder)
        await seeder.settle_job_states()
        await seeder.refresh_matches()
        await seeder.backdate()
        await seeder.finish()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="wipe business data (keeps the skills taxonomy) and re-seed"
    )
    args = parser.parse_args()
    from app.core.logging import configure_logging

    configure_logging("INFO", json_logs=False)

    async def _go() -> None:
        try:
            done = await run(reset=args.reset)
            print("Demo data created." if done else "Demo data already present (use --reset to rebuild).")
        finally:
            await dispose_engine()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
