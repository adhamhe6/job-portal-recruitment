"""Skill taxonomy endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CacheDep, CurrentUser, Pagination, SessionDep, require
from app.cache.redis_cache import CacheDomain
from app.core.security import Permission
from app.db.models import User
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.services.skills import SkillService

router = APIRouter(prefix="/skills", tags=["Skills"])


@router.get(
    "",
    response_model=Page[SkillOut],
    summary="Search / autocomplete skills",
    description="Public. Matches names and aliases (`postgres` finds PostgreSQL).",
)
async def list_skills(
    session: SessionDep,
    cache: CacheDep,
    p: Pagination,
    q: Annotated[str | None, Query(max_length=60)] = None,
    category: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[SkillOut]:
    async def compute() -> Page[SkillOut]:
        rows, total = await SkillService(session, cache).search(
            q, page=p.page, page_size=p.page_size, category=category
        )
        return Page.build(
            [SkillOut.model_validate(s) for s in rows], page=p.page, page_size=p.page_size, total=total
        )

    return await cache.get_or_set(
        "skills:list",
        [CacheDomain.SKILLS],
        compute,
        params={"q": q, "c": category, "p": p.page, "s": p.page_size},
        ttl=600,
        serialize=lambda v: v.model_dump(mode="json"),
        deserialize=lambda d: Page[SkillOut].model_validate(d),
    )


@router.post(
    "",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a skill",
    description="New skills start unverified until an admin verifies them. Existing names and aliases are rejected with SKILL_EXISTS.",
    responses=COMMON_ERRORS,
)
async def create_skill(
    data: SkillCreate,
    session: SessionDep,
    cache: CacheDep,
    user: Annotated[User, Depends(require(Permission.CREATE_SKILL))],
) -> SkillOut:
    return SkillOut.model_validate(await SkillService(session, cache).create(data))


@router.get(
    "/{skill_id}",
    response_model=SkillDetail,
    summary="Skill with aliases",
    responses={404: COMMON_ERRORS[404]},
)
async def get_skill(skill_id: uuid.UUID, session: SessionDep) -> SkillDetail:
    return await SkillService(session).detail(skill_id)


@router.patch(
    "/{skill_id}",
    response_model=SkillDetail,
    summary="Edit a skill, verify it, add aliases (admin)",
    responses=COMMON_ERRORS,
)
async def update_skill(
    skill_id: uuid.UUID,
    data: SkillUpdate,
    session: SessionDep,
    cache: CacheDep,
    admin: Annotated[User, Depends(require(Permission.MANAGE_SKILLS))],
) -> SkillDetail:
    return await SkillService(session, cache).update(skill_id, data)


_ = CurrentUser
