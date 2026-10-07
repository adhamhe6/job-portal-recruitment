"""Search: public job search and recruiter candidate search."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.dependencies import CacheDep, OptionalUser, Pagination, SessionDep, require, search_limit
from app.cache.redis_cache import CacheDomain
from app.core.security import Permission, Role
from app.db.models import (
    Availability,
    CandidateProfile,
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    RemotePreference,
    User,
    WorkplaceType,
)
from app.schemas.candidate import CandidateListItem
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.job import JobListItem
from app.search.candidates import CandidateFilters, CandidateSearch, CandidateSort
from app.search.jobs import JobFilters, JobSearch, JobSort
from app.services.skills import SkillService

router = APIRouter(prefix="/search", tags=["Search"], dependencies=[Depends(search_limit)])


async def _resolve_skills(session: SessionDep, skill_ids: list[uuid.UUID] | None, skills: list[str] | None) -> tuple[list[uuid.UUID], bool]:
    """Returns ``(ids, unresolved)``; an unknown skill *name* means nothing can match."""
    ids = list(skill_ids or [])
    unresolved = False
    if skills:
        found = await SkillService(session).find_by_terms(skills)
        for term in skills:
            if term in found:
                ids.append(found[term].id)
            else:
                unresolved = True
    return list(dict.fromkeys(ids)), unresolved


@router.get(
    "/jobs", response_model=Page[JobListItem], summary="Search published jobs",
    description="Public. Keyword search uses PostgreSQL full-text search (title > skills > description) with typo tolerance on the "
    "title; every filter is applied in SQL. Signed-in candidates additionally get `is_saved`, `has_applied` and `match_score`.",
)
async def search_jobs(
    session: SessionDep,
    cache: CacheDep,
    viewer: OptionalUser,
    p: Pagination,
    q: Annotated[str | None, Query(max_length=200, description="Keywords")] = None,
    skill_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    skill: Annotated[list[str] | None, Query(max_length=60, description="Skill names/aliases")] = None,
    skills_mode: Annotated[str, Query(pattern="^(any|all)$")] = "any",
    location: Annotated[str | None, Query(max_length=100)] = None,
    employment_type: Annotated[list[EmploymentType] | None, Query()] = None,
    workplace_type: Annotated[list[WorkplaceType] | None, Query()] = None,
    experience_level: Annotated[list[ExperienceLevel] | None, Query()] = None,
    max_experience: Annotated[Decimal | None, Query(ge=0, le=70, description="Jobs asking for at most this many years")] = None,
    salary_min: Annotated[Decimal | None, Query(ge=0)] = None,
    salary_max: Annotated[Decimal | None, Query(ge=0)] = None,
    company_id: uuid.UUID | None = None,
    posted_within_days: Annotated[int | None, Query(ge=1, le=365)] = None,
    saved_only: bool = False,
    sort: JobSort = JobSort.RELEVANCE,
) -> Page[JobListItem]:
    ids, unresolved = await _resolve_skills(session, skill_id, skill)
    if unresolved and skills_mode == "all":
        return Page.build([], page=p.page, page_size=p.page_size, total=0)
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        from app.core.errors import ValidationFailure

        raise ValidationFailure("salary_min must not exceed salary_max", code="INVALID_SALARY_RANGE")
    filters = JobFilters(
        q=q, skill_ids=ids, skills_mode=skills_mode, location=location, employment_types=employment_type or [], workplace_types=workplace_type or [],
        experience_levels=experience_level or [], max_min_experience=max_experience, salary_min=salary_min, salary_max=salary_max,
        company_id=company_id, posted_within_days=posted_within_days, sort=sort, only_saved=saved_only,
    )
    candidate_id = None
    if viewer is not None and viewer.role == Role.CANDIDATE:
        candidate_id = await session.scalar(select(CandidateProfile.id).where(CandidateProfile.user_id == viewer.id))

    async def compute() -> Page[JobListItem]:
        items, total = await JobSearch(session).run(filters, public=True, page=p.page, page_size=p.page_size, candidate_id=candidate_id)
        return Page.build(items, page=p.page, page_size=p.page_size, total=total)

    if candidate_id is not None:  # personalised → not shared-cacheable
        return await compute()
    params = {**{k: str(getattr(filters, k)) for k in filters.__slots__}, "p": p.page, "s": p.page_size}
    return await cache.get_or_set(
        "search:jobs", [CacheDomain.JOBS], compute, params=params, ttl=60,
        serialize=lambda v: v.model_dump(mode="json"), deserialize=lambda d: Page[JobListItem].model_validate(d),
    )


@router.get(
    "/candidates", response_model=Page[CandidateListItem], summary="Search candidates (recruiters)",
    description="Restricted to candidates visible to your company (marketplace opt-ins, your applicants, your imported candidates). "
    "Pass `job_id` to sort by the semantic match score and filter by `min_match_score`.",
    responses=COMMON_ERRORS,
)
async def search_candidates(
    session: SessionDep,
    user: Annotated[User, Depends(require(Permission.SEARCH_CANDIDATES))],
    p: Pagination,
    q: Annotated[str | None, Query(max_length=200)] = None,
    skill_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    skill: Annotated[list[str] | None, Query(max_length=60)] = None,
    skills_mode: Annotated[str, Query(pattern="^(any|all)$")] = "all",
    min_experience: Annotated[Decimal | None, Query(ge=0, le=70)] = None,
    max_experience: Annotated[Decimal | None, Query(ge=0, le=70)] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    min_education: EducationLevel | None = None,
    certification: Annotated[str | None, Query(max_length=100)] = None,
    availability: Annotated[list[Availability] | None, Query()] = None,
    remote_preference: Annotated[list[RemotePreference] | None, Query()] = None,
    job_id: uuid.UUID | None = None,
    min_match_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    applicants_only: bool = False,
    sort: CandidateSort = CandidateSort.RELEVANCE,
) -> Page[CandidateListItem]:
    if job_id is not None:
        from app.services.access import load_job_for_staff

        await load_job_for_staff(session, user, job_id)
    ids, unresolved = await _resolve_skills(session, skill_id, skill)
    if unresolved and skills_mode == "all":
        return Page.build([], page=p.page, page_size=p.page_size, total=0)
    if min_experience is not None and max_experience is not None and min_experience > max_experience:
        from app.core.errors import ValidationFailure

        raise ValidationFailure("min_experience must not exceed max_experience", code="INVALID_EXPERIENCE_RANGE")
    f = CandidateFilters(
        q=q, skill_ids=ids, skills_mode=skills_mode, min_experience=min_experience, max_experience=max_experience, location=location,
        min_education=min_education, certification=certification, availability=availability or [], remote_preference=remote_preference or [],
        job_id=job_id, min_match_score=min_match_score, applicants_only=applicants_only, sort=sort,
    )
    items, total = await CandidateSearch(session).run(user, f, page=p.page, page_size=p.page_size)
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)
