"""Authentication: register, login, token refresh/rotation, logout, current user."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import CurrentUser, SessionDep, login_limit, oauth2_scheme, register_limit
from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.logging import request_id_ctx
from app.core.security import decode_access_token
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    RegisterCandidateRequest,
    RegisterEmployerRequest,
    TokenResponse,
    UpdateMeRequest,
)
from app.schemas.common import COMMON_ERRORS, MessageResponse
from app.services.auth import AuthService, IssuedTokens
from app.services.users import build_me

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("app.request")

_REFRESH_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        token,
        max_age=s.refresh_token_expire_days * 86400,
        httponly=True,
        secure=s.refresh_cookie_secure,
        samesite="strict",
        path=_REFRESH_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        s.refresh_cookie_name,
        path=_REFRESH_PATH,
        httponly=True,
        samesite="strict",
        secure=s.refresh_cookie_secure,
    )


async def _token_response(session: SessionDep, issued: IssuedTokens, response: Response) -> TokenResponse:
    _set_refresh_cookie(response, issued.refresh_token)
    return TokenResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=await build_me(session, issued.user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a candidate account",
    dependencies=[Depends(register_limit)],
    responses={409: {"description": "EMAIL_ALREADY_REGISTERED"}},
)
async def register_candidate(
    data: RegisterCandidateRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    svc = AuthService(session)
    user = await svc.register_candidate(data)
    issued = await svc.login(user.email, data.password, user_agent=request.headers.get("user-agent"))
    return await _token_response(session, issued, response)


@router.post(
    "/register/employer",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a recruiter and create their company",
    description="Creates the company and a recruiter account that administers it, atomically.",
    dependencies=[Depends(register_limit)],
    responses={409: {"description": "EMAIL_ALREADY_REGISTERED or COMPANY_NAME_TAKEN"}},
)
async def register_employer(
    data: RegisterEmployerRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    svc = AuthService(session)
    user = await svc.register_employer(data)
    issued = await svc.login(user.email, data.password, user_agent=request.headers.get("user-agent"))
    return await _token_response(session, issued, response)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in with email and password",
    description="Returns a short-lived access token (JSON) and sets an HttpOnly, SameSite=Strict refresh cookie.",
    dependencies=[Depends(login_limit)],
    responses={
        401: {"description": "INVALID_CREDENTIALS / ACCOUNT_SUSPENDED"},
        429: {"description": "RATE_LIMITED"},
    },
)
async def login(
    data: LoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    issued = await AuthService(session).login(
        data.email, data.password, user_agent=request.headers.get("user-agent")
    )
    return await _token_response(session, issued, response)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth2 password flow (used by Swagger's Authorize button)",
    dependencies=[Depends(login_limit)],
)
async def oauth_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    session: SessionDep,
) -> TokenResponse:
    issued = await AuthService(session).login(
        form.username, form.password, user_agent=request.headers.get("user-agent")
    )
    return await _token_response(session, issued, response)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate the refresh token and get a new access token",
    description="Reads the refresh token from the HttpOnly cookie. Each refresh token is single-use; presenting a "
    "used one revokes the whole token family.",
    responses={401: {"description": "INVALID_REFRESH_TOKEN"}},
)
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse | JSONResponse:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    try:
        issued = await AuthService(session).refresh(raw, user_agent=request.headers.get("user-agent"))
    except AuthenticationError as exc:
        logger.warning("authentication failure", extra={"code": exc.code})
        # Headers set on the injected ``response`` are discarded when an exception propagates to the error handler, so the
        # error envelope is built here to be able to expire the dead cookie in the same response.
        failure = JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id_ctx.get(),
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
        _clear_refresh_cookie(failure)
        return failure
    return await _token_response(session, issued, response)


@router.post("/logout", response_model=MessageResponse, summary="Revoke the session")
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> MessageResponse:
    jti, ttl = None, 0
    if token:
        try:
            payload = decode_access_token(token)
            jti = payload["jti"]
            import time

            ttl = max(int(payload["exp"] - time.time()), 0)
        except AuthenticationError:
            pass
    await AuthService(session).logout(request.cookies.get(get_settings().refresh_cookie_name), jti, ttl)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Signed out")


@router.get("/me", response_model=MeOut, summary="Current user", responses=COMMON_ERRORS)
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await build_me(session, user)


@router.patch("/me", response_model=MeOut, summary="Update own account details", responses=COMMON_ERRORS)
async def update_me(data: UpdateMeRequest, user: CurrentUser, session: SessionDep) -> MeOut:
    from app.db.models import CandidateProfile

    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is not None or k == "phone":
            setattr(user, k, v)
    if user.role.value == "CANDIDATE" and ({"first_name", "last_name"} & changes.keys()):
        from sqlalchemy import update

        await session.execute(
            update(CandidateProfile)
            .where(CandidateProfile.user_id == user.id)
            .values(first_name=user.first_name, last_name=user.last_name, display_name=user.full_name)
        )
    await session.commit()
    return await build_me(session, user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password (revokes all sessions)",
    responses=COMMON_ERRORS,
)
async def change_password(
    data: ChangePasswordRequest, user: CurrentUser, session: SessionDep, response: Response
) -> MessageResponse:
    await AuthService(session).change_password(user, data.current_password, data.new_password)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Password updated; please sign in again")
