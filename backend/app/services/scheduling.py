"""Fire-and-forget scheduling of derived-data refreshes (embeddings, matches).

A failure to *enqueue* (Redis down) must never fail the user's primary action: derived data is rebuilt later (next
change, the periodic sweep, or lazily on read), so we log and carry on.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceUnavailableError
from app.db.models import TaskType
from app.services.tasks import Dispatcher, TaskService

logger = logging.getLogger(__name__)


async def schedule_candidate_refresh(
    session: AsyncSession,
    dispatcher: Dispatcher | None,
    candidate_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> None:
    if dispatcher is None:
        return
    try:
        await TaskService(session).submit(
            TaskType.MATCH_CANDIDATE,
            {"candidate_id": str(candidate_id)},
            dispatcher,
            created_by_id=user_id,
            dedupe_key=f"match-candidate:{candidate_id}",
        )
    except ServiceUnavailableError:
        logger.warning(
            "candidate refresh not queued (queue unavailable)", extra={"candidate_id": str(candidate_id)}
        )


async def schedule_job_match(
    session: AsyncSession,
    dispatcher: Dispatcher | None,
    job_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    notify: bool = False,
) -> tuple[uuid.UUID | None, bool]:
    """Returns ``(task_id, created)``; ``(None, False)`` when the queue is unavailable."""
    if dispatcher is None:
        return None, False
    try:
        task, created = await TaskService(session).submit(
            TaskType.MATCH_JOB,
            {"job_id": str(job_id), "notify": notify},
            dispatcher,
            created_by_id=user_id,
            company_id=company_id,
            dedupe_key=f"match-job:{job_id}",
        )
        return task.id, created
    except ServiceUnavailableError:
        logger.warning("job match not queued (queue unavailable)", extra={"job_id": str(job_id)})
        return None, False
