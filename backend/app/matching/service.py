"""Matching service: keeps embeddings fresh, retrieves candidates/jobs with pgvector and persists scored matches."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.models import (
    Application,
    ApplicationStatus,
    CandidateJobMatch,
    CandidateProfile,
    CandidateSource,
    Job,
    JobStatus,
    NotificationType,
)
from app.matching.embedder import EmbeddingError, get_embedder
from app.matching.loaders import load_candidate_features, load_job_features
from app.matching.representation import CandidateFeatures, JobFeatures, embed_components, embedding_hash
from app.matching.scoring import MATCHING_VERSION, MatchResult, score_pair
from app.services.common import utcnow
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

NOTIFY_THRESHOLD = 0.70  # candidate is told about a newly published job at/above this score
RECRUITER_NOTIFY_THRESHOLD = 0.80  # staff are told about a *newly* strong candidate at/above this score
NOTIFY_MAX_PER_JOB = 25


@dataclass(slots=True)
class MatchRunSummary:
    scored: int
    embedded_job: bool
    embedded_candidates: int
    top_score: float | None


def _live_job_filter(today: Any = None) -> Any:
    return and_(
        Job.status == JobStatus.PUBLISHED,
        or_(Job.application_deadline.is_(None), Job.application_deadline >= func.current_date()),
    )


class MatchingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    # --- embeddings -----------------------------------------------------------------------------------
    async def refresh_job_embedding(self, job: Job, features: JobFeatures) -> bool:
        """Embed the job if the embedded text, model or version changed. Returns True when re-embedded."""
        emb = get_embedder()
        h = embedding_hash(features.components(), emb.name, emb.version)
        if job.embedding is not None and job.embedding_source_hash == h:
            return False
        vec = await embed_components(features.components())
        job.embedding = vec.tolist()
        job.embedding_model, job.embedding_version = emb.name, emb.version
        job.embedding_source_hash, job.embedding_generated_at = h, utcnow()
        return True

    async def refresh_candidate_embedding(self, cand: CandidateProfile, features: CandidateFeatures) -> bool:
        emb = get_embedder()
        comps = features.components()
        if not any(comps.values()):
            return False
        h = embedding_hash(comps, emb.name, emb.version)
        if cand.embedding is not None and cand.embedding_source_hash == h:
            return False
        vec = await embed_components(comps)
        cand.embedding = vec.tolist()
        cand.embedding_model, cand.embedding_version = emb.name, emb.version
        cand.embedding_source_hash, cand.embedding_generated_at = h, utcnow()
        return True

    async def refresh_candidate_text(
        self, candidate_id: uuid.UUID
    ) -> tuple[CandidateProfile, CandidateFeatures]:
        """Rebuild the denormalised search text (cheap, SQL only — safe in the request path). Does not commit."""
        cand = await self.session.get(CandidateProfile, candidate_id)
        if cand is None:
            raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
        features = (await load_candidate_features(self.session, [candidate_id]))[candidate_id]
        cand.skills_text = " ".join(s.name for s in features.skills) or None
        parts = [
            features.summary,
            " ".join(features.recent_titles(6)),
            " ".join(features.certifications),
            " ".join(features.education_text),
            features.resume_excerpt,
        ]
        cand.search_text = " ".join(p for p in parts if p)[:20000] or None
        return cand, features

    async def refresh_candidate_index(self, candidate_id: uuid.UUID) -> bool:
        """Rebuild the search text *and* the embedding. Idempotent: an unchanged source hash skips re-embedding."""
        cand, features = await self.refresh_candidate_text(candidate_id)
        try:
            changed = await self.refresh_candidate_embedding(cand, features)
        except EmbeddingError as exc:
            logger.warning(
                "candidate embedding skipped",
                extra={"candidate_id": str(candidate_id), "reason": str(exc)[:80]},
            )
            changed = False
        await self.session.commit()
        return changed

    async def refresh_job_index(self, job_id: uuid.UUID) -> bool:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        features = (await load_job_features(self.session, [job_id]))[job_id]
        job.skills_text = ", ".join(s.name for s in [*features.required, *features.preferred]) or None
        try:
            changed = await self.refresh_job_embedding(job, features)
        except EmbeddingError as exc:
            logger.warning("job embedding skipped", extra={"job_id": str(job_id), "reason": str(exc)[:80]})
            changed = False
        await self.session.commit()
        return changed

    # --- scoring + persistence -------------------------------------------------------------------------
    @staticmethod
    def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
        if a is None or b is None:
            return None
        return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))

    async def _upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        for start in range(0, len(rows), 500):
            chunk = rows[start : start + 500]
            stmt = pg_insert(CandidateJobMatch).values(chunk)
            update_cols = {c: stmt.excluded[c] for c in chunk[0] if c not in ("job_id", "candidate_id")}
            await self.session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_candidate_job_matches_job_candidate", set_=update_cols
                )
            )

    def _row(
        self, job: Job, cand: CandidateProfile, jf: JobFeatures, cf: CandidateFeatures, result: MatchResult
    ) -> dict[str, Any]:
        emb = get_embedder()
        return {
            "job_id": job.id,
            "candidate_id": cand.id,
            "overall_score": result.overall,
            "semantic_score": result.semantic,
            "raw_cosine": result.raw_cosine,
            "required_skill_score": result.required,
            "preferred_skill_score": result.preferred,
            "experience_score": result.experience,
            "education_score": result.education,
            "preference_score": result.preference,
            "explanation": result.explanation,
            "matching_version": MATCHING_VERSION,
            "embedding_model": emb.name,
            "embedding_version": emb.version,
            "job_hash": jf.feature_hash(),
            "candidate_hash": cf.feature_hash(),
            "generated_at": utcnow(),
        }

    async def _set_ef_search(self, value: int = 200) -> None:
        await self.session.execute(text(f"SET LOCAL hnsw.ef_search = {int(value)}"))

    async def eligible_candidate_ids_for_job(self, job: Job, limit: int) -> list[uuid.UUID]:
        """Vector retrieval of eligible candidates (marketplace + company-sourced + applicants), then all applicants."""
        applicants = select(Application.candidate_id).where(
            Application.job_id == job.id, Application.status != ApplicationStatus.WITHDRAWN
        )
        ids: list[uuid.UUID] = []
        if job.embedding is not None:
            await self._set_ef_search()
            dist = CandidateProfile.embedding.cosine_distance(job.embedding)
            eligible = or_(
                and_(
                    CandidateProfile.source == CandidateSource.SELF, CandidateProfile.is_searchable.is_(True)
                ),
                and_(
                    CandidateProfile.source == CandidateSource.IMPORTED,
                    CandidateProfile.sourced_by_company_id == job.company_id,
                ),
                CandidateProfile.id.in_(applicants),
            )
            rows = await self.session.execute(
                select(CandidateProfile.id)
                .where(CandidateProfile.embedding.is_not(None), eligible)
                .order_by(dist)
                .limit(limit)
            )
            ids = [r[0] for r in rows.all()]
        seen = set(ids)
        for (cid,) in (await self.session.execute(applicants)).all():  # applicants are always scored
            if cid not in seen:
                ids.append(cid)
                seen.add(cid)
        return ids

    async def match_job(
        self, job_id: uuid.UUID, *, notify: bool = False, limit: int | None = None
    ) -> MatchRunSummary:
        """(Re)score a job against its candidate pool and persist the results (idempotent upsert)."""
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        jf = (await load_job_features(self.session, [job_id]))[job_id]
        embedded_job = False
        try:
            embedded_job = await self.refresh_job_embedding(job, jf)
        except EmbeddingError:
            logger.warning("job has too little text to embed", extra={"job_id": str(job_id)})
        job.skills_text = ", ".join(s.name for s in [*jf.required, *jf.preferred]) or None
        await self.session.commit()

        cand_ids = await self.eligible_candidate_ids_for_job(
            job, limit or self.settings.match_retrieval_limit
        )
        cfs = await load_candidate_features(self.session, cand_ids)
        cands = {
            c.id: c
            for c in (
                await self.session.execute(select(CandidateProfile).where(CandidateProfile.id.in_(cand_ids)))
            ).scalars()
        }
        embedded_c = 0
        rows: list[dict[str, Any]] = []
        results: list[tuple[uuid.UUID, float]] = []
        for cid in cand_ids:
            c, cf = cands.get(cid), cfs.get(cid)
            if c is None or cf is None:
                continue
            try:  # a candidate whose embedding is stale/missing is refreshed lazily here
                if await self.refresh_candidate_embedding(c, cf):
                    embedded_c += 1
            except EmbeddingError:
                pass
            result = score_pair(jf, cf, self._cosine(job.embedding, c.embedding))
            rows.append(self._row(job, c, jf, cf, result))
            results.append((cid, result.overall))
        await self._upsert(rows)
        # Drop stale rows for candidates that are no longer in the pool (e.g. opted out of the marketplace or withdrew). Only when the
        # whole pool was evaluated (the job has an embedding): without one only applicants are scored and the rest must be kept.
        if job.embedding is not None:
            await self.session.execute(
                text("DELETE FROM candidate_job_matches WHERE job_id = :j AND candidate_id <> ALL(:ids)"),
                {"j": job_id, "ids": cand_ids},
            )
        if notify:
            await self._notify_job_matches(job, sorted(results, key=lambda r: -r[1]))
        await self.session.commit()
        top = max((s for _, s in results), default=None)
        logger.info(
            "job matched",
            extra={"job_id": str(job_id), "scored": len(rows), "embedded_candidates": embedded_c},
        )
        return MatchRunSummary(len(rows), embedded_job, embedded_c, top)

    async def _notify_job_matches(self, job: Job, ranked: list[tuple[uuid.UUID, float]]) -> None:
        """New-job recommendation to strong-match candidates (registered users only), once per (candidate, job)."""
        notifier = NotificationService(self.session)
        strong = [(cid, s) for cid, s in ranked if s >= NOTIFY_THRESHOLD][:NOTIFY_MAX_PER_JOB]
        if not strong:
            return
        user_ids = {
            cid: uid
            for cid, uid in (
                await self.session.execute(
                    select(CandidateProfile.id, CandidateProfile.user_id).where(
                        CandidateProfile.id.in_([c for c, _ in strong])
                    )
                )
            ).all()
            if uid is not None
        }
        for cid, score in strong:
            uid = user_ids.get(cid)
            if uid:
                await notifier.stage(
                    uid,
                    NotificationType.NEW_JOB_RECOMMENDATION,
                    "New job matches your profile",
                    f"“{job.title}” is a {round(score * 100)}% match for your profile.",
                    job_id=job.id,
                    dedupe_key=f"job-rec:{job.id}",
                )
        top_strong = [r for r in ranked if r[1] >= RECRUITER_NOTIFY_THRESHOLD]
        if top_strong:  # one aggregated heads-up for the people responsible for the job
            for uid in {u for u in (job.created_by_id, job.hiring_manager_id) if u}:
                await notifier.stage(
                    uid,
                    NotificationType.NEW_CANDIDATE_MATCH,
                    "Strong candidate matches found",
                    f"{len(top_strong)} candidate{'s' if len(top_strong) != 1 else ''} match “{job.title}” at {round(RECRUITER_NOTIFY_THRESHOLD * 100)}% or more.",
                    job_id=job.id,
                    dedupe_key=f"job-matches:{job.id}",
                )

    async def match_candidate(self, candidate_id: uuid.UUID, *, limit: int | None = None) -> MatchRunSummary:
        """(Re)score one candidate against live jobs (vector top-K) and persist."""
        cand = await self.session.get(CandidateProfile, candidate_id)
        if cand is None:
            raise NotFoundError("Candidate not found", code="CANDIDATE_NOT_FOUND")
        cf = (await load_candidate_features(self.session, [candidate_id]))[candidate_id]
        try:
            await self.refresh_candidate_embedding(cand, cf)
        except EmbeddingError:
            logger.info("candidate has too little data to embed", extra={"candidate_id": str(candidate_id)})
        await self.session.commit()
        if cand.embedding is None:
            return MatchRunSummary(0, False, 0, None)
        await self._set_ef_search()
        dist = Job.embedding.cosine_distance(cand.embedding)
        job_ids = [
            r[0]
            for r in (
                await self.session.execute(
                    select(Job.id)
                    .where(Job.embedding.is_not(None), _live_job_filter())
                    .order_by(dist)
                    .limit(limit or self.settings.recommendation_limit)
                )
            ).all()
        ]
        jfs = await load_job_features(self.session, job_ids)
        jobs = {
            j.id: j for j in (await self.session.execute(select(Job).where(Job.id.in_(job_ids)))).scalars()
        }
        previously_scored = {
            r[0]
            for r in (
                await self.session.execute(
                    select(CandidateJobMatch.job_id).where(
                        CandidateJobMatch.candidate_id == candidate_id, CandidateJobMatch.job_id.in_(job_ids)
                    )
                )
            ).all()
        }
        rows, best = [], None
        notifier = NotificationService(self.session)
        for jid in job_ids:
            j, jf = jobs.get(jid), jfs.get(jid)
            if j is None or jf is None:
                continue
            result = score_pair(jf, cf, self._cosine(j.embedding, cand.embedding))
            rows.append(self._row(j, cand, jf, cf, result))
            best = result.overall if best is None else max(best, result.overall)
            # First time this candidate is strongly matched to a live job → tell the job's owner (marketplace candidates only).
            if (
                result.overall >= RECRUITER_NOTIFY_THRESHOLD
                and jid not in previously_scored
                and cand.source == CandidateSource.SELF
                and cand.is_searchable
                and j.created_by_id
            ):
                await notifier.stage(
                    j.created_by_id,
                    NotificationType.NEW_CANDIDATE_MATCH,
                    "New strong candidate match",
                    f"{cand.display_name} is a {round(result.overall * 100)}% match for “{j.title}”.",
                    job_id=j.id,
                    dedupe_key=f"cand-match:{j.id}:{cand.id}",
                )
        await self._upsert(rows)
        await self.session.commit()
        return MatchRunSummary(len(rows), False, 0, best)

    # --- reads ------------------------------------------------------------------------------------------
    async def get_or_compute(self, job: Job, cand: CandidateProfile) -> CandidateJobMatch:
        """Return the stored match for the pair, recomputing when absent or stale (hash / version mismatch)."""
        jf = (await load_job_features(self.session, [job.id]))[job.id]
        cf = (await load_candidate_features(self.session, [cand.id]))[cand.id]
        emb = get_embedder()
        existing = (
            await self.session.execute(
                select(CandidateJobMatch).where(
                    CandidateJobMatch.job_id == job.id, CandidateJobMatch.candidate_id == cand.id
                )
            )
        ).scalar_one_or_none()
        fresh = (
            existing is not None
            and existing.job_hash == jf.feature_hash()
            and existing.candidate_hash == cf.feature_hash()
            and existing.matching_version == MATCHING_VERSION
            and existing.embedding_model == emb.name
            and existing.embedding_version == emb.version
        )
        if fresh:
            assert existing is not None
            return existing
        try:
            await self.refresh_job_embedding(job, jf)
            await self.refresh_candidate_embedding(cand, cf)
        except EmbeddingError:
            pass
        result = score_pair(jf, cf, self._cosine(job.embedding, cand.embedding))
        await self._upsert([self._row(job, cand, jf, cf, result)])
        await self.session.commit()
        return (
            await self.session.execute(
                select(CandidateJobMatch)
                .where(CandidateJobMatch.job_id == job.id, CandidateJobMatch.candidate_id == cand.id)
                # The upsert bypasses the ORM: without this the stale row already in the identity map would be returned as is.
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def reembed_all(self, ctx_progress: Any = None) -> dict[str, int]:
        """Regenerate embeddings for every job/candidate whose text, model or version changed (e.g. after a model upgrade).
        Unchanged items are skipped by their source hash, so this is cheap to re-run."""
        job_ids = [r[0] for r in (await self.session.execute(select(Job.id))).all()]
        cand_ids = [r[0] for r in (await self.session.execute(select(CandidateProfile.id))).all()]
        total = max(len(job_ids) + len(cand_ids), 1)
        n_jobs = n_cands = done = 0
        for jid in job_ids:
            n_jobs += int(await self.refresh_job_index(jid))
            done += 1
            if ctx_progress and done % 25 == 0:
                await ctx_progress(int(done * 100 / total), "embedding jobs")
        for cid in cand_ids:
            n_cands += int(await self.refresh_candidate_index(cid))
            done += 1
            if ctx_progress and done % 25 == 0:
                await ctx_progress(int(done * 100 / total), "embedding candidates")
        return {
            "jobs_reembedded": n_jobs,
            "candidates_reembedded": n_cands,
            "jobs_total": len(job_ids),
            "candidates_total": len(cand_ids),
        }
