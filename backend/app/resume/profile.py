"""Merging parser output into candidate records (database side of the résumé subsystem).

Rules that hold everywhere in this module:

* parser output is a **suggestion**: rows created from it carry ``source = RESUME``; skills start as ``SUGGESTED``;
* an existing row is never overwritten, a ``USER`` / ``CONFIRMED`` row is never downgraded, and a ``REJECTED`` skill is
  never resurrected by reprocessing;
* skills are only linked to *existing* taxonomy entries — résumé text never creates new (unverified) skills.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, CacheDomain
from app.db.models import (
    CandidateLanguage,
    CandidateProfile,
    CandidateSkill,
    CandidateSource,
    Certification,
    DataSource,
    Education,
    EducationLevel,
    Experience,
    Job,
    JobStatus,
    LanguageProficiency,
    Skill,
    SkillStatus,
)
from app.matching.service import MatchingService
from app.services.scheduling import schedule_candidate_refresh, schedule_job_match
from app.services.skills import SkillService
from app.services.tasks import Dispatcher

logger = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)
MAX_COMPANY_JOBS_REMATCHED = 50


def norm(text: str | None) -> str:
    return _NON_ALNUM.sub(" ", (text or "").casefold()).strip()


def split_name(full_name: str | None) -> tuple[str, str]:
    """``"Jane van Doe"`` → ``("Jane", "van Doe")``; unknown names get an honest placeholder."""
    parts = (full_name or "").split()
    if not parts:
        return "Unnamed", "candidate"
    if len(parts) == 1:
        return parts[0][:100], "-"
    return parts[0][:100], " ".join(parts[1:])[:100]


def experience_key(title: str | None, company: str | None, start: date | str | None) -> tuple[str, str, str]:
    start_s = start.strftime("%Y-%m") if isinstance(start, date) else (str(start)[:7] if start else "")
    return norm(title), norm(company), start_s


def education_key(institution: str | None, level: str | None) -> tuple[str, str]:
    return norm(institution), level or ""


@dataclass(slots=True)
class ProfileSnapshot:
    """What the candidate already has (to flag/skip duplicates)."""

    skills: dict[uuid.UUID, tuple[SkillStatus, DataSource]] = field(default_factory=dict)
    experiences: set[tuple[str, str, str]] = field(default_factory=set)
    educations: set[tuple[str, str]] = field(default_factory=set)
    certifications: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)


async def load_snapshot(session: AsyncSession, candidate_id: uuid.UUID) -> ProfileSnapshot:
    snap = ProfileSnapshot()
    for sid, status, source in (
        await session.execute(
            select(CandidateSkill.skill_id, CandidateSkill.status, CandidateSkill.source).where(
                CandidateSkill.candidate_id == candidate_id
            )
        )
    ).all():
        snap.skills[sid] = (status, source)
    for e in (
        await session.execute(select(Experience).where(Experience.candidate_id == candidate_id))
    ).scalars():
        snap.experiences.add(experience_key(e.title, e.company_name, e.start_date))
    for ed in (
        await session.execute(select(Education).where(Education.candidate_id == candidate_id))
    ).scalars():
        snap.educations.add(education_key(ed.institution, ed.degree_level.value))
    for c in (
        await session.execute(select(Certification.name).where(Certification.candidate_id == candidate_id))
    ).all():
        snap.certifications.add(norm(c[0]))
    for lang in (
        await session.execute(
            select(CandidateLanguage.language).where(CandidateLanguage.candidate_id == candidate_id)
        )
    ).all():
        snap.languages.add(norm(lang[0]))
    return snap


async def resolve_skills(session: AsyncSession, names: Iterable[str]) -> dict[str, Skill]:
    """Canonical skill names → existing ``Skill`` rows. Unknown names are simply absent (never created)."""
    unique = list(dict.fromkeys(names))
    return await SkillService(session).find_by_terms(unique) if unique else {}


async def merge_skill_suggestions(
    session: AsyncSession, candidate_id: uuid.UUID, suggestions: Iterable[tuple[Skill, float]]
) -> int:
    """Insert ``RESUME`` / ``SUGGESTED`` skills; refresh the confidence of earlier *suggestions* only.

    ``ON CONFLICT`` keeps this race-free and idempotent: reprocessing never duplicates a row, never touches ``USER`` or
    ``CONFIRMED`` rows and never revives a ``REJECTED`` one. Returns the number of rows inserted or refreshed.
    """
    rows = [
        {
            "candidate_id": candidate_id,
            "skill_id": skill.id,
            "source": DataSource.RESUME,
            "status": SkillStatus.SUGGESTED,
            "confidence": Decimal(str(round(min(max(conf, 0.0), 0.99), 2))),
        }
        for skill, conf in suggestions
    ]
    if not rows:
        return 0
    insert = pg_insert(CandidateSkill).values(rows)
    upsert = insert.on_conflict_do_update(
        constraint="uq_candidate_skills_candidate_skill",
        set_={"confidence": insert.excluded.confidence},
        where=(CandidateSkill.source == DataSource.RESUME) & (CandidateSkill.status == SkillStatus.SUGGESTED),
    ).returning(CandidateSkill.id)
    return len((await session.execute(upsert)).all())


async def dismiss_skill_suggestions(
    session: AsyncSession, candidate_id: uuid.UUID, names: Iterable[str]
) -> int:
    """Mark still-unconfirmed ``RESUME`` skill suggestions with these names as ``REJECTED``.

    Used when the candidate removes a skill in the résumé review, so the profile's "suggested from your résumé" list and
    the review agree. Confirmed or user-entered skills are never touched. Returns the number of rows dismissed.
    """
    resolved = await resolve_skills(session, [n for n in names if n])
    if not resolved:
        return 0
    rows = await session.execute(
        update(CandidateSkill)
        .where(
            CandidateSkill.candidate_id == candidate_id,
            CandidateSkill.skill_id.in_([s.id for s in resolved.values()]),
            CandidateSkill.source == DataSource.RESUME,
            CandidateSkill.status == SkillStatus.SUGGESTED,
        )
        .values(status=SkillStatus.REJECTED)
        .returning(CandidateSkill.id)
    )
    return len(rows.all())


# --- structured rows created from suggestions (apply endpoint + bulk import) -------------------------------------------


def as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def build_experience(
    candidate_id: uuid.UUID, item: Mapping[str, Any], today: date
) -> tuple[Experience | None, str | None]:
    """``(row, None)`` or ``(None, reason)`` — rows must satisfy the table's NOT NULL / CHECK rules."""
    title, company = (item.get("title") or "").strip(), (item.get("company") or "").strip()
    start, end = as_date(item.get("start_date")), as_date(item.get("end_date"))
    current = bool(item.get("is_current"))
    missing = [name for name, v in (("title", title), ("company", company), ("start_date", start)) if not v]
    if missing:
        return None, "MISSING_" + "_".join(m.upper() for m in missing)
    assert start is not None
    if start > today:
        return None, "START_IN_FUTURE"
    if current:
        end = None
    elif end is not None and end < start:
        return None, "INVALID_DATES"
    return (
        Experience(
            candidate_id=candidate_id,
            title=title[:200],
            company_name=company[:200],
            location=(item.get("location") or None) and str(item["location"])[:200],
            start_date=start,
            end_date=end,
            is_current=current,
            description=(item.get("description") or None),
            source=DataSource.RESUME,
        ),
        None,
    )


def build_education(candidate_id: uuid.UUID, item: Mapping[str, Any]) -> tuple[Education | None, str | None]:
    institution = (item.get("institution") or "").strip()
    level = item.get("degree_level")
    if not institution:
        return None, "MISSING_INSTITUTION"
    if level not in {lv.value for lv in EducationLevel}:
        return None, "MISSING_DEGREE_LEVEL"
    start_year, end_year = item.get("start_year"), item.get("end_year")
    if isinstance(start_year, int) and isinstance(end_year, int) and end_year < start_year:
        return None, "INVALID_YEARS"
    return (
        Education(
            candidate_id=candidate_id,
            institution=institution[:200],
            degree_level=EducationLevel(level),
            degree=(item.get("degree") or None),
            field_of_study=(item.get("field_of_study") or None),
            start_year=start_year if isinstance(start_year, int) else None,
            end_year=end_year if isinstance(end_year, int) else None,
            source=DataSource.RESUME,
        ),
        None,
    )


def build_certification(
    candidate_id: uuid.UUID, item: Mapping[str, Any]
) -> tuple[Certification | None, str | None]:
    name = (item.get("name") or "").strip()
    if not name:
        return None, "MISSING_NAME"
    return (
        Certification(
            candidate_id=candidate_id,
            name=name[:200],
            issuer=(item.get("issuer") or None) and str(item["issuer"])[:200],
            issued_on=as_date(item.get("issued_on")),
            source=DataSource.RESUME,
        ),
        None,
    )


def build_language(
    candidate_id: uuid.UUID, item: Mapping[str, Any]
) -> tuple[CandidateLanguage | None, str | None]:
    language = (item.get("language") or "").strip()
    proficiency = item.get("proficiency")
    if not language:
        return None, "MISSING_LANGUAGE"
    if proficiency not in {p.value for p in LanguageProficiency}:
        return None, "MISSING_PROFICIENCY"
    return CandidateLanguage(
        candidate_id=candidate_id, language=language[:60], proficiency=LanguageProficiency(proficiency)
    ), None


def years_value(parsed: Mapping[str, Any]) -> Decimal | None:
    yoe = parsed.get("years_of_experience")
    value = yoe.get("value") if isinstance(yoe, Mapping) else yoe
    if isinstance(value, int | float) and 0 <= value <= 70:
        return Decimal(str(round(float(value), 1)))
    return None


# --- refresh after a profile change ---------------------------------------------------------------------------------------


async def schedule_company_job_matches(
    session: AsyncSession,
    dispatcher: Dispatcher | None,
    company_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    """Re-rank a company's live jobs (the only jobs its sourced candidates are eligible for)."""
    job_ids = (
        (
            await session.execute(
                select(Job.id)
                .where(Job.company_id == company_id, Job.status == JobStatus.PUBLISHED)
                .order_by(Job.created_at.desc())
                .limit(MAX_COMPANY_JOBS_REMATCHED)
            )
        )
        .scalars()
        .all()
    )
    for job_id in job_ids:
        await schedule_job_match(session, dispatcher, job_id, user_id=user_id, company_id=company_id)


async def refresh_after_change(
    session: AsyncSession,
    candidate: CandidateProfile,
    *,
    dispatcher: Dispatcher | None,
    cache: Cache | None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Rebuild the search text + embedding now, then queue the match refresh and invalidate caches.

    Registered candidates are re-matched against live jobs. Company-sourced (IMPORTED) candidates are only ever
    eligible for their own company's jobs, so *those* jobs are re-ranked instead.
    """
    await MatchingService(session).refresh_candidate_index(candidate.id)
    if cache is not None:
        await cache.invalidate(CacheDomain.CANDIDATES, CacheDomain.MATCHES)
    if candidate.source == CandidateSource.IMPORTED and candidate.sourced_by_company_id is not None:
        await schedule_company_job_matches(
            session, dispatcher, candidate.sourced_by_company_id, user_id=user_id
        )
    else:
        await schedule_candidate_refresh(session, dispatcher, candidate.id, user_id)
