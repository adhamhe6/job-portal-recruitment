"""Job search: structured filters in SQL + PostgreSQL full-text search + trigram fuzzy match on the title.

All filtering, ranking, sorting and pagination happen in the database; nothing is loaded into Python to be filtered.

* keyword ``q``: ``websearch_to_tsquery`` over the weighted ``search_tsv`` (title A, skills B, description C, dept/location D),
  OR'd with a trigram ``%`` match on the title so a typo ("pyton developr") still finds results.
* ``skills``: ANY-of / ALL-of via EXISTS over ``job_skills`` (index ``(skill_id, job_id)``).
* Relevance sort = ``ts_rank_cd`` + 0.4 · ``similarity(title, q)``.
"""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Application,
    ApplicationStatus,
    CandidateJobMatch,
    Company,
    CompanyStatus,
    EmploymentType,
    ExperienceLevel,
    Job,
    JobSkill,
    JobStatus,
    SavedJob,
    SkillRequirement,
    WorkplaceType,
)
from app.schemas.job import JobListItem
from app.services.common import escape_like, paginate, utcnow


class JobSort(enum.StrEnum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    SALARY_DESC = "salary_desc"
    SALARY_ASC = "salary_asc"
    DEADLINE = "deadline"
    MATCH = "match"
    TITLE = "title"


@dataclass(slots=True)
class JobFilters:
    q: str | None = None
    skill_ids: list[uuid.UUID] = field(default_factory=list)
    skills_mode: str = "any"  # any | all
    location: str | None = None
    employment_types: list[EmploymentType] = field(default_factory=list)
    workplace_types: list[WorkplaceType] = field(default_factory=list)
    experience_levels: list[ExperienceLevel] = field(default_factory=list)
    max_min_experience: Decimal | None = None  # jobs requiring at most this many years
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    company_id: uuid.UUID | None = None
    posted_within_days: int | None = None
    statuses: list[JobStatus] = field(default_factory=list)  # staff list only
    department: str | None = None
    sort: JobSort = JobSort.NEWEST
    only_saved: bool = False


_EXCLUSION = re.compile(r"(^|\s)-\S")


def has_exclusion(q: str) -> bool:
    """True when a ``websearch_to_tsquery`` query contains a negated term such as ``-java``."""
    return bool(_EXCLUSION.search(q))


def _tsquery(q: str) -> Any:
    return func.websearch_to_tsquery("english", q)


def build_job_query(
    f: JobFilters,
    *,
    public: bool,
    company_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    hiring_manager_id: uuid.UUID | None = None,
) -> tuple[Select[Any], bool]:
    """Returns ``(statement, has_match_column)``. ``public`` restricts to live, published jobs."""
    stmt = select(Job).join(Company, Company.id == Job.company_id)
    if public:
        stmt = stmt.where(
            Job.status == JobStatus.PUBLISHED,
            Company.status
            == CompanyStatus.ACTIVE,  # a suspended employer's postings are taken off the public site
            or_(Job.application_deadline.is_(None), Job.application_deadline >= func.current_date()),
        )
    if company_id is not None:
        stmt = stmt.where(Job.company_id == company_id)
    if hiring_manager_id is not None:
        stmt = stmt.where(Job.hiring_manager_id == hiring_manager_id)
    if f.company_id is not None:
        stmt = stmt.where(Job.company_id == f.company_id)
    if f.statuses:
        stmt = stmt.where(Job.status.in_(f.statuses))
    rank_expr: Any = None
    if f.q and f.q.strip():
        q = f.q.strip()[:200]
        tsq = _tsquery(q)
        # Typo tolerance (trigram similarity of the title) is skipped when the query excludes terms ("engineer -java"):
        # a fuzzy title match would otherwise bring back exactly the postings the user asked to leave out.
        fuzzy = [] if has_exclusion(q) else [Job.title.op("%")(q)]
        stmt = stmt.where(or_(Job.search_tsv.op("@@")(tsq), *fuzzy))
        rank_expr = func.ts_rank_cd(Job.search_tsv, tsq) + 0.4 * func.similarity(Job.title, q)
    if f.skill_ids:
        if f.skills_mode == "all":
            for sid in f.skill_ids:
                stmt = stmt.where(exists().where(JobSkill.job_id == Job.id, JobSkill.skill_id == sid))
        else:
            stmt = stmt.where(exists().where(JobSkill.job_id == Job.id, JobSkill.skill_id.in_(f.skill_ids)))
    if f.location:
        stmt = stmt.where(Job.location.ilike(f"%{escape_like(f.location.strip())}%", escape="\\"))
    if f.department:
        stmt = stmt.where(Job.department.ilike(f"%{escape_like(f.department.strip())}%", escape="\\"))
    if f.employment_types:
        stmt = stmt.where(Job.employment_type.in_(f.employment_types))
    if f.workplace_types:
        stmt = stmt.where(Job.workplace_type.in_(f.workplace_types))
    if f.experience_levels:
        stmt = stmt.where(Job.experience_level.in_(f.experience_levels))
    if f.max_min_experience is not None:
        stmt = stmt.where(Job.min_experience_years <= f.max_min_experience)
    # Salary overlap: the job's [min, max] range intersects the requested range (NULL bounds are open).
    if f.salary_min is not None:
        stmt = stmt.where(
            or_(Job.salary_max.is_(None), Job.salary_max >= f.salary_min),
            or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)),
        )
    if f.salary_max is not None:
        stmt = stmt.where(
            or_(Job.salary_min.is_(None), Job.salary_min <= f.salary_max),
            or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)),
        )
    if f.posted_within_days:
        stmt = stmt.where(Job.published_at >= utcnow() - timedelta(days=f.posted_within_days))

    has_match = candidate_id is not None
    match_col: Any = literal(None)
    if candidate_id is not None:
        stmt = stmt.outerjoin(
            CandidateJobMatch,
            and_(CandidateJobMatch.job_id == Job.id, CandidateJobMatch.candidate_id == candidate_id),
        )
        match_col = CandidateJobMatch.overall_score
        if f.only_saved:
            stmt = stmt.join(SavedJob, and_(SavedJob.job_id == Job.id, SavedJob.candidate_id == candidate_id))
    stmt = stmt.add_columns(match_col.label("match_score"))

    sort = f.sort
    if sort == JobSort.RELEVANCE and rank_expr is None:
        sort = JobSort.NEWEST
    if sort == JobSort.MATCH and not has_match:
        sort = JobSort.NEWEST
    order: list[Any]
    if sort == JobSort.RELEVANCE:
        order = [rank_expr.desc(), Job.published_at.desc().nulls_last()]
    elif sort == JobSort.SALARY_DESC:
        order = [
            func.coalesce(Job.salary_max, Job.salary_min).desc().nulls_last(),
            Job.published_at.desc().nulls_last(),
        ]
    elif sort == JobSort.SALARY_ASC:
        order = [
            func.coalesce(Job.salary_min, Job.salary_max).asc().nulls_last(),
            Job.published_at.desc().nulls_last(),
        ]
    elif sort == JobSort.DEADLINE:
        order = [Job.application_deadline.asc().nulls_last(), Job.published_at.desc().nulls_last()]
    elif sort == JobSort.MATCH:
        order = [match_col.desc().nulls_last(), Job.published_at.desc().nulls_last()]
    elif sort == JobSort.TITLE:
        order = [func.lower(Job.title).asc()]
    else:
        # PUBLISHED rows always have published_at, so plain DESC lets the partial index ix_jobs_published serve the ordering
        # (NULLS LAST would not match the index and forces a sort of every published row — measured 60 ms vs 2.7 ms).
        order = [Job.published_at.desc() if public else Job.updated_at.desc()]
    stmt = stmt.order_by(*order, Job.id)
    return stmt, has_match


class JobSearch:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        f: JobFilters,
        *,
        public: bool,
        page: int,
        page_size: int,
        company_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        hiring_manager_id: uuid.UUID | None = None,
        with_counts: bool = False,
    ) -> tuple[list[JobListItem], int]:
        stmt, _ = build_job_query(
            f,
            public=public,
            company_id=company_id,
            candidate_id=candidate_id,
            hiring_manager_id=hiring_manager_id,
        )
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size, scalars=False)
        if not rows:
            return [], total
        job_ids = [r[0].id for r in rows]
        # Second query (not a join) for skills/company/flags: keeps pagination exact and avoids N+1.
        jobs = {
            j.id: j
            for j in (
                await self.session.execute(
                    select(Job)
                    .where(Job.id.in_(job_ids))
                    .options(selectinload(Job.company), selectinload(Job.skills).selectinload(JobSkill.skill))
                )
            ).scalars()
        }
        saved: set[uuid.UUID] = set()
        applied: set[uuid.UUID] = set()
        if candidate_id is not None:
            saved = {
                r[0]
                for r in (
                    await self.session.execute(
                        select(SavedJob.job_id).where(
                            SavedJob.candidate_id == candidate_id, SavedJob.job_id.in_(job_ids)
                        )
                    )
                ).all()
            }
            applied = {
                r[0]
                for r in (
                    await self.session.execute(
                        select(Application.job_id).where(
                            Application.candidate_id == candidate_id,
                            Application.job_id.in_(job_ids),
                            Application.status != ApplicationStatus.WITHDRAWN,
                        )
                    )
                ).all()
            }
        counts: dict[uuid.UUID, int] = {}
        if with_counts:
            counts = dict(
                (
                    await self.session.execute(
                        select(Application.job_id, func.count())
                        .where(Application.job_id.in_(job_ids))
                        .group_by(Application.job_id)
                    )
                ).all()
            )
        items: list[JobListItem] = []
        for row in rows:
            job = jobs[row[0].id]
            req = [
                js.skill.name
                for js in sorted(job.skills, key=lambda x: x.skill.name.lower())
                if js.requirement == SkillRequirement.REQUIRED
            ]
            items.append(
                JobListItem(
                    id=job.id,
                    title=job.title,
                    company_id=job.company_id,
                    company_name=job.company.name,
                    company_logo_url=job.company.logo_url,
                    department=job.department,
                    location=job.location,
                    employment_type=job.employment_type,
                    workplace_type=job.workplace_type,
                    experience_level=job.experience_level,
                    min_experience_years=job.min_experience_years,
                    salary_min=job.salary_min,
                    salary_max=job.salary_max,
                    salary_currency=job.salary_currency,
                    skills=req[:6],
                    status=job.status,
                    published_at=job.published_at,
                    application_deadline=job.application_deadline,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    is_saved=(job.id in saved) if candidate_id else None,
                    has_applied=(job.id in applied) if candidate_id else None,
                    match_score=float(row.match_score) if row.match_score is not None else None,
                    application_count=counts.get(job.id, 0) if with_counts else None,
                )
            )
        return items, total
