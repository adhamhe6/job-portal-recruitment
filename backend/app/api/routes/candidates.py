"""Candidate self-service (profile, experience, education, skills …) and the recruiter-facing candidate view."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import CacheDep, DispatcherDep, Pagination, SessionDep, require
from app.core.security import Permission
from app.db.models import User
from app.schemas.candidate import (
    CandidateProfileOut,
    CandidateSkillIn,
    CandidateSkillOut,
    CandidateSkillUpdate,
    CandidateView,
    CertificationIn,
    CertificationOut,
    EducationIn,
    EducationOut,
    ExperienceIn,
    ExperienceOut,
    LanguageIn,
    LanguageOut,
    ProfileCompletion,
    ProfileUpdate,
)
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.job import JobListItem
from app.services.candidates import CandidateService

router = APIRouter(prefix="/candidates", tags=["Candidates"], responses=COMMON_ERRORS)

Me = Annotated[User, Depends(require(Permission.MANAGE_OWN_PROFILE))]
Staff = Annotated[User, Depends(require(Permission.VIEW_CANDIDATES))]


def _svc(session: SessionDep, dispatcher: DispatcherDep, cache: CacheDep) -> CandidateService:
    return CandidateService(session, dispatcher, cache)


Svc = Annotated[CandidateService, Depends(_svc)]


@router.get("/me", response_model=CandidateProfileOut, summary="My profile (with completion)")
async def get_my_profile(user: Me, svc: Svc) -> CandidateProfileOut:
    return await svc.own_profile(user)


@router.patch("/me", response_model=CandidateProfileOut, summary="Update my profile (partial)")
async def update_my_profile(data: ProfileUpdate, user: Me, svc: Svc) -> CandidateProfileOut:
    return await svc.update_profile(user, data)


@router.get("/me/completion", response_model=ProfileCompletion, summary="Profile completion and what is missing")
async def my_completion(user: Me, svc: Svc) -> ProfileCompletion:
    return (await svc.own_profile(user)).completion


@router.post("/me/experiences", response_model=ExperienceOut, status_code=status.HTTP_201_CREATED, summary="Add work experience")
async def add_experience(data: ExperienceIn, user: Me, svc: Svc) -> ExperienceOut:
    return await svc.add_experience(user, data)


@router.put("/me/experiences/{item_id}", response_model=ExperienceOut, summary="Replace a work-experience entry")
async def update_experience(item_id: uuid.UUID, data: ExperienceIn, user: Me, svc: Svc) -> ExperienceOut:
    return await svc.update_experience(user, item_id, data)


@router.delete("/me/experiences/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a work-experience entry")
async def delete_experience(item_id: uuid.UUID, user: Me, svc: Svc) -> Response:
    await svc.delete_experience(user, item_id)
    return Response(status_code=204)


@router.post("/me/educations", response_model=EducationOut, status_code=status.HTTP_201_CREATED, summary="Add education")
async def add_education(data: EducationIn, user: Me, svc: Svc) -> EducationOut:
    return await svc.add_education(user, data)


@router.put("/me/educations/{item_id}", response_model=EducationOut, summary="Replace an education entry")
async def update_education(item_id: uuid.UUID, data: EducationIn, user: Me, svc: Svc) -> EducationOut:
    return await svc.update_education(user, item_id, data)


@router.delete("/me/educations/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an education entry")
async def delete_education(item_id: uuid.UUID, user: Me, svc: Svc) -> Response:
    await svc.delete_education(user, item_id)
    return Response(status_code=204)


@router.post("/me/certifications", response_model=CertificationOut, status_code=status.HTTP_201_CREATED, summary="Add a certification")
async def add_certification(data: CertificationIn, user: Me, svc: Svc) -> CertificationOut:
    return await svc.add_certification(user, data)


@router.put("/me/certifications/{item_id}", response_model=CertificationOut, summary="Replace a certification")
async def update_certification(item_id: uuid.UUID, data: CertificationIn, user: Me, svc: Svc) -> CertificationOut:
    return await svc.update_certification(user, item_id, data)


@router.delete("/me/certifications/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a certification")
async def delete_certification(item_id: uuid.UUID, user: Me, svc: Svc) -> Response:
    await svc.delete_certification(user, item_id)
    return Response(status_code=204)


@router.post("/me/languages", response_model=LanguageOut, status_code=status.HTTP_201_CREATED, summary="Add a language")
async def add_language(data: LanguageIn, user: Me, svc: Svc) -> LanguageOut:
    return await svc.add_language(user, data)


@router.delete("/me/languages/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a language")
async def delete_language(item_id: uuid.UUID, user: Me, svc: Svc) -> Response:
    await svc.delete_language(user, item_id)
    return Response(status_code=204)


@router.post(
    "/me/skills", response_model=CandidateSkillOut, status_code=status.HTTP_201_CREATED, summary="Add a skill to my profile",
    description="Reference a skill by `skill_id` or by `name` (aliases such as 'Postgres' resolve to the canonical skill).",
)
async def add_skill(data: CandidateSkillIn, user: Me, svc: Svc) -> CandidateSkillOut:
    return await svc.add_skill(user, data)


@router.patch(
    "/me/skills/{item_id}", response_model=CandidateSkillOut, summary="Update proficiency / confirm or reject a résumé-suggested skill"
)
async def update_skill(item_id: uuid.UUID, data: CandidateSkillUpdate, user: Me, svc: Svc) -> CandidateSkillOut:
    return await svc.update_skill(user, item_id, data)


@router.delete("/me/skills/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a skill")
async def remove_skill(item_id: uuid.UUID, user: Me, svc: Svc) -> Response:
    await svc.remove_skill(user, item_id)
    return Response(status_code=204)


@router.get("/me/saved-jobs", response_model=Page[JobListItem], summary="Jobs I saved")
async def my_saved_jobs(
    user: Annotated[User, Depends(require(Permission.APPLY_TO_JOBS))], session: SessionDep, p: Pagination
) -> Page[JobListItem]:
    from sqlalchemy import select

    from app.db.models import CandidateProfile
    from app.search.jobs import JobFilters, JobSearch

    cid = await session.scalar(select(CandidateProfile.id).where(CandidateProfile.user_id == user.id))
    items, total = await JobSearch(session).run(JobFilters(only_saved=True), public=True, page=p.page, page_size=p.page_size, candidate_id=cid)
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.get(
    "/{candidate_id}", response_model=CandidateView, summary="Candidate profile as seen by hiring staff",
    description="Contact details and résumé files are only included for applicants to your company and candidates you sourced "
    "(`access = FULL`); marketplace candidates are returned with `access = PROFILE`. Pass `job_id` to include the match explanation.",
)
async def get_candidate(
    candidate_id: uuid.UUID, user: Staff, svc: Svc, job_id: Annotated[uuid.UUID | None, Query()] = None
) -> CandidateView:
    return await svc.staff_view(user, candidate_id, job_id=job_id)
