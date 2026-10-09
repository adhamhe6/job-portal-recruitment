# Verification record

Everything below was **run**, on the dates and against the targets stated, and the numbers are copied from the tool output.
Where something was *not* verified, or was verified only in part, it says so. Re-run commands are given for each item.

Environment: Linux container, Python 3.13 (local virtualenv) and 3.12 (Docker image and CI), Node 22, PostgreSQL 16.15 + pgvector 0.6.0,
Redis 7, Docker 29, Chromium 1194 (Playwright). Date of the runs: 2026-10-09.

## 1. Summary

| Gate | Result | Command |
|---|---|---|
| Backend lint | pass | `ruff check app tests scripts` |
| Backend formatting | pass (186 files) | `ruff format --check app tests scripts` |
| Backend types | pass (112 source files) | `mypy app` |
| Migrations match models | pass (`No new upgrade operations detected.`) | `alembic upgrade head && alembic check` |
| Backend tests | **1771 passed**, 0 failed (7 min 08 s) | `pytest -q` |
| Backend line coverage | **85 %** (10 859 statements, 1 634 missed), measured in an earlier run of the same suite | `pytest --cov=app` |
| Frontend lint / format / types / build | pass / pass / pass / pass | `npm run lint && npm run format:check && npm run typecheck && npm run build` |
| Frontend tests | **502 passed** in 41 files | `npm test` |
| Browser end-to-end (Playwright, real Docker stack) | **15 passed** (1.0 min) | `cd e2e && npx playwright test` |
| Docker Compose stack | builds; all six services healthy; seeded by the one-shot `migrate` service | `docker compose up -d --build --wait` |
| Matching evaluation | report regenerated, see `matching-evaluation.md` | `python -m app.matching.eval` |
| Query-plan measurements | see `performance.md` | `backend/scripts/perf/` |

The backend suite was run against a database created with an **ICU `en-US` collation** (to imitate the collation of the PostgreSQL image
used in CI) as well as the sandbox's default `C` collation; the two differ in alphabetical ordering, which is how three CI-only failures
were found and fixed (§4).

**CI (GitHub Actions)** runs three jobs: backend (lint, types, migrations, tests), frontend (lint, format, types, tests, build) and
Docker (image build, full-stack smoke through nginx, and the Playwright suite against the Compose stack). On commit `958757f` **all three
jobs passed** (backend 7 min 48 s, frontend 3 min 03 s, Docker + browser e2e 4 min 36 s). Earlier runs on this branch failed for reasons
that were not application defects and were fixed (Docker Hub rate-limiting of the service-container pulls; a collation-dependent ordering
bug, see §4); the history is on the pull request.

## 2. What the tests cover

### Backend — `pytest` (real PostgreSQL + real Redis; nothing is mocked that the specification says must be real)

* The session starts by running Alembic **downgrade → upgrade** on an empty database, so the migration is exercised on every run; the
  skills ontology is seeded once and every test starts from a truncated database and an empty Redis.
* **363 unit-test functions** (pure logic: scoring, representation, parser, validation, security primitives, state-machine tables,
  config safety checks, SQL shape of the search queries), **246 integration-test functions** (services, constraints, worker/queue
  round trip through a real ARQ worker, cache and Redis-outage behaviour, the demo seed) and **355 API end-to-end test functions**
  (every route family, authorization matrices, the error envelope, the OpenAPI contract). Parametrised tests make the executed total 1771.
* Authorization is tested as matrices (each role × each endpoint family, own vs. foreign tenant), including 404-for-foreign-tenant.
* Failure paths: corrupt/empty/encrypted/oversized/disguised uploads, queue unavailable at enqueue time, worker crash recovery (reaper),
  Redis down (fail-open), concurrent interview booking (database exclusion constraint decides), duplicate applications under a race.

### Frontend — Vitest + Testing Library + MSW (502 tests)

Per-feature suites (jobs, auth, notifications, profile, résumé review, recommendations, applications pipeline and detail, candidates and
bulk import, matching, interviews and the scheduling conflict dialog, reports and CSV export, admin and settings) plus route guards
and API-client tests. They cover loading / error / empty states, role differences and permission denials.
`jsdom` drops multipart file names, so upload tests assert size and flags rather than the file name.

### Browser end-to-end — Playwright against the running Docker stack (15 scenarios)

UI → nginx → API → PostgreSQL/Redis → worker → UI, using the seeded demo data:

| Scenario | Spec |
|---|---|
| Authentication, bad credentials, RBAC page guards, session survives reload and ends on sign-out | `auth-rbac.spec.ts` (4) |
| Candidate searches, applies with a cover letter, sees it listed, withdraws | `candidate-apply.spec.ts` (1) |
| Recruiter creates and publishes a job → it is publicly searchable → a new candidate applies → recruiter moves them through the pipeline and records a note | `recruiter-job-pipeline.spec.ts` (1) |
| Résumé upload → worker parses it → review → apply accepted suggestions → profile; a non-PDF is rejected | `resume-review.spec.ts` (2) |
| Interview double-booking is refused with a clear conflict, a free slot is accepted, the candidate confirms; feedback is internal | `interviews.spec.ts` (2) |
| Explained ranked matches and a worker-backed refresh; reports + CSV download; admin monitoring | `matching-reports-admin.spec.ts` (3) |
| No horizontal overflow at 375 px on public, candidate and recruiter pages; mobile navigation | `responsive.spec.ts` (2) |

The suite is re-runnable against the same database (unique slots / accounts per run). It needs the registration and login rate limits
raised for the stack under test (the app deliberately limits them); `docker-compose.yml` exposes `LOGIN_RATE_LIMIT_ATTEMPTS` and
`REGISTER_RATE_LIMIT_ATTEMPTS` for this and CI sets them for its browser job.

## 3. Things verified by hand against the live stack

* **Security probes** (`security-review.md` §4): response headers, mass assignment on registration, SQL-injection-shaped search input,
  cross-tenant read (404), unauthenticated / garbage-token access (401), role escalation to staff/admin endpoints (403), disguised and
  oversized uploads (415 / 413).
* **Resilience:** the API container was recreated while nginx ran; before the fix nginx kept the stale address (502 until restarted), after
  switching nginx to re-resolve through Docker DNS the stack recovers on its own (502 only while the new container starts).
* **Seed:** `python -m app.scripts.seed --reset` takes about 25 s and produces 16 candidates with generated PDF résumés that go through the
  real parser, 14 jobs in every lifecycle state, 20 applications, 5 interviews (upcoming, confirmed, completed with feedback). A test
  (`tests/integration/test_seed.py`) keeps this from rotting.
* **UI at phone width:** the frontend engineers checked each new page at 375 px and 1280 px in Chromium (no horizontal overflow, no
  console errors other than the expected 401 of the silent session refresh at boot); `responsive.spec.ts` automates the overflow check.

## 4. Defects found by this verification (and fixed)

| Found by | Defect | Fix |
|---|---|---|
| CI | Alphabetical ordering of skills and job titles in reports depended on the database collation (3 tests failed only on CI's `en_US` PostgreSQL) | order by `lower(x) COLLATE "C"`; tests compare case-insensitively; suite re-run on an ICU collation |
| Query-plan measurement | `ORDER BY published_at DESC NULLS LAST` could not use the partial index (60 ms vs 2 ms) | plain `DESC`, pinned by a unit test (`performance.md`) |
| Browser test | Removing a skill in the résumé review left the matching "suggested from your résumé" skill on the profile | removal now dismisses the profile suggestion; regression test fails without the fix |
| Compose smoke | nginx cached the API address at start-up → 502 after the API container was recreated | re-resolve through Docker DNS (`resolver 127.0.0.11`) |
| Browser test | Login/registration rate limits (working as designed) blocked the suite | configurable via environment for the e2e stack only |
| CI | Docker Hub throttling of `pgvector/pgvector`/`redis` service-container pulls failed the backend job before any code ran | backend job uses the runner's PostgreSQL + `postgresql-16-pgvector` and Redis from apt |
| Seed review | The demo had no résumés or interviews | seed now uploads generated PDFs and schedules/completes interviews |
| Frontend | 22 pages were still "under construction" placeholders at the start of the frontend wave | all implemented; the route-guard test now asserts real pages |

## 5. Limitations and honest notes

* **Matching quality evidence is weak by construction.** 12 jobs × 16 candidates, labelled by the authors, synthetic profiles. The baselines
  (keyword TF-IDF, exact skill overlap) score almost as well on it; the numbers show sensible behaviour, not real-world accuracy.
  No fairness / disparate-impact measurement was done (it needs real, consented data).
* **WordLlama is a static-embedding model**: fast, offline and deterministic, but weaker than a transformer encoder on long contextual
  text. The optional sentence-transformers backend is **untested** (the model host was unreachable here).
* **Résumé parsing is rule-based.** It handled the generated PDFs and test fixtures well; it will make mistakes on unusual layouts, and
  scanned/image résumés are rejected (no OCR). Years of experience are computed from date ranges and can be overstated.
* **No e-mail/SMS delivery**: notifications are in-app only; there is no invitation or password-reset e-mail flow.
* **Security:** self-review only (see `security-review.md`): no TLS in the shipped Compose file, no MFA, no malware scanning of uploads,
  no dependency-vulnerability gate in CI, no third-party penetration test.
* **Accessibility** was designed in (labels, roles, focus management, keyboard alternatives, text alternatives for charts) and exercised
  through Testing Library role queries, but **no automated axe/WAVE audit and no screen-reader pass was run**.
* **Browser coverage:** Chromium only; no Firefox/WebKit/Safari runs.
* **Performance numbers** (`performance.md`) come from one machine and a synthetic dataset; they show relative effects, not an SLA.
  Load/stress testing under concurrent users was not performed beyond the concurrency tests for booking, applications and task claiming.
* **Frontend gaps noted by the implementers:** no hiring-manager job-assignment UI, no company logo upload (URL only), interview
  "history" is limited to the data the API provides, ZIP bulk import is not supported by the backend, and the board view's column counts
  cover the current page only.
* **Docker Hub rate limiting** affected image pulls in the sandbox and on CI runners; builds retry, and the backend CI job no longer
  depends on it, but the Docker/browser CI job still pulls base images from Docker Hub.
* **Not run:** Compose against a managed/production-like environment (TLS, secrets management, backups), horizontal scaling of
  API/worker replicas (the design allows it; it was not exercised).

## 6. Future work

Real-data evaluation and a fairness audit of the matching; a transformer-based embedder behind the existing `Embedder` interface
(with a migration for the vector dimension); OCR for scanned résumés; e-mail notifications and invitations; MFA and password reset;
retention / erasure / data-export workflows for candidate data; keyset pagination for very large candidate searches; an axe-based
accessibility gate and cross-browser e2e in CI; dependency scanning; object storage for résumés.
