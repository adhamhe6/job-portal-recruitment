"""Companies (tenants) and their members."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CacheDep, CurrentUser, Pagination, SessionDep, require
from app.core.errors import PermissionDeniedError
from app.core.security import Permission, Role
from app.db.models import CompanyStatus, User
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.company import (
    CompanyCreate,
    CompanyOut,
    CompanyPublic,
    CompanyUpdate,
    MemberCreate,
    MemberOut,
    MemberUpdate,
)
from app.services.companies import CompanyService

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get(
    "", response_model=Page[CompanyOut], summary="List all companies (admin)", responses=COMMON_ERRORS
)
async def list_companies(
    session: SessionDep,
    p: Pagination,
    _: Annotated[User, Depends(require(Permission.MANAGE_COMPANIES))],
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_: Annotated[CompanyStatus | None, Query(alias="status")] = None,
) -> Page[CompanyOut]:
    rows, total = await CompanyService(session).list(q=q, status=status_, page=p.page, page_size=p.page_size)
    return Page.build(
        [CompanyOut.model_validate(c) for c in rows], page=p.page, page_size=p.page_size, total=total
    )


@router.post(
    "",
    response_model=CompanyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a company (admin)",
    responses=COMMON_ERRORS,
)
async def create_company(
    data: CompanyCreate,
    session: SessionDep,
    admin: Annotated[User, Depends(require(Permission.MANAGE_COMPANIES))],
) -> CompanyOut:
    return CompanyOut.model_validate(await CompanyService(session).create(admin, data))


@router.get("/me", response_model=CompanyOut, summary="The caller's own company", responses=COMMON_ERRORS)
async def my_company(user: CurrentUser, session: SessionDep) -> CompanyOut:
    if user.company_id is None:
        raise PermissionDeniedError("Your account is not attached to a company")
    return CompanyOut.model_validate(await CompanyService(session).get(user.company_id))


@router.get(
    "/{company_id}",
    response_model=CompanyPublic,
    summary="Public company profile",
    description="Only intentionally public fields are returned. No authentication required.",
    responses={404: COMMON_ERRORS[404]},
)
async def get_company(company_id: uuid.UUID, session: SessionDep) -> CompanyPublic:
    return CompanyPublic.model_validate(await CompanyService(session).get(company_id))


@router.patch("/{company_id}", response_model=CompanyOut, summary="Update a company", responses=COMMON_ERRORS)
async def update_company(
    company_id: uuid.UUID, data: CompanyUpdate, user: CurrentUser, session: SessionDep, cache: CacheDep
) -> CompanyOut:
    if user.role not in (Role.ADMIN, Role.RECRUITER):
        raise PermissionDeniedError("You cannot manage companies")
    return CompanyOut.model_validate(await CompanyService(session, cache).update(user, company_id, data))


@router.get(
    "/{company_id}/members", response_model=list[MemberOut], summary="Company staff", responses=COMMON_ERRORS
)
async def list_members(company_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[MemberOut]:
    return await CompanyService(session).list_members(user, company_id)


@router.post(
    "/{company_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a recruiter or hiring manager",
    description="Company administrators create staff accounts directly (no e-mail invitation flow).",
    responses=COMMON_ERRORS,
)
async def add_member(
    company_id: uuid.UUID, data: MemberCreate, user: CurrentUser, session: SessionDep
) -> MemberOut:
    return await CompanyService(session).add_member(user, company_id, data)


@router.patch(
    "/{company_id}/members/{user_id}",
    response_model=MemberOut,
    summary="Update a member",
    responses=COMMON_ERRORS,
)
async def update_member(
    company_id: uuid.UUID, user_id: uuid.UUID, data: MemberUpdate, user: CurrentUser, session: SessionDep
) -> MemberOut:
    return await CompanyService(session).update_member(user, company_id, user_id, data)
