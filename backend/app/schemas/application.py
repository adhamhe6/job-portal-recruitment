from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ApplicationStatus
from app.schemas.common import ORMModel


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "00000000-0000-0000-0000-000000000000",
                "cover_letter": "I would love to join…",
            }
        }
    )
    job_id: uuid.UUID
    resume_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the candidate's primary résumé"
    )
    cover_letter: str | None = Field(default=None, max_length=8000)
    source: str = Field(default="DIRECT", pattern="^(DIRECT|RECOMMENDATION|SEARCH|REFERRAL)$")


class StatusChange(BaseModel):
    status: ApplicationStatus
    comment: str | None = Field(default=None, max_length=2000)


class WithdrawRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class NoteOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID | None
    author_name: str | None
    body: str
    created_at: datetime


class HistoryEntry(BaseModel):
    id: uuid.UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    actor_name: str | None
    comment: str | None = Field(
        description="Visible to candidates only for their own withdrawal / rejection reason"
    )
    created_at: datetime


class ApplicationListItem(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID
    company_name: str
    candidate_id: uuid.UUID
    candidate_name: str
    candidate_headline: str | None = None
    status: ApplicationStatus
    applied_at: datetime
    status_changed_at: datetime
    match_score: float | None = None
    match_band: str | None = None
    has_resume: bool = False
    next_interview_at: datetime | None = None


class ApplicationDetail(ORMModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID
    company_name: str
    candidate_id: uuid.UUID
    candidate_name: str
    status: ApplicationStatus
    cover_letter: str | None
    resume_id: uuid.UUID | None
    resume_filename: str | None = None
    source: str
    rejection_reason: str | None
    applied_at: datetime
    status_changed_at: datetime
    allowed_next_statuses: list[ApplicationStatus]
    match: dict[str, Any] | None = None
    history: list[HistoryEntry]
