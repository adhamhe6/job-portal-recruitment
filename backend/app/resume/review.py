"""Extracted-data review: the suggestion view, owner corrections (PATCH) and applying suggestions to the profile.

Suggestions live in ``resume_processing_results.parsed_data`` (JSON). Corrections edit that JSON only — never the raw
``extracted_text`` — and flag the touched items ``corrected``; removed suggestions stay in place (``removed = true``) so
the ``index`` values the client holds remain stable. Applying creates rows with ``source = RESUME`` and is conservative:
duplicates are skipped and existing user-provided scalar values are only replaced for fields listed in ``overwrite``.
"""

from __future__ import annotations

import copy
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailure
from app.db.models import CandidateProfile, CandidateSkill, DataSource, Skill, SkillStatus, User
from app.resume import profile as ops
from app.schemas.resume import (
    ApplyRequest,
    ApplyResult,
    ExtractedCertification,
    ExtractedContact,
    ExtractedEducation,
    ExtractedExperience,
    ExtractedLanguage,
    ExtractedPatch,
    ExtractedResume,
    ExtractedSkill,
    ExtractedYears,
    SkippedItem,
)

SECTIONS = ("skills", "experiences", "educations", "certifications", "languages")
MAX_SUMMARY = 5000
MAX_HEADLINE = 200


def _live(items: Sequence[Mapping[str, Any]]) -> list[tuple[int, Mapping[str, Any]]]:
    return [(i, it) for i, it in enumerate(items) if not it.get("removed")]


# --- the review view -------------------------------------------------------------------------------------------------


async def build_extracted(
    session: AsyncSession, *, resume_id: uuid.UUID, candidate_id: uuid.UUID, parsed: Mapping[str, Any]
) -> ExtractedResume:
    snap = await ops.load_snapshot(session, candidate_id)
    skill_items = parsed.get("skills") or []
    resolved = await ops.resolve_skills(session, (s.get("name", "") for s in skill_items))

    skills: list[ExtractedSkill] = []
    for i, s in _live(skill_items):
        skill = resolved.get(s.get("name", ""))
        row = snap.skills.get(skill.id) if skill else None
        skills.append(
            ExtractedSkill(
                index=i,
                name=s["name"],
                skill_id=skill.id if skill else None,
                confidence=float(s.get("confidence", 0)),
                listed=bool(s.get("listed")),
                already_on_profile=bool(row and row[0] == SkillStatus.CONFIRMED),
                status=row[0] if row else None,
                corrected=bool(s.get("corrected")),
            )
        )

    experiences: list[ExtractedExperience] = []
    for i, e in _live(parsed.get("experiences") or []):
        missing = [
            f
            for f, v in (
                ("title", e.get("title")),
                ("company", e.get("company")),
                ("start_date", e.get("start_date")),
            )
            if not v
        ]
        experiences.append(
            ExtractedExperience(
                index=i,
                title=e.get("title"),
                company=e.get("company"),
                location=e.get("location"),
                start_date=ops.as_date(e.get("start_date")),
                end_date=ops.as_date(e.get("end_date")),
                is_current=bool(e.get("is_current")),
                description=e.get("description"),
                confidence=float(e.get("confidence", 0)),
                already_on_profile=ops.experience_key(e.get("title"), e.get("company"), e.get("start_date"))
                in snap.experiences,
                corrected=bool(e.get("corrected")),
                missing_for_apply=missing,
            )
        )

    educations: list[ExtractedEducation] = []
    for i, e in _live(parsed.get("educations") or []):
        missing = [
            f
            for f, v in (("institution", e.get("institution")), ("degree_level", e.get("degree_level")))
            if not v
        ]
        educations.append(
            ExtractedEducation(
                index=i,
                institution=e.get("institution"),
                degree=e.get("degree"),
                degree_level=e.get("degree_level"),
                field_of_study=e.get("field_of_study"),
                start_year=e.get("start_year"),
                end_year=e.get("end_year"),
                confidence=float(e.get("confidence", 0)),
                already_on_profile=ops.education_key(e.get("institution"), e.get("degree_level"))
                in snap.educations,
                corrected=bool(e.get("corrected")),
                missing_for_apply=missing,
            )
        )

    certifications = [
        ExtractedCertification(
            index=i,
            name=c["name"],
            issuer=c.get("issuer"),
            issued_on=ops.as_date(c.get("issued_on")),
            issued_year=c.get("issued_year"),
            confidence=float(c.get("confidence", 0)),
            already_on_profile=ops.norm(c["name"]) in snap.certifications,
            corrected=bool(c.get("corrected")),
        )
        for i, c in _live(parsed.get("certifications") or [])
    ]
    languages = [
        ExtractedLanguage(
            index=i,
            language=lang["language"],
            proficiency=lang.get("proficiency"),
            confidence=float(lang.get("confidence", 0)),
            already_on_profile=ops.norm(lang["language"]) in snap.languages,
            corrected=bool(lang.get("corrected")),
            missing_for_apply=[] if lang.get("proficiency") else ["proficiency"],
        )
        for i, lang in _live(parsed.get("languages") or [])
    ]
    yoe = parsed.get("years_of_experience")
    return ExtractedResume(
        resume_id=resume_id,
        candidate_id=candidate_id,
        parser_version=str(parsed.get("parser_version") or ""),
        has_corrections=bool(parsed.get("has_corrections")),
        contact=ExtractedContact(
            **{k: (parsed.get("contact") or {}).get(k) for k in ExtractedContact.model_fields}
        ),
        headline=parsed.get("headline"),
        summary=parsed.get("summary"),
        years_of_experience=ExtractedYears(
            value=yoe.get("value"), basis=yoe.get("basis"), stated=yoe.get("stated")
        )
        if isinstance(yoe, Mapping)
        else None,
        skills=skills,
        experiences=experiences,
        educations=educations,
        certifications=certifications,
        languages=languages,
        sections_detected=list(parsed.get("sections") or []),
        warnings=list(parsed.get("warnings") or []),
    )


# --- corrections -------------------------------------------------------------------------------------------------------------


def _patch_items(parsed: dict[str, Any], section: str, patches: Sequence[Any]) -> None:
    items: list[dict[str, Any]] = parsed.setdefault(section, [])
    for p in patches:
        if p.index >= len(items):
            raise ValidationFailure(
                f"No {section[:-1] if section.endswith('s') else section} suggestion with index {p.index}",
                code="INVALID_INDEX",
                details={"section": section, "index": p.index, "count": len(items)},
            )
        item = items[p.index]
        if "remove" in p.model_fields_set:
            item["removed"] = bool(p.remove)
        for field in p.model_fields_set - {"index", "remove"}:
            value = getattr(p, field)
            item[field] = (
                value.isoformat()
                if isinstance(value, date)
                else (value.value if hasattr(value, "value") else value)
            )
        if p.model_fields_set - {"index", "remove"}:
            item["corrected"] = True
        if item.get("is_current"):
            item["end_date"] = None


async def apply_patch(
    session: AsyncSession, parsed: Mapping[str, Any], patch: ExtractedPatch
) -> dict[str, Any]:
    """Return a corrected deep copy of ``parsed`` (the caller stores it). Raises ``ValidationFailure`` on a bad index."""
    out: dict[str, Any] = copy.deepcopy(dict(parsed))
    touched = False
    if patch.contact is not None:
        contact = out.setdefault("contact", {})
        for field in patch.contact.model_fields_set:
            contact[field] = getattr(patch.contact, field)
            touched = True
    for field in ("headline", "summary"):
        if field in patch.model_fields_set:
            out[field] = getattr(patch, field)
            touched = True
    if "years_of_experience" in patch.model_fields_set:
        value = patch.years_of_experience
        out["years_of_experience"] = (
            None
            if value is None
            else {"value": float(value), "basis": "corrected", "computed": None, "stated": None}
        )
        touched = True

    # Skill renames are re-resolved against the taxonomy so the canonical spelling is stored when one exists.
    renamed = [p.name for p in patch.skills if p.name]
    canon = await ops.resolve_skills(session, renamed)
    for p in patch.skills:
        if p.name and p.name in canon:
            p.name = canon[p.name].name
    _patch_items(out, "skills", patch.skills)
    _patch_items(out, "experiences", patch.experiences)
    _patch_items(out, "educations", patch.educations)
    _patch_items(out, "certifications", patch.certifications)
    _patch_items(out, "languages", patch.languages)
    touched = touched or any(getattr(patch, s) for s in SECTIONS)
    if touched:
        out["has_corrections"] = True
    return out


# --- apply ---------------------------------------------------------------------------------------------------------------------


def _indices(selection: list[int] | str, items: Sequence[Any]) -> list[int]:
    if selection == "all":
        return list(range(len(items)))
    assert isinstance(selection, list)
    return list(dict.fromkeys(selection))


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


async def apply_extracted(
    session: AsyncSession,
    *,
    candidate: CandidateProfile,
    parsed: Mapping[str, Any],
    request: ApplyRequest,
    today: date | None = None,
) -> ApplyResult:
    """Copy the selected suggestions into the structured profile (caller commits)."""
    today = today or date.today()
    snap = await ops.load_snapshot(session, candidate.id)
    applied: dict[str, int] = defaultdict(int)
    skipped: list[SkippedItem] = []

    def pick(section: str, selection: list[int] | str) -> list[tuple[int, Mapping[str, Any]]]:
        items = parsed.get(section) or []
        out: list[tuple[int, Mapping[str, Any]]] = []
        for i in _indices(selection, items):
            if not 0 <= i < len(items):
                skipped.append(SkippedItem(section=section, index=i, reason="NOT_FOUND"))
            elif items[i].get("removed"):
                if selection != "all":
                    skipped.append(SkippedItem(section=section, index=i, reason="REMOVED"))
            else:
                out.append((i, items[i]))
        return out

    # skills: confirm (or create as confirmed) taxonomy skills; unknown names are never created from résumé text
    chosen = pick("skills", request.skills)
    resolved = await ops.resolve_skills(session, (it.get("name", "") for _, it in chosen))
    existing_rows: dict[uuid.UUID, CandidateSkill] = {}
    if resolved:
        for row in (
            await session.execute(
                select(CandidateSkill).where(
                    CandidateSkill.candidate_id == candidate.id,
                    CandidateSkill.skill_id.in_([s.id for s in resolved.values()]),
                )
            )
        ).scalars():
            existing_rows[row.skill_id] = row
    new_skill_ids: set[uuid.UUID] = set()
    for i, item in chosen:
        skill: Skill | None = resolved.get(item.get("name", ""))
        if skill is None:
            skipped.append(SkippedItem(section="skills", index=i, reason="UNKNOWN_SKILL"))
            continue
        current = existing_rows.get(skill.id)
        if (current is not None and current.status == SkillStatus.CONFIRMED) or skill.id in new_skill_ids:
            skipped.append(SkippedItem(section="skills", index=i, reason="ALREADY_ON_PROFILE"))
            continue
        if (
            current is not None
        ):  # a suggestion (or one the user dismissed earlier, now explicitly chosen again)
            current.status = SkillStatus.CONFIRMED
        else:
            session.add(
                CandidateSkill(
                    candidate_id=candidate.id,
                    skill_id=skill.id,
                    source=DataSource.RESUME,
                    status=SkillStatus.CONFIRMED,
                    confidence=Decimal(str(round(min(float(item.get("confidence", 0.5)), 0.99), 2))),
                )
            )
            new_skill_ids.add(skill.id)
        applied["skills"] += 1

    def add_rows(
        section: str,
        selection: list[int] | str,
        build: Callable[[Mapping[str, Any]], tuple[Any, str | None]],
        key: Callable[[Any], Any],
        seen: set[Any],
    ) -> None:
        for i, item in pick(section, selection):
            row, reason = build(item)
            if row is None:
                skipped.append(SkippedItem(section=section, index=i, reason=reason or "INVALID"))
                continue
            k = key(row)
            if k in seen:
                skipped.append(SkippedItem(section=section, index=i, reason="ALREADY_ON_PROFILE"))
                continue
            seen.add(k)
            session.add(row)
            applied[section] += 1

    add_rows(
        "experiences",
        request.experiences,
        lambda it: ops.build_experience(candidate.id, it, today),
        lambda r: ops.experience_key(r.title, r.company_name, r.start_date),
        snap.experiences,
    )
    add_rows(
        "educations",
        request.educations,
        lambda it: ops.build_education(candidate.id, it),
        lambda r: ops.education_key(r.institution, r.degree_level.value),
        snap.educations,
    )
    add_rows(
        "certifications",
        request.certifications,
        lambda it: ops.build_certification(candidate.id, it),
        lambda r: ops.norm(r.name),
        snap.certifications,
    )
    add_rows(
        "languages",
        request.languages,
        lambda it: ops.build_language(candidate.id, it),
        lambda r: ops.norm(r.language),
        snap.languages,
    )

    fields_applied = await _apply_fields(session, candidate, parsed, request, skipped)
    return ApplyResult(applied=dict(applied), fields_applied=fields_applied, skipped=skipped)


async def _apply_fields(
    session: AsyncSession,
    candidate: CandidateProfile,
    parsed: Mapping[str, Any],
    request: ApplyRequest,
    skipped: list[SkippedItem],
) -> list[str]:
    contact = parsed.get("contact") or {}
    user: User | None = await session.get(User, candidate.user_id) if candidate.user_id else None
    done: list[str] = []
    for field in dict.fromkeys(request.fields):
        section = f"profile.{field}"
        if field == "summary":
            suggestion: Any = parsed.get("summary")
        elif field == "headline":
            suggestion = parsed.get("headline")
        elif field == "years_experience":
            suggestion = ops.years_value(parsed)
        elif field == "phone":
            suggestion = contact.get("phone")
        else:  # location + the three URLs live under "contact"
            suggestion = contact.get(field)
        if _blank(suggestion):
            skipped.append(SkippedItem(section=section, reason="NO_SUGGESTION"))
            continue
        current = (
            (user.phone if user else candidate.contact_phone)
            if field == "phone"
            else getattr(candidate, field)
        )
        if not _blank(current) and field not in request.overwrite:
            skipped.append(SkippedItem(section=section, reason="FIELD_NOT_EMPTY"))
            continue
        value: Any = suggestion
        if field in ("linkedin_url", "github_url", "portfolio_url"):
            if not (
                isinstance(value, str) and value.startswith(("http://", "https://")) and len(value) <= 500
            ):
                skipped.append(SkippedItem(section=section, reason="INVALID_URL"))
                continue
        elif field == "headline":
            value = str(value)[:MAX_HEADLINE]
        elif field == "summary":
            value = str(value)[:MAX_SUMMARY]
        elif field == "location":
            value = str(value)[:200]
        elif field == "phone":
            value = str(value)[:32]
        if field == "phone":
            if user is not None:
                user.phone = value
            else:
                candidate.contact_phone = value
        else:
            setattr(candidate, field, value)
        done.append(field)
    return done
