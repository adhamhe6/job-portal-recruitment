"""Semantic matching: ranked candidates per job (recruiters) and job recommendations (candidates)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencies import CacheDep, DispatcherDep, Pagination, SessionDep, expensive_limit, require
from app.cache.redis_cache import CacheDomain
from app.core.security import Permission
from app.db.models import Availability, EmploymentType, User, WorkplaceType
from app.schemas.common import COMMON_ERRORS, Page, TaskRef
from app.schemas.match import (
    CandidateFacingMatch,
    MatchDetail,
    MatchedCandidate,
    RankedCandidatesMeta,
    RecommendationsMeta,
    RecommendedJob,
)
from app.services.matches import MatchQueryService

matches_router = APIRouter(prefix="/matches", tags=["Matches"], responses=COMMON_ERRORS)
recs_router = APIRouter(prefix="/recommendations", tags=["Recommendations"], responses=COMMON_ERRORS)


class RankedCandidatesPage(Page[MatchedCandidate]):
    meta: RankedCandidatesMeta


class RecommendationsPage(Page[RecommendedJob]):
    meta: RecommendationsMeta


def _svc(session: SessionDep, dispatcher: DispatcherDep, cache: CacheDep) -> MatchQueryService:
    return MatchQueryService(session, dispatcher, cache)


Svc = Annotated[MatchQueryService, Depends(_svc)]
Viewer = Annotated[User, Depends(require(Permission.VIEW_MATCHES))]
Runner = Annotated[User, Depends(require(Permission.RUN_MATCHING))]
Cand = Annotated[User, Depends(require(Permission.VIEW_RECOMMENDATIONS))]


@matches_router.get(
    "/jobs/{job_id}/candidates",
    response_model=RankedCandidatesPage,
    summary="Ranked candidates for a job",
    description="Reads the persisted semantic matches (no model inference on this request). If rows are stale or missing a background "
    "refresh is queued and its id is returned in `meta.computing_task_id`. The score is a ranking aid, not a hiring decision.",
)
async def ranked_candidates(
    job_id: uuid.UUID,
    user: Viewer,
    svc: Svc,
    p: Pagination,
    min_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    min_experience: Annotated[Decimal | None, Query(ge=0, le=70)] = None,
    skill_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    availability: Annotated[list[Availability] | None, Query()] = None,
    applicants_only: bool = False,
) -> RankedCandidatesPage:
    items, total, meta = await svc.ranked_candidates(
        user,
        job_id,
        min_score=min_score,
        min_experience=min_experience,
        skill_ids=skill_id,
        location=location,
        availability=availability,
        applicants_only=applicants_only,
        page=p.page,
        page_size=p.page_size,
    )
    page = Page.build(items, page=p.page, page_size=p.page_size, total=total)
    return RankedCandidatesPage(**page.model_dump(), meta=meta)


@matches_router.post(
    "/jobs/{job_id}/refresh",
    response_model=TaskRef,
    status_code=202,
    summary="Re-run matching for a job (background)",
    dependencies=[Depends(expensive_limit)],
)
async def refresh_job_matches(job_id: uuid.UUID, user: Runner, svc: Svc) -> TaskRef:
    task_id, _ = await svc.refresh_job(user, job_id)
    return TaskRef(task_id=str(task_id))


@matches_router.get(
    "/jobs/{job_id}/candidates/{candidate_id}",
    response_model=MatchDetail,
    summary="Detailed match explanation",
)
async def match_detail(job_id: uuid.UUID, candidate_id: uuid.UUID, user: Viewer, svc: Svc) -> MatchDetail:
    return await svc.detail(user, job_id, candidate_id)


@matches_router.get(
    "/me/jobs/{job_id}", response_model=CandidateFacingMatch, summary="Why does this job fit me? (candidates)"
)
async def my_job_match(job_id: uuid.UUID, user: Cand, svc: Svc) -> CandidateFacingMatch:
    return await svc.my_job_match(user, job_id)


@recs_router.get(
    "/jobs",
    response_model=RecommendationsPage,
    summary="Recommended jobs for me",
    description="Only PUBLISHED, still-open jobs I have not already applied to. Each item carries the real match explanation.",
)
async def recommended_jobs(
    user: Cand,
    svc: Svc,
    cache: CacheDep,
    p: Pagination,
    min_score: Annotated[float, Query(ge=0, le=1)] = 0.0,
    workplace_type: Annotated[list[WorkplaceType] | None, Query()] = None,
    employment_type: Annotated[list[EmploymentType] | None, Query()] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    skill_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^(score|newest)$")] = "score",
) -> RecommendationsPage:
    async def compute() -> RecommendationsPage:
        items, total, meta = await svc.recommendations(
            user,
            min_score=min_score,
            workplace_types=workplace_type,
            employment_types=employment_type,
            location=location,
            skill_ids=skill_id,
            sort=sort,
            page=p.page,
            page_size=p.page_size,
        )
        return RecommendationsPage(
            **Page.build(items, page=p.page, page_size=p.page_size, total=total).model_dump(), meta=meta
        )

    # Cached per candidate+filters; keys embed the matches/jobs/applications namespace versions so any relevant write invalidates them.
    params = {
        "u": str(user.id),
        "m": min_score,
        "w": workplace_type,
        "e": employment_type,
        "l": location,
        "k": [str(s) for s in skill_id or []],
        "s": sort,
        "p": p.page,
        "n": p.page_size,
    }
    result = await cache.get_or_set(
        "recs:jobs",
        [CacheDomain.MATCHES, CacheDomain.JOBS, CacheDomain.APPLICATIONS],
        compute,
        params=params,
        ttl=300,
        serialize=lambda v: v.model_dump(mode="json"),
        deserialize=lambda d: RecommendationsPage.model_validate(d),
    )
    return result


@recs_router.post(
    "/refresh",
    response_model=TaskRef,
    status_code=202,
    summary="Recompute my recommendations (background)",
    dependencies=[Depends(expensive_limit)],
)
async def refresh_recommendations(user: Cand, svc: Svc) -> TaskRef:
    return TaskRef(task_id=str(await svc.refresh_mine(user)))


_ = BaseModel
