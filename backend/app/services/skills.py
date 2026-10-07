"""Skill taxonomy: lookup by loose key/alias, find-or-create, autocomplete."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.db.models import Skill, SkillAlias
from app.matching.skills import ONTOLOGY, skill_key
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.services.common import escape_like, paginate


class SkillService:
    def __init__(self, session: AsyncSession, cache: Cache | None = None) -> None:
        self.session = session
        self.cache = cache

    async def _invalidate(self) -> None:
        if self.cache:
            await self.cache.invalidate(CacheDomain.SKILLS)

    async def find_by_term(self, term: str) -> Skill | None:
        """Resolve a free-text term (name, alias, spelling variant) to a canonical skill."""
        key = skill_key(term)
        if not key:
            return None
        skill = (await self.session.execute(select(Skill).where(Skill.normalized_name == key))).scalar_one_or_none()
        if skill:
            return skill
        return (
            await self.session.execute(select(Skill).join(SkillAlias, SkillAlias.skill_id == Skill.id).where(SkillAlias.alias == key))
        ).scalar_one_or_none()

    async def find_by_terms(self, terms: Iterable[str]) -> dict[str, Skill]:
        """Batch resolution: returns ``{input term: Skill}`` for terms that resolve."""
        keyed = {t: skill_key(t) for t in terms if skill_key(t)}
        if not keyed:
            return {}
        keys = set(keyed.values())
        direct = {s.normalized_name: s for s in (await self.session.execute(select(Skill).where(Skill.normalized_name.in_(keys)))).scalars()}
        via_alias = {
            a.alias: s
            for a, s in (
                await self.session.execute(
                    select(SkillAlias, Skill).join(Skill, Skill.id == SkillAlias.skill_id).where(SkillAlias.alias.in_(keys))
                )
            ).all()
        }
        out: dict[str, Skill] = {}
        for term, key in keyed.items():
            if key in direct:
                out[term] = direct[key]
            elif key in via_alias:
                out[term] = via_alias[key]
        return out

    async def get_or_create(self, name: str, *, category: str | None = None, verified: bool = False) -> Skill:
        existing = await self.find_by_term(name)
        if existing:
            return existing
        clean = " ".join(name.split())
        key = skill_key(clean)
        if not key or len(key) > 100:
            raise ValidationFailure("Invalid skill name", code="INVALID_SKILL")
        skill = Skill(name=clean, normalized_name=key, category=category, is_verified=verified)
        self.session.add(skill)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            again = await self.find_by_term(name)
            if again:
                return again
            raise
        await self._invalidate()
        return skill

    async def search(self, q: str | None, *, page: int, page_size: int, category: str | None = None) -> tuple[list[Skill], int]:
        stmt = select(Skill).order_by(Skill.name)
        if q:
            like = f"%{escape_like(q.strip().lower())}%"
            key_like = f"%{escape_like(skill_key(q))}%"
            alias_skill_ids = select(SkillAlias.skill_id).where(SkillAlias.alias.like(key_like))
            stmt = stmt.where(or_(func.lower(Skill.name).like(like), Skill.normalized_name.like(key_like), Skill.id.in_(alias_skill_ids)))
            # Prefix matches first, then alphabetical.
            stmt = stmt.order_by(None).order_by((func.lower(Skill.name).like(f"{escape_like(q.strip().lower())}%")).desc(), Skill.name)
        if category:
            stmt = stmt.where(Skill.category == category)
        return await paginate(self.session, stmt, page=page, page_size=page_size)

    async def create(self, data: SkillCreate) -> Skill:
        if await self.find_by_term(data.name):
            raise ConflictError("This skill already exists (possibly under an alias)", code="SKILL_EXISTS")
        skill = await self.get_or_create(data.name, category=data.category, verified=False)
        await self.session.commit()
        return skill

    async def detail(self, skill_id: uuid.UUID) -> SkillDetail:
        skill = await self.session.get(Skill, skill_id)
        if skill is None:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND")
        aliases = (await self.session.execute(select(SkillAlias.display_alias).where(SkillAlias.skill_id == skill_id))).scalars().all()
        return SkillDetail(**SkillOut.model_validate(skill).model_dump(), aliases=sorted(aliases))

    async def update(self, skill_id: uuid.UUID, data: SkillUpdate) -> SkillDetail:
        skill = await self.session.get(Skill, skill_id)
        if skill is None:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND")
        changes = data.model_dump(exclude_unset=True, exclude={"add_aliases"})
        if "name" in changes and changes["name"]:
            key = skill_key(changes["name"])
            other = await self.find_by_term(changes["name"])
            if other and other.id != skill.id:
                raise ConflictError("Another skill already uses this name", code="SKILL_EXISTS")
            skill.name, skill.normalized_name = " ".join(changes.pop("name").split()), key
        for k, v in changes.items():
            setattr(skill, k, v)
        for alias in data.add_aliases:
            key = skill_key(alias)
            other = await self.find_by_term(alias)
            if other and other.id != skill.id:
                raise ConflictError(f"'{alias}' already refers to {other.name}", code="SKILL_EXISTS")
            if key and key != skill.normalized_name and not other:
                self.session.add(SkillAlias(skill_id=skill.id, alias=key, display_alias=" ".join(alias.split())))
        await self.session.commit()
        await self._invalidate()
        return await self.detail(skill_id)


async def seed_ontology(session: AsyncSession) -> int:
    """Idempotently insert the built-in skills + aliases. Returns the number of new skills."""
    existing = {k for (k,) in (await session.execute(select(Skill.normalized_name))).all()}
    existing_aliases = {a for (a,) in (await session.execute(select(SkillAlias.alias))).all()}
    created = 0
    for o in ONTOLOGY:
        if o.key in existing:
            skill = (await session.execute(select(Skill).where(Skill.normalized_name == o.key))).scalar_one()
        else:
            skill = Skill(name=o.name, normalized_name=o.key, category=o.category, family=o.family, is_verified=True)
            session.add(skill)
            await session.flush()
            created += 1
        for alias in o.aliases:
            ak = skill_key(alias)
            if ak and ak != o.key and ak not in existing_aliases and ak not in existing:
                session.add(SkillAlias(skill_id=skill.id, alias=ak, display_alias=alias))
                existing_aliases.add(ak)
    await session.commit()
    return created
