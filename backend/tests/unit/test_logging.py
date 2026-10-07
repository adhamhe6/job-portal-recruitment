"""Structured logging: JSON shape, correlation ids and secret redaction."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import pytest

from app.core.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    job_id_ctx,
    request_id_ctx,
    user_id_ctx,
)


def _record(msg: str = "hello", level: int = logging.INFO, **extra: Any) -> logging.LogRecord:
    rec = logging.LogRecord("app.test", level, __file__, 1, msg, None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def _json(rec: logging.LogRecord) -> dict[str, Any]:
    return json.loads(JsonFormatter().format(rec))


def test_json_record_shape() -> None:
    out = _json(_record("started", logging.WARNING, port=8000))
    assert out["msg"] == "started" and out["level"] == "WARNING" and out["logger"] == "app.test" and out["port"] == 8000
    assert out["ts"].endswith("+00:00")


def test_json_record_includes_correlation_ids_only_when_set() -> None:
    assert not {"request_id", "job_id", "user_id"} & _json(_record()).keys()
    t1, t2, t3 = request_id_ctx.set("req-1"), job_id_ctx.set("job-1"), user_id_ctx.set("user-1")
    try:
        out = _json(_record())
        assert (out["request_id"], out["job_id"], out["user_id"]) == ("req-1", "job-1", "user-1")
    finally:
        request_id_ctx.reset(t1)
        job_id_ctx.reset(t2)
        user_id_ctx.reset(t3)


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "PASSWORD", "access_token", "refresh_token", "token", "client_secret", "secret_key",
     "authorization", "Authorization", "api_key", "x_api_key", "cookie", "set_cookie", "token_hash"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    out = _json(_record(**{key: "super-secret-value"}))
    assert out[key] == "***"
    assert "super-secret-value" not in json.dumps(out)


def test_nested_dicts_are_redacted() -> None:
    out = _json(_record(payload={"user": "ada", "password": "hunter2", "nested": {"Authorization": "Bearer abc", "ok": 1}}))
    assert out["payload"] == {"user": "ada", "password": "***", "nested": {"Authorization": "***", "ok": 1}}


def test_secrets_inside_lists_of_dicts_are_redacted() -> None:
    out = _json(_record(headers=[{"authorization": "Bearer abc"}, {"x": "y"}]))
    assert "Bearer abc" not in json.dumps(out)


def test_non_sensitive_values_pass_through() -> None:
    out = _json(_record(user_email="ada@example.com", count=3, status=200, path="/api/v1/jobs"))
    assert out["count"] == 3 and out["status"] == 200 and out["path"] == "/api/v1/jobs"


def test_exception_info_is_serialised() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    out = _json(rec)
    assert "ValueError: boom" in out["exc_info"]


def test_unserialisable_extra_does_not_break_logging() -> None:
    out = _json(_record(thing=object(), when=__import__("datetime").datetime(2020, 1, 1)))
    assert "object" in out["thing"] and out["when"].startswith("2020-01-01")


def test_reserved_attributes_are_not_duplicated() -> None:
    out = _json(_record("m"))
    assert not {"name", "levelno", "pathname", "args", "created"} & out.keys()


def test_text_formatter_redacts_extras_and_prefixes_request_id() -> None:
    token = request_id_ctx.set("abcdef123456")
    try:
        line = TextFormatter("%(levelname)s %(message)s").format(_record("hi", password="hunter2", plain="ok"))
    finally:
        request_id_ctx.reset(token)
    assert line.startswith("[abcdef12] INFO hi") and "hunter2" not in line and "'password': '***'" in line and "'plain': 'ok'" in line


def test_configure_logging_installs_one_handler_with_the_requested_formatter() -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("debug", json_logs=True)
        assert len(root.handlers) == 1 and isinstance(root.handlers[0].formatter, JsonFormatter) and root.level == logging.DEBUG
        configure_logging("WARNING", json_logs=False)
        assert len(root.handlers) == 1 and isinstance(root.handlers[0].formatter, TextFormatter) and root.level == logging.WARNING
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        logging.getLogger("uvicorn.access").disabled = False
