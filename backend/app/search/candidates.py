"""Recruiter candidate search.

Visibility (enforced in the WHERE clause, never in Python): a recruiter sees
  1. registered candidates who opted into the marketplace (``is_searchable``),
  2. candidates who applied to one of the company's jobs,
  3. candidates the company sourced via bulk import.
Contact details are never part of search results.

Ranking: when ``q`` is given, ``ts_rank_cd`` over the weighted ``search_tsv`` (skills/name/headline A, résumé+profile text C)
+ trigram similarity on the name; when ``job_id`` is given, the persisted semantic match score; otherwise recency.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Role
from app.db.models import (
    Application,
    Availability,
    CandidateJobMatch,
    CandidateProfile,
    CandidateSkill,
    CandidateSource,
    Certification,
    Education,
    EducationLevel,
    Job,
    RemotePreference,
    Skill,
    SkillStatus,
    User,
)
from app.matching.scoring import overall_band
from app.schemas.candidate import CandidateListItem
from app.search.jobs import has_exclusion
from app.services.common import escape_like, paginate

EDU_RANK = {lvl: i for i, lvl in enumerate(EducationLevel)}


class CandidateSort(enum.StrEnum):
    RELEVANCE = "relevance"
    MATCH = "match"
    EXPERIENCE = "experience"
    RECENT = "recent"
    NAME = "name"


@dataclass(slots=True)
class CandidateFilters:
    q: str | None = None
    skill_ids: list[uuid.UUID] = field(default_factory=list)
    skills_mode: str = "all"
    min_experience: Decimal | None = None
    max_experience: Decimal | None = None
    location: str | None = None
    min_education: EducationLevel | None = None
    certification: str | None = None
    availability: list[Availability] = field(default_factory=list)
    remote_preference: list[RemotePreference] = field(default_factory=list)
    job_id: uuid.UUID | None = None
    min_match_score: float | None = None
    applicants_only: bool = False
    sort: CandidateSort = CandidateSort.RELEVANCE


def visibility_predicate(user: User) -> Any:
    applied = exists().where(
        Application.candidate_id == CandidateProfile.id,
        Application.job_id == Job.id,
        Job.company_id == user.company_id,
    )
    if user.role == Role.ADMIN:
        return CandidateProfile.id.is_not(None)
    return or_(
        and_(CandidateProfile.source == CandidateSource.SELF, CandidateProfile.is_searchable.is_(True)),
        and_(
            CandidateProfile.source == CandidateSource.IMPORTED,
            CandidateProfile.sourced_by_company_id == user.company_id,
        ),
        applied,
    )


def build_candidate_query(user: User, f: CandidateFilters) -> Select[Any]:
    stmt = select(CandidateProfile).where(visibility_predicate(user))
    match_col: Any = None
    if f.job_id is not None:
        stmt = stmt.outerjoin(
            CandidateJobMatch,
            and_(CandidateJobMatch.job_id == f.job_id, CandidateJobMatch.candidate_id == CandidateProfile.id),
        )
        match_col = CandidateJobMatch.overall_score
        if f.min_match_score is not None:
            stmt = stmt.where(match_col >= f.min_match_score)
    if f.applicants_only and f.job_id is not None:
        stmt = stmt.where(
            exists().where(Application.candidate_id == CandidateProfile.id, Application.job_id == f.job_id)
        )
    rank: Any = None
    if f.q and f.q.strip():
        q = f.q.strip()[:200]
        tsq = func.websearch_to_tsquery("english", q)
        fuzzy = (
            [] if has_exclusion(q) else [CandidateProfile.display_name.op("%")(q)]
        )  # see app.search.jobs.has_exclusion
        stmt = stmt.where(or_(CandidateProfile.search_tsv.op("@@")(tsq), *fuzzy))
        rank = func.ts_rank_cd(CandidateProfile.search_tsv, tsq) + 0.5 * func.similarity(
            CandidateProfile.display_name, q
        )
    if f.skill_ids:

        def has(sid: uuid.UUID) -> Any:
            return exists().where(
                CandidateSkill.candidate_id == CandidateProfile.id,
                CandidateSkill.skill_id == sid,
                CandidateSkill.status != SkillStatus.REJECTED,
            )

        if f.skills_mode == "any":
            stmt = stmt.where(or_(*[has(s) for s in f.skill_ids]))
        else:
            for sid in f.skill_ids:
                stmt = stmt.where(has(sid))
    if f.min_experience is not None:
        stmt = stmt.where(CandidateProfile.years_experience >= f.min_experience)
    if f.max_experience is not None:
        stmt = stmt.where(CandidateProfile.years_experience <= f.max_experience)
    if f.location:
        stmt = stmt.where(
            CandidateProfile.location.ilike(f"%{escape_like(f.location.strip())}%", escape="\\")
        )
    if f.min_education is not None:
        allowed = [lvl for lvl, r in EDU_RANK.items() if r >= EDU_RANK[f.min_education]]
        stmt = stmt.where(
            exists().where(Education.candidate_id == CandidateProfile.id, Education.degree_level.in_(allowed))
        )
    if f.certification:
        stmt = stmt.where(
            exists().where(
                Certification.candidate_id == CandidateProfile.id,
                Certification.name.ilike(f"%{escape_like(f.certification.strip())}%", escape="\\"),
            )
        )
    if f.availability:
        stmt = stmt.where(CandidateProfile.availability.in_(f.availability))
    if f.remote_preference:
        stmt = stmt.where(CandidateProfile.remote_preference.in_(f.remote_preference))

    sort = f.sort
    if sort == CandidateSort.MATCH and match_col is None:
        sort = CandidateSort.RELEVANCE
    if sort == CandidateSort.RELEVANCE and rank is None:
        sort = CandidateSort.MATCH if match_col is not None else CandidateSort.RECENT
    if sort == CandidateSort.RELEVANCE:
        order = [rank.desc(), CandidateProfile.updated_at.desc()]
    elif sort == CandidateSort.MATCH:
        order = [match_col.desc().nulls_last(), CandidateProfile.updated_at.desc()]
    elif sort == CandidateSort.EXPERIENCE:
        order = [CandidateProfile.years_experience.desc().nulls_last(), CandidateProfile.updated_at.desc()]
    elif sort == CandidateSort.NAME:
        order = [func.lower(CandidateProfile.display_name).asc()]
    else:
        order = [CandidateProfile.updated_at.desc()]
    stmt = stmt.add_columns(
        (match_col if match_col is not None else case((CandidateProfile.id.is_(None), 0.0))).label(
            "match_score"
        )
    )
    return stmt.order_by(*order, CandidateProfile.id)


class CandidateSearch:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self, user: User, f: CandidateFilters, *, page: int, page_size: int
    ) -> tuple[list[CandidateListItem], int]:
        stmt = build_candidate_query(user, f)
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size, scalars=False)
        if not rows:
            return [], total
        ids = [r[0].id for r in rows]
        skills: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
        for cid, sid, name in (
            await self.session.execute(
                select(CandidateSkill.candidate_id, Skill.id, Skill.name)
                .join(Skill, Skill.id == CandidateSkill.skill_id)
                .where(CandidateSkill.candidate_id.in_(ids), CandidateSkill.status != SkillStatus.REJECTED)
                .order_by(Skill.name)
            )
        ).all():
            skills.setdefault(cid, []).append((sid, name))
        applied: set[uuid.UUID] = set()
        if f.job_id is not None:
            applied = {
                r[0]
                for r in (
                    await self.session.execute(
                        select(Application.candidate_id).where(
                            Application.job_id == f.job_id, Application.candidate_id.in_(ids)
                        )
                    )
                ).all()
            }
        # Contact-level access for list rows: applicants/sourced are FULL, marketplace rows PROFILE.
        company_applicants: set[uuid.UUID] = set()
        if user.company_id:
            company_applicants = {
                r[0]
                for r in (
                    await self.session.execute(
                        select(Application.candidate_id)
                        .join(Job, Job.id == Application.job_id)
                        .where(Job.company_id == user.company_id, Application.candidate_id.in_(ids))
                    )
                ).all()
            }
        wanted = set(f.skill_ids)
        items: list[CandidateListItem] = []
        for row in rows:
            c = row[0]
            have = skills.get(c.id, [])
            score = float(row.match_score) if row.match_score is not None else None
            access = (
                "FULL"
                if (
                    c.id in company_applicants
                    or c.source == CandidateSource.IMPORTED
                    or user.role == Role.ADMIN
                )
                else "PROFILE"
            )
            items.append(
                CandidateListItem(
                    id=c.id,
                    display_name=c.display_name,
                    headline=c.headline,
                    location=c.location,
                    years_experience=c.years_experience,
                    availability=c.availability,
                    remote_preference=c.remote_preference,
                    source=c.source,
                    access=access,
                    top_skills=[n for _, n in have][:8],
                    skill_matches=[n for sid, n in have if sid in wanted],
                    match_score=score,
                    match_band=overall_band(score) if score is not None else None,
                    has_applied=c.id in applied,
                    updated_at=c.updated_at,
                )
            )
        return items, total
