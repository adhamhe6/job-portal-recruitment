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
        return {"from": self.start.isoformat() if self.start else None, "to": self.end.isoformat() if self.end else None}

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
        raise ValidationFailure(f"The date range may span at most {MAX_RANGE_DAYS} days", code="DATE_RANGE_TOO_LARGE")
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
    unit = {"day": literal_column("'day'"), "week": literal_column("'week'"), "month": literal_column("'month'")}[gran]
    return cast(func.date_trunc(unit, func.timezone("UTC", col)), Date)


def _series(rows: Sequence[tuple[date, int]], window: Window, gran: Granularity) -> list[SeriesPoint]:
    assert window.start is not None
    assert window.end is not None
    have = {d: int(n) for d, n in rows}
    return [SeriesPoint(bucket=b, count=have.get(b, 0)) for b in bucket_starts(window.start, window.end, gran)]


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
    async def resolve_scope(self, user: User, company_id: uuid.UUID | None = None, *, allow_hiring_manager: bool = True) -> Scope:
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
    def _app_conds(scope: Scope, window: Window, job_id: uuid.UUID | None = None) -> list[ColumnElement[bool]]:
        conds = scope.job_conds()
        conds += window.conds(A.applied_at)
        if job_id:
            conds.append(A.job_id == job_id)
        return conds

    async def _status_counts(self, scope: Scope, window: Window, job_id: uuid.UUID | None = None) -> list[StatusCount]:
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
            StatusCount(status=st, count=have.get(st, 0), percent=_pct(have.get(st, 0), total)) for st in ApplicationStatus
        ]

    async def _funnel(self, scope: Scope, window: Window, job_id: uuid.UUID | None = None) -> tuple[int, list[FunnelStage]]:
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
            stages.append(FunnelStage(stage=st, count=n, pct_of_applied=_pct(n, applied) if applied else None, pct_of_previous=None, is_branch=True))
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

    async def _recruiter_dashboard(self, scope: Scope, window: Window, gran: Granularity) -> RecruiterDashboard:
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
            .where(*jc, Iv.status.in_(ACTIVE_INTERVIEW_STATUSES), Iv.start_at >= now, Iv.start_at < now + timedelta(days=7))
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
        activity = {b: InterviewActivityPoint(bucket=b) for b in bucket_starts(window.start, window.end, gran)}
        for b, st, n in act_rows:
            if b in activity:
                setattr(activity[b], st.value.lower(), int(n))
                activity[b].total += int(n)

        jx = aliased(Job)  # an alias keeps visibility_predicate's own Job subquery uncorrelated from this one
        top_rows = (
            await s.execute(
                select(Mt.overall_score, CandidateProfile.id, CandidateProfile.display_name, CandidateProfile.headline, jx.id, jx.title, A.id)
                .select_from(Mt)
                .join(jx, jx.id == Mt.job_id)
                .join(CandidateProfile, CandidateProfile.id == Mt.candidate_id)
                .outerjoin(A, and_(A.job_id == Mt.job_id, A.candidate_id == Mt.candidate_id, A.status != ApplicationStatus.WITHDRAWN))
                .where(jx.status == JobStatus.PUBLISHED, *scope.job_conds(jx), visibility_predicate(scope.user))
                .order_by(Mt.overall_score.desc(), CandidateProfile.id)
                .limit(5)
            )
        ).all()

        recent_rows = (
            await s.execute(
                select(A.id, CandidateProfile.id, CandidateProfile.display_name, J.id, J.title, A.status, A.applied_at, Mt.overall_score)
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
            applications_by_job=[JobCount(job_id=jid, title=t, job_status=st, applications=int(n)) for jid, t, st, n in by_job_rows],
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
        cand = (await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))).scalar_one_or_none()
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
        saved = await self.session.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.candidate_id == candidate_id))
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
                .order_by(Resume.is_primary.desc(), Resume.created_at.desc(), ResumeDocument.created_at.desc().nulls_last())
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
                await s.execute(select(A.status, func.count()).where(A.candidate_id == candidate_id).group_by(A.status))
            ).all()
        }
        total = sum(counts.values())
        live = sum(n for st, n in counts.items() if st in _LIVE)
        by_status = [StatusCount(status=st, count=counts.get(st, 0), percent=_pct(counts.get(st, 0), total)) for st in ApplicationStatus]

        iv_rows = (
            await s.execute(
                select(Iv, J.id, J.title, Company.name)
                .select_from(Iv)
                .join(A, A.id == Iv.application_id)
                .join(J, J.id == A.job_id)
                .join(Company, Company.id == J.company_id)
                .where(Iv.candidate_id == candidate_id, Iv.status.in_(ACTIVE_INTERVIEW_STATUSES), Iv.end_at >= now)
                .order_by(Iv.start_at, Iv.id)
                .limit(5)
            )
        ).all()

        applied = select(A.job_id).where(A.candidate_id == candidate_id, A.status != ApplicationStatus.WITHDRAWN)
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
            "admin-dashboard", _ALL_DOMAINS, {"scope": "platform"}, self._admin_dashboard, AdminDashboard, ttl=ADMIN_TTL
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
            companies=CompanyTotals(total=sum(companies.values()), active=companies["ACTIVE"], suspended=companies["SUSPENDED"]),
            jobs_by_status=_fill(JobStatus, await grouped(J.status)),
            applications_by_status=_fill(ApplicationStatus, await grouped(A.status)),
            interviews_by_status=_fill(InterviewStatus, await grouped(Iv.status)),
            resumes_by_status=_fill(ResumeStatus, await grouped(Resume.status)),
            tasks_last_24h_by_status=_fill(
                TaskStatus, await grouped(BackgroundTask.status, BackgroundTask.created_at >= now - timedelta(hours=24))
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
            matches=MatchTotals(pairs=int(m_pairs), jobs_with_matches=int(m_jobs), candidates_with_matches=int(m_cands), last_generated_at=m_last),
        )
