"""Interview scheduling and feedback schemas.

Two audiences, two representations: staff get everything (internal notes, participants, feedback counters, the
application's allowed next stages); candidates get a deliberately small view that can never carry internal notes,
feedback, ratings or other people's contact data. Responses discriminate on ``audience``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import (
    ApplicationStatus,
    HireRecommendation,
    InterviewStatus,
    InterviewType,
    ParticipantRole,
)


def validate_iana_timezone(value: str) -> str:
    """Return ``value`` if it is a known IANA zone (``Europe/Berlin``), else raise ``ValueError``."""
    name = value.strip()
    try:
        ZoneInfo(name)
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError (malformed key), OSError
        raise ValueError(f"'{value}' is not a valid IANA timezone (e.g. 'Europe/Berlin')") from exc
    return name


def validate_https_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or not parts.netloc or any(c.isspace() for c in url):
        raise ValueError("meeting_url must be a valid https:// link")
    return url


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ParticipantIn(BaseModel):
    user_id: uuid.UUID
    role: ParticipantRole = Field(
        default=ParticipantRole.INTERVIEWER, description="OBSERVERs do not block a calendar slot"
    )


class _SlotFields(BaseModel):
    @field_validator("timezone", check_fields=False)
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return validate_iana_timezone(v) if v is not None else None

    @field_validator("meeting_url", check_fields=False)
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return validate_https_url(v)

    @field_validator("location", "notes", check_fields=False)
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class InterviewCreate(_SlotFields):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "application_id": "00000000-0000-0000-0000-000000000000",
                "interview_type": "TECHNICAL",
                "start_at": "2030-05-20T09:00:00",
                "end_at": "2030-05-20T10:00:00",
                "timezone": "Europe/Berlin",
                "meeting_url": "https://meet.example.com/abc-defg",
                "location": None,
                "notes": "Focus on system design.",
                "participants": [{"user_id": "00000000-0000-0000-0000-000000000001", "role": "INTERVIEWER"}],
            }
        }
    )

    application_id: uuid.UUID
    interview_type: InterviewType
    start_at: datetime = Field(
        description="Start of the interview. Timezone-aware values are converted to UTC; a naive value is read in `timezone`."
    )
    end_at: datetime = Field(description="End of the interview (after `start_at`, at most 12 hours later)")
    timezone: str = Field(
        default="UTC", max_length=64, description="IANA timezone the interview is communicated in"
    )
    location: str | None = Field(
        default=None,
        max_length=300,
        description="Physical location; at least one of location / meeting_url is required",
    )
    meeting_url: str | None = Field(default=None, max_length=500, description="https:// video-call link")
    notes: str | None = Field(
        default=None, max_length=4000, description="Internal notes — never shown to the candidate"
    )
    participants: list[ParticipantIn] = Field(
        min_length=1, max_length=15, description="At least one INTERVIEWER"
    )


class InterviewUpdate(_SlotFields):
    """Partial update. Changing ``start_at`` / ``end_at`` reschedules (status → RESCHEDULED) and notifies everyone.

    Send ``start_at`` alone to move the interview while keeping its duration. ``participants``, when present,
    replaces the participant list."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_at": "2030-05-21T09:00:00",
                "end_at": "2030-05-21T10:00:00",
                "timezone": "Europe/Berlin",
                "notes": "Moved at the candidate's request",
            }
        }
    )
    interview_type: InterviewType | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=300)
    meeting_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)
    participants: list[ParticipantIn] | None = Field(default=None, min_length=1, max_length=15)


class CancelRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"reason": "Interviewer unavailable; will be rescheduled next week"}}
    )
    reason: str = Field(
        min_length=3, max_length=500, description="Internal reason (not sent to the candidate)"
    )

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("reason must be at least 3 characters")
        return v


# --- feedback ---------------------------------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "rating": 4,
                "recommendation": "HIRE",
                "strengths": "Clear communicator, strong SQL.",
                "weaknesses": "Limited experience with message queues.",
                "notes": "Would pair well with the platform team.",
            }
        }
    )
    rating: int = Field(ge=1, le=5, description="1 (poor) … 5 (outstanding)")
    recommendation: HireRecommendation
    strengths: str | None = Field(default=None, max_length=4000)
    weaknesses: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("strengths", "weaknesses", "notes")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    rating: int
    recommendation: HireRecommendation
    strengths: str | None
    weaknesses: str | None
    notes: str | None
    submitted_at: datetime
    is_mine: bool = False


class FeedbackSummary(BaseModel):
    interview_id: uuid.UUID
    count: int
    average_rating: float | None
    recommendations: dict[HireRecommendation, int]
    items: list[FeedbackOut]


# --- read models ------------------------------------------------------------------------------------------------


class ParticipantOut(BaseModel):
    user_id: uuid.UUID
    name: str
    role: ParticipantRole
    has_submitted_feedback: bool = False


class ApplicationStageOut(BaseModel):
    id: uuid.UUID
    status: ApplicationStatus
    allowed_next_statuses: list[ApplicationStatus] = Field(
        description="Stages a recruiter may move the application to now (e.g. OFFER / REJECTED after the interview)"
    )


class StaffInterviewItem(BaseModel):
    audience: Literal["staff"] = "staff"
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_name: str
    interview_type: InterviewType
    start_at: datetime
    end_at: datetime
    timezone: str
    location: str | None
    meeting_url: str | None
    status: InterviewStatus
    participants: list[ParticipantOut]
    feedback_count: int


class StaffInterviewView(StaffInterviewItem):
    company_id: uuid.UUID
    company_name: str
    start_local: str = Field(
        description="start_at rendered in the interview's timezone (ISO 8601 with offset)"
    )
    end_local: str
    duration_minutes: int
    notes: str | None = Field(description="Internal notes")
    cancelled_reason: str | None
    created_by_id: uuid.UUID | None
    created_by_name: str | None
    my_feedback_submitted: bool
    can_submit_feedback: bool
    application: ApplicationStageOut
    created_at: datetime
    updated_at: datetime


class CandidateInterviewView(BaseModel):
    """What a candidate sees: logistics only. No notes, feedback, ratings, cancellation reasons or staff contact data."""

    audience: Literal["candidate"] = "candidate"
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    interview_type: InterviewType
    start_at: datetime
    end_at: datetime
    start_local: str
    end_local: str
    timezone: str
    duration_minutes: int
    location: str | None
    meeting_url: str | None
    status: InterviewStatus
    interviewers: list[str] = Field(description="Display names of the interviewers")
    can_confirm: bool = Field(description="True while the candidate can still confirm attendance")


InterviewDetail = Annotated[StaffInterviewView | CandidateInterviewView, Field(discriminator="audience")]
InterviewListEntry = Annotated[StaffInterviewItem | CandidateInterviewView, Field(discriminator="audience")]
