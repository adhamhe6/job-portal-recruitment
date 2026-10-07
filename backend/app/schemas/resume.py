"""Résumé API schemas: upload / status, extracted-data review (suggestions), apply, and bulk import.

Storage keys, file-system paths and the raw extracted text never appear in these models.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import EducationLevel, ImportItemStatus, LanguageProficiency, SkillStatus
from app.schemas.common import Page

# --- résumé + processing status ------------------------------------------------------------------------------------


class ProcessingOut(BaseModel):
    """Live status of the (latest) processing run; combines the processing result row and the background task."""

    task_id: uuid.UUID | None = Field(
        default=None, description="Latest background task; poll `GET /tasks/{id}`"
    )
    task_status: str | None = Field(default=None, description="PENDING | RUNNING | COMPLETED | FAILED")
    stage: str | None = Field(default=None, description="Current pipeline stage while the task runs")
    progress: int | None = Field(default=None, ge=0, le=100)
    attempts: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    parser_version: str | None = None
    page_count: int | None = None
    text_char_count: int | None = None
    was_truncated: bool = False
    has_embedding: bool = False
    embedding_model: str | None = None
    embedding_version: str | None = None
    error_code: str | None = Field(
        default=None, description="Stable machine-readable failure code, e.g. NO_TEXT_EXTRACTED"
    )
    error_message: str | None = Field(
        default=None, description="Safe, user-facing explanation (never document content)"
    )


class ResumeOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "5b0f4c1e-0d0a-4c6a-9d77-6a1f3f6f9a11",
                    "candidate_id": "0c7d5a8e-3a2b-4f11-8a53-2c9d1f9a7b10",
                    "status": "PROCESSED",
                    "is_primary": True,
                    "original_filename": "jane-doe-cv.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 48211,
                    "sha256": "9f2c…",
                    "created_at": "2026-10-07T12:00:00Z",
                    "updated_at": "2026-10-07T12:00:04Z",
                    "task_id": "7a1d2d0e-1f2b-4c33-b1f0-0d3f5f6a7b88",
                    "processing": {
                        "task_status": "COMPLETED",
                        "progress": 100,
                        "parser_version": "v1",
                        "has_embedding": True,
                    },
                }
            ]
        }
    )

    id: uuid.UUID
    candidate_id: uuid.UUID
    status: Literal["UPLOADED", "PROCESSING", "PROCESSED", "FAILED"]
    is_primary: bool
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    updated_at: datetime
    task_id: uuid.UUID | None = Field(default=None, description="Latest processing task, if one was queued")
    processing: ProcessingOut


class ResumeUploadOut(ResumeOut):
    """Response of ``POST /resumes``: the résumé plus what happened to the processing request."""

    message: str | None = Field(
        default=None,
        description="Set when processing could not be queued (the upload is kept; use `POST /resumes/{id}/process`)",
    )
    duplicate: bool = Field(
        default=False,
        description="True when this exact file was uploaded before and the existing résumé is returned",
    )


# --- extracted data (suggestions) --------------------------------------------------------------------------------------


class ExtractedContact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    location: str | None = None


class ExtractedSkill(BaseModel):
    index: int = Field(description="Stable position of this suggestion; used by PATCH / apply")
    name: str
    skill_id: uuid.UUID | None = Field(
        default=None,
        description="Taxonomy skill this resolves to; null = not in the taxonomy (cannot be applied)",
    )
    confidence: float = Field(ge=0, le=1)
    listed: bool = Field(
        description="Found in a skills list (higher confidence) rather than only mentioned in prose"
    )
    already_on_profile: bool = Field(description="A confirmed skill with this name is already on the profile")
    status: SkillStatus | None = Field(
        default=None, description="Status of the profile skill row, if any (SUGGESTED / CONFIRMED / REJECTED)"
    )
    corrected: bool = False


class ExtractedExperience(BaseModel):
    index: int
    title: str | None = None
    company: str | None = None
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None
    confidence: float = Field(ge=0, le=1)
    already_on_profile: bool = False
    corrected: bool = False
    missing_for_apply: list[str] = Field(
        default_factory=list,
        description="Required fields still empty; correct them via PATCH before applying",
    )


class ExtractedEducation(BaseModel):
    index: int
    institution: str | None = None
    degree: str | None = None
    degree_level: EducationLevel | None = None
    field_of_study: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    confidence: float = Field(ge=0, le=1)
    already_on_profile: bool = False
    corrected: bool = False
    missing_for_apply: list[str] = Field(default_factory=list)


class ExtractedCertification(BaseModel):
    index: int
    name: str
    issuer: str | None = None
    issued_on: date | None = None
    issued_year: int | None = None
    confidence: float = Field(ge=0, le=1)
    already_on_profile: bool = False
    corrected: bool = False


class ExtractedLanguage(BaseModel):
    index: int
    language: str
    proficiency: LanguageProficiency | None = None
    confidence: float = Field(ge=0, le=1)
    already_on_profile: bool = False
    corrected: bool = False
    missing_for_apply: list[str] = Field(default_factory=list)


class ExtractedResume(BaseModel):
    """Everything the parser suggests for the profile, with confidence scores. Nothing here is applied automatically
    except skills (as unconfirmed suggestions); raw text is never returned."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "resume_id": "5b0f4c1e-0d0a-4c6a-9d77-6a1f3f6f9a11",
                    "candidate_id": "0c7d5a8e-3a2b-4f11-8a53-2c9d1f9a7b10",
                    "parser_version": "v1",
                    "has_corrections": False,
                    "contact": {
                        "name": "Jane Doe",
                        "email": "jane@example.com",
                        "phone": "+49 151 2345 6789",
                        "location": "Berlin, Germany",
                    },
                    "headline": "Senior Backend Engineer",
                    "summary": "Backend engineer with 8+ years of experience…",
                    "years_of_experience": 7.8,
                    "years_basis": "employment_history",
                    "skills": [
                        {
                            "index": 0,
                            "name": "Python",
                            "skill_id": "16a72775-41c8-441d-a38f-b14383e768e8",
                            "confidence": 0.95,
                            "listed": True,
                            "already_on_profile": False,
                            "status": "SUGGESTED",
                            "corrected": False,
                        }
                    ],
                    "experiences": [
                        {
                            "index": 0,
                            "title": "Senior Backend Engineer",
                            "company": "Acme Corp",
                            "start_date": "2020-01-01",
                            "end_date": None,
                            "is_current": True,
                            "confidence": 0.9,
                            "already_on_profile": False,
                            "missing_for_apply": [],
                        }
                    ],
                    "educations": [],
                    "certifications": [],
                    "languages": [],
                    "sections_detected": ["summary", "skills", "experience"],
                    "warnings": [],
                }
            ]
        }
    )

    resume_id: uuid.UUID
    candidate_id: uuid.UUID
    parser_version: str
    has_corrections: bool
    contact: ExtractedContact
    headline: str | None = None
    summary: str | None = None
    years_of_experience: float | None = Field(
        default=None, description="Total years: the union of dated jobs, or an explicit claim in the résumé"
    )
    years_basis: str | None = Field(
        default=None,
        description="employment_history (union of dated jobs) | stated (explicit claim) | corrected",
    )
    skills: list[ExtractedSkill]
    experiences: list[ExtractedExperience]
    educations: list[ExtractedEducation]
    certifications: list[ExtractedCertification]
    languages: list[ExtractedLanguage]
    sections_detected: list[str]
    warnings: list[str]


# --- PATCH /extracted --------------------------------------------------------------------------------------------------


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: Annotated[int, Field(ge=0, description="`index` of the suggestion, as returned by GET /extracted")]
    remove: bool = Field(
        default=False, description="Drop this suggestion (it will not be offered or applied)"
    )


class SkillPatch(_Item):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Correct the skill name (re-resolved against the taxonomy)",
    )


class ExperiencePatch(_Item):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _dates(self) -> ExperiencePatch:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class EducationPatch(_Item):
    institution: str | None = Field(default=None, min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    degree_level: EducationLevel | None = None
    field_of_study: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)


class CertificationPatch(_Item):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: date | None = None


class LanguagePatch(_Item):
    language: str | None = Field(default=None, min_length=2, max_length=60)
    proficiency: LanguageProficiency | None = None


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    linkedin_url: str | None = Field(default=None, max_length=500)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)

    @field_validator("linkedin_url", "github_url", "portfolio_url")
    @classmethod
    def _http(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("http://", "https://")) or " " in v:
            raise ValueError("must be a valid http(s) URL")
        return v


class ExtractedPatch(BaseModel):
    """Correct or remove individual suggestions. Only the fields you send change (``null`` clears a scalar). The raw
    extracted text is never modified; corrected items are flagged ``corrected``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "summary": "Backend engineer focused on reliable APIs.",
                    "skills": [{"index": 3, "remove": True}, {"index": 4, "name": "PostgreSQL"}],
                    "experiences": [
                        {"index": 0, "start_date": "2020-01-01", "title": "Senior Backend Engineer"}
                    ],
                }
            ]
        },
    )
    contact: ContactPatch | None = None
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)
    years_of_experience: float | None = Field(default=None, ge=0, le=70)
    skills: list[SkillPatch] = Field(default_factory=list, max_length=200)
    experiences: list[ExperiencePatch] = Field(default_factory=list, max_length=100)
    educations: list[EducationPatch] = Field(default_factory=list, max_length=100)
    certifications: list[CertificationPatch] = Field(default_factory=list, max_length=100)
    languages: list[LanguagePatch] = Field(default_factory=list, max_length=100)


# --- POST /extracted/apply ---------------------------------------------------------------------------------------------


Selection = Annotated[list[int] | Literal["all"], Field(description="Suggestion indices to copy, or `all`")]
_PROFILE_FIELDS = (
    "summary",
    "headline",
    "location",
    "years_experience",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "phone",
)
ProfileField = Literal[
    "summary",
    "headline",
    "location",
    "years_experience",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "phone",
]


class ApplyRequest(BaseModel):
    """Choose what to copy from the suggestions into the structured profile. Existing user-provided values are never
    replaced silently: scalar profile fields are only filled when empty unless that field is listed in ``overwrite``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "skills": "all",
                    "experiences": [0, 1],
                    "educations": [0],
                    "certifications": [],
                    "languages": [0, 1],
                    "fields": ["summary", "headline", "location", "years_experience"],
                    "overwrite": [],
                }
            ]
        },
    )
    skills: Selection = Field(default_factory=list)
    experiences: Selection = Field(default_factory=list)
    educations: Selection = Field(default_factory=list)
    certifications: Selection = Field(default_factory=list)
    languages: Selection = Field(default_factory=list)
    fields: list[ProfileField] = Field(
        default_factory=list, description="Profile fields to fill from the suggestions"
    )
    overwrite: list[ProfileField] = Field(
        default_factory=list,
        description="Fields (subset of `fields`) that may replace an existing non-empty value",
    )

    @model_validator(mode="before")
    @classmethod
    def _shorthands(cls, data: Any) -> Any:
        """Accept the obvious shorthands: ``"skills": true`` (= all), ``"summary": true`` (= fields: [summary]) and
        ``"overwrite": true`` / ``{"summary": true}`` (= overwrite every / the listed selected fields)."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        for section in ("skills", "experiences", "educations", "certifications", "languages"):
            if d.get(section) is True:
                d[section] = "all"
            elif d.get(section) in (False, None):
                d.pop(section, None)
        fields = [str(f) for f in (d.get("fields") or [])]
        for name in _PROFILE_FIELDS:
            if name in d and d.pop(name) is True and name not in fields:
                fields.append(name)
        d["fields"] = fields
        overwrite = d.get("overwrite")
        if overwrite is True:
            d["overwrite"] = list(fields)
        elif isinstance(overwrite, dict):
            d["overwrite"] = [k for k, v in overwrite.items() if v is True]
        elif overwrite in (False, None):
            d["overwrite"] = []
        return d

    @model_validator(mode="after")
    def _overwrite_subset(self) -> ApplyRequest:
        extra = set(self.overwrite) - set(self.fields)
        if extra:
            raise ValueError(f"overwrite lists fields that are not selected in `fields`: {sorted(extra)}")
        return self


class SkippedItem(BaseModel):
    section: str
    index: int | None = None
    reason: str = Field(
        description="ALREADY_ON_PROFILE | NOT_FOUND | REMOVED | UNKNOWN_SKILL | MISSING_* | INVALID_* | FIELD_NOT_EMPTY | NO_SUGGESTION"
    )


class ApplyResult(BaseModel):
    applied: dict[str, int] = Field(description="Rows created / confirmed per section")
    fields_applied: list[str]
    skipped: list[SkippedItem]


# --- bulk import ----------------------------------------------------------------------------------------------------------


class RejectedFile(BaseModel):
    filename: str
    reason: str
    code: str | None = Field(
        default=None,
        description="Machine-readable reason, e.g. UNSUPPORTED_MEDIA_TYPE, PAYLOAD_TOO_LARGE, EMPTY_FILE",
    )


class BulkImportAccepted(BaseModel):
    batch_id: uuid.UUID
    task_id: uuid.UUID | None = Field(
        default=None,
        description="null when the queue was unavailable; retry with `POST /resumes/bulk-imports/{id}/process`",
    )
    accepted: int
    rejected: list[RejectedFile]
    message: str | None = None


class BulkImportCounts(BaseModel):
    pending: int = 0
    created: int = 0
    duplicate: int = 0
    failed: int = 0


class BulkImportItemOut(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    status: ImportItemStatus
    candidate_id: uuid.UUID | None = None
    resume_id: uuid.UUID | None = None
    error_code: str | None = None
    error_message: str | None = None


class BulkImportBatchOut(BaseModel):
    id: uuid.UUID
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    total_files: int
    counts: BulkImportCounts
    task_id: uuid.UUID | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    finished_at: datetime | None = None


class BulkImportBatchDetail(BulkImportBatchOut):
    items: list[BulkImportItemOut]


BulkImportPage = Page[BulkImportBatchOut]

_ = Any
