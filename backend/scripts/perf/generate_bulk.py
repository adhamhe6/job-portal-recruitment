"""Generate a large synthetic dataset to measure query plans (`docs/performance.md`).

Usage (against a scratch database that has been migrated):
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/talentlens_perf \
        python scripts/perf/generate_bulk.py --jobs 30000 --candidates 50000

Rows are generated inside PostgreSQL (generate_series + random()) for speed; embeddings are real model outputs computed in
Python from each row's own text. Data is synthetic: it exists to exercise the planner, not to evaluate matching quality.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time

import numpy as np
from sqlalchemy import text

from app.core.security import hash_password
from app.db.database import dispose_engine, get_engine
from app.matching.embedder import get_embedder
from app.matching.representation import COMPONENT_WEIGHTS

TITLES = [
    "Backend Engineer",
    "Frontend Engineer",
    "Data Scientist",
    "DevOps Engineer",
    "Product Manager",
    "Data Analyst",
    "QA Engineer",
    "Machine Learning Engineer",
    "Site Reliability Engineer",
    "Mobile Developer",
    "Security Engineer",
    "Marketing Manager",
    "Financial Analyst",
    "Registered Nurse",
    "UX Designer",
    "Sales Executive",
    "Customer Success Manager",
    "HR Business Partner",
]
LEVELS = ["Junior", "Senior", "Lead", "Staff", ""]
CITIES = [
    "Berlin, Germany",
    "Munich, Germany",
    "London, United Kingdom",
    "Amsterdam, Netherlands",
    "Boston, USA",
    "Austin, USA",
    "Lisbon, Portugal",
    "Paris, France",
    "Vienna, Austria",
    "Remote",
]
FILLER = (
    "You will work with a cross-functional team to design, build and operate reliable products, collaborate with stakeholders, write clear "
    "documentation, review code and continuously improve our processes and tooling in a fast-moving environment. "
)


async def main(n_jobs: int, n_cands: int, n_companies: int) -> None:
    rng = random.Random(1)
    emb = get_embedder()
    pw = hash_password("PerfPass123!")
    t0 = time.time()
    async with get_engine().begin() as conn:
        await conn.execute(
            text("TRUNCATE users, companies, jobs, candidate_profiles RESTART IDENTITY CASCADE")
        )
        skills = (await conn.execute(text("SELECT id, name FROM skills"))).all()
        if not skills:
            raise SystemExit("run the bootstrap first (skills taxonomy is empty)")
        print(f"{len(skills)} skills; creating {n_companies} companies, {n_jobs} jobs, {n_cands} candidates")
        await conn.execute(
            text(
                "INSERT INTO companies (name, slug) SELECT 'Company '||g, 'company-'||g FROM generate_series(1,:n) g"
            ),
            {"n": n_companies},
        )
        await conn.execute(
            text(
                "INSERT INTO users (email, password_hash, first_name, last_name, role, company_id) "
                "SELECT 'rec'||row_number() over ()||'@perf.example', :pw, 'Rec', 'Ruiter', 'RECRUITER', c.id FROM companies c"
            ),
            {"pw": pw},
        )
        titles = rng.sample(TITLES, len(TITLES))
        await conn.execute(text("CREATE TEMP TABLE _titles(i int, t text)"))
        for i, t in enumerate(titles):
            await conn.execute(text("INSERT INTO _titles VALUES (:i,:t)"), {"i": i, "t": t})
        await conn.execute(text("CREATE TEMP TABLE _cities(i int, city text)"))
        for i, c in enumerate(CITIES):
            await conn.execute(text("INSERT INTO _cities VALUES (:i,:c)"), {"i": i, "c": c})
        await conn.execute(
            text(
                """
                INSERT INTO jobs (company_id, created_by_id, title, department, description, responsibilities, location, employment_type, workplace_type,
                                  salary_min, salary_max, min_experience_years, status, published_at, application_deadline, created_at, updated_at)
                SELECT c.id, u.id,
                       (SELECT t FROM _titles WHERE i = (g % :nt)) || ' #' || g,
                       'Dept ' || (g % 20),
                       :filler || 'Role number ' || g,
                       :filler,
                       (SELECT city FROM _cities WHERE i = (g % :nc)),
                       (ARRAY['FULL_TIME','FULL_TIME','FULL_TIME','PART_TIME','CONTRACT','INTERNSHIP'])[1 + (g % 6)],
                       (ARRAY['ONSITE','HYBRID','REMOTE'])[1 + (g % 3)],
                       40000 + (g % 80) * 1000, 60000 + (g % 80) * 1500, (g % 8),
                       (ARRAY['PUBLISHED','PUBLISHED','PUBLISHED','PUBLISHED','PUBLISHED','PUBLISHED','CLOSED','DRAFT','PAUSED','ARCHIVED'])[1 + (g % 10)],
                       now() - (g % 120) * interval '1 day',
                       current_date + ((g % 60) - 5),
                       now() - (g % 150) * interval '1 day', now()
                FROM generate_series(1, :n) g
                JOIN companies c ON c.id = (SELECT id FROM companies ORDER BY id OFFSET (g % :nco) LIMIT 1)
                JOIN users u ON u.company_id = c.id
                """
            ),
            {"n": n_jobs, "nt": len(TITLES), "nc": len(CITIES), "nco": n_companies, "filler": FILLER},
        )
        await conn.execute(text("UPDATE jobs SET published_at = NULL WHERE status = 'DRAFT'"))
        await conn.execute(text("UPDATE jobs SET closed_at = now() WHERE status IN ('CLOSED','ARCHIVED')"))
        # job skills: 6 distinct random skills per job (first 4 REQUIRED, rest PREFERRED)
        await conn.execute(
            text(
                """
                INSERT INTO job_skills (job_id, skill_id, requirement)
                SELECT j.id, s.id, CASE WHEN s.rn <= 4 THEN 'REQUIRED' ELSE 'PREFERRED' END
                FROM jobs j
                CROSS JOIN LATERAL (
                    SELECT id, row_number() over () rn FROM (SELECT id FROM skills ORDER BY md5(id::text || j.id::text) LIMIT 6) x
                ) s
                """
            )
        )
        await conn.execute(
            text(
                "UPDATE jobs j SET skills_text = (SELECT string_agg(s.name, ', ') FROM job_skills js JOIN skills s ON s.id = js.skill_id WHERE js.job_id = j.id)"
            )
        )
        print(f"jobs done ({time.time() - t0:.0f}s)")

        await conn.execute(
            text(
                "INSERT INTO users (email, password_hash, first_name, last_name, role) "
                "SELECT 'cand'||g||'@perf.example', :pw, 'Cand'||g, 'Idate', 'CANDIDATE' FROM generate_series(1,:n) g"
            ),
            {"pw": pw, "n": n_cands},
        )
        await conn.execute(
            text(
                """
                INSERT INTO candidate_profiles (user_id, source, first_name, last_name, display_name, headline, summary, location, years_experience,
                                                remote_preference, availability, is_searchable, created_at, updated_at)
                SELECT u.id, 'SELF', u.first_name, u.last_name, u.first_name || ' ' || u.last_name,
                       (SELECT t FROM _titles WHERE i = (n % :nt)), :filler || 'Candidate ' || n,
                       (SELECT city FROM _cities WHERE i = (n % :nc)), (n % 15) + 0.5,
                       (ARRAY['ONSITE','HYBRID','REMOTE','FLEXIBLE'])[1 + (n % 4)], (ARRAY['IMMEDIATELY','TWO_WEEKS','ONE_MONTH','THREE_MONTHS'])[1 + (n % 4)],
                       (n % 10) <> 0, now() - (n % 300) * interval '1 day', now()
                FROM (SELECT id, first_name, last_name, row_number() over (order by id) n FROM users WHERE role = 'CANDIDATE') u
                """
            ),
            {"nt": len(TITLES), "nc": len(CITIES), "filler": FILLER},
        )
        await conn.execute(
            text(
                """
                INSERT INTO candidate_skills (candidate_id, skill_id, source, status)
                SELECT cp.id, s.id, 'USER', 'CONFIRMED'
                FROM candidate_profiles cp
                CROSS JOIN LATERAL (SELECT id FROM skills ORDER BY md5(id::text || cp.id::text) LIMIT 7) s
                """
            )
        )
        await conn.execute(
            text(
                "UPDATE candidate_profiles c SET skills_text = (SELECT string_agg(s.name, ' ') FROM candidate_skills cs JOIN skills s ON s.id = cs.skill_id WHERE cs.candidate_id = c.id), "
                "search_text = c.summary"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO experiences (candidate_id, title, company_name, start_date, end_date, description) "
                "SELECT id, headline, 'Employer '||(abs(hashtext(id::text)) % 500), current_date - interval '4 years', current_date - interval '1 year', 'Worked on '||coalesce(skills_text,'') "
                "FROM candidate_profiles"
            )
        )
        print(f"candidates done ({time.time() - t0:.0f}s)")

        # real embeddings (role / skills / prose components combined exactly like production)
        w = np.array(
            [COMPONENT_WEIGHTS["role"], COMPONENT_WEIGHTS["skills"], COMPONENT_WEIGHTS["prose"]],
            dtype=np.float32,
        )
        for table, role_col, skills_col, prose_col in (
            ("jobs", "title", "skills_text", "description"),
            ("candidate_profiles", "headline", "skills_text", "summary"),
        ):
            ids = [r[0] for r in (await conn.execute(text(f"SELECT id FROM {table}"))).all()]
            done = 0
            for i in range(0, len(ids), 2000):
                batch = ids[i : i + 2000]
                rows = (
                    await conn.execute(
                        text(
                            f"SELECT id, {role_col}, coalesce({skills_col}, ''), left({prose_col}, 600) FROM {table} WHERE id = ANY(:ids)"
                        ),
                        {"ids": batch},
                    )
                ).all()
                texts = [[(r[1] or "x"), (r[2] or "x"), (r[3] or "x")] for r in rows]
                flat = emb.embed([t for tri in texts for t in tri]).reshape(len(rows), 3, -1)
                vecs = (flat * w[None, :, None]).sum(axis=1)
                vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
                await conn.execute(
                    text(
                        f"UPDATE {table} SET embedding = CAST(:v AS vector), embedding_model = :m, embedding_version = :ver, embedding_source_hash = 'perf' WHERE id = CAST(:id AS uuid)"
                    ),
                    [
                        {
                            "v": "[" + ",".join(f"{x:.6f}" for x in vec) + "]",
                            "m": emb.name,
                            "ver": emb.version,
                            "id": str(r[0]),
                        }
                        for vec, r in zip(vecs, rows, strict=True)
                    ],
                )
                done += len(batch)
            print(f"{table}: embedded {done} ({time.time() - t0:.0f}s)")

        # applications & matches
        await conn.execute(
            text(
                """
                INSERT INTO applications (job_id, candidate_id, status, applied_at, status_changed_at, created_at, updated_at)
                SELECT j.id, cp.id, (ARRAY['APPLIED','APPLIED','SCREENING','SHORTLISTED','INTERVIEW','OFFER','REJECTED','REJECTED','HIRED'])[1 + (g % 9)],
                       now() - (g % 90) * interval '1 day', now(), now(), now()
                FROM generate_series(1, :n) g
                JOIN (SELECT id, row_number() over () rn FROM jobs WHERE status = 'PUBLISHED') j ON j.rn = 1 + (g % (SELECT count(*) FROM jobs WHERE status = 'PUBLISHED'))
                JOIN (SELECT id, row_number() over () rn FROM candidate_profiles) cp ON cp.rn = 1 + ((g * 7919) % :nc)
                ON CONFLICT DO NOTHING
                """
            ),
            {"n": n_cands * 3, "nc": n_cands},
        )
        await conn.execute(text("ANALYZE"))
        counts = {
            t: (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            for t in ("jobs", "job_skills", "candidate_profiles", "candidate_skills", "applications")
        }
        print("row counts:", counts, f"total {time.time() - t0:.0f}s")
    await dispose_engine()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=30000)
    ap.add_argument("--candidates", type=int, default=50000)
    ap.add_argument("--companies", type=int, default=200)
    a = ap.parse_args()
    asyncio.run(main(a.jobs, a.candidates, a.companies))
