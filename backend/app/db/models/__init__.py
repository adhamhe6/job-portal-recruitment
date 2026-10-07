"""All ORM models (imported here so ``Base.metadata`` is complete for Alembic and tests)."""

from app.db.models.application import Application, ApplicationNote, ApplicationStatusHistory
from app.db.models.candidate import (
    EMBEDDING_DIM,
    CandidateLanguage,
    CandidateProfile,
    CandidateSkill,
    Certification,
    Education,
    Experience,
)
from app.db.models.enums import *  # noqa: F403
from app.db.models.interview import Interview, InterviewFeedback, InterviewParticipant
from app.db.models.job import Job, JobSkill, SavedJob
from app.db.models.matching import CandidateJobMatch
from app.db.models.resume import Resume, ResumeDocument, ResumeProcessingResult
from app.db.models.skill import Skill, SkillAlias
from app.db.models.system import AuditEvent, BackgroundTask, BulkImportBatch, BulkImportItem, Notification
from app.db.models.user import Company, RecruiterProfile, RefreshToken, User

__all__ = [
    "EMBEDDING_DIM",
    "Application",
    "ApplicationNote",
    "ApplicationStatusHistory",
    "AuditEvent",
    "BackgroundTask",
    "BulkImportBatch",
    "BulkImportItem",
    "CandidateJobMatch",
    "CandidateLanguage",
    "CandidateProfile",
    "CandidateSkill",
    "Certification",
    "Company",
    "Education",
    "Experience",
    "Interview",
    "InterviewFeedback",
    "InterviewParticipant",
    "Job",
    "JobSkill",
    "Notification",
    "RecruiterProfile",
    "RefreshToken",
    "Resume",
    "ResumeDocument",
    "ResumeProcessingResult",
    "SavedJob",
    "Skill",
    "SkillAlias",
    "User",
]
