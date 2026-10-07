"""Résumés: the logical résumé, its stored document and the asynchronous processing result."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.candidate import EMBEDDING_DIM, CandidateProfile
from app.db.models.enums import ProcessingStatus, ResumeStatus, pg_enum


class Resume(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "resumes"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[ResumeStatus] = mapped_column(
        pg_enum(ResumeStatus, "resume_status"), nullable=False, default=ResumeStatus.UPLOADED, server_default="UPLOADED"
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    candidate: Mapped[CandidateProfile] = relationship(lazy="raise")
    documents: Mapped[list[ResumeDocument]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", lazy="raise", order_by="ResumeDocument.created_at.desc()"
    )
    result: Mapped[ResumeProcessingResult | None] = relationship(
        back_populates="resume", cascade="all, delete-orphan", uselist=False, lazy="raise"
    )

    __table_args__ = (
        Index("ix_resumes_candidate_created", "candidate_id", text("created_at DESC")),
        # At most one primary résumé per candidate (the one used for matching and as the default application résumé).
        Index("uq_resumes_one_primary", "candidate_id", unique=True, postgresql_where=text("is_primary")),
    )


class ResumeDocument(UUIDMixin, Base):
    """A stored file. ``storage_key`` is server-generated and opaque — never derived from the client filename."""

    __tablename__ = "resume_documents"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="documents", lazy="raise")

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_resume_documents_sha256", "sha256"),
    )


class ResumeProcessingResult(UUIDMixin, TimestampMixin, Base):
    """Output of the worker pipeline. One row per résumé (idempotent upsert on reprocessing)."""

    __tablename__ = "resume_processing_results"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        pg_enum(ProcessingStatus, "processing_status"), nullable=False, default=ProcessingStatus.PROCESSING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(String(20))

    extracted_text: Mapped[str | None] = mapped_column(Text)  # sensitive: never logged
    text_char_count: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    was_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # parser *suggestions*, not user data

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_version: Mapped[str | None] = mapped_column(String(20))

    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))  # safe, user-facing; never raw document content

    resume: Mapped[Resume] = relationship(back_populates="result", lazy="raise")
