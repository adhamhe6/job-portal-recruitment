"""Helpers shared by services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(UTC)


async def paginate(
    session: AsyncSession, stmt: Select[Any], *, page: int, page_size: int, scalars: bool = True
) -> tuple[list[Any], int]:
    """Run ``stmt`` with LIMIT/OFFSET plus a COUNT over the same filters. Returns ``(rows, total)``."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await session.execute(count_stmt)).scalar_one())
    if total == 0 or (page - 1) * page_size >= total:
        return [], total
    result = await session.execute(stmt.limit(page_size).offset((page - 1) * page_size))
    rows = list(result.scalars().all()) if scalars else list(result.all())
    return rows, total


def record_audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Stage an audit event in the caller's transaction (committed together with the business change)."""
    session.add(
        AuditEvent(
            actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, company_id=company_id, meta=meta
        )
    )


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards in user input."""
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
