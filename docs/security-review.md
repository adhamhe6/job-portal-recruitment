# Security and privacy review

Scope: the code in this repository as deployed by `docker compose up`. "Evidence" names either an automated test that runs in CI or a
probe that was run against the live Compose stack during review (commands and outcomes are in the *Live probes* section).
This is a self-review by the authors, **not** an independent penetration test.

## 1. Threat model in one paragraph

Assets: candidate personal data (contact details, résumés, work history), recruiter notes and interview feedback, tenant isolation
between companies, credentials. Actors: anonymous visitors, candidates, recruiters/hiring managers (tenant-scoped), admins, and a
hostile authenticated user trying to reach another tenant's data or escalate their role. Out of scope here: TLS termination and network
perimeter (the Compose stack serves plain HTTP on localhost; see *Deployment hardening*), host/container hardening, and email delivery.

## 2. Controls and evidence

| Concern | Control | Evidence |
|---|---|---|
| Authentication | Argon2id password hashing; 15-minute JWT access token held in memory only; opaque, hashed, single-use rotating refresh token in an `HttpOnly; SameSite=Strict` cookie scoped to `/api/v1/auth`; presenting a used refresh token revokes the whole token family; logout denylists the access-token `jti` (Redis, best effort) | `tests/unit/test_security.py`, `tests/e2e/test_auth_flows.py` (rotation, reuse detection, logout), `tests/integration/test_redis_outage.py` (denylist fails open); Playwright `auth-rbac.spec.ts` (session survives reload, ends on sign-out) |
| Credential brute force | Fixed-window rate limit on login (default 10 attempts / 5 min per client), registration, uploads, search and expensive endpoints; fails open if Redis is down | Observed live: repeated sign-ins from one address returned *"Too many sign-in attempts"* (this had to be raised for the e2e suite via `LOGIN_RATE_LIMIT_ATTEMPTS`) |
| Authorization (function level) | Role permission matrix in `core/security.py`, enforced by FastAPI dependencies; server-side only (the UI hides things but never decides) | Live probes: candidate → `/search/candidates` 403, `/admin/system` 403; anonymous → 401; garbage bearer → 401; Playwright RBAC scenarios |
| Authorization (object level / tenancy) | Every service call goes through `services/access.py`; a resource of another tenant answers **404**, not 403, so existence is not disclosed | Live probe: Northwind application → own recruiter 200, another company's recruiter 404; `tests/integration/test_*authorization*.py` and the per-feature authorization matrices |
| Mass assignment | Pydantic request schemas whitelist fields; role is never taken from a public registration body | Live probe: `POST /auth/register` with `"role":"ADMIN"` created a **CANDIDATE** (the issued token's `role` claim is `CANDIDATE`) |
| Injection (SQL) | SQLAlchemy parameterised queries only; `LIKE` input escaped (`escape_like`); FTS via `websearch_to_tsquery` | Live probe: `q=' OR 1=1; DROP TABLE jobs;--` returned an empty, well-formed result; search SQL shape pinned by unit tests |
| XSS | React escapes output; no `dangerouslySetInnerHTML`/`innerHTML` anywhere in `frontend/src`; strict CSP (`script-src 'self'`, `frame-ancestors 'none'`) | grep of the source; response headers observed live |
| CSV / formula injection | Cells starting with `= + - @` are prefixed with `'` in every CSV export | `tests/integration/test_report_csv.py` |
| File upload | Size cap enforced while streaming; type decided by **magic bytes** not the client MIME/extension; DOCX must be a sound OOXML ZIP with member-count and uncompressed-size (zip-bomb) limits; names sanitised and never used as storage paths (storage key is generated); per-user upload rate limit | Live probes: an executable renamed `.pdf` → 415 `CONTENT_NOT_RECOGNISED`; a 14 MB body → 413 from nginx (limit 12 MB, API limit 5 MB); `tests/unit/test_resume_validation.py`, `tests/integration/test_resume_authorization.py` |
| Résumé file access | Download only through an authorised API call (owner, or staff of a company with an application/sourcing relationship); no static file serving of the storage directory | `tests/integration/test_resume_authorization.py` |
| CSRF | State-changing calls need a bearer token in the `Authorization` header (not a cookie); the only cookie-authenticated endpoints are `/auth/refresh` and `/auth/logout`, protected by `SameSite=Strict` | design; `tests/e2e/test_auth_flows.py` |
| CORS | Explicit allow-list from `CORS_ORIGINS`; wildcard rejected in production; the Compose stack serves UI and API from one origin through nginx | `core/config.py` production validator |
| Secrets & configuration | `ENVIRONMENT=production` refuses to start with the published dev `SECRET_KEY`, a default admin password, demo seeding, `DEBUG`, wildcard CORS, or an insecure refresh cookie; `.env` is git-ignored; `.env.example` marks every value as development-only | `tests/unit/test_config.py` |
| Logging | Structured JSON; keys named password/token/secret/authorization/api_key/cookie are redacted before serialisation; every request carries an `X-Request-ID` that also appears in error bodies | `core/logging.py`, observed in container logs |
| Error handling | One error envelope; unexpected exceptions return a generic 500 with a request id, never a stack trace or SQL | `tests/e2e/test_error_envelope.py` |
| Audit | Application status history, interview and feedback changes, account/role/company changes and security events are recorded in history tables / `audit_events` in the same transaction as the change (the application does not expose update or delete for them; the database does not otherwise forbid it) | per-feature tests |
| Dependency & image hygiene | Pinned `requirements.lock`, `package-lock.json`; multi-stage Docker builds; API image runs as non-root; no secrets in images | `backend/Dockerfile` |

## 3. Privacy and fairness

* **Data minimisation / visibility.** A candidate profile can be marketplace-visible or not; contact details are released to a company
  only where an application or sourcing relationship exists. Interview feedback and recruiter notes are never returned to candidates.
* **No protected attributes in matching.** Matching inputs are skills, experience, education, role text and stated preferences. Name,
  gender, age, nationality and photo are not features (`tests/unit/test_representation.py` asserts the candidate representation carries no identity fields).
* **Explainability.** Every score is stored with its component breakdown and a human-readable explanation; the UI states that it is a
  ranking aid, not a hiring decision.
* **Not measured:** disparate impact across demographic groups. That requires real, consented data and was not attempted
  (see `docs/matching-evaluation.md`).
* **Retention.** A scheduled worker job purges expired refresh tokens and old completed tasks; there is **no** automated candidate-data
  retention/erasure workflow or data-subject export yet (listed under limitations).

## 4. Live probes (Compose stack, 2026-10-09)

Run with `curl` against `http://localhost:8080`; each result above is what was actually returned. Not exhaustively probed: the path-traversal
case (a `../` filename) was only sent with non-PDF content, so it was rejected for content type before the name mattered — filename sanitisation
is covered by unit tests, not by that probe.

## 5. Known gaps and residual risks

1. **No TLS in the shipped Compose file.** `REFRESH_COOKIE_SECURE=false` by default for localhost; production mode refuses that setting, so
   a real deployment must terminate HTTPS in front of nginx and set it to `true`. HSTS is therefore not sent by the shipped nginx.
2. **Access-token logout is best effort.** The `jti` denylist is in Redis and fails open; a stolen access token stays valid until it expires
   (≤ 15 minutes) if Redis is unavailable at logout time.
3. **No account lockout or MFA.** Only rate limiting. No email verification or password-reset email flow (no SMTP dependency).
4. **Rate limiting keys on the client address as seen by the API** (`X-Forwarded-For` from nginx). Behind another proxy, configure trusted
   proxies, otherwise clients share a bucket.
5. **API responses carry fewer security headers than the SPA** (the API sets `X-Content-Type-Options` and `X-Request-ID`; the strict CSP applies to the SPA).
   The Swagger UI at `/docs` loads assets from a CDN and is therefore exempt from the strict CSP; disable `/docs` in production if undesired.
6. **No malware scanning of uploaded résumés** (type/structure validation only). Files are never executed or served inline.
7. **Résumé parsing runs in the worker process** on untrusted files with size/time limits but without an OS-level sandbox.
8. **Demo accounts share a published password.** Seeding is refused when `ENVIRONMENT=production`.
9. **Dependency vulnerability scanning is not wired into CI** (no `pip-audit`/`npm audit` gate).
10. **Not independently tested.** No third-party penetration test or fuzzing was performed.
