"""Job postings: creation, editing, lifecycle state machine, skills, saved jobs and the read models."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import BusinessRuleError, ConflictError, InvalidStateTransitionError, NotFoundError, PermissionDeniedError
from app.core.security import Role
from app.db.models import (
    Application,
    ApplicationStatus,
    CandidateJobMatch,
    CandidateProfile,
    Company,
    CompanyStatus,
    Job,
    JobSkill,
    JobStatus,
    SavedJob,
    SkillRequirement,
    User,
    UserStatus,
)
from app.matching.scoring import overall_band
from app.schemas.company import CompanyPublic
from app.schemas.job import (
    JobCreate,
    JobDetail,
    JobPublic,
    JobSkillIn,
    JobSkillOut,
    JobStats,
    JobUpdate,
    MatchPreview,
)
from app.schemas.skill import SkillOut
from app.services.access import can_manage_job, can_view_job_internal, is_admin, load_job_for_staff, require_company
from app.services.common import record_audit, utcnow
from app.services.scheduling import schedule_job_match
from app.services.skills import SkillService
from app.services.tasks import Dispatcher

logger = logging.getLogger(__name__)

# Lifecycle: DRAFT → PUBLISHED ⇄ PAUSED → CLOSED → ARCHIVED   (+ DRAFT → ARCHIVED, PUBLISHED → CLOSED)
JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.DRAFT: frozenset({JobStatus.PUBLISHED, JobStatus.ARCHIVED}),
    JobStatus.PUBLISHED: frozenset({JobStatus.PAUSED, JobStatus.CLOSED}),
    JobStatus.PAUSED: frozenset({JobStatus.PUBLISHED, JobStatus.CLOSED}),
    JobStatus.CLOSED: frozenset({JobStatus.ARCHIVED}),
    JobStatus.ARCHIVED: frozenset(),
}
EDITABLE_STATUSES = frozenset({JobStatus.DRAFT, JobStatus.PUBLISHED, JobStatus.PAUSED})
# Fields whose change alters who matches: they trigger a re-match of a live job.
MATCH_AFFECTING = {
    "title", "description", "responsibilities", "qualifications", "skills", "min_experience_years", "max_experience_years",
    "experience_level", "min_education_level", "location", "workplace_type", "employment_type",
}


def is_open_for_applications(job: Job, today: date | None = None) -> tuple[bool, str | None]:
    if job.status != JobStatus.PUBLISHED:
        return False, "This job is not accepting applications"
    if job.application_deadline and job.application_deadline < (today or date.today()):
        return False, "The application deadline has passed"
    return True, None


class JobService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher | None = None, cache: Cache | None = None) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.cache = cache

    async def _invalidate(self, *, matches: bool = False) -> None:
        if self.cache:
            await self.cache.invalidate(CacheDomain.JOBS, *( [CacheDomain.MATCHES] if matches else []))

    # --- skills ---------------------------------------------------------------------------------------------
    async def _set_skills(self, job: Job, items: list[JobSkillIn]) -> None:
        skills = SkillService(self.session, self.cache)
        resolved: dict[uuid.UUID, JobSkillIn] = {}
        for item in items:
            if item.skill_id:
                from app.db.models import Skill

                skill = await self.session.get(Skill, item.skill_id)
                if skill is None:
                    raise NotFoundError(f"Skill {item.skill_id} not found", code="SKILL_NOT_FOUND")
            else:
                assert item.name
                skill = await skills.get_or_create(item.name)
            # A skill listed twice: REQUIRED wins over PREFERRED.
            prev = resolved.get(skill.id)
            if prev is None or (item.requirement == SkillRequirement.REQUIRED and prev.requirement != SkillRequirement.REQUIRED):
                resolved[skill.id] = item
        await self.session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
        for sid, item in resolved.items():
            self.session.add(JobSkill(job_id=job.id, skill_id=sid, requirement=item.requirement, min_years=item.min_years))
        await self.session.flush()

    async def _validate_hiring_manager(self, actor: User, company_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
        if user_id is None:
            return
        hm = await self.session.get(User, user_id)
        if hm is None or hm.company_id != company_id or hm.role not in (Role.HIRING_MANAGER, Role.RECRUITER) or hm.status != UserStatus.ACTIVE:
            raise BusinessRuleError("Hiring manager must be an active staff member of the same company", code="INVALID_HIRING_MANAGER")

    # --- create / update ----------------------------------------------------------------------------------------
    async def create(self, actor: User, data: JobCreate, *, company_id: uuid.UUID | None = None) -> Job:
        if is_admin(actor):
            if company_id is None:
                raise BusinessRuleError("company_id is required for admins", code="COMPANY_REQUIRED")
            cid = company_id
        else:
            if actor.role != Role.RECRUITER:
                raise PermissionDeniedError("Only recruiters can create jobs")
            cid = require_company(actor)
        company = await self.session.get(Company, cid)
        if company is None:
            raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
        if company.status != CompanyStatus.ACTIVE:
            raise BusinessRuleError("This company is suspended", code="COMPANY_SUSPENDED")
        await self._validate_hiring_manager(actor, cid, data.hiring_manager_id)
        fields = data.model_dump(exclude={"skills"})
        job = Job(company_id=cid, created_by_id=actor.id, status=JobStatus.DRAFT, **fields)
        self.session.add(job)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A live job with the same title, location and workplace type already exists", code="DUPLICATE_JOB") from exc
        await self._set_skills(job, data.skills)
        await self._refresh_skills_text(job)
        record_audit(self.session, actor_id=actor.id, action="job.created", entity_type="job", entity_id=job.id, company_id=cid)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A live job with the same title, location and workplace type already exists", code="DUPLICATE_JOB") from exc
        await self._invalidate()
        return job

    async def _refresh_skills_text(self, job: Job) -> None:
        """Denormalise skill names onto the job (feeds the full-text index)."""
        from app.db.models import Skill

        rows = (
            await self.session.execute(
                select(Skill.name).join(JobSkill, JobSkill.skill_id == Skill.id).where(JobSkill.job_id == job.id).order_by(Skill.name)
            )
        ).scalars().all()
        job.skills_text = ", ".join(rows) or None

    async def update(self, actor: User, job_id: uuid.UUID, data: JobUpdate) -> Job:
        job = await load_job_for_staff(self.session, actor, job_id, write=True)
        if job.status not in EDITABLE_STATUSES:
            raise BusinessRuleError("Closed or archived jobs cannot be edited", code="JOB_NOT_EDITABLE")
        changes: dict[str, Any] = data.model_dump(exclude_unset=True, exclude={"skills"})
        for non_null in ("title", "description", "employment_type", "workplace_type", "salary_currency", "min_experience_years"):
            if non_null in changes and changes[non_null] is None:
                changes.pop(non_null)
        if "hiring_manager_id" in changes:
            await self._validate_hiring_manager(actor, job.company_id, changes["hiring_manager_id"])
        merged = {**{k: getattr(job, k) for k in ("salary_min", "salary_max", "min_experience_years", "max_experience_years")}, **changes}
        if merged["salary_min"] is not None and merged["salary_max"] is not None and merged["salary_max"] < merged["salary_min"]:
            raise BusinessRuleError("salary_max must be greater than or equal to salary_min", code="INVALID_SALARY_RANGE")
        if merged["max_experience_years"] is not None and merged["max_experience_years"] < merged["min_experience_years"]:
            raise BusinessRuleError("max_experience_years must be >= min_experience_years", code="INVALID_EXPERIENCE_RANGE")
        if "application_deadline" in changes and changes["application_deadline"] and changes["application_deadline"] < date.today():
            raise BusinessRuleError("application_deadline cannot be in the past", code="INVALID_DEADLINE")
        for k, v in changes.items():
            setattr(job, k, v)
        affects_match = bool(MATCH_AFFECTING & set(changes)) or data.skills is not None
        if data.skills is not None:
            await self._set_skills(job, data.skills)
        await self._refresh_skills_text(job)
        record_audit(self.session, actor_id=actor.id, action="job.updated", entity_type="job", entity_id=job.id, company_id=job.company_id)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A live job with the same title, location and workplace type already exists", code="DUPLICATE_JOB") from exc
        await self._invalidate(matches=affects_match)
        if affects_match and job.status == JobStatus.PUBLISHED:
            await schedule_job_match(self.session, self.dispatcher, job.id, user_id=actor.id, company_id=job.company_id)
        return job

    async def delete_draft(self, actor: User, job_id: uuid.UUID) -> None:
        job = await load_job_for_staff(self.session, actor, job_id, write=True)
        if job.status != JobStatus.DRAFT:
            raise BusinessRuleError("Only drafts can be deleted; close and archive published jobs instead", code="JOB_NOT_DELETABLE")
        await self.session.delete(job)
        record_audit(self.session, actor_id=actor.id, action="job.deleted", entity_type="job", entity_id=job_id, company_id=job.company_id)
        await self.session.commit()
        await self._invalidate(matches=True)

    # --- lifecycle ------------------------------------------------------------------------------------------------
    async def _publish_problems(self, job: Job) -> list[str]:
        problems: list[str] = []
        if len(job.description.strip()) < 30:
            problems.append("Description must be at least 30 characters")
        n_required = await self.session.scalar(
            select(func.count()).select_from(JobSkill).where(JobSkill.job_id == job.id, JobSkill.requirement == SkillRequirement.REQUIRED)
        )
        if not n_required:
            problems.append("Add at least one required skill")
        if job.application_deadline and job.application_deadline < date.today():
            problems.append("The application deadline is in the past")
        company = await self.session.get(Company, job.company_id)
        if company is None or company.status != CompanyStatus.ACTIVE:
            problems.append("The company account is suspended")
        return problems

    async def transition(self, actor: User, job_id: uuid.UUID, target: JobStatus, reason: str | None = None) -> Job:
        job = await load_job_for_staff(self.session, actor, job_id, write=True)
        if target not in JOB_TRANSITIONS[job.status]:
            raise InvalidStateTransitionError(
                f"A {job.status.value.lower()} job cannot become {target.value.lower()}",
                details={"from": job.status.value, "to": target.value, "allowed": sorted(s.value for s in JOB_TRANSITIONS[job.status])},
            )
        if target == JobStatus.PUBLISHED:
            problems = await self._publish_problems(job)
            if problems:
                raise BusinessRuleError("This job cannot be published yet", code="PUBLISH_VALIDATION_FAILED", details=problems)
            job.published_at = job.published_at or utcnow()
        if target in (JobStatus.CLOSED, JobStatus.ARCHIVED):
            job.closed_at = job.closed_at or utcnow()
        previous = job.status
        job.status = target
        record_audit(
            self.session, actor_id=actor.id, action=f"job.{target.value.lower()}", entity_type="job", entity_id=job.id,
            company_id=job.company_id, meta={"from": previous.value, "reason": reason},
        )
        await self.session.commit()
        await self._invalidate(matches=True)
        if target == JobStatus.PUBLISHED:
            await schedule_job_match(self.session, self.dispatcher, job.id, user_id=actor.id, company_id=job.company_id, notify=previous == JobStatus.DRAFT)
        return job

    # --- reads -------------------------------------------------------------------------------------------------------
    async def _load(self, job_id: uuid.UUID) -> Job:
        job = (
            await self.session.execute(
                select(Job).where(Job.id == job_id).options(selectinload(Job.company), selectinload(Job.skills).selectinload(JobSkill.skill))
            )
        ).scalar_one_or_none()
        if job is None:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        return job

    @staticmethod
    def _skill_outs(job: Job) -> list[JobSkillOut]:
        order = {SkillRequirement.REQUIRED: 0, SkillRequirement.PREFERRED: 1}
        return [
            JobSkillOut(skill=SkillOut.model_validate(js.skill), requirement=js.requirement, min_years=js.min_years)
            for js in sorted(job.skills, key=lambda j: (order[j.requirement], j.skill.name.lower()))
        ]

    async def public_detail(self, job_id: uuid.UUID, viewer: User | None) -> JobPublic | JobDetail:
        """Anonymous/candidate callers see PUBLISHED jobs only (404 otherwise); the owning company's staff see everything."""
        job = await self._load(job_id)
        staff_view = viewer is not None and can_view_job_internal(viewer, job)
        if not staff_view and (job.status != JobStatus.PUBLISHED or job.company.status != CompanyStatus.ACTIVE):
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        base = {
            **{f: getattr(job, f) for f in JobPublic.model_fields if hasattr(job, f) and f not in ("company", "skills")},
            "company": CompanyPublic.model_validate(job.company),
            "skills": self._skill_outs(job),
        }
        open_, reason = is_open_for_applications(job)
        if staff_view:
            assert viewer is not None
            count = await self.session.scalar(select(func.count()).select_from(Application).where(Application.job_id == job.id))
            hm_name = None
            if job.hiring_manager_id:
                hm = await self.session.get(User, job.hiring_manager_id)
                hm_name = hm.full_name if hm else None
            return JobDetail(
                **base,
                company_id=job.company_id,
                created_by_id=job.created_by_id,
                hiring_manager_id=job.hiring_manager_id,
                hiring_manager_name=hm_name,
                closed_at=job.closed_at,
                application_count=int(count or 0),
                embedding_ready=job.embedding is not None,
                allowed_transitions=sorted(JOB_TRANSITIONS[job.status], key=lambda s: s.value) if can_manage_job(viewer, job) else [],
                can_apply=open_,
                apply_blocked_reason=reason,
            )
        pub = JobPublic(**base, can_apply=open_, apply_blocked_reason=reason)
        if viewer is not None and viewer.role == Role.CANDIDATE:
            await self._decorate_for_candidate(pub, job, viewer)
        return pub

    async def _decorate_for_candidate(self, pub: JobPublic, job: Job, viewer: User) -> None:
        profile_id = await self.session.scalar(select(CandidateProfile.id).where(CandidateProfile.user_id == viewer.id))
        if profile_id is None:
            return
        pub.is_saved = bool(await self.session.scalar(select(SavedJob.job_id).where(SavedJob.candidate_id == profile_id, SavedJob.job_id == job.id)))
        app = (
            await self.session.execute(
                select(Application.id, Application.status).where(
                    Application.job_id == job.id, Application.candidate_id == profile_id, Application.status != ApplicationStatus.WITHDRAWN
                )
            )
        ).first()
        if app:
            pub.my_application_id, pub.my_application_status = app[0], app[1].value
            pub.can_apply, pub.apply_blocked_reason = False, "You have already applied to this job"
        m = await self.session.scalar(
            select(CandidateJobMatch.overall_score).where(CandidateJobMatch.job_id == job.id, CandidateJobMatch.candidate_id == profile_id)
        )
        if m is not None:
            pub.match = MatchPreview(overall_score=m, band=overall_band(m))

    async def stats(self, actor: User, job_id: uuid.UUID) -> JobStats:
        job = await load_job_for_staff(self.session, actor, job_id)
        rows = (
            await self.session.execute(
                select(Application.status, func.count()).where(Application.job_id == job.id).group_by(Application.status)
            )
        ).all()
        by_status = {s.value: n for s, n in rows}
        matched, last = (
            await self.session.execute(
                select(func.count(), func.max(CandidateJobMatch.generated_at)).where(CandidateJobMatch.job_id == job.id)
            )
        ).one()
        return JobStats(job_id=job.id, applications_total=sum(by_status.values()), applications_by_status=by_status, matches_computed=matched, last_matched_at=last)

    # --- saved jobs ------------------------------------------------------------------------------------------------------
    async def _candidate_id(self, user: User) -> uuid.UUID:
        cid = await self.session.scalar(select(CandidateProfile.id).where(CandidateProfile.user_id == user.id))
        if cid is None:
            raise PermissionDeniedError("Only candidates can save jobs")
        return cid

    async def save(self, user: User, job_id: uuid.UUID) -> None:
        cid = await self._candidate_id(user)
        job = await self.session.get(Job, job_id)
        if job is None or job.status != JobStatus.PUBLISHED:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        if await self.session.scalar(select(Company.status).where(Company.id == job.company_id)) != CompanyStatus.ACTIVE:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        if not await self.session.scalar(select(SavedJob.job_id).where(SavedJob.candidate_id == cid, SavedJob.job_id == job_id)):
            self.session.add(SavedJob(candidate_id=cid, job_id=job_id))
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()  # concurrent double-save: idempotent

    async def unsave(self, user: User, job_id: uuid.UUID) -> None:
        cid = await self._candidate_id(user)
        await self.session.execute(delete(SavedJob).where(SavedJob.candidate_id == cid, SavedJob.job_id == job_id))
        await self.session.commit()
