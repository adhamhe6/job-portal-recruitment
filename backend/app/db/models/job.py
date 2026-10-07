"""Job postings, required/preferred skills and saved jobs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, TimestampMixin, UUIDMixin
from app.db.models.candidate import EMBEDDING_DIM, CandidateProfile
from app.db.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobStatus,
    SkillRequirement,
    WorkplaceType,
    pg_enum,
)
from app.db.models.skill import Skill
from app.db.models.user import Company, User


class Job(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibilities: Mapped[str | None] = mapped_column(Text)
    qualifications: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[EmploymentType] = mapped_column(
        pg_enum(EmploymentType, "job_employment_type"), nullable=False, default=EmploymentType.FULL_TIME
    )
    workplace_type: Mapped[WorkplaceType] = mapped_column(
        pg_enum(WorkplaceType, "job_workplace_type"), nullable=False, default=WorkplaceType.ONSITE
    )
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    min_experience_years: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0, server_default="0")
    max_experience_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    experience_level: Mapped[ExperienceLevel | None] = mapped_column(pg_enum(ExperienceLevel, "experience_level"))
    min_education_level: Mapped[EducationLevel | None] = mapped_column(
        pg_enum(EducationLevel, "job_min_education_level")
    )
    application_deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.DRAFT, server_default="DRAFT"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- search & semantic index ---------------------------------------------------------------
    skills_text: Mapped[str | None] = mapped_column(Text)  # canonical names of required+preferred skills
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(skills_text, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(description, '') || ' ' || coalesce(responsibilities, '')), 'C') || "
            "setweight(to_tsvector('english', coalesce(department, '') || ' ' || coalesce(location, '')), 'D')",
            persisted=True,
        ),
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_version: Mapped[str | None] = mapped_column(String(20))
    embedding_source_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(lazy="raise")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="raise")
    hiring_manager: Mapped[User | None] = relationship(foreign_keys=[hiring_manager_id], lazy="raise")
    skills: Mapped[list[JobSkill]] = relationship(back_populates="job", cascade="all, delete-orphan", lazy="raise")

    __table_args__ = (
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="salary_min_positive"),
        CheckConstraint("salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min", name="salary_range_ordered"),
        CheckConstraint("min_experience_years >= 0 AND min_experience_years <= 70", name="min_experience_range"),
        CheckConstraint(
            "max_experience_years IS NULL OR max_experience_years >= min_experience_years", name="experience_range_ordered"
        ),
        CheckConstraint(
            "status = 'DRAFT' OR published_at IS NOT NULL OR status = 'ARCHIVED'", name="published_at_set"
        ),
        # Public search: published jobs, newest first.
        Index("ix_jobs_published", text("published_at DESC"), postgresql_where=text("status = 'PUBLISHED'")),
        Index("ix_jobs_company_status", "company_id", "status", text("updated_at DESC")),
        Index("ix_jobs_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_jobs_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_jobs_location_trgm", "location", postgresql_using="gin", postgresql_ops={"location": "gin_trgm_ops"}),
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Duplicate-posting guard: one *live* posting per (company, title, location, workplace type).
        Index(
            "uq_jobs_active_duplicate",
            "company_id",
            func.lower(title),
            func.lower(func.coalesce(location, "")),
            "workplace_type",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'PUBLISHED', 'PAUSED')"),
        ),
    )


class JobSkill(UUIDMixin, Base):
    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )
    requirement: Mapped[SkillRequirement] = mapped_column(
        pg_enum(SkillRequirement, "job_skill_requirement"), nullable=False, default=SkillRequirement.REQUIRED
    )
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))

    job: Mapped[Job] = relationship(back_populates="skills", lazy="raise")
    skill: Mapped[Skill] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("job_id", "skill_id", name="uq_job_skills_job_skill"),
        CheckConstraint("min_years IS NULL OR min_years >= 0", name="min_years_positive"),
        Index("ix_job_skills_skill_job", "skill_id", "job_id"),
    )


class SavedJob(Base):
    __tablename__ = "saved_jobs"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job: Mapped[Job] = relationship(lazy="raise")
    candidate: Mapped[CandidateProfile] = relationship(lazy="raise")

    __table_args__ = (Index("ix_saved_jobs_candidate_created", "candidate_id", text("created_at DESC")),)
