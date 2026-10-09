"""Applications, their audit trail and internal recruiter notes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.candidate import CandidateProfile
from app.db.models.enums import ApplicationStatus, pg_enum
from app.db.models.job import Job
from app.db.models.resume import Resume
from app.db.models.user import User


class Application(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="RESTRICT")
    )
    cover_letter: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ApplicationStatus] = mapped_column(
        pg_enum(ApplicationStatus, "application_status"),
        nullable=False,
        default=ApplicationStatus.APPLIED,
        server_default="APPLIED",
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="DIRECT", server_default="DIRECT")
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500))

    job: Mapped[Job] = relationship(lazy="raise")
    candidate: Mapped[CandidateProfile] = relationship(lazy="raise")
    resume: Mapped[Resume | None] = relationship(lazy="raise")
    history: Mapped[list[ApplicationStatusHistory]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="ApplicationStatusHistory.created_at",
    )

    __table_args__ = (
        # One live application per candidate per job; a candidate may re-apply only after withdrawing.
        Index(
            "uq_applications_live_per_candidate_job",
            "job_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("status <> 'WITHDRAWN'"),
        ),
        Index("ix_applications_job_status", "job_id", "status"),
        Index("ix_applications_job_applied", "job_id", text("applied_at DESC")),
        Index("ix_applications_candidate_applied", "candidate_id", text("applied_at DESC")),
        Index("ix_applications_applied_at", text("applied_at DESC")),
        Index("ix_applications_resume", "resume_id", postgresql_where=text("resume_id IS NOT NULL")),
    )


class ApplicationStatusHistory(UUIDMixin, Base):
    __tablename__ = "application_status_history"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        pg_enum(ApplicationStatus, "history_from_status")
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(
        pg_enum(ApplicationStatus, "history_to_status"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application] = relationship(back_populates="history", lazy="raise")
    actor: Mapped[User | None] = relationship(lazy="raise")

    __table_args__ = (Index("ix_application_history_app_created", "application_id", "created_at"),)


class ApplicationNote(UUIDMixin, Base):
    """Internal notes — visible to the hiring company's staff only, never to candidates."""

    __tablename__ = "application_notes"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    author: Mapped[User | None] = relationship(lazy="raise")

    __table_args__ = (Index("ix_application_notes_app_created", "application_id", "created_at"),)
