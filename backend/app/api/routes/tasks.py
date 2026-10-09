from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.common import COMMON_ERRORS
from app.schemas.notification import TaskOut
from app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"], responses=COMMON_ERRORS)


@router.get(
    "/{task_id}",
    response_model=TaskOut,
    summary="Background task status",
    description="Poll until `status` is COMPLETED or FAILED. `progress` (0-100) and `stage` are written by the worker as it runs. "
    "(Named *tasks* because `/jobs` is the job-posting resource.)",
)
async def get_task(task_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> TaskOut:
    return TaskOut.model_validate(await TaskService(session).get_for_user(user, task_id))
