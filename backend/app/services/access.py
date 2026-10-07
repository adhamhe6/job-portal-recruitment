"""Object-level authorization.

Route handlers never decide access. Every service funnels through these helpers so that tenant isolation,
ownership and assignment rules live in exactly one place. Resources belonging to another tenant are reported as
*not found* (404) rather than forbidden, so ids cannot be probed for existence.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import STAFF_ROLES, Role
from app.db.models import Application, CandidateProfile, CandidateSource, Job, User


def is_admin(user: User) -> bool:
    return user.role == Role.ADMIN


def is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES


def require_company(user: User) -> uuid.UUID:
    if user.company_id is None:
        raise PermissionDeniedError("Your account is not attached to a company")
    return user.company_id


# --- jobs -------------------------------------------------------------------------------------


def can_manage_job(user: User, job: Job) -> bool:
    """Create/edit/publish/close: admins, and recruiters of the owning company."""
    if is_admin(user):
        return True
    return user.role == Role.RECRUITER and user.company_id == job.company_id


def can_view_job_internal(user: User, job: Job) -> bool:
    """See drafts/internal fields: admins, the owning company's recruiters, and the assigned hiring manager."""
    if is_admin(user):
        return True
    if user.company_id != job.company_id:
        return False
    if user.role == Role.RECRUITER:
        return True
    return user.role == Role.HIRING_MANAGER and job.hiring_manager_id == user.id


async def load_job_for_staff(session: AsyncSession, user: User, job_id: uuid.UUID, *, write: bool = False) -> Job:
    job = await session.get(Job, job_id)
    if job is None or not can_view_job_internal(user, job):
        raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
    if write and not can_manage_job(user, job):
        raise PermissionDeniedError("You cannot modify this job")
    return job


# --- candidates ---------------------------------------------------------------------------------


class CandidateAccess(enum.IntEnum):
    NONE = 0
    PROFILE = 1  # profile visible, contact details and résumé file withheld (marketplace visibility)
    FULL = 2  # applicant or company-sourced: contact details + résumé file


async def candidate_access_for(session: AsyncSession, user: User, candidate: CandidateProfile) -> CandidateAccess:
    """What may ``user`` see of ``candidate``?

    * the candidate themself and admins: everything
    * a company's recruiter: FULL when the candidate applied to one of the company's jobs or was sourced by the
      company; PROFILE when the candidate opted into the marketplace (``is_searchable``)
    * a hiring manager: FULL only for candidates who applied to a job assigned to them
    """
    if is_admin(user) or (candidate.user_id is not None and candidate.user_id == user.id):
        return CandidateAccess.FULL
    if not is_staff(user) or user.company_id is None:
        return CandidateAccess.NONE

    applied = await session.scalar(
        select(
            exists().where(
                Application.candidate_id == candidate.id,
                Application.job_id == Job.id,
                Job.company_id == user.company_id,
                *([Job.hiring_manager_id == user.id] if user.role == Role.HIRING_MANAGER else []),
            )
        )
    )
    if applied:
        return CandidateAccess.FULL
    if user.role == Role.HIRING_MANAGER:
        return CandidateAccess.NONE
    if candidate.source == CandidateSource.IMPORTED and candidate.sourced_by_company_id == user.company_id:
        return CandidateAccess.FULL
    if candidate.source == CandidateSource.SELF and candidate.is_searchable:
        return CandidateAccess.PROFILE
    return CandidateAccess.NONE


async def load_candidate_for_user(
    session: AsyncSession, user: User, candidate_id: uuid.UUID, *, minimum: CandidateAccess = CandidateAccess.PROFILE
) -> tuple[CandidateProfile, CandidateAccess]:
    candidate = await session.get(CandidateProfile, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
    access = await candidate_access_for(session, user, candidate)
    if access < minimum or access == CandidateAccess.NONE:
        raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
    return candidate, access


# --- applications -----------------------------------------------------------------------------------


async def load_application_for_user(
    session: AsyncSession, user: User, application_id: uuid.UUID, *, manage: bool = False
) -> tuple[Application, Job]:
    """Load an application the caller may see; ``manage`` additionally requires recruiter-level rights."""
    app = await session.get(Application, application_id)
    if app is None:
        raise NotFoundError("Application not found", code="APPLICATION_NOT_FOUND")
    job = await session.get(Job, app.job_id)
    assert job is not None
    if user.role == Role.CANDIDATE:
        profile_user_id = await session.scalar(
            select(CandidateProfile.user_id).where(CandidateProfile.id == app.candidate_id)
        )
        if profile_user_id != user.id:
            raise NotFoundError("Application not found", code="APPLICATION_NOT_FOUND")
        if manage:
            raise PermissionDeniedError("Candidates cannot manage application stages")
        return app, job
    if not can_view_job_internal(user, job):
        raise NotFoundError("Application not found", code="APPLICATION_NOT_FOUND")
    if manage and not can_manage_job(user, job):
        raise PermissionDeniedError("You cannot manage applications for this job")
    return app, job
