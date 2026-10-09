"""Reports & dashboards.

Every figure is an SQL aggregate over the real tables - no Python loops over large row sets (the only loops are over
bucket lists and fixed enums, both bounded). Results are cached with versioned-namespace invalidation (``Cache.get_or_set``):
each report names the data domains it depends on, so a write to jobs / applications / interviews / matches / candidates
makes the next request recompute. Items that no cache domain tracks (unread notifications, résumé status, saved jobs) are
always read live.

Authorization is resolved once in :meth:`ReportService.resolve_scope`: recruiters are strictly company-scoped, hiring
managers are limited to jobs assigned to them, admins may look at one company or the whole platform, everyone else is refused.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import Date, Numeric, and_, case, cast, desc, extract, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationFailure
from app.core.security import STAFF_ROLES, Role
from app.db.models import (
    ACTIVE_INTERVIEW_STATUSES,
    Application,
    ApplicationNote,
    ApplicationStatus,
    ApplicationStatusHistory,
    AuditEvent,
    BackgroundTask,
    CandidateJobMatch,
    CandidateProfile,
    CandidateSkill,
    Company,
    CompanyStatus,
    HireRecommendation,
    Interview,
    InterviewFeedback,
    InterviewStatus,
    InterviewType,
    Job,
    JobSkill,
    JobStatus,
    Resume,
    ResumeDocument,
    ResumeProcessingResult,
    ResumeStatus,
    SavedJob,
    Skill,
    SkillRequirement,
    SkillStatus,
    TaskStatus,
    User,
    UserStatus,
)
from app.matching.scoring import overall_band
from app.schemas.report import (
    AdminDashboard,
    ApplicationsByJobPage,
    ApplicationsByJobRow,
    ApplicationsByStatusOut,
    AuditBrief,
    BandCount,
    CandidateDashboard,
    CompanyTotals,
    FeedbackStats,
    FunnelOut,
    FunnelStage,
    InterviewActivityPoint,
    InterviewStatisticsOut,
    JobCount,
    JobPerformancePage,
    JobPerformanceRow,
    MatchingPerformanceOut,
    MatchTotals,
    OutcomeScore,
    Period,
    PipelineStageRow,
    PipelineSummaryOut,
    ProfileCompletionBrief,
    RecentApplication,
    RecommendedJobBrief,
    RecruiterActivityPage,
    RecruiterActivityRow,
    RecruiterDashboard,
    RecruiterKpis,
    ResumeStatusBrief,
    SeriesPoint,
    SkillDemand,
    SkillSupply,
    SourceStatisticsPage,
    SourceStatRow,
    StatusCount,
    TopMatch,
    TopSkillsOut,
    TopTenStats,
    UpcomingInterview,
)
from app.search.candidates import visibility_predicate
from app.services.candidates import CandidateService
from app.services.common import paginate, utcnow
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
Granularity = Literal["day", "week", "month"]
SortOrder = Literal["asc", "desc"]

A = Application
H = ApplicationStatusHistory
J = Job
Iv = Interview
Mt = CandidateJobMatch

DASHBOARD_TTL = 60
ANALYTICS_TTL = 120
ACTIVITY_TTL = 30  # application notes do not bump a cache domain, so keep the activity report short-lived
ADMIN_TTL = 15  # users / résumés / tasks / audit events are not tracked by a cache domain
DEFAULT_DASHBOARD_DAYS = 30
MAX_RANGE_DAYS = 1830
MAX_BUCKETS = 400
MAX_EXPORT_ROWS = 5000
STALE_AFTER_DAYS = 14
FUNNEL_MAIN = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.HIRED,
)
_RANK = {st: i + 1 for i, st in enumerate(FUNNEL_MAIN)}  # APPLIED=1 … HIRED=6
_SHORTLIST_OR_LATER = (
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.HIRED,
)
_LIVE = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
)
# Mirrors app.matching.scoring.overall_band (a unit test keeps the two in sync).
BAND_EDGES: tuple[tuple[str, float], ...] = (("STRONG", 0.75), ("GOOD", 0.55), ("PARTIAL", 0.35))
BAND_ORDER = ("STRONG", "GOOD", "PARTIAL", "WEAK")
_ALL_DOMAINS = (
    CacheDomain.JOBS,
    CacheDomain.APPLICATIONS,
    CacheDomain.INTERVIEWS,
    CacheDomain.MATCHES,
    CacheDomain.CANDIDATES,
    CacheDomain.USERS,
)


# --------------------------------------------------------------------------------------------------------------------
# small value helpers
# --------------------------------------------------------------------------------------------------------------------
def _today() -> date:
    return date.today()


def _ratio(n: int | float, d: int | float, digits: int = 4) -> float | None:
    return round(n / d, digits) if d else None


def _pct(n: int | float, d: int | float) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _round(v: Any, digits: int = 2) -> float | None:
    return round(float(v), digits) if v is not None else None


def _cnt(*conds: Any) -> Any:
    """``count(*)`` or ``count(*) FILTER (WHERE …)``."""
    real = [c for c in conds if c is not None]
    return func.count().filter(and_(*real)) if real else func.count()


def _fill(enum_cls: Any, rows: Sequence[tuple[Any, int]]) -> dict[str, int]:
    out = {m.value: 0 for m in enum_cls}
    for key, n in rows:
        out[getattr(key, "value", key)] = int(n)
    return out


def _rank(col: Any) -> Any:
    """Position of a status on the main hiring line (APPLIED=1 … HIRED=6); branches rank as 1."""
    return case(*[(col == st, rk) for st, rk in _RANK.items() if rk > 1], else_=1)


def band_case(col: Any) -> Any:
    return case(*[(col >= edge, name) for name, edge in BAND_EDGES], else_="WEAK")


# --------------------------------------------------------------------------------------------------------------------
# scope & window
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Scope:
    user: User
    company_id: uuid.UUID | None  # None: platform-wide (admins only)
    hiring_manager_id: uuid.UUID | None  # set: only jobs assigned to this hiring manager

    @property
    def kind(self) -> Literal["company", "assigned_jobs", "platform"]:
        if self.hiring_manager_id:
            return "assigned_jobs"
        return "company" if self.company_id else "platform"

    def job_conds(self, job: Any = Job) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.company_id:
            conds.append(job.company_id == self.company_id)
        if self.hiring_manager_id:
            conds.append(job.hiring_manager_id == self.hiring_manager_id)
        return conds

    def cache_params(self) -> dict[str, Any]:
        return {
            "user": str(self.user.id),
            "company": str(self.company_id) if self.company_id else None,
            "hm": str(self.hiring_manager_id) if self.hiring_manager_id else None,
        }


@dataclass(frozen=True, slots=True)
class Window:
    start: date | None = None  # inclusive UTC calendar day
    end: date | None = None  # inclusive

    def conds(self, col: Any) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.start:
            conds.append(col >= datetime.combine(self.start, time.min, UTC))
        if self.end:
            conds.append(col < datetime.combine(self.end + timedelta(days=1), time.min, UTC))
        return conds

    def params(self) -> dict[str, Any]:
        return {
            "from": self.start.isoformat() if self.start else None,
            "to": self.end.isoformat() if self.end else None,
        }

    def period(self, granularity: Granularity | None = None) -> Period:
        return Period(from_date=self.start, to_date=self.end, granularity=granularity)


def make_window(from_date: date | None, to_date: date | None, *, default_days: int | None = None) -> Window:
    """Validate a user-supplied date range. With ``default_days`` an absent range becomes "the last N days"."""
    if from_date and to_date and from_date > to_date:
        raise ValidationFailure("from_date must not be after to_date", code="INVALID_DATE_RANGE")
    if default_days:
        to_date = to_date or datetime.now(UTC).date()
        from_date = from_date or (to_date - timedelta(days=default_days - 1))
        if from_date > to_date:
            raise ValidationFailure("from_date must not be after to_date", code="INVALID_DATE_RANGE")
    if from_date and to_date and (to_date - from_date).days > MAX_RANGE_DAYS:
        raise ValidationFailure(
            f"The date range may span at most {MAX_RANGE_DAYS} days", code="DATE_RANGE_TOO_LARGE"
        )
    return Window(from_date, to_date)


def _bucket_floor(d: date, gran: Granularity) -> date:
    if gran == "week":
        return d - timedelta(days=d.weekday())  # ISO weeks start on Monday, like date_trunc('week')
    if gran == "month":
        return d.replace(day=1)
    return d


def _bucket_next(d: date, gran: Granularity) -> date:
    if gran == "day":
        return d + timedelta(days=1)
    if gran == "week":
        return d + timedelta(days=7)
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def bucket_starts(start: date, end: date, gran: Granularity) -> list[date]:
    out: list[date] = []
    cur = _bucket_floor(start, gran)
    while cur <= end:
        out.append(cur)
        cur = _bucket_next(cur, gran)
    return out


def pick_granularity(window: Window, requested: Granularity | None) -> Granularity:
    assert window.start is not None
    assert window.end is not None
    days = (window.end - window.start).days + 1
    auto: Granularity = "day" if days <= 62 else "week" if days <= 400 else "month"
    gran = requested or auto
    if len(bucket_starts(window.start, window.end, gran)) > MAX_BUCKETS:
        raise ValidationFailure(
            f"Too many {gran} buckets for this range (max {MAX_BUCKETS}); choose a coarser granularity",
            code="GRANULARITY_TOO_FINE",
        )
    return gran


def _bucket_expr(col: Any, gran: Granularity) -> Any:
    """``date_trunc(gran, col AT TIME ZONE 'UTC')::date`` with the unit inlined (a closed set, never user text)."""
    units: dict[str, Any] = {
        "day": literal_column("'day'"),
        "week": literal_column("'week'"),
        "month": literal_column("'month'"),
    }
    unit = units[gran]
    return cast(func.date_trunc(unit, func.timezone("UTC", col)), Date)


def _series(rows: Sequence[tuple[date, int]], window: Window, gran: Granularity) -> list[SeriesPoint]:
    assert window.start is not None
    assert window.end is not None
    have = {d: int(n) for d, n in rows}
    return [
        SeriesPoint(bucket=b, count=have.get(b, 0)) for b in bucket_starts(window.start, window.end, gran)
    ]


# --------------------------------------------------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------------------------------------------------
@dataclass(slots=True)
class Table:
    name: str
    headers: list[str]
    rows: list[list[Any]]


_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:
    """Render one cell. Text a spreadsheet would read as a formula gets a leading apostrophe (CSV injection)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        if value.lstrip(" ").startswith(_DANGEROUS_PREFIXES):
            return "'" + value
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def render_csv(table: Table) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([csv_cell(h) for h in table.headers])
    for row in table.rows:
        writer.writerow([csv_cell(c) for c in row])
    return buf.getvalue()


def build_page[P: BaseModel](
    cls: type[P], items: list[Any], *, page: int, page_size: int, total: int, period: Period
) -> P:
    return cls(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if total else 0,
        period=period,
    )


def csv_filename(name: str) -> str:
    return f"talentlens-{name}-{datetime.now(UTC):%Y%m%d}.csv"


class CandidateDashboardCore(BaseModel):
    """The cacheable part of the candidate dashboard (everything driven by tracked cache domains)."""

    generated_at: datetime
    total_applications: int
    active_applications: int
    applications_by_status: list[StatusCount]
    upcoming_interviews: list[UpcomingInterview]
    recommended_jobs: list[RecommendedJobBrief]


# --------------------------------------------------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------------------------------------------------
class ReportService:
    def __init__(self, session: AsyncSession, cache: Cache | None = None) -> None:
        self.session = session
        self.cache = cache

    async def _cached(
        self,
        name: str,
        domains: Sequence[CacheDomain],
        params: dict[str, Any],
        compute: Callable[[], Awaitable[M]],
        model: type[M],
        *,
        ttl: int = ANALYTICS_TTL,
    ) -> M:
        if self.cache is None:
            return await compute()
        return await self.cache.get_or_set(
            name,
            domains,
            compute,
            params=params,
            ttl=ttl,
            serialize=lambda m: m.model_dump(mode="json"),
            deserialize=model.model_validate,
        )

    async def _fetch(self, stmt: Any, page: int | None, page_size: int | None) -> tuple[list[Any], int]:
        """One page (JSON) or up to ``MAX_EXPORT_ROWS`` rows (CSV export, ``page`` is None)."""
        if page is None:
            rows = list((await self.session.execute(stmt.limit(MAX_EXPORT_ROWS))).all())
            return rows, len(rows)
        return await paginate(self.session, stmt, page=page, page_size=page_size or 20, scalars=False)

    # ----------------------------------------------------------------------------------------------------------------
    # authorization
    # ----------------------------------------------------------------------------------------------------------------
    async def resolve_scope(
        self, user: User, company_id: uuid.UUID | None = None, *, allow_hiring_manager: bool = True
    ) -> Scope:
        if user.role == Role.ADMIN:
            if company_id is not None and await self.session.get(Company, company_id) is None:
                raise NotFoundError("Company not found", code="COMPANY_NOT_FOUND")
            return Scope(user, company_id, None)
        if user.role not in STAFF_ROLES or user.company_id is None:
            raise PermissionDeniedError("You do not have access to company reports")
        if company_id is not None and company_id != user.company_id:
            raise PermissionDeniedError("You can only view reports of your own company")
        if user.role == Role.HIRING_MANAGER:
            if not allow_hiring_manager:
                raise PermissionDeniedError("This report is available to recruiters only")
            return Scope(user, user.company_id, user.id)
        return Scope(user, user.company_id, None)

    # ----------------------------------------------------------------------------------------------------------------
    # shared building blocks
    # ----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _app_conds(
        scope: Scope, window: Window, job_id: uuid.UUID | None = None
    ) -> list[ColumnElement[bool]]:
        conds = scope.job_conds()
        conds += window.conds(A.applied_at)
        if job_id:
            conds.append(A.job_id == job_id)
        return conds

    async def _status_counts(
        self, scope: Scope, window: Window, job_id: uuid.UUID | None = None
    ) -> list[StatusCount]:
        rows = (
            await self.session.execute(
                select(A.status, func.count())
                .select_from(A)
                .join(J, J.id == A.job_id)
                .where(*self._app_conds(scope, window, job_id))
                .group_by(A.status)
            )
        ).all()
        have = {st: int(n) for st, n in rows}
        total = sum(have.values())
        return [
            StatusCount(status=st, count=have.get(st, 0), percent=_pct(have.get(st, 0), total))
            for st in ApplicationStatus
        ]

    async def _funnel(
        self, scope: Scope, window: Window, job_id: uuid.UUID | None = None
    ) -> tuple[int, list[FunnelStage]]:
        """Cumulative "reached" counts from application_status_history (an application that was shortlisted and later
        rejected still counts as having reached SHORTLISTED)."""
        reached = func.greatest(func.coalesce(func.max(_rank(H.to_status)), 1), _rank(A.status)).label("r")
        per_app = (
            select(A.id.label("id"), A.status.label("status"), reached)
            .select_from(A)
            .join(J, J.id == A.job_id)
            .outerjoin(H, H.application_id == A.id)
            .where(*self._app_conds(scope, window, job_id))
            .group_by(A.id, A.status)
            .subquery()
        )
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    *[func.count().filter(per_app.c.r >= rk) for rk in range(2, 7)],
                    func.count().filter(per_app.c.status == ApplicationStatus.REJECTED),
                    func.count().filter(per_app.c.status == ApplicationStatus.WITHDRAWN),
                ).select_from(per_app)
            )
        ).one()
        applied = int(row[0])
        counts = [applied, *[int(c) for c in row[1:6]]]
        stages: list[FunnelStage] = []
        for i, st in enumerate(FUNNEL_MAIN):
            prev = counts[i - 1] if i else 0
            stages.append(
                FunnelStage(
                    stage=st,
                    count=counts[i],
                    pct_of_applied=_pct(counts[i], applied) if applied else None,
                    pct_of_previous=_pct(counts[i], prev) if prev else None,
                )
            )
        for st, n in ((ApplicationStatus.REJECTED, int(row[6])), (ApplicationStatus.WITHDRAWN, int(row[7]))):
            stages.append(
                FunnelStage(
                    stage=st,
                    count=n,
                    pct_of_applied=_pct(n, applied) if applied else None,
                    pct_of_previous=None,
                    is_branch=True,
                )
            )
        return applied, stages

    def _cohort(self, scope: Scope, window: Window, job_id: uuid.UUID | None = None) -> tuple[Any, Any]:
        """CTEs: the applications of the scope/window, and per application the milestones read from its history."""
        apps = (
            select(
                A.id.label("id"),
                A.job_id.label("job_id"),
                A.candidate_id.label("candidate_id"),
                A.applied_at.label("applied_at"),
                A.status.label("status"),
                A.source.label("source"),
            )
            .select_from(A)
            .join(J, J.id == A.job_id)
            .where(*self._app_conds(scope, window, job_id))
            .cte("cohort_apps")
        )
        hist = (
            select(
                H.application_id.label("application_id"),
                func.min(H.created_at).filter(H.from_status.is_not(None)).label("first_change_at"),
                func.min(H.created_at).filter(H.to_status == ApplicationStatus.HIRED).label("hired_at"),
                func.bool_or(H.to_status.in_(_SHORTLIST_OR_LATER)).label("shortlisted"),
            )
            .select_from(H)
            .join(apps, apps.c.id == H.application_id)
            .group_by(H.application_id)
            .cte("cohort_hist")
        )
        return apps, hist

    # ----------------------------------------------------------------------------------------------------------------
    # recruiter / hiring-manager dashboard
    # ----------------------------------------------------------------------------------------------------------------
    async def recruiter_dashboard(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        granularity: Granularity | None,
    ) -> RecruiterDashboard:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date, default_days=DEFAULT_DASHBOARD_DAYS)
        gran = pick_granularity(window, granularity)
        return await self._cached(
            "recruiter-dashboard",
            _ALL_DOMAINS[:5],
            {**scope.cache_params(), **window.params(), "gran": gran},
            lambda: self._recruiter_dashboard(scope, window, gran),
            RecruiterDashboard,
            ttl=DASHBOARD_TTL,
        )

    async def _recruiter_dashboard(
        self, scope: Scope, window: Window, gran: Granularity
    ) -> RecruiterDashboard:
        s = self.session
        now = utcnow()
        today = _today()
        jc = scope.job_conds()
        assert window.start is not None
        assert window.end is not None

        active, nearing, advertised = (
            await s.execute(
                select(
                    _cnt(J.status == JobStatus.PUBLISHED),
                    _cnt(
                        J.status == JobStatus.PUBLISHED,
                        J.application_deadline.is_not(None),
                        J.application_deadline >= today,
                        J.application_deadline <= today + timedelta(days=7),
                    ),
                    _cnt(J.status.in_((JobStatus.PUBLISHED, JobStatus.PAUSED, JobStatus.CLOSED))),
                )
                .select_from(J)
                .where(*jc)
            )
        ).one()
        total_apps, in_screening, shortlisted = (
            await s.execute(
                select(
                    _cnt(*window.conds(A.applied_at)),
                    _cnt(A.status == ApplicationStatus.SCREENING),
                    _cnt(A.status == ApplicationStatus.SHORTLISTED),
                )
                .select_from(A)
                .join(J, J.id == A.job_id)
                .where(*jc)
            )
        ).one()
        upcoming = await s.scalar(
            select(func.count())
            .select_from(Iv)
            .join(A, A.id == Iv.application_id)
            .join(J, J.id == A.job_id)
            .where(
                *jc,
                Iv.status.in_(ACTIVE_INTERVIEW_STATUSES),
                Iv.start_at >= now,
                Iv.start_at < now + timedelta(days=7),
            )
        )
        hires = await s.scalar(
            select(func.count(func.distinct(H.application_id)))
            .select_from(H)
            .join(A, A.id == H.application_id)
            .join(J, J.id == A.job_id)
            .where(*jc, H.to_status == ApplicationStatus.HIRED, *window.conds(H.created_at))
        )
        _, funnel = await self._funnel(scope, window)
        status_dist = await self._status_counts(scope, window)

        bucket = _bucket_expr(A.applied_at, gran)
        over_time = (
            await s.execute(
                select(bucket, func.count())
                .select_from(A)
                .join(J, J.id == A.job_id)
                .where(*self._app_conds(scope, window))
                .group_by(bucket)
            )
        ).all()

        by_job_rows = (
            await s.execute(
                select(J.id, J.title, J.status, func.count().label("n"))
                .select_from(A)
                .join(J, J.id == A.job_id)
                .where(*self._app_conds(scope, window))
                .group_by(J.id)
                .order_by(desc("n"), J.title, J.id)
                .limit(8)
            )
        ).all()

        ibucket = _bucket_expr(Iv.start_at, gran)
        act_rows = (
            await s.execute(
                select(ibucket, Iv.status, func.count())
                .select_from(Iv)
                .join(A, A.id == Iv.application_id)
                .join(J, J.id == A.job_id)
                .where(*jc, *window.conds(Iv.start_at))
                .group_by(ibucket, Iv.status)
            )
        ).all()
        activity = {
            b: InterviewActivityPoint(bucket=b) for b in bucket_starts(window.start, window.end, gran)
        }
        for b, st, n in act_rows:
            if b in activity:
                setattr(activity[b], st.value.lower(), int(n))
                activity[b].total += int(n)

        # Aliases keep visibility_predicate's own Job / Application subquery uncorrelated from this query's tables:
        # "has applied to any job of my company" must not collapse into "applied to this very job".
        jx, ax = aliased(Job), aliased(Application)
        top_rows = (
            await s.execute(
                select(
                    Mt.overall_score,
                    CandidateProfile.id,
                    CandidateProfile.display_name,
                    CandidateProfile.headline,
                    jx.id,
                    jx.title,
                    ax.id,
                )
                .select_from(Mt)
                .join(jx, jx.id == Mt.job_id)
                .join(CandidateProfile, CandidateProfile.id == Mt.candidate_id)
                .outerjoin(
                    ax,
                    and_(
                        ax.job_id == Mt.job_id,
                        ax.candidate_id == Mt.candidate_id,
                        ax.status != ApplicationStatus.WITHDRAWN,
                    ),
                )
                .where(
                    jx.status == JobStatus.PUBLISHED, *scope.job_conds(jx), visibility_predicate(scope.user)
                )
                .order_by(Mt.overall_score.desc(), CandidateProfile.id)
                .limit(5)
            )
        ).all()

        recent_rows = (
            await s.execute(
                select(
                    A.id,
                    CandidateProfile.id,
                    CandidateProfile.display_name,
                    J.id,
                    J.title,
                    A.status,
                    A.applied_at,
                    Mt.overall_score,
                )
                .select_from(A)
                .join(J, J.id == A.job_id)
                .join(CandidateProfile, CandidateProfile.id == A.candidate_id)
                .outerjoin(Mt, and_(Mt.job_id == A.job_id, Mt.candidate_id == A.candidate_id))
                .where(*jc)
                .order_by(A.applied_at.desc(), A.id)
                .limit(8)
            )
        ).all()

        return RecruiterDashboard(
            scope=scope.kind,
            company_id=scope.company_id,
            period=window.period(gran),
            generated_at=now,
            kpis=RecruiterKpis(
                active_jobs=int(active),
                total_applications=int(total_apps),
                applications_in_screening=int(in_screening),
                shortlisted=int(shortlisted),
                upcoming_interviews=int(upcoming or 0),
                jobs_nearing_deadline=int(nearing),
                avg_applications_per_job=round(int(total_apps) / int(advertised), 2) if advertised else 0.0,
                hires_in_period=int(hires or 0),
            ),
            funnel=funnel,
            applications_over_time=_series([(b, int(n)) for b, n in over_time], window, gran),
            applications_by_job=[
                JobCount(job_id=jid, title=t, job_status=st, applications=int(n))
                for jid, t, st, n in by_job_rows
            ],
            status_distribution=status_dist,
            interview_activity=list(activity.values()),
            top_matching_candidates=[
                TopMatch(
                    candidate_id=cid,
                    candidate_name=name,
                    headline=head,
                    job_id=jid,
                    job_title=jt,
                    score=round(float(score), 4),
                    band=overall_band(float(score)),
                    application_id=aid,
                )
                for score, cid, name, head, jid, jt, aid in top_rows
            ],
            recent_applications=[
                RecentApplication(
                    id=aid,
                    candidate_id=cid,
                    candidate_name=name,
                    job_id=jid,
                    job_title=jt,
                    status=st,
                    applied_at=at,
                    match_score=round(float(sc), 4) if sc is not None else None,
                    match_band=overall_band(float(sc)) if sc is not None else None,
                )
                for aid, cid, name, jid, jt, st, at, sc in recent_rows
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # candidate dashboard
    # ----------------------------------------------------------------------------------------------------------------
    async def candidate_dashboard(self, user: User) -> CandidateDashboard:
        if user.role != Role.CANDIDATE:
            raise PermissionDeniedError("Only candidates have a candidate dashboard")
        cand = (
            await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
        ).scalar_one_or_none()
        if cand is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        candidate_id = cand.id
        core = await self._cached(
            "candidate-dashboard",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.INTERVIEWS, CacheDomain.MATCHES),
            {"candidate": str(candidate_id)},
            lambda: self._candidate_core(candidate_id),
            CandidateDashboardCore,
            ttl=DASHBOARD_TTL,
        )
        # Live parts: nothing invalidates a cache domain when these change.
        completion = (await CandidateService(self.session).own_profile(user)).completion
        saved = await self.session.scalar(
            select(func.count()).select_from(SavedJob).where(SavedJob.candidate_id == candidate_id)
        )
        return CandidateDashboard(
            generated_at=core.generated_at,
            profile_completion=ProfileCompletionBrief(percent=completion.percent, missing=completion.missing),
            total_applications=core.total_applications,
            active_applications=core.active_applications,
            applications_by_status=core.applications_by_status,
            upcoming_interviews=core.upcoming_interviews,
            recommended_jobs=core.recommended_jobs,
            resume=await self._resume_status(candidate_id),
            saved_jobs=int(saved or 0),
            unread_notifications=await NotificationService(self.session).unread_count(user),
        )

    async def _resume_status(self, candidate_id: uuid.UUID) -> ResumeStatusBrief:
        row = (
            await self.session.execute(
                select(
                    Resume.id,
                    Resume.status,
                    Resume.created_at,
                    ResumeDocument.original_filename,
                    ResumeProcessingResult.status,
                    ResumeProcessingResult.error_code,
                )
                .select_from(Resume)
                .outerjoin(ResumeDocument, ResumeDocument.resume_id == Resume.id)
                .outerjoin(ResumeProcessingResult, ResumeProcessingResult.resume_id == Resume.id)
                .where(Resume.candidate_id == candidate_id)
                .order_by(
                    Resume.is_primary.desc(),
                    Resume.created_at.desc(),
                    ResumeDocument.created_at.desc().nulls_last(),
                )
                .limit(1)
            )
        ).first()
        if row is None:
            return ResumeStatusBrief(has_resume=False)
        rid, status, created, filename, pstatus, err = row
        return ResumeStatusBrief(
            has_resume=True,
            resume_id=rid,
            filename=filename,
            status=status.value,
            processing_status=pstatus.value if pstatus else None,
            error_code=err,
            uploaded_at=created,
        )

    async def _candidate_core(self, candidate_id: uuid.UUID) -> CandidateDashboardCore:
        s = self.session
        now = utcnow()
        counts = {
            st: int(n)
            for st, n in (
                await s.execute(
                    select(A.status, func.count()).where(A.candidate_id == candidate_id).group_by(A.status)
                )
            ).all()
        }
        total = sum(counts.values())
        live = sum(n for st, n in counts.items() if st in _LIVE)
        by_status = [
            StatusCount(status=st, count=counts.get(st, 0), percent=_pct(counts.get(st, 0), total))
            for st in ApplicationStatus
        ]

        iv_rows = (
            await s.execute(
                select(Iv, J.id, J.title, Company.name)
                .select_from(Iv)
                .join(A, A.id == Iv.application_id)
                .join(J, J.id == A.job_id)
                .join(Company, Company.id == J.company_id)
                .where(
                    Iv.candidate_id == candidate_id,
                    Iv.status.in_(ACTIVE_INTERVIEW_STATUSES),
                    Iv.end_at >= now,
                )
                .order_by(Iv.start_at, Iv.id)
                .limit(5)
            )
        ).all()

        applied = select(A.job_id).where(
            A.candidate_id == candidate_id, A.status != ApplicationStatus.WITHDRAWN
        )
        rec_rows = (
            await s.execute(
                select(Mt.overall_score, Mt.explanation["summary"].astext, J, Company.name)
                .select_from(Mt)
                .join(J, J.id == Mt.job_id)
                .join(Company, Company.id == J.company_id)
                .where(
                    Mt.candidate_id == candidate_id,
                    J.status == JobStatus.PUBLISHED,
                    (J.application_deadline.is_(None)) | (J.application_deadline >= _today()),
                    J.id.not_in(applied),
                )
                .order_by(Mt.overall_score.desc(), J.id)
                .limit(5)
            )
        ).all()
        return CandidateDashboardCore(
            generated_at=now,
            total_applications=total,
            active_applications=live,
            applications_by_status=by_status,
            upcoming_interviews=[
                UpcomingInterview(
                    id=iv.id,
                    application_id=iv.application_id,
                    job_id=jid,
                    job_title=title,
                    company_name=cname,
                    interview_type=iv.interview_type.value,
                    start_at=iv.start_at,
                    end_at=iv.end_at,
                    timezone=iv.timezone,
                    status=iv.status,
                    location=iv.location,
                    meeting_url=iv.meeting_url,
                )
                for iv, jid, title, cname in iv_rows
            ],
            recommended_jobs=[
                RecommendedJobBrief(
                    job_id=job.id,
                    title=job.title,
                    company_name=cname,
                    location=job.location,
                    workplace_type=job.workplace_type.value,
                    employment_type=job.employment_type.value,
                    score=round(float(score), 4),
                    percent=round(float(score) * 100),
                    band=overall_band(float(score)),
                    summary=summary,
                    published_at=job.published_at,
                    application_deadline=job.application_deadline,
                )
                for score, summary, job, cname in rec_rows
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # admin dashboard
    # ----------------------------------------------------------------------------------------------------------------
    async def admin_dashboard(self, user: User) -> AdminDashboard:
        if user.role != Role.ADMIN:
            raise PermissionDeniedError("Platform reports are available to administrators only")
        return await self._cached(
            "admin-dashboard",
            _ALL_DOMAINS,
            {"scope": "platform"},
            self._admin_dashboard,
            AdminDashboard,
            ttl=ADMIN_TTL,
        )

    async def _admin_dashboard(self) -> AdminDashboard:
        s = self.session
        now = utcnow()

        async def grouped(col: Any, *where: Any) -> list[tuple[Any, int]]:
            stmt = select(col, func.count()).group_by(col)
            if where:
                stmt = stmt.where(*where)
            return [(k, int(n)) for k, n in (await s.execute(stmt)).all()]

        users_by_role = _fill(Role, await grouped(User.role))
        users_by_status = _fill(UserStatus, await grouped(User.status))
        companies = _fill(CompanyStatus, await grouped(Company.status))
        since = Window(now.date() - timedelta(days=29), now.date())
        signups = (
            await s.execute(
                select(_bucket_expr(User.created_at, "day").label("b"), func.count())
                .where(*since.conds(User.created_at))
                .group_by(literal_column("b"))
            )
        ).all()
        audit_rows = (
            await s.execute(
                select(AuditEvent, User.first_name, User.last_name)
                .outerjoin(User, User.id == AuditEvent.actor_id)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                .limit(10)
            )
        ).all()
        m_pairs, m_jobs, m_cands, m_last = (
            await s.execute(
                select(
                    func.count(),
                    func.count(func.distinct(Mt.job_id)),
                    func.count(func.distinct(Mt.candidate_id)),
                    func.max(Mt.generated_at),
                )
            )
        ).one()
        return AdminDashboard(
            generated_at=now,
            users_total=sum(users_by_role.values()),
            users_by_role=users_by_role,
            users_by_status=users_by_status,
            companies=CompanyTotals(
                total=sum(companies.values()), active=companies["ACTIVE"], suspended=companies["SUSPENDED"]
            ),
            jobs_by_status=_fill(JobStatus, await grouped(J.status)),
            applications_by_status=_fill(ApplicationStatus, await grouped(A.status)),
            interviews_by_status=_fill(InterviewStatus, await grouped(Iv.status)),
            resumes_by_status=_fill(ResumeStatus, await grouped(Resume.status)),
            tasks_last_24h_by_status=_fill(
                TaskStatus,
                await grouped(BackgroundTask.status, BackgroundTask.created_at >= now - timedelta(hours=24)),
            ),
            signups_over_time=_series([(b, int(n)) for b, n in signups], since, "day"),
            recent_audit_events=[
                AuditBrief(
                    id=ev.id,
                    action=ev.action,
                    entity_type=ev.entity_type,
                    entity_id=ev.entity_id,
                    actor_id=ev.actor_id,
                    actor_name=f"{fn} {ln}".strip() if fn else None,
                    company_id=ev.company_id,
                    created_at=ev.created_at,
                )
                for ev, fn, ln in audit_rows
            ],
            matches=MatchTotals(
                pairs=int(m_pairs),
                jobs_with_matches=int(m_jobs),
                candidates_with_matches=int(m_cands),
                last_generated_at=m_last,
            ),
        )

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: applications by job / by status / funnel
    # ----------------------------------------------------------------------------------------------------------------
    async def _abj_items(
        self,
        scope: Scope,
        window: Window,
        sort: str,
        order: SortOrder,
        page: int | None,
        page_size: int | None,
    ) -> tuple[list[ApplicationsByJobRow], int]:
        status_cols = {st: _cnt(A.status == st).label(f"n_{st.value.lower()}") for st in ApplicationStatus}
        n = func.count().label("n")
        sort_keys: dict[str, Any] = {
            "applications": n,
            "title": func.lower(J.title).collate("C"),
            "shortlisted": status_cols[ApplicationStatus.SHORTLISTED],
            "hired": status_cols[ApplicationStatus.HIRED],
            "rejected": status_cols[ApplicationStatus.REJECTED],
        }
        key = sort_keys.get(sort, n)
        stmt = (
            select(J.id, J.title, J.status, J.department, n, *status_cols.values())
            .select_from(J)
            .join(A, A.job_id == J.id)
            .where(*self._app_conds(scope, window))
            .group_by(J.id)
            .order_by(key.asc() if order == "asc" else key.desc(), J.title, J.id)
        )
        rows, total = await self._fetch(stmt, page, page_size)
        items = [
            ApplicationsByJobRow(
                job_id=r[0],
                title=r[1],
                job_status=r[2],
                department=r[3],
                applications=int(r[4]),
                by_status={st.value: int(r[5 + i]) for i, st in enumerate(ApplicationStatus)},
            )
            for r in rows
        ]
        return items, total

    async def applications_by_job(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
        page: int,
        page_size: int,
    ) -> ApplicationsByJobPage:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> ApplicationsByJobPage:
            items, total = await self._abj_items(scope, window, sort, order, page, page_size)
            return build_page(
                ApplicationsByJobPage,
                items,
                page=page,
                page_size=page_size,
                total=total,
                period=window.period(),
            )

        return await self._cached(
            "applications-by-job",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS),
            {
                **scope.cache_params(),
                **window.params(),
                "sort": sort,
                "order": order,
                "page": page,
                "size": page_size,
            },
            compute,
            ApplicationsByJobPage,
        )

    async def applications_by_job_table(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
    ) -> Table:
        scope = await self.resolve_scope(user, company_id)
        items, _ = await self._abj_items(scope, make_window(from_date, to_date), sort, order, None, None)
        return Table(
            "applications-by-job",
            [
                "job_id",
                "title",
                "job_status",
                "department",
                "applications",
                *[f"count_{st.value.lower()}" for st in ApplicationStatus],
            ],
            [
                [
                    i.job_id,
                    i.title,
                    i.job_status.value,
                    i.department,
                    i.applications,
                    *[i.by_status[st.value] for st in ApplicationStatus],
                ]
                for i in items
            ],
        )

    async def applications_by_status(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        job_id: uuid.UUID | None,
    ) -> ApplicationsByStatusOut:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> ApplicationsByStatusOut:
            items = await self._status_counts(scope, window, job_id)
            return ApplicationsByStatusOut(
                period=window.period(), job_id=job_id, total=sum(i.count for i in items), items=items
            )

        return await self._cached(
            "applications-by-status",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS),
            {**scope.cache_params(), **window.params(), "job": str(job_id) if job_id else None},
            compute,
            ApplicationsByStatusOut,
        )

    @staticmethod
    def applications_by_status_table(out: ApplicationsByStatusOut) -> Table:
        return Table(
            "applications-by-status",
            ["status", "count", "percent"],
            [[i.status.value, i.count, i.percent] for i in out.items],
        )

    async def funnel(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        job_id: uuid.UUID | None,
    ) -> FunnelOut:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> FunnelOut:
            applied, stages = await self._funnel(scope, window, job_id)
            return FunnelOut(period=window.period(), job_id=job_id, applications=applied, stages=stages)

        return await self._cached(
            "funnel",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS),
            {**scope.cache_params(), **window.params(), "job": str(job_id) if job_id else None},
            compute,
            FunnelOut,
        )

    @staticmethod
    def funnel_table(out: FunnelOut) -> Table:
        return Table(
            "funnel",
            ["stage", "kind", "count", "pct_of_applied", "pct_of_previous"],
            [
                [
                    s.stage.value,
                    "branch" if s.is_branch else "stage",
                    s.count,
                    s.pct_of_applied,
                    s.pct_of_previous,
                ]
                for s in out.stages
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: interview statistics
    # ----------------------------------------------------------------------------------------------------------------
    async def interview_statistics(
        self, user: User, *, company_id: uuid.UUID | None, from_date: date | None, to_date: date | None
    ) -> InterviewStatisticsOut:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> InterviewStatisticsOut:
            s = self.session
            conds = [*scope.job_conds(), *window.conds(Iv.start_at)]
            duration = func.avg(extract("epoch", Iv.end_at - Iv.start_at) / 60.0)
            row = (
                await s.execute(
                    select(func.count(), duration, *[_cnt(Iv.status == st) for st in InterviewStatus])
                    .select_from(Iv)
                    .join(A, A.id == Iv.application_id)
                    .join(J, J.id == A.job_id)
                    .where(*conds)
                )
            ).one()
            by_status = {st.value: int(row[2 + i]) for i, st in enumerate(InterviewStatus)}
            by_type = _fill(
                InterviewType,
                (
                    await s.execute(
                        select(Iv.interview_type, func.count())
                        .select_from(Iv)
                        .join(A, A.id == Iv.application_id)
                        .join(J, J.id == A.job_id)
                        .where(*conds)
                        .group_by(Iv.interview_type)
                    )
                ).all(),
            )
            fb = (
                await s.execute(
                    select(
                        func.count(InterviewFeedback.id),
                        func.count(func.distinct(InterviewFeedback.interview_id)),
                        func.avg(InterviewFeedback.rating),
                        *[_cnt(InterviewFeedback.recommendation == r) for r in HireRecommendation],
                    )
                    .select_from(InterviewFeedback)
                    .join(Iv, Iv.id == InterviewFeedback.interview_id)
                    .join(A, A.id == Iv.application_id)
                    .join(J, J.id == A.job_id)
                    .where(*conds)
                )
            ).one()
            total = int(row[0])
            held = by_status["COMPLETED"] + by_status["NO_SHOW"]
            return InterviewStatisticsOut(
                period=window.period(),
                total=total,
                by_status=by_status,
                by_type=by_type,
                avg_duration_minutes=_round(row[1], 1),
                held_or_missed=held,
                no_show_rate=_ratio(by_status["NO_SHOW"], held),
                cancellation_rate=_ratio(by_status["CANCELLED"], total),
                feedback=FeedbackStats(
                    entries=int(fb[0]),
                    interviews_with_feedback=int(fb[1]),
                    average_rating=_round(fb[2], 2),
                    recommendations={r.value: int(fb[3 + i]) for i, r in enumerate(HireRecommendation)},
                ),
            )

        return await self._cached(
            "interview-statistics",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.INTERVIEWS),
            {**scope.cache_params(), **window.params()},
            compute,
            InterviewStatisticsOut,
        )

    @staticmethod
    def interview_statistics_table(out: InterviewStatisticsOut) -> Table:
        rows: list[list[Any]] = [["interviews", "total", out.total]]
        rows += [["status", k, v] for k, v in out.by_status.items()]
        rows += [["type", k, v] for k, v in out.by_type.items()]
        rows += [
            ["metric", "avg_duration_minutes", out.avg_duration_minutes],
            ["metric", "no_show_rate", out.no_show_rate],
            ["metric", "cancellation_rate", out.cancellation_rate],
            ["feedback", "entries", out.feedback.entries],
            ["feedback", "average_rating", out.feedback.average_rating],
        ]
        rows += [["recommendation", k, v] for k, v in out.feedback.recommendations.items()]
        return Table("interview-statistics", ["section", "key", "value"], rows)

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: job performance
    # ----------------------------------------------------------------------------------------------------------------
    async def _perf_items(
        self,
        scope: Scope,
        window: Window,
        sort: str,
        order: SortOrder,
        page: int | None,
        page_size: int | None,
    ) -> tuple[list[JobPerformanceRow], int]:
        apps, hist = self._cohort(scope, window)
        agg = (
            select(
                J.id.label("job_id"),
                J.title.label("title"),
                J.status.label("job_status"),
                J.published_at.label("published_at"),
                func.count(apps.c.id).label("applications"),
                func.count(apps.c.id).filter(hist.c.shortlisted.is_(True)).label("reached_shortlist"),
                func.count(apps.c.id).filter(hist.c.hired_at.is_not(None)).label("hires"),
                func.avg(extract("epoch", hist.c.first_change_at - apps.c.applied_at) / 86400.0).label(
                    "d_first"
                ),
                func.avg(extract("epoch", hist.c.hired_at - apps.c.applied_at) / 86400.0).label("d_hire"),
                func.avg(Mt.overall_score).label("avg_score"),
                func.count(Mt.id).label("scored"),
            )
            .select_from(J)
            .join(apps, apps.c.job_id == J.id)
            .outerjoin(hist, hist.c.application_id == apps.c.id)
            .outerjoin(Mt, and_(Mt.job_id == apps.c.job_id, Mt.candidate_id == apps.c.candidate_id))
            .group_by(J.id)
            .subquery("perf")
        )
        sh_rate = cast(agg.c.reached_shortlist, Numeric) / func.nullif(agg.c.applications, 0)
        hire_rate = cast(agg.c.hires, Numeric) / func.nullif(agg.c.applications, 0)
        sort_keys: dict[str, Any] = {
            "applications": agg.c.applications,
            "title": func.lower(agg.c.title).collate("C"),
            "shortlist_rate": sh_rate,
            "hire_rate": hire_rate,
            "avg_days_to_hire": agg.c.d_hire,
            "avg_match_score": agg.c.avg_score,
        }
        key = sort_keys.get(sort, agg.c.applications)
        stmt = select(agg, sh_rate.label("sh_rate"), hire_rate.label("hire_rate")).order_by(
            (key.asc() if order == "asc" else key.desc()).nulls_last(), agg.c.title, agg.c.job_id
        )
        rows, total = await self._fetch(stmt, page, page_size)
        items = [
            JobPerformanceRow(
                job_id=r.job_id,
                title=r.title,
                job_status=r.job_status,
                published_at=r.published_at,
                applications=int(r.applications),
                reached_shortlist=int(r.reached_shortlist),
                hires=int(r.hires),
                shortlist_rate=_round(r.sh_rate, 4),
                hire_rate=_round(r.hire_rate, 4),
                avg_days_to_first_status_change=_round(r.d_first, 2),
                avg_days_to_hire=_round(r.d_hire, 2),
                avg_match_score=_round(r.avg_score, 4),
                applicants_scored=int(r.scored),
            )
            for r in rows
        ]
        return items, total

    async def job_performance(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
        page: int,
        page_size: int,
    ) -> JobPerformancePage:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> JobPerformancePage:
            items, total = await self._perf_items(scope, window, sort, order, page, page_size)
            return build_page(
                JobPerformancePage, items, page=page, page_size=page_size, total=total, period=window.period()
            )

        return await self._cached(
            "job-performance",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.MATCHES),
            {
                **scope.cache_params(),
                **window.params(),
                "sort": sort,
                "order": order,
                "page": page,
                "size": page_size,
            },
            compute,
            JobPerformancePage,
        )

    JOB_PERFORMANCE_HEADERS = (
        "job_id", "title", "job_status", "published_at", "applications", "reached_shortlist", "hires", "shortlist_rate", "hire_rate",
        "avg_days_to_first_status_change", "avg_days_to_hire", "avg_match_score", "applicants_scored",
    )  # fmt: skip

    async def job_performance_table(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
    ) -> Table:
        scope = await self.resolve_scope(user, company_id)
        items, _ = await self._perf_items(scope, make_window(from_date, to_date), sort, order, None, None)
        return Table(
            "job-performance",
            list(self.JOB_PERFORMANCE_HEADERS),
            [
                [
                    i.job_id,
                    i.title,
                    i.job_status.value,
                    i.published_at,
                    i.applications,
                    i.reached_shortlist,
                    i.hires,
                    i.shortlist_rate,
                    i.hire_rate,
                    i.avg_days_to_first_status_change,
                    i.avg_days_to_hire,
                    i.avg_match_score,
                    i.applicants_scored,
                ]
                for i in items
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: recruiter activity
    # ----------------------------------------------------------------------------------------------------------------
    async def _activity_items(
        self,
        scope: Scope,
        window: Window,
        sort: str,
        order: SortOrder,
        page: int | None,
        page_size: int | None,
    ) -> tuple[list[RecruiterActivityRow], int]:
        jc = scope.job_conds()
        company_audit = [AuditEvent.company_id == scope.company_id] if scope.company_id else []
        company_iv = [Iv.company_id == scope.company_id] if scope.company_id else []
        changes = (
            select(H.actor_id.label("uid"), func.count().label("n"))
            .select_from(H)
            .join(A, A.id == H.application_id)
            .join(J, J.id == A.job_id)
            .where(H.from_status.is_not(None), H.actor_id.is_not(None), *jc, *window.conds(H.created_at))
            .group_by(H.actor_id)
            .subquery("changes")
        )
        scheduled = (
            select(AuditEvent.actor_id.label("uid"), func.count().label("n"))
            .where(
                AuditEvent.action == "interview.scheduled",
                AuditEvent.actor_id.is_not(None),
                *company_audit,
                *window.conds(AuditEvent.created_at),
            )
            .group_by(AuditEvent.actor_id)
            .subquery("scheduled")
        )
        notes = (
            select(ApplicationNote.author_id.label("uid"), func.count().label("n"))
            .select_from(ApplicationNote)
            .join(A, A.id == ApplicationNote.application_id)
            .join(J, J.id == A.job_id)
            .where(ApplicationNote.author_id.is_not(None), *jc, *window.conds(ApplicationNote.created_at))
            .group_by(ApplicationNote.author_id)
            .subquery("notes")
        )
        feedback = (
            select(InterviewFeedback.author_id.label("uid"), func.count().label("n"))
            .select_from(InterviewFeedback)
            .join(Iv, Iv.id == InterviewFeedback.interview_id)
            .where(*company_iv, *window.conds(InterviewFeedback.submitted_at))
            .group_by(InterviewFeedback.author_id)
            .subquery("feedback")
        )
        n_changes = func.coalesce(changes.c.n, 0)
        n_sched = func.coalesce(scheduled.c.n, 0)
        n_notes = func.coalesce(notes.c.n, 0)
        n_fb = func.coalesce(feedback.c.n, 0)
        total = (n_changes + n_sched + n_notes + n_fb).label("total")
        staff_cond: list[ColumnElement[bool]] = [User.role.in_(tuple(STAFF_ROLES))]
        if scope.company_id:
            staff_cond.append(User.company_id == scope.company_id)
        full_name = func.lower(User.first_name + " " + User.last_name)
        sort_keys: dict[str, Any] = {
            "total": total,
            "status_changes": n_changes,
            "interviews_scheduled": n_sched,
            "notes": n_notes,
            "feedback": n_fb,
            "name": full_name,
        }
        key = sort_keys.get(sort, total)
        stmt = (
            select(
                User.id, User.first_name, User.last_name, User.role, Company.id, Company.name,
                n_changes.label("n_changes"), n_sched.label("n_sched"), n_notes.label("n_notes"), n_fb.label("n_fb"), total,
            )
            .select_from(User)
            .join(Company, Company.id == User.company_id)
            .outerjoin(changes, changes.c.uid == User.id)
            .outerjoin(scheduled, scheduled.c.uid == User.id)
            .outerjoin(notes, notes.c.uid == User.id)
            .outerjoin(feedback, feedback.c.uid == User.id)
            .where(*staff_cond)
            .order_by(key.asc() if order == "asc" else key.desc(), full_name, User.id)
        )  # fmt: skip
        rows, count = await self._fetch(stmt, page, page_size)
        items = [
            RecruiterActivityRow(
                user_id=r[0],
                name=f"{r[1]} {r[2]}".strip(),
                role=r[3].value,
                company_id=r[4],
                company_name=r[5],
                status_changes=int(r[6]),
                interviews_scheduled=int(r[7]),
                notes_added=int(r[8]),
                feedback_submitted=int(r[9]),
                total_actions=int(r[10]),
            )
            for r in rows
        ]
        return items, count

    async def recruiter_activity(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
        page: int,
        page_size: int,
    ) -> RecruiterActivityPage:
        scope = await self.resolve_scope(user, company_id, allow_hiring_manager=False)
        window = make_window(from_date, to_date)

        async def compute() -> RecruiterActivityPage:
            items, total = await self._activity_items(scope, window, sort, order, page, page_size)
            return build_page(
                RecruiterActivityPage,
                items,
                page=page,
                page_size=page_size,
                total=total,
                period=window.period(),
            )

        return await self._cached(
            "recruiter-activity",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.INTERVIEWS, CacheDomain.USERS),
            {
                **scope.cache_params(),
                **window.params(),
                "sort": sort,
                "order": order,
                "page": page,
                "size": page_size,
            },
            compute,
            RecruiterActivityPage,
            ttl=ACTIVITY_TTL,
        )

    async def recruiter_activity_table(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
    ) -> Table:
        scope = await self.resolve_scope(user, company_id, allow_hiring_manager=False)
        items, _ = await self._activity_items(scope, make_window(from_date, to_date), sort, order, None, None)
        return Table(
            "recruiter-activity",
            [
                "user_id",
                "name",
                "role",
                "company",
                "status_changes",
                "interviews_scheduled",
                "notes_added",
                "feedback_submitted",
                "total_actions",
            ],
            [
                [
                    i.user_id,
                    i.name,
                    i.role,
                    i.company_name,
                    i.status_changes,
                    i.interviews_scheduled,
                    i.notes_added,
                    i.feedback_submitted,
                    i.total_actions,
                ]
                for i in items
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: source statistics
    # ----------------------------------------------------------------------------------------------------------------
    async def _source_items(
        self,
        scope: Scope,
        window: Window,
        sort: str,
        order: SortOrder,
        page: int | None,
        page_size: int | None,
    ) -> tuple[list[SourceStatRow], int]:
        apps, hist = self._cohort(scope, window)
        n = func.count(apps.c.id).label("n")
        grand = func.sum(func.count(apps.c.id)).over().label("grand")
        shortlisted = func.count(apps.c.id).filter(hist.c.shortlisted.is_(True)).label("shortlisted")
        hires = func.count(apps.c.id).filter(hist.c.hired_at.is_not(None)).label("hires")
        sort_keys: dict[str, Any] = {
            "applications": n,
            "source": apps.c.source,
            "hires": hires,
            "shortlisted": shortlisted,
        }
        key = sort_keys.get(sort, n)
        stmt = (
            select(apps.c.source, n, grand, shortlisted, hires)
            .select_from(apps)
            .outerjoin(hist, hist.c.application_id == apps.c.id)
            .group_by(apps.c.source)
            .order_by(key.asc() if order == "asc" else key.desc(), apps.c.source)
        )
        rows, total = await self._fetch(stmt, page, page_size)
        items = [
            SourceStatRow(
                source=r[0],
                applications=int(r[1]),
                share=round(int(r[1]) / int(r[2]), 4) if r[2] else 0.0,
                reached_shortlist=int(r[3]),
                hires=int(r[4]),
                shortlist_rate=_ratio(int(r[3]), int(r[1])),
                hire_rate=_ratio(int(r[4]), int(r[1])),
            )
            for r in rows
        ]
        return items, total

    async def source_statistics(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
        page: int,
        page_size: int,
    ) -> SourceStatisticsPage:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> SourceStatisticsPage:
            items, total = await self._source_items(scope, window, sort, order, page, page_size)
            return build_page(
                SourceStatisticsPage,
                items,
                page=page,
                page_size=page_size,
                total=total,
                period=window.period(),
            )

        return await self._cached(
            "source-statistics",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS),
            {
                **scope.cache_params(),
                **window.params(),
                "sort": sort,
                "order": order,
                "page": page,
                "size": page_size,
            },
            compute,
            SourceStatisticsPage,
        )

    async def source_statistics_table(
        self,
        user: User,
        *,
        company_id: uuid.UUID | None,
        from_date: date | None,
        to_date: date | None,
        sort: str,
        order: SortOrder,
    ) -> Table:
        scope = await self.resolve_scope(user, company_id)
        items, _ = await self._source_items(scope, make_window(from_date, to_date), sort, order, None, None)
        return Table(
            "source-statistics",
            ["source", "applications", "share", "reached_shortlist", "hires", "shortlist_rate", "hire_rate"],
            [
                [
                    i.source,
                    i.applications,
                    i.share,
                    i.reached_shortlist,
                    i.hires,
                    i.shortlist_rate,
                    i.hire_rate,
                ]
                for i in items
            ],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: matching performance (only what the stored data supports)
    # ----------------------------------------------------------------------------------------------------------------
    async def matching_performance(
        self, user: User, *, company_id: uuid.UUID | None, from_date: date | None, to_date: date | None
    ) -> MatchingPerformanceOut:
        scope = await self.resolve_scope(user, company_id)
        window = make_window(from_date, to_date)

        async def compute() -> MatchingPerformanceOut:
            s = self.session
            jc = scope.job_conds()
            band = band_case(Mt.overall_score)

            def bands(rows: Sequence[tuple[str, int]]) -> list[BandCount]:
                have = {b: int(n) for b, n in rows}
                total = sum(have.values())
                return [
                    BandCount(band=b, count=have.get(b, 0), percent=_pct(have.get(b, 0), total))
                    for b in BAND_ORDER
                ]

            all_rows = (
                await s.execute(
                    select(band, func.count())
                    .select_from(Mt)
                    .join(J, J.id == Mt.job_id)
                    .where(*jc)
                    .group_by(band)
                )
            ).all()
            app_join = and_(Mt.job_id == A.job_id, Mt.candidate_id == A.candidate_id)
            app_conds = self._app_conds(scope, window)
            app_rows = (
                await s.execute(
                    select(band, func.count())
                    .select_from(A)
                    .join(J, J.id == A.job_id)
                    .join(Mt, app_join)
                    .where(*app_conds)
                    .group_by(band)
                )
            ).all()
            outcome = case(
                (A.status == ApplicationStatus.HIRED, "HIRED"),
                (A.status == ApplicationStatus.REJECTED, "REJECTED"),
                (A.status == ApplicationStatus.WITHDRAWN, "WITHDRAWN"),
                else_="IN_PROGRESS",
            )
            out_rows = (
                await s.execute(
                    select(outcome, func.count(), func.avg(Mt.overall_score))
                    .select_from(A)
                    .join(J, J.id == A.job_id)
                    .join(Mt, app_join)
                    .where(*app_conds)
                    .group_by(outcome)
                )
            ).all()
            by_outcome = {o: (int(n), _round(avg, 4)) for o, n, avg in out_rows}
            ranked = (
                select(
                    Mt.job_id.label("job_id"),
                    Mt.candidate_id.label("candidate_id"),
                    func.rank().over(partition_by=Mt.job_id, order_by=Mt.overall_score.desc()).label("rk"),
                )
                .select_from(Mt)
                .join(J, J.id == Mt.job_id)
                .where(*jc)
                .cte("ranked_matches")
            )
            top = (
                await s.execute(
                    select(
                        func.count(A.id),
                        func.count(ranked.c.job_id),
                        func.count(A.id).filter(ranked.c.rk <= 10),
                    )
                    .select_from(A)
                    .join(J, J.id == A.job_id)
                    .outerjoin(
                        ranked, and_(ranked.c.job_id == A.job_id, ranked.c.candidate_id == A.candidate_id)
                    )
                    .where(*app_conds)
                )
            ).one()
            scored_pairs = sum(n for _, n in all_rows)

            outcomes = [
                OutcomeScore(
                    outcome=o,
                    applications=by_outcome.get(o, (0, None))[0],
                    avg_score=by_outcome.get(o, (0, None))[1],
                )
                for o in ("HIRED", "REJECTED", "WITHDRAWN", "IN_PROGRESS")
            ]
            hired, rejected = by_outcome.get("HIRED", (0, None)), by_outcome.get("REJECTED", (0, None))
            delta = (
                round(hired[1] - rejected[1], 4) if hired[1] is not None and rejected[1] is not None else None
            )
            notes = [
                "Scores rank candidates against a job; they are a relevance aid, not a prediction of hiring success."
            ]
            if scored_pairs == 0:
                notes.append("No match scores have been computed yet for these jobs.")
            if delta is not None and (hired[0] < 10 or rejected[0] < 10):
                notes.append(
                    f"The hired-vs-rejected comparison rests on {hired[0]} hired and {rejected[0]} rejected scored applicants; "
                    "samples this small say little."
                )
            elif delta is None and (hired[0] or rejected[0]):
                notes.append("Hired-vs-rejected needs scored applicants in both groups.")
            if int(top[0]) > int(top[1]):
                notes.append(
                    f"{int(top[0]) - int(top[1])} of {int(top[0])} applicants have no stored match score yet."
                )
            return MatchingPerformanceOut(
                period=window.period(),
                scored_pairs=scored_pairs,
                all_scored_distribution=bands([(b, int(n)) for b, n in all_rows]),
                applicant_distribution=bands([(b, int(n)) for b, n in app_rows]),
                avg_score_by_outcome=outcomes,
                hired_minus_rejected=delta,
                top10=TopTenStats(
                    applicants=int(top[0]),
                    applicants_with_score=int(top[1]),
                    applicants_in_top10=int(top[2]),
                    pct_in_top10=_pct(int(top[2]), int(top[1])) if top[1] else None,
                ),
                notes=notes,
            )

        return await self._cached(
            "matching-performance",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.MATCHES),
            {**scope.cache_params(), **window.params()},
            compute,
            MatchingPerformanceOut,
        )

    @staticmethod
    def matching_performance_table(out: MatchingPerformanceOut) -> Table:
        rows: list[list[Any]] = [
            ["all_scored_band", b.band, b.count, b.percent] for b in out.all_scored_distribution
        ]
        rows += [["applicant_band", b.band, b.count, b.percent] for b in out.applicant_distribution]
        rows += [
            ["avg_score_by_outcome", o.outcome, o.applications, o.avg_score] for o in out.avg_score_by_outcome
        ]
        rows += [
            ["top10", "applicants", out.top10.applicants, None],
            ["top10", "applicants_with_score", out.top10.applicants_with_score, None],
            ["top10", "applicants_in_top10", out.top10.applicants_in_top10, out.top10.pct_in_top10],
        ]
        return Table("matching-performance", ["section", "key", "count", "value"], rows)

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: top skills
    # ----------------------------------------------------------------------------------------------------------------
    async def top_skills(self, user: User, *, company_id: uuid.UUID | None, limit: int) -> TopSkillsOut:
        scope = await self.resolve_scope(user, company_id)

        async def compute() -> TopSkillsOut:
            s = self.session
            jc = scope.job_conds()
            live_jobs = [J.status == JobStatus.PUBLISHED, *jc]
            demand = (
                await s.execute(
                    select(
                        Skill.id,
                        Skill.name,
                        func.count(func.distinct(JobSkill.job_id)).label("jobs"),
                        _cnt(JobSkill.requirement == SkillRequirement.REQUIRED),
                        _cnt(JobSkill.requirement == SkillRequirement.PREFERRED),
                    )
                    .select_from(JobSkill)
                    .join(Skill, Skill.id == JobSkill.skill_id)
                    .join(J, J.id == JobSkill.job_id)
                    .where(*live_jobs)
                    .group_by(Skill.id)
                    .order_by(desc("jobs"), Skill.name, Skill.id)
                    .limit(limit)
                )
            ).all()
            applicants = (
                select(A.candidate_id)
                .join(J, J.id == A.job_id)
                .where(A.status != ApplicationStatus.WITHDRAWN, *jc)
                .distinct()
                .subquery("applicants")
            )
            supply = (
                await s.execute(
                    select(
                        Skill.id,
                        Skill.name,
                        func.count(func.distinct(CandidateSkill.candidate_id)).label("n"),
                    )
                    .select_from(CandidateSkill)
                    .join(Skill, Skill.id == CandidateSkill.skill_id)
                    .join(applicants, applicants.c.candidate_id == CandidateSkill.candidate_id)
                    .where(CandidateSkill.status == SkillStatus.CONFIRMED)
                    .group_by(Skill.id)
                    .order_by(desc("n"), Skill.name, Skill.id)
                    .limit(limit)
                )
            ).all()
            n_jobs = await s.scalar(select(func.count()).select_from(J).where(*live_jobs))
            n_apps = await s.scalar(select(func.count()).select_from(applicants))
            return TopSkillsOut(
                scope=scope.kind,
                jobs_considered=int(n_jobs or 0),
                applicants_considered=int(n_apps or 0),
                requested=[
                    SkillDemand(
                        skill_id=sid,
                        skill=name,
                        jobs=int(n),
                        required_in_jobs=int(req),
                        preferred_in_jobs=int(pref),
                    )
                    for sid, name, n, req, pref in demand
                ],
                available=[
                    SkillSupply(skill_id=sid, skill=name, candidates=int(n)) for sid, name, n in supply
                ],
            )

        return await self._cached(
            "top-skills",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS, CacheDomain.CANDIDATES, CacheDomain.SKILLS),
            {**scope.cache_params(), "limit": limit},
            compute,
            TopSkillsOut,
        )

    @staticmethod
    def top_skills_table(out: TopSkillsOut) -> Table:
        rows: list[list[Any]] = [
            ["requested", d.skill, d.jobs, d.required_in_jobs, d.preferred_in_jobs] for d in out.requested
        ]
        rows += [["available", a.skill, a.candidates, None, None] for a in out.available]
        return Table("top-skills", ["list", "skill", "count", "required_in_jobs", "preferred_in_jobs"], rows)

    # ----------------------------------------------------------------------------------------------------------------
    # analytics: pipeline summary (a snapshot of the current state)
    # ----------------------------------------------------------------------------------------------------------------
    async def pipeline_summary(
        self, user: User, *, company_id: uuid.UUID | None, job_id: uuid.UUID | None
    ) -> PipelineSummaryOut:
        scope = await self.resolve_scope(user, company_id)

        async def compute() -> PipelineSummaryOut:
            age_days = extract("epoch", func.now() - A.status_changed_at) / 86400.0
            conds = scope.job_conds()
            if job_id:
                conds.append(A.job_id == job_id)
            rows = (
                await self.session.execute(
                    select(
                        A.status,
                        func.count(),
                        func.avg(age_days),
                        func.max(age_days),
                        _cnt(age_days > STALE_AFTER_DAYS),
                    )
                    .select_from(A)
                    .join(J, J.id == A.job_id)
                    .where(*conds)
                    .group_by(A.status)
                )
            ).all()
            have = {st: (int(n), avg, mx, int(stale)) for st, n, avg, mx, stale in rows}
            stages: list[PipelineStageRow] = []
            for st in ApplicationStatus:
                n, avg, mx, stale = have.get(st, (0, None, None, 0))
                live = st in _LIVE
                stages.append(
                    PipelineStageRow(
                        stage=st,
                        count=n,
                        avg_days_in_stage=_round(avg, 1) if live else None,
                        max_days_in_stage=_round(mx, 1) if live else None,
                        stale=stale if live else 0,
                    )
                )
            total = sum(r.count for r in stages)
            live_total = sum(r.count for r in stages if r.stage in _LIVE)
            return PipelineSummaryOut(
                job_id=job_id,
                stale_after_days=STALE_AFTER_DAYS,
                total=total,
                live=live_total,
                closed=total - live_total,
                stale=sum(r.stale for r in stages),
                stages=stages,
            )

        return await self._cached(
            "pipeline-summary",
            (CacheDomain.JOBS, CacheDomain.APPLICATIONS),
            {**scope.cache_params(), "job": str(job_id) if job_id else None},
            compute,
            PipelineSummaryOut,
            ttl=30,
        )

    @staticmethod
    def pipeline_summary_table(out: PipelineSummaryOut) -> Table:
        return Table(
            "pipeline-summary",
            ["stage", "count", "avg_days_in_stage", "max_days_in_stage", "stale"],
            [[r.stage.value, r.count, r.avg_days_in_stage, r.max_days_in_stage, r.stale] for r in out.stages],
        )
