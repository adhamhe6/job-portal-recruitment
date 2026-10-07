"""Platform monitoring and maintenance (ADMIN only): system health, background tasks, audit log, embeddings, matching."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

from arq.constants import default_queue_name, health_check_key_suffix
from redis.exceptions import RedisError
from sqlalchemy import func, null, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.cache.redis_cache import Cache, get_redis
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailure
from app.core.security import Role
from app.db.models import (
    ACTIVE_TASK_STATUSES,
    AuditEvent,
    BackgroundTask,
    CandidateJobMatch,
    CandidateProfile,
    Job,
    JobStatus,
    ResumeProcessingResult,
    TaskStatus,
    TaskType,
    User,
)
from app.matching.scoring import MATCHING_VERSION
from app.schemas.admin import (
    AdminTaskOut,
    AppInfo,
    AuditEventOut,
    DatabaseStatus,
    EmbeddingBucket,
    EmbeddingModelStatus,
    EmbeddingsStatus,
    LastRefresh,
    MatchingStatus,
    MatchTaskCounts,
    MatchVersionCount,
    RedisStatus,
    StaleTask,
    SystemStatus,
    TaskHealth,
    WorkerStatus,
)
from app.services.common import paginate, record_audit, utcnow
from app.services.tasks import Dispatcher, TaskService

logger = logging.getLogger(__name__)

STALE_PENDING_MINUTES = 10
STALE_RUNNING_MINUTES = 30
REDIS_TIMEOUT_SECONDS = 2.0
HEALTH_KEY = f"{default_queue_name}{health_check_key_suffix}"  # "arq:queue:health-check" - written by the ARQ worker
REFRESH_DEDUPE_KEY = "refresh-embeddings"
_KV = re.compile(r"(\w+)=(\d+)")


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _fill_status(rows: list[tuple[Any, int]]) -> dict[str, int]:
    out = {s.value: 0 for s in TaskStatus}
    for k, n in rows:
        out[getattr(k, "value", k)] = int(n)
    return out


def _task_out(t: BackgroundTask) -> AdminTaskOut:
    return AdminTaskOut(
        id=t.id,
        type=t.type,
        status=t.status,
        progress=t.progress,
        stage=t.stage,
        attempts=t.attempts,
        error_code=t.error_code,
        error_message=t.error_message,
        dedupe_key=t.dedupe_key,
        created_by_id=t.created_by_id,
        company_id=t.company_id,
        params=t.params or {},
        has_result=t.result is not None,
        created_at=t.created_at,
        updated_at=t.updated_at,
        started_at=t.started_at,
        finished_at=t.finished_at,
    )


def _migration_head() -> str | None:
    """Newest Alembic revision shipped with this build (None when the migration scripts are not part of the image)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


def _heartbeat_key(task_id: uuid.UUID) -> str:
    try:  # reuse the worker's own naming when the worker module is importable
        from app.workers.worker import heartbeat_key

        return heartbeat_key(str(task_id))
    except Exception:
        return f"task:heartbeat:{task_id}"


class AdminService:
    def __init__(self, session: AsyncSession, cache: Cache | None = None) -> None:
        self.session = session
        self.cache = cache

    @staticmethod
    def _require_admin(user: User) -> None:
        if user.role != Role.ADMIN:
            raise PermissionDeniedError("Administrators only")

    # ------------------------------------------------------------------------------------------------------------
    # system status
    # ------------------------------------------------------------------------------------------------------------
    async def _database(self) -> DatabaseStatus:
        try:
            t0 = time.perf_counter()
            await self.session.execute(text("SELECT 1"))
            latency = _ms(t0)
        except Exception as exc:
            return DatabaseStatus(ok=False, error=type(exc).__name__)
        version = await self.session.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        revision: str | None = None
        try:
            async with self.session.begin_nested():  # a missing alembic_version table must not poison the transaction
                revision = await self.session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        except Exception:
            revision = None
        head = await asyncio.to_thread(_migration_head)
        return DatabaseStatus(
            ok=True,
            latency_ms=latency,
            pgvector_version=version,
            migration_revision=revision,
            migration_head=head,
            migrations_current=(revision == head) if revision and head else None,
        )

    async def _redis_and_worker(self) -> tuple[RedisStatus, WorkerStatus]:
        mode = get_settings().job_backend
        worker = WorkerStatus(mode=mode, alive=None, health_key=HEALTH_KEY)
        redis = get_redis()
        try:
            t0 = time.perf_counter()
            await asyncio.wait_for(redis.ping(), REDIS_TIMEOUT_SECONDS)
            latency = _ms(t0)
        except (RedisError, OSError, TimeoutError) as exc:
            return RedisStatus(ok=False, error=type(exc).__name__), worker
        depth: int | None = None
        with contextlib.suppress(RedisError, OSError, TimeoutError):
            depth = int(await asyncio.wait_for(redis.zcard(default_queue_name), REDIS_TIMEOUT_SECONDS))
        status = RedisStatus(ok=True, latency_ms=latency, queue_depth=depth)
        if mode == "arq":
            try:
                raw = await asyncio.wait_for(redis.get(HEALTH_KEY), REDIS_TIMEOUT_SECONDS)
                ttl_ms = await asyncio.wait_for(redis.pttl(HEALTH_KEY), REDIS_TIMEOUT_SECONDS)
            except (RedisError, OSError, TimeoutError):
                return status, worker
            worker.alive = raw is not None
            if raw is not None:
                line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                kv = {k: int(v) for k, v in _KV.findall(line)}
                worker.last_check = line[:200]
                worker.health_ttl_seconds = round(ttl_ms / 1000, 1) if ttl_ms and ttl_ms > 0 else None
                worker.jobs_complete, worker.jobs_failed = kv.get("j_complete"), kv.get("j_failed")
                worker.jobs_retried, worker.jobs_ongoing, worker.queued = kv.get("j_retried"), kv.get("j_ongoing"), kv.get("queued")
        return status, worker

    async def _embedding(self) -> EmbeddingModelStatus:
        s = get_settings()
        base = {"backend": s.embedding_backend, "model_name": s.embedding_model_name, "model_version": s.embedding_version, "dimension": s.embedding_dim}
        try:
            from app.matching.embedder import get_embedder

            embedder = await asyncio.to_thread(get_embedder)
            vec = await asyncio.to_thread(embedder.embed, ["health check"])
            ok = tuple(vec.shape) == (1, s.embedding_dim)
            return EmbeddingModelStatus(**base, loaded=ok, error=None if ok else "unexpected embedding dimension")
        except Exception as exc:
            return EmbeddingModelStatus(**base, loaded=False, error=type(exc).__name__)

    async def _task_health(self) -> TaskHealth:
        s = self.session
        now = utcnow()
        by_status = _fill_status([(k, n) for k, n in (await s.execute(select(BackgroundTask.status, func.count()).group_by(BackgroundTask.status))).all()])
        recent = _fill_status(
            [
                (k, n)
                for k, n in (
                    await s.execute(
                        select(BackgroundTask.status, func.count())
                        .where(BackgroundTask.created_at >= now - timedelta(hours=24))
                        .group_by(BackgroundTask.status)
                    )
                ).all()
            ]
        )
        stale_cond = or_(
            (BackgroundTask.status == TaskStatus.PENDING) & (BackgroundTask.created_at < now - timedelta(minutes=STALE_PENDING_MINUTES)),
            (BackgroundTask.status == TaskStatus.RUNNING) & (BackgroundTask.updated_at < now - timedelta(minutes=STALE_RUNNING_MINUTES)),
        )
        stale_count = int(await s.scalar(select(func.count()).select_from(BackgroundTask).where(stale_cond)) or 0)
        rows = (
            await s.execute(select(BackgroundTask).where(stale_cond).order_by(BackgroundTask.created_at, BackgroundTask.id).limit(10))
        ).scalars().all()
        beats: dict[uuid.UUID, bool] = {}
        running = [t.id for t in rows if t.status == TaskStatus.RUNNING]
        if running:
            with contextlib.suppress(RedisError, OSError, TimeoutError):
                vals = await asyncio.wait_for(get_redis().mget([_heartbeat_key(i) for i in running]), REDIS_TIMEOUT_SECONDS)
                beats = {i: v is not None for i, v in zip(running, vals, strict=True)}
        stale = [
            StaleTask(
                id=t.id,
                type=t.type,
                status=t.status,
                stage=t.stage,
                created_at=t.created_at,
                updated_at=t.updated_at,
                age_minutes=round(((now - (t.created_at if t.status == TaskStatus.PENDING else t.updated_at)).total_seconds()) / 60, 1),
                worker_heartbeat=beats.get(t.id) if t.status == TaskStatus.RUNNING else None,
            )
            for t in rows
        ]
        return TaskHealth(
            by_status=by_status,
            last_24h_by_status=recent,
            stale_pending_after_minutes=STALE_PENDING_MINUTES,
            stale_running_after_minutes=STALE_RUNNING_MINUTES,
            stale_count=stale_count,
            stale=stale,
        )

    async def system_status(self, user: User) -> SystemStatus:
        self._require_admin(user)
        settings = get_settings()
        db = await self._database()
        redis_status, worker = await self._redis_and_worker()
        embedding = await self._embedding()
        tasks = await self._task_health() if db.ok else TaskHealth(
            by_status={}, last_24h_by_status={}, stale_pending_after_minutes=STALE_PENDING_MINUTES,
            stale_running_after_minutes=STALE_RUNNING_MINUTES, stale_count=0, stale=[],
        )
        degraded = (
            not redis_status.ok
            or not embedding.loaded
            or worker.alive is False
            or db.migrations_current is False
            or tasks.stale_count > 0
        )
        status = "down" if not db.ok else "degraded" if degraded else "ok"
        return SystemStatus(
            status=status,
            checked_at=utcnow(),
            app=AppInfo(
                name=settings.app_name,
                version=__version__,
                environment=settings.environment,
                python_version=platform.python_version(),
                job_backend=settings.job_backend,
                cache_enabled=settings.cache_enabled,
            ),
            database=db,
            redis=redis_status,
            embedding=embedding,
            worker=worker,
            tasks=tasks,
        )

    # ------------------------------------------------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------------------------------------------------
    async def list_tasks(
        self, user: User, *, status: TaskStatus | None, type_: TaskType | None, page: int, page_size: int
    ) -> tuple[list[AdminTaskOut], int]:
        self._require_admin(user)
        stmt = select(BackgroundTask).order_by(BackgroundTask.created_at.desc(), BackgroundTask.id)
        if status:
            stmt = stmt.where(BackgroundTask.status == status)
        if type_:
            stmt = stmt.where(BackgroundTask.type == type_)
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size)
        return [_task_out(t) for t in rows], total

    async def retry_task(self, user: User, task_id: uuid.UUID, dispatcher: Dispatcher) -> AdminTaskOut:
        self._require_admin(user)
        task = await self.session.get(BackgroundTask, task_id)
        if task is None:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND")
        if task.status != TaskStatus.FAILED:
            raise ConflictError(
                f"Only FAILED tasks can be retried (this one is {task.status.value})", code="TASK_NOT_RETRYABLE", details={"status": task.status.value}
            )
        dedupe_key, task_type, previous_error = task.dedupe_key, task.type, task.error_code  # plain values: ORM state expires on rollback
        try:
            # Atomic FAILED -> PENDING: of two admins clicking at once, exactly one proceeds.
            moved = (
                await self.session.execute(
                    update(BackgroundTask)
                    .where(BackgroundTask.id == task_id, BackgroundTask.status == TaskStatus.FAILED)
                    .values(
                        status=TaskStatus.PENDING, progress=0, stage="retrying", attempts=0, error_code=None, error_message=None,
                        result=null(), started_at=None, finished_at=None,
                    )
                    .returning(BackgroundTask.id)
                    .execution_options(synchronize_session=False)
                )
            ).scalar_one_or_none()
            if moved is None:
                await self.session.rollback()
                raise ConflictError("This task is no longer FAILED", code="TASK_NOT_RETRYABLE")
            record_audit(
                self.session, actor_id=user.id, action="task.retried", entity_type="task", entity_id=task_id,
                meta={"type": task_type.value, "previous_error": previous_error},
            )
            await self.session.commit()
        except IntegrityError as exc:  # another task with the same dedupe key is active now
            await self.session.rollback()
            raise ConflictError(
                "An equivalent task is already pending or running", code="TASK_ALREADY_ACTIVE", details={"dedupe_key": dedupe_key}
            ) from exc
        await self.session.refresh(task)
        await TaskService(self.session).enqueue(task, dispatcher)
        await self.session.refresh(task)
        return _task_out(task)

    # ------------------------------------------------------------------------------------------------------------
    # audit log
    # ------------------------------------------------------------------------------------------------------------
    async def list_audit(
        self,
        user: User,
        *,
        actor_id: uuid.UUID | None,
        action: str | None,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditEventOut], int]:
        self._require_admin(user)
        if from_date and to_date and from_date > to_date:
            raise ValidationFailure("from_date must not be after to_date", code="INVALID_DATE_RANGE")
        stmt: Any = (
            select(AuditEvent, User.first_name, User.last_name, User.email)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        )
        if actor_id:
            stmt = stmt.where(AuditEvent.actor_id == actor_id)
        if action:
            if action.endswith("*"):
                prefix = action[:-1].replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
                stmt = stmt.where(AuditEvent.action.like(prefix + "%", escape="\\"))
            else:
                stmt = stmt.where(AuditEvent.action == action)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)
        if company_id:
            stmt = stmt.where(AuditEvent.company_id == company_id)
        if from_date:
            stmt = stmt.where(AuditEvent.created_at >= datetime.combine(from_date, dtime.min, UTC))
        if to_date:
            stmt = stmt.where(AuditEvent.created_at < datetime.combine(to_date + timedelta(days=1), dtime.min, UTC))
        rows, total = await paginate(self.session, stmt, page=page, page_size=page_size, scalars=False)
        return [
            AuditEventOut(
                id=ev.id, action=ev.action, entity_type=ev.entity_type, entity_id=ev.entity_id, actor_id=ev.actor_id,
                actor_name=f"{fn} {ln}".strip() if fn else None, actor_email=email, company_id=ev.company_id, metadata=ev.meta,
                created_at=ev.created_at,
            )
            for ev, fn, ln, email in rows
        ], total

    # ------------------------------------------------------------------------------------------------------------
    # embeddings
    # ------------------------------------------------------------------------------------------------------------
    async def refresh_embeddings(self, user: User, dispatcher: Dispatcher) -> tuple[BackgroundTask, bool]:
        self._require_admin(user)
        task, created = await TaskService(self.session).submit(
            TaskType.REFRESH_EMBEDDINGS, {}, dispatcher, created_by_id=user.id, dedupe_key=REFRESH_DEDUPE_KEY
        )
        if created:
            record_audit(self.session, actor_id=user.id, action="embeddings.refresh_requested", entity_type="task", entity_id=task.id)
            await self.session.commit()
        return task, created

    async def _bucket(self, population: str, entity: Any, where: list[Any], model_col: Any, version_col: Any, emb_col: Any) -> EmbeddingBucket:
        s = get_settings()
        right_model = (model_col == s.embedding_model_name) & (version_col == s.embedding_version)
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(emb_col.is_(None)),
                    func.count().filter(emb_col.is_not(None), right_model),
                    func.count().filter(
                        emb_col.is_not(None),
                        model_col.is_distinct_from(s.embedding_model_name) | version_col.is_distinct_from(s.embedding_version),
                    ),
                )
                .select_from(entity)
                .where(*where)
            )
        ).one()
        return EmbeddingBucket(population=population, total=int(row[0]), missing=int(row[1]), current=int(row[2]), outdated=int(row[3]))

    async def embeddings_status(self, user: User) -> EmbeddingsStatus:
        self._require_admin(user)
        s = get_settings()
        jobs = await self._bucket(
            "jobs that are PUBLISHED or PAUSED (drafts and closed jobs are not embedded)", Job,
            [Job.status.in_((JobStatus.PUBLISHED, JobStatus.PAUSED))], Job.embedding_model, Job.embedding_version, Job.embedding,
        )
        candidates = await self._bucket(
            "all candidate profiles (profiles without any text cannot be embedded)", CandidateProfile, [],
            CandidateProfile.embedding_model, CandidateProfile.embedding_version, CandidateProfile.embedding,
        )
        from app.db.models import ProcessingStatus

        resumes = await self._bucket(
            "successfully processed résumés", ResumeProcessingResult, [ResumeProcessingResult.status == ProcessingStatus.COMPLETED],
            ResumeProcessingResult.embedding_model, ResumeProcessingResult.embedding_version, ResumeProcessingResult.embedding,
        )
        active = await self.session.scalar(
            select(BackgroundTask.id).where(BackgroundTask.type == TaskType.REFRESH_EMBEDDINGS, BackgroundTask.status.in_(ACTIVE_TASK_STATUSES)).limit(1)
        )
        last = (
            await self.session.execute(
                select(BackgroundTask)
                .where(BackgroundTask.type == TaskType.REFRESH_EMBEDDINGS)
                .order_by(BackgroundTask.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return EmbeddingsStatus(
            model_name=s.embedding_model_name,
            model_version=s.embedding_version,
            dimension=s.embedding_dim,
            jobs=jobs,
            candidates=candidates,
            resume_results=resumes,
            active_refresh_task_id=active,
            last_refresh=LastRefresh(task_id=last.id, status=last.status, finished_at=last.finished_at, result=last.result) if last else None,
        )

    # ------------------------------------------------------------------------------------------------------------
    # matching
    # ------------------------------------------------------------------------------------------------------------
    async def matching_status(self, user: User) -> MatchingStatus:
        self._require_admin(user)
        s = get_settings()
        sess = self.session
        pairs, jobs, cands, last = (
            await sess.execute(
                select(
                    func.count(), func.count(func.distinct(CandidateJobMatch.job_id)),
                    func.count(func.distinct(CandidateJobMatch.candidate_id)), func.max(CandidateJobMatch.generated_at),
                )
            )
        ).one()
        versions = (
            await sess.execute(
                select(
                    CandidateJobMatch.matching_version, CandidateJobMatch.embedding_model, CandidateJobMatch.embedding_version, func.count()
                )
                .group_by(CandidateJobMatch.matching_version, CandidateJobMatch.embedding_model, CandidateJobMatch.embedding_version)
                .order_by(func.count().desc())
            )
        ).all()
        by_version = [
            MatchVersionCount(
                matching_version=mv, embedding_model=em, embedding_version=ev, pairs=int(n),
                current=(mv == MATCHING_VERSION and em == s.embedding_model_name and ev == s.embedding_version),
            )
            for mv, em, ev, n in versions
        ]
        published = int(await sess.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.PUBLISHED)) or 0)
        without = int(
            await sess.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.status == JobStatus.PUBLISHED, ~select(CandidateJobMatch.id).where(CandidateJobMatch.job_id == Job.id).exists())
            )
            or 0
        )
        match_types = (TaskType.MATCH_JOB, TaskType.MATCH_CANDIDATE)
        active = int(
            await sess.scalar(
                select(func.count()).select_from(BackgroundTask).where(BackgroundTask.type.in_(match_types), BackgroundTask.status.in_(ACTIVE_TASK_STATUSES))
            )
            or 0
        )
        recent = (
            await sess.execute(
                select(BackgroundTask.status, func.count())
                .where(BackgroundTask.type.in_(match_types), BackgroundTask.created_at >= utcnow() - timedelta(hours=24))
                .group_by(BackgroundTask.status)
            )
        ).all()
        return MatchingStatus(
            matching_version=MATCHING_VERSION,
            embedding_model=s.embedding_model_name,
            embedding_version=s.embedding_version,
            pairs=int(pairs),
            jobs_with_matches=int(jobs),
            candidates_with_matches=int(cands),
            last_generated_at=last,
            stale_by_version=sum(v.pairs for v in by_version if not v.current),
            by_version=by_version,
            published_jobs=published,
            published_jobs_without_matches=without,
            tasks=MatchTaskCounts(active=active, last_24h_by_status=_fill_status([(k, n) for k, n in recent])),
        )
