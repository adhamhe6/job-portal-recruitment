"""Pure unit tests for the résumé parser (no database, no I/O)."""

from __future__ import annotations

import json
import time
from datetime import date

import pytest

from app.db.models import EducationLevel, LanguageProficiency
from app.resume.parser import (
    PARSER_VERSION,
    extract_contact,
    extract_skills_from_text,
    find_date_range,
    map_degree_level,
    parse_certifications,
    parse_educations,
    parse_experiences,
    parse_languages,
    parse_resume,
    split_lines,
    split_sections,
)
from tests.fixtures_resumes import BACKEND_TEXT, FRONTEND_TEXT, NURSE_TEXT

TODAY = date(2026, 10, 7)


def names(skills) -> set[str]:
    return {s.name for s in skills}


def skill(skills, name: str):
    return next(s for s in skills if s.name == name)


# --- sections ----------------------------------------------------------------------------------------------------


def test_parser_version_constant():
    assert PARSER_VERSION == "v1"
    assert parse_resume("x", today=TODAY).parser_version == "v1"


@pytest.mark.parametrize(
    ("heading", "key"),
    [
        ("Summary", "summary"),
        ("PROFESSIONAL SUMMARY", "summary"),
        ("Profile", "summary"),
        ("Objective", "summary"),
        ("Career Objective:", "summary"),
        ("Experience", "experience"),
        ("Work Experience", "experience"),
        ("EMPLOYMENT HISTORY", "experience"),
        ("Work History", "experience"),
        ("Professional Experience", "experience"),
        ("Education", "education"),
        ("EDUCATION & TRAINING", "education"),
        ("Skills", "skills"),
        ("Technical Skills", "skills"),
        ("Technologies", "skills"),
        ("Core Competencies", "skills"),
        ("Certifications", "certifications"),
        ("Licenses & Certifications", "certifications"),
        ("Languages", "languages"),
        ("Projects", "projects"),
        ("Personal Projects", "projects"),
        ("S K I L L S", "skills"),
    ],
)
def test_section_headings_detected(heading, key):
    sections, _, _ = split_sections([heading, "some content line"])
    assert sections[1].key == key
    assert sections[1].lines == ["some content line"]


def test_unknown_lines_are_not_headings_and_header_zone_precedes_first_heading():
    sections, content, owner = split_sections(["Jane Doe", "jane@example.com", "Skills", "Python"])
    assert [s.key for s in sections] == ["header", "skills"]
    assert sections[0].lines == ["Jane Doe", "jane@example.com"]
    assert content[2] == "" and owner[3] == "skills"


def test_inline_heading_with_content_and_programming_languages_label_is_not_spoken_languages():
    sections, _, _ = split_sections(["Skills", "Languages: Python, Go, SQL", "Frameworks: Django"])
    assert [s.key for s in sections] == ["header", "skills"]  # "Languages:" stayed inside the skills section
    sections, _, _ = split_sections(["Languages: English (Native), German (Fluent)"])
    assert sections[1].key == "languages"
    assert sections[1].lines == ["English (Native), German (Fluent)"]


def test_sections_detected_on_full_resume():
    r = parse_resume(BACKEND_TEXT, today=TODAY)
    assert {"summary", "skills", "experience", "education", "certifications", "languages"} <= set(r.sections)


# --- contact -----------------------------------------------------------------------------------------------------


def test_contact_full_header():
    r = parse_resume(BACKEND_TEXT, today=TODAY)
    c = r.contact
    assert c.name == "Jane Doe"
    assert c.email == "jane.doe@example.com"
    assert c.phone == "+49 151 2345 6789"
    assert c.linkedin_url == "https://www.linkedin.com/in/janedoe"
    assert c.github_url == "https://github.com/janedoe"
    assert c.location == "Berlin, Germany"


def test_contact_portfolio_and_credentials_in_name():
    r = parse_resume(
        FRONTEND_TEXT.replace("github.com/alexkim", "https://alexkim.dev | github.com/alexkim"), today=TODAY
    )
    assert r.contact.name == "Alex Kim" and r.contact.portfolio_url == "https://alexkim.dev"
    n = parse_resume(NURSE_TEXT, today=TODAY).contact
    assert n.name == "Maria Gonzalez"  # "MARIA GONZALEZ, RN": upper case folded, credential dropped
    assert n.phone == "(512) 555-0142" and n.location == "Austin, TX"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["Sam O'Neil-Smith", "sam@x.example"], "Sam O'Neil-Smith"),
        (["Dr. Ana María Pérez", "ana@x.example"], "Ana María Pérez"),
        (["Ludwig van Beethoven | l@x.example"], "Ludwig van Beethoven"),
        (["Name: Priya Nair"], "Priya Nair"),
        (["Curriculum Vitae", "Priya Nair"], "Priya Nair"),
        (["Software Engineer", "Priya Nair"], "Priya Nair"),  # a job title is not a name
        (["jane.doe@example.com", "+1 555 123 4567"], None),
        (["Résumé"], None),
        (["احمد علي", "ahmed@x.example"], "احمد علي"),
    ],
)
def test_name_detection(lines, expected):
    contact, _ = extract_contact(lines)
    assert contact.name == expected


def test_email_phone_and_location_edge_cases():
    c, _ = extract_contact(
        ["Jo Bloggs", "Tel: 2018-2021", "mail: JO.B@Example.COM", "Phone +44 (0)20 7946 0958", "London, UK"]
    )
    assert c.email == "jo.b@example.com"  # lower-cased
    assert c.phone == "+44 (0)20 7946 0958"  # a year range is not a phone number
    assert c.location == "London, UK"
    c, _ = extract_contact(["Jo Bloggs", "Backend Engineer, Python", "icon@2x.png"])
    assert c.location is None  # job title with a comma is not a location
    assert c.email is None  # image file names are not e-mail addresses
    c, _ = extract_contact(["Jo Bloggs", "Location: Bangalore, Karnataka"])
    assert c.location == "Bangalore, Karnataka"  # explicit label


def test_phone_not_taken_from_date_ranges():
    c, _ = extract_contact(["Jo Bloggs", "Jan 2018 - Dec 2021", "03/2019 - 08/2021", "2018-2021"])
    assert c.phone is None


def test_urls_from_hyperlink_targets():
    c, _ = extract_contact(
        ["Jo Bloggs", "LinkedIn | GitHub"],
        links=[
            "https://www.linkedin.com/in/jo-bloggs/",
            "https://github.com/jobloggs/repo",
            "mailto:jo@x.example",
        ],
    )
    assert c.linkedin_url == "https://www.linkedin.com/in/jo-bloggs"
    assert c.github_url == "https://github.com/jobloggs"
    assert c.email == "jo@x.example"


def test_no_protected_attributes_are_extracted():
    text = """Jane Doe
jane@example.com
Date of Birth: 12 March 1990
Gender: Female
Marital Status: Married
Nationality: German
Age: 34

Skills
Python, Django, SQL
"""
    payload = json.dumps(parse_resume(text, today=TODAY).to_dict()).lower()
    for token in (
        "1990",
        "female",
        "married",
        "german",
        "birth",
        "marital",
        "nationality",
        "gender",
        "age: 34",
    ):
        assert token not in payload


# --- dates -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "start", "end", "current"),
    [
        ("Jan 2020 – Present", date(2020, 1, 1), None, True),
        ("January 2020 - present", date(2020, 1, 1), None, True),
        ("Sept. 2018 — Mar 2021", date(2018, 9, 1), date(2021, 3, 31), False),
        ("2018-2021", date(2018, 1, 1), date(2021, 12, 31), False),
        ("2018 – 2021", date(2018, 1, 1), date(2021, 12, 31), False),
        ("03/2019 - 08/2021", date(2019, 3, 1), date(2021, 8, 31), False),
        ("3/2019 to 12/2020", date(2019, 3, 1), date(2020, 12, 31), False),
        ("2019-03 - 2021-08", date(2019, 3, 1), date(2021, 8, 31), False),
        ("2015 - Current", date(2015, 1, 1), None, True),
        ("since March 2022", date(2022, 3, 1), None, True),
        ("Feb 2020 to date", date(2020, 2, 1), None, True),
    ],
)
def test_date_ranges(line, start, end, current):
    r = find_date_range(f"Acme Corp | {line}", TODAY)
    assert r is not None
    assert (r.start, r.end, r.is_current) == (start, end, current)


@pytest.mark.parametrize(
    "line", ["no dates here", "Founded in 1850", "2030 - 2031", "Dec 2021 - Jan 2020", "version 3.2.1"]
)
def test_non_ranges_and_invalid_ranges_are_ignored(line):
    assert find_date_range(line, TODAY) is None


def test_end_dates_are_clamped_to_today():
    r = find_date_range("2024 - 2030", TODAY)
    assert r is not None and r.end == TODAY


# --- experience --------------------------------------------------------------------------------------------------


def test_experience_stacked_title_company_dates():
    lines = [
        "Senior Backend Engineer",
        "Acme Corp, Berlin | Jan 2020 – Present",
        "• Designed REST APIs",
        "• Mentored juniors",
        "Backend Developer — Initech GmbH     03/2016 - 12/2019",
        "• Built Django services",
    ]
    exps = parse_experiences(lines, TODAY)
    assert len(exps) == 2
    first, second = exps
    assert (first.title, first.company, first.location) == ("Senior Backend Engineer", "Acme Corp", "Berlin")
    assert first.start_date == date(2020, 1, 1) and first.end_date is None and first.is_current
    assert first.description == "Designed REST APIs\nMentored juniors"
    assert (second.title, second.company) == ("Backend Developer", "Initech GmbH")
    assert second.start_date == date(2016, 3, 1) and second.end_date == date(2019, 12, 31)
    assert second.description == "Built Django services"


def test_experience_inline_layouts():
    exps = parse_experiences(
        [
            "Software Engineer at Globex (2013-2016)",
            "Developed internal tools.",
            "Frontend Developer, Globex Corporation      2021 - Present",
            "Built a design system.",
            "Jan 2022 – Present   Data Analyst, Northwind Traders",
            "Wrote dashboards",
        ],
        TODAY,
    )
    assert [(e.title, e.company) for e in exps] == [
        ("Software Engineer", "Globex"),
        ("Frontend Developer", "Globex Corporation"),
        ("Data Analyst", "Northwind Traders"),
    ]
    assert exps[0].start_date == date(2013, 1, 1) and exps[0].end_date == date(2016, 12, 31)
    assert exps[2].is_current


def test_experience_company_first_and_dates_underneath():
    exps = parse_experiences(
        [
            "Acme Corp",
            "Senior Project Manager",
            "2017 - 2021",
            "Managed teams.",
            "Beta Industries",
            "Project Coordinator",
            "2014 - 2017",
        ],
        TODAY,
    )
    assert [(e.title, e.company) for e in exps] == [
        ("Senior Project Manager", "Acme Corp"),
        ("Project Coordinator", "Beta Industries"),
    ]
    assert exps[0].description == "Managed teams."


def test_experience_dates_on_own_line_then_header():
    exps = parse_experiences(
        [
            "2019 – 2021",
            "Junior Analyst",
            "Contoso Ltd.",
            "Wrote SQL reports",
            "2022 - Present",
            "Analyst",
            "Fabrikam",
        ],
        TODAY,
    )
    assert [(e.title, e.company) for e in exps] == [
        ("Junior Analyst", "Contoso Ltd."),
        ("Analyst", "Fabrikam"),
    ]


def test_bullets_with_dates_do_not_create_entries():
    exps = parse_experiences(
        [
            "Engineer, Acme   2020 - 2022",
            "• Migrated everything between 2019-2020 without downtime",
            "• Wrote docs",
        ],
        TODAY,
    )
    assert len(exps) == 1 and "between 2019-2020" in (exps[0].description or "")


def test_experience_without_any_dates_is_low_confidence_and_has_no_dates():
    exps = parse_experiences(
        ["Barista", "Corner Cafe", "• Served customers", "Cashier", "Mega Mart", "• Handled payments"], TODAY
    )
    assert len(exps) == 2
    assert all(e.start_date is None and e.confidence <= 0.4 for e in exps)


def test_experience_confidence_reflects_completeness():
    exps = parse_experiences(["Engineer, Acme   2020 - 2022", "Acme", "2018 - 2019"], TODAY)
    assert exps[0].confidence >= 0.8
    assert 0 < min(e.confidence for e in exps) <= 1


# --- skills -------------------------------------------------------------------------------------------------------


def test_skills_listed_vs_prose_confidence():
    r = parse_resume(BACKEND_TEXT, today=TODAY)
    py, celery = skill(r.skills, "Python"), skill(r.skills, "Celery")
    assert py.listed and py.confidence >= 0.9
    assert not celery.listed and celery.confidence < 0.7  # only mentioned in prose
    assert py.confidence > celery.confidence
    assert all(0 < s.confidence <= 1 for s in r.skills)


def test_ambiguous_skills_need_a_skills_context():
    prose = extract_skills_from_text(
        "Experience\nBuilt services in Go and Rust, analysed data in R, wrote C, used Excel and Swift daily."
    )
    assert not names(prose) & {"Go", "Rust", "R", "C", "Excel", "Swift"}
    listed = extract_skills_from_text("Skills\nGo, Rust, R, C, Swift, Excel, Ruby")
    assert {"Go", "Rust", "R", "C", "Swift", "Excel", "Ruby"} <= names(listed)
    # a skills-like list line outside a Skills section counts when most of it is recognised skills
    line = extract_skills_from_text("Experience\nTech: Python, Go, Docker, Kubernetes")
    assert "Go" in names(line)
    # ... but a sentence that merely contains commas does not
    sentence = extract_skills_from_text(
        "Experience\nI built Python, Docker and Kubernetes tooling for Go developers, mostly on weekends."
    )
    assert "Go" not in names(sentence) and "Python" in names(sentence)


def test_go_golang_exact_case_in_sentence_is_not_enough():
    for text in (
        "Experience\nWrote microservices in Go.",
        "Experience\nWrote microservices in Golang.",
        "Experience\nGo to market strategy",
    ):
        assert "Go" not in names(extract_skills_from_text(text)), text


def test_hyphenated_compounds_do_not_match_ambiguous_skills():
    found = extract_skills_from_text("Skills\nA go-getter attitude, R-squared analysis, Python, Docker")
    assert "Go" not in names(found) and "R" not in names(found) and {"Python", "Docker"} <= names(found)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("C++, C#, .NET, Node.js", {"C++", "C#", ".NET", "Node.js"}),
        ("CI/CD and A/B testing", {"CI/CD", "A/B Testing"}),
        ("NodeJS, Postgres, k8s, golang, ReactJS", {"Node.js", "PostgreSQL", "Kubernetes", "Go", "React"}),
        ("ASP.NET Core with C#", {"ASP.NET", "C#"}),
        ("Skills\nReact Native, React", {"React Native", "React"}),
    ],
)
def test_word_boundary_matching_and_aliases(text, expected):
    found = names(extract_skills_from_text(text if text.startswith("Skills") else f"Skills\n{text}"))
    assert expected <= found


def test_longest_match_wins_and_substrings_do_not_match():
    found = names(
        extract_skills_from_text(
            "Experience\nBuilt apps with React Native. Wrote JavaScript. Used MySQL and PostgreSQL."
        )
    )
    assert "React Native" in found and "React" not in found
    assert "JavaScript" in found and "Java" not in found
    assert "MySQL" in found and "SQL" not in found  # "MySQL" must not leak a bare "SQL"
    assert "C" not in found and "C++" not in found


def test_c_is_not_matched_inside_c_plus_plus_or_c_sharp():
    found = names(extract_skills_from_text("Skills\nC++, C#, Python"))
    assert "C" not in found and {"C++", "C#"} <= found


def test_weak_words_and_short_aliases_do_not_create_false_positives():
    text = "Experience\nAdministered 5 ml doses. Worked a 40 hr week with a rest period; monitoring patient vitals; react quickly; lean teams; epic workload."
    found = names(extract_skills_from_text(text))
    assert not found & {
        "Machine Learning",
        "REST APIs",
        "Monitoring",
        "React",
        "Process Improvement",
        "Electronic Health Records",
        "Employee Relations",
    }


def test_skills_in_emails_and_urls_are_ignored():
    found = names(
        extract_skills_from_text(
            "Contact\nSkills\nPython\nExperience\njohn.react@example.com github.com/u/go-tools"
        )
    )
    assert found == {"Python"}


def test_skills_from_ignored_sections_are_not_mined():
    found = names(
        extract_skills_from_text("Interests\nPython hiking, Kubernetes cooking\nReferences\nDocker Inc.")
    )
    assert found == set()


def test_skill_names_are_canonical_ontology_names():
    from app.matching.skills import ONTOLOGY

    canonical = {o.name for o in ONTOLOGY}
    r = parse_resume(BACKEND_TEXT + "\n" + FRONTEND_TEXT + "\n" + NURSE_TEXT, today=TODAY)
    assert names(r.skills) <= canonical


# --- education ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("B.Sc. in Computer Science", EducationLevel.BACHELOR),
        ("BSc Physics", EducationLevel.BACHELOR),
        ("Bachelor of Arts in History", EducationLevel.BACHELOR),
        ("Bachelor's degree", EducationLevel.BACHELOR),
        ("BS in Nursing", EducationLevel.BACHELOR),
        ("BSN, Nursing", EducationLevel.BACHELOR),
        ("B.Eng. Mechanical Engineering", EducationLevel.BACHELOR),
        ("MSc Data Science", EducationLevel.MASTER),
        ("M.Sc. in Physics", EducationLevel.MASTER),
        ("Master of Business Administration", EducationLevel.MASTER),
        ("MBA", EducationLevel.MASTER),
        ("Master's in Law", EducationLevel.MASTER),
        ("MS in Computer Science", EducationLevel.MASTER),
        ("PhD in Chemistry", EducationLevel.DOCTORATE),
        ("Ph.D. Economics", EducationLevel.DOCTORATE),
        ("Doctorate in Law", EducationLevel.DOCTORATE),
        ("Associate of Science", EducationLevel.ASSOCIATE),
        ("Associate degree in Nursing", EducationLevel.ASSOCIATE),
        ("High School Diploma", EducationLevel.HIGH_SCHOOL),
        ("Abitur", EducationLevel.HIGH_SCHOOL),
    ],
)
def test_degree_level_mapping(text, level):
    assert map_degree_level(text) == level.value
    assert level.value in {e.value for e in EducationLevel}


@pytest.mark.parametrize(
    "text", ["Cambridge, MA", "Certificate in Welding", "Studied at the school of hard knocks", "Diploma"]
)
def test_no_degree_level_guessed(text):
    assert map_degree_level(text) is None


def test_education_entries_institution_degree_field_and_years():
    edus = parse_educations(
        [
            "Technical University of Berlin",
            "B.Sc. in Computer Science, 2009 – 2013",
            "M.Sc. in Software Engineering — KTH Royal Institute of Technology (2013 - 2015)",
            "Reed College",
            "Bachelor of Arts in Economics, 2013-2017",
            "GPA: 3.8",
        ],
        TODAY,
    )
    assert len(edus) == 3
    a, b, c = edus
    assert (a.institution, a.degree_level, a.field_of_study, a.start_year, a.end_year) == (
        "Technical University of Berlin",
        "BACHELOR",
        "Computer Science",
        2009,
        2013,
    )
    assert (b.institution, b.degree_level, b.field_of_study) == (
        "KTH Royal Institute of Technology",
        "MASTER",
        "Software Engineering",
    )
    assert (b.start_year, b.end_year) == (2013, 2015)
    assert (c.institution, c.degree_level, c.field_of_study) == ("Reed College", "BACHELOR", "Economics")


def test_education_single_year_is_graduation_year_and_institution_without_keyword():
    edus = parse_educations(["BS in Computer Science, Stanford, 2012"], TODAY)
    assert len(edus) == 1
    assert edus[0].institution == "Stanford" and edus[0].end_year == 2012 and edus[0].start_year is None
    assert edus[0].degree_level == "BACHELOR"


def test_education_requires_something_recognisable():
    assert parse_educations(["Dean's list", "Relevant coursework: Algorithms"], TODAY) == []


# --- certifications & languages ----------------------------------------------------------------------------------


def test_certifications_from_section_and_known_patterns():
    certs = parse_certifications(
        [
            "AWS Certified Solutions Architect – Associate (Amazon Web Services), 2021",
            "Certified Kubernetes Administrator (CKA)",
            "• PMP, 2019",
        ],
        [],
    )
    by_name = {c.name: c for c in certs}
    aws = by_name["AWS Certified Solutions Architect – Associate"]
    assert aws.issuer == "Amazon Web Services" and aws.issued_year == 2021 and aws.issued_on is None
    assert "Certified Kubernetes Administrator (CKA)" in by_name
    assert by_name["PMP"].issued_year == 2019


def test_certification_month_year_gives_issued_on_and_known_patterns_found_outside_section():
    certs = parse_certifications(
        ["Scrum Master — Scrum Alliance, Mar 2022"], ["Experience", "Holds CISSP and PMP credentials"]
    )
    assert certs[0].issued_on == date(2022, 3, 1) and certs[0].issuer == "Scrum Alliance"
    found = {c.name for c in certs}
    assert {"CISSP", "PMP"} <= found
    assert all(
        c.confidence < 0.7 for c in certs if c.name in {"CISSP", "PMP"}
    )  # not in a certifications section


def test_certifications_deduplicated():
    certs = parse_certifications(
        ["Certified Kubernetes Administrator (CKA)"], ["Certified Kubernetes Administrator (CKA)", "CKA"]
    )
    assert len(certs) == 1


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "English (Native), German (Fluent), French - Basic",
            [("English", "NATIVE"), ("German", "FLUENT"), ("French", "BASIC")],
        ),
        ("Spanish: Conversational | Arabic - Native", [("Spanish", "CONVERSATIONAL"), ("Arabic", "NATIVE")]),
        ("German B2, English C1", [("German", "CONVERSATIONAL"), ("English", "FLUENT")]),
        ("English, German", [("English", None), ("German", None)]),
        ("• Mandarin (Professional working proficiency)", [("Mandarin", "FLUENT")]),
    ],
)
def test_languages_and_proficiency(line, expected):
    assert [(lang.language, lang.proficiency) for lang in parse_languages([line])] == expected
    for lang in parse_languages([line]):
        assert lang.proficiency is None or lang.proficiency in {p.value for p in LanguageProficiency}


def test_languages_ignores_non_languages():
    assert parse_languages(["Python, Docker, hiking"]) == []


# --- years, summary, headline ------------------------------------------------------------------------------------


def test_years_of_experience_is_union_of_employment_intervals():
    text = """Jo Bloggs
Experience
Engineer, Acme   Jan 2015 - Dec 2019
Engineer, Beta   Jan 2018 - Dec 2020
"""
    r = parse_resume(text, today=TODAY)
    yoe = r.years_of_experience
    assert yoe is not None and yoe.basis == "employment_history"
    assert yoe.value == pytest.approx(
        6.0, abs=0.1
    )  # 2015-2020 once; the 2018-2019 overlap is not double counted


def test_years_stated_when_no_dated_experience():
    r = parse_resume(
        "Jo Bloggs\nSummary\nDeveloper with over 7 years of professional experience in fintech.", today=TODAY
    )
    assert r.years_of_experience is not None
    assert (r.years_of_experience.basis, r.years_of_experience.value) == ("stated", 7.0)
    assert parse_resume("Jo Bloggs\nSummary\nCurious beginner.", today=TODAY).years_of_experience is None


@pytest.mark.parametrize(
    "phrase",
    ["8+ years of experience", "5 years' experience", "12 yrs experience", "3 years of Python experience"],
)
def test_stated_years_phrases(phrase):
    assert parse_resume(f"Summary\nEngineer with {phrase}.", today=TODAY).years_of_experience is not None


def test_summary_and_headline():
    r = parse_resume(BACKEND_TEXT, today=TODAY)
    assert r.summary is not None and r.summary.startswith("Backend engineer with 8+ years")
    assert r.headline == "Senior Backend Engineer" and (r.headline_confidence or 0) >= 0.7
    r2 = parse_resume("Priya Nair\nExperience\nAcme Corp\nSenior Project Manager\n2017 - 2021\n", today=TODAY)
    assert (
        r2.headline == "Senior Project Manager" and (r2.headline_confidence or 1) < 0.7
    )  # derived from the latest title only


# --- full documents ----------------------------------------------------------------------------------------------


def test_backend_resume_end_to_end():
    r = parse_resume(BACKEND_TEXT, today=TODAY)
    assert [e.title for e in r.experiences] == [
        "Senior Backend Engineer",
        "Backend Developer",
        "Software Engineer",
    ]
    assert r.experiences[0].is_current and r.experiences[2].end_date == date(2016, 12, 31)
    assert len(r.educations) == 1 and r.educations[0].degree_level == "BACHELOR"
    assert {c.name for c in r.certifications} >= {
        "AWS Certified Solutions Architect – Associate",
        "Certified Kubernetes Administrator (CKA)",
    }
    assert {(lang.language, lang.proficiency) for lang in r.languages} == {
        ("English", "FLUENT"),
        ("German", "NATIVE"),
        ("French", "BASIC"),
    }
    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "AWS", "Go"} <= names(r.skills)
    assert r.warnings == []


def test_frontend_resume_end_to_end():
    r = parse_resume(FRONTEND_TEXT, today=TODAY)
    assert r.contact.name == "Alex Kim" and r.contact.location == "San Francisco, CA"
    assert [(e.title, e.company) for e in r.experiences] == [
        ("Frontend Developer", "Globex Corporation"),
        ("UI Developer", "Initech Labs"),
    ]
    assert {"React", "TypeScript", "Next.js", "Tailwind CSS", "HTML", "CSS", "Figma"} <= names(r.skills)
    assert "Python" not in names(r.skills)
    assert r.educations[0].institution == "Stanford University"


def test_nurse_resume_end_to_end():
    r = parse_resume(NURSE_TEXT, today=TODAY)
    assert r.contact.name == "Maria Gonzalez"
    assert [(e.title, e.company) for e in r.experiences] == [
        ("ICU Registered Nurse", "St. David's Medical Center"),
        ("Staff Nurse", "Seton Hospital"),
    ]
    assert r.experiences[1].location == "Austin, TX"
    assert r.educations[0].degree_level == "BACHELOR" and r.educations[0].field_of_study == "Nursing"
    assert {"Patient Care", "Critical Care"} <= names(r.skills)
    assert not names(r.skills) & {
        "React",
        "Machine Learning",
        "Python",
    }  # "5 ml", "reading about React" (Interests) are noise
    assert {c.name for c in r.certifications} >= {
        "Registered Nurse (RN) License",
        "BLS Certified",
        "ACLS Certified",
    }


def test_to_dict_is_json_serialisable_and_stable():
    d = parse_resume(BACKEND_TEXT, today=TODAY).to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d == parse_resume(BACKEND_TEXT, today=TODAY).to_dict()  # deterministic
    assert set(d) >= {
        "contact",
        "skills",
        "experiences",
        "educations",
        "certifications",
        "languages",
        "years_of_experience",
        "sections",
    }


# --- robustness --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\n\t",
        "Just some random paragraph of text that is not a resume at all.",
        "Experience\n" + "x" * 50_000,
        "Skills\n" + ", ".join(["Python"] * 5000),
        "\x00\x01\x02 Experience \x03\nEngineer, Acme   2020 - 2022",
        "Education\n" + "University " * 3000,
        "Experience\n" + "2018 - " * 5000,
    ],
)
def test_parser_never_crashes_and_stays_fast(text):
    t0 = time.perf_counter()
    r = parse_resume(text, today=TODAY)
    assert time.perf_counter() - t0 < 5
    json.dumps(r.to_dict())


def test_non_resume_text_yields_empty_suggestions_not_guesses():
    r = parse_resume(
        "The quick brown fox jumps over the lazy dog. It was a sunny day in the park.", today=TODAY
    )
    assert r.contact.name is None and r.contact.email is None
    assert not (r.experiences or r.educations or r.certifications or r.languages or r.skills)
    assert r.years_of_experience is None and r.summary is None


def test_split_lines_caps_line_length():
    assert max(len(line) for line in split_lines("a" * 100_000)) <= 2000
