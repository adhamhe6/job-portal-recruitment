"""Request-schema validation rules (no HTTP, no database)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.application import ApplicationCreate, NoteCreate, StatusChange
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterCandidateRequest,
    RegisterEmployerRequest,
    UpdateMeRequest,
    validate_password_strength,
)
from app.schemas.candidate import (
    CandidateSkillIn,
    CandidateSkillUpdate,
    CertificationIn,
    EducationIn,
    ExperienceIn,
    LanguageIn,
    ProfileUpdate,
)
from app.schemas.common import PageParams, validate_http_url, validate_phone
from app.schemas.company import AdminUserCreate, CompanyCreate, CompanyUpdate, MemberCreate, MemberUpdate
from app.schemas.job import JobCreate, JobSkillIn, JobUpdate
from app.schemas.skill import SkillCreate

TODAY = date.today()
DESC = "A perfectly reasonable job description."


def errors(model: type, **data: Any) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as exc:
        model(**data)
    return exc.value.errors()


def fields_in_error(model: type, **data: Any) -> set[str]:
    return {str(e["loc"][0]) for e in errors(model, **data)}


# --- passwords ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        "CorrectHorse42",
        "abcdefghi1",
        "1234567890a",
        "Passw0rd!!",
        "ünïcödé-pass-9",
        "a" * 127 + "1",
        "a1" * 64,
    ],
)
def test_acceptable_passwords(password: str) -> None:
    assert validate_password_strength(password) == password


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Short1", "at least 10"),
        ("abcdefghi1"[:9], "at least 10"),
        ("", "at least 10"),
        ("onlyletterslong", "letter and one digit"),
        ("12345678901234", "letter and one digit"),
        ("!!!!!!!!!!!!!!", "letter and one digit"),
        ("a" * 129 + "1", "at most 128"),
        ("a1" * 65, "at most 128"),
    ],
)
def test_rejected_passwords(password: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_password_strength(password)


def test_password_length_boundaries() -> None:
    assert len(validate_password_strength("a" * 9 + "1")) == 10
    assert len(validate_password_strength("a" * 127 + "1")) == 128
    with pytest.raises(ValueError, match="at least 10"):
        validate_password_strength("a" * 8 + "1")


@pytest.mark.parametrize(
    ("model", "field"), [(RegisterCandidateRequest, "password"), (RegisterEmployerRequest, "password")]
)
def test_weak_password_is_reported_against_its_field(model: type, field: str) -> None:
    data = {
        "email": "a@example.com",
        "password": "weak",
        "first_name": "A",
        "last_name": "B",
        "company_name": "Acme Inc",
    }
    assert fields_in_error(model, **data) == {field}


def test_change_password_validates_only_the_new_password() -> None:
    assert fields_in_error(ChangePasswordRequest, current_password="x", new_password="short") == {
        "new_password"
    }
    assert (
        ChangePasswordRequest(current_password="x", new_password="Longenough1").new_password == "Longenough1"
    )


# --- phone numbers ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    ["+49 170 1234567", "(415) 555-0199", "+1-415-555-0199", "123456", "030 1234567", "+44.20.7946.0958"],
)
def test_valid_phone_numbers(phone: str) -> None:
    assert validate_phone(phone) == phone


@pytest.mark.parametrize(
    "phone", ["abc", "12345", "phone: 123456", "+49 170 12345a", "1" * 40, "<script>", "123 456 789; DROP"]
)
def test_invalid_phone_numbers(phone: str) -> None:
    with pytest.raises(ValueError, match="valid phone"):
        validate_phone(phone)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_phone_becomes_none(blank: str | None) -> None:
    assert validate_phone(blank) is None


def test_phone_is_trimmed_and_validated_wherever_it_is_accepted() -> None:
    reg = RegisterCandidateRequest(
        email="a@example.com",
        password="Longenough1",
        first_name="A",
        last_name="B",
        phone=" +49 170 1234567 ",
    )
    assert reg.phone == "+49 170 1234567"
    assert "phone" in fields_in_error(
        RegisterCandidateRequest,
        email="a@example.com",
        password="Longenough1",
        first_name="A",
        last_name="B",
        phone="abc",
    )
    assert "phone" in fields_in_error(UpdateMeRequest, phone="abc")
    assert "phone" in fields_in_error(ProfileUpdate, phone="abc")
    assert "phone" in fields_in_error(
        MemberCreate,
        email="a@example.com",
        password="Longenough1",
        first_name="A",
        last_name="B",
        phone="abc",
    )
    assert "phone" in fields_in_error(
        AdminUserCreate,
        email="a@example.com",
        password="Longenough1",
        first_name="A",
        last_name="B",
        role="CANDIDATE",
        phone="abc",
    )


# --- names / e-mail / login -----------------------------------------------------------------------------------------------------


def test_names_are_trimmed_and_must_not_be_blank() -> None:
    ok = RegisterCandidateRequest(
        email="a@example.com", password="Longenough1", first_name="  Ada ", last_name=" Lovelace  "
    )
    assert (ok.first_name, ok.last_name) == ("Ada", "Lovelace")
    base = {"email": "a@example.com", "password": "Longenough1"}
    assert fields_in_error(RegisterCandidateRequest, **base, first_name="   ", last_name="B") == {
        "first_name"
    }
    assert fields_in_error(RegisterCandidateRequest, **base, first_name="A", last_name="") == {"last_name"}
    assert fields_in_error(RegisterCandidateRequest, **base, first_name="x" * 101, last_name="B") == {
        "first_name"
    }


@pytest.mark.parametrize(
    "email", ["", "plain", "a@", "@example.com", "a b@example.com", "a@@example.com", "a@example"]
)
def test_invalid_emails(email: str) -> None:
    assert fields_in_error(LoginRequest, email=email, password="x") == {"email"}


def test_login_password_bounds() -> None:
    assert fields_in_error(LoginRequest, email="a@example.com", password="") == {"password"}
    assert fields_in_error(LoginRequest, email="a@example.com", password="x" * 129) == {"password"}
    assert LoginRequest(email="a@example.com", password="x").password == "x"  # login never enforces strength


def test_update_me_allows_partial_updates() -> None:
    assert UpdateMeRequest(first_name="New").last_name is None
    assert fields_in_error(UpdateMeRequest, first_name="") == {"first_name"}


def test_employer_registration_company_rules() -> None:
    base = {"email": "a@example.com", "password": "Longenough1", "first_name": "A", "last_name": "B"}
    assert fields_in_error(RegisterEmployerRequest, **base, company_name="A") == {"company_name"}
    assert RegisterEmployerRequest(**base, company_name="  Acme  ").company_name == "Acme"
    assert fields_in_error(RegisterEmployerRequest, **base, company_name="Acme", company_size="HUGE") == {
        "company_size"
    }
    assert fields_in_error(
        RegisterEmployerRequest, **base, company_name="Acme", company_website="javascript:alert(1)"
    ) == {"company_website"}
    assert (
        RegisterEmployerRequest(
            **base, company_name="Acme", company_website="https://acme.example.com"
        ).company_website
        == "https://acme.example.com"
    )


# --- URLs ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/a?b=1#c",
        "https://sub.example.co.uk/in/jane-doe",
        "http://localhost:8080",
    ],
)
def test_valid_urls(url: str) -> None:
    assert validate_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://example.com",
        "example.com",
        "www.example.com",
        "https://",
        "http://",
        "//example.com",
        "https://exa mple.com",
        "data:text/html;base64,AAAA",
        "https://example.com/" + "a" * 500,
        "mailto:a@example.com",
        "not a url",
    ],
)
def test_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError, match="valid http"):
        validate_http_url(url)


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_blank_url_becomes_none(blank: str | None) -> None:
    assert validate_http_url(blank) is None


def test_urls_are_validated_on_profiles_certifications_and_companies() -> None:
    assert fields_in_error(ProfileUpdate, portfolio_url="javascript:alert(1)") == {"portfolio_url"}
    assert fields_in_error(ProfileUpdate, linkedin_url="linkedin.com/in/me") == {"linkedin_url"}
    assert fields_in_error(ProfileUpdate, github_url="https://") == {"github_url"}
    assert ProfileUpdate(github_url=" https://github.com/me ").github_url == "https://github.com/me"
    assert fields_in_error(CertificationIn, name="AWS", credential_url="javascript:x") == {"credential_url"}
    assert fields_in_error(CompanyCreate, name="Acme", website="acme.com") == {"website"}
    assert fields_in_error(CompanyCreate, name="Acme", logo_url="ftp://x.com/logo.png") == {"logo_url"}
    assert fields_in_error(CompanyUpdate, website="not a url") == {"website"}
    assert CompanyUpdate(website="").website is None


# --- profile ranges ---------------------------------------------------------------------------------------------------------------


def test_profile_update_is_fully_optional_and_tracks_explicit_nulls() -> None:
    assert ProfileUpdate().model_dump(exclude_unset=True) == {}
    assert ProfileUpdate(headline=None).model_dump(exclude_unset=True) == {"headline": None}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("years_experience", -1),
        ("years_experience", 70.1),
        ("years_experience", "abc"),
        ("years_experience", Decimal("1.55")),
        ("expected_salary", -5),
        ("salary_currency", "US"),
        ("salary_currency", "USDX"),
        ("remote_preference", "ANYWHERE"),
        ("availability", "SOMEDAY"),
        ("employment_preference", "SLAVERY"),
        ("headline", "x" * 201),
        ("summary", "x" * 5001),
        ("location", "x" * 201),
        ("is_searchable", "maybe"),
    ],
)
def test_profile_field_rejections(field: str, value: Any) -> None:
    assert fields_in_error(ProfileUpdate, **{field: value}) == {field}


def test_profile_boundaries_and_normalisation() -> None:
    assert ProfileUpdate(years_experience=0).years_experience == 0
    assert ProfileUpdate(years_experience=70).years_experience == 70
    assert ProfileUpdate(expected_salary=0).expected_salary == 0
    assert ProfileUpdate(salary_currency="eur").salary_currency == "EUR"


# --- experience / education / certification / language ---------------------------------------------------------------------------------


def test_experience_current_job_rule_clears_the_end_date() -> None:
    e = ExperienceIn(
        title="Dev",
        company_name="Acme",
        start_date=TODAY - timedelta(days=400),
        is_current=True,
        end_date=TODAY - timedelta(days=10),
    )
    assert e.end_date is None and e.is_current is True


def test_experience_dates() -> None:
    start = TODAY - timedelta(days=400)
    assert (
        ExperienceIn(title="Dev", company_name="A", start_date=start, end_date=start).end_date == start
    )  # one-day job is fine
    assert ExperienceIn(title="Dev", company_name="A", start_date=start).end_date is None
    assert ExperienceIn(title="Dev", company_name="A", start_date=TODAY).start_date == TODAY
    msgs = " ".join(
        e["msg"]
        for e in errors(
            ExperienceIn, title="Dev", company_name="A", start_date=start, end_date=start - timedelta(days=1)
        )
    )
    assert "end_date must not be before start_date" in msgs
    msgs = " ".join(
        e["msg"]
        for e in errors(ExperienceIn, title="Dev", company_name="A", start_date=TODAY + timedelta(days=1))
    )
    assert "cannot be in the future" in msgs


@pytest.mark.parametrize(("title", "company"), [("", "A"), ("Dev", ""), ("x" * 201, "A"), ("Dev", "x" * 201)])
def test_experience_required_text_fields(title: str, company: str) -> None:
    assert errors(ExperienceIn, title=title, company_name=company, start_date=TODAY)


def test_education_years() -> None:
    assert (
        EducationIn(institution="MIT", degree_level="MASTER", start_year=2010, end_year=2010).end_year == 2010
    )
    assert (
        EducationIn(institution="MIT", degree_level="MASTER", start_year=1950, end_year=2100).start_year
        == 1950
    )
    assert EducationIn(institution="MIT", degree_level="MASTER").start_year is None
    assert "end_year must not be before start_year" in " ".join(
        e["msg"]
        for e in errors(EducationIn, institution="MIT", degree_level="MASTER", start_year=2012, end_year=2010)
    )
    for bad in (1949, 2101, 0, -5):
        assert fields_in_error(EducationIn, institution="MIT", degree_level="MASTER", start_year=bad) == {
            "start_year"
        }
    assert fields_in_error(EducationIn, institution="MIT", degree_level="PHD") == {"degree_level"}
    assert fields_in_error(EducationIn, institution="", degree_level="MASTER") == {"institution"}


def test_certification_dates() -> None:
    assert CertificationIn(name="CKA", issued_on=TODAY, expires_on=TODAY).name == "CKA"
    assert CertificationIn(name="CKA").issued_on is None
    assert "expires_on must not be before issued_on" in " ".join(
        e["msg"]
        for e in errors(CertificationIn, name="CKA", issued_on=TODAY, expires_on=TODAY - timedelta(days=1))
    )


def test_language_rules() -> None:
    assert LanguageIn(language="German", proficiency="FLUENT").language == "German"
    assert fields_in_error(LanguageIn, language="G", proficiency="FLUENT") == {"language"}
    assert fields_in_error(LanguageIn, language="German", proficiency="PERFECT") == {"proficiency"}


# --- skills -----------------------------------------------------------------------------------------------------------------------------


def test_skill_reference_needs_an_id_or_a_name() -> None:
    assert errors(CandidateSkillIn)
    assert errors(CandidateSkillIn, name="   ")
    assert CandidateSkillIn(name="Python").skill_id is None
    assert CandidateSkillIn(skill_id="00000000-0000-0000-0000-000000000001").name is None
    assert errors(JobSkillIn)
    assert errors(JobSkillIn, name="")


@pytest.mark.parametrize("years", [-1, 70.5, 71, "x"])
def test_skill_years_bounds(years: Any) -> None:
    assert fields_in_error(CandidateSkillIn, name="Python", years_experience=years) == {"years_experience"}
    assert fields_in_error(CandidateSkillUpdate, years_experience=years) == {"years_experience"}


def test_skill_proficiency_values() -> None:
    assert CandidateSkillIn(name="Python", proficiency="EXPERT").proficiency == "EXPERT"
    assert fields_in_error(CandidateSkillIn, name="Python", proficiency="GURU") == {"proficiency"}
    assert fields_in_error(CandidateSkillUpdate, status="MAYBE") == {"status"}


def test_job_skill_min_years_bounds() -> None:
    assert JobSkillIn(name="Python", min_years=30).min_years == 30
    assert fields_in_error(JobSkillIn, name="Python", min_years=31) == {"min_years"}
    assert fields_in_error(JobSkillIn, name="Python", requirement="NICE") == {"requirement"}
    assert JobSkillIn(name="Python").requirement == "REQUIRED"


def test_new_skill_names_are_whitespace_normalised() -> None:
    assert SkillCreate(name="  Apache   Kafka ").name == "Apache Kafka"
    assert fields_in_error(SkillCreate, name="   ") == {"name"}
    assert fields_in_error(SkillCreate, name="x" * 101) == {"name"}


# --- jobs ------------------------------------------------------------------------------------------------------------------------------------


def job(**overrides: Any) -> dict[str, Any]:
    return {"title": "Backend Engineer", "description": DESC, **overrides}


def test_job_create_minimal() -> None:
    j = JobCreate(**job())
    assert (j.employment_type, j.workplace_type, j.salary_currency, j.min_experience_years, j.skills) == (
        "FULL_TIME",
        "ONSITE",
        "USD",
        0,
        [],
    )


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"title": "ab"}, "title"),
        ({"title": ""}, "title"),
        ({"title": "      "}, "title"),
        ({"title": " a  "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"description": "short"}, "description"),
        ({"description": "          "}, "description"),
        ({"description": "x" * 20001}, "description"),
        ({"employment_type": "SLAVE"}, "employment_type"),
        ({"workplace_type": "MOON"}, "workplace_type"),
        ({"experience_level": "GOD"}, "experience_level"),
        ({"min_education_level": "PHD"}, "min_education_level"),
        ({"salary_min": -1}, "salary_min"),
        ({"salary_currency": "US"}, "salary_currency"),
        ({"min_experience_years": -1}, "min_experience_years"),
        ({"min_experience_years": 71}, "min_experience_years"),
        ({"max_experience_years": 71}, "max_experience_years"),
        ({"application_deadline": (TODAY - timedelta(days=1)).isoformat()}, "application_deadline"),
        ({"application_deadline": "tomorrow"}, "application_deadline"),
        ({"hiring_manager_id": "not-a-uuid"}, "hiring_manager_id"),
        ({"skills": [{"name": f"S{i}"} for i in range(41)]}, "skills"),
        ({"skills": [{}]}, "skills"),
    ],
)
def test_job_create_single_field_rejections(overrides: dict[str, Any], field: str) -> None:
    assert fields_in_error(JobCreate, **job(**overrides)) == {field}


def test_job_cross_field_ranges() -> None:
    msgs = " ".join(e["msg"] for e in errors(JobCreate, **job(salary_min=100, salary_max=99)))
    assert "salary_max must be greater than or equal to salary_min" in msgs
    msgs = " ".join(
        e["msg"] for e in errors(JobCreate, **job(min_experience_years=5, max_experience_years=4))
    )
    assert "max_experience_years must be greater than or equal to min_experience_years" in msgs
    assert JobCreate(**job(salary_min=100, salary_max=100)).salary_max == 100  # equal bounds are fine
    assert JobCreate(**job(salary_max=50)).salary_min is None  # open-ended on one side is fine
    assert JobCreate(**job(min_experience_years=5, max_experience_years=5)).max_experience_years == 5


def test_job_normalisation() -> None:
    j = JobCreate(
        **job(title="  Senior   Backend\tEngineer ", description="  " + DESC + "  ", salary_currency="eur")
    )
    assert j.title == "Senior Backend Engineer" and j.description == DESC and j.salary_currency == "EUR"


def test_job_deadline_today_is_allowed() -> None:
    assert JobCreate(**job(application_deadline=TODAY)).application_deadline == TODAY


def test_job_decimal_precision_limits() -> None:
    assert fields_in_error(JobCreate, **job(salary_min=Decimal("1.234"))) == {"salary_min"}
    assert fields_in_error(JobCreate, **job(min_experience_years=Decimal("1.25"))) == {"min_experience_years"}
    assert fields_in_error(JobCreate, **job(salary_min=Decimal("1" * 11 + ".00"))) == {"salary_min"}


def test_job_update_is_partial_but_validates_what_it_gets() -> None:
    assert JobUpdate().model_dump(exclude_unset=True) == {}
    assert JobUpdate(title="  New   title ").title == "New title"
    assert fields_in_error(JobUpdate, title="     ") == {"title"}
    assert fields_in_error(JobUpdate, title="ab") == {"title"}
    assert fields_in_error(JobUpdate, description="         ") == {"description"}
    assert fields_in_error(JobUpdate, salary_min=-1) == {"salary_min"}
    assert JobUpdate(salary_currency="gbp").salary_currency == "GBP"
    assert (
        JobUpdate(skills=[]).skills == []
    )  # an empty list means "remove all skills", distinct from "unchanged"
    assert JobUpdate().skills is None


# --- companies / applications / paging -----------------------------------------------------------------------------------------------------------


def test_member_and_admin_role_restrictions() -> None:
    base = {"email": "a@example.com", "password": "Longenough1", "first_name": "A", "last_name": "B"}
    assert MemberCreate(**base, role="HIRING_MANAGER").role == "HIRING_MANAGER"
    assert fields_in_error(MemberCreate, **base, role="ADMIN") == {"role"}
    assert fields_in_error(MemberCreate, **base, role="CANDIDATE") == {"role"}
    assert fields_in_error(MemberUpdate, role="ADMIN") == {"role"}
    assert MemberUpdate(role="RECRUITER").role == "RECRUITER" and MemberUpdate().role is None
    assert AdminUserCreate(**base, role="ADMIN").role == "ADMIN"


def test_company_name_bounds() -> None:
    assert fields_in_error(CompanyCreate, name="A") == {"name"}
    assert fields_in_error(CompanyCreate, name="x" * 201) == {"name"}
    assert fields_in_error(CompanyCreate, name="Acme", description="x" * 5001) == {"description"}
    assert fields_in_error(CompanyCreate, name="Acme", size="ENORMOUS") == {"size"}


def test_application_payloads() -> None:
    jid = "00000000-0000-0000-0000-000000000001"
    assert ApplicationCreate(job_id=jid).source == "DIRECT"
    for src in ("DIRECT", "RECOMMENDATION", "SEARCH", "REFERRAL"):
        assert ApplicationCreate(job_id=jid, source=src).source == src
    assert fields_in_error(ApplicationCreate, job_id=jid, source="HACK") == {"source"}
    assert fields_in_error(ApplicationCreate, job_id="x") == {"job_id"}
    assert fields_in_error(ApplicationCreate, job_id=jid, cover_letter="x" * 8001) == {"cover_letter"}
    assert fields_in_error(StatusChange, status="DONE") == {"status"}
    assert fields_in_error(StatusChange, status="REJECTED", comment="x" * 2001) == {"comment"}
    assert fields_in_error(NoteCreate, body="") == {"body"}
    assert fields_in_error(NoteCreate, body="x" * 4001) == {"body"}


def test_page_params() -> None:
    p = PageParams(page=3, page_size=25)
    assert p.offset == 50
    assert PageParams().page == 1 and PageParams().page_size == 20
