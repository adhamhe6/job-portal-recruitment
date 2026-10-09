"""Admin & monitoring schemas. Nothing here carries secrets (no URLs with credentials, keys or tokens)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.models import TaskStatus, TaskType


class AppInfo(BaseModel):
    name: str
    version: str
    environment: str
    python_version: str
    job_backend: str = Field(
        description="`arq` (Redis + worker process) or `inline` (in-process, tests / no-worker mode)"
    )
    cache_enabled: bool


class DatabaseStatus(BaseModel):
    ok: bool
    latency_ms: float | None = None
    pgvector_version: str | None = None
    migration_revision: str | None = Field(default=None, description="Revision stored in alembic_version")
    migration_head: str | None = Field(
        default=None, description="Newest revision shipped with this build (best effort)"
    )
    migrations_current: bool | None = Field(
        default=None, description="revision == head; null when either is unknown"
    )
    error: str | None = None


class RedisStatus(BaseModel):
    ok: bool
    latency_ms: float | None = None
    queue_depth: int | None = Field(
        default=None, description="Jobs waiting in the ARQ queue (ZCARD arq:queue), best effort"
    )
    error: str | None = None


class EmbeddingModelStatus(BaseModel):
    backend: str
    model_name: str
    model_version: str
    dimension: int
    loaded: bool = Field(
        description="True when the model could be loaded and produced a vector of the expected size"
    )
    error: str | None = None


class WorkerStatus(BaseModel):
    mode: str = Field(
        description="`arq`: a separate worker process; `inline`: tasks run inside the API process"
    )
    alive: bool | None = Field(
        description="ARQ health-check key present (the worker refreshes it periodically); null when not applicable/unknown"
    )
    health_key: str
    health_ttl_seconds: float | None = None
    last_check: str | None = Field(default=None, description="Raw summary line written by the worker")
    jobs_complete: int | None = None
    jobs_failed: int | None = None
    jobs_retried: int | None = None
    jobs_ongoing: int | None = None
    queued: int | None = None


class StaleTask(BaseModel):
    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    stage: str | None
    created_at: datetime
    updated_at: datetime
    age_minutes: float = Field(
        description="Minutes since creation (PENDING) or since the last progress update (RUNNING)"
    )
    worker_heartbeat: bool | None = Field(
        default=None, description="RUNNING only: the executing worker's heartbeat key exists"
    )


class TaskHealth(BaseModel):
    by_status: dict[str, int]
    last_24h_by_status: dict[str, int]
    stale_pending_after_minutes: int
    stale_running_after_minutes: int
    stale_count: int
    stale: list[StaleTask] = Field(description="Up to 10, oldest first")


class SystemStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checked_at: datetime
    app: AppInfo
    database: DatabaseStatus
    redis: RedisStatus
    embedding: EmbeddingModelStatus
    worker: WorkerStatus
    tasks: TaskHealth


class AdminTaskOut(BaseModel):
    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    progress: int
    stage: str | None
    attempts: int
    error_code: str | None
    error_message: str | None
    dedupe_key: str | None
    created_by_id: uuid.UUID | None
    company_id: uuid.UUID | None
    params: dict[str, Any]
    has_result: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AuditEventOut(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    actor_email: str | None
    company_id: uuid.UUID | None
    metadata: dict[str, Any] | None
    created_at: datetime


class EmbeddingRefreshOut(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus
    created: bool = Field(
        description="False when an identical refresh was already queued or running (deduplicated)"
    )


class EmbeddingBucket(BaseModel):
    population: str = Field(description="What is counted")
    total: int
    current: int = Field(description="Embedded with the configured model name and version")
    outdated: int = Field(description="Embedded with a different model name or version (run a refresh)")
    missing: int = Field(description="No embedding stored yet")


class LastRefresh(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus
    finished_at: datetime | None
    result: dict[str, Any] | None


class EmbeddingsStatus(BaseModel):
    model_name: str
    model_version: str
    dimension: int
    jobs: EmbeddingBucket
    candidates: EmbeddingBucket
    resume_results: EmbeddingBucket
    active_refresh_task_id: uuid.UUID | None
    last_refresh: LastRefresh | None


class MatchVersionCount(BaseModel):
    matching_version: str
    embedding_model: str
    embedding_version: str
    pairs: int
    current: bool


class MatchTaskCounts(BaseModel):
    active: int = Field(description="PENDING or RUNNING match tasks")
    last_24h_by_status: dict[str, int]


class MatchingStatus(BaseModel):
    matching_version: str
    embedding_model: str
    embedding_version: str
    pairs: int
    jobs_with_matches: int
    candidates_with_matches: int
    last_generated_at: datetime | None
    stale_by_version: int = Field(
        description="Pairs computed with another matching/embedding version (hash staleness is checked on read)"
    )
    by_version: list[MatchVersionCount]
    published_jobs: int
    published_jobs_without_matches: int
    tasks: MatchTaskCounts
