"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import api_router
from app.cache.redis_cache import close_redis, get_cache, get_redis
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_ctx, user_id_ctx
from app.db.database import dispose_engine, get_engine
from app.schemas.common import ErrorResponse

logger = logging.getLogger("app.request")

OPENAPI_TAGS = [
    {"name": "Authentication", "description": "Register, sign in, rotate refresh tokens. Access tokens are short-lived JWTs sent as `Authorization: Bearer …`; the refresh token lives in an HttpOnly cookie."},
    {"name": "Users (admin)", "description": "Platform user administration. **ADMIN only.**"},
    {"name": "Companies", "description": "Tenants. Recruiters can only see and change their own company's data."},
    {"name": "Skills", "description": "Structured skill taxonomy with aliases and related-skill families."},
    {"name": "Candidates", "description": "Candidate profile, experience, education, skills and recruiter-facing candidate views."},
    {"name": "Jobs", "description": "Job postings and their lifecycle (DRAFT → PUBLISHED ⇄ PAUSED → CLOSED → ARCHIVED)."},
    {"name": "Search", "description": "Public job search and recruiter candidate search (PostgreSQL FTS + trigram + filters + vectors)."},
    {"name": "Resumes", "description": "Résumé upload, validation, asynchronous processing and extracted-data review."},
    {"name": "Applications", "description": "Applications, the stage workflow, history and internal notes."},
    {"name": "Interviews", "description": "Interview scheduling, participants, conflicts and structured feedback."},
    {"name": "Matches", "description": "Semantic candidate↔job matching: ranked candidates and score explanations."},
    {"name": "Recommendations", "description": "Recommended jobs for the signed-in candidate."},
    {"name": "Notifications", "description": "In-app notification centre."},
    {"name": "Reports", "description": "Dashboards, funnel and analytics reports (CSV export available)."},
    {"name": "Tasks", "description": "Status of background work (résumé processing, matching, bulk import)."},
    {"name": "Admin", "description": "System monitoring and maintenance. **ADMIN only.**"},
    {"name": "Health", "description": "Liveness and readiness."},
]


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details, "request_id": request_id_ctx.get()}}
    return JSONResponse(status_code=status_code, content=body)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.workers.dispatch import build_dispatcher

        app.state.dispatcher, closer = await build_dispatcher()
        logger.info("api started", extra={"environment": settings.environment, "version": __version__})
        try:
            yield
        finally:
            await closer()
            await close_redis()
            await dispose_engine()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=(
            "Job portal & recruitment management API: companies, jobs, candidates, résumé processing, "
            "applications, interviews and **semantic candidate↔job matching**.\n\n"
            "**Auth:** call `POST /api/v1/auth/login` (or use *Authorize*), then send the access token as a Bearer token. "
            "**Matching** produces a ranking/relevance score to assist recruiters — it is not an automated hiring decision."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Content-Disposition"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_ctx.set(rid[:64])
        user_id_ctx.set(None)
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
            response = _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = rid[:64]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path not in ("/health", "/health/ready"):
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code == 401:
            logger.warning("authentication failure", extra={"code": exc.code})
        elif exc.status_code == 403:
            logger.warning("authorization failure", extra={"code": exc.code})
        resp = _error_response(exc.status_code, exc.code, exc.message, exc.details)
        if exc.status_code == 401:
            resp.headers["WWW-Authenticate"] = "Bearer"
        if exc.status_code == 429 and isinstance(exc.details, dict) and "retry_after_seconds" in exc.details:
            resp.headers["Retry-After"] = str(exc.details["retry_after_seconds"])
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return _error_response(422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}
        return _error_response(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))

    @app.exception_handler(OperationalError)
    async def db_unavailable_handler(_: Request, exc: OperationalError) -> JSONResponse:
        logger.error("database unavailable", extra={"error": type(exc.orig).__name__ if exc.orig else "OperationalError"})
        return _error_response(503, "SERVICE_UNAVAILABLE", "The database is temporarily unavailable")

    @app.exception_handler(DBAPIError)
    async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
        logger.error("database error", extra={"error": type(exc.orig).__name__ if exc.orig else "DBAPIError"})
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception", extra={"error": type(exc).__name__})
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    app.include_router(api_router, prefix=settings.api_prefix)

    # --- health -----------------------------------------------------------------------------------
    @app.get("/health", tags=["Health"], summary="Liveness", include_in_schema=True)
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get(
        "/health/ready",
        tags=["Health"],
        summary="Readiness (database, pgvector, Redis, embedder)",
        responses={503: {"model": ErrorResponse}},
    )
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        ok = True
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
                ext = (await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))).scalar()
                checks["database"] = "ok"
                checks["pgvector"] = "ok" if ext else "missing"
                ok = ok and bool(ext)
        except Exception:
            checks["database"] = "unavailable"
            ok = False
        checks["redis"] = "ok" if await get_cache().ping() else "unavailable (degraded: cache/queue disabled)"
        # Redis is an optimisation, not a source of truth; readiness depends only on PostgreSQL.
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", "checks": checks})

    return app


app = create_app()
_ = get_redis  # re-exported for tests that patch the client
