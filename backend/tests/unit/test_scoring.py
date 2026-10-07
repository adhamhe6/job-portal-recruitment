"""Pure scoring: skill coverage, experience/education/preference alignment, combination, floor, bands, explanation."""

from __future__ import annotations

import json
import math

import pytest

from app.matching.scoring import (
    COSINE_HIGH,
    COSINE_LOW,
    FLOOR_CAP,
    FLOOR_COVERAGE,
    RELATED_CREDIT,
    WEIGHTS,
    calibrate_cosine,
    combine,
    education_alignment,
    experience_alignment,
    overall_band,
    preference_alignment,
    score_pair,
    semantic_band,
    skill_coverage,
)
from tests.helpers_matching import candidate, exp, days_ago, job, skill

PG = skill("PostgreSQL", "relational-database")
MYSQL = skill("MySQL", "relational-database")
MARIA = skill("MariaDB", "relational-database")
PY = skill("Python")
GO = skill("Go")
DOCKER = skill("Docker", "containers")

# --- weights / calibration --------------------------------------------------------------------------------


def test_weights_sum_to_one_and_are_positive() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert set(WEIGHTS) == {"semantic", "required", "preferred", "experience", "education", "preference"}
    assert all(w > 0 for w in WEIGHTS.values())
    assert WEIGHTS["required"] > WEIGHTS["preferred"]


@pytest.mark.parametrize(
    ("cosine", "expected"),
    [(-1.0, 0.0), (0.0, 0.0), (COSINE_LOW, 0.0), (COSINE_HIGH, 1.0), (1.0, 1.0), (2.0, 1.0)],
)
def test_calibrate_cosine_bounds(cosine: float, expected: float) -> None:
    assert calibrate_cosine(cosine) == expected


def test_calibrate_cosine_midpoint_and_monotonic() -> None:
    assert calibrate_cosine((COSINE_LOW + COSINE_HIGH) / 2) == pytest.approx(0.5)
    xs = [i / 100 for i in range(-20, 121)]
    ys = [calibrate_cosine(x) for x in xs]
    assert all(0.0 <= y <= 1.0 for y in ys)
    assert all(a <= b for a, b in zip(ys, ys[1:], strict=False))
    assert len(set(ys)) > 40  # strictly increasing inside the calibration window


@pytest.mark.parametrize(
    ("score", "band"),
    [(0.0, "LOW"), (0.39, "LOW"), (0.4, "MEDIUM"), (0.69, "MEDIUM"), (0.7, "HIGH"), (1.0, "HIGH")],
)
def test_semantic_bands(score: float, band: str) -> None:
    assert semantic_band(score) == band


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0.0, "WEAK"),
        (0.349, "WEAK"),
        (0.35, "PARTIAL"),
        (0.549, "PARTIAL"),
        (0.55, "GOOD"),
        (0.749, "GOOD"),
        (0.75, "STRONG"),
        (1.0, "STRONG"),
    ],
)
def test_overall_bands(score: float, band: str) -> None:
    assert overall_band(score) == band


# --- skill coverage ----------------------------------------------------------------------------------------


def test_coverage_with_nothing_wanted_is_not_applicable() -> None:
    cov = skill_coverage([], [PY])
    assert cov.score is None and cov.matched == [] and cov.related == [] and cov.missing == []


def test_coverage_exact_match_is_full_credit_and_reports_provenance() -> None:
    cov = skill_coverage([PY, PG], [skill("Python", source="RESUME"), PG])
    assert cov.score == 1.0
    assert [m["name"] for m in cov.matched] == ["Python", "PostgreSQL"]
    assert cov.matched[0]["source"] == "RESUME"
    assert cov.related == [] and cov.missing == []


def test_coverage_same_skill_id_is_exact_even_with_a_different_display_name() -> None:
    alias_view = skill("Postgres", "relational-database")
    alias_view.skill_id = PG.skill_id  # the same canonical skill, reached through an alias
    assert skill_coverage([PG], [alias_view]).score == 1.0


def test_coverage_related_family_gets_partial_credit() -> None:
    cov = skill_coverage([MYSQL], [PG])
    assert cov.score == RELATED_CREDIT
    assert cov.related == [{"required": "MySQL", "candidate_has": "PostgreSQL"}]
    assert cov.matched == [] and cov.missing == []


def test_coverage_exact_beats_related_when_both_present() -> None:
    cov = skill_coverage([MYSQL], [PG, MYSQL])
    assert cov.score == 1.0 and cov.related == [] and [m["name"] for m in cov.matched] == ["MySQL"]


def test_coverage_missing_skill_scores_zero() -> None:
    cov = skill_coverage([GO], [PY, PG])
    assert cov.score == 0.0 and cov.missing == ["Go"]


def test_coverage_skill_without_family_never_matches_by_family() -> None:
    assert skill_coverage([skill("Rust")], [skill("Go")]).score == 0.0


def test_coverage_mixed_exact_related_missing() -> None:
    cov = skill_coverage([PY, MYSQL, GO, DOCKER], [PY, PG])
    assert cov.score == pytest.approx((1.0 + 0.5 + 0.0 + 0.0) / 4)
    assert (len(cov.matched), len(cov.related), len(cov.missing)) == (1, 1, 2)


def test_coverage_one_candidate_skill_can_cover_a_whole_family_partially() -> None:
    cov = skill_coverage([MYSQL, MARIA], [PG])
    assert cov.score == RELATED_CREDIT  # both wanted skills are related to the one candidate skill


@pytest.mark.parametrize("have", [[], [PY]])
def test_coverage_is_bounded(have: list) -> None:
    for wanted in ([PY], [PY, GO, PG], [MYSQL, MARIA]):
        score = skill_coverage(wanted, have).score
        assert score is not None and 0.0 <= score <= 1.0


# --- experience ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lo", "hi", "years", "status", "score"),
    [
        (3, None, 5, "MEETS", 1.0),
        (3, None, 3, "MEETS", 1.0),
        (3, 6, 4, "MEETS", 1.0),
        (3, 6, 6, "MEETS", 1.0),
        (4, None, 2, "BELOW", 0.5),
        (4, None, 0, "BELOW", 0.0),
        (1, None, 0.5, "BELOW", 0.5),
        (0.5, None, 0.0, "BELOW", 0.5),  # shortfall is measured against max(minimum, 1 year)
        (3, 5, 7, "ABOVE", 0.9),
        (3, 5, 20, "ABOVE", 0.7),  # floors at 0.7: over-experience is never a heavy penalty
        (3, None, None, "UNKNOWN", 0.4),
    ],
)
def test_experience_alignment_table(
    lo: float, hi: float | None, years: float | None, status: str, score: float
) -> None:
    res = experience_alignment(job(min_experience_years=lo, max_experience_years=hi), years)
    assert res.status == status
    assert res.score == pytest.approx(score)
    assert res.candidate_years == years


def test_experience_not_required_has_no_score() -> None:
    res = experience_alignment(job(min_experience_years=0, max_experience_years=None), 7)
    assert res.status == "NOT_REQUIRED" and res.score is None
    res = experience_alignment(job(min_experience_years=0, max_experience_years=None), None)
    assert res.status == "NOT_REQUIRED" and res.score is None


def test_experience_text_describes_the_requirement() -> None:
    assert "3+ years" in experience_alignment(job(min_experience_years=3), 1).text
    assert "3–6 years" in experience_alignment(job(min_experience_years=3, max_experience_years=6), 4).text
    assert "not provided" in experience_alignment(job(min_experience_years=3), None).text


# --- education ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("required", "have", "status", "score"),
    [
        (None, ["BACHELOR"], "NOT_REQUIRED", None),
        ("BACHELOR", ["BACHELOR"], "MEETS", 1.0),
        ("BACHELOR", ["MASTER"], "MEETS", 1.0),
        ("BACHELOR", ["HIGH_SCHOOL", "DOCTORATE"], "MEETS", 1.0),
        ("MASTER", ["BACHELOR"], "BELOW", 0.5),  # one level short
        ("MASTER", ["ASSOCIATE"], "BELOW", 0.0),  # two levels short
        ("DOCTORATE", ["HIGH_SCHOOL"], "BELOW", 0.0),
        ("BACHELOR", [], "UNKNOWN", 0.4),
        ("BACHELOR", ["NONSENSE"], "UNKNOWN", 0.4),
    ],
)
def test_education_alignment_table(
    required: str | None, have: list[str], status: str, score: float | None
) -> None:
    res = education_alignment(job(min_education_level=required), have)
    assert res.status == status
    assert res.score == (pytest.approx(score) if score is not None else None)


def test_education_reports_the_best_level() -> None:
    res = education_alignment(job(min_education_level="MASTER"), ["HIGH_SCHOOL", "BACHELOR"])
    assert res.candidate_level == "BACHELOR" and res.required_level == "MASTER"


# --- preferences -------------------------------------------------------------------------------------------------


def test_preferences_empty_when_candidate_gave_nothing_and_no_location_overlap() -> None:
    res = preference_alignment(job(location=None), candidate(location=None))
    assert res.score is None and res.notes == {}


@pytest.mark.parametrize(
    ("workplace", "pref", "fit"),
    [
        ("REMOTE", "REMOTE", 1.0),
        ("REMOTE", "FLEXIBLE", 1.0),
        ("REMOTE", "HYBRID", 0.6),
        ("REMOTE", "ONSITE", 0.2),
        ("HYBRID", "HYBRID", 1.0),
        ("HYBRID", "REMOTE", 0.6),
        ("HYBRID", "ONSITE", 0.6),
        ("ONSITE", "ONSITE", 1.0),
        ("ONSITE", "HYBRID", 0.7),
        ("ONSITE", "REMOTE", 0.2),
        ("ONSITE", "FLEXIBLE", 1.0),
    ],
)
def test_workplace_fit_table(workplace: str, pref: str, fit: float) -> None:
    res = preference_alignment(
        job(workplace_type=workplace, location=None), candidate(remote_preference=pref, location=None)
    )
    assert res.score == pytest.approx(fit)
    assert "workplace" in res.notes


def test_remote_jobs_ignore_location() -> None:
    far = preference_alignment(
        job(workplace_type="REMOTE", location="Tokyo, Japan"),
        candidate(remote_preference="REMOTE", location="Lima, Peru"),
    )
    assert far.score == 1.0 and "location" not in far.notes
    # ...whereas an on-site job is sensitive to it
    onsite = preference_alignment(
        job(workplace_type="ONSITE", location="Tokyo, Japan"),
        candidate(remote_preference="ONSITE", location="Lima, Peru"),
    )
    assert onsite.notes["location"] == "Different location"
    assert onsite.score == pytest.approx((1.0 + 0.2) / 2)


@pytest.mark.parametrize(
    ("job_loc", "cand_loc", "fit", "note"),
    [
        ("Berlin, Germany", "Berlin, Germany", 1.0, "Same city"),
        ("berlin, germany", "BERLIN, GERMANY", 1.0, "Same city"),
        ("Berlin, Germany", "Munich, Germany", 0.6, "Same region/country"),
        ("Berlin, Germany", "Paris, France", 0.2, "Different location"),
    ],
)
def test_location_fit(job_loc: str, cand_loc: str, fit: float, note: str) -> None:
    res = preference_alignment(
        job(workplace_type="ONSITE", location=job_loc), candidate(remote_preference=None, location=cand_loc)
    )
    assert res.score == pytest.approx(fit) and res.notes["location"] == note


def test_employment_preference() -> None:
    same = preference_alignment(
        job(location=None, employment_type="CONTRACT"),
        candidate(location=None, employment_preference="CONTRACT"),
    )
    other = preference_alignment(
        job(location=None, employment_type="CONTRACT"),
        candidate(location=None, employment_preference="FULL_TIME"),
    )
    assert same.score == 1.0 and same.notes["employment"] == "Employment type matches"
    assert other.score == pytest.approx(0.3) and "full time" in other.notes["employment"]


def test_preference_score_is_the_mean_of_available_parts() -> None:
    res = preference_alignment(
        job(workplace_type="HYBRID", location="Berlin, Germany", employment_type="FULL_TIME"),
        candidate(remote_preference="HYBRID", location="Berlin, Germany", employment_preference="PART_TIME"),
    )
    assert res.score == pytest.approx((1.0 + 1.0 + 0.3) / 3, abs=1e-3)


# --- combine ------------------------------------------------------------------------------------------------------------


def test_combine_all_components() -> None:
    comps = {
        "semantic": 1.0,
        "required": 1.0,
        "preferred": 1.0,
        "experience": 1.0,
        "education": 1.0,
        "preference": 1.0,
    }
    assert combine(comps) == pytest.approx(1.0)
    assert combine({k: 0.0 for k in comps}) == 0.0
    mixed = {
        "semantic": 0.5,
        "required": 1.0,
        "preferred": 0.0,
        "experience": 1.0,
        "education": 0.0,
        "preference": 0.5,
    }
    assert combine(mixed) == pytest.approx(sum(WEIGHTS[k] * v for k, v in mixed.items()))


def test_combine_renormalises_over_missing_components() -> None:
    # Only two components apply: weights 0.30 and 0.15 are rescaled to sum to one.
    value = combine(
        {
            "required": 1.0,
            "experience": 0.0,
            "semantic": None,
            "preferred": None,
            "education": None,
            "preference": None,
        }
    )
    assert value == pytest.approx(0.30 / (0.30 + 0.15))
    # A missing component neither rewards nor punishes: all-equal scores stay equal.
    assert combine({"required": 0.6, "experience": 0.6}) == pytest.approx(0.6)
    assert combine({"required": 0.6, "experience": 0.6, "preferred": None}) == pytest.approx(0.6)


def test_combine_with_nothing_applicable_is_zero() -> None:
    assert combine({}) == 0.0
    assert combine({"semantic": None, "required": None}) == 0.0


# --- score_pair: floor, explanation, summary ------------------------------------------------------------------------------------


def _strong_pair() -> tuple:
    j = job(
        required=[PY, PG],
        preferred=[DOCKER],
        min_experience_years=3,
        min_education_level="BACHELOR",
        workplace_type="HYBRID",
        location="Berlin, Germany",
        employment_type="FULL_TIME",
    )
    c = candidate(
        skills=[PY, PG, DOCKER],
        declared_years=5,
        education_levels=["MASTER"],
        remote_preference="HYBRID",
        location="Berlin, Germany",
        employment_preference="FULL_TIME",
    )
    return j, c


def test_perfect_pair_scores_one_with_a_perfect_cosine() -> None:
    j, c = _strong_pair()
    res = score_pair(j, c, 1.0)
    assert res.overall == 1.0
    assert (res.required, res.preferred, res.experience, res.education, res.preference) == (
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
    )
    assert res.semantic == 1.0 and res.raw_cosine == 1.0
    assert res.explanation["band"] == "STRONG" and res.explanation["qualification_floor_applied"] is False


def test_overall_always_within_unit_interval() -> None:
    j, c = _strong_pair()
    for cos in (-1.0, 0.0, 0.3, 0.6, 1.0):
        assert 0.0 <= score_pair(j, c, cos).overall <= 1.0
    worst = score_pair(job(required=[GO]), candidate(skills=[], declared_years=0), 0.0)
    assert 0.0 <= worst.overall <= 1.0


def test_semantic_similarity_orders_otherwise_identical_candidates() -> None:
    j, c = _strong_pair()
    scores = [score_pair(j, c, cos).overall for cos in (0.2, 0.4, 0.6, 0.8)]
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_qualification_floor_caps_underqualified_candidates() -> None:
    j = job(
        required=[PY, PG, GO, skill("Rust"), skill("Java")],
        preferred=[],
        min_experience_years=0,
        location=None,
    )
    c = candidate(skills=[], declared_years=10, location=None)
    res = score_pair(j, c, 1.0)  # perfect semantics, zero required-skill coverage
    assert res.required == 0.0 < FLOOR_COVERAGE
    assert res.overall <= FLOOR_CAP and res.explanation["qualification_floor_applied"] is True
    # without the floor the same pair would have scored much higher
    uncapped = combine({"semantic": 1.0, "required": 0.0})
    assert uncapped > FLOOR_CAP


def test_floor_boundary_at_exactly_the_coverage_threshold() -> None:
    four = [skill(n) for n in ("A1", "A2", "A3", "A4")]
    at = score_pair(
        job(required=four, preferred=[], location=None), candidate(skills=[four[0]], location=None), 1.0
    )
    below = score_pair(
        job(required=[*four, skill("A5")], preferred=[], location=None),
        candidate(skills=[four[0]], location=None),
        1.0,
    )
    assert at.required == FLOOR_COVERAGE and at.explanation["qualification_floor_applied"] is False
    assert below.required == pytest.approx(0.2) and below.explanation["qualification_floor_applied"] is True


def test_no_required_skills_means_no_floor() -> None:
    res = score_pair(job(required=[], preferred=[DOCKER]), candidate(skills=[]), 0.9)
    assert res.required is None and res.explanation["qualification_floor_applied"] is False


def test_missing_embedding_is_reported_as_unknown_semantics() -> None:
    j, c = _strong_pair()
    res = score_pair(j, c, None)
    assert res.explanation["semantic"]["band"] == "UNKNOWN" and res.explanation["semantic"]["cosine"] is None
    assert res.raw_cosine == 0.0 and res.semantic == 0.0


def test_explanation_structure_is_complete_and_json_serialisable() -> None:
    j, c = _strong_pair()
    e = score_pair(j, c, 0.7).explanation
    assert set(e) >= {
        "band",
        "overall_percent",
        "skills",
        "experience",
        "education",
        "semantic",
        "preferences",
        "weights",
        "summary",
        "qualification_floor_applied",
    }
    assert set(e["skills"]) == {"required", "preferred"}
    for part in e["skills"].values():
        assert set(part) == {"coverage", "matched", "related", "missing", "total"}
    assert set(e["experience"]) == {"status", "candidate_years", "required_min", "required_max", "text"}
    assert set(e["education"]) == {"status", "candidate_level", "required_level"}
    assert set(e["semantic"]) == {"band", "score", "cosine"}
    assert e["weights"] == WEIGHTS
    assert 0 <= e["overall_percent"] <= 100
    json.dumps(e)  # stored in a JSONB column


def test_explanation_lists_matched_related_and_missing_skills() -> None:
    j = job(required=[PY, MYSQL, GO], preferred=[DOCKER])
    c = candidate(skills=[PY, PG], declared_years=4)
    e = score_pair(j, c, 0.6).explanation
    req = e["skills"]["required"]
    assert [m["name"] for m in req["matched"]] == ["Python"]
    assert req["related"] == [{"required": "MySQL", "candidate_has": "PostgreSQL"}]
    assert req["missing"] == ["Go"] and req["total"] == 3
    assert e["skills"]["preferred"]["missing"] == ["Docker"]


def test_summary_text() -> None:
    j, c = _strong_pair()
    summary = score_pair(j, c, 0.8).explanation["summary"]
    assert summary.startswith("Strong match; covers 2 of 2 required skills")
    assert "semantic relevance high" in summary and summary.endswith(".")
    assert "missing" not in summary

    weak = score_pair(
        job(required=[PY, GO, MYSQL], min_experience_years=5), candidate(skills=[PG], declared_years=1), 0.3
    ).explanation["summary"]
    assert weak.startswith("Weak match") or weak.startswith("Partial match")
    assert (
        "(+1 related)" in weak
        and "below the experience requirement" in weak
        and "missing: Python, Go" in weak
    )


def test_summary_lists_at_most_four_missing_skills() -> None:
    many = [skill(f"S{i}") for i in range(7)]
    summary = score_pair(job(required=many, preferred=[]), candidate(skills=[]), 0.5).explanation["summary"]
    assert summary.count("S") >= 4 and "S4" not in summary.split("missing:")[1]


def test_candidate_years_fall_back_to_experience_history() -> None:
    c = candidate(declared_years=None, experiences=[exp("Dev", days_ago(365 * 6), None)])
    res = score_pair(job(min_experience_years=3), c, 0.5)
    assert res.explanation["experience"]["status"] == "MEETS"
    assert res.explanation["experience"]["candidate_years"] == pytest.approx(6.0, abs=0.2)
    unknown = score_pair(job(min_experience_years=3), candidate(declared_years=None, experiences=[]), 0.5)
    assert unknown.explanation["experience"]["status"] == "UNKNOWN"


def test_declared_years_win_over_history() -> None:
    c = candidate(declared_years=1.0, experiences=[exp("Dev", days_ago(365 * 10), None)])
    assert score_pair(job(min_experience_years=3), c, 0.5).explanation["experience"]["candidate_years"] == 1.0


def test_rounding_is_applied_to_stored_values() -> None:
    j, c = _strong_pair()
    res = score_pair(j, c, 0.5432109)
    assert (
        res.overall == round(res.overall, 4)
        and res.semantic == round(res.semantic, 4)
        and res.raw_cosine == round(res.raw_cosine, 4)
    )
    assert not math.isnan(res.overall)


def test_better_qualified_candidate_ranks_higher_for_the_same_job() -> None:
    j = job(required=[PY, PG, GO], preferred=[DOCKER], min_experience_years=3)
    strong = candidate(skills=[PY, PG, GO, DOCKER], declared_years=5)
    medium = candidate(skills=[PY, PG], declared_years=5)
    related = candidate(skills=[PY, MYSQL, GO], declared_years=5)
    weak = candidate(skills=[skill("Excel")], declared_years=1)
    scores = {
        n: score_pair(j, c, 0.6).overall
        for n, c in dict(strong=strong, related=related, medium=medium, weak=weak).items()
    }
    assert scores["strong"] > scores["related"] > scores["weak"]
    assert scores["strong"] > scores["medium"] > scores["weak"]
