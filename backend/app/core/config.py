"""Application configuration, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_INSECURE_SECRETS = {"", "change-me", "changeme", "secret", "dev-insecure-secret-key-change-me-in-production"}
# Published defaults (code / .env.example / demo seed): fine for local use, never for production.
_PUBLISHED_PASSWORDS = {"ChangeMe123!", "DemoPass123!"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TalentLens"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    database_url: str = "postgresql+asyncpg://talentlens:talentlens@localhost:5432/talentlens"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_default_ttl_seconds: int = 300

    # --- authentication -----------------------------------------------------------------
    secret_key: SecretStr = SecretStr("dev-insecure-secret-key-change-me-in-production")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    refresh_cookie_name: str = "tl_refresh"
    refresh_cookie_secure: bool = False  # set true behind HTTPS (required in production)

    # --- rate limits (fixed window, per client) ------------------------------------------
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300
    register_rate_limit_attempts: int = 10
    register_rate_limit_window_seconds: int = 3600
    upload_rate_limit_attempts: int = 20
    upload_rate_limit_window_seconds: int = 3600
    expensive_rate_limit_attempts: int = 30
    expensive_rate_limit_window_seconds: int = 60
    search_rate_limit_attempts: int = 120
    search_rate_limit_window_seconds: int = 60

    first_admin_email: str = "admin@example.com"
    first_admin_password: SecretStr = SecretStr("ChangeMe123!")
    seed_demo_data: bool = False

    # --- background jobs ------------------------------------------------------------------
    # "arq" uses Redis + a worker process; "inline" runs tasks in-process (tests / no-worker mode).
    job_backend: Literal["arq", "inline"] = "arq"
    task_max_attempts: int = 2

    # --- résumé storage & validation ---------------------------------------------------------
    storage_backend: Literal["local"] = "local"
    storage_dir: str = "/data/resumes"
    max_resume_mb: int = 5
    max_resume_text_chars: int = 200_000
    max_bulk_import_files: int = 200
    max_docx_uncompressed_mb: int = 50

    # --- embeddings & matching ---------------------------------------------------------------
    embedding_backend: Literal["wordllama", "sentence-transformers"] = "wordllama"
    embedding_dim: int = 256
    embedding_model_name: str = "wordllama-l2-supercat-256"
    embedding_version: str = "v1"
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    matching_version: str = "v1"
    match_retrieval_limit: int = 300  # vector candidates re-scored per job
    recommendation_limit: int = 100

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith(
                "["
            ):  # JSON array (NoDecode means pydantic-settings no longer parses it for us)
                return json.loads(text)
            return [v.strip() for v in text.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.environment == "production":
            key = self.secret_key.get_secret_value()
            if key in _INSECURE_SECRETS or key.lower().startswith("change-me") or len(key) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of >= 32 chars in production")
            if self.first_admin_password.get_secret_value() in _PUBLISHED_PASSWORDS:
                raise ValueError("FIRST_ADMIN_PASSWORD must not be a published default in production")
            if self.seed_demo_data:
                raise ValueError(
                    "SEED_DEMO_DATA must be false in production (demo accounts share a published password)"
                )
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are not allowed in production")
            if not self.refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be true in production (serve over HTTPS)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
