"""Cross-cutting tables: notifications, background tasks, bulk imports, audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.enums import ImportItemStatus, NotificationType, TaskStatus, TaskType, pg_enum


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(pg_enum(NotificationType, "notification_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Typed references (real foreign keys) instead of a polymorphic id: a notification can never point at a
    # resource that does not exist.
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE")
    )
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE")
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"))
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # Idempotency: the same event can be delivered twice (worker retry) without duplicating the notification.
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
        Index("ix_notifications_user_unread", "user_id", postgresql_where=text("NOT is_read")),
    )


class BackgroundTask(UUIDMixin, TimestampMixin, Base):
    """Durable state of an asynchronous operation (the queue itself is Redis/ARQ; this is the record of truth)."""

    __tablename__ = "background_tasks"

    type: Mapped[TaskType] = mapped_column(pg_enum(TaskType, "task_type"), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.PENDING, server_default="PENDING"
    )
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    stage: Mapped[str | None] = mapped_column(String(60))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        # Idempotent enqueueing: at most one active task per dedupe key.
        Index(
            "uq_background_tasks_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('PENDING', 'RUNNING')"),
        ),
        Index("ix_background_tasks_status_created", "status", text("created_at DESC")),
        Index("ix_background_tasks_creator", "created_by_id", text("created_at DESC")),
    )


class BulkImportBatch(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bulk_import_batches"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("background_tasks.id", ondelete="SET NULL")
    )
    total_files: Mapped[int] = mapped_column(Integer, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[BulkImportItem]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", lazy="raise", order_by="BulkImportItem.created_at"
    )

    __table_args__ = (CheckConstraint("total_files > 0", name="total_positive"),)


class BulkImportItem(UUIDMixin, Base):
    __tablename__ = "bulk_import_items"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bulk_import_batches.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ImportItemStatus] = mapped_column(
        pg_enum(ImportItemStatus, "import_item_status"),
        nullable=False,
        default=ImportItemStatus.PENDING,
        server_default="PENDING",
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="SET NULL")
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batch: Mapped[BulkImportBatch] = relationship(back_populates="items", lazy="raise")

    __table_args__ = (Index("ix_bulk_import_items_batch_status", "batch_id", "status"),)


class AuditEvent(UUIDMixin, Base):
    """Append-only record of security- and business-relevant actions (job published, status changed, user suspended …)."""

    __tablename__ = "audit_events"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_created", text("created_at DESC")),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_company_created", "company_id", text("created_at DESC")),
    )
