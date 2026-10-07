from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.models import (
    Availability,
    CandidateSource,
    DataSource,
    EducationLevel,
    EmploymentType,
    LanguageProficiency,
    RemotePreference,
    SkillProficiency,
    SkillStatus,
)
from app.schemas.common import ORMModel
from app.schemas.skill import SkillOut


def _http_url(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    if not (v.startswith("http://") or v.startswith("https://")) or " " in v or len(v) > 500:
        raise ValueError("must be a valid http(s) URL")
    return v


class ProfileUpdate(BaseModel):
    """Partial update: every field optional; omitted fields are untouched, ``null`` clears."""

    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    years_experience: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)
    expected_salary: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    remote_preference: RemotePreference | None = None
    employment_preference: EmploymentType | None = None
    availability: Availability | None = None
    portfolio_url: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    is_searchable: bool | None = None

    _urls = field_validator("portfolio_url", "linkedin_url", "github_url")(_http_url)

    @field_validator("salary_currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class ExperienceIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _check(self) -> ExperienceIn:
        if self.start_date > date.today():
            raise ValueError("start_date cannot be in the future")
        if self.is_current:
            self.end_date = None
        elif self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class ExperienceOut(ORMModel):
    id: uuid.UUID
    title: str
    company_name: str
    location: str | None
    start_date: date
    end_date: date | None
    is_current: bool
    description: str | None
    source: DataSource


class EducationIn(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    degree_level: EducationLevel
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)

    @model_validator(mode="after")
    def _check(self) -> EducationIn:
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class EducationOut(ORMModel):
    id: uuid.UUID
    institution: str
    degree_level: EducationLevel
    degree: str | None
    field_of_study: str | None
    start_year: int | None
    end_year: int | None
    source: DataSource


class CertificationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: date | None = None
    expires_on: date | None = None
    credential_url: str | None = None

    _url = field_validator("credential_url")(_http_url)

    @model_validator(mode="after")
    def _check(self) -> CertificationIn:
        if self.issued_on and self.expires_on and self.expires_on < self.issued_on:
            raise ValueError("expires_on must not be before issued_on")
        return self


class CertificationOut(ORMModel):
    id: uuid.UUID
    name: str
    issuer: str | None
    issued_on: date | None
    expires_on: date | None
    credential_url: str | None
    source: DataSource


class LanguageIn(BaseModel):
    language: str = Field(min_length=2, max_length=60)
    proficiency: LanguageProficiency


class LanguageOut(ORMModel):
    id: uuid.UUID
    language: str
    proficiency: LanguageProficiency


class CandidateSkillIn(BaseModel):
    """Reference an existing skill by id, or by name (resolved through aliases; unknown names create an unverified skill)."""

    skill_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=100)
    proficiency: SkillProficiency | None = None
    years_experience: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)

    @model_validator(mode="after")
    def _one_of(self) -> CandidateSkillIn:
        if not self.skill_id and not (self.name and self.name.strip()):
            raise ValueError("provide skill_id or name")
        return self


class CandidateSkillUpdate(BaseModel):
    proficiency: SkillProficiency | None = None
    years_experience: Decimal | None = Field(default=None, ge=0, le=70, max_digits=4, decimal_places=1)
    status: SkillStatus | None = Field(default=None, description="CONFIRMED to accept a suggested skill, REJECTED to dismiss it")


class CandidateSkillOut(BaseModel):
    id: uuid.UUID
    skill: SkillOut
    proficiency: SkillProficiency | None
    years_experience: Decimal | None
    source: DataSource
    status: SkillStatus
    confidence: float | None = None


class CompletionItem(BaseModel):
    key: str
    label: str
    weight: int
    done: bool


class ProfileCompletion(BaseModel):
    percent: int
    items: list[CompletionItem]
    missing: list[str]


class ResumeBrief(ORMModel):
    id: uuid.UUID
    status: str
    is_primary: bool
    original_filename: str | None = None
    created_at: datetime


class CandidateProfileOut(BaseModel):
    """The candidate's own, complete profile."""

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    headline: str | None
    summary: str | None
    location: str | None
    years_experience: Decimal | None
    expected_salary: Decimal | None
    salary_currency: str
    remote_preference: RemotePreference | None
    employment_preference: EmploymentType | None
    availability: Availability | None
    portfolio_url: str | None
    linkedin_url: str | None
    github_url: str | None
    is_searchable: bool
    skills: list[CandidateSkillOut]
    experiences: list[ExperienceOut]
    educations: list[EducationOut]
    certifications: list[CertificationOut]
    languages: list[LanguageOut]
    completion: ProfileCompletion
    primary_resume: ResumeBrief | None = None
    updated_at: datetime


class ApplicationBrief(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    status: str
    applied_at: datetime


class CandidateView(BaseModel):
    """What staff see. ``access`` says how much was released (PROFILE = marketplace view, FULL = applicant/sourced)."""

    id: uuid.UUID
    display_name: str
    source: CandidateSource
    access: str
    headline: str | None
    summary: str | None
    location: str | None
    years_experience: Decimal | None
    expected_salary: Decimal | None
    salary_currency: str
    remote_preference: RemotePreference | None
    employment_preference: EmploymentType | None
    availability: Availability | None
    portfolio_url: str | None
    linkedin_url: str | None
    github_url: str | None
    email: str | None = Field(default=None, description="Only when access = FULL")
    phone: str | None = Field(default=None, description="Only when access = FULL")
    skills: list[CandidateSkillOut]
    experiences: list[ExperienceOut]
    educations: list[EducationOut]
    certifications: list[CertificationOut]
    languages: list[LanguageOut]
    resumes: list[ResumeBrief] = Field(default_factory=list, description="Only when access = FULL")
    applications: list[ApplicationBrief] = Field(default_factory=list, description="Applications to the caller's company")
    updated_at: datetime
    match: dict[str, Any] | None = Field(default=None, description="Present when ?job_id= is supplied")


class CandidateListItem(BaseModel):
    id: uuid.UUID
    display_name: str
    headline: str | None
    location: str | None
    years_experience: Decimal | None
    availability: Availability | None
    remote_preference: RemotePreference | None
    source: CandidateSource
    access: str
    top_skills: list[str]
    skill_matches: list[str] = Field(default_factory=list, description="Requested skills this candidate has")
    match_score: float | None = Field(default=None, description="0..1, present when job_id was supplied")
    match_band: str | None = None
    has_applied: bool = False
    updated_at: datetime
