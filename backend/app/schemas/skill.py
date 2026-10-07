from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class SkillOut(ORMModel):
    id: uuid.UUID
    name: str
    category: str | None = None
    family: str | None = None
    is_verified: bool = True


class SkillDetail(SkillOut):
    aliases: list[str] = Field(default_factory=list)


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("must not be blank")
        return v


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    family: str | None = Field(default=None, max_length=50)
    is_verified: bool | None = None
    add_aliases: list[str] = Field(default_factory=list, max_length=20)
