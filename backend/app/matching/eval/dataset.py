"""Hand-labelled relevance judgements for the demo cast (jobs × candidates) and feature builders.

Rubric (assigned by reading each profile against each job, *independently of the scorer*):
  3 = strong: would be shortlisted today (core skills and seniority fit)
  2 = plausible: most core skills, notable gaps
  1 = adjacent: related field / some overlap, unlikely to be shortlisted
  0 = unrelated (everything not listed below)

LIMITATIONS (also stated in docs/matching-evaluation.md): 16 candidates × 12 jobs, labelled by the same team that built the
system, on synthetic profiles. It demonstrates that the ranking is sensible and lets us compare methods; it is **not**
evidence of real-world accuracy and says nothing about fairness across demographic groups.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.matching.representation import CandidateFeatures, ExperienceItem, JobFeatures, SkillRef
from app.matching.skills import ONTOLOGY, skill_key
from app.scripts import seed_data as D

_FAMILY = {s.key: s.family for s in ONTOLOGY}
for _s in ONTOLOGY:
    for _a in _s.aliases:
        _FAMILY.setdefault(skill_key(_a), _s.family)

# job key → {candidate key: grade}
LABELS: dict[str, dict[str, int]] = {
    "backend": {
        "alex": 3,
        "nina": 3,
        "tomas": 3,
        "elena": 2,
        "gabe": 1,
        "mateo": 1,
        "farah": 1,
        "dmitri": 1,
        "oscar": 1,
        "chen": 1,
        "priya": 1,
    },
    "frontend": {"bianca": 3, "elena": 1},
    "mle": {"chen": 3, "priya": 2, "hana": 1, "alex": 1, "nina": 1},
    "devops": {"dmitri": 3, "nina": 2, "alex": 1},
    "analyst": {"hana": 3, "priya": 2, "lena": 1, "chen": 1},
    "platform": {"alex": 3, "nina": 3, "tomas": 3, "dmitri": 2, "oscar": 1, "elena": 1, "gabe": 1},
    "qa": {"oscar": 3, "alex": 1, "nina": 1, "tomas": 1},
    "icu_nurse": {"julia": 3},
    "clin_analyst": {"hana": 2, "priya": 2, "julia": 1, "chen": 1, "lena": 1},
    "marketing_mgr": {"kofi": 3},
    "fin_analyst": {"lena": 3, "hana": 1},
    "java_backend": {"gabe": 3, "alex": 1, "nina": 1, "tomas": 1},
}


def _skill(name: str, years: float | None = None, source: str | None = None) -> SkillRef:
    k = skill_key(name)
    return SkillRef(skill_id=k, name=name, family=_FAMILY.get(k), years=years, source=source)


def job_features(jd: dict) -> JobFeatures:
    req = [_skill(n) for n, r in jd["skills"] if r == "REQUIRED"]
    pref = [_skill(n) for n, r in jd["skills"] if r == "PREFERRED"]
    return JobFeatures(
        job_id=jd["key"],
        title=jd["title"],
        company_id=jd["company"],
        summary=jd["description"],
        responsibilities=jd["responsibilities"],
        qualifications=jd["qualifications"],
        required=req,
        preferred=pref,
        min_experience_years=float(jd["min_exp"]),
        max_experience_years=float(jd["max_exp"]) if jd["max_exp"] is not None else None,
        experience_level=jd["level"],
        min_education_level=jd["education"],
        location=jd["location"],
        workplace_type=jd["workplace"],
        employment_type=jd["employment"],
    )


def candidate_features(cd: dict) -> CandidateFeatures:
    def ago(y: float) -> date:
        return date.today() - timedelta(days=int(y * 365.25))

    return CandidateFeatures(
        candidate_id=cd["key"],
        headline=cd["headline"],
        summary=cd["summary"],
        skills=[_skill(n, yrs, "USER") for n, _prof, yrs in cd["skills"]],
        experiences=[
            ExperienceItem(t, c, ago(s), ago(e) if e else None, d) for t, c, s, e, d in cd["experiences"]
        ],
        certifications=[n for n, _ in cd["certifications"]],
        education_levels=[lvl for _i, lvl, *_ in cd["education"]],
        education_text=[f"{deg} {fld}" for _i, _l, deg, fld, *_ in cd["education"]],
        declared_years=cd["years"],
        location=cd["location"],
        remote_preference=cd["remote"],
        employment_preference=cd["employment"],
    )


def all_jobs() -> dict[str, JobFeatures]:
    return {jd["key"]: job_features(jd) for jd in D.JOBS if jd["key"] in LABELS}


def all_candidates() -> dict[str, CandidateFeatures]:
    return {cd["key"]: candidate_features(cd) for cd in D.CANDIDATES}
