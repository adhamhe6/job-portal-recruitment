"""Background-task handlers for résumés (see ``app.workers.tasks`` for the handler contract).

Both handlers are idempotent: ``handle_process_resume`` upserts a single processing result per résumé and merges skill
suggestions with ``ON CONFLICT``; ``handle_bulk_import`` only touches items that are still ``PENDING`` and finalises each
item in the same transaction that creates its candidate.
"""

from __future__ import annotations

from typing import Any

from app.resume.bulk import run_bulk_import
from app.resume.pipeline import run_process_resume
from app.workers.tasks import TaskContext


async def handle_process_resume(ctx: TaskContext) -> dict[str, Any]:
    return await run_process_resume(ctx)


async def handle_bulk_import(ctx: TaskContext) -> dict[str, Any]:
    return await run_bulk_import(ctx)
