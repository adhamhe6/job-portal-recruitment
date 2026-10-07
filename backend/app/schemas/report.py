"""Reporting & dashboard schemas. Every number is produced by SQL aggregates over real rows."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import ApplicationStatus, InterviewStatus, JobStatus
from app.schemas.common import Page


class Period(BaseModel):
    """The effective, inclusive date window of a report (``null`` = unbounded)."""

    from_date: date | None = None
    to_date: date | None = None
    granularity: Literal["day", "week", "month"] | None = Field(
        default=None, description="Bucket size of time series in this report"
    )


class StatusCount(BaseModel):
    status: ApplicationStatus
    count: int
    percent: float = Field(description="Share of the total, 0-100 (one decimal)")


class FunnelStage(BaseModel):
    stage: ApplicationStatus
    count: int = Field(
        description="Applications that ever reached this stage (derived from application_status_history, not the current status). "
        "For the REJECTED / WITHDRAWN branches: applications currently in that terminal state."
    )
    pct_of_applied: float | None = Field(description="Share of all applications, 0-100")
    pct_of_previous: float | None = Field(description="Conversion from the previous main-line stage, 0-100 (null for branches)")
    is_branch: bool = False


class SeriesPoint(BaseModel):
    bucket: date = Field(description="First day of the bucket (UTC)")
    count: int


class JobCount(BaseModel):
    job_id: uuid.UUID
    title: str
    job_status: JobStatus
    applications: int


class InterviewActivityPoint(BaseModel):
    bucket: date
    scheduled: int = 0
    confirmed: int = 0
    rescheduled: int = 0
    completed: int = 0
    cancelled: int = 0
    no_show: int = 0
    total: int = 0


class TopMatch(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    headline: str | None
    job_id: uuid.UUID
    job_title: str
    score: float = Field(description="0..1 ranking score (not a hiring probability)")
    band: str
    application_id: uuid.UUID | None = Field(description="Set when the candidate already applied to that job")


class RecentApplication(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    job_id: uuid.UUID
    job_title: str
    status: ApplicationStatus
    applied_at: datetime
    match_score: float | None
    match_band: str | None


class RecruiterKpis(BaseModel):
    active_jobs: int = Field(description="PUBLISHED jobs now")
    total_applications: int = Field(description="Applications received in the period")
    applications_in_screening: int = Field(description="Applications currently in SCREENING (snapshot)")
    shortlisted: int = Field(description="Applications currently SHORTLISTED (snapshot)")
    upcoming_interviews: int = Field(description="Active interviews starting within the next 7 days")
    jobs_nearing_deadline: int = Field(description="PUBLISHED jobs whose deadline is within the next 7 days")
    avg_applications_per_job: float = Field(
        description="Applications received in the period / jobs that were advertised (PUBLISHED, PAUSED or CLOSED); 0 when none"
    )
    hires_in_period: int = Field(description="Applications moved to HIRED within the period")


class RecruiterDashboard(BaseModel):
    scope: Literal["company", "assigned_jobs", "platform"] = Field(
        description="company = recruiter view; assigned_jobs = hiring-manager view restricted to jobs assigned to them"
    )
    company_id: uuid.UUID | None
    period: Period
    generated_at: datetime
    kpis: RecruiterKpis
    funnel: list[FunnelStage]
    applications_over_time: list[SeriesPoint]
    applications_by_job: list[JobCount]
    status_distribution: list[StatusCount]
    interview_activity: list[InterviewActivityPoint]
    top_matching_candidates: list[TopMatch]
    recent_applications: list[RecentApplication]


# --- candidate dashboard ---------------------------------------------------------------------------------------


class ProfileCompletionBrief(BaseModel):
    percent: int
    missing: list[str]


class UpcomingInterview(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    interview_type: str
    start_at: datetime
    end_at: datetime
    timezone: str
    status: InterviewStatus
    location: str | None
    meeting_url: str | None


class RecommendedJobBrief(BaseModel):
    job_id: uuid.UUID
    title: str
    company_name: str
    location: str | None
    workplace_type: str
    employment_type: str
    score: float
    percent: int
    band: str
    summary: str | None
    published_at: datetime | None
    application_deadline: date | None


class ResumeStatusBrief(BaseModel):
    has_resume: bool
    resume_id: uuid.UUID | None = None
    filename: str | None = None
    status: str | None = Field(default=None, description="UPLOADED | PROCESSING | PROCESSED | FAILED")
    processing_status: str | None = Field(default=None, description="PROCESSING | COMPLETED | FAILED (from the worker result)")
    error_code: str | None = None
    uploaded_at: datetime | None = None


class CandidateDashboard(BaseModel):
    generated_at: datetime
    profile_completion: ProfileCompletionBrief
    total_applications: int
    active_applications: int = Field(description="Applications not yet HIRED, REJECTED or WITHDRAWN")
    applications_by_status: list[StatusCount]
    upcoming_interviews: list[UpcomingInterview]
    recommended_jobs: list[RecommendedJobBrief]
    resume: ResumeStatusBrief
    saved_jobs: int
    unread_notifications: int


# --- admin dashboard -------------------------------------------------------------------------------------------


class AuditBrief(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    company_id: uuid.UUID | None
    created_at: datetime


class MatchTotals(BaseModel):
    pairs: int
    jobs_with_matches: int
    candidates_with_matches: int
    last_generated_at: datetime | None


class CompanyTotals(BaseModel):
    total: int
    active: int
    suspended: int


class AdminDashboard(BaseModel):
    generated_at: datetime
    users_total: int
    users_by_role: dict[str, int]
    users_by_status: dict[str, int]
    companies: CompanyTotals
    jobs_by_status: dict[str, int]
    applications_by_status: dict[str, int]
    interviews_by_status: dict[str, int]
    resumes_by_status: dict[str, int]
    tasks_last_24h_by_status: dict[str, int]
    signups_over_time: list[SeriesPoint] = Field(description="New users per day, last 30 days")
    recent_audit_events: list[AuditBrief]
    matches: MatchTotals


# --- analytics -------------------------------------------------------------------------------------------------


class ApplicationsByJobRow(BaseModel):
    job_id: uuid.UUID
    title: str
    job_status: JobStatus
    department: str | None
    applications: int
    by_status: dict[str, int]


class ApplicationsByJobPage(Page[ApplicationsByJobRow]):
    period: Period


class ApplicationsByStatusOut(BaseModel):
    period: Period
    job_id: uuid.UUID | None
    total: int
    items: list[StatusCount]


class FunnelOut(BaseModel):
    period: Period
    job_id: uuid.UUID | None
    applications: int
    stages: list[FunnelStage]


class FeedbackStats(BaseModel):
    entries: int
    interviews_with_feedback: int
    average_rating: float | None
    recommendations: dict[str, int]


class InterviewStatisticsOut(BaseModel):
    period: Period
    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    avg_duration_minutes: float | None
    held_or_missed: int = Field(description="COMPLETED + NO_SHOW: the denominator of the no-show rate")
    no_show_rate: float | None = Field(description="NO_SHOW / (COMPLETED + NO_SHOW), 0..1")
    cancellation_rate: float | None = Field(description="CANCELLED / all interviews, 0..1")
    feedback: FeedbackStats


class JobPerformanceRow(BaseModel):
    job_id: uuid.UUID
    title: str
    job_status: JobStatus
    published_at: datetime | None
    applications: int
    reached_shortlist: int = Field(description="Applications that reached SHORTLISTED or later")
    hires: int
    shortlist_rate: float | None = Field(description="reached_shortlist / applications, 0..1")
    hire_rate: float | None = Field(description="hires / applications, 0..1")
    avg_days_to_first_status_change: float | None
    avg_days_to_hire: float | None
    avg_match_score: float | None = Field(description="Mean overall match score of applicants that have a stored score")
    applicants_scored: int


class JobPerformancePage(Page[JobPerformanceRow]):
    period: Period
    note: str = "Job views are not tracked; performance starts at the application."


class RecruiterActivityRow(BaseModel):
    user_id: uuid.UUID
    name: str
    role: str
    company_id: uuid.UUID
    company_name: str
    status_changes: int = Field(description="Application stage changes made (status history)")
    interviews_scheduled: int = Field(description="From audit events")
    notes_added: int
    feedback_submitted: int
    total_actions: int


class RecruiterActivityPage(Page[RecruiterActivityRow]):
    period: Period


class SourceStatRow(BaseModel):
    source: str
    applications: int
    share: float = Field(description="Share of all applications, 0..1")
    reached_shortlist: int
    hires: int
    shortlist_rate: float | None
    hire_rate: float | None


class SourceStatisticsPage(Page[SourceStatRow]):
    period: Period


class BandCount(BaseModel):
    band: str
    count: int
    percent: float


class OutcomeScore(BaseModel):
    outcome: Literal["HIRED", "REJECTED", "WITHDRAWN", "IN_PROGRESS"]
    applications: int = Field(description="Applications of that outcome that have a stored match score")
    avg_score: float | None


class TopTenStats(BaseModel):
    applicants: int
    applicants_with_score: int
    applicants_in_top10: int = Field(description="Applicants ranked in the 10 best scores of their job's scored candidates")
    pct_in_top10: float | None = Field(description="applicants_in_top10 / applicants_with_score, 0-100")


class MatchingPerformanceOut(BaseModel):
    period: Period
    scored_pairs: int
    all_scored_distribution: list[BandCount] = Field(description="Every scored candidate of the in-scope jobs (not period-filtered)")
    applicant_distribution: list[BandCount] = Field(description="Applicants (applied in the period) that have a stored score")
    avg_score_by_outcome: list[OutcomeScore]
    hired_minus_rejected: float | None = Field(description="avg(HIRED) - avg(REJECTED) when both groups have scores")
    top10: TopTenStats
    notes: list[str] = Field(description="Data-driven caveats (e.g. small samples). The score is a ranking aid, not a hiring decision.")


class SkillDemand(BaseModel):
    skill_id: uuid.UUID
    skill: str
    jobs: int = Field(description="Published jobs listing the skill")
    required_in_jobs: int
    preferred_in_jobs: int


class SkillSupply(BaseModel):
    skill_id: uuid.UUID
    skill: str
    candidates: int = Field(description="Distinct applicants with the skill (confirmed)")


class TopSkillsOut(BaseModel):
    scope: Literal["company", "assigned_jobs", "platform"]
    jobs_considered: int
    applicants_considered: int
    requested: list[SkillDemand]
    available: list[SkillSupply]


class PipelineStageRow(BaseModel):
    stage: ApplicationStatus
    count: int
    avg_days_in_stage: float | None = Field(description="Mean days since the last status change (live stages only)")
    max_days_in_stage: float | None
    stale: int = Field(description="Live applications unchanged for more than `stale_after_days`")


class PipelineSummaryOut(BaseModel):
    job_id: uuid.UUID | None
    stale_after_days: int
    total: int
    live: int
    closed: int
    stale: int
    stages: list[PipelineStageRow]
