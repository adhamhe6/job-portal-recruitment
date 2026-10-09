"""Password hashing (Argon2id), JWT access tokens, opaque refresh tokens and the role → permission matrix.

Object-level authorization (tenant isolation, ownership, assignment) is *not* here — it lives in
``app.services.access`` and is applied by every service. This module only answers "may this role
perform this kind of operation at all?".
"""

from __future__ import annotations

import enum
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()
# A real hash used to equalise timing when the user does not exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


class Role(enum.StrEnum):
    ADMIN = "ADMIN"
    RECRUITER = "RECRUITER"
    HIRING_MANAGER = "HIRING_MANAGER"
    CANDIDATE = "CANDIDATE"


STAFF_ROLES = frozenset({Role.RECRUITER, Role.HIRING_MANAGER})


class Permission(enum.StrEnum):
    MANAGE_USERS = "manage_users"
    MANAGE_COMPANIES = "manage_companies"
    MANAGE_OWN_COMPANY = "manage_own_company"
    CREATE_SKILL = "create_skill"
    MANAGE_SKILLS = "manage_skills"
    MANAGE_JOBS = "manage_jobs"
    VIEW_COMPANY_JOBS = "view_company_jobs"
    SEARCH_CANDIDATES = "search_candidates"
    VIEW_CANDIDATES = "view_candidates"
    MANAGE_APPLICATIONS = "manage_applications"
    REVIEW_APPLICATIONS = "review_applications"
    MANAGE_OWN_PROFILE = "manage_own_profile"
    APPLY_TO_JOBS = "apply_to_jobs"
    UPLOAD_RESUME = "upload_resume"
    IMPORT_RESUMES = "import_resumes"
    SCHEDULE_INTERVIEWS = "schedule_interviews"
    VIEW_INTERVIEWS = "view_interviews"
    PROVIDE_FEEDBACK = "provide_feedback"
    VIEW_MATCHES = "view_matches"
    RUN_MATCHING = "run_matching"
    VIEW_RECOMMENDATIONS = "view_recommendations"
    VIEW_REPORTS = "view_reports"
    VIEW_ADMIN_REPORTS = "view_admin_reports"
    MONITOR_SYSTEM = "monitor_system"


_P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.RECRUITER: frozenset(
        {
            _P.MANAGE_OWN_COMPANY,
            _P.CREATE_SKILL,
            _P.MANAGE_JOBS,
            _P.VIEW_COMPANY_JOBS,
            _P.SEARCH_CANDIDATES,
            _P.VIEW_CANDIDATES,
            _P.MANAGE_APPLICATIONS,
            _P.REVIEW_APPLICATIONS,
            _P.IMPORT_RESUMES,
            _P.SCHEDULE_INTERVIEWS,
            _P.VIEW_INTERVIEWS,
            _P.PROVIDE_FEEDBACK,
            _P.VIEW_MATCHES,
            _P.RUN_MATCHING,
            _P.VIEW_REPORTS,
        }
    ),
    Role.HIRING_MANAGER: frozenset(
        {
            _P.VIEW_COMPANY_JOBS,
            _P.VIEW_CANDIDATES,
            _P.REVIEW_APPLICATIONS,
            _P.VIEW_INTERVIEWS,
            _P.PROVIDE_FEEDBACK,
            _P.VIEW_MATCHES,
            _P.VIEW_REPORTS,
        }
    ),
    Role.CANDIDATE: frozenset(
        {
            _P.CREATE_SKILL,
            _P.MANAGE_OWN_PROFILE,
            _P.APPLY_TO_JOBS,
            _P.UPLOAD_RESUME,
            _P.VIEW_INTERVIEWS,
            _P.VIEW_RECOMMENDATIONS,
        }
    ),
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(Role(role), frozenset())


# --- passwords ----------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time verification; also burns a hash when the user is unknown."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# --- access tokens (JWT) ---------------------------------------------------------------------


def create_access_token(
    subject: uuid.UUID | str, role: str, expires_minutes: int | None = None
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    settings = get_settings()
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=minutes),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # explicit allow-list: blocks alg=none/confusion
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid authentication token", code="INVALID_TOKEN") from exc
    if payload.get("type") != "access":
        raise AuthenticationError("Invalid authentication token", code="INVALID_TOKEN")
    return payload


# --- refresh tokens (opaque, stored hashed) ----------------------------------------------------


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
