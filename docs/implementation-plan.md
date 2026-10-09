# TalentLens — Implementation Plan

> Job Portal & Recruitment Management System with résumé processing and semantic candidate–job matching.
> This is the working plan; `README.md` is the user-facing description and `docs/*.md` hold the evidence
> (performance, security, evaluation, verification).

## 1. Current repository state

| Item | State at start |
|---|---|
| Code | None. The repository contained only a one-line `README.md` (initial commit). |
| Backend / frontend / Docker / CI / tests / migrations | Did not exist. |
| Sandbox facts that shaped the design | Docker daemon runs and pulls images; PostgreSQL 16 + Redis installed; `pgvector` installable via apt; **HuggingFace is unreachable**, PyPI and npm are reachable. |

Everything below was built from scratch. A sibling project by the same author (`inventory-demand-forecasting`)
was used only as a reference for proven operational patterns (ARQ worker with heartbeat/reaper, versioned-namespace
Redis cache, fail-open Redis, structured logging, Compose layout).

## 2. Target architecture

```
Browser ── React/TS SPA (nginx) ──/api──► FastAPI (async) ──► PostgreSQL 16 + pgvector (+ FTS, pg_trgm, btree_gist)
                                              │  └─────────► Redis  (cache · rate limit · ARQ queue)
                                              └─enqueue──────►  ARQ worker (résumé → text → parse → embed → match → notify)
```

* **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic.
* **Source of truth:** PostgreSQL only. Redis holds disposable state (cache, counters, queue).
* **Vectors:** `pgvector` (`vector(256)`, HNSW, cosine) inside the same database — no separate vector DB.
* **Layering:** `api/routes` (HTTP only) → `services` (business rules, authorization, transactions) → `db/models`.
  Domain packages hold pure logic that is unit-testable without a database: `resume/` (extraction + parsing),
  `matching/` (embedder, representation, scoring, explanation), `search/` (query builders).
* **Frontend:** React 19, TypeScript, Tailwind v4, Radix/shadcn-style components, TanStack Query, React Hook Form + zod, Recharts.

## 3. Backend modules

| Module | Responsibility |
|---|---|
| `core/` | settings (fail-closed in production), Argon2id + JWT, error taxonomy, structured logging, permission matrix |
| `db/models/` | SQLAlchemy models; naming convention; DB-level constraints |
| `services/` | auth, users, companies, skills, candidates, jobs, applications, interviews, notifications, resumes, matching, recommendations, search, reports, admin |
| `resume/` | storage abstraction, file validation (magic bytes, not client MIME), PDF/DOCX text extraction, section/skill/experience/education parsing |
| `matching/` | `Embedder` protocol + WordLlama implementation, text representations, scoring, explanation, evaluation harness |
| `search/` | job + candidate search (FTS + trigram + filters + vector re-rank) |
| `workers/` | ARQ worker, task dispatcher, task handlers, reaper, cron |
| `cache/` | Redis cache with namespace versioning, fixed-window rate limiter, both fail-open |

## 4. Database design (summary)

UUID primary keys (non-enumerable ids). Key tables: `users`, `companies`, `recruiter_profiles`, `refresh_tokens`,
`skills`, `skill_aliases`, `candidate_profiles`, `candidate_skills`, `experiences`, `educations`, `certifications`,
`candidate_languages`, `jobs`, `job_skills`, `saved_jobs`, `resumes`, `resume_documents`, `resume_processing_results`,
`applications`, `application_status_history`, `application_notes`, `interviews`, `interview_participants`,
`interview_feedback`, `candidate_job_matches`, `notifications`, `background_tasks`, `bulk_import_batches/items`, `audit_events`.

DB-enforced invariants (not only app-level): unique lower(email); staff roles must have a company
(`ck_users_staff_company`); salary range, experience, interview time, rating ranges via CHECK; partial unique index
for *one live application per candidate per job*; partial unique index for active duplicate jobs; **GiST exclusion
constraints** preventing overlapping interviews for the same candidate and the same interviewer; unique
`(job_id, candidate_id)` on matches; notification idempotency key.
Full detail and rationale in `docs/architecture.md` (written with the implementation).

## 5. Authentication & authorization

* Argon2id password hashing; JWT access token (15 min) + opaque, hashed, **rotating refresh token** in an
  `HttpOnly; SameSite=Strict` cookie scoped to `/api/v1/auth`, with reuse detection (token-family revoke).
  Logout revokes the family and denylists the access token `jti` in Redis (best effort, short TTL).
* Roles: `ADMIN`, `RECRUITER`, `HIRING_MANAGER`, `CANDIDATE`. Permission matrix in `core/security.py`;
  **object-level** checks (tenant isolation, ownership, assignment) live in `services/access.py` and are called by
  every service — route handlers never decide access themselves.
* Tenant boundary = company. Recruiters see only their company's jobs/applications/interviews; hiring managers only jobs
  assigned to them; candidates only their own data; candidate contact data and résumé files are released to a company only
  when a relationship exists (application or sourcing).

## 6. Recruitment workflows

* Job: `DRAFT → PUBLISHED ⇄ PAUSED → CLOSED → ARCHIVED` (+ `DRAFT → ARCHIVED`), transitions table-driven, role-checked.
* Application: `APPLIED → SCREENING → SHORTLISTED → INTERVIEW → OFFER → HIRED`; `REJECTED` from any live state before HIRED;
  `WITHDRAWN` from APPLIED/SCREENING (candidate). Every change writes `application_status_history` in the same transaction.
* Interview: `SCHEDULED → CONFIRMED/RESCHEDULED → COMPLETED/CANCELLED/NO_SHOW`; scheduling validates times, participants
  (same company, correct roles), application stage, and conflicts (DB exclusion constraint is the final arbiter).
* Feedback is internal-only; completing an interview + feedback can advance the application.

## 7. Résumé-processing pipeline

Upload (size/extension/magic-byte/zip-bomb checks, sanitized name, sha256) → `ResumeDocument` stored via `Storage`
abstraction (local volume now, S3-shaped interface) → `background_tasks` row (PENDING) → ARQ job → worker:
`extract text` → `parse (sections, contact, skills via ontology, experience, education, certs, languages)` →
`normalize` → `embed` → `ResumeProcessingResult` + `Resume.status` → refresh candidate embedding → enqueue match refresh →
in-app notification. Parser output is stored as *suggestions* (`source=RESUME`, `status=SUGGESTED`); the candidate confirms,
edits or rejects; user-entered data is never overwritten silently. Failures are recorded with safe error codes; retries are bounded.

## 8. Semantic matching architecture

1. **Representation** — job: title + summary + responsibilities + required/preferred skills + level; candidate: headline +
   summary + recent titles + skills + experience bullets + education + certifications + truncated résumé body. Bounded length,
   deterministic normalization, content hash for change detection. No protected attributes are ever features.
2. **Embedding** — `Embedder` protocol; default `WordLlamaEmbedder` (pretrained, 256-d, bundled in the wheel, CPU-only,
   offline, deterministic). Model name/version stored with every vector. Optional sentence-transformers adapter.
3. **Retrieval** — pgvector HNSW cosine for top-N candidate/job retrieval, combined with SQL eligibility filters.
4. **Scoring** — `0.30 semantic + 0.30 required skills + 0.10 preferred skills + 0.15 experience + 0.05 education + 0.10 preferences`
   with missing job-side criteria re-normalised out; skill coverage gives full credit for canonical/alias matches and partial credit
   for same-family skills (e.g. MySQL ↔ PostgreSQL). It is a *ranking/relevance* score, not a hiring probability.
5. **Explanation** — strong/related/missing skills, experience vs requirement, semantic band, preference notes.
6. **Persistence** — `candidate_job_matches` rows with component scores, explanation JSON, model/matching versions and source
   hashes; staleness detected by hash/version comparison; refreshed by background tasks on relevant change.
7. **Evaluation** — labeled demonstration set (`app/matching/eval/`), Precision@K / Recall@K / NDCG / MRR, compared against a
   lexical baseline; results in `docs/matching-evaluation.md` produced by a script, not hand-written.

## 9. Search strategy

Structured filters in SQL with targeted indexes; PostgreSQL FTS (`websearch_to_tsquery`, weighted generated `tsvector`,
GIN) for keywords; `pg_trgm` for typo-tolerant title/name matching; vector similarity for "match score" sorting and the
matching/recommendation features only. Pagination is `page`/`page_size` everywhere. Measured with `EXPLAIN (ANALYZE)` on a
synthetic bulk dataset — see `docs/performance.md`.

## 10. Background jobs & caching

ARQ on Redis (asyncio-native like the API; Celery would add a sync runtime and broker abstraction for no gain). Durable job
state lives in PostgreSQL (`background_tasks`: PENDING/RUNNING/COMPLETED/FAILED + progress), with queue-level dedupe keys, a
heartbeat + reaper for crashed workers, and bounded retries. Redis cache uses version-counter namespaces (O(1) invalidation);
every Redis call fails open; documented keys/TTLs in `docs/architecture.md`.

## 11. Testing strategy

pytest against **real** PostgreSQL (migrated by Alembic, incl. downgrade/upgrade) and **real** Redis: unit (pure logic),
integration (services/repositories/worker), API e2e (workflows 1–6 + failure matrix + authorization matrix). Vitest +
Testing Library + MSW for the SPA; Playwright for browser-level UI→API→DB→Worker flows against the Docker stack.
Ruff + mypy (backend), oxlint/ESLint + `tsc` (frontend). Nothing is mocked that the spec says must be real (DB, Redis, worker).

## 12. Deployment & CI

`docker compose up --build`: `postgres` (pgvector image), `redis`, one-shot `migrate` (alembic + bootstrap/seed), `api`, `worker`,
`web` (nginx, proxies `/api`). Health checks everywhere, `depends_on: service_healthy / service_completed_successfully`.
GitHub Actions: backend lint/types/tests with Postgres+Redis services, frontend lint/types/tests/build, Docker build + stack
smoke + Playwright.

## 13. Major technical decisions

| Decision | Choice | Why |
|---|---|---|
| Queue | ARQ | async-native, tiny, reuses services; durable state in PG |
| Vector store | pgvector in PostgreSQL | one source of truth, transactional, filterable with SQL |
| Embeddings | WordLlama (pretrained, bundled) | runs offline/CPU, deterministic, ~ms/doc; swappable via `Embedder` |
| IDs | UUID v4 | no enumeration of candidate/application ids |
| Refresh tokens | rotating, hashed, httpOnly cookie | no long-lived secret in JS-readable storage |
| Background-job API | `/api/v1/tasks/{id}` | `/jobs/{id}` is the job *posting* resource |
| Notifications | in-app (DB) + worker; email optional | no SMTP dependency for the demo |
| Skills | normalized table + aliases + families | structured matching and explainability |

## 14. Phases

1. Scaffold + core + schema + migrations ✅
2. Auth/RBAC, companies, skills, candidates, jobs, applications (+history), notifications
3. Résumé upload/validation/storage + extraction/parsing + worker
4. Embeddings, matching, recommendations, evaluation
5. Interviews + feedback, search, reports/dashboards, admin
6. Seed scenarios, backend test suite, lint/type gates
7. Frontend (shell → recruiter → candidate → admin), frontend tests
8. Docker, CI, full-system validation (API + browser), performance/security review, documentation
