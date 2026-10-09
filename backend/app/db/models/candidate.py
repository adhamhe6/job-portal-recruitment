"""Candidate profiles and their structured sub-resources."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.enums import (
    Availability,
    CandidateSource,
    DataSource,
    EducationLevel,
    EmploymentType,
    LanguageProficiency,
    RemotePreference,
    SkillProficiency,
    SkillStatus,
    pg_enum,
)
from app.db.models.skill import Skill
from app.db.models.user import Company, User

EMBEDDING_DIM = 256


class CandidateProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "candidate_profiles"

    # Registered candidates have a user; candidates sourced via bulk résumé import (IMPORTED) do not,
    # and belong to the importing company's private talent pool.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    source: Mapped[CandidateSource] = mapped_column(
        pg_enum(CandidateSource, "candidate_source"),
        nullable=False,
        default=CandidateSource.SELF,
        server_default="SELF",
    )
    sourced_by_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # Denormalised identity (copied from the user for registered candidates; authoritative for imported ones).
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(210), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))

    headline: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    expected_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    remote_preference: Mapped[RemotePreference | None] = mapped_column(
        pg_enum(RemotePreference, "remote_preference")
    )
    employment_preference: Mapped[EmploymentType | None] = mapped_column(
        pg_enum(EmploymentType, "candidate_employment_preference")
    )
    availability: Mapped[Availability | None] = mapped_column(pg_enum(Availability, "availability"))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    github_url: Mapped[str | None] = mapped_column(String(500))
    is_searchable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # --- search & semantic index (maintained by CandidateIndexService, never by the client) -----------
    skills_text: Mapped[str | None] = mapped_column(Text)  # canonical skill names, space separated
    search_text: Mapped[str | None] = mapped_column(Text)  # summary + titles + résumé body (bounded)
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(display_name, '') || ' ' || coalesce(headline, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(skills_text, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(search_text, '')), 'C')",
            persisted=True,
        ),
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_version: Mapped[str | None] = mapped_column(String(20))
    embedding_source_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(lazy="raise")
    sourced_by_company: Mapped[Company | None] = relationship(lazy="raise")
    skills: Mapped[list[CandidateSkill]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", lazy="raise"
    )
    experiences: Mapped[list[Experience]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="Experience.start_date.desc()",
    )
    educations: Mapped[list[Education]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="Education.end_year.desc().nulls_first()",
    )
    certifications: Mapped[list[Certification]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", lazy="raise"
    )
    languages: Mapped[list[CandidateLanguage]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "years_experience IS NULL OR (years_experience >= 0 AND years_experience <= 70)",
            name="years_experience_range",
        ),
        CheckConstraint("expected_salary IS NULL OR expected_salary >= 0", name="expected_salary_positive"),
        # A profile is either a registered user's or a company-sourced one with its own identity.
        CheckConstraint(
            "(user_id IS NOT NULL AND source = 'SELF') OR (user_id IS NULL AND source = 'IMPORTED' AND sourced_by_company_id IS NOT NULL)",
            name="owner_consistent",
        ),
        Index("ix_candidate_profiles_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_candidate_profiles_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_candidate_profiles_location_trgm",
            "location",
            postgresql_using="gin",
            postgresql_ops={"location": "gin_trgm_ops"},
        ),
        Index(
            "ix_candidate_profiles_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Searchable registered candidates: the recruiter marketplace.
        Index(
            "ix_candidate_profiles_searchable",
            "years_experience",
            postgresql_where=text("is_searchable AND source = 'SELF'"),
        ),
        # Imported candidates are unique per company by contact e-mail (duplicate detection).
        Index(
            "uq_candidate_profiles_company_email",
            "sourced_by_company_id",
            func.lower(contact_email),
            unique=True,
            postgresql_where=text("source = 'IMPORTED' AND contact_email IS NOT NULL"),
        ),
    )

    @property
    def is_registered(self) -> bool:
        return self.user_id is not None


class CandidateSkill(UUIDMixin, Base):
    __tablename__ = "candidate_skills"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    proficiency: Mapped[SkillProficiency | None] = mapped_column(
        pg_enum(SkillProficiency, "skill_proficiency")
    )
    years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    source: Mapped[DataSource] = mapped_column(
        pg_enum(DataSource, "candidate_skill_source"),
        nullable=False,
        default=DataSource.USER,
        server_default="USER",
    )
    status: Mapped[SkillStatus] = mapped_column(
        pg_enum(SkillStatus, "candidate_skill_status"),
        nullable=False,
        default=SkillStatus.CONFIRMED,
        server_default="CONFIRMED",
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate: Mapped[CandidateProfile] = relationship(back_populates="skills", lazy="raise")
    skill: Mapped[Skill] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("candidate_id", "skill_id", name="uq_candidate_skills_candidate_skill"),
        CheckConstraint(
            "years_experience IS NULL OR (years_experience >= 0 AND years_experience <= 70)",
            name="years_range",
        ),
        Index("ix_candidate_skills_skill_candidate", "skill_id", "candidate_id"),
    )


class Experience(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "experiences"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[DataSource] = mapped_column(
        pg_enum(DataSource, "experience_source"),
        nullable=False,
        default=DataSource.USER,
        server_default="USER",
    )

    candidate: Mapped[CandidateProfile] = relationship(back_populates="experiences", lazy="raise")

    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("NOT is_current OR end_date IS NULL", name="current_has_no_end"),
    )


class Education(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "educations"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree_level: Mapped[EducationLevel] = mapped_column(
        pg_enum(EducationLevel, "degree_level"), nullable=False
    )
    degree: Mapped[str | None] = mapped_column(String(200))
    field_of_study: Mapped[str | None] = mapped_column(String(200))
    start_year: Mapped[int | None] = mapped_column(SmallInteger)
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[DataSource] = mapped_column(
        pg_enum(DataSource, "education_source"),
        nullable=False,
        default=DataSource.USER,
        server_default="USER",
    )

    candidate: Mapped[CandidateProfile] = relationship(back_populates="educations", lazy="raise")

    __table_args__ = (
        CheckConstraint("start_year IS NULL OR (start_year BETWEEN 1950 AND 2100)", name="start_year_range"),
        CheckConstraint("end_year IS NULL OR (end_year BETWEEN 1950 AND 2100)", name="end_year_range"),
        CheckConstraint(
            "start_year IS NULL OR end_year IS NULL OR end_year >= start_year", name="years_ordered"
        ),
    )


class Certification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "certifications"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    credential_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[DataSource] = mapped_column(
        pg_enum(DataSource, "certification_source"),
        nullable=False,
        default=DataSource.USER,
        server_default="USER",
    )

    candidate: Mapped[CandidateProfile] = relationship(back_populates="certifications", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "issued_on IS NULL OR expires_on IS NULL OR expires_on >= issued_on", name="dates_ordered"
        ),
    )


class CandidateLanguage(UUIDMixin, Base):
    __tablename__ = "candidate_languages"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(60), nullable=False)
    proficiency: Mapped[LanguageProficiency] = mapped_column(
        pg_enum(LanguageProficiency, "language_proficiency"), nullable=False
    )

    candidate: Mapped[CandidateProfile] = relationship(back_populates="languages", lazy="raise")

    __table_args__ = (
        Index("uq_candidate_languages_lang", "candidate_id", func.lower(language), unique=True),
    )
