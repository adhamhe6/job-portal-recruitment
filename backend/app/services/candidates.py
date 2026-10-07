"""Candidate profiles: self-service CRUD, profile completion, and the recruiter-facing candidate view."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.db.models import (
    Application,
    CandidateLanguage,
    CandidateProfile,
    CandidateSkill,
    Certification,
    DataSource,
    Education,
    Experience,
    Job,
    Resume,
    ResumeDocument,
    ResumeStatus,
    SkillStatus,
    User,
)
from app.matching.service import MatchingService
from app.schemas.candidate import (
    ApplicationBrief,
    CandidateProfileOut,
    CandidateSkillIn,
    CandidateSkillOut,
    CandidateSkillUpdate,
    CandidateView,
    CertificationIn,
    CertificationOut,
    CompletionItem,
    EducationIn,
    EducationOut,
    ExperienceIn,
    ExperienceOut,
    LanguageIn,
    LanguageOut,
    ProfileCompletion,
    ProfileUpdate,
    ResumeBrief,
)
from app.schemas.skill import SkillOut
from app.services.access import CandidateAccess, candidate_access_for, load_job_for_staff
from app.services.scheduling import schedule_candidate_refresh
from app.services.skills import SkillService
from app.services.tasks import Dispatcher

T = TypeVar("T")

PROFILE_FIELDS = (
    "headline",
    "summary",
    "location",
    "years_experience",
    "expected_salary",
    "salary_currency",
    "remote_preference",
    "employment_preference",
    "availability",
    "portfolio_url",
    "linkedin_url",
    "github_url",
    "is_searchable",
)

_COMPLETION: list[tuple[str, str, int]] = [
    ("headline", "Add a professional headline", 10),
    ("summary", "Write a short professional summary", 10),
    ("location", "Add your location", 5),
    ("years_experience", "State your years of experience", 5),
    ("skills", "Add at least 3 skills", 20),
    ("experience", "Add your work experience", 15),
    ("education", "Add your education", 10),
    ("resume", "Upload your résumé", 15),
    ("links", "Add a portfolio, LinkedIn or GitHub link", 5),
    ("preferences", "Set your work preferences or availability", 5),
]


def compute_completion(profile: CandidateProfile, *, skills: int, experiences: int, educations: int, has_resume: bool) -> ProfileCompletion:
    done = {
        "headline": bool(profile.headline),
        "summary": bool(profile.summary and len(profile.summary) >= 30),
        "location": bool(profile.location),
        "years_experience": profile.years_experience is not None,
        "skills": skills >= 3,
        "experience": experiences >= 1,
        "education": educations >= 1,
        "resume": has_resume,
        "links": bool(profile.portfolio_url or profile.linkedin_url or profile.github_url),
        "preferences": bool(profile.remote_preference or profile.availability),
    }
    items = [CompletionItem(key=k, label=label, weight=w, done=done[k]) for k, label, w in _COMPLETION]
    percent = sum(i.weight for i in items if i.done)
    return ProfileCompletion(percent=percent, items=items, missing=[i.label for i in items if not i.done])


async def load_full_profile(session: AsyncSession, candidate_id: uuid.UUID) -> CandidateProfile:
    stmt = (
        select(CandidateProfile)
        .where(CandidateProfile.id == candidate_id)
        .options(
            selectinload(CandidateProfile.skills).selectinload(CandidateSkill.skill),
            selectinload(CandidateProfile.experiences),
            selectinload(CandidateProfile.educations),
            selectinload(CandidateProfile.certifications),
            selectinload(CandidateProfile.languages),
            selectinload(CandidateProfile.user),
        )
    )
    profile = (await session.execute(stmt)).scalar_one_or_none()
    if profile is None:
        raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
    return profile


def skill_out(cs: CandidateSkill) -> CandidateSkillOut:
    return CandidateSkillOut(
        id=cs.id,
        skill=SkillOut.model_validate(cs.skill),
        proficiency=cs.proficiency,
        years_experience=cs.years_experience,
        source=cs.source,
        status=cs.status,
        confidence=float(cs.confidence) if cs.confidence is not None else None,
    )


class CandidateService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher | None = None, cache: Cache | None = None) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.cache = cache

    # --- helpers --------------------------------------------------------------------------------------
    async def profile_for_user(self, user: User) -> CandidateProfile:
        profile = (await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))).scalar_one_or_none()
        if profile is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        return profile

    async def _after_change(self, profile: CandidateProfile, user: User | None = None) -> None:
        """Refresh the denormalised search text synchronously; embedding + matches in the background."""
        await MatchingService(self.session).refresh_candidate_text(profile.id)
        await self.session.commit()
        if self.cache:
            await self.cache.invalidate(CacheDomain.CANDIDATES, CacheDomain.MATCHES)
        await schedule_candidate_refresh(self.session, self.dispatcher, profile.id, user.id if user else None)

    async def _primary_resume(self, candidate_id: uuid.UUID) -> tuple[Resume, str | None] | None:
        row = (
            await self.session.execute(
                select(Resume, ResumeDocument.original_filename)
                .outerjoin(ResumeDocument, ResumeDocument.resume_id == Resume.id)
                .where(Resume.candidate_id == candidate_id, Resume.is_primary.is_(True))
                .limit(1)
            )
        ).first()
        return (row[0], row[1]) if row else None

    # --- own profile -----------------------------------------------------------------------------------
    async def own_profile(self, user: User) -> CandidateProfileOut:
        base = await self.profile_for_user(user)
        profile = await load_full_profile(self.session, base.id)
        primary = await self._primary_resume(profile.id)
        active_skills = [s for s in profile.skills if s.status != SkillStatus.REJECTED]
        has_resume = bool(primary and primary[0].status == ResumeStatus.PROCESSED)
        completion = compute_completion(
            profile, skills=len([s for s in active_skills if s.status == SkillStatus.CONFIRMED]), experiences=len(profile.experiences),
            educations=len(profile.educations), has_resume=has_resume,
        )
        return CandidateProfileOut(
            id=profile.id,
            first_name=profile.first_name,
            last_name=profile.last_name,
            email=profile.user.email if profile.user else profile.contact_email,
            phone=profile.user.phone if profile.user else profile.contact_phone,
            headline=profile.headline,
            summary=profile.summary,
            location=profile.location,
            years_experience=profile.years_experience,
            expected_salary=profile.expected_salary,
            salary_currency=profile.salary_currency,
            remote_preference=profile.remote_preference,
            employment_preference=profile.employment_preference,
            availability=profile.availability,
            portfolio_url=profile.portfolio_url,
            linkedin_url=profile.linkedin_url,
            github_url=profile.github_url,
            is_searchable=profile.is_searchable,
            skills=[skill_out(s) for s in sorted(profile.skills, key=lambda s: s.skill.name.lower())],
            experiences=[ExperienceOut.model_validate(e) for e in profile.experiences],
            educations=[EducationOut.model_validate(e) for e in profile.educations],
            certifications=[CertificationOut.model_validate(c) for c in profile.certifications],
            languages=[LanguageOut.model_validate(lang) for lang in profile.languages],
            completion=completion,
            primary_resume=(
                ResumeBrief(id=primary[0].id, status=primary[0].status.value, is_primary=True, original_filename=primary[1], created_at=primary[0].created_at)
                if primary
                else None
            ),
            updated_at=profile.updated_at,
        )

    async def update_profile(self, user: User, data: ProfileUpdate) -> CandidateProfileOut:
        profile = await self.profile_for_user(user)
        changes: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "phone" in changes:
            user.phone = changes.pop("phone")
        for k, v in changes.items():
            if k in ("salary_currency", "is_searchable") and v is None:
                continue
            setattr(profile, k, v)
        await self.session.commit()
        await self._after_change(profile, user)
        return await self.own_profile(user)

    # --- generic child CRUD --------------------------------------------------------------------------------
    async def _child(self, model: type[T], item_id: uuid.UUID, profile: CandidateProfile) -> T:
        obj = await self.session.get(model, item_id)
        if obj is None or obj.candidate_id != profile.id:  # type: ignore[attr-defined]
            raise NotFoundError("Item not found", code="NOT_FOUND")
        return obj

    async def add_experience(self, user: User, data: ExperienceIn) -> ExperienceOut:
        profile = await self.profile_for_user(user)
        obj = Experience(candidate_id=profile.id, source=DataSource.USER, **data.model_dump())
        self.session.add(obj)
        await self.session.commit()
        await self._after_change(profile, user)
        return ExperienceOut.model_validate(obj)

    async def update_experience(self, user: User, item_id: uuid.UUID, data: ExperienceIn) -> ExperienceOut:
        profile = await self.profile_for_user(user)
        obj = await self._child(Experience, item_id, profile)
        for k, v in data.model_dump().items():
            setattr(obj, k, v)
        obj.source = DataSource.USER
        await self.session.commit()
        await self._after_change(profile, user)
        return ExperienceOut.model_validate(obj)

    async def delete_experience(self, user: User, item_id: uuid.UUID) -> None:
        profile = await self.profile_for_user(user)
        await self.session.delete(await self._child(Experience, item_id, profile))
        await self.session.commit()
        await self._after_change(profile, user)

    async def add_education(self, user: User, data: EducationIn) -> EducationOut:
        profile = await self.profile_for_user(user)
        obj = Education(candidate_id=profile.id, source=DataSource.USER, **data.model_dump())
        self.session.add(obj)
        await self.session.commit()
        await self._after_change(profile, user)
        return EducationOut.model_validate(obj)

    async def update_education(self, user: User, item_id: uuid.UUID, data: EducationIn) -> EducationOut:
        profile = await self.profile_for_user(user)
        obj = await self._child(Education, item_id, profile)
        for k, v in data.model_dump().items():
            setattr(obj, k, v)
        obj.source = DataSource.USER
        await self.session.commit()
        await self._after_change(profile, user)
        return EducationOut.model_validate(obj)

    async def delete_education(self, user: User, item_id: uuid.UUID) -> None:
        profile = await self.profile_for_user(user)
        await self.session.delete(await self._child(Education, item_id, profile))
        await self.session.commit()
        await self._after_change(profile, user)

    async def add_certification(self, user: User, data: CertificationIn) -> CertificationOut:
        profile = await self.profile_for_user(user)
        obj = Certification(candidate_id=profile.id, source=DataSource.USER, **data.model_dump())
        self.session.add(obj)
        await self.session.commit()
        await self._after_change(profile, user)
        return CertificationOut.model_validate(obj)

    async def update_certification(self, user: User, item_id: uuid.UUID, data: CertificationIn) -> CertificationOut:
        profile = await self.profile_for_user(user)
        obj = await self._child(Certification, item_id, profile)
        for k, v in data.model_dump().items():
            setattr(obj, k, v)
        await self.session.commit()
        await self._after_change(profile, user)
        return CertificationOut.model_validate(obj)

    async def delete_certification(self, user: User, item_id: uuid.UUID) -> None:
        profile = await self.profile_for_user(user)
        await self.session.delete(await self._child(Certification, item_id, profile))
        await self.session.commit()
        await self._after_change(profile, user)

    async def add_language(self, user: User, data: LanguageIn) -> LanguageOut:
        profile = await self.profile_for_user(user)
        exists = await self.session.scalar(
            select(CandidateLanguage.id).where(CandidateLanguage.candidate_id == profile.id, func.lower(CandidateLanguage.language) == data.language.lower())
        )
        if exists:
            raise ConflictError("Language already added", code="LANGUAGE_EXISTS")
        obj = CandidateLanguage(candidate_id=profile.id, **data.model_dump())
        self.session.add(obj)
        await self.session.commit()
        return LanguageOut.model_validate(obj)

    async def delete_language(self, user: User, item_id: uuid.UUID) -> None:
        profile = await self.profile_for_user(user)
        await self.session.delete(await self._child(CandidateLanguage, item_id, profile))
        await self.session.commit()

    # --- skills ----------------------------------------------------------------------------------------------
    async def add_skill(self, user: User, data: CandidateSkillIn) -> CandidateSkillOut:
        profile = await self.profile_for_user(user)
        skills = SkillService(self.session, self.cache)
        if data.skill_id:
            from app.db.models import Skill

            skill = await self.session.get(Skill, data.skill_id)
            if skill is None:
                raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND")
        else:
            assert data.name
            skill = await skills.get_or_create(data.name)
        existing = (
            await self.session.execute(select(CandidateSkill).where(CandidateSkill.candidate_id == profile.id, CandidateSkill.skill_id == skill.id))
        ).scalar_one_or_none()
        if existing and existing.status == SkillStatus.CONFIRMED:
            raise ConflictError("You already have this skill", code="SKILL_ALREADY_ADDED")
        if existing:  # a parser suggestion (or rejected one) the user now explicitly claims
            existing.status, existing.source = SkillStatus.CONFIRMED, DataSource.USER
            existing.proficiency, existing.years_experience = data.proficiency, data.years_experience
            cs = existing
        else:
            cs = CandidateSkill(
                candidate_id=profile.id, skill_id=skill.id, proficiency=data.proficiency, years_experience=data.years_experience,
                source=DataSource.USER, status=SkillStatus.CONFIRMED,
            )
            self.session.add(cs)
        await self.session.commit()
        await self._after_change(profile, user)
        cs.skill = skill
        return skill_out(cs)

    async def update_skill(self, user: User, item_id: uuid.UUID, data: CandidateSkillUpdate) -> CandidateSkillOut:
        profile = await self.profile_for_user(user)
        cs = await self._child(CandidateSkill, item_id, profile)
        changes = data.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(cs, k, v)
        if changes.get("status") == SkillStatus.CONFIRMED:
            cs.source = DataSource.USER if cs.source == DataSource.USER else cs.source  # keep provenance of parser suggestions
        await self.session.commit()
        await self._after_change(profile, user)
        row = (await self.session.execute(select(CandidateSkill).where(CandidateSkill.id == cs.id).options(selectinload(CandidateSkill.skill)))).scalar_one()
        return skill_out(row)

    async def remove_skill(self, user: User, item_id: uuid.UUID) -> None:
        profile = await self.profile_for_user(user)
        cs = await self._child(CandidateSkill, item_id, profile)
        if cs.source == DataSource.RESUME:
            cs.status = SkillStatus.REJECTED  # remember the dismissal so reprocessing doesn't re-suggest it
        else:
            await self.session.execute(delete(CandidateSkill).where(CandidateSkill.id == cs.id))
        await self.session.commit()
        await self._after_change(profile, user)

    # --- staff view --------------------------------------------------------------------------------------------
    async def staff_view(self, user: User, candidate_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> CandidateView:
        base = await self.session.get(CandidateProfile, candidate_id)
        if base is None:
            raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
        access = await candidate_access_for(self.session, user, base)
        if access == CandidateAccess.NONE:
            raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
        profile = await load_full_profile(self.session, candidate_id)
        full = access == CandidateAccess.FULL
        resumes: list[ResumeBrief] = []
        if full:
            for r, fname in (
                await self.session.execute(
                    select(Resume, ResumeDocument.original_filename)
                    .outerjoin(ResumeDocument, ResumeDocument.resume_id == Resume.id)
                    .where(Resume.candidate_id == candidate_id)
                    .order_by(Resume.created_at.desc())
                )
            ).all():
                resumes.append(ResumeBrief(id=r.id, status=r.status.value, is_primary=r.is_primary, original_filename=fname, created_at=r.created_at))
        apps: list[ApplicationBrief] = []
        if user.company_id:
            for a, title in (
                await self.session.execute(
                    select(Application, Job.title)
                    .join(Job, Job.id == Application.job_id)
                    .where(Application.candidate_id == candidate_id, Job.company_id == user.company_id)
                    .order_by(Application.applied_at.desc())
                )
            ).all():
                apps.append(ApplicationBrief(id=a.id, job_id=a.job_id, job_title=title, status=a.status.value, applied_at=a.applied_at))
        match = None
        if job_id:
            job = await load_job_for_staff(self.session, user, job_id)
            m = await MatchingService(self.session).get_or_compute(job, base)
            match = {
                "job_id": str(job.id),
                "overall_score": m.overall_score,
                "semantic_score": m.semantic_score,
                "required_skill_score": m.required_skill_score,
                "preferred_skill_score": m.preferred_skill_score,
                "experience_score": m.experience_score,
                "education_score": m.education_score,
                "preference_score": m.preference_score,
                "explanation": m.explanation,
                "generated_at": m.generated_at.isoformat(),
            }
        active = [s for s in profile.skills if s.status != SkillStatus.REJECTED]
        return CandidateView(
            id=profile.id,
            display_name=profile.display_name,
            source=profile.source,
            access=access.name,
            headline=profile.headline,
            summary=profile.summary,
            location=profile.location,
            years_experience=profile.years_experience,
            expected_salary=profile.expected_salary,
            salary_currency=profile.salary_currency,
            remote_preference=profile.remote_preference,
            employment_preference=profile.employment_preference,
            availability=profile.availability,
            portfolio_url=profile.portfolio_url,
            linkedin_url=profile.linkedin_url,
            github_url=profile.github_url,
            email=(profile.user.email if profile.user else profile.contact_email) if full else None,
            phone=(profile.user.phone if profile.user else profile.contact_phone) if full else None,
            skills=[skill_out(s) for s in sorted(active, key=lambda s: s.skill.name.lower())],
            experiences=[ExperienceOut.model_validate(e) for e in profile.experiences],
            educations=[EducationOut.model_validate(e) for e in profile.educations],
            certifications=[CertificationOut.model_validate(c) for c in profile.certifications],
            languages=[LanguageOut.model_validate(lang) for lang in profile.languages],
            resumes=resumes,
            applications=apps,
            updated_at=profile.updated_at,
            match=match,
        )


_ = BusinessRuleError  # re-exported for route modules
