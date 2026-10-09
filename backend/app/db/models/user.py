"""Identity & tenancy: companies, users, recruiter profiles, refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import Role
from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.enums import CompanySize, CompanyStatus, UserStatus, pg_enum


class Company(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200))
    size: Mapped[CompanySize | None] = mapped_column(pg_enum(CompanySize, "company_size"))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[CompanyStatus] = mapped_column(
        pg_enum(CompanyStatus, "company_status"),
        nullable=False,
        default=CompanyStatus.ACTIVE,
        server_default="ACTIVE",
    )

    __table_args__ = (Index("uq_companies_name_lower", func.lower(name), unique=True),)


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[Role] = mapped_column(pg_enum(Role, "user_role"), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), nullable=False, default=UserStatus.ACTIVE, server_default="ACTIVE"
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company | None] = relationship(lazy="raise")
    recruiter_profile: Mapped[RecruiterProfile | None] = relationship(
        back_populates="user", uselist=False, lazy="raise"
    )

    __table_args__ = (
        Index("uq_users_email_lower", func.lower(email), unique=True),
        # Company membership is valid: recruiters and hiring managers always belong to a company.
        CheckConstraint(
            "role NOT IN ('RECRUITER', 'HIRING_MANAGER') OR company_id IS NOT NULL", name="staff_company"
        ),
        CheckConstraint("role <> 'CANDIDATE' OR company_id IS NULL", name="candidate_no_company"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class RecruiterProfile(TimestampMixin, Base):
    """Staff-specific attributes (recruiters and hiring managers)."""

    __tablename__ = "recruiter_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    job_title: Mapped[str | None] = mapped_column(String(150))
    department: Mapped[str | None] = mapped_column(String(100))
    is_company_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    user: Mapped[User] = relationship(back_populates="recruiter_profile", lazy="raise")


class RefreshToken(UUIDMixin, Base):
    """Opaque rotating refresh tokens, stored as SHA-256. ``family_id`` links a rotation chain so a reused
    (already-rotated) token revokes the whole chain."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
