"""Structured skills taxonomy: canonical skills, aliases (synonyms) and families (for related-skill partial credit)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, UUIDMixin


class Skill(UUIDMixin, Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(100), nullable=False)  # display name, e.g. "PostgreSQL"
    normalized_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)  # loose key, e.g. "postgresql"
    category: Mapped[str | None] = mapped_column(String(50))  # e.g. "Databases"
    # Skills in the same family are interchangeable-ish (MySQL/PostgreSQL, React/Vue): partial match credit.
    family: Mapped[str | None] = mapped_column(String(50))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    aliases: Mapped[list[SkillAlias]] = relationship(
        back_populates="skill", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        Index("ix_skills_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("ix_skills_family", "family"),
    )


class SkillAlias(UUIDMixin, Base):
    __tablename__ = "skill_aliases"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)  # loose key
    display_alias: Mapped[str] = mapped_column(String(100), nullable=False)

    skill: Mapped[Skill] = relationship(back_populates="aliases", lazy="raise")
