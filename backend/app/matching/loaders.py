"""Load matching features from the database in batches (no per-row queries)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CandidateProfile,
    CandidateSkill,
    Certification,
    Education,
    Experience,
    Job,
    JobSkill,
    Resume,
    ResumeProcessingResult,
    ResumeStatus,
    Skill,
    SkillRequirement,
    SkillStatus,
)
from app.matching.representation import (
    MAX_RESUME_EXCERPT_CHARS,
    CandidateFeatures,
    ExperienceItem,
    JobFeatures,
    SkillRef,
    clean,
)


async def load_job_features(
    session: AsyncSession, job_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, JobFeatures]:
    ids = list(job_ids)
    if not ids:
        return {}
    jobs = {j.id: j for j in (await session.execute(select(Job).where(Job.id.in_(ids)))).scalars()}
    skills_by_job: dict[uuid.UUID, list[tuple[JobSkill, Skill]]] = {}
    rows = (
        await session.execute(
            select(JobSkill, Skill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id.in_(ids))
            .order_by(Skill.name)
        )
    ).all()
    for js, sk in rows:
        skills_by_job.setdefault(js.job_id, []).append((js, sk))
    out: dict[uuid.UUID, JobFeatures] = {}
    for jid, j in jobs.items():
        req: list[SkillRef] = []
        pref: list[SkillRef] = []
        for js, sk in skills_by_job.get(jid, []):
            ref = SkillRef(
                str(sk.id), sk.name, sk.family, float(js.min_years) if js.min_years is not None else None
            )
            (req if js.requirement == SkillRequirement.REQUIRED else pref).append(ref)
        out[jid] = JobFeatures(
            job_id=str(jid),
            title=j.title,
            company_id=str(j.company_id),
            summary=clean(j.description),
            responsibilities=clean(j.responsibilities),
            qualifications=clean(j.qualifications),
            required=req,
            preferred=pref,
            min_experience_years=float(j.min_experience_years or 0),
            max_experience_years=float(j.max_experience_years)
            if j.max_experience_years is not None
            else None,
            experience_level=j.experience_level.value if j.experience_level else None,
            min_education_level=j.min_education_level.value if j.min_education_level else None,
            location=j.location,
            workplace_type=j.workplace_type.value,
            employment_type=j.employment_type.value,
        )
    return out


async def load_candidate_features(
    session: AsyncSession, candidate_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, CandidateFeatures]:
    ids = list(candidate_ids)
    if not ids:
        return {}
    profiles = {
        p.id: p
        for p in (
            await session.execute(select(CandidateProfile).where(CandidateProfile.id.in_(ids)))
        ).scalars()
    }

    skills: dict[uuid.UUID, list[SkillRef]] = {}
    for cs, sk in (
        await session.execute(
            select(CandidateSkill, Skill)
            .join(Skill, Skill.id == CandidateSkill.skill_id)
            .where(CandidateSkill.candidate_id.in_(ids), CandidateSkill.status != SkillStatus.REJECTED)
            .order_by(Skill.name)
        )
    ).all():
        skills.setdefault(cs.candidate_id, []).append(
            SkillRef(
                str(sk.id),
                sk.name,
                sk.family,
                float(cs.years_experience) if cs.years_experience is not None else None,
                cs.source.value,
            )
        )

    experiences: dict[uuid.UUID, list[ExperienceItem]] = {}
    for e in (await session.execute(select(Experience).where(Experience.candidate_id.in_(ids)))).scalars():
        experiences.setdefault(e.candidate_id, []).append(
            ExperienceItem(e.title, e.company_name, e.start_date, e.end_date, e.description)
        )

    edu_levels: dict[uuid.UUID, list[str]] = {}
    edu_text: dict[uuid.UUID, list[str]] = {}
    for ed in (await session.execute(select(Education).where(Education.candidate_id.in_(ids)))).scalars():
        edu_levels.setdefault(ed.candidate_id, []).append(ed.degree_level.value)
        edu_text.setdefault(ed.candidate_id, []).append(
            " ".join(p for p in (ed.degree, ed.field_of_study) if p)
        )

    certs: dict[uuid.UUID, list[str]] = {}
    for c in (
        await session.execute(select(Certification).where(Certification.candidate_id.in_(ids)))
    ).scalars():
        certs.setdefault(c.candidate_id, []).append(c.name)

    # Excerpt of the primary, successfully processed résumé (bounded, SQL-side, so we never pull whole documents).
    excerpts: dict[uuid.UUID, str] = {}
    for cid, text in (
        await session.execute(
            select(Resume.candidate_id, func.left(ResumeProcessingResult.extracted_text, 4000))
            .join(ResumeProcessingResult, ResumeProcessingResult.resume_id == Resume.id)
            .where(
                Resume.candidate_id.in_(ids),
                Resume.is_primary.is_(True),
                Resume.status == ResumeStatus.PROCESSED,
            )
        )
    ).all():
        excerpts[cid] = clean(text, MAX_RESUME_EXCERPT_CHARS)

    out: dict[uuid.UUID, CandidateFeatures] = {}
    for cid, p in profiles.items():
        excerpt = excerpts.get(cid, "")
        out[cid] = CandidateFeatures(
            candidate_id=str(cid),
            headline=clean(p.headline),
            summary=clean(p.summary),
            skills=skills.get(cid, []),
            experiences=experiences.get(cid, []),
            certifications=certs.get(cid, []),
            education_levels=edu_levels.get(cid, []),
            education_text=edu_text.get(cid, []),
            declared_years=float(p.years_experience) if p.years_experience is not None else None,
            location=p.location,
            remote_preference=p.remote_preference.value if p.remote_preference else None,
            employment_preference=p.employment_preference.value if p.employment_preference else None,
            resume_excerpt=excerpt,
            resume_text_hash=hashlib.sha256(excerpt.encode()).hexdigest() if excerpt else "",
        )
    return out
