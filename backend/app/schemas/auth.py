from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import Role
from app.db.models import CompanySize, UserStatus
from app.schemas.common import ORMModel, validate_http_url, validate_phone


def validate_password_strength(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters long")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters long")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


class _NameFields(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    _phone = field_validator("phone")(validate_phone)


class RegisterCandidateRequest(_NameFields):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "ada@example.com",
                "password": "CorrectHorse42",
                "first_name": "Ada",
                "last_name": "Lovelace",
            }
        }
    )
    email: EmailStr
    password: str

    _pw = field_validator("password")(validate_password_strength)


class RegisterEmployerRequest(_NameFields):
    """Registers a recruiter *and* creates their company in one transaction (the recruiter becomes company admin)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "rita@acme.example",
                "password": "CorrectHorse42",
                "first_name": "Rita",
                "last_name": "Recruiter",
                "company_name": "Acme Robotics",
                "company_industry": "Robotics",
            }
        }
    )
    email: EmailStr
    password: str
    job_title: str | None = Field(default=None, max_length=150)
    company_name: str = Field(min_length=2, max_length=200)
    company_industry: str | None = Field(default=None, max_length=100)
    company_website: str | None = Field(default=None, max_length=500)
    company_location: str | None = Field(default=None, max_length=200)
    company_size: CompanySize | None = None

    _pw = field_validator("password")(validate_password_strength)
    _website = field_validator("company_website")(validate_http_url)

    @field_validator("company_name")
    @classmethod
    def _company_strip(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "recruiter@demo.example", "password": "DemoPass123!"}}
    )
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    _pw = field_validator("new_password")(validate_password_strength)


class UpdateMeRequest(_NameFields):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)  # type: ignore[assignment]
    last_name: str | None = Field(default=None, min_length=1, max_length=100)  # type: ignore[assignment]


class CompanyBrief(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None = None


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    phone: str | None
    role: Role
    status: UserStatus
    company_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime


class MeOut(UserOut):
    """Current user with the context the SPA needs to route and render."""

    company: CompanyBrief | None = None
    candidate_id: uuid.UUID | None = Field(default=None, description="Candidate profile id (CANDIDATE role)")
    is_company_admin: bool = False
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")
    user: MeOut
