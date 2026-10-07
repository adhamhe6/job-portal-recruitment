"""Registration, login, refresh-token rotation, logout and password change."""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import RateLimiter, get_denylist, get_redis
from app.core.config import get_settings
from app.core.errors import AuthenticationError, ConflictError, RateLimitedError
from app.core.security import (
    Role,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)
from app.db.models import (
    CandidateProfile,
    Company,
    RecruiterProfile,
    RefreshToken,
    User,
    UserStatus,
)
from app.schemas.auth import RegisterCandidateRequest, RegisterEmployerRequest
from app.services.common import record_audit, utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "company"


async def unique_company_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)[:200]
    slug, n = base, 1
    while await session.scalar(select(Company.id).where(Company.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


async def email_taken(session: AsyncSession, email: str) -> bool:
    return bool(await session.scalar(select(User.id).where(func.lower(User.email) == email.lower())))


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- registration -----------------------------------------------------------------------------
    async def register_candidate(self, data: RegisterCandidateRequest) -> User:
        email = data.email.lower()
        if await email_taken(self.session, email):
            raise ConflictError("An account with this email already exists", code="EMAIL_ALREADY_REGISTERED")
        user = User(
            email=email,
            password_hash=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            role=Role.CANDIDATE,
        )
        self.session.add(user)
        try:
            await self.session.flush()
            self.session.add(
                CandidateProfile(
                    user_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    display_name=user.full_name,
                    contact_email=None,
                    contact_phone=None,
                )
            )
            record_audit(self.session, actor_id=user.id, action="user.registered", entity_type="user", entity_id=user.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("An account with this email already exists", code="EMAIL_ALREADY_REGISTERED") from exc
        return user

    async def register_employer(self, data: RegisterEmployerRequest) -> User:
        email = data.email.lower()
        if await email_taken(self.session, email):
            raise ConflictError("An account with this email already exists", code="EMAIL_ALREADY_REGISTERED")
        if await self.session.scalar(select(Company.id).where(func.lower(Company.name) == data.company_name.lower())):
            raise ConflictError("A company with this name already exists", code="COMPANY_NAME_TAKEN")
        try:
            company = Company(
                name=data.company_name,
                slug=await unique_company_slug(self.session, data.company_name),
                industry=data.company_industry,
                website=data.company_website,
                location=data.company_location,
                size=data.company_size,
            )
            self.session.add(company)
            await self.session.flush()
            user = User(
                email=email,
                password_hash=hash_password(data.password),
                first_name=data.first_name,
                last_name=data.last_name,
                phone=data.phone,
                role=Role.RECRUITER,
                company_id=company.id,
            )
            self.session.add(user)
            await self.session.flush()
            self.session.add(RecruiterProfile(user_id=user.id, job_title=data.job_title, is_company_admin=True))
            record_audit(
                self.session,
                actor_id=user.id,
                action="company.created",
                entity_type="company",
                entity_id=company.id,
                company_id=company.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Email or company name already in use", code="EMAIL_ALREADY_REGISTERED") from exc
        return user

    # --- login / refresh / logout --------------------------------------------------------------------
    async def login(self, email: str, password: str, *, user_agent: str | None = None) -> IssuedTokens:
        settings = get_settings()
        limiter = RateLimiter(get_redis())
        bucket = f"loginfail:{email.lower()}"
        wait = await limiter.retry_after(bucket, settings.login_rate_limit_attempts)
        if wait:
            raise RateLimitedError(
                "Too many failed sign-in attempts; try again later", details={"retry_after_seconds": wait}
            )
        user = (
            await self.session.execute(select(User).where(func.lower(User.email) == email.lower()))
        ).scalar_one_or_none()
        # Always verify (against a dummy hash for unknown emails) so response time does not reveal account existence.
        ok = verify_password(password, user.password_hash if user else None)
        if not ok or user is None:
            await limiter.hit(bucket, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)
            logger.warning("login failed", extra={"reason": "bad_credentials"})
            raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")
        if user.status != UserStatus.ACTIVE:
            logger.warning("login blocked", extra={"reason": "suspended", "user_id": str(user.id)})
            raise AuthenticationError("This account has been suspended", code="ACCOUNT_SUSPENDED")
        await limiter.reset(bucket)
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        tokens = await self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        await self.session.commit()
        return tokens

    async def _issue(self, user: User, *, family_id: uuid.UUID, user_agent: str | None) -> IssuedTokens:
        settings = get_settings()
        access, expires_in = create_access_token(user.id, user.role.value)
        raw = generate_refresh_token()
        self.session.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=hash_refresh_token(raw),
                user_agent=(user_agent or "")[:255] or None,
                expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
            )
        )
        return IssuedTokens(access_token=access, expires_in=expires_in, refresh_token=raw, user=user)

    async def refresh(self, raw_token: str | None, *, user_agent: str | None = None) -> IssuedTokens:
        if not raw_token:
            raise AuthenticationError("Missing refresh token", code="INVALID_REFRESH_TOKEN")
        token = (
            await self.session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).with_for_update()
            )
        ).scalar_one_or_none()
        if token is None:
            raise AuthenticationError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")
        if token.revoked_at is not None:
            # A rotated token was presented again: the chain may be stolen. Revoke the whole family.
            await self._revoke_family(token.family_id)
            await self.session.commit()
            logger.warning("refresh token reuse detected", extra={"user_id": str(token.user_id)})
            raise AuthenticationError("Refresh token has been revoked", code="INVALID_REFRESH_TOKEN")
        if token.expires_at <= utcnow():
            raise AuthenticationError("Refresh token has expired", code="INVALID_REFRESH_TOKEN")
        user = await self.session.get(User, token.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise AuthenticationError("Account is not active", code="ACCOUNT_SUSPENDED")
        token.revoked_at = utcnow()
        tokens = await self._issue(user, family_id=token.family_id, user_agent=user_agent)
        await self.session.commit()
        return tokens

    async def logout(self, raw_refresh: str | None, access_jti: str | None = None, access_exp_seconds: int = 0) -> None:
        if raw_refresh:
            token = (
                await self.session.execute(
                    select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
                )
            ).scalar_one_or_none()
            if token is not None:
                await self._revoke_family(token.family_id)
                await self.session.commit()
        if access_jti:
            await get_denylist().revoke(access_jti, access_exp_seconds)

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )

    async def change_password(self, user: User, current: str, new: str) -> None:
        if not verify_password(current, user.password_hash):
            raise AuthenticationError("Current password is incorrect", code="INVALID_CREDENTIALS")
        user.password_hash = hash_password(new)
        await self.revoke_all_for_user(user.id)
        record_audit(self.session, actor_id=user.id, action="user.password_changed", entity_type="user", entity_id=user.id)
        await self.session.commit()
