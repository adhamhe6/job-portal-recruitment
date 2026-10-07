"""Background-task handlers for matching and embedding maintenance (see ``app.workers.tasks`` for the contract)."""

from __future__ import annotations

import uuid
from typing import Any

from app.cache.redis_cache import CacheDomain
from app.matching.embedder import EmbeddingError
from app.matching.service import MatchingService
from app.workers.tasks import RetryableError, TaskContext, TaskFailure


async def handle_match_job(ctx: TaskContext) -> dict[str, Any]:
    job_id = uuid.UUID(ctx.params["job_id"])
    await ctx.progress(10, "loading job")
    async with ctx.sessionmaker() as session:
        try:
            await ctx.progress(30, "embedding and retrieving candidates")
            summary = await MatchingService(session).match_job(job_id, notify=bool(ctx.params.get("notify")))
        except EmbeddingError as exc:
            raise RetryableError("embedding model unavailable") from exc
    await ctx.cache.invalidate(CacheDomain.MATCHES)
    await ctx.progress(95, "finishing")
    return {"scored": summary.scored, "top_score": summary.top_score, "job_embedded": summary.embedded_job}


async def handle_match_candidate(ctx: TaskContext) -> dict[str, Any]:
    candidate_id = uuid.UUID(ctx.params["candidate_id"])
    await ctx.progress(10, "updating profile index")
    async with ctx.sessionmaker() as session:
        svc = MatchingService(session)
        try:
            await svc.refresh_candidate_index(candidate_id)
            await ctx.progress(50, "matching published jobs")
            summary = await svc.match_candidate(candidate_id)
        except EmbeddingError as exc:
            raise RetryableError("embedding model unavailable") from exc
    await ctx.cache.invalidate(CacheDomain.MATCHES, CacheDomain.CANDIDATES)
    return {"scored": summary.scored, "top_score": summary.top_score}


async def handle_refresh_embeddings(ctx: TaskContext) -> dict[str, Any]:
    async with ctx.sessionmaker() as session:
        try:
            result = await MatchingService(session).reembed_all(ctx.progress)
        except EmbeddingError as exc:
            raise TaskFailure("EMBEDDING_UNAVAILABLE", "The embedding model could not be loaded") from exc
    await ctx.cache.invalidate(CacheDomain.MATCHES, CacheDomain.CANDIDATES, CacheDomain.JOBS)
    return result
