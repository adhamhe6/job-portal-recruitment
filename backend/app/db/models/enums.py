"""Domain enums. Persisted as VARCHAR + CHECK constraint (not native PG enums) so values can evolve via plain migrations."""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Column type: VARCHAR with a named CHECK constraint listing the allowed values."""
    values = [m.value for m in enum_cls]
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(len(v) for v in values),
        values_callable=lambda e: [m.value for m in e],
    )


class UserStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompanyStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompanySize(enum.StrEnum):
    S_1_10 = "1-10"
    S_11_50 = "11-50"
    S_51_200 = "51-200"
    S_201_1000 = "201-1000"
    S_1000_PLUS = "1000+"


class JobStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class EmploymentType(enum.StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    INTERNSHIP = "INTERNSHIP"
    TEMPORARY = "TEMPORARY"


class WorkplaceType(enum.StrEnum):
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"


class ExperienceLevel(enum.StrEnum):
    ENTRY = "ENTRY"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    LEAD = "LEAD"


class EducationLevel(enum.StrEnum):
    """Ordered: the integer rank is used for education alignment scoring."""

    HIGH_SCHOOL = "HIGH_SCHOOL"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    DOCTORATE = "DOCTORATE"

    @property
    def rank(self) -> int:
        return list(type(self)).index(self)


class SkillRequirement(enum.StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class SkillProficiency(enum.StrEnum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class DataSource(enum.StrEnum):
    """Provenance of structured candidate data: typed by the user vs. suggested by the résumé parser."""

    USER = "USER"
    RESUME = "RESUME"


class SkillStatus(enum.StrEnum):
    CONFIRMED = "CONFIRMED"
    SUGGESTED = "SUGGESTED"
    REJECTED = "REJECTED"


class RemotePreference(enum.StrEnum):
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"
    FLEXIBLE = "FLEXIBLE"


class Availability(enum.StrEnum):
    IMMEDIATELY = "IMMEDIATELY"
    TWO_WEEKS = "TWO_WEEKS"
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class LanguageProficiency(enum.StrEnum):
    BASIC = "BASIC"
    CONVERSATIONAL = "CONVERSATIONAL"
    FLUENT = "FLUENT"
    NATIVE = "NATIVE"


class CandidateSource(enum.StrEnum):
    SELF = "SELF"  # registered on the platform
    IMPORTED = "IMPORTED"  # sourced by a company via bulk résumé import


class ResumeStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class ProcessingStatus(enum.StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ApplicationStatus(enum.StrEnum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    SHORTLISTED = "SHORTLISTED"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class InterviewType(enum.StrEnum):
    PHONE_SCREEN = "PHONE_SCREEN"
    TECHNICAL = "TECHNICAL"
    BEHAVIORAL = "BEHAVIORAL"
    PANEL = "PANEL"
    ONSITE = "ONSITE"
    FINAL = "FINAL"


class InterviewStatus(enum.StrEnum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


ACTIVE_INTERVIEW_STATUSES = (
    InterviewStatus.SCHEDULED,
    InterviewStatus.CONFIRMED,
    InterviewStatus.RESCHEDULED,
)


class ParticipantRole(enum.StrEnum):
    INTERVIEWER = "INTERVIEWER"
    OBSERVER = "OBSERVER"


class HireRecommendation(enum.StrEnum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    NO_HIRE = "NO_HIRE"
    STRONG_NO_HIRE = "STRONG_NO_HIRE"


class NotificationType(enum.StrEnum):
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPLICATION_STATUS_CHANGED = "APPLICATION_STATUS_CHANGED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_RESCHEDULED = "INTERVIEW_RESCHEDULED"
    INTERVIEW_CANCELLED = "INTERVIEW_CANCELLED"
    RESUME_PROCESSED = "RESUME_PROCESSED"
    RESUME_FAILED = "RESUME_FAILED"
    NEW_CANDIDATE_MATCH = "NEW_CANDIDATE_MATCH"
    NEW_JOB_RECOMMENDATION = "NEW_JOB_RECOMMENDATION"
    BULK_IMPORT_COMPLETED = "BULK_IMPORT_COMPLETED"


class TaskType(enum.StrEnum):
    PROCESS_RESUME = "PROCESS_RESUME"
    MATCH_JOB = "MATCH_JOB"  # (re)score one job against candidates
    MATCH_CANDIDATE = "MATCH_CANDIDATE"  # (re)score one candidate against published jobs
    REFRESH_EMBEDDINGS = "REFRESH_EMBEDDINGS"  # re-embed everything stale / on model change
    BULK_RESUME_IMPORT = "BULK_RESUME_IMPORT"
    EXPORT_REPORT = "EXPORT_REPORT"


class TaskStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ACTIVE_TASK_STATUSES = (TaskStatus.PENDING, TaskStatus.RUNNING)


class ImportItemStatus(enum.StrEnum):
    PENDING = "PENDING"
    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


def enum_values(enum_cls: type[enum.Enum]) -> list[Any]:
    return [m.value for m in enum_cls]
