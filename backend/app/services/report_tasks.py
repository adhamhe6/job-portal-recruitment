"""Background handler for ``TaskType.EXPORT_REPORT`` (registered in ``app.workers.tasks.HANDLER_PATHS``).

The one supported export is the *job performance* report as CSV. The CSV text is stored in the task ``result`` (capped at
``RESULT_MAX_ROWS`` rows so the JSONB value stays small); the requester downloads it from ``GET /api/v1/tasks/{id}``.
The authorization scope is derived from the *requesting user* when the task runs, never from client-supplied parameters.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.core.errors import AppError
from app.db.models import User, UserStatus
from app.services.reports import ReportService, SortOrder, csv_filename, render_csv
from app.workers.tasks import TaskContext, TaskFailure

RESULT_MAX_ROWS = 1000
SUPPORTED_REPORTS = ("job-performance",)


def _opt_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


async def handle_export_report(ctx: TaskContext) -> dict[str, Any]:
    params = ctx.params
    if params.get("report") not in SUPPORTED_REPORTS:
        raise TaskFailure("UNSUPPORTED_REPORT", "This report cannot be exported in the background")
    if ctx.created_by_id is None:
        raise TaskFailure("EXPORT_FORBIDDEN", "The export has no requesting user")
    try:
        company_id = uuid.UUID(params["company_id"]) if params.get("company_id") else None
        from_date, to_date = _opt_date(params.get("from_date")), _opt_date(params.get("to_date"))
    except (ValueError, TypeError) as exc:
        raise TaskFailure("INVALID_PARAMETERS", "The export parameters are invalid") from exc
    sort = str(params.get("sort") or "applications")
    order: SortOrder = "asc" if params.get("order") == "asc" else "desc"

    await ctx.progress(10, "checking access")
    async with ctx.sessionmaker() as session:
        user = await session.get(User, ctx.created_by_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise TaskFailure("EXPORT_FORBIDDEN", "The requesting user can no longer export reports")
        await ctx.progress(30, "querying")
        try:
            table = await ReportService(session).job_performance_table(
                user, company_id=company_id, from_date=from_date, to_date=to_date, sort=sort, order=order
            )
        except AppError as exc:  # permission / validation problems become a clean, user-facing failure
            raise TaskFailure(exc.code, exc.message) from exc

    await ctx.progress(80, "rendering CSV")
    total_rows = len(table.rows)
    table.rows = table.rows[:RESULT_MAX_ROWS]
    return {
        "report": "job-performance",
        "filename": csv_filename("job-performance"),
        "content_type": "text/csv",
        "rows": len(table.rows),
        "total_rows": total_rows,
        "truncated": total_rows > RESULT_MAX_ROWS,
        "csv": render_csv(table),
    }
