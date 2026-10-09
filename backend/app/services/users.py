"""User administration and the "who am I" read model."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.security import ROLE_PERMISSIONS, STAFF_ROLES, Role, hash_password
from app.db.models import CandidateProfile, Company, RecruiterProfile, User, UserStatus
from app.schemas.auth import CompanyBrief, MeOut, UserOut
from app.services.auth import AuthService, email_taken
from app.services.common import escape_like, paginate, record_audit


async def build_me(session: AsyncSession, user: User) -> MeOut:
    company = await session.get(Company, user.company_id) if user.company_id else None
    candidate_id = None
    if user.role == Role.CANDIDATE:
        candidate_id = await session.scalar(
            select(CandidateProfile.id).where(CandidateProfile.user_id == user.id)
        )
    is_company_admin = False
    if user.role in STAFF_ROLES:
        is_company_admin = bool(
            await session.scalar(
                select(RecruiterProfile.is_company_admin).where(RecruiterProfile.user_id == user.id)
            )
        )
    return MeOut(
        **UserOut.model_validate(user).model_dump(),
        company=CompanyBrief.model_validate(company) if company else None,
        candidate_id=candidate_id,
        is_company_admin=is_company_admin,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[user.role]),
    )


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        q: str | None,
        role: Role | None,
        status: UserStatus | None,
        company_id: uuid.UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[User], int]:
        stmt = select(User).order_by(User.created_at.desc(), User.id)
        if q:
            like = f"%{escape_like(q.lower())}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.email).like(like),
                    func.lower(User.first_name + " " + User.last_name).like(like),
                )
            )
        if role:
            stmt = stmt.where(User.role == role)
        if status:
            stmt = stmt.where(User.status == status)
        if company_id:
            stmt = stmt.where(User.company_id == company_id)
        return await paginate(self.session, stmt, page=page, page_size=page_size)

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found", code="USER_NOT_FOUND")
        return user

    async def create(
        self,
        actor: User,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: Role,
        phone: str | None = None,
        company_id: uuid.UUID | None = None,
        job_title: str | None = None,
        department: str | None = None,
        is_company_admin: bool = False,
    ) -> User:
        email = email.lower()
        if await email_taken(self.session, email):
            raise ConflictError("An account with this email already exists", code="EMAIL_ALREADY_REGISTERED")
        if role in STAFF_ROLES and company_id is None:
            raise BusinessRuleError(
                "Recruiters and hiring managers must belong to a company", code="COMPANY_REQUIRED"
            )
        if role not in STAFF_ROLES and company_id is not None:
            raise BusinessRuleError(
                "Only recruiters and hiring managers belong to a company", code="COMPANY_NOT_ALLOWED"
            )
        if company_id is not None and await self.session.get(Company, company_id) is None:
            raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
        user = User(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=role,
            company_id=company_id,
        )
        self.session.add(user)
        try:
            await self.session.flush()
            if role in STAFF_ROLES:
                self.session.add(
                    RecruiterProfile(
                        user_id=user.id,
                        job_title=job_title,
                        department=department,
                        is_company_admin=is_company_admin,
                    )
                )
            elif role == Role.CANDIDATE:
                self.session.add(
                    CandidateProfile(
                        user_id=user.id,
                        first_name=first_name,
                        last_name=last_name,
                        display_name=user.full_name,
                    )
                )
            record_audit(
                self.session,
                actor_id=actor.id,
                action="user.created",
                entity_type="user",
                entity_id=user.id,
                company_id=company_id,
                meta={"role": role.value},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "An account with this email already exists", code="EMAIL_ALREADY_REGISTERED"
            ) from exc
        return user

    async def update(self, actor: User, user_id: uuid.UUID, changes: dict[str, Any]) -> User:
        user = await self.get(user_id)
        if user.id == actor.id and (
            changes.get("status") == UserStatus.SUSPENDED or changes.get("role", user.role) != user.role
        ):
            raise BusinessRuleError(
                "You cannot suspend or change the role of your own account", code="SELF_MODIFICATION"
            )
        new_role = changes.get("role", user.role)
        new_company = changes.get("company_id", user.company_id)
        if new_role in STAFF_ROLES and new_company is None:
            raise BusinessRuleError(
                "Recruiters and hiring managers must belong to a company", code="COMPANY_REQUIRED"
            )
        if new_role not in STAFF_ROLES:
            new_company = None
        for field in ("first_name", "last_name", "phone", "status"):
            if field in changes:
                setattr(user, field, changes[field])
        user.role = new_role
        user.company_id = new_company
        if new_role in STAFF_ROLES and await self.session.get(RecruiterProfile, user.id) is None:
            self.session.add(RecruiterProfile(user_id=user.id))
        if changes.get("status") == UserStatus.SUSPENDED:
            await AuthService(self.session).revoke_all_for_user(user.id)
        record_audit(
            self.session,
            actor_id=actor.id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            company_id=user.company_id,
            meta={k: str(v) for k, v in changes.items()},
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise BusinessRuleError("Invalid role/company combination", code="INVALID_ROLE_COMPANY") from exc
        return user
