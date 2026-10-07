"""FastAPI dependencies: sessions, authentication, permission checks, rate limiting, pagination."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, RateLimiter, TokenDenylist, get_cache, get_denylist, get_redis
from app.core.config import get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError, RateLimitedError
from app.core.logging import user_id_ctx
from app.core.security import Permission, decode_access_token, has_permission
from app.db.database import session_scope
from app.db.models import User, UserStatus
from app.schemas.common import PageParams
from app.services.tasks import Dispatcher

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False, description="Bearer access token")

SessionDep = Annotated[AsyncSession, Depends(session_scope)]
Pagination = Annotated[PageParams, Depends()]


def get_cache_dep() -> Cache:
    return get_cache()


CacheDep = Annotated[Cache, Depends(get_cache_dep)]


def get_dispatcher(request: Request) -> Dispatcher:
    return request.app.state.dispatcher  # type: ignore[no-any-return]


DispatcherDep = Annotated[Dispatcher, Depends(get_dispatcher)]


async def _load_user(token: str | None, session: AsyncSession, denylist: TokenDenylist) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token)
    if await denylist.is_revoked(payload["jti"]):
        raise AuthenticationError("Token has been revoked", code="TOKEN_REVOKED")
    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise AuthenticationError("Invalid authentication token", code="INVALID_TOKEN") from exc
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AuthenticationError("Invalid authentication token", code="INVALID_TOKEN")
    if user.status != UserStatus.ACTIVE:
        raise AuthenticationError("Account is suspended", code="ACCOUNT_SUSPENDED")
    user_id_ctx.set(str(user.id))
    return user


async def get_current_user(
    session: SessionDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    return await _load_user(token, session, get_denylist())


async def get_optional_user(
    session: SessionDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User | None:
    """Anonymous callers are allowed; a *presented but invalid* token is still an error."""
    if not token:
        return None
    return await _load_user(token, session, get_denylist())


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require(*permissions: Permission) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: the caller's role must grant *all* listed permissions (coarse check; object-level
    authorization is enforced again inside the services)."""

    async def _dep(user: CurrentUser) -> User:
        for p in permissions:
            if not has_permission(user.role, p):
                raise PermissionDeniedError("You do not have permission to perform this action")
        return user

    return _dep


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(
    bucket: str, attempts_attr: str, window_attr: str, *, per_user: bool = False
) -> Callable[[Request], Awaitable[None]]:
    """Fixed-window rate limit keyed by client IP (or by user id when ``per_user`` and authenticated).
    Limits come from settings so tests/deployments can tune them. Fails open when Redis is down."""

    async def _dep(request: Request) -> None:
        settings = get_settings()
        limit = int(getattr(settings, attempts_attr))
        window = int(getattr(settings, window_attr))
        subject = client_ip(request)
        if per_user:
            uid = user_id_ctx.get()
            if uid:
                subject = f"user:{uid}"
        allowed, retry_after = await RateLimiter(get_redis()).hit(f"{bucket}:{subject}", limit, window)
        if not allowed:
            raise RateLimitedError(
                "Too many requests; please slow down", details={"retry_after_seconds": retry_after}
            )

    return _dep


login_limit = rate_limit("login", "login_rate_limit_attempts", "login_rate_limit_window_seconds")
register_limit = rate_limit("register", "register_rate_limit_attempts", "register_rate_limit_window_seconds")
upload_limit = rate_limit("upload", "upload_rate_limit_attempts", "upload_rate_limit_window_seconds", per_user=True)
expensive_limit = rate_limit(
    "expensive", "expensive_rate_limit_attempts", "expensive_rate_limit_window_seconds", per_user=True
)
search_limit = rate_limit("search", "search_rate_limit_attempts", "search_rate_limit_window_seconds", per_user=True)
