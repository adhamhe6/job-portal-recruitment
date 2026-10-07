"""Persisted candidate↔job match results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, UUIDMixin
from app.db.models.candidate import CandidateProfile
from app.db.models.job import Job


class CandidateJobMatch(UUIDMixin, Base):
    """One scored (job, candidate) pair. A row is *stale* when the stored source hashes or versions
    differ from the current ones; staleness is checked, never assumed."""

    __tablename__ = "candidate_job_matches"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_score: Mapped[float] = mapped_column(Float, nullable=False)
    raw_cosine: Mapped[float] = mapped_column(Float, nullable=False)
    required_skill_score: Mapped[float | None] = mapped_column(Float)
    preferred_skill_score: Mapped[float | None] = mapped_column(Float)
    experience_score: Mapped[float | None] = mapped_column(Float)
    education_score: Mapped[float | None] = mapped_column(Float)
    preference_score: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    matching_version: Mapped[str] = mapped_column(String(20), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False)
    job_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    job: Mapped[Job] = relationship(lazy="raise")
    candidate: Mapped[CandidateProfile] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_candidate_job_matches_job_candidate"),
        CheckConstraint("overall_score >= 0 AND overall_score <= 1", name="overall_range"),
        CheckConstraint("semantic_score >= 0 AND semantic_score <= 1", name="semantic_range"),
        Index("ix_candidate_job_matches_job_score", "job_id", text("overall_score DESC")),
        Index("ix_candidate_job_matches_candidate_score", "candidate_id", text("overall_score DESC")),
    )
