"""Settings: defaults, parsing and the fail-closed production validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

GOOD_SECRET = "k" * 48
GOOD_PASSWORD = "A-Long-Unique-Admin-Passphrase-9"


def prod(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "secret_key": GOOD_SECRET,
        "first_admin_password": GOOD_PASSWORD,
        "seed_demo_data": False,
        "debug": False,
        "cors_origins": ["https://app.example.com"],
        "refresh_cookie_secure": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_a_correct_production_configuration_is_accepted() -> None:
    s = prod()
    assert s.environment == "production" and s.refresh_cookie_secure and not s.debug


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"secret_key": "dev-insecure-secret-key-change-me-in-production"}, "SECRET_KEY"),
        ({"secret_key": ""}, "SECRET_KEY"),
        ({"secret_key": "change-me"}, "SECRET_KEY"),
        ({"secret": "x"}, None),  # unknown settings are ignored, not an error
        ({"secret_key": "short-but-random-9f3a"}, "SECRET_KEY"),  # < 32 characters
        ({"secret_key": "k" * 31}, "SECRET_KEY"),
        ({"secret_key": "Change-Me-" + "z" * 40}, "SECRET_KEY"),  # looks like the placeholder even though long
        ({"first_admin_password": "ChangeMe123!"}, "FIRST_ADMIN_PASSWORD"),
        ({"first_admin_password": "DemoPass123!"}, "FIRST_ADMIN_PASSWORD"),
        ({"seed_demo_data": True}, "SEED_DEMO_DATA"),
        ({"debug": True}, "DEBUG"),
        ({"cors_origins": ["*"]}, "CORS"),
        ({"cors_origins": ["https://a.example.com", "*"]}, "CORS"),
        ({"refresh_cookie_secure": False}, "REFRESH_COOKIE_SECURE"),
    ],
)
def test_production_safety_validators(overrides: dict[str, object], needle: str | None) -> None:
    if needle is None:
        prod(**overrides)
        return
    with pytest.raises(ValidationError) as exc:
        prod(**overrides)
    assert needle in str(exc.value)


def test_boundary_secret_length_is_32() -> None:
    assert prod(secret_key="k" * 32).secret_key.get_secret_value() == "k" * 32


def test_the_same_values_are_fine_outside_production() -> None:
    for env in ("development", "test"):
        s = Settings(
            _env_file=None, environment=env, secret_key="change-me", first_admin_password="ChangeMe123!",
            seed_demo_data=True, debug=True, cors_origins=["*"], refresh_cookie_secure=False,
        )  # type: ignore[arg-type]
        assert s.environment == env


def test_defaults_are_safe_for_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ENVIRONMENT", "JOB_BACKEND", "CORS_ORIGINS", "DEBUG", "SEED_DEMO_DATA"):  # the harness pins some of these
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert s.environment == "development"
    assert s.debug is False and s.seed_demo_data is False
    assert s.access_token_expire_minutes == 15 and s.refresh_token_expire_days == 14
    assert s.cors_origins == ["http://localhost:5173"]
    assert s.job_backend == "arq" and s.task_max_attempts == 2
    assert s.embedding_dim == 256 and s.api_prefix == "/api/v1"


def test_secret_key_is_not_leaked_by_repr() -> None:
    s = prod()
    assert GOOD_SECRET not in repr(s) and GOOD_SECRET not in str(s.model_dump())
    assert GOOD_PASSWORD not in repr(s)


def test_environment_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="staging")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_algorithm="none")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://a.example.com", ["https://a.example.com"]),
        ("https://a.example.com, https://b.example.com ,", ["https://a.example.com", "https://b.example.com"]),
        ('["https://a.example.com","https://b.example.com"]', ["https://a.example.com", "https://b.example.com"]),
        ("", []),
    ],
)
def test_cors_origins_accept_comma_separated_and_json(raw: str, expected: list[str]) -> None:
    assert Settings(_env_file=None, cors_origins=raw).cors_origins == expected  # type: ignore[arg-type]


def test_cors_origins_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://x.example.com,https://y.example.com")
    assert Settings(_env_file=None).cors_origins == ["https://x.example.com", "https://y.example.com"]


def test_production_settings_can_be_loaded_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", GOOD_SECRET)
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", GOOD_PASSWORD)
    monkeypatch.setenv("REFRESH_COOKIE_SECURE", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    assert Settings(_env_file=None).environment == "production"
    monkeypatch.setenv("SEED_DEMO_DATA", "true")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
