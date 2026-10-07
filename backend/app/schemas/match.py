from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import Availability
from app.schemas.job import JobListItem


class ScoreBreakdown(BaseModel):
    """Component scores in [0, 1]; ``null`` = not applicable to this job/candidate."""

    semantic: float
    required_skills: float | None
    preferred_skills: float | None
    experience: float | None
    education: float | None
    preferences: float | None


class MatchedCandidate(BaseModel):
    candidate_id: uuid.UUID
    display_name: str
    headline: str | None
    location: str | None
    years_experience: Decimal | None
    availability: Availability | None
    overall_score: float = Field(description="0..1 ranking/relevance score — not a probability of being hired")
    overall_percent: int
    band: str
    breakdown: ScoreBreakdown
    summary: str
    strong_skills: list[str]
    related_skills: list[dict[str, str]]
    missing_required: list[str]
    missing_preferred: list[str]
    experience_text: str
    semantic_band: str
    has_applied: bool
    application_id: uuid.UUID | None = None
    application_status: str | None = None
    access: str
    stale: bool = False
    generated_at: datetime


class RankedCandidatesMeta(BaseModel):
    job_id: uuid.UUID
    total_scored: int
    last_generated_at: datetime | None
    stale_rows: int = 0
    embedding_model: str
    matching_version: str
    computing_task_id: uuid.UUID | None = None


class MatchDetail(BaseModel):
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_name: str
    overall_score: float
    overall_percent: int
    band: str
    breakdown: ScoreBreakdown
    explanation: dict[str, Any]
    embedding_model: str
    embedding_version: str
    matching_version: str
    generated_at: datetime


class CandidateFacingMatch(BaseModel):
    """Explanation shown to a candidate for a job — job-relevant facts only, no internal weights or raw cosines."""

    overall_percent: int
    band: str
    summary: str
    matched_skills: list[str]
    related_skills: list[dict[str, str]]
    missing_required: list[str]
    missing_preferred: list[str]
    experience_text: str
    experience_status: str
    semantic_band: str
    generated_at: datetime


class RecommendedJob(BaseModel):
    job: JobListItem
    match: CandidateFacingMatch


class RecommendationsMeta(BaseModel):
    last_generated_at: datetime | None
    computing: bool = False
    task_id: uuid.UUID | None = None
    profile_ready: bool = True
    hint: str | None = None
