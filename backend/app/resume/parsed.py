"""Typed result of the résumé parser and its JSON form (stored in ``resume_processing_results.parsed_data``).

Everything here is a *suggestion*: optional fields are ``None`` when the parser could not determine them, and each list
item carries a ``confidence`` in [0, 1] so the UI can show how sure the parser is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

PARSER_VERSION = "v1"


@dataclass(slots=True)
class ParsedContact:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    location: str | None = None


@dataclass(slots=True)
class ParsedSkill:
    name: str  # canonical ontology name
    confidence: float
    mentions: int = 1
    listed: bool = False  # found in a Skills section / skills-style list (vs. only mentioned in prose)


@dataclass(slots=True)
class ParsedExperience:
    title: str | None
    company: str | None
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class ParsedEducation:
    institution: str | None
    degree: str | None = None
    degree_level: str | None = None  # EducationLevel value
    field_of_study: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class ParsedCertification:
    name: str
    issuer: str | None = None
    issued_on: date | None = None  # only when month + year are known
    issued_year: int | None = None
    confidence: float = 0.6


@dataclass(slots=True)
class ParsedLanguage:
    language: str
    proficiency: str | None = None  # LanguageProficiency value, None when the résumé does not say
    confidence: float = 0.7


@dataclass(slots=True)
class YearsOfExperience:
    value: float | None
    basis: str  # "employment_history" (union of dated jobs) | "stated" (explicit "N years of experience")
    computed: float | None = None
    stated: float | None = None


@dataclass(slots=True)
class ParsedResume:
    parser_version: str = PARSER_VERSION
    contact: ParsedContact = field(default_factory=ParsedContact)
    headline: str | None = None
    headline_confidence: float | None = None
    summary: str | None = None
    skills: list[ParsedSkill] = field(default_factory=list)
    experiences: list[ParsedExperience] = field(default_factory=list)
    educations: list[ParsedEducation] = field(default_factory=list)
    certifications: list[ParsedCertification] = field(default_factory=list)
    languages: list[ParsedLanguage] = field(default_factory=list)
    years_of_experience: YearsOfExperience | None = None
    sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form stored in the database (dates as ISO strings)."""
        c = self.contact
        yoe = self.years_of_experience
        return {
            "parser_version": self.parser_version,
            "contact": {
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "linkedin_url": c.linkedin_url,
                "github_url": c.github_url,
                "portfolio_url": c.portfolio_url,
                "location": c.location,
            },
            "headline": self.headline,
            "headline_confidence": self.headline_confidence,
            "summary": self.summary,
            "skills": [
                {"name": s.name, "confidence": s.confidence, "mentions": s.mentions, "listed": s.listed}
                for s in self.skills
            ],
            "experiences": [
                {
                    "title": e.title,
                    "company": e.company,
                    "location": e.location,
                    "start_date": e.start_date.isoformat() if e.start_date else None,
                    "end_date": e.end_date.isoformat() if e.end_date else None,
                    "is_current": e.is_current,
                    "description": e.description,
                    "confidence": e.confidence,
                }
                for e in self.experiences
            ],
            "educations": [
                {
                    "institution": e.institution,
                    "degree": e.degree,
                    "degree_level": e.degree_level,
                    "field_of_study": e.field_of_study,
                    "start_year": e.start_year,
                    "end_year": e.end_year,
                    "confidence": e.confidence,
                }
                for e in self.educations
            ],
            "certifications": [
                {
                    "name": c.name,
                    "issuer": c.issuer,
                    "issued_on": c.issued_on.isoformat() if c.issued_on else None,
                    "issued_year": c.issued_year,
                    "confidence": c.confidence,
                }
                for c in self.certifications
            ],
            "languages": [
                {"language": lang.language, "proficiency": lang.proficiency, "confidence": lang.confidence}
                for lang in self.languages
            ],
            "years_of_experience": (
                {"value": yoe.value, "basis": yoe.basis, "computed": yoe.computed, "stated": yoe.stated}
                if yoe
                else None
            ),
            "sections": self.sections,
            "warnings": self.warnings,
        }
