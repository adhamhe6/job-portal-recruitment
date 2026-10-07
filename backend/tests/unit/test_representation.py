"""Text representation, content hashes and experience arithmetic (pure logic)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.matching.embedder import EmbeddingError
from app.matching.representation import (
    COMPONENT_WEIGHTS,
    MAX_PROSE_CHARS,
    ExperienceItem,
    clean,
    combine_component_vectors,
    embed_components,
    embedding_hash,
    total_years_of_experience,
)
from tests.helpers_matching import candidate, days_ago, exp, job, skill

# --- clean() ----------------------------------------------------------------------------------------------


def test_clean_handles_none_and_blank() -> None:
    assert clean(None) == ""
    assert clean("") == ""
    assert clean("  \n\t  ") == ""


def test_clean_collapses_whitespace() -> None:
    assert clean("a   b\n\nc\t d") == "a b c d"


@pytest.mark.parametrize(
    "noise",
    [
        "jane.doe@example.com",
        "JANE+tag@sub.example.co.uk",
        "https://linkedin.com/in/jane-doe",
        "http://example.com/path?x=1&y=2",
        "www.janedoe.dev",
        "+49 170 1234567",
        "(415) 555-0199",
        "+1-415-555-0199",
        "0170 1234567",
    ],
)
def test_clean_strips_contact_details(noise: str) -> None:
    out = clean(f"Senior engineer {noise} building APIs")
    assert out == "Senior engineer building APIs"


def test_clean_strips_multiple_contacts_and_keeps_prose() -> None:
    text = "Reach me: a@b.com, +44 20 7946 0958 or https://x.io/me. I build Python services."
    out = clean(text)
    assert "@" not in out and "http" not in out and "7946" not in out
    assert "I build Python services." in out


def test_clean_keeps_ordinary_numbers() -> None:
    assert (
        clean("Reduced latency by 40% across 12 services in 3 regions")
        == "Reduced latency by 40% across 12 services in 3 regions"
    )


def test_clean_truncates_on_a_word_boundary() -> None:
    text = "alpha beta gamma delta epsilon"
    for limit in range(len("alpha"), len(text)):
        out = clean(text, limit)
        assert len(out) <= limit
        # never ends mid-word: the output is a whole-word prefix of the text
        assert text.startswith(out)
        assert text[len(out) : len(out) + 1] in ("", " ")
        # ... and it is the longest such prefix: the next word would not have fitted
        rest = text[len(out) :].split()
        assert not rest or len(out) + 1 + len(rest[0]) > limit


def test_clean_keeps_a_word_that_ends_exactly_at_the_limit() -> None:
    # "alpha beta" is exactly 10 characters and the next character is a space: nothing should be dropped.
    assert clean("alpha beta gamma", 10) == "alpha beta"
    assert clean("aaa bbb ccc", 7) == "aaa bbb"


def test_clean_returns_text_unchanged_when_it_fits() -> None:
    assert clean("short text", 10) == "short text"
    assert clean("short text", 100) == "short text"


def test_clean_single_overlong_word_is_hard_cut() -> None:
    assert clean("x" * 50, 10) == "x" * 10


def test_clean_is_idempotent() -> None:
    once = clean("  mail me  a@b.com  now \n", 20)
    assert clean(once, 20) == once


# --- total_years_of_experience -------------------------------------------------------------------------------


TODAY = date(2026, 1, 1)


def _years(*spans: tuple[date, date | None]) -> float:
    return total_years_of_experience([ExperienceItem("t", "c", s, e) for s, e in spans], today=TODAY)


def test_no_experience_is_zero() -> None:
    assert total_years_of_experience([], today=TODAY) == 0.0


def test_single_job() -> None:
    assert _years((date(2020, 1, 1), date(2022, 1, 1))) == pytest.approx(2.0, abs=0.05)


def test_non_overlapping_jobs_add_up() -> None:
    assert _years(
        (date(2015, 1, 1), date(2017, 1, 1)), (date(2018, 1, 1), date(2021, 1, 1))
    ) == pytest.approx(5.0, abs=0.1)


def test_overlapping_jobs_are_not_double_counted() -> None:
    # 2015-2019 and 2017-2021 overlap for two years: union = 6 years, not 8.
    assert _years(
        (date(2015, 1, 1), date(2019, 1, 1)), (date(2017, 1, 1), date(2021, 1, 1))
    ) == pytest.approx(6.0, abs=0.1)


def test_fully_contained_job_adds_nothing() -> None:
    assert _years(
        (date(2010, 1, 1), date(2020, 1, 1)), (date(2012, 1, 1), date(2013, 1, 1))
    ) == pytest.approx(10.0, abs=0.1)


def test_touching_jobs_merge_without_gap() -> None:
    assert _years(
        (date(2018, 1, 1), date(2019, 1, 1)), (date(2019, 1, 1), date(2020, 1, 1))
    ) == pytest.approx(2.0, abs=0.05)


def test_open_ended_job_runs_until_today() -> None:
    assert _years((date(2021, 1, 1), None)) == pytest.approx(5.0, abs=0.05)


def test_open_ended_job_overlapping_a_closed_one() -> None:
    assert _years((date(2019, 1, 1), date(2022, 1, 1)), (date(2021, 1, 1), None)) == pytest.approx(
        7.0, abs=0.1
    )


def test_order_of_input_does_not_matter() -> None:
    a = (date(2010, 1, 1), date(2012, 1, 1))
    b = (date(2011, 1, 1), date(2015, 1, 1))
    c = (date(2018, 1, 1), None)
    assert _years(a, b, c) == _years(c, b, a) == _years(b, c, a)


def test_inverted_and_future_spans_are_ignored() -> None:
    assert _years((date(2022, 1, 1), date(2020, 1, 1))) == 0.0  # end before start
    assert _years((date(2030, 1, 1), None)) == 0.0  # starts after "today"


def test_result_is_rounded_to_one_decimal() -> None:
    value = _years((date(2020, 1, 1), date(2021, 5, 17)))
    assert value == round(value, 1)


# --- feature hashes ---------------------------------------------------------------------------------------------


def test_job_hash_is_stable_across_instances_and_calls() -> None:
    assert job().feature_hash() == job().feature_hash()
    j = job()
    assert j.feature_hash() == j.feature_hash()
    assert len(j.feature_hash()) == 64


def test_job_hash_ignores_identity_but_not_content() -> None:
    base = job().feature_hash()
    assert job(job_id="other", company_id="other").feature_hash() == base  # identity is not a feature
    changed = {
        "title": "Frontend Engineer",
        "summary": "Something else entirely.",
        "responsibilities": "Different duties.",
        "min_experience_years": 5.0,
        "max_experience_years": 8.0,
        "experience_level": "SENIOR",
        "min_education_level": "BACHELOR",
        "location": "Munich, Germany",
        "workplace_type": "REMOTE",
        "employment_type": "CONTRACT",
        "required": [skill("Python")],
        "preferred": [],
    }
    for field, value in changed.items():
        assert job(**{field: value}).feature_hash() != base, f"hash ignores {field}"


def test_job_hash_reacts_to_skill_minimum_years_but_not_order() -> None:
    a = job(required=[skill("Python"), skill("Go")])
    b = job(required=[skill("Go"), skill("Python")])
    assert a.feature_hash() == b.feature_hash()
    assert job(required=[skill("Python", years=5), skill("Go")]).feature_hash() != a.feature_hash()


def test_candidate_hash_stable_and_sensitive() -> None:
    base = candidate().feature_hash()
    assert candidate().feature_hash() == base
    assert candidate(candidate_id="someone-else").feature_hash() == base
    changed = {
        "headline": "Data scientist",
        "summary": "Trains models.",
        "skills": [skill("Python")],
        "experiences": [exp("Engineer", date(2020, 1, 1), None)],
        "education_levels": ["MASTER"],
        "declared_years": 9.0,
        "location": "Paris, France",
        "remote_preference": "REMOTE",
        "employment_preference": "CONTRACT",
        "resume_excerpt": "Extra résumé text",
        "certifications": ["AWS Certified"],
    }
    for field, value in changed.items():
        assert candidate(**{field: value}).feature_hash() != base, f"hash ignores {field}"


def test_candidate_hash_and_text_do_not_depend_on_row_load_order() -> None:
    e1, e2 = (
        exp("Engineer", date(2020, 1, 1), None, description="one"),
        exp("Analyst", date(2018, 1, 1), date(2019, 1, 1), description="two"),
    )
    e3 = exp(
        "Tester", date(2020, 1, 1), None, description="three"
    )  # same start date as e1: ties must be broken deterministically
    a = candidate(
        skills=[skill("Python"), skill("Go")],
        education_levels=["BACHELOR", "MASTER"],
        education_text=["BSc CS", "MSc AI"],
        certifications=["AWS", "CKA"],
        experiences=[e1, e2, e3],
    )
    b = candidate(
        skills=[skill("Go"), skill("Python")],
        education_levels=["MASTER", "BACHELOR"],
        education_text=["MSc AI", "BSc CS"],
        certifications=["CKA", "AWS"],
        experiences=[e3, e2, e1],
    )
    assert a.components() == b.components()
    assert a.feature_hash() == b.feature_hash()


def test_embedding_hash_depends_on_text_model_and_version() -> None:
    comps = {"role": "a", "skills": "b", "prose": "c"}
    base = embedding_hash(comps, "m", "v1")
    assert embedding_hash(dict(comps), "m", "v1") == base
    assert embedding_hash({**comps, "prose": "d"}, "m", "v1") != base
    assert embedding_hash(comps, "m2", "v1") != base
    assert embedding_hash(comps, "m", "v2") != base


# --- components: only job-relevant text, never identity ---------------------------------------------------------------


def test_job_components_structure_and_content() -> None:
    comps = job(experience_level="SENIOR").components()
    assert set(comps) == {"role", "skills", "prose"}
    assert "Backend Engineer" in comps["role"] and "Senior level" in comps["role"]
    assert comps["skills"] == "PostgreSQL, Python, Docker"  # required (sorted) then preferred (sorted)
    assert "Design APIs" in comps["prose"]


def test_job_components_without_level_or_preferred_skills() -> None:
    comps = job(experience_level=None, preferred=[]).components()
    assert comps["role"] == "Backend Engineer"
    assert comps["skills"] == "PostgreSQL, Python"
    only_pref = job(required=[], preferred=[skill("Docker")]).components()
    assert only_pref["skills"] == "Docker"


def test_candidate_components_never_leak_contact_data() -> None:
    cand = candidate(
        headline="Engineer",
        summary="Reach me at jane.doe@example.com or +49 170 1234567, portfolio https://jane.dev",
        experiences=[
            exp(
                "Backend Engineer",
                date(2020, 1, 1),
                None,
                description="Contact: boss@acme.com, www.acme.com/team",
            ),
        ],
        resume_excerpt="Phone (415) 555-0199 email jane@work.org",
    )
    blob = " ".join(cand.components().values())
    for needle in ("@", "http", "www.", "7946", "1234567", "555-0199", "jane.doe", "boss"):
        assert needle not in blob, needle


def test_candidate_components_do_not_carry_any_identity_field() -> None:
    cand = candidate()
    fields = {f for f in type(cand).__dataclass_fields__}
    assert not (
        {"name", "first_name", "last_name", "display_name", "email", "phone", "gender", "age", "photo"}
        & fields
    )


def test_candidate_components_use_recent_titles_in_order() -> None:
    cand = candidate(
        experiences=[
            exp("Intern", days_ago(3000), days_ago(2800)),
            exp("Senior Engineer", days_ago(200), None),
            exp("Engineer", days_ago(1500), days_ago(300)),
        ]
    )
    assert cand.recent_titles(2) == ["Senior Engineer", "Engineer"]
    assert cand.components()["role"].startswith("Backend engineer. Senior Engineer, Engineer")


def test_candidate_role_component_is_cleaned_of_contact_data() -> None:
    cand = candidate(
        headline="Engineer jane@x.com",
        experiences=[exp("Developer (+49 170 1234567)", days_ago(500), None)],
    )
    role = cand.components()["role"]
    assert "@" not in role and "1234567" not in role


def test_prose_is_bounded() -> None:
    long = "word " * 5000
    prose = candidate(summary=long, resume_excerpt=long).components()["prose"]
    assert len(prose) <= MAX_PROSE_CHARS
    assert len(job(summary=long).components()["prose"]) <= MAX_PROSE_CHARS


def test_empty_components_are_empty_strings() -> None:
    empty = candidate(headline="", summary="", skills=[], experiences=[])
    assert empty.components() == {"role": "", "skills": "", "prose": ""}


# --- vector combination ------------------------------------------------------------------------------------------------


def test_component_weights_sum_to_one() -> None:
    assert sum(COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)


def test_combine_component_vectors_is_unit_length_and_renormalises_weights() -> None:
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(3, 8)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    full = combine_component_vectors(["role", "skills", "prose"], vectors)
    assert full.dtype == np.float32 and np.linalg.norm(full) == pytest.approx(1.0, abs=1e-5)
    # a single component collapses to that component itself
    only = combine_component_vectors(["skills"], vectors[1:2])
    assert np.allclose(only, vectors[1], atol=1e-6)
    expected = (0.35 * vectors[0] + 0.30 * vectors[2]) / np.linalg.norm(0.35 * vectors[0] + 0.30 * vectors[2])
    assert np.allclose(combine_component_vectors(["role", "prose"], vectors[[0, 2]]), expected, atol=1e-5)


def test_combine_rejects_degenerate_vectors() -> None:
    vectors = np.array([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32)
    with pytest.raises(EmbeddingError):
        combine_component_vectors(["role", "role"], vectors)  # equal weights cancel exactly


async def test_embed_components_skips_blank_parts_and_rejects_all_blank() -> None:
    vec = await embed_components({"role": "Backend engineer", "skills": "   ", "prose": ""})
    assert vec.shape == (256,) and np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)
    with pytest.raises(EmbeddingError):
        await embed_components({"role": "", "skills": "  ", "prose": ""})
