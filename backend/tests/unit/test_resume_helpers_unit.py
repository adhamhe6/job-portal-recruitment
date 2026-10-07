"""Pure helpers around the résumé subsystem: apply-request shorthands, download headers, profile row builders, embedding text."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.resume import profile as ops
from app.resume.parser import parse_resume
from app.resume.pipeline import (
    EMBEDDING_PROSE_CHARS,
    EMBEDDING_ROLE_CHARS,
    EMBEDDING_SKILL_CHARS,
    embedding_components,
)
from app.schemas.resume import ApplyRequest, ExtractedPatch
from app.services.resumes import content_disposition
from tests.fixtures_resumes import BACKEND_TEXT

TODAY = date(2026, 10, 7)
CID = uuid.uuid4()


# --- ApplyRequest -------------------------------------------------------------------------------------------------------


def test_apply_request_canonical_and_shorthand_forms_are_equivalent():
    canonical = ApplyRequest(skills="all", fields=["summary", "headline"], overwrite=["summary"])
    shorthand = ApplyRequest.model_validate(
        {"skills": True, "summary": True, "headline": True, "overwrite": {"summary": True}}
    )
    assert shorthand == canonical
    everything = ApplyRequest.model_validate({"fields": ["location", "summary"], "overwrite": True})
    assert everything.overwrite == ["location", "summary"]
    assert ApplyRequest.model_validate({"skills": False, "experiences": None}).skills == []
    assert ApplyRequest().fields == [] and ApplyRequest().overwrite == []


@pytest.mark.parametrize(
    "body",
    [
        {"overwrite": ["summary"]},  # overwrite must be a subset of the selected fields
        {"fields": ["nationality"]},  # unknown / protected field names are not selectable
        {"skills": ["x"]},
        {"skills": [-1.5]},
        {"unknown": 1},
        {"fields": ["summary"], "overwrite": {"headline": True}},
    ],
)
def test_apply_request_rejects_nonsense(body):
    with pytest.raises(ValidationError):
        ApplyRequest.model_validate(body)


def test_extracted_patch_validation():
    ExtractedPatch.model_validate(
        {"skills": [{"index": 0, "remove": True}], "experiences": [{"index": 1, "start_date": "2020-01-01"}]}
    )
    for bad in (
        {"skills": [{"remove": True}]},  # index is required
        {"skills": [{"index": -1}]},
        {"experiences": [{"index": 0, "start_date": "2021-01-01", "end_date": "2020-01-01"}]},
        {"educations": [{"index": 0, "degree_level": "WIZARD"}]},
        {"languages": [{"index": 0, "proficiency": "GOOD"}]},
        {"contact": {"linkedin_url": "javascript:alert(1)"}},
        {"years_of_experience": 120},
        {"surprise": True},
    ):
        with pytest.raises(ValidationError):
            ExtractedPatch.model_validate(bad)


# --- download header --------------------------------------------------------------------------------------------------------


def test_content_disposition_is_header_safe_with_ascii_fallback_and_utf8_form():
    cd = content_disposition("Zoë Müller – CV.pdf", inline=False)
    assert cd.startswith(
        'attachment; filename="Zoe Muller  CV.pdf"; '
    )  # accents folded for the ASCII fallback
    assert "filename*=UTF-8''Zo%C3%AB%20M%C3%BCller%20%E2%80%93%20CV.pdf" in cd
    assert content_disposition("cv.pdf", inline=True).startswith("inline; ")
    nasty = content_disposition('a"b;c\\d.pdf', inline=False)
    assert (
        "\r" not in nasty and "\n" not in nasty and nasty.count('"') == 2
    )  # quotes in the name cannot break out of the header
    assert 'filename="resume"' in content_disposition(
        "日本語", inline=False
    )  # nothing ASCII left: generic fallback


# --- profile helpers -------------------------------------------------------------------------------------------------------


def test_split_name_and_norm():
    assert ops.split_name("Jane Doe") == ("Jane", "Doe")
    assert ops.split_name("Ludwig van Beethoven") == ("Ludwig", "van Beethoven")
    assert ops.split_name("Madonna") == ("Madonna", "-")
    assert ops.split_name(None) == ("Unnamed", "candidate")
    assert ops.norm("  Acme,  Corp.  ") == ops.norm("acme corp") == "acme corp"


def test_build_experience_enforces_the_table_rules():
    ok, why = ops.build_experience(
        CID, {"title": "Dev", "company": "Acme", "start_date": "2020-01-01", "end_date": "2021-01-01"}, TODAY
    )
    assert (
        why is None
        and ok is not None
        and ok.source.value == "RESUME"
        and ok.end_date == date(2021, 1, 1)
        and not ok.is_current
    )
    cur, _ = ops.build_experience(
        CID,
        {
            "title": "Dev",
            "company": "Acme",
            "start_date": "2020-01-01",
            "end_date": "2021-01-01",
            "is_current": True,
        },
        TODAY,
    )
    assert cur is not None and cur.end_date is None and cur.is_current  # CHECK current_has_no_end
    for item, reason in (
        ({"title": "Dev", "company": "Acme"}, "MISSING_START_DATE"),
        ({"company": "Acme", "start_date": "2020-01-01"}, "MISSING_TITLE"),
        ({"title": "Dev", "start_date": "2020-01-01"}, "MISSING_COMPANY"),
        ({"start_date": "2020-01-01"}, "MISSING_TITLE_COMPANY"),
        ({"title": "Dev", "company": "Acme", "start_date": "2030-01-01"}, "START_IN_FUTURE"),
        (
            {"title": "Dev", "company": "Acme", "start_date": "2020-05-01", "end_date": "2020-01-01"},
            "INVALID_DATES",
        ),
    ):
        row, why = ops.build_experience(CID, item, TODAY)
        assert row is None and why == reason, item


def test_build_education_certification_language_rules():
    edu, _ = ops.build_education(
        CID, {"institution": "TU Berlin", "degree_level": "BACHELOR", "start_year": 2010, "end_year": 2014}
    )
    assert edu is not None and edu.degree_level.value == "BACHELOR"
    assert ops.build_education(CID, {"institution": "TU Berlin"})[1] == "MISSING_DEGREE_LEVEL"
    assert (
        ops.build_education(CID, {"institution": "TU", "degree_level": "WIZARD"})[1] == "MISSING_DEGREE_LEVEL"
    )
    assert ops.build_education(CID, {"degree_level": "BACHELOR"})[1] == "MISSING_INSTITUTION"
    assert (
        ops.build_education(
            CID, {"institution": "X", "degree_level": "MASTER", "start_year": 2015, "end_year": 2012}
        )[1]
        == "INVALID_YEARS"
    )
    cert, _ = ops.build_certification(CID, {"name": "PMP", "issued_on": "2022-03-01", "issuer": "PMI"})
    assert cert is not None and cert.issued_on == date(2022, 3, 1)
    assert ops.build_certification(CID, {"name": " "})[1] == "MISSING_NAME"
    lang, _ = ops.build_language(CID, {"language": "German", "proficiency": "FLUENT"})
    assert lang is not None and lang.proficiency.value == "FLUENT"
    assert ops.build_language(CID, {"language": "German"})[1] == "MISSING_PROFICIENCY"


def test_years_value_and_as_date():
    assert float(ops.years_value({"years_of_experience": {"value": 7.84}}) or 0) == 7.8
    assert ops.years_value({"years_of_experience": {"value": 120}}) is None
    assert ops.years_value({"years_of_experience": None}) is None and ops.years_value({}) is None
    assert (
        ops.as_date("2020-02-03T10:00:00") == date(2020, 2, 3)
        and ops.as_date("garbage") is None
        and ops.as_date(None) is None
    )


# --- embedding text ---------------------------------------------------------------------------------------------------------


def test_embedding_components_are_bounded_and_contain_no_contact_details():
    parsed = parse_resume(BACKEND_TEXT * 20, today=TODAY)
    comps = embedding_components(parsed, BACKEND_TEXT)
    assert set(comps) == {"role", "skills", "prose"}
    assert (
        len(comps["role"]) <= EMBEDDING_ROLE_CHARS
        and len(comps["skills"]) <= EMBEDDING_SKILL_CHARS
        and len(comps["prose"]) <= EMBEDDING_PROSE_CHARS
    )
    assert sum(map(len, comps.values())) <= 1900  # "bounded excerpt, ~1800 characters"
    blob = " ".join(comps.values())
    assert "Python" in blob and "@" not in blob and "+49" not in blob and "linkedin" not in blob.lower()


def test_embedding_components_fall_back_to_the_raw_text_when_nothing_was_parsed():
    text = (
        "Totally unstructured prose about a career spent fixing things with soldering irons and patience. "
        * 40
    )
    comps = embedding_components(parse_resume(text, today=TODAY), text)
    assert (
        comps["role"] == "" and comps["skills"] == "" and 100 < len(comps["prose"]) <= EMBEDDING_PROSE_CHARS
    )
