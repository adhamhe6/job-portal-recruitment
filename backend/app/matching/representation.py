"""Turning candidates and jobs into text for embedding, plus deterministic content hashes.

Strategy (documented in docs/architecture.md):
* Both sides are described with the **same three aligned components** so titles are compared with titles, skills
  with skills and prose with prose:
    1. *role*   — job title + level  /  headline + recent job titles
    2. *skills* — required then preferred skills  /  the candidate's (non-rejected) skills
    3. *prose*  — responsibilities & summary  /  summary + experience descriptions + résumé excerpt
* The stored vector is the L2-normalised weighted sum of the component embeddings (``COMPONENT_WEIGHTS``). Prose is
  *truncated* so a long résumé cannot drown out the structured signals. Empty components are skipped and the weights
  renormalised.
* Only job-relevant information is used: no name, age, gender, photo, nationality or other personal attribute is ever
  part of the text.
* ``embedding_hash`` fingerprints the exact text embedded (skip re-embedding when unchanged); ``feature_hash``
  fingerprints everything the *score* depends on (used to detect stale matches).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.matching.embedder import EmbeddingError, aembed

COMPONENT_WEIGHTS = {"role": 0.35, "skills": 0.35, "prose": 0.30}
MAX_PROSE_CHARS = 1800
MAX_RESUME_EXCERPT_CHARS = 1200

_WS = re.compile(r"\s+")
_CONTACT = re.compile(r"(\S+@\S+|https?://\S+|www\.\S+|\+?\(?\d[\d\s().\-]{7,}\d)")


def clean(text: str | None, limit: int | None = None) -> str:
    t = _WS.sub(" ", (text or "")).strip()
    t = _CONTACT.sub(" ", t)  # contact details are noise for semantics (and personal data)
    t = _WS.sub(" ", t).strip()
    if not limit or len(t) <= limit:
        return t
    cut = t[:limit]
    # the cut falls inside a word: drop the partial word (a single overlong word is hard-cut)
    if not t[limit].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def _names(skills: list[SkillRef]) -> list[str]:
    return sorted((s.name for s in skills), key=str.casefold)


def _newest_first(experiences: list[ExperienceItem]) -> list[ExperienceItem]:
    """Most recent first; ties are broken by title/company so the order never depends on how the rows were loaded."""
    return sorted(
        experiences, key=lambda e: (e.start, e.title.casefold(), e.company.casefold()), reverse=True
    )


@dataclass(slots=True)
class SkillRef:
    skill_id: str
    name: str
    family: str | None = None
    years: float | None = None  # candidate: years of use; job: minimum years
    source: str | None = None  # candidate skills: USER / RESUME


@dataclass(slots=True)
class JobFeatures:
    job_id: str
    title: str
    company_id: str
    summary: str
    responsibilities: str
    qualifications: str
    required: list[SkillRef]
    preferred: list[SkillRef]
    min_experience_years: float
    max_experience_years: float | None
    experience_level: str | None
    min_education_level: str | None
    location: str | None
    workplace_type: str
    employment_type: str

    def components(self) -> dict[str, str]:
        role = ". ".join(
            p
            for p in (
                clean(self.title),
                (self.experience_level or "").title() + " level" if self.experience_level else "",
            )
            if p
        )
        skills = ", ".join(_names(self.required))
        if self.preferred:
            skills = (
                f"{skills}, {', '.join(_names(self.preferred))}"
                if skills
                else ", ".join(_names(self.preferred))
            )
        prose = clean(f"{self.responsibilities} {self.summary} {self.qualifications}", MAX_PROSE_CHARS)
        return {"role": role, "skills": skills, "prose": prose}

    def feature_hash(self) -> str:
        return _hash(
            {
                "c": self.components(),
                "req": sorted((s.skill_id, s.years) for s in self.required),
                "pref": sorted((s.skill_id, s.years) for s in self.preferred),
                "exp": [self.min_experience_years, self.max_experience_years, self.experience_level],
                "edu": self.min_education_level,
                "loc": [self.location, self.workplace_type, self.employment_type],
            }
        )


@dataclass(slots=True)
class ExperienceItem:
    title: str
    company: str
    start: date
    end: date | None
    description: str | None = None


@dataclass(slots=True)
class CandidateFeatures:
    candidate_id: str
    headline: str
    summary: str
    skills: list[SkillRef]
    experiences: list[ExperienceItem]
    certifications: list[str]
    education_levels: list[str]  # EducationLevel values
    education_text: list[str]
    declared_years: float | None
    location: str | None
    remote_preference: str | None
    employment_preference: str | None
    resume_excerpt: str = ""
    resume_text_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def recent_titles(self, n: int = 4) -> list[str]:
        return [e.title for e in _newest_first(self.experiences)[:n]]

    def components(self) -> dict[str, str]:
        # Everything is cleaned (contact details removed) and put in a canonical order, so the text - and therefore the hash -
        # does not depend on the order in which rows happened to be loaded.
        role = ". ".join(p for p in (clean(self.headline), clean(", ".join(self.recent_titles()))) if p)
        skills = clean(", ".join(_names(self.skills)))
        exp_text = " ".join(e.description or "" for e in _newest_first(self.experiences)[:4])
        extras = " ".join(
            [
                *sorted(self.certifications, key=str.casefold)[:6],
                *sorted(self.education_text, key=str.casefold)[:3],
            ]
        )
        prose = clean(f"{self.summary} {exp_text} {extras} {self.resume_excerpt}", MAX_PROSE_CHARS)
        return {"role": role, "skills": skills, "prose": prose}

    def feature_hash(self) -> str:
        return _hash(
            {
                "c": self.components(),
                "skills": sorted((s.skill_id, s.years) for s in self.skills),
                "exp": sorted((e.title, str(e.start), str(e.end)) for e in self.experiences),
                "years": self.declared_years,
                "edu": sorted(self.education_levels),
                "prefs": [self.location, self.remote_preference, self.employment_preference],
            }
        )


def embedding_hash(components: dict[str, str], model: str, version: str) -> str:
    return _hash({"components": components, "model": model, "version": version})


def combine_component_vectors(keys: list[str], vectors: np.ndarray) -> np.ndarray:
    weights = np.array([COMPONENT_WEIGHTS[k] for k in keys], dtype=np.float32)
    weights = weights / weights.sum()
    combined = (vectors * weights[:, None]).sum(axis=0)
    norm = np.linalg.norm(combined)
    if not np.isfinite(norm) or norm == 0:
        raise EmbeddingError("degenerate embedding")
    return (combined / norm).astype(np.float32)


async def embed_components(components: dict[str, str]) -> np.ndarray:
    """Weighted combination of component embeddings → one normalised vector of shape ``(dim,)``."""
    present = {k: v for k, v in components.items() if v.strip()}
    if not present:
        raise EmbeddingError("insufficient data to build an embedding")
    keys = list(present)
    return combine_component_vectors(keys, await aembed([present[k] for k in keys]))


def embed_components_sync(components: dict[str, str], embedder: Any) -> np.ndarray:
    """Synchronous variant (evaluation harness, scripts)."""
    present = {k: v for k, v in components.items() if v.strip()}
    if not present:
        raise EmbeddingError("insufficient data to build an embedding")
    keys = list(present)
    return combine_component_vectors(keys, embedder.embed([present[k] for k in keys]))


def total_years_of_experience(experiences: list[ExperienceItem], today: date | None = None) -> float:
    """Union of employment intervals (overlapping jobs are not double-counted), in years."""
    today = today or date.today()
    spans = sorted((e.start, e.end or today) for e in experiences if e.start <= (e.end or today))
    total_days, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:  # type: ignore[operator]
            cur_e = max(cur_e, e)  # type: ignore[type-var]
        else:
            total_days += (cur_e - cur_s).days  # type: ignore[operator]
            cur_s, cur_e = s, e
    if cur_s is not None:
        total_days += (cur_e - cur_s).days  # type: ignore[operator]
    return round(total_days / 365.25, 1)
