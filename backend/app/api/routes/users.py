"""Platform user administration (ADMIN only)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import Pagination, SessionDep, require
from app.core.security import Permission, Role
from app.db.models import User, UserStatus
from app.schemas.auth import UserOut
from app.schemas.common import COMMON_ERRORS, Page
from app.schemas.company import AdminUserCreate, AdminUserUpdate
from app.services.users import UserService

router = APIRouter(prefix="/users", tags=["Users (admin)"], responses=COMMON_ERRORS)

AdminUser = Annotated[User, Depends(require(Permission.MANAGE_USERS))]


@router.get("", response_model=Page[UserOut], summary="List users")
async def list_users(
    admin: AdminUser,
    session: SessionDep,
    p: Pagination,
    q: Annotated[str | None, Query(max_length=100, description="Email or name contains")] = None,
    role: Role | None = None,
    status_: Annotated[UserStatus | None, Query(alias="status")] = None,
    company_id: uuid.UUID | None = None,
) -> Page[UserOut]:
    rows, total = await UserService(session).list(
        q=q, role=role, status=status_, company_id=company_id, page=p.page, page_size=p.page_size
    )
    return Page.build(
        [UserOut.model_validate(u) for u in rows], page=p.page, page_size=p.page_size, total=total
    )


@router.post(
    "", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Create a user with any role"
)
async def create_user(data: AdminUserCreate, admin: AdminUser, session: SessionDep) -> UserOut:
    user = await UserService(session).create(
        admin,
        email=data.email,
        password=data.password,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        role=data.role,
        company_id=data.company_id,
    )
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut, summary="Get a user")
async def get_user(user_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> UserOut:
    return UserOut.model_validate(await UserService(session).get(user_id))


@router.patch("/{user_id}", response_model=UserOut, summary="Update role, status or company of a user")
async def update_user(
    user_id: uuid.UUID, data: AdminUserUpdate, admin: AdminUser, session: SessionDep
) -> UserOut:
    user = await UserService(session).update(admin, user_id, data.model_dump(exclude_unset=True))
    return UserOut.model_validate(user)
