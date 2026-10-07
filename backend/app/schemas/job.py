from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobStatus,
    SkillRequirement,
    WorkplaceType,
)
from app.schemas.common import ORMModel
from app.schemas.company import CompanyPublic
from app.schemas.skill import SkillOut


class JobSkillIn(BaseModel):
    skill_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=100)
    requirement: SkillRequirement = SkillRequirement.REQUIRED
    min_years: Decimal | None = Field(default=None, ge=0, le=30, max_digits=3, decimal_places=1)

    @model_validator(mode="after")
    def _one_of(self) -> JobSkillIn:
        if not self.skill_id and not (self.name and self.name.strip()):
            raise ValueError("provide skill_id or name")
        return self


class JobSkillOut(BaseModel):
    skill: SkillOut
    requirement: SkillRequirement
    min_years: Decimal | None = None


def _clean_title(v: str | None) -> str | None:
    """Collapse whitespace; the *normalised* title must still be a real title (length is checked after trimming)."""
    if v is None:
        return None
    v = " ".join(v.split())
    if len(v) < 3:
        raise ValueError("title must be at least 3 characters long")
    return v


def _clean_description(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if len(v) < 10:
        raise ValueError("description must be at least 10 characters long")
    return v


class _JobFields(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=10, max_length=20000)
    responsibilities: str | None = Field(default=None, max_length=10000)
    qualifications: str | None = Field(default=None, max_length=10000)
    benefits: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    workplace_type: WorkplaceType = WorkplaceType.ONSITE
    salary_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_max: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_currency: str = Field(default="USD", min_length=3, max_length=3)
    min_experience_years: Decimal = Field(default=Decimal("0"), ge=0, le=70, max_digits=4, decimal_places=1)
    max_experience_years: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)
    experience_level: ExperienceLevel | None = None
    min_education_level: EducationLevel | None = None
    application_deadline: date | None = None
    hiring_manager_id: uuid.UUID | None = None

    _title = field_validator("title")(_clean_title)
    _description = field_validator("description")(_clean_description)

    @field_validator("salary_currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _ranges(self) -> _JobFields:
        if self.salary_min is not None and self.salary_max is not None and self.salary_max < self.salary_min:
            raise ValueError("salary_max must be greater than or equal to salary_min")
        if self.max_experience_years is not None and self.max_experience_years < self.min_experience_years:
            raise ValueError("max_experience_years must be greater than or equal to min_experience_years")
        return self


class JobCreate(_JobFields):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Senior Backend Engineer",
                "department": "Platform",
                "description": "Build and scale the APIs that power our recruiting product.",
                "responsibilities": "Design services, review code, mentor engineers.",
                "location": "Berlin, Germany",
                "employment_type": "FULL_TIME",
                "workplace_type": "HYBRID",
                "salary_min": 90000,
                "salary_max": 120000,
                "min_experience_years": 4,
                "skills": [
                    {"name": "Python", "requirement": "REQUIRED"},
                    {"name": "PostgreSQL", "requirement": "REQUIRED"},
                    {"name": "Kubernetes", "requirement": "PREFERRED"},
                ],
            }
        }
    )
    skills: list[JobSkillIn] = Field(default_factory=list, max_length=40)

    @field_validator("application_deadline")
    @classmethod
    def _future(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("application_deadline cannot be in the past")
        return v


class JobUpdate(BaseModel):
    """Partial update. ``skills``, when present, *replaces* the job's skill list."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, min_length=10, max_length=20000)
    responsibilities: str | None = Field(default=None, max_length=10000)
    qualifications: str | None = Field(default=None, max_length=10000)
    benefits: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType | None = None
    workplace_type: WorkplaceType | None = None
    salary_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_max: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    min_experience_years: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)
    max_experience_years: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)
    experience_level: ExperienceLevel | None = None
    min_education_level: EducationLevel | None = None
    application_deadline: date | None = None
    hiring_manager_id: uuid.UUID | None = None
    skills: list[JobSkillIn] | None = Field(default=None, max_length=40)

    _title = field_validator("title")(_clean_title)
    _description = field_validator("description")(_clean_description)

    @field_validator("salary_currency")
    @classmethod
    def _cur(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class JobTransition(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class MatchPreview(BaseModel):
    overall_score: float
    band: str


class JobBase(ORMModel):
    id: uuid.UUID
    title: str
    department: str | None
    description: str
    responsibilities: str | None
    qualifications: str | None
    benefits: str | None
    location: str | None
    employment_type: EmploymentType
    workplace_type: WorkplaceType
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str
    min_experience_years: Decimal
    max_experience_years: Decimal | None
    experience_level: ExperienceLevel | None
    min_education_level: EducationLevel | None
    application_deadline: date | None
    status: JobStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobPublic(JobBase):
    """Public job detail: only intentionally public information. No recruiter identities, no internal fields."""

    company: CompanyPublic
    skills: list[JobSkillOut]
    is_saved: bool | None = Field(default=None, description="Present for signed-in candidates")
    my_application_id: uuid.UUID | None = None
    my_application_status: str | None = None
    match: MatchPreview | None = Field(default=None, description="Present for signed-in candidates with a computed match")
    can_apply: bool | None = None
    apply_blocked_reason: str | None = None


class JobDetail(JobPublic):
    """Staff view of a job (adds ownership and counters)."""

    company_id: uuid.UUID
    created_by_id: uuid.UUID | None
    hiring_manager_id: uuid.UUID | None
    hiring_manager_name: str | None = None
    closed_at: datetime | None = None
    application_count: int = 0
    embedding_ready: bool = False
    allowed_transitions: list[JobStatus] = Field(default_factory=list)


class JobListItem(BaseModel):
    id: uuid.UUID
    title: str
    company_id: uuid.UUID
    company_name: str
    company_logo_url: str | None = None
    department: str | None
    location: str | None
    employment_type: EmploymentType
    workplace_type: WorkplaceType
    experience_level: ExperienceLevel | None
    min_experience_years: Decimal
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str
    skills: list[str] = Field(description="Required skill names (first 6)")
    status: JobStatus
    published_at: datetime | None
    application_deadline: date | None
    created_at: datetime
    updated_at: datetime
    # candidate-aware extras
    is_saved: bool | None = None
    has_applied: bool | None = None
    match_score: float | None = None
    # staff-aware extras
    application_count: int | None = None


class JobStats(BaseModel):
    job_id: uuid.UUID
    applications_total: int
    applications_by_status: dict[str, int]
    matches_computed: int
    last_matched_at: datetime | None
    extra: dict[str, Any] = Field(default_factory=dict)
