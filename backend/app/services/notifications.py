"""In-app notification centre.

``stage`` writes inside the *caller's* transaction, so a notification exists if and only if the business change that
caused it was committed. A ``dedupe_key`` makes delivery idempotent (worker retries never duplicate it).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models import Notification, NotificationType, User
from app.services.common import paginate, utcnow


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stage(
        self,
        user_id: uuid.UUID,
        type_: NotificationType,
        title: str,
        message: str,
        *,
        job_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        interview_id: uuid.UUID | None = None,
        resume_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        stmt = (
            pg_insert(Notification)
            .values(
                user_id=user_id,
                type=type_,
                title=title[:200],
                message=message[:1000],
                job_id=job_id,
                application_id=application_id,
                interview_id=interview_id,
                resume_id=resume_id,
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
        )
        await self.session.execute(stmt)

    async def list(self, user: User, *, unread_only: bool, page: int, page_size: int) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc(), Notification.id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        return await paginate(self.session, stmt, page=page, page_size=page_size)

    async def unread_count(self, user: User) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
            )
            or 0
        )

    async def mark_read(self, user: User, notification_id: uuid.UUID) -> Notification:
        n = await self.session.get(Notification, notification_id)
        if n is None or n.user_id != user.id:
            raise NotFoundError("Notification not found", code="NOTIFICATION_NOT_FOUND")
        if not n.is_read:
            n.is_read, n.read_at = True, utcnow()
            await self.session.commit()
        return n

    async def mark_all_read(self, user: User) -> int:
        res = await self.session.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=utcnow())
        )
        await self.session.commit()
        return int(res.rowcount or 0)  # type: ignore[attr-defined]
