# TalentLens — Job Portal & Recruitment Management System

A full-stack recruitment platform: employers publish jobs, candidates build structured profiles and upload résumés, résumés are processed asynchronously, and a **semantic matching engine ranks candidates for jobs (and jobs for candidates) with an explanation a recruiter can read**. Applications move through an audited pipeline, interviews are scheduled with conflict protection, and dashboards report on the whole funnel.

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic |
| **Data** | PostgreSQL 16 (+ **pgvector**, full-text search, `pg_trgm`, `btree_gist`) · Redis 7 |
| **Async work** | ARQ worker on Redis, with durable task state in PostgreSQL |
| **AI / matching** | WordLlama pretrained embeddings (bundled, offline) · hybrid scoring (semantic + skills + experience + education + preferences) · explanations · evaluation harness |
| **Résumés** | PDF/DOCX validation (magic bytes, zip-bomb guard) → `pypdf` / `python-docx` extraction → rule-based parser → reviewable suggestions |
| **Frontend** | React 19 · TypeScript · Tailwind v4 · Radix/shadcn-style components · TanStack Query · React Hook Form + zod · Recharts |
| **Quality** | pytest (unit / integration / API e2e on real PostgreSQL + Redis) · Vitest + Testing Library + MSW · Playwright (browser e2e) · Ruff · mypy · ESLint · Prettier · GitHub Actions |
| **Deploy** | `docker compose up --build` → `postgres`, `redis`, `migrate`, `api`, `worker`, `web` (nginx) |

> The matching score is a **ranking aid for human reviewers, not an automated hiring decision**. Only job-relevant qualifications are used — never names, gender, age, nationality, photos or other personal attributes. See [AI matching](#ai-matching) and [`docs/matching-evaluation.md`](docs/matching-evaluation.md) for how it is built and what has (and has not) been validated.

---

## Quick start (Docker)

```bash
git clone https://github.com/adhamhe6/job-portal-recruitment.git
cd job-portal-recruitment
cp .env.example .env        # set SECRET_KEY:  openssl rand -hex 32
docker compose up --build
```

| What | URL |
|---|---|
| Web app | http://localhost:8080 |
| Swagger UI | http://localhost:8080/docs (direct: http://localhost:8000/docs — bound to 127.0.0.1) |
| ReDoc / OpenAPI JSON | http://localhost:8000/redoc · http://localhost:8000/openapi.json |
| Health | http://localhost:8000/health · readiness `/health/ready` (DB, pgvector, Redis) |

On first start the one-shot **`migrate`** service runs `alembic upgrade head`, seeds the skill taxonomy, creates the first admin (`FIRST_ADMIN_EMAIL`/`FIRST_ADMIN_PASSWORD`) and — with `SEED_DEMO_DATA=true` (the default in `.env.example`) — builds the demo dataset through the real API (about 25–30 seconds: 4 companies, 16 candidates with generated PDF résumés processed by the real pipeline, 14 jobs, 20 applications, interviews with feedback). `api` and `worker` start only after it succeeds; every service has a health check.

### Demo accounts (development only — password `DemoPass123!`)

| Role | Email | What to try |
|---|---|---|
| Recruiter (Northwind Labs) | `recruiter@demo.example` | dashboard, jobs, **Candidate Matching**, pipeline, interviews |
| Hiring manager (Northwind) | `hiring.manager@demo.example` | assigned jobs, applications, interview feedback |
| Candidate (strong backend) | `candidate@demo.example` | profile, résumé upload, recommended jobs, apply |
| Candidate (frontend / ML) | `bianca.costa@demo.example`, `chen.wei@demo.example` | different recommendations |
| Platform admin | `admin@demo.example` | users, companies, system monitoring |
| Other tenants' recruiters | `recruiter.helio@demo.example`, `recruiter.brightwave@demo.example`, `recruiter.orbit@demo.example` | tenant isolation |

The login page offers one-click demo logins only when the server reports demo mode (`GET /api/v1/meta`). The server **refuses** `SEED_DEMO_DATA=true` when `ENVIRONMENT=production`, so these credentials cannot reach a production deployment by accident.

### Suggested 5-minute demo

1. Sign in as the **recruiter** → *Dashboard* (funnel, KPIs, top matches — all real aggregates) → *Candidate Matching* → pick **Senior Backend Engineer**: on the freshly seeded data Alex Rivera ranks first (≈97 %) with the explanation “covers 5 of 5 required skills, 5.5 years vs 4+ required”; open a lower-ranked candidate to see *related* skills (MySQL ≈ PostgreSQL) and *missing* ones.
2. Sign in as a **new candidate** (Register) → fill the profile → upload a PDF/DOCX résumé → watch the résumé go from *Processing* to *Processed* (a real background job whose progress the page polls) → review & apply the extracted skills.
3. *Recommended Jobs* shows jobs ranked from the same matching system (closed/paused/unpublished jobs never appear) → open one → *Apply*.
4. Back as the recruiter: the application is in *Applications* (pipeline), already ranked → shortlist → **schedule an interview** (try double-booking: the database refuses) → the candidate receives a notification and sees the interview → record feedback → advance the application.

---

## Architecture

```mermaid
flowchart LR
    B[Browser<br/>React + TS] --> N[nginx]
    N --> A[FastAPI]
    A --> P[(PostgreSQL 16<br/>+ pgvector)]
    A --> R[(Redis<br/>cache · limits · queue)]
    R --> W[ARQ worker<br/>résumé · embeddings · matching]
    W --> P
    W --> S[(résumé storage)]
    A --> S
```

Full write-up (data model, authorization, workflows, background processing, matching, caching, trade-offs): **[`docs/architecture.md`](docs/architecture.md)**. Decisions and evidence: [`docs/implementation-plan.md`](docs/implementation-plan.md) · [`docs/performance.md`](docs/performance.md) · [`docs/security-review.md`](docs/security-review.md) · [`docs/matching-evaluation.md`](docs/matching-evaluation.md) · [`docs/verification.md`](docs/verification.md).

### What makes it technically interesting

* **Hybrid semantic matching, persisted and explainable.** Job and candidate are embedded from aligned components (role / skills / prose), compared by cosine similarity, then combined with required/preferred skill coverage (alias- and family-aware), experience, education and preference fit. Every score stores its component breakdown, model/version and input hashes, so stale scores are *detected*, not assumed.
* **pgvector inside PostgreSQL** — one transactional store for relational data, FTS, trigram and vectors; eligibility is plain SQL, ranking is HNSW + exact re-scoring.
* **Correctness pushed into the database**: partial unique indexes (one live application per candidate/job), GiST *exclusion constraints* (no double-booked candidate or interviewer, even under concurrency), CHECKs, generated tsvector columns.
* **Real asynchronous pipeline with recovery**: durable task rows, idempotent dedupe keys, atomic claim, heartbeat + reaper for crashed workers, bounded retries, progress the UI polls.
* **Security by construction**: Argon2id, rotating refresh tokens with reuse detection, central object-level authorization with 404-for-foreign-tenant, candidate-visibility levels, validated/streamed uploads served only through authorised endpoints.
* **Everything degrades gracefully when Redis is down** (cache/limits/queue off, data intact).

---

## Features

* **Accounts & RBAC** — ADMIN / RECRUITER / HIRING_MANAGER / CANDIDATE; employer self-registration creates the company; company admins add staff; platform admin manages users & companies.
* **Jobs** — drafts, publish-time validation, lifecycle `DRAFT → PUBLISHED ⇄ PAUSED → CLOSED → ARCHIVED`, required/preferred skills, salary, experience & education requirements, deadlines, hiring-manager assignment, duplicate-posting guard.
* **Job search** — keyword (FTS) + typo-tolerant title, skills (any/all), location, employment & workplace type, salary overlap, experience level, freshness, sorting, pagination, saved jobs, per-candidate match badges.
* **Candidates** — structured profile (experience, education, certifications, languages, skills with provenance), profile-completion guidance, marketplace opt-in/out, recruiter candidate search with visibility rules and contact masking.
* **Résumés** — PDF/DOCX upload, background extraction & parsing, skill/experience/education suggestions with confidence that the candidate reviews and applies, failure handling, authorised download, **bulk import** with duplicate detection.
* **Matching & recommendations** — ranked candidates per job with explanations; recommended jobs per candidate; refresh on change; model/version tracking; nightly sweep.
* **Applications** — controlled stage workflow with full audit history, internal notes, withdrawal, per-role views.
* **Interviews** — scheduling with timezone & participants, conflict detection (DB-enforced), reschedule/cancel/confirm/no-show, structured private feedback, notifications.
* **Notifications** — in-app centre (unread count, mark read/all), idempotent delivery.
* **Reports & dashboards** — recruiter / candidate / admin dashboards, funnel, applications by job/status, job performance, interview statistics, top skills, matching performance, CSV export.
* **Admin** — system monitoring (DB, pgvector, Redis, queue, worker, embedding model), task list/retry, audit log, embedding refresh.

## Local development (without Docker for the app)

Prerequisites: Python 3.12+, Node 22+, PostgreSQL 16 with `pgvector` + `pg_trgm` + `btree_gist`, Redis 7 (or run just those two with `docker compose up postgres redis`).

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/talentlens
export REDIS_URL=redis://localhost:6379/0 STORAGE_DIR=./storage
alembic upgrade head                      # schema from an empty database
python -m app.scripts.bootstrap           # skill taxonomy + first admin (+ demo data if SEED_DEMO_DATA=true)
python -m app.scripts.seed --reset        # (re)build the demo dataset
uvicorn app.main:app --reload             # API on :8000   → http://localhost:8000/docs
arq app.workers.worker.WorkerSettings     # worker (separate terminal)

# frontend
cd frontend
npm ci
npm run dev                               # http://localhost:5173 (proxies /api → :8000)
```

`JOB_BACKEND=inline` runs background tasks inside the API process (handy for quick experiments; the worker is the real path).

### Database & migrations

Alembic owns the schema: `alembic upgrade head` works from an empty database (the test-suite also runs `downgrade base → upgrade head`), and CI runs `alembic check` so models and migrations cannot drift. Create a migration with `alembic revision --autogenerate -m "…"` and review it (expression/partial indexes and exclusion constraints need a human check).

### Seed data

`python -m app.scripts.seed` drives the **real API in-process** (registration, profile editing, job creation/publishing, applications, stage changes, interviews, résumé upload and processing) so seeded rows pass the same validation, state machines, embeddings and matching as live traffic; timestamps are then spread over the last weeks so charts look realistic. The cast is designed for demonstration: a strong, a partial, an adjacent-stack, a junior and an irrelevant candidate per showcase job; nursing/marketing/finance roles prove it is not developer-only; a candidate who opted out of recruiter search; jobs in every lifecycle state. Deterministic (fixed RNG seed).

## AI matching

1. **Résumé processing** (worker): validate → extract text → parse (sections, contact, skills via the ontology, experience, education, certifications) → suggestions with confidence → embedding. Suggestions never overwrite user-entered data.
2. **Representation**: for jobs and candidates alike — *role* (title / headline + recent titles), *skills*, *prose* (responsibilities & summary / experience & résumé excerpt, truncated). Contact data is stripped; no personal attributes are used.
3. **Embeddings**: WordLlama `l2-supercat` (256-d) — pretrained, bundled in the wheel, CPU-only, offline, deterministic. Stored in `vector(256)` columns with model name, version, source hash and timestamp; unchanged text is never re-embedded. The `Embedder` interface makes the model replaceable (procedure in `docs/architecture.md`).
4. **Semantic similarity**: cosine between job and candidate vectors, calibrated to 0‥1.
5. **Structured matching**: required/preferred skill coverage (canonical/alias = 1.0, same *family* such as MySQL↔PostgreSQL = 0.5), experience alignment, education alignment, workplace/location/employment preference fit.
6. **Ranking**: `overall = Σ wᵢ·sᵢ / Σ wᵢ` with weights semantic 0.30 · required 0.30 · preferred 0.10 · experience 0.15 · education 0.05 · preference 0.10, inapplicable components dropped and renormalised, and a qualification floor (< 25 % required coverage caps the score at 0.45).
7. **Explainability**: matched / related / missing skills, experience & education status, semantic band, preference notes, one summary sentence — shown to recruiters in full and to candidates in a safe subset.
8. **Versioning & freshness**: `matching_version`, `embedding_model/version` and input hashes stored per match; mismatches mark rows stale and queue a refresh. Triggers: publish, material job edit, profile/résumé change, new application, nightly sweep.
9. **Evaluation**: `python -m app.matching.eval --write docs/matching-evaluation.md` scores the pipeline against a hand-labelled set (P@K, R@K, NDCG, MRR, MAP) next to keyword/skill-overlap/embedding-only baselines. The limitations are stated in the report: small synthetic set, labelled by the authors, no fairness audit.

## Testing

```bash
# backend (needs PostgreSQL + Redis; databases are created/migrated by the suite itself)
cd backend
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/talentlens_test
export TEST_REDIS_URL=redis://localhost:6379/15
pytest -q                                  # unit + integration + API e2e
pytest --cov=app --cov-report=term-missing:skip-covered
ruff check app tests scripts && ruff format --check app tests scripts
mypy app
python -m app.matching.eval                # matching quality report

# frontend
cd frontend
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build

# browser end-to-end against the running docker stack (UI → API → PostgreSQL/Redis/worker → UI)
# The suite signs in and registers throwaway accounts far faster than the production-style rate limits allow,
# so raise them for the stack under test (CI does the same):
printf 'LOGIN_RATE_LIMIT_ATTEMPTS=1000\nREGISTER_RATE_LIMIT_ATTEMPTS=1000\n' >> .env
docker compose up -d --build --wait
cd e2e && npm ci && npx playwright install chromium && npx playwright test
```

Current results and the exact commands that produced them are recorded in [`docs/verification.md`](docs/verification.md).

## API documentation

Swagger UI at `/docs` (OpenAPI at `/openapi.json`): every route has a tag, summary, request/response schema and documented error codes. Click **Authorize** and sign in with an email/password (OAuth2 password flow → `POST /api/v1/auth/token`). Errors always look like:

```json
{ "error": { "code": "APPLICATION_ALREADY_EXISTS", "message": "You have already applied to this job.", "details": null, "request_id": "…" } }
```

Lists share one envelope: `{ "items": [], "page": 1, "page_size": 20, "total": 120, "pages": 6 }`. Long-running operations return `202 { "task_id": … }`; poll `GET /api/v1/tasks/{id}` for `status` / `progress` / `stage`. (The background-task resource is `/tasks` because `/jobs` is the job-posting resource.)

## Configuration

All configuration is environment-driven (`.env.example` lists everything; nothing secret is committed). `ENVIRONMENT=production` makes the server **refuse to start** with a weak `SECRET_KEY`, a published admin password, demo seeding, `DEBUG`, wildcard CORS or an insecure refresh cookie.

## Performance

Measured with `EXPLAIN (ANALYZE, BUFFERS)` on 30 k jobs / 50 k candidates / 150 k applications: [`docs/performance.md`](docs/performance.md) (index choices, before/after timings, one real ordering bug found by measuring).

## Limitations & honest notes

See the end of [`docs/verification.md`](docs/verification.md): no OCR for scanned résumés, no outbound e-mail, WordLlama is a static-embedding model (weaker than a transformer encoder on long contextual text), the evaluation set is small and synthetic, and the optional sentence-transformers backend is untested because the model host was unreachable in the build environment.
