"""Read side of matching: ranked candidates for a job, match detail, and job recommendations for a candidate."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import Role
from app.db.models import (
    Application,
    ApplicationStatus,
    Availability,
    CandidateJobMatch,
    CandidateProfile,
    CandidateSkill,
    Company,
    CompanyStatus,
    Job,
    JobSkill,
    JobStatus,
    SkillRequirement,
    SkillStatus,
    TaskType,
    User,
)
from app.matching.embedder import get_embedder
from app.matching.loaders import load_candidate_features, load_job_features
from app.matching.scoring import MATCHING_VERSION, overall_band
from app.matching.service import MatchingService
from app.schemas.job import JobListItem
from app.schemas.match import (
    CandidateFacingMatch,
    MatchDetail,
    MatchedCandidate,
    RankedCandidatesMeta,
    RecommendationsMeta,
    RecommendedJob,
    ScoreBreakdown,
)
from app.search.candidates import visibility_predicate
from app.services.access import CandidateAccess, candidate_access_for, load_job_for_staff
from app.services.common import paginate
from app.services.scheduling import schedule_candidate_refresh, schedule_job_match
from app.services.tasks import Dispatcher, TaskService


def _breakdown(m: CandidateJobMatch) -> ScoreBreakdown:
    return ScoreBreakdown(
        semantic=m.semantic_score, required_skills=m.required_skill_score, preferred_skills=m.preferred_skill_score,
        experience=m.experience_score, education=m.education_score, preferences=m.preference_score,
    )


def candidate_facing(m: CandidateJobMatch) -> CandidateFacingMatch:
    e = m.explanation
    req, pref = e["skills"]["required"], e["skills"]["preferred"]
    return CandidateFacingMatch(
        overall_percent=round(m.overall_score * 100), band=overall_band(m.overall_score), summary=e.get("summary", ""),
        matched_skills=[s["name"] for s in [*req["matched"], *pref["matched"]]],
        related_skills=[{"wanted": r["required"], "you_have": r["candidate_has"]} for r in [*req["related"], *pref["related"]]],
        missing_required=req["missing"], missing_preferred=pref["missing"],
        experience_text=e["experience"]["text"], experience_status=e["experience"]["status"],
        semantic_band=e["semantic"]["band"], generated_at=m.generated_at,
    )


class MatchQueryService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher | None = None, cache: Cache | None = None) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.cache = cache

    # --- recruiter side -----------------------------------------------------------------------------------------
    async def ranked_candidates(
        self,
        user: User,
        job_id: uuid.UUID,
        *,
        min_score: float | None = None,
        min_experience: Decimal | None = None,
        skill_ids: list[uuid.UUID] | None = None,
        location: str | None = None,
        availability: list[Availability] | None = None,
        applicants_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MatchedCandidate], int, RankedCandidatesMeta]:
        job = await load_job_for_staff(self.session, user, job_id)
        stmt = (
            select(CandidateJobMatch, CandidateProfile)
            .join(CandidateProfile, CandidateProfile.id == CandidateJobMatch.candidate_id)
            .where(CandidateJobMatch.job_id == job.id, visibility_predicate(user))
        )
        if min_score is not None:
            stmt = stmt.where(CandidateJobMatch.overall_score >= min_score)
        if min_experience is not None:
            stmt = stmt.where(CandidateProfile.years_experience >= min_experience)
        for sid in skill_ids or []:
            stmt = stmt.where(
                exists().where(CandidateSkill.candidate_id == CandidateProfile.id, CandidateSkill.skill_id == sid, CandidateSkill.status != SkillStatus.REJECTED)
            )
        if location:
            stmt = stmt.where(CandidateProfile.location.ilike(f"%{location.strip().replace('%', '').replace('_', '')}%"))
        if availability:
            stmt = stmt.where(CandidateProfile.availability.in_(availability))
        if applicants_only:
            stmt = stmt.where(exists().where(Application.candidate_id == CandidateProfile.id, Application.job_id == job.id))
        rows, total = await paginate(
            self.session, stmt.order_by(CandidateJobMatch.overall_score.desc(), CandidateProfile.id), page=page, page_size=page_size, scalars=False
        )
        ids = [p.id for _, p in rows]
        apps = {
            a.candidate_id: a
            for a in (
                await self.session.execute(
                    select(Application).where(Application.job_id == job.id, Application.candidate_id.in_(ids), Application.status != ApplicationStatus.WITHDRAWN)
                )
            ).scalars()
        }
        jf = (await load_job_features(self.session, [job.id]))[job.id]
        cfs = await load_candidate_features(self.session, ids)
        job_hash = jf.feature_hash()
        emb = get_embedder()
        items: list[MatchedCandidate] = []
        stale = 0
        for m, p in rows:
            is_stale = (
                m.job_hash != job_hash or m.candidate_hash != cfs[p.id].feature_hash() or m.matching_version != MATCHING_VERSION
                or m.embedding_model != emb.name or m.embedding_version != emb.version
            )
            stale += int(is_stale)
            e = m.explanation
            req, pref = e["skills"]["required"], e["skills"]["preferred"]
            app = apps.get(p.id)
            access = await candidate_access_for(self.session, user, p)
            items.append(
                MatchedCandidate(
                    candidate_id=p.id, display_name=p.display_name, headline=p.headline, location=p.location, years_experience=p.years_experience,
                    availability=p.availability, overall_score=m.overall_score, overall_percent=round(m.overall_score * 100),
                    band=overall_band(m.overall_score), breakdown=_breakdown(m), summary=e.get("summary", ""),
                    strong_skills=[s["name"] for s in [*req["matched"], *pref["matched"]]],
                    related_skills=[{"required": r["required"], "candidate_has": r["candidate_has"]} for r in [*req["related"], *pref["related"]]],
                    missing_required=req["missing"], missing_preferred=pref["missing"], experience_text=e["experience"]["text"],
                    semantic_band=e["semantic"]["band"], has_applied=app is not None, application_id=app.id if app else None,
                    application_status=app.status.value if app else None, access=access.name, stale=is_stale, generated_at=m.generated_at,
                )
            )
        totals = (
            await self.session.execute(
                select(func.count(), func.max(CandidateJobMatch.generated_at)).where(CandidateJobMatch.job_id == job.id)
            )
        ).one()
        task_id = None
        if stale or totals[0] == 0:  # stale or never computed → refresh in the background (deduplicated)
            task_id, _ = await schedule_job_match(self.session, self.dispatcher, job.id, user_id=user.id, company_id=job.company_id)
        meta = RankedCandidatesMeta(
            job_id=job.id, total_scored=totals[0], last_generated_at=totals[1], stale_rows=stale,
            embedding_model=emb.name, matching_version=MATCHING_VERSION, computing_task_id=task_id,
        )
        return items, total, meta

    async def refresh_job(self, user: User, job_id: uuid.UUID) -> tuple[uuid.UUID, bool]:
        job = await load_job_for_staff(self.session, user, job_id, write=False)
        if user.role not in (Role.RECRUITER, Role.ADMIN):
            raise PermissionDeniedError("Only recruiters can run matching")
        task_id, created = await schedule_job_match(self.session, self.dispatcher, job.id, user_id=user.id, company_id=job.company_id)
        if task_id is None:
            from app.core.errors import ServiceUnavailableError

            raise ServiceUnavailableError("The job queue is unavailable; please try again shortly")
        return task_id, created

    async def detail(self, user: User, job_id: uuid.UUID, candidate_id: uuid.UUID) -> MatchDetail:
        job = await load_job_for_staff(self.session, user, job_id)
        cand = await self.session.get(CandidateProfile, candidate_id)
        if cand is None or await candidate_access_for(self.session, user, cand) == CandidateAccess.NONE:
            raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
        m = await MatchingService(self.session).get_or_compute(job, cand)
        return MatchDetail(
            job_id=job.id, job_title=job.title, candidate_id=cand.id, candidate_name=cand.display_name, overall_score=m.overall_score,
            overall_percent=round(m.overall_score * 100), band=overall_band(m.overall_score), breakdown=_breakdown(m), explanation=m.explanation,
            embedding_model=m.embedding_model, embedding_version=m.embedding_version, matching_version=m.matching_version, generated_at=m.generated_at,
        )

    # --- candidate side --------------------------------------------------------------------------------------------
    async def my_job_match(self, user: User, job_id: uuid.UUID) -> CandidateFacingMatch:
        cand = (await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))).scalar_one_or_none()
        job = await self.session.get(Job, job_id)
        if cand is None or job is None or job.status != JobStatus.PUBLISHED:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        if await self.session.scalar(select(Company.status).where(Company.id == job.company_id)) != CompanyStatus.ACTIVE:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        return candidate_facing(await MatchingService(self.session).get_or_compute(job, cand))

    async def recommendations(
        self,
        user: User,
        *,
        min_score: float = 0.0,
        workplace_types: list[str] | None = None,
        employment_types: list[str] | None = None,
        location: str | None = None,
        skill_ids: list[uuid.UUID] | None = None,
        sort: str = "score",
        page: int = 1,
        page_size: int = 12,
    ) -> tuple[list[RecommendedJob], int, RecommendationsMeta]:
        cand = (await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))).scalar_one_or_none()
        if cand is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        applied = select(Application.job_id).where(Application.candidate_id == cand.id, Application.status != ApplicationStatus.WITHDRAWN)
        stmt = (
            select(CandidateJobMatch, Job)
            .join(Job, Job.id == CandidateJobMatch.job_id)
            .join(Company, Company.id == Job.company_id)
            .where(
                CandidateJobMatch.candidate_id == cand.id,
                Job.status == JobStatus.PUBLISHED,  # never recommend draft/paused/closed/archived jobs
                Company.status == CompanyStatus.ACTIVE,  # ... nor those of a suspended employer
                or_(Job.application_deadline.is_(None), Job.application_deadline >= func.current_date()),  # nor ones no longer open
                Job.id.not_in(applied),
                CandidateJobMatch.overall_score >= min_score,
            )
        )
        if workplace_types:
            stmt = stmt.where(Job.workplace_type.in_(workplace_types))
        if employment_types:
            stmt = stmt.where(Job.employment_type.in_(employment_types))
        if location:
            stmt = stmt.where(Job.location.ilike(f"%{location.strip().replace('%', '').replace('_', '')}%"))
        for sid in skill_ids or []:
            stmt = stmt.where(exists().where(JobSkill.job_id == Job.id, JobSkill.skill_id == sid))
        order = [Job.published_at.desc().nulls_last()] if sort == "newest" else [CandidateJobMatch.overall_score.desc()]
        rows, total = await paginate(self.session, stmt.order_by(*order, Job.id), page=page, page_size=page_size, scalars=False)

        job_ids = [j.id for _, j in rows]
        jobs = {
            j.id: j
            for j in (
                await self.session.execute(
                    select(Job).where(Job.id.in_(job_ids)).options(selectinload(Job.company), selectinload(Job.skills).selectinload(JobSkill.skill))
                )
            ).scalars()
        }
        from app.db.models import SavedJob

        saved = {r[0] for r in (await self.session.execute(select(SavedJob.job_id).where(SavedJob.candidate_id == cand.id, SavedJob.job_id.in_(job_ids)))).all()}
        items: list[RecommendedJob] = []
        for m, j0 in rows:
            j = jobs[j0.id]
            req = [js.skill.name for js in sorted(j.skills, key=lambda x: x.skill.name.lower()) if js.requirement == SkillRequirement.REQUIRED]
            items.append(
                RecommendedJob(
                    job=JobListItem(
                        id=j.id, title=j.title, company_id=j.company_id, company_name=j.company.name, company_logo_url=j.company.logo_url,
                        department=j.department, location=j.location, employment_type=j.employment_type, workplace_type=j.workplace_type,
                        experience_level=j.experience_level, min_experience_years=j.min_experience_years, salary_min=j.salary_min,
                        salary_max=j.salary_max, salary_currency=j.salary_currency, skills=req[:6], status=j.status, published_at=j.published_at,
                        application_deadline=j.application_deadline, created_at=j.created_at, updated_at=j.updated_at,
                        is_saved=j.id in saved, has_applied=False, match_score=m.overall_score,
                    ),
                    match=candidate_facing(m),
                )
            )
        last = await self.session.scalar(select(func.max(CandidateJobMatch.generated_at)).where(CandidateJobMatch.candidate_id == cand.id))
        meta = RecommendationsMeta(last_generated_at=last, profile_ready=cand.embedding is not None)
        if last is None or cand.embedding is None:
            # Nothing precomputed yet (new profile): build it in the background rather than on this request.
            await schedule_candidate_refresh(self.session, self.dispatcher, cand.id, user.id)
            active = await TaskService(self.session)._active_by_key(f"match-candidate:{cand.id}")
            meta.computing, meta.task_id = active is not None, active.id if active else None
            meta.hint = (
                "Add skills, experience or upload your résumé so we can understand your profile." if cand.embedding is None and not active else "Finding jobs that fit your profile…"
            )
        return items, total, meta

    async def refresh_mine(self, user: User) -> uuid.UUID:
        cand = (await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))).scalar_one_or_none()
        if cand is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        task, _ = await TaskService(self.session).submit(
            TaskType.MATCH_CANDIDATE, {"candidate_id": str(cand.id)}, self.dispatcher, created_by_id=user.id, dedupe_key=f"match-candidate:{cand.id}"  # type: ignore[arg-type]
        )
        if self.cache:
            await self.cache.invalidate(CacheDomain.MATCHES)
        return task.id


_ = (and_, Any)
