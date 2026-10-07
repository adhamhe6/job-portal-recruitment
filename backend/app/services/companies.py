"""Company profile and membership management (tenant administration)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import STAFF_ROLES, Role
from app.db.models import Company, CompanyStatus, RecruiterProfile, User, UserStatus
from app.schemas.company import CompanyCreate, CompanyUpdate, MemberCreate, MemberOut, MemberUpdate
from app.services.access import is_admin
from app.services.auth import AuthService, unique_company_slug
from app.services.common import escape_like, paginate, record_audit
from app.services.users import UserService


class CompanyService:
    def __init__(self, session: AsyncSession, cache: Cache | None = None) -> None:
        self.session = session
        self.cache = cache

    async def get(self, company_id: uuid.UUID) -> Company:
        company = await self.session.get(Company, company_id)
        if company is None:
            raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
        return company

    async def list(self, *, q: str | None, status: CompanyStatus | None, page: int, page_size: int) -> tuple[list[Company], int]:
        stmt = select(Company).order_by(Company.name)
        if q:
            stmt = stmt.where(func.lower(Company.name).like(f"%{escape_like(q.lower())}%"))
        if status:
            stmt = stmt.where(Company.status == status)
        return await paginate(self.session, stmt, page=page, page_size=page_size)

    async def create(self, actor: User, data: CompanyCreate) -> Company:
        if await self.session.scalar(select(Company.id).where(func.lower(Company.name) == data.name.lower())):
            raise ConflictError("A company with this name already exists", code="COMPANY_NAME_TAKEN")
        company = Company(**data.model_dump(), slug=await unique_company_slug(self.session, data.name))
        self.session.add(company)
        await self.session.flush()
        record_audit(
            self.session, actor_id=actor.id, action="company.created", entity_type="company", entity_id=company.id, company_id=company.id
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A company with this name already exists", code="COMPANY_NAME_TAKEN") from exc
        return company

    async def _require_company_admin(self, actor: User, company_id: uuid.UUID) -> None:
        if is_admin(actor):
            return
        if actor.company_id != company_id or actor.role != Role.RECRUITER:
            raise PermissionDeniedError("You cannot manage this company")
        flag = await self.session.scalar(select(RecruiterProfile.is_company_admin).where(RecruiterProfile.user_id == actor.id))
        if not flag:
            raise PermissionDeniedError("Only company administrators can do this")

    async def update(self, actor: User, company_id: uuid.UUID, data: CompanyUpdate) -> Company:
        company = await self.get(company_id)
        if not is_admin(actor) and actor.company_id != company_id:
            raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
        await self._require_company_admin(actor, company_id)
        changes: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "status" in changes and not is_admin(actor):
            raise PermissionDeniedError("Only platform administrators can change company status")
        if "name" in changes and changes["name"] is None:
            changes.pop("name")
        if "name" in changes and changes["name"].lower() != company.name.lower():
            if await self.session.scalar(select(Company.id).where(func.lower(Company.name) == changes["name"].lower())):
                raise ConflictError("A company with this name already exists", code="COMPANY_NAME_TAKEN")
        for k, v in changes.items():
            setattr(company, k, v)
        record_audit(
            self.session, actor_id=actor.id, action="company.updated", entity_type="company", entity_id=company.id, company_id=company.id
        )
        await self.session.commit()
        if self.cache:  # company name/logo/status are part of cached job lists, searches and recommendations
            await self.cache.invalidate(CacheDomain.JOBS, CacheDomain.MATCHES)
        return company

    # --- members -------------------------------------------------------------------------------------
    async def list_members(self, actor: User, company_id: uuid.UUID) -> list[MemberOut]:
        if not is_admin(actor) and (actor.company_id != company_id or actor.role not in STAFF_ROLES):
            raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
        rows = (
            await self.session.execute(
                select(User, RecruiterProfile)
                .outerjoin(RecruiterProfile, RecruiterProfile.user_id == User.id)
                .where(User.company_id == company_id)
                .order_by(User.last_name, User.first_name)
            )
        ).all()
        return [self._member_out(u, p) for u, p in rows]

    @staticmethod
    def _member_out(user: User, profile: RecruiterProfile | None) -> MemberOut:
        return MemberOut(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role,
            status=user.status,
            job_title=profile.job_title if profile else None,
            department=profile.department if profile else None,
            is_company_admin=bool(profile and profile.is_company_admin),
            last_login_at=user.last_login_at,
        )

    async def add_member(self, actor: User, company_id: uuid.UUID, data: MemberCreate) -> MemberOut:
        await self.get(company_id)
        await self._require_company_admin(actor, company_id)
        user = await UserService(self.session).create(
            actor,
            email=data.email,
            password=data.password,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            role=data.role,
            company_id=company_id,
            job_title=data.job_title,
            department=data.department,
        )
        profile = await self.session.get(RecruiterProfile, user.id)
        return self._member_out(user, profile)

    async def update_member(self, actor: User, company_id: uuid.UUID, user_id: uuid.UUID, data: MemberUpdate) -> MemberOut:
        await self._require_company_admin(actor, company_id)
        user = await self.session.get(User, user_id)
        if user is None or user.company_id != company_id:
            raise NotFoundError("Member not found", code="MEMBER_NOT_FOUND")
        profile = await self.session.get(RecruiterProfile, user.id)
        if profile is None:
            profile = RecruiterProfile(user_id=user.id)
            self.session.add(profile)
        if user.id == actor.id and (data.status == UserStatus.SUSPENDED or (data.role and data.role != user.role)):
            raise BusinessRuleError("You cannot suspend or change the role of your own account", code="SELF_MODIFICATION")
        if data.role:
            user.role = data.role
        if data.status:
            user.status = data.status
            if data.status == UserStatus.SUSPENDED:
                await AuthService(self.session).revoke_all_for_user(user.id)
        if data.job_title is not None:
            profile.job_title = data.job_title
        if data.department is not None:
            profile.department = data.department
        record_audit(
            self.session, actor_id=actor.id, action="member.updated", entity_type="user", entity_id=user.id, company_id=company_id
        )
        await self.session.commit()
        return self._member_out(user, profile)
