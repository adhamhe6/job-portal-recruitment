from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import Role
from app.db.models import CompanySize, CompanyStatus, UserStatus
from app.schemas.auth import validate_password_strength
from app.schemas.common import ORMModel, validate_http_url, validate_phone

_url = validate_http_url


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    size: CompanySize | None = None
    logo_url: str | None = Field(default=None, max_length=500)

    _urls = field_validator("website", "logo_url")(_url)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    size: CompanySize | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    status: CompanyStatus | None = Field(default=None, description="Admin only")

    _urls = field_validator("website", "logo_url")(_url)


class CompanyPublic(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    industry: str | None
    website: str | None
    location: str | None
    size: CompanySize | None
    logo_url: str | None


class CompanyOut(CompanyPublic):
    status: CompanyStatus
    created_at: datetime
    updated_at: datetime


class MemberCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    _phone = field_validator("phone")(validate_phone)
    role: Role = Role.RECRUITER
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=100)

    _pw = field_validator("password")(validate_password_strength)

    @field_validator("role")
    @classmethod
    def _staff_only(cls, v: Role) -> Role:
        if v not in (Role.RECRUITER, Role.HIRING_MANAGER):
            raise ValueError("role must be RECRUITER or HIRING_MANAGER")
        return v


class MemberUpdate(BaseModel):
    role: Role | None = None
    status: UserStatus | None = None
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=100)

    @field_validator("role")
    @classmethod
    def _staff_only(cls, v: Role | None) -> Role | None:
        if v is not None and v not in (Role.RECRUITER, Role.HIRING_MANAGER):
            raise ValueError("role must be RECRUITER or HIRING_MANAGER")
        return v


class MemberOut(ORMModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: Role
    status: UserStatus
    job_title: str | None = None
    department: str | None = None
    is_company_admin: bool = False
    last_login_at: datetime | None = None


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    _phone = field_validator("phone")(validate_phone)
    role: Role
    company_id: uuid.UUID | None = None

    _pw = field_validator("password")(validate_password_strength)


class AdminUserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    _phone = field_validator("phone")(validate_phone)
    role: Role | None = None
    status: UserStatus | None = None
    company_id: uuid.UUID | None = None
