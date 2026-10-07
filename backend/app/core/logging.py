"""Structured (JSON) logging with request/job correlation ids.

Every record carries the current ``request_id`` / ``job_id`` from context variables so a
single request or background job can be traced across log lines. Keys that look like
secrets are redacted defensively before serialisation.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_ctx: ContextVar[str | None] = ContextVar("job_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

_SENSITIVE_KEYS = ("password", "token", "secret", "authorization", "api_key", "cookie")
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _redact(value: Any, key: str = "") -> Any:
    if any(s in key.lower() for s in _SENSITIVE_KEYS):
        return "***"
    if isinstance(value, dict):
        return {k: _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, key) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for ctx_key, ctx in (("request_id", request_id_ctx), ("job_id", job_id_ctx)):
            val = ctx.get()
            if val:
                payload[ctx_key] = val
        uid = user_id_ctx.get()
        if uid is not None:
            payload["user_id"] = uid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _redact(value, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: _redact(v, k)
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        rid = request_id_ctx.get() or job_id_ctx.get()
        prefix = f"[{rid[:8]}] " if rid else ""
        return f"{prefix}{base}" + (f" {extras}" if extras else "")


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log is replaced by our request-logging middleware.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("sqlalchemy.engine", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
