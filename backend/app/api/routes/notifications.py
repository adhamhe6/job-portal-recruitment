from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, Pagination, SessionDep
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.notification import NotificationOut, UnreadCount
from app.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"], responses=COMMON_ERRORS)


@router.get("", response_model=Page[NotificationOut], summary="My notifications (newest first)")
async def list_notifications(
    user: CurrentUser, session: SessionDep, p: Pagination, unread_only: Annotated[bool, Query()] = False
) -> Page[NotificationOut]:
    rows, total = await NotificationService(session).list(user, unread_only=unread_only, page=p.page, page_size=p.page_size)
    return Page.build([NotificationOut.model_validate(n) for n in rows], page=p.page, page_size=p.page_size, total=total)


@router.get("/unread-count", response_model=UnreadCount, summary="Number of unread notifications")
async def unread_count(user: CurrentUser, session: SessionDep) -> UnreadCount:
    return UnreadCount(unread=await NotificationService(session).unread_count(user))


@router.post("/read-all", response_model=UnreadCount, summary="Mark all as read")
async def mark_all_read(user: CurrentUser, session: SessionDep) -> UnreadCount:
    await NotificationService(session).mark_all_read(user)
    return UnreadCount(unread=0)


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Mark one notification as read")
async def mark_read(notification_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> NotificationOut:
    return NotificationOut.model_validate(await NotificationService(session).mark_read(user, notification_id))
