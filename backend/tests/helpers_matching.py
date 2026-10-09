"""Builders for the pure matching dataclasses (no database)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.matching.representation import CandidateFeatures, ExperienceItem, JobFeatures, SkillRef


def skill(
    name: str, family: str | None = None, years: float | None = None, source: str | None = "USER"
) -> SkillRef:
    return SkillRef(
        skill_id=f"id-{name.lower().replace(' ', '-')}", name=name, family=family, years=years, source=source
    )


def job(**overrides: Any) -> JobFeatures:
    base: dict[str, Any] = {
        "job_id": "job-1",
        "title": "Backend Engineer",
        "company_id": "company-1",
        "summary": "Build and operate Python services.",
        "responsibilities": "Design APIs and review code.",
        "qualifications": "Experience with REST APIs.",
        "required": [skill("Python"), skill("PostgreSQL", "relational-database")],
        "preferred": [skill("Docker")],
        "min_experience_years": 3.0,
        "max_experience_years": None,
        "experience_level": "MID",
        "min_education_level": None,
        "location": "Berlin, Germany",
        "workplace_type": "HYBRID",
        "employment_type": "FULL_TIME",
    }
    base.update(overrides)
    return JobFeatures(**base)


def candidate(**overrides: Any) -> CandidateFeatures:
    base: dict[str, Any] = {
        "candidate_id": "cand-1",
        "headline": "Backend engineer",
        "summary": "Builds Python APIs.",
        "skills": [skill("Python"), skill("PostgreSQL", "relational-database"), skill("Docker")],
        "experiences": [],
        "certifications": [],
        "education_levels": [],
        "education_text": [],
        "declared_years": 4.0,
        "location": "Berlin, Germany",
        "remote_preference": None,
        "employment_preference": None,
    }
    base.update(overrides)
    return CandidateFeatures(**base)


def exp(
    title: str, start: date, end: date | None, company: str = "Acme", description: str | None = None
) -> ExperienceItem:
    return ExperienceItem(title=title, company=company, start=start, end=end, description=description)


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)
