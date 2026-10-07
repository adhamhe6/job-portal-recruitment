"""Dashboards and analytics reports. Role-scoped; list reports support pagination, sorting and ``?format=csv``."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    CacheDep,
    CurrentUser,
    DispatcherDep,
    Pagination,
    SessionDep,
    expensive_limit,
    require,
)
from app.core.security import Permission
from app.db.models import TaskType, User
from app.schemas.common import COMMON_ERRORS, TaskRef
from app.schemas.report import (
    AdminDashboard,
    ApplicationsByJobPage,
    ApplicationsByStatusOut,
    CandidateDashboard,
    FunnelOut,
    InterviewStatisticsOut,
    JobPerformancePage,
    MatchingPerformanceOut,
    PipelineSummaryOut,
    RecruiterActivityPage,
    RecruiterDashboard,
    SourceStatisticsPage,
    TopSkillsOut,
)
from app.services.reports import Granularity, ReportService, Table, csv_filename, make_window, render_csv
from app.services.tasks import TaskService

router = APIRouter(prefix="/reports", tags=["Reports"], responses=COMMON_ERRORS)


def _svc(session: SessionDep, cache: CacheDep) -> ReportService:
    return ReportService(session, cache)


Svc = Annotated[ReportService, Depends(_svc)]
Viewer = Annotated[User, Depends(require(Permission.VIEW_REPORTS))]
PlatformAdmin = Annotated[User, Depends(require(Permission.VIEW_ADMIN_REPORTS))]

CompanyParam = Annotated[
    uuid.UUID | None,
    Query(
        description="Admins only: restrict to one company (omit for the whole platform). Staff may only pass their own."
    ),
]
FromParam = Annotated[date | None, Query(description="First day to include (UTC, inclusive)")]
ToParam = Annotated[date | None, Query(description="Last day to include (UTC, inclusive)")]
FormatParam = Annotated[
    Literal["json", "csv"],
    Query(alias="format", description="`csv` returns text/csv (all rows up to 5000, ignoring pagination)"),
]
OrderParam = Annotated[Literal["asc", "desc"], Query(description="Sort direction")]

CSV_OK: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "JSON body, or `text/csv` (attachment) when `format=csv`. Text cells that start with `= + - @` are prefixed with `'` "
        "to neutralise spreadsheet formula injection.",
        "content": {"text/csv": {"schema": {"type": "string"}, "example": "job_id,title,applications\r\n…"}},
    }
}


def csv_response(table: Table) -> Response:
    return Response(
        content=render_csv(table),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{csv_filename(table.name)}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/recruiter-dashboard",
    response_model=RecruiterDashboard,
    summary="Recruiter dashboard (hiring managers: assigned jobs only)",
    description=(
        "KPIs, hiring funnel, applications over time, applications per job, status distribution, interview activity, the best "
        "semantic matches for published jobs and the latest applications - all computed in SQL and cached (60 s, invalidated by "
        "writes). The window defaults to the last 30 days; `total_applications`, the funnel, the charts and `hires_in_period` use it, "
        "while screening / shortlisted / interviews / deadlines are current snapshots. The funnel counts applications that ever "
        "*reached* a stage (from the status history), with REJECTED / WITHDRAWN as branches."
    ),
)
async def recruiter_dashboard(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    granularity: Annotated[
        Granularity | None, Query(description="Bucket size for time series (default: chosen from the range)")
    ] = None,
) -> RecruiterDashboard:
    return await svc.recruiter_dashboard(
        user, company_id=company_id, from_date=from_date, to_date=to_date, granularity=granularity
    )


@router.get(
    "/candidate-dashboard",
    response_model=CandidateDashboard,
    summary="Candidate dashboard (own data only)",
    description=(
        "Profile completion, application counts by status, the next 5 interviews, the top 5 recommended published jobs (not already "
        "applied to) with score, band and summary, résumé processing status, saved jobs and unread notifications."
    ),
)
async def candidate_dashboard(user: CurrentUser, svc: Svc) -> CandidateDashboard:
    return await svc.candidate_dashboard(user)


@router.get(
    "/admin-dashboard",
    response_model=AdminDashboard,
    summary="Platform dashboard (admins)",
    description="Users by role/status, companies, jobs / applications / interviews / résumés by status, tasks of the last 24 h, signups, recent audit events and match totals.",
)
async def admin_dashboard(user: PlatformAdmin, svc: Svc) -> AdminDashboard:
    return await svc.admin_dashboard(user)


@router.get(
    "/applications-by-job",
    response_model=ApplicationsByJobPage,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Applications per job",
    description="Jobs that received applications in the period, with the per-status breakdown. Sortable and paginated; `format=csv` exports all rows.",
)
async def applications_by_job(
    user: Viewer,
    svc: Svc,
    p: Pagination,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    sort: Annotated[
        Literal["applications", "title", "shortlisted", "hired", "rejected"], Query()
    ] = "applications",
    order: OrderParam = "desc",
    fmt: FormatParam = "json",
) -> ApplicationsByJobPage | Response:
    if fmt == "csv":
        return csv_response(
            await svc.applications_by_job_table(
                user, company_id=company_id, from_date=from_date, to_date=to_date, sort=sort, order=order
            )
        )
    return await svc.applications_by_job(
        user,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        order=order,
        page=p.page,
        page_size=p.page_size,
    )


@router.get(
    "/applications-by-status",
    response_model=ApplicationsByStatusOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Applications by current status",
    description="All eight statuses (zero-filled) for applications received in the period, optionally for one job.",
)
async def applications_by_status(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    job_id: uuid.UUID | None = None,
    fmt: FormatParam = "json",
) -> ApplicationsByStatusOut | Response:
    out = await svc.applications_by_status(
        user, company_id=company_id, from_date=from_date, to_date=to_date, job_id=job_id
    )
    return csv_response(svc.applications_by_status_table(out)) if fmt == "csv" else out


@router.get(
    "/funnel",
    response_model=FunnelOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Hiring funnel (optionally per job)",
    description="Cumulative counts of applications that reached APPLIED → SCREENING → SHORTLISTED → INTERVIEW → OFFER → HIRED, taken from the "
    "status history, plus the REJECTED / WITHDRAWN branches.",
)
async def funnel(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    job_id: uuid.UUID | None = None,
    fmt: FormatParam = "json",
) -> FunnelOut | Response:
    out = await svc.funnel(user, company_id=company_id, from_date=from_date, to_date=to_date, job_id=job_id)
    return csv_response(svc.funnel_table(out)) if fmt == "csv" else out


@router.get(
    "/interview-statistics",
    response_model=InterviewStatisticsOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Interview statistics",
    description="Counts by status and type, average duration, no-show rate (no-shows / (completed + no-shows)), cancellation rate and the "
    "feedback rating / recommendation distribution. The window applies to the interview start time.",
)
async def interview_statistics(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    fmt: FormatParam = "json",
) -> InterviewStatisticsOut | Response:
    out = await svc.interview_statistics(user, company_id=company_id, from_date=from_date, to_date=to_date)
    return csv_response(svc.interview_statistics_table(out)) if fmt == "csv" else out


@router.get(
    "/job-performance",
    response_model=JobPerformancePage,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Per-job performance",
    description="Applications, shortlist rate, hire rate, average days to first status change and to hire, and the average match score of the "
    "applicants. Job views are not tracked, so the funnel starts at the application. Use `POST /reports/job-performance/export` for a "
    "background CSV export.",
)
async def job_performance(
    user: Viewer,
    svc: Svc,
    p: Pagination,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    sort: Annotated[
        Literal[
            "applications", "title", "shortlist_rate", "hire_rate", "avg_days_to_hire", "avg_match_score"
        ],
        Query(),
    ] = "applications",
    order: OrderParam = "desc",
    fmt: FormatParam = "json",
) -> JobPerformancePage | Response:
    if fmt == "csv":
        return csv_response(
            await svc.job_performance_table(
                user, company_id=company_id, from_date=from_date, to_date=to_date, sort=sort, order=order
            )
        )
    return await svc.job_performance(
        user,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        order=order,
        page=p.page,
        page_size=p.page_size,
    )


@router.post(
    "/job-performance/export",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Export the job-performance report as a background CSV",
    description="Queues an `EXPORT_REPORT` task; poll `GET /api/v1/tasks/{task_id}` - the CSV text is in `result.csv` once COMPLETED. Repeating the "
    "same request while one is running returns the running task.",
    dependencies=[Depends(expensive_limit)],
)
async def export_job_performance(
    user: Viewer,
    svc: Svc,
    session: SessionDep,
    dispatcher: DispatcherDep,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    sort: Annotated[
        Literal[
            "applications", "title", "shortlist_rate", "hire_rate", "avg_days_to_hire", "avg_match_score"
        ],
        Query(),
    ] = "applications",
    order: OrderParam = "desc",
) -> TaskRef:
    scope = await svc.resolve_scope(user, company_id)  # fail fast with the proper 403/404
    make_window(from_date, to_date)
    params = {
        "report": "job-performance",
        "company_id": str(scope.company_id) if scope.company_id else None,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "sort": sort,
        "order": order,
    }
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    task, _ = await TaskService(session).submit(
        TaskType.EXPORT_REPORT,
        params,
        dispatcher,
        created_by_id=user.id,
        company_id=scope.company_id,
        dedupe_key=f"export-report:{user.id}:{digest}",
    )
    return TaskRef(task_id=str(task.id), status=task.status.value)


@router.get(
    "/recruiter-activity",
    response_model=RecruiterActivityPage,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Activity per recruiter (recruiters, admins)",
    description="Stage changes (status history), interviews scheduled (audit events), notes and feedback entries per staff member. "
    "Hiring managers are refused.",
)
async def recruiter_activity(
    user: Viewer,
    svc: Svc,
    p: Pagination,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    sort: Annotated[
        Literal["total", "status_changes", "interviews_scheduled", "notes", "feedback", "name"], Query()
    ] = "total",
    order: OrderParam = "desc",
    fmt: FormatParam = "json",
) -> RecruiterActivityPage | Response:
    if fmt == "csv":
        return csv_response(
            await svc.recruiter_activity_table(
                user, company_id=company_id, from_date=from_date, to_date=to_date, sort=sort, order=order
            )
        )
    return await svc.recruiter_activity(
        user,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        order=order,
        page=p.page,
        page_size=p.page_size,
    )


@router.get(
    "/source-statistics",
    response_model=SourceStatisticsPage,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Applications by source",
    description="Where applications come from (DIRECT, SEARCH, RECOMMENDATION, REFERRAL) with shortlist and hire rates per source.",
)
async def source_statistics(
    user: Viewer,
    svc: Svc,
    p: Pagination,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    sort: Annotated[Literal["applications", "source", "hires", "shortlisted"], Query()] = "applications",
    order: OrderParam = "desc",
    fmt: FormatParam = "json",
) -> SourceStatisticsPage | Response:
    if fmt == "csv":
        return csv_response(
            await svc.source_statistics_table(
                user, company_id=company_id, from_date=from_date, to_date=to_date, sort=sort, order=order
            )
        )
    return await svc.source_statistics(
        user,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        order=order,
        page=p.page,
        page_size=p.page_size,
    )


@router.get(
    "/matching-performance",
    response_model=MatchingPerformanceOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="What the stored match scores show",
    description="Score distribution by band, average score of hired vs rejected applicants (with sample sizes) and the share of applicants who "
    "ranked in their job's top 10 scored candidates. Descriptive only: it does not claim the score predicts hiring.",
)
async def matching_performance(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    from_date: FromParam = None,
    to_date: ToParam = None,
    fmt: FormatParam = "json",
) -> MatchingPerformanceOut | Response:
    out = await svc.matching_performance(user, company_id=company_id, from_date=from_date, to_date=to_date)
    return csv_response(svc.matching_performance_table(out)) if fmt == "csv" else out


@router.get(
    "/top-skills",
    response_model=TopSkillsOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Most requested vs most common skills",
    description="Skills most requested by published jobs next to the skills most common among the applicants (confirmed candidate skills). "
    "Admins without `company_id` get the platform-wide view.",
)
async def top_skills(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    limit: Annotated[int, Query(ge=1, le=50, description="Entries per list")] = 15,
    fmt: FormatParam = "json",
) -> TopSkillsOut | Response:
    out = await svc.top_skills(user, company_id=company_id, limit=limit)
    return csv_response(svc.top_skills_table(out)) if fmt == "csv" else out


@router.get(
    "/pipeline-summary",
    response_model=PipelineSummaryOut,
    responses={**COMMON_ERRORS, **CSV_OK},
    summary="Current pipeline snapshot",
    description="Applications per stage right now with the time spent in the current stage and how many live applications have been waiting for "
    "more than 14 days.",
)
async def pipeline_summary(
    user: Viewer,
    svc: Svc,
    company_id: CompanyParam = None,
    job_id: uuid.UUID | None = None,
    fmt: FormatParam = "json",
) -> PipelineSummaryOut | Response:
    out = await svc.pipeline_summary(user, company_id=company_id, job_id=job_id)
    return csv_response(svc.pipeline_summary_table(out)) if fmt == "csv" else out
