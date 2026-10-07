from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.models import NotificationType, TaskStatus, TaskType
from app.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    is_read: bool
    read_at: datetime | None
    job_id: uuid.UUID | None
    application_id: uuid.UUID | None
    interview_id: uuid.UUID | None
    resume_id: uuid.UUID | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


class TaskOut(ORMModel):
    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    progress: int
    stage: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
