"""Shared schema primitives: pagination envelope, error body, base classes."""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

T = TypeVar("T")

_PHONE_RE = re.compile(r"^[+()\d][\d\s().\-]{5,30}$")


def validate_phone(value: str | None) -> str | None:
    """Blank -> None; otherwise a plausible phone number (digits, spaces and ``+ ( ) . -``)."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not _PHONE_RE.match(value):
        raise ValueError("Enter a valid phone number")
    return value


def validate_http_url(value: str | None) -> str | None:
    """Blank -> None; otherwise a well-formed absolute http(s) URL (rejects ``javascript:``, empty hosts, spaces)."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 500 or any(ch.isspace() for ch in value):
        raise ValueError("must be a valid http(s) URL")
    try:
        HttpUrl(value)
    except ValidationError:
        raise ValueError("must be a valid http(s) URL") from None
    return value


class ORMModel(BaseModel):
    """Response models are built from ORM rows; they are never the ORM rows themselves."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


class Page(BaseModel, Generic[T]):
    """Consistent pagination envelope used by every list endpoint."""

    items: list[T]
    page: int = Field(ge=1, description="1-based page number")
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0, description="Total rows matching the filters")
    pages: int = Field(ge=0, description="Total number of pages")

    @classmethod
    def build(cls, items: list[Any], *, page: int, page_size: int, total: int) -> Page[Any]:
        return cls(items=items, page=page, page_size=page_size, total=total, pages=math.ceil(total / page_size) if total else 0)


class PageParams:
    """FastAPI dependency: ``?page=1&page_size=20`` (page_size capped at 100)."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=100_000, description="1-based page number")] = 1,
        page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class ErrorBody(BaseModel):
    code: str = Field(examples=["APPLICATION_ALREADY_EXISTS"])
    message: str = Field(examples=["You have already applied to this job."])
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx response has this shape."""

    error: ErrorBody


class MessageResponse(BaseModel):
    message: str


class TaskRef(BaseModel):
    """Returned when work was queued: poll ``GET /api/v1/tasks/{id}``."""

    task_id: str
    status: str = "PENDING"


COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing, invalid or expired access token"},
    403: {"model": ErrorResponse, "description": "Authenticated but not allowed"},
    404: {"model": ErrorResponse, "description": "Resource not found (or not visible to the caller)"},
    422: {"model": ErrorResponse, "description": "Validation or business-rule failure"},
}
