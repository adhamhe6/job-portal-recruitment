"""Measure the real query plans used by the API against the bulk dataset (see generate_bulk.py).

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/talentlens_perf PYTHONPATH=. python scripts/perf/explain.py

For each scenario the *actual SQLAlchemy statement* built by the application is compiled and run under
``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)``; "without index" variants drop the index inside a transaction that is rolled back.
Output is a markdown table (pasted into docs/performance.md by hand after review).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect

from app.db.database import dispose_engine, get_engine
from app.db.models import Notification, User
from app.search.candidates import CandidateFilters, CandidateSort, build_candidate_query
from app.search.jobs import JobFilters, JobSort, build_job_query


class Prepared:
    """A compiled application statement + positional parameters, runnable on a raw asyncpg connection."""

    def __init__(self, stmt: Any) -> None:
        compiled = stmt.compile(dialect=asyncpg_dialect())
        params = compiled.construct_params()
        procs = compiled._bind_processors
        self.sql = str(compiled)
        self.args = [procs[k](params[k]) if k in procs else params[k] for k in compiled.positiontup or []]


class Prepared_raw:
    def __init__(self, sql: str) -> None:
        self.sql, self.args = sql, []


def sql_of(stmt: Any) -> Prepared:
    return Prepared(stmt)


def node_summary(plan: dict[str, Any], depth: int = 0, out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    label = plan["Node Type"]
    if "Index Name" in plan:
        label += f" [{plan['Index Name']}]"
    elif "Relation Name" in plan:
        label += f" [{plan['Relation Name']}]"
    if depth < 4:
        out.append(label)
    for child in plan.get("Plans", []):
        node_summary(child, depth + 1, out)
    return out


async def explain(conn: Any, sql: Prepared | str, drop: str | None = None) -> tuple[float, float, list[str], int]:
    if drop:
        await conn.execute(text(drop))
    raw = (await conn.get_raw_connection()).driver_connection
    prepared = sql if isinstance(sql, Prepared) else Prepared_raw(sql)
    doc = await raw.fetchval(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {prepared.sql}", *prepared.args)
    doc = doc if isinstance(doc, list) else json.loads(doc)
    root = doc[0]
    plan = root["Plan"]
    buffers = plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0)
    return root["Execution Time"], root["Planning Time"], node_summary(plan), buffers


async def main() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        n_jobs = (await conn.execute(text("SELECT count(*) FROM jobs WHERE status='PUBLISHED'"))).scalar_one()
        n_cand = (await conn.execute(text("SELECT count(*) FROM candidate_profiles"))).scalar_one()
        print(f"dataset: {n_jobs} published jobs, {n_cand} candidates\n")
        # a company-staff user for candidate search visibility
        user_id, company_id = (await conn.execute(text("SELECT id, company_id FROM users WHERE role='RECRUITER' LIMIT 1"))).one()
        user = (await conn.execute(select(User).where(User.id == user_id))).one()
        u = User(id=user_id, company_id=company_id, role=user.role)
        sk = [str(r[0]) for r in (await conn.execute(text("SELECT id FROM skills WHERE name IN ('Python','Kubernetes','PostgreSQL','React') ORDER BY name"))).all()]
        py, k8s, pg, react = (uuid.UUID(s) for s in sk[2:3] + sk[1:2] + sk[0:1] + sk[3:4]) if len(sk) == 4 else (None,) * 4
        job_id = (await conn.execute(text("SELECT id FROM jobs WHERE status='PUBLISHED' AND embedding IS NOT NULL LIMIT 1"))).scalar_one()
        busy_job = (await conn.execute(text("SELECT job_id FROM applications GROUP BY job_id ORDER BY count(*) DESC LIMIT 1"))).scalar_one()
        some_cand = (await conn.execute(text("SELECT candidate_id FROM applications LIMIT 1"))).scalar_one()

    scenarios: list[tuple[str, Any, str | None]] = []
    stmt, _ = build_job_query(JobFilters(q="python developer", sort=JobSort.RELEVANCE), public=True)
    scenarios.append(("Job search: keyword `python developer` (FTS + title trigram, relevance sort)", sql_of(stmt.limit(20)), "DROP INDEX ix_jobs_search_tsv"))
    stmt, _ = build_job_query(JobFilters(q="pyton developr", sort=JobSort.RELEVANCE), public=True)
    scenarios.append(("Job search: typo `pyton developr` (trigram fallback)", sql_of(stmt.limit(20)), "DROP INDEX ix_jobs_title_trgm"))
    stmt, _ = build_job_query(JobFilters(sort=JobSort.NEWEST), public=True)
    scenarios.append(("Job search: no keyword, newest first (partial index on published_at)", sql_of(stmt.limit(20)), "DROP INDEX ix_jobs_published"))
    if py:
        stmt, _ = build_job_query(JobFilters(skill_ids=[py, pg], skills_mode="all", sort=JobSort.NEWEST), public=True)
        scenarios.append(("Job search: skills ALL of {Python, PostgreSQL}, newest first", sql_of(stmt.limit(20)), "DROP INDEX ix_job_skills_skill_job"))
    stmt, _ = build_job_query(JobFilters(location="berlin", sort=JobSort.NEWEST), public=True)
    scenarios.append(("Job search: location contains `berlin` (ILIKE, trigram GIN)", sql_of(stmt.limit(20)), "DROP INDEX ix_jobs_location_trgm"))
    f = CandidateFilters(q="kubernetes terraform", sort=CandidateSort.RELEVANCE)
    scenarios.append(("Candidate search: keyword `kubernetes terraform` (FTS)", sql_of(build_candidate_query(u, f).limit(20)), "DROP INDEX ix_candidate_profiles_search_tsv"))
    if py:
        f = CandidateFilters(skill_ids=[py, pg], skills_mode="all", min_experience=Decimal("3"), sort=CandidateSort.RECENT)
        scenarios.append(("Candidate search: skills ALL of {Python, PostgreSQL}, ≥3 yrs", sql_of(build_candidate_query(u, f).limit(20)), "DROP INDEX ix_candidate_skills_skill_candidate"))
    f = CandidateFilters(q="aarav", sort=CandidateSort.RELEVANCE)
    scenarios.append(("Candidate search: name fragment (trigram on display_name)", sql_of(build_candidate_query(u, f).limit(20)), "DROP INDEX ix_candidate_profiles_display_name_trgm"))

    async with engine.connect() as conn:
        emb = (await conn.execute(text("SELECT embedding::text FROM jobs WHERE id = :i"), {"i": job_id})).scalar_one()
        ann = f"""SELECT id FROM candidate_profiles WHERE embedding IS NOT NULL AND ((source='SELF' AND is_searchable) OR (source='IMPORTED' AND sourced_by_company_id='{company_id}'))
                  ORDER BY embedding <=> '{emb}' LIMIT 300"""
        scenarios.append(("Vector retrieval: 300 nearest eligible candidates for a job (pgvector HNSW, ef_search=200)", ann, "DROP INDEX ix_candidate_profiles_embedding_hnsw"))
        scenarios.append(("Applications of one job by status", f"SELECT * FROM applications WHERE job_id = '{busy_job}' AND status='SCREENING' ORDER BY applied_at DESC LIMIT 20", "DROP INDEX ix_applications_job_status"))
        scenarios.append(("Applications of one candidate (newest first)", f"SELECT * FROM applications WHERE candidate_id = '{some_cand}' ORDER BY applied_at DESC LIMIT 20", "DROP INDEX ix_applications_candidate_applied"))
        scenarios.append(("Dashboard: applications per status for one company (join jobs)", f"SELECT a.status, count(*) FROM applications a JOIN jobs j ON j.id = a.job_id WHERE j.company_id = '{company_id}' GROUP BY a.status", "DROP INDEX ix_applications_job_status"))

    print("| Scenario | With index (ms) | Without index (ms) | Plan (with index) |\n|---|---|---|---|")
    async with engine.connect() as conn:
        for name, sql, drop in scenarios:
            await conn.execute(text("SET hnsw.ef_search = 200"))
            # warm-up then measure best of 3 (plans are cached in shared buffers by then)
            best = None
            for _ in range(3):
                t, plan_t, nodes, buf = await explain(conn, sql)
                best = t if best is None else min(best, t)
            await conn.rollback()
            async with engine.connect() as c2:  # separate connection: the DROP INDEX is rolled back when it closes
                await c2.execute(text("SET hnsw.ef_search = 200"))
                best_wo = None
                for i in range(3):
                    t2, _, _, _ = await explain(c2, sql, drop if i == 0 else None)
                    best_wo = t2 if best_wo is None else min(best_wo, t2)
                await c2.rollback()
            print(f"| {name} | {best:.1f} | {best_wo:.1f} | {' → '.join(dict.fromkeys(nodes))[:140]} |")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
_ = Notification
