"""Interviews, participants and structured feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.application import Application
from app.db.models.enums import (
    HireRecommendation,
    InterviewStatus,
    InterviewType,
    ParticipantRole,
    pg_enum,
)
from app.db.models.user import User

_ACTIVE = "status IN ('SCHEDULED', 'CONFIRMED', 'RESCHEDULED')"


class Interview(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "interviews"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised from the application (both immutable for an application): enables the candidate
    # exclusion constraint and company-scoped date queries without joins.
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    interview_type: Mapped[InterviewType] = mapped_column(pg_enum(InterviewType, "interview_type"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    location: Mapped[str | None] = mapped_column(String(300))
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)  # internal
    status: Mapped[InterviewStatus] = mapped_column(
        pg_enum(InterviewStatus, "interview_status"),
        nullable=False,
        default=InterviewStatus.SCHEDULED,
        server_default="SCHEDULED",
    )
    cancelled_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    during: Mapped[Any] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, end_at, '[)')", persisted=True))

    application: Mapped[Application] = relationship(lazy="raise")
    participants: Mapped[list[InterviewParticipant]] = relationship(
        back_populates="interview", cascade="all, delete-orphan", lazy="raise"
    )
    feedback: Mapped[list[InterviewFeedback]] = relationship(
        back_populates="interview", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="end_after_start"),
        CheckConstraint("end_at - start_at <= interval '12 hours'", name="max_duration"),
        # A candidate cannot be double-booked: enforced by the database, so it holds under concurrency.
        ExcludeConstraint(
            ("candidate_id", "="), ("during", "&&"), name="ex_interviews_candidate_no_overlap", where=text(_ACTIVE)
        ),
        Index("ix_interviews_company_start", "company_id", "start_at"),
        Index("ix_interviews_candidate_start", "candidate_id", "start_at"),
        Index("ix_interviews_start", "start_at"),
    )


class InterviewParticipant(UUIDMixin, Base):
    __tablename__ = "interview_participants"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ParticipantRole] = mapped_column(
        pg_enum(ParticipantRole, "participant_role"), nullable=False, default=ParticipantRole.INTERVIEWER
    )
    # Mirrors the interview's slot while it is active (kept in sync by InterviewService in the same
    # transaction) so an interviewer cannot be double-booked.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    during: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)

    interview: Mapped[Interview] = relationship(back_populates="participants", lazy="raise")
    user: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("interview_id", "user_id", name="uq_interview_participants_interview_user"),
        ExcludeConstraint(
            ("user_id", "="),
            ("during", "&&"),
            name="ex_interview_participants_user_no_overlap",
            where=text("is_active AND role = 'INTERVIEWER'"),
        ),
        Index("ix_interview_participants_user", "user_id"),
    )


class InterviewFeedback(UUIDMixin, Base):
    """Structured interviewer feedback. Internal-only: never serialised to candidates."""

    __tablename__ = "interview_feedback"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recommendation: Mapped[HireRecommendation] = mapped_column(
        pg_enum(HireRecommendation, "hire_recommendation"), nullable=False
    )
    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    interview: Mapped[Interview] = relationship(back_populates="feedback", lazy="raise")
    author: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("interview_id", "author_id", name="uq_interview_feedback_interview_author"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
    )
