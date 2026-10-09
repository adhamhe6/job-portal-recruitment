"""Applications: submission, the stage workflow with an audit trail, withdrawal and internal notes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import (
    BusinessRuleError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import Role
from app.db.models import (
    ACTIVE_INTERVIEW_STATUSES,
    Application,
    ApplicationNote,
    ApplicationStatus,
    ApplicationStatusHistory,
    CandidateJobMatch,
    CandidateProfile,
    Company,
    CompanyStatus,
    Interview,
    Job,
    NotificationType,
    Resume,
    ResumeDocument,
    User,
)
from app.matching.scoring import overall_band
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationListItem,
    HistoryEntry,
    NoteOut,
)
from app.services.access import is_admin, is_staff, load_application_for_user
from app.services.common import escape_like, paginate, record_audit, utcnow
from app.services.jobs import is_open_for_applications
from app.services.notifications import NotificationService
from app.services.scheduling import schedule_job_match
from app.services.tasks import Dispatcher

logger = logging.getLogger(__name__)

A = ApplicationStatus
TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    A.APPLIED: frozenset({A.SCREENING, A.REJECTED, A.WITHDRAWN}),
    A.SCREENING: frozenset({A.SHORTLISTED, A.REJECTED, A.WITHDRAWN}),
    A.SHORTLISTED: frozenset({A.INTERVIEW, A.REJECTED}),
    A.INTERVIEW: frozenset({A.OFFER, A.REJECTED}),
    A.OFFER: frozenset({A.HIRED, A.REJECTED}),
    A.HIRED: frozenset(),
    A.REJECTED: frozenset(),
    A.WITHDRAWN: frozenset(),
}
TERMINAL = frozenset({A.HIRED, A.REJECTED, A.WITHDRAWN})
CANDIDATE_MESSAGES = {
    A.SCREENING: "is now being screened",
    A.SHORTLISTED: "has been shortlisted",
    A.INTERVIEW: "has moved to the interview stage",
    A.OFFER: "has reached the offer stage — congratulations!",
    A.HIRED: "was successful — welcome aboard!",
    A.REJECTED: "has been updated: the team decided not to proceed",
}


def staff_targets(status: ApplicationStatus) -> list[ApplicationStatus]:
    """Next statuses a recruiter may choose (WITHDRAWN is candidate-only)."""
    return sorted(TRANSITIONS[status] - {A.WITHDRAWN}, key=lambda s: s.value)


def apply_transition(
    session: AsyncSession,
    app: Application,
    target: ApplicationStatus,
    *,
    actor_id: uuid.UUID | None,
    comment: str | None = None,
) -> None:
    """Validate and record a stage change (history row in the same transaction). Caller commits."""
    if target not in TRANSITIONS[app.status]:
        raise InvalidStateTransitionError(
            f"An application in '{app.status.value}' cannot move to '{target.value}'",
            details={
                "from": app.status.value,
                "to": target.value,
                "allowed": sorted(s.value for s in TRANSITIONS[app.status]),
            },
        )
    session.add(
        ApplicationStatusHistory(
            application_id=app.id,
            from_status=app.status,
            to_status=target,
            actor_id=actor_id,
            comment=comment,
        )
    )
    app.status = target
    app.status_changed_at = utcnow()
    if target == A.REJECTED and comment:
        app.rejection_reason = comment[:500]


class ApplicationService:
    def __init__(
        self, session: AsyncSession, dispatcher: Dispatcher | None = None, cache: Cache | None = None
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.cache = cache

    async def _invalidate(self) -> None:
        if self.cache:
            await self.cache.invalidate(CacheDomain.APPLICATIONS)

    # --- submit ---------------------------------------------------------------------------------------------
    async def apply(self, user: User, data: ApplicationCreate) -> Application:
        if user.role != Role.CANDIDATE:
            raise PermissionDeniedError("Only candidates can apply to jobs")
        profile = (
            await self.session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
        ).scalar_one_or_none()
        if profile is None:
            raise NotFoundError("Candidate profile not found", code="CANDIDATE_NOT_FOUND")
        job = await self.session.get(Job, data.job_id)
        if job is None:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        if job.status.value in ("DRAFT", "ARCHIVED"):
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")  # not publicly visible
        if (
            await self.session.scalar(select(Company.status).where(Company.id == job.company_id))
            != CompanyStatus.ACTIVE
        ):
            raise NotFoundError(
                "Job not found", code="JOB_NOT_FOUND"
            )  # a suspended employer's postings are off the public site
        open_, reason = is_open_for_applications(job)
        if not open_:
            raise BusinessRuleError(
                reason or "This job is not accepting applications", code="JOB_NOT_ACCEPTING_APPLICATIONS"
            )
        existing = await self.session.scalar(
            select(Application.id).where(
                Application.job_id == job.id,
                Application.candidate_id == profile.id,
                Application.status != A.WITHDRAWN,
            )
        )
        if existing:
            raise ConflictError("You have already applied to this job.", code="APPLICATION_ALREADY_EXISTS")

        resume_id = data.resume_id
        if resume_id is not None:
            resume = await self.session.get(Resume, resume_id)
            if resume is None or resume.candidate_id != profile.id:
                raise NotFoundError("Résumé not found", code="RESUME_NOT_FOUND")
        else:
            resume_id = await self.session.scalar(
                select(Resume.id).where(Resume.candidate_id == profile.id, Resume.is_primary.is_(True))
            )

        app = Application(
            job_id=job.id,
            candidate_id=profile.id,
            resume_id=resume_id,
            cover_letter=data.cover_letter,
            source=data.source,
            status=A.APPLIED,
        )
        self.session.add(app)
        try:
            await self.session.flush()
        except (
            IntegrityError
        ) as exc:  # concurrent double submit: the partial unique index is the final arbiter
            await self.session.rollback()
            raise ConflictError(
                "You have already applied to this job.", code="APPLICATION_ALREADY_EXISTS"
            ) from exc
        self.session.add(
            ApplicationStatusHistory(
                application_id=app.id, from_status=None, to_status=A.APPLIED, actor_id=user.id
            )
        )
        notifier = NotificationService(self.session)
        await notifier.stage(
            user.id,
            NotificationType.APPLICATION_SUBMITTED,
            "Application submitted",
            f"Your application for “{job.title}” was received.",
            job_id=job.id,
            application_id=app.id,
            dedupe_key=f"app-submitted:{app.id}",
        )
        recipients = {uid for uid in (job.created_by_id, job.hiring_manager_id) if uid}
        for uid in recipients:
            await notifier.stage(
                uid,
                NotificationType.APPLICATION_SUBMITTED,
                "New application",
                f"{profile.display_name} applied to “{job.title}”.",
                job_id=job.id,
                application_id=app.id,
                dedupe_key=f"app-submitted:{app.id}",
            )
        record_audit(
            self.session,
            actor_id=user.id,
            action="application.submitted",
            entity_type="application",
            entity_id=app.id,
            company_id=job.company_id,
        )
        await self.session.commit()
        await self._invalidate()
        # Make sure the applicant is ranked for the recruiter (idempotent, deduplicated background task).
        await schedule_job_match(
            self.session, self.dispatcher, job.id, user_id=user.id, company_id=job.company_id
        )
        return app

    # --- stage changes --------------------------------------------------------------------------------------------
    async def _lock(self, application_id: uuid.UUID) -> None:
        await self.session.execute(
            select(Application.id).where(Application.id == application_id).with_for_update()
        )

    async def change_status(
        self, user: User, application_id: uuid.UUID, target: ApplicationStatus, comment: str | None = None
    ) -> Application:
        app, job = await load_application_for_user(self.session, user, application_id, manage=True)
        if target == A.WITHDRAWN:
            raise BusinessRuleError(
                "Only the candidate can withdraw an application", code="WITHDRAW_BY_CANDIDATE_ONLY"
            )
        await self._lock(application_id)
        await self.session.refresh(app)
        previous = app.status
        apply_transition(self.session, app, target, actor_id=user.id, comment=comment)
        await self._notify_candidate(app, job, target)
        record_audit(
            self.session,
            actor_id=user.id,
            action="application.status_changed",
            entity_type="application",
            entity_id=app.id,
            company_id=job.company_id,
            meta={"from": previous.value, "to": target.value},
        )
        await self.session.commit()
        await self._invalidate()
        return app

    async def _notify_candidate(self, app: Application, job: Job, target: ApplicationStatus) -> None:
        if target not in CANDIDATE_MESSAGES:
            return
        uid = await self.session.scalar(
            select(CandidateProfile.user_id).where(CandidateProfile.id == app.candidate_id)
        )
        if uid:
            await NotificationService(self.session).stage(
                uid,
                NotificationType.APPLICATION_STATUS_CHANGED,
                "Application update",
                f"Your application for “{job.title}” {CANDIDATE_MESSAGES[target]}.",
                job_id=job.id,
                application_id=app.id,
                dedupe_key=f"app-status:{app.id}:{target.value}",
            )

    async def withdraw(
        self, user: User, application_id: uuid.UUID, comment: str | None = None
    ) -> Application:
        app, job = await load_application_for_user(self.session, user, application_id)
        if user.role != Role.CANDIDATE:
            raise PermissionDeniedError("Only the candidate can withdraw an application")
        await self._lock(application_id)
        await self.session.refresh(app)
        if app.status not in (A.APPLIED, A.SCREENING):
            raise BusinessRuleError(
                "This application is already past the screening stage; please contact the recruiter to withdraw",
                code="CANNOT_WITHDRAW",
                details={"status": app.status.value},
            )
        apply_transition(self.session, app, A.WITHDRAWN, actor_id=user.id, comment=comment)
        record_audit(
            self.session,
            actor_id=user.id,
            action="application.withdrawn",
            entity_type="application",
            entity_id=app.id,
            company_id=job.company_id,
        )
        await self.session.commit()
        await self._invalidate()
        return app

    # --- notes -------------------------------------------------------------------------------------------------------
    async def add_note(self, user: User, application_id: uuid.UUID, body: str) -> NoteOut:
        if not is_staff(user) and not is_admin(user):
            raise PermissionDeniedError("Only hiring staff can add notes")
        app, _ = await load_application_for_user(self.session, user, application_id)
        note = ApplicationNote(application_id=app.id, author_id=user.id, body=body.strip())
        self.session.add(note)
        await self.session.commit()
        return NoteOut(
            id=note.id,
            author_id=user.id,
            author_name=user.full_name,
            body=note.body,
            created_at=note.created_at,
        )

    async def list_notes(self, user: User, application_id: uuid.UUID) -> list[NoteOut]:
        if not is_staff(user) and not is_admin(user):
            raise PermissionDeniedError("Notes are internal to the hiring team")
        app, _ = await load_application_for_user(self.session, user, application_id)
        rows = (
            await self.session.execute(
                select(ApplicationNote, User)
                .outerjoin(User, User.id == ApplicationNote.author_id)
                .where(ApplicationNote.application_id == app.id)
                .order_by(ApplicationNote.created_at.desc())
            )
        ).all()
        return [
            NoteOut(
                id=n.id,
                author_id=n.author_id,
                author_name=u.full_name if u else None,
                body=n.body,
                created_at=n.created_at,
            )
            for n, u in rows
        ]

    # --- reads ---------------------------------------------------------------------------------------------------------
    def _scope(self, user: User, stmt: Any) -> Any:
        if user.role == Role.CANDIDATE:
            return stmt.where(CandidateProfile.user_id == user.id)
        if is_admin(user):
            return stmt
        if user.company_id is None:
            return stmt.where(False)
        stmt = stmt.where(Job.company_id == user.company_id)
        if user.role == Role.HIRING_MANAGER:
            stmt = stmt.where(Job.hiring_manager_id == user.id)
        return stmt

    async def list(
        self,
        user: User,
        *,
        job_id: uuid.UUID | None = None,
        statuses: list[ApplicationStatus] | None = None,
        q: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 20,
        active_only: bool = False,
    ) -> tuple[list[ApplicationListItem], int]:
        next_interview = (
            select(func.min(Interview.start_at))
            .where(
                Interview.application_id == Application.id,
                Interview.status.in_(ACTIVE_INTERVIEW_STATUSES),
                Interview.start_at >= func.now(),
            )
            .correlate(Application)
            .scalar_subquery()
        )
        stmt = (
            select(
                Application,
                Job,
                Company,
                CandidateProfile,
                CandidateJobMatch.overall_score,
                next_interview.label("next_interview_at"),
            )
            .join(Job, Job.id == Application.job_id)
            .join(Company, Company.id == Job.company_id)
            .join(CandidateProfile, CandidateProfile.id == Application.candidate_id)
            .outerjoin(
                CandidateJobMatch,
                and_(
                    CandidateJobMatch.job_id == Application.job_id,
                    CandidateJobMatch.candidate_id == Application.candidate_id,
                ),
            )
        )
        stmt = self._scope(user, stmt)
        if job_id:
            stmt = stmt.where(Application.job_id == job_id)
        if statuses:
            stmt = stmt.where(Application.status.in_(statuses))
        if active_only:
            stmt = stmt.where(Application.status.not_in(list(TERMINAL)))
        if q and q.strip():
            like = f"%{escape_like(q.strip().lower())}%"
            stmt = stmt.where(
                or_(func.lower(CandidateProfile.display_name).like(like), func.lower(Job.title).like(like))
            )
        orders: dict[str, list[Any]] = {
            "newest": [Application.applied_at.desc()],
            "oldest": [Application.applied_at.asc()],
            "updated": [Application.status_changed_at.desc()],
            "match": [CandidateJobMatch.overall_score.desc().nulls_last(), Application.applied_at.desc()],
        }
        order: list[Any] = orders.get(sort, [Application.applied_at.desc()])
        rows, total = await paginate(
            self.session, stmt.order_by(*order, Application.id), page=page, page_size=page_size, scalars=False
        )
        items = [
            ApplicationListItem(
                id=a.id,
                job_id=j.id,
                job_title=j.title,
                company_id=c.id,
                company_name=c.name,
                candidate_id=p.id,
                candidate_name=p.display_name,
                candidate_headline=p.headline if user.role != Role.CANDIDATE else None,
                status=a.status,
                applied_at=a.applied_at,
                status_changed_at=a.status_changed_at,
                match_score=float(score) if score is not None and user.role != Role.CANDIDATE else None,
                match_band=overall_band(score) if score is not None and user.role != Role.CANDIDATE else None,
                has_resume=a.resume_id is not None,
                next_interview_at=nxt,
            )
            for a, j, c, p, score, nxt in rows
        ]
        return items, total

    async def detail(self, user: User, application_id: uuid.UUID) -> ApplicationDetail:
        app, job = await load_application_for_user(self.session, user, application_id)
        company = await self.session.get(Company, job.company_id)
        cand = await self.session.get(CandidateProfile, app.candidate_id)
        assert company is not None
        assert cand is not None
        is_candidate = user.role == Role.CANDIDATE
        hist_rows = (
            await self.session.execute(
                select(ApplicationStatusHistory, User)
                .outerjoin(User, User.id == ApplicationStatusHistory.actor_id)
                .where(ApplicationStatusHistory.application_id == app.id)
                .order_by(ApplicationStatusHistory.created_at, ApplicationStatusHistory.id)
            )
        ).all()
        history = [
            HistoryEntry(
                id=h.id,
                from_status=h.from_status,
                to_status=h.to_status,
                # Candidates see the timeline, but not staff identities or internal comments.
                actor_name=(
                    "You"
                    if u and u.id == user.id
                    else "Hiring team"
                    if is_candidate
                    else (u.full_name if u else None)
                ),
                comment=(h.comment if (not is_candidate or (u and u.id == user.id)) else None),
                created_at=h.created_at,
            )
            for h, u in hist_rows
        ]
        filename = None
        if app.resume_id:
            filename = await self.session.scalar(
                select(ResumeDocument.original_filename)
                .where(ResumeDocument.resume_id == app.resume_id)
                .limit(1)
            )
        match = None
        if not is_candidate:
            m = (
                await self.session.execute(
                    select(CandidateJobMatch).where(
                        CandidateJobMatch.job_id == app.job_id,
                        CandidateJobMatch.candidate_id == app.candidate_id,
                    )
                )
            ).scalar_one_or_none()
            if m:
                match = {
                    "overall_score": m.overall_score,
                    "band": overall_band(m.overall_score),
                    "summary": m.explanation.get("summary"),
                }
        return ApplicationDetail(
            id=app.id,
            job_id=job.id,
            job_title=job.title,
            company_id=company.id,
            company_name=company.name,
            candidate_id=cand.id,
            candidate_name=cand.display_name,
            status=app.status,
            cover_letter=app.cover_letter,
            resume_id=app.resume_id,
            resume_filename=filename,
            source=app.source,
            rejection_reason=None if is_candidate else app.rejection_reason,
            applied_at=app.applied_at,
            status_changed_at=app.status_changed_at,
            allowed_next_statuses=[]
            if (is_candidate or user.role == Role.HIRING_MANAGER)
            else staff_targets(app.status),
            match=match,
            history=history,
        )
