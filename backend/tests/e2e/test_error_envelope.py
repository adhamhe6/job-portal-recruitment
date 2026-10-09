"""Every failure - validation, auth, missing routes, conflicts, limits, crashes - uses one envelope and leaks nothing."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    UnsupportedMediaError,
)
from app.main import app
from tests.helpers import auth, create_job, job_payload, register_candidate, register_employer
from tests.helpers_spine import API, assert_error, client_from, fast_argon  # noqa: F401

pytestmark = pytest.mark.e2e

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


def assert_hardened(resp: Any) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers.get(name) == value, (name, dict(resp.headers))


# --- one envelope for everything -----------------------------------------------------------------------------------------------------------------------


async def test_the_documented_error_classes_share_the_envelope(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    job = await create_job(client, rec, publish=True)
    cases = [
        (await client.post(f"{API}/auth/login", json={"email": "bad"}), 422, "VALIDATION_ERROR"),
        (await client.get(f"{API}/auth/me"), 401, "UNAUTHORIZED"),
        (await client.get(f"{API}/auth/me", headers=auth("junk")), 401, "INVALID_TOKEN"),
        (await client.get(f"{API}/users", headers=cand["h"]), 403, "FORBIDDEN"),
        (await client.get(f"{API}/jobs/{uuid.uuid4()}"), 404, "JOB_NOT_FOUND"),
        (await client.get(f"{API}/this/does/not/exist"), 404, "NOT_FOUND"),
        (await client.put(f"{API}/search/jobs"), 405, "METHOD_NOT_ALLOWED"),
        (await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job["id"]}), 201, None),
        (
            await client.post(f"{API}/applications", headers=cand["h"], json={"job_id": job["id"]}),
            409,
            "APPLICATION_ALREADY_EXISTS",
        ),
        (
            await client.post(f"{API}/jobs/{job['id']}/publish", headers=rec["h"]),
            409,
            "INVALID_STATE_TRANSITION",
        ),
        (
            await client.patch(
                f"{API}/jobs/{job['id']}", headers=rec["h"], json={"salary_min": 10, "salary_max": 5}
            ),
            422,
            "INVALID_SALARY_RANGE",
        ),
    ]
    for resp, status, code in cases:
        if code is None:
            assert resp.status_code == status
            continue
        assert_error(resp, status, code)
        assert_hardened(resp)


async def test_the_envelope_has_exactly_four_fields_and_correlates_with_the_header(
    client: AsyncClient,
) -> None:
    r = await client.get(f"{API}/jobs/{uuid.uuid4()}", headers={"X-Request-ID": "req-abc-123"})
    assert r.json() == {
        "error": {
            "code": "JOB_NOT_FOUND",
            "message": "Job not found",
            "details": None,
            "request_id": "req-abc-123",
        }
    }
    assert r.headers["x-request-id"] == "req-abc-123"


async def test_validation_details_name_the_offending_fields(client: AsyncClient) -> None:
    err = assert_error(
        await client.post(
            f"{API}/auth/register/employer",
            json={"email": "x", "password": "y", "first_name": "a", "last_name": "b", "company_name": "c"},
        ),
        422,
        "VALIDATION_ERROR",
    )
    fields = {d["field"] for d in err["details"]}
    assert {"email", "password", "company_name"} <= fields
    assert all(set(d) == {"field", "message", "type"} for d in err["details"])
    nested = assert_error(
        await client.post(
            f"{API}/jobs",
            headers=(await register_employer(client))["h"],
            json=job_payload(skills=[{"name": "x", "requirement": "NOPE"}]),
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert any(d["field"].startswith("skills.0") for d in nested["details"])
    query = assert_error(await client.get(f"{API}/search/jobs", params={"page": 0}), 422, "VALIDATION_ERROR")
    assert query["details"][0]["field"] == "page"
    path = assert_error(await client.get(f"{API}/jobs/not-a-uuid"), 422, "VALIDATION_ERROR")
    assert path["details"][0]["field"] == "job_id"


async def test_rejected_input_is_not_echoed_back(client: AsyncClient) -> None:
    secret = "hunter2-Hunter2-very-secret"
    r = await client.post(
        f"{API}/auth/register",
        json={"email": "not-an-email", "password": secret[:5], "first_name": secret, "last_name": ""},
    )
    assert r.status_code == 422 and secret not in r.text and secret[:5] not in r.text.replace("password", "")


async def test_unknown_routes_and_methods(client: AsyncClient) -> None:
    r404 = await client.get("/definitely-not-here")
    assert_error(r404, 404, "NOT_FOUND")
    r405 = await client.delete(f"{API}/auth/login")
    assert_error(r405, 405, "METHOD_NOT_ALLOWED")
    assert "POST" in r405.headers.get("allow", "")
    assert_hardened(r404)
    assert_error(await client.get(f"{API}/jobs/{uuid.uuid4()}/publish"), 405, "METHOD_NOT_ALLOWED")


async def test_wrong_content_types_and_malformed_bodies_are_client_errors(client: AsyncClient) -> None:
    rec = await register_employer(client)
    url = f"{API}/jobs"
    assert_error(
        await client.post(url, headers={**rec["h"], "content-type": "text/plain"}, content="title=x"),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(url, headers={**rec["h"], "content-type": "application/json"}, content=b"{"),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(url, headers={**rec["h"], "content-type": "application/json"}, content=b""),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(await client.post(url, headers=rec["h"], json="a string"), 422, "VALIDATION_ERROR")
    assert_error(await client.post(url, headers=rec["h"], json=None), 422, "VALIDATION_ERROR")
    assert_error(
        await client.post(
            url, headers={**rec["h"], "content-type": "application/json"}, content=b"\xff\xfe\x00"
        ),
        400,
        "BAD_REQUEST",
    )


@pytest.mark.parametrize("field", ["title", "description"])
async def test_nul_characters_are_a_validation_error_not_a_server_error(
    client: AsyncClient, field: str
) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    bad = job_payload(**{field: "before\x00after " * 5})
    assert_error(await client.post(f"{API}/jobs", headers=rec["h"], json=bad), 422, "VALIDATION_ERROR")
    assert_error(
        await client.patch(f"{API}/candidates/me", headers=cand["h"], json={"headline": "x\x00y"}),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(
        await client.post(f"{API}/candidates/me/skills", headers=cand["h"], json={"name": "Py\x00thon"}),
        422,
        "VALIDATION_ERROR",
    )
    assert_error(await client.get(f"{API}/skills", params={"q": "a\x00b"}), 422, "VALIDATION_ERROR")
    assert_error(
        await client.get(f"{API}/search/jobs", params={"location": "a\x00b"}), 422, "VALIDATION_ERROR"
    )
    assert_error(
        await client.post(
            f"{API}/auth/register",
            json={
                "email": "nul@test.example",
                "password": "CorrectHorse42",
                "first_name": "A\x00",
                "last_name": "B",
            },
        ),
        422,
        "VALIDATION_ERROR",
    )
    ok = await client.patch(f"{API}/candidates/me", headers=cand["h"], json={"headline": "fine"})
    assert ok.status_code == 200, "a rejected request must not poison the connection or session"


async def test_unusual_but_valid_unicode_is_accepted(client: AsyncClient) -> None:
    rec = await register_employer(client)
    cand = await register_candidate(client)
    r = await client.post(
        f"{API}/jobs", headers=rec["h"], json=job_payload("Ingénieur Backend 🚀 日本語", location="Zürich")
    )
    assert r.status_code == 201 and r.json()["title"] == "Ingénieur Backend 🚀 日本語"
    assert (
        await client.patch(
            f"{API}/candidates/me", headers=cand["h"], json={"headline": "Entwickler für Käse 🧀"}
        )
    ).json()["headline"] == "Entwickler für Käse 🧀"


# --- request ids + headers -----------------------------------------------------------------------------------------------------------------------------------------


async def test_request_ids_are_generated_unique_and_present_on_every_response(client: AsyncClient) -> None:
    ids = set()
    for url in ("/health", f"{API}/skills", f"{API}/auth/me", "/nope"):
        r = await client.get(url)
        rid = r.headers["x-request-id"]
        assert re.fullmatch(r"[0-9a-f]{32}", rid), rid
        ids.add(rid)
        assert_hardened(r)
    assert len(ids) == 4


async def test_client_supplied_request_ids_are_echoed_but_bounded(client: AsyncClient) -> None:
    r = await client.get("/health", headers={"X-Request-ID": "x" * 200})
    assert r.headers["x-request-id"] == "x" * 64
    r = await client.get(f"{API}/auth/me", headers={"X-Request-ID": "trace-1"})
    assert r.headers["x-request-id"] == "trace-1" and r.json()["error"]["request_id"] == "trace-1"


async def test_cors_allows_the_configured_origin_only(client: AsyncClient) -> None:
    origin = get_settings().cors_origins[0]
    ok = await client.options(
        f"{API}/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert (
        ok.status_code == 200
        and ok.headers["access-control-allow-origin"] == origin
        and ok.headers["access-control-allow-credentials"] == "true"
    )
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    evil = await client.options(
        f"{API}/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers and evil.status_code == 400
    simple = await client.get("/health", headers={"Origin": origin})
    assert (
        simple.headers["access-control-allow-origin"] == origin
        and "x-request-id" in simple.headers["access-control-expose-headers"].lower()
    )
    assert (
        "access-control-allow-origin"
        not in (await client.get("/health", headers={"Origin": "https://evil.example"})).headers
    )


# --- crashes -------------------------------------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def boom_routes() -> Iterator[None]:
    """Test-only routes that fail in every way the application can fail."""
    router = APIRouter(prefix="/__test")

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internals: /etc/passwd password=hunter2 postgresql://user:pw@db/x")

    @router.get("/zero")
    async def zero() -> int:
        return 1 // 0

    @router.get("/db-down")
    async def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused to 10.0.0.5:5432 password=pw"))

    @router.get("/db-error")
    async def db_error() -> None:
        raise DBAPIError("SELECT secret FROM t", {}, Exception('relation "secret_table" does not exist'))

    @router.get("/db-data")
    async def db_data() -> None:
        class Cause(Exception):
            sqlstate = "22021"

        orig = Exception("invalid byte sequence")
        orig.__cause__ = Cause()
        raise DBAPIError("INSERT ...", {}, orig)

    for status_cls, name in (
        (NotFoundError, "nf"),
        (ConflictError, "conflict"),
        (BusinessRuleError, "rule"),
        (PermissionDeniedError, "denied"),
        (PayloadTooLargeError, "big"),
        (UnsupportedMediaError, "media"),
    ):

        def make(cls: type[AppError] = status_cls) -> Any:
            async def handler() -> None:
                raise cls("Something specific", code="CUSTOM_CODE", details={"hint": [1, 2]})

            return handler

        router.add_api_route(f"/app-error/{name}", make(), methods=["GET"])

    app.include_router(router)
    added = [r for r in app.router.routes if getattr(r, "path", "").startswith("/__test")]
    yield
    for r in added:
        app.router.routes.remove(r)


async def test_unexpected_exceptions_become_a_generic_500_without_internals(
    client: AsyncClient, boom_routes: None, caplog: pytest.LogCaptureFixture
) -> None:
    for path in ("/__test/crash", "/__test/zero"):
        r = await client.get(path)
        err = assert_error(r, 500, "INTERNAL_ERROR")
        assert err["message"] == "An unexpected error occurred" and err["details"] is None
        body = r.text
        for leak in (
            "Traceback",
            "RuntimeError",
            "ZeroDivisionError",
            "passwd",
            "hunter2",
            "postgresql://",
            'File "',
            "/home/",
            ".py",
        ):
            assert leak not in body, (path, leak)
        assert_hardened(r)
    assert any("unhandled" in rec.getMessage() for rec in caplog.records), "the failure is logged server-side"


async def test_database_failures_are_mapped_without_leaking_sql(
    client: AsyncClient, boom_routes: None
) -> None:
    down = await client.get("/__test/db-down")
    err = assert_error(down, 503, "SERVICE_UNAVAILABLE")
    assert (
        "refused" not in down.text
        and "10.0.0.5" not in down.text
        and "SELECT" not in down.text
        and err["message"].startswith("The database is temporarily")
    )
    generic = await client.get("/__test/db-error")
    assert_error(generic, 500, "INTERNAL_ERROR")
    assert "secret_table" not in generic.text and "SELECT" not in generic.text
    data = await client.get("/__test/db-data")
    assert_error(data, 422, "VALIDATION_ERROR")
    assert "INSERT" not in data.text


@pytest.mark.parametrize(
    ("name", "status"),
    [("nf", 404), ("conflict", 409), ("rule", 422), ("denied", 403), ("big", 413), ("media", 415)],
)
async def test_application_errors_keep_their_status_code_details_and_envelope(
    client: AsyncClient, boom_routes: None, name: str, status: int
) -> None:
    err = assert_error(await client.get(f"/__test/app-error/{name}"), status, "CUSTOM_CODE")
    assert err["message"] == "Something specific" and err["details"] == {"hint": [1, 2]}


async def test_401_responses_advertise_the_bearer_scheme_and_429_the_retry_time(client: AsyncClient) -> None:
    r = await client.get(f"{API}/auth/me")
    assert r.headers["www-authenticate"] == "Bearer"
    from app.cache.redis_cache import get_redis

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(get_settings(), "search_rate_limit_attempts", 1)
        async with client_from("10.77.0.1") as c:
            await c.get(f"{API}/search/jobs")
            limited = await c.get(f"{API}/search/jobs")
    assert_error(limited, 429, "RATE_LIMITED")
    assert limited.headers["retry-after"] == str(limited.json()["error"]["details"]["retry_after_seconds"])
    await get_redis().delete("ratelimit:search:10.77.0.1")


async def test_a_crash_in_one_request_does_not_affect_the_next(
    client: AsyncClient, boom_routes: None
) -> None:
    assert (await client.get("/__test/crash")).status_code == 500
    assert (await client.get("/health")).status_code == 200
    rec = await register_employer(client)
    assert (await client.get(f"{API}/auth/me", headers=rec["h"])).status_code == 200


async def test_no_stack_traces_when_the_app_is_driven_without_re_raising() -> None:
    from app.main import app as the_app

    async with AsyncClient(
        transport=ASGITransport(app=the_app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        r = await c.get("/definitely-missing")
        assert r.status_code == 404 and "Traceback" not in r.text
