"""Interview scheduling, participants, conflict detection and structured feedback.

Invariants maintained here (the database is the final arbiter, this service keeps it consistent):

* ``interview_participants.during`` / ``is_active`` always mirror the interview's slot while it is active, in the same
  transaction as every create / reschedule / cancel / complete / no-show - so the GiST exclusion constraints keep both
  the candidate and every interviewer from being double-booked, also under concurrency.
* Conflicts are pre-checked for a friendly message (with the clashing time window); the PostgreSQL exclusion violation
  is caught as the race-safe fallback and reported identically (409 ``INTERVIEW_CONFLICT``).
* Candidates only ever receive ``CandidateInterviewView`` - no notes, feedback, ratings or internal reasons.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import Cache, CacheDomain
from app.core.errors import (
    BusinessRuleError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailure,
)
from app.core.security import STAFF_ROLES, Role
from app.db.models import (
    ACTIVE_INTERVIEW_STATUSES,
    Application,
    ApplicationStatus,
    AuditEvent,
    CandidateProfile,
    Company,
    HireRecommendation,
    Interview,
    InterviewFeedback,
    InterviewParticipant,
    InterviewStatus,
    InterviewType,
    Job,
    NotificationType,
    ParticipantRole,
    User,
    UserStatus,
)
from app.schemas.interview import (
    ApplicationStageOut,
    CancelRequest,
    CandidateInterviewView,
    FeedbackIn,
    FeedbackOut,
    FeedbackSummary,
    InterviewCreate,
    InterviewUpdate,
    ParticipantIn,
    ParticipantOut,
    StaffInterviewItem,
    StaffInterviewView,
)
from app.services.access import is_admin, load_application_for_user
from app.services.applications import CANDIDATE_MESSAGES, apply_transition, staff_targets
from app.services.common import paginate, record_audit, utcnow
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

PAST_TOLERANCE = timedelta(minutes=5)
MAX_DURATION = timedelta(hours=12)
_ACTIVE = tuple(ACTIVE_INTERVIEW_STATUSES)
_CANDIDATE_CONSTRAINT = "ex_interviews_candidate_no_overlap"
_INTERVIEWER_CONSTRAINT = "ex_interview_participants_user_no_overlap"
_TYPE_LABEL = {
    InterviewType.PHONE_SCREEN: "Phone screen",
    InterviewType.TECHNICAL: "Technical interview",
    InterviewType.BEHAVIORAL: "Behavioral interview",
    InterviewType.PANEL: "Panel interview",
    InterviewType.ONSITE: "Onsite interview",
    InterviewType.FINAL: "Final interview",
}


def _now() -> datetime:
    """Single clock for every time rule in this module (tests patch it to move past an interview's start)."""
    return utcnow()


def _slot(start: datetime, end: datetime) -> Range[datetime]:
    return Range(start, end, bounds="[)")


def _to_utc(value: datetime, tz: ZoneInfo) -> datetime:
    """Timezone-aware values are converted; naive values are read as wall-clock time in ``tz``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(UTC)


def _local_iso(value: datetime, tz_name: str) -> str:
    return value.astimezone(ZoneInfo(tz_name)).isoformat()


def _fmt_window(start: datetime, end: datetime) -> str:
    s, e = start.astimezone(UTC), end.astimezone(UTC)
    end_part = f"{e:%H:%M}" if s.date() == e.date() else f"{e:%Y-%m-%d %H:%M}"
    return f"{s:%Y-%m-%d %H:%M} to {end_part} UTC"


def _db_conflict_kind(exc: DBAPIError) -> str | None:
    text = str(exc.orig)
    if _CANDIDATE_CONSTRAINT in text:
        return "candidate"
    if _INTERVIEWER_CONSTRAINT in text:
        return "interviewer"
    if "deadlock detected" in text:
        return "deadlock"
    return None


@dataclass(slots=True)
class Loaded:
    interview: Interview
    application: Application
    job: Job
    company: Company
    candidate: CandidateProfile


@dataclass(slots=True)
class Conflict:
    kind: Literal["candidate", "interviewer"]
    interview_id: uuid.UUID | None
    start_at: datetime | None
    end_at: datetime | None
    who: str | None = None

    def as_detail(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "interview_id": str(self.interview_id) if self.interview_id else None,
            "start_at": self.start_at.astimezone(UTC).isoformat() if self.start_at else None,
            "end_at": self.end_at.astimezone(UTC).isoformat() if self.end_at else None,
            "participant": self.who,
        }


def validate_slot(start: datetime, end: datetime, *, now: datetime, check_past: bool) -> None:
    if end <= start:
        raise ValidationFailure("The interview must end after it starts", code="INVALID_TIME_RANGE")
    if end - start > MAX_DURATION:
        raise ValidationFailure("An interview cannot last longer than 12 hours", code="INTERVIEW_TOO_LONG")
    if check_past and start < now - PAST_TOLERANCE:
        raise ValidationFailure("The interview cannot start in the past", code="INTERVIEW_IN_PAST")


class InterviewService:
    def __init__(self, session: AsyncSession, cache: Cache | None = None) -> None:
        self.session = session
        self.cache = cache

    async def _invalidate(self) -> None:
        if self.cache:
            await self.cache.invalidate(CacheDomain.INTERVIEWS, CacheDomain.APPLICATIONS)

    # ------------------------------------------------------------------------------------------------------------
    # loading & authorization
    # ------------------------------------------------------------------------------------------------------------
    async def _load(self, interview_id: uuid.UUID) -> Loaded:
        row = (
            await self.session.execute(
                select(Interview, Application, Job, Company, CandidateProfile)
                .join(Application, Application.id == Interview.application_id)
                .join(Job, Job.id == Application.job_id)
                .join(Company, Company.id == Job.company_id)
                .join(CandidateProfile, CandidateProfile.id == Interview.candidate_id)
                .where(Interview.id == interview_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Interview not found", code="INTERVIEW_NOT_FOUND")
        return Loaded(*row)

    async def _is_participant(self, interview_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        InterviewParticipant.interview_id == interview_id,
                        InterviewParticipant.user_id == user_id,
                    )
                )
            )
        )

    async def _can_view(self, user: User, ld: Loaded) -> bool:
        if is_admin(user):
            return True
        if user.role == Role.CANDIDATE:
            return ld.candidate.user_id is not None and ld.candidate.user_id == user.id
        if user.company_id is None or user.company_id != ld.interview.company_id:
            return False
        if user.role == Role.RECRUITER:
            return True
        if user.role == Role.HIRING_MANAGER:
            return ld.job.hiring_manager_id == user.id or await self._is_participant(ld.interview.id, user.id)
        return False

    async def _get_visible(self, user: User, interview_id: uuid.UUID) -> Loaded:
        ld = await self._load(interview_id)
        if not await self._can_view(user, ld):
            raise NotFoundError(
                "Interview not found", code="INTERVIEW_NOT_FOUND"
            )  # never reveal other tenants' ids
        return ld

    async def _require_manager(self, user: User, ld: Loaded, *, allow_participant: bool = False) -> None:
        if is_admin(user):
            return
        if user.role == Role.RECRUITER and user.company_id == ld.interview.company_id:
            return
        if (
            allow_participant
            and user.role == Role.HIRING_MANAGER
            and await self._is_participant(ld.interview.id, user.id)
        ):
            return
        raise PermissionDeniedError("You are not allowed to manage this interview")

    async def _lock(self, ld: Loaded) -> None:
        """Serialise concurrent state changes of one interview (``SELECT … FOR UPDATE``) and re-read its state."""
        await self.session.execute(
            select(Interview)
            .where(Interview.id == ld.interview.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _require_active(interview: Interview, action: str) -> None:
        if interview.status not in _ACTIVE:
            raise InvalidStateTransitionError(
                f"A {interview.status.value.lower().replace('_', ' ')} interview cannot be {action}",
                details={"status": interview.status.value},
            )

    # ------------------------------------------------------------------------------------------------------------
    # participants & conflicts
    # ------------------------------------------------------------------------------------------------------------
    async def _resolve_participants(
        self, job: Job, items: list[ParticipantIn]
    ) -> dict[uuid.UUID, ParticipantRole]:
        ids = [p.user_id for p in items]
        if len(set(ids)) != len(ids):
            raise ValidationFailure("A participant can only be listed once", code="DUPLICATE_PARTICIPANT")
        users = {
            u.id: u for u in (await self.session.execute(select(User).where(User.id.in_(ids)))).scalars()
        }
        for p in items:
            u = users.get(p.user_id)
            # Unknown ids and other tenants' users are indistinguishable on purpose.
            if (
                u is None
                or u.company_id != job.company_id
                or u.role not in STAFF_ROLES
                or u.status != UserStatus.ACTIVE
            ):
                raise BusinessRuleError(
                    "Participants must be active recruiters or hiring managers of your company",
                    code="INVALID_PARTICIPANT",
                    details={"user_id": str(p.user_id)},
                )
            if u.role == Role.HIRING_MANAGER and job.hiring_manager_id != u.id:
                raise BusinessRuleError(
                    "A hiring manager can only take part in interviews for jobs assigned to them",
                    code="INVALID_PARTICIPANT",
                    details={"user_id": str(p.user_id)},
                )
        if not any(p.role == ParticipantRole.INTERVIEWER for p in items):
            raise ValidationFailure(
                "At least one participant must be an INTERVIEWER", code="INTERVIEWER_REQUIRED"
            )
        return {p.user_id: p.role for p in items}

    async def _find_conflicts(
        self,
        *,
        company_id: uuid.UUID,
        candidate_id: uuid.UUID | None,
        interviewer_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        exclude: uuid.UUID | None,
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []
        if candidate_id is not None:
            stmt = select(Interview.id, Interview.start_at, Interview.end_at, Interview.company_id).where(
                Interview.candidate_id == candidate_id,
                Interview.status.in_(_ACTIVE),
                Interview.start_at < end,
                Interview.end_at > start,
            )
            if exclude:
                stmt = stmt.where(Interview.id != exclude)
            for iid, s, e, cid in (await self.session.execute(stmt.order_by(Interview.start_at))).all():
                if cid == company_id:
                    conflicts.append(Conflict("candidate", iid, s, e))
                else:  # another company's interview: the candidate is busy, but nothing about it may leak
                    conflicts.append(Conflict("candidate", None, None, None))
        if interviewer_ids:
            stmt2 = (
                select(Interview.id, Interview.start_at, Interview.end_at, User.first_name, User.last_name)
                .join(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
                .join(User, User.id == InterviewParticipant.user_id)
                .where(
                    InterviewParticipant.user_id.in_(interviewer_ids),
                    InterviewParticipant.is_active.is_(True),
                    InterviewParticipant.role == ParticipantRole.INTERVIEWER,
                    Interview.start_at < end,
                    Interview.end_at > start,
                )
            )
            if exclude:
                stmt2 = stmt2.where(Interview.id != exclude)
            for iid, s, e, fn, ln in (await self.session.execute(stmt2.order_by(Interview.start_at))).all():
                conflicts.append(Conflict("interviewer", iid, s, e, f"{fn} {ln}".strip()))
        return conflicts

    @staticmethod
    def _raise_conflict(conflicts: list[Conflict]) -> None:
        first = conflicts[0]
        if first.start_at is None or first.end_at is None:
            message = "The candidate is not available at the requested time"
        elif first.kind == "candidate":
            message = (
                f"The candidate already has an interview from {_fmt_window(first.start_at, first.end_at)}"
            )
        else:
            message = f"{first.who} is already booked from {_fmt_window(first.start_at, first.end_at)}"
        raise ConflictError(
            message, code="INTERVIEW_CONFLICT", details={"conflicts": [c.as_detail() for c in conflicts]}
        )

    async def _raise_db_conflict(
        self,
        exc: DBAPIError,
        *,
        company_id: uuid.UUID,
        candidate_id: uuid.UUID,
        interviewer_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        exclude: uuid.UUID | None,
    ) -> NoReturn:
        """Race-safe fallback: the exclusion constraint fired after the pre-check passed."""
        kind = _db_conflict_kind(exc)
        if kind is None:
            raise exc
        await self.session.rollback()
        conflicts = await self._find_conflicts(
            company_id=company_id,
            candidate_id=candidate_id,
            interviewer_ids=interviewer_ids,
            start=start,
            end=end,
            exclude=exclude,
        )
        if conflicts:
            self._raise_conflict(conflicts)
        who = (
            "The candidate"
            if kind == "candidate"
            else "An interviewer"
            if kind == "interviewer"
            else "The requested slot"
        )
        raise ConflictError(
            f"{who} was booked by a concurrent request; please choose another time",
            code="INTERVIEW_CONFLICT",
            details={
                "conflicts": [
                    {"kind": "candidate" if kind == "candidate" else "interviewer", "interview_id": None}
                ]
            },
        ) from exc

    # ------------------------------------------------------------------------------------------------------------
    # notifications & audit
    # ------------------------------------------------------------------------------------------------------------
    async def _participant_user_ids(self, interview_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            (
                await self.session.execute(
                    select(InterviewParticipant.user_id).where(
                        InterviewParticipant.interview_id == interview_id
                    )
                )
            ).scalars()
        )

    async def _next_version(self, interview_id: uuid.UUID) -> int:
        """Number of reschedules/edits so far + 1 (read under the interview row lock), used in dedupe keys."""
        n = await self.session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.entity_type == "interview",
                AuditEvent.entity_id == interview_id,
                AuditEvent.action.in_(("interview.rescheduled", "interview.updated")),
            )
        )
        return int(n or 0) + 1

    async def _notify(
        self,
        ld: Loaded,
        type_: NotificationType,
        *,
        actor_id: uuid.UUID,
        title: str,
        candidate_message: str,
        staff_message: str,
        dedupe_key: str,
        recipient_ids: list[uuid.UUID] | None = None,
    ) -> None:
        notifier = NotificationService(self.session)
        iv = ld.interview
        if ld.candidate.user_id is not None:
            await notifier.stage(
                ld.candidate.user_id,
                type_,
                title,
                candidate_message,
                job_id=ld.job.id,
                application_id=ld.application.id,
                interview_id=iv.id,
                dedupe_key=dedupe_key,
            )
        ids = recipient_ids if recipient_ids is not None else await self._participant_user_ids(iv.id)
        for uid in dict.fromkeys(ids):
            if uid == actor_id:
                continue
            await notifier.stage(
                uid,
                type_,
                title,
                staff_message,
                job_id=ld.job.id,
                application_id=ld.application.id,
                interview_id=iv.id,
                dedupe_key=dedupe_key,
            )

    @staticmethod
    def _when(iv: Interview) -> str:
        local = iv.start_at.astimezone(ZoneInfo(iv.timezone))
        return f"{local:%a %d %b %Y, %H:%M} ({iv.timezone})"

    # ------------------------------------------------------------------------------------------------------------
    # schedule
    # ------------------------------------------------------------------------------------------------------------
    async def schedule(self, user: User, data: InterviewCreate) -> uuid.UUID:
        app, job = await load_application_for_user(self.session, user, data.application_id, manage=True)
        await self.session.execute(
            select(Application)
            .where(Application.id == app.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if app.status not in (ApplicationStatus.SHORTLISTED, ApplicationStatus.INTERVIEW):
            raise BusinessRuleError(
                "Interviews can only be scheduled for shortlisted applications or applications already at the interview stage",
                code="APPLICATION_NOT_INTERVIEWABLE",
                details={
                    "status": app.status.value,
                    "allowed": [ApplicationStatus.SHORTLISTED.value, ApplicationStatus.INTERVIEW.value],
                },
            )
        tz = ZoneInfo(data.timezone)
        start, end = _to_utc(data.start_at, tz), _to_utc(data.end_at, tz)
        validate_slot(start, end, now=_now(), check_past=True)
        if not data.location and not data.meeting_url:
            raise ValidationFailure(
                "Provide a location or a meeting link (https)", code="LOCATION_OR_LINK_REQUIRED"
            )
        participants = await self._resolve_participants(job, data.participants)
        interviewers = sorted(u for u, r in participants.items() if r == ParticipantRole.INTERVIEWER)
        conflicts = await self._find_conflicts(
            company_id=job.company_id,
            candidate_id=app.candidate_id,
            interviewer_ids=interviewers,
            start=start,
            end=end,
            exclude=None,
        )
        if conflicts:
            self._raise_conflict(conflicts)

        company_id, candidate_id = (
            job.company_id,
            app.candidate_id,
        )  # plain values: ORM state is unusable after a failed flush
        iv = Interview(
            application_id=app.id,
            candidate_id=candidate_id,
            company_id=company_id,
            interview_type=data.interview_type,
            start_at=start,
            end_at=end,
            timezone=data.timezone,
            location=data.location,
            meeting_url=data.meeting_url,
            notes=data.notes,
            status=InterviewStatus.SCHEDULED,
            created_by_id=user.id,
        )
        try:
            self.session.add(iv)
            await self.session.flush()
            # Deterministic insertion order (sorted ids) keeps concurrent requests from deadlocking each other.
            for uid in sorted(participants):
                self.session.add(
                    InterviewParticipant(
                        interview_id=iv.id,
                        user_id=uid,
                        role=participants[uid],
                        is_active=True,
                        during=_slot(start, end),
                    )
                )
            await self.session.flush()
        except DBAPIError as exc:
            await self._raise_db_conflict(
                exc,
                company_id=company_id,
                candidate_id=candidate_id,
                interviewer_ids=interviewers,
                start=start,
                end=end,
                exclude=None,
            )

        company = await self.session.get(Company, job.company_id)
        candidate = await self.session.get(CandidateProfile, app.candidate_id)
        assert company is not None
        assert candidate is not None
        ld = Loaded(iv, app, job, company, candidate)
        if app.status == ApplicationStatus.SHORTLISTED:
            apply_transition(
                self.session,
                app,
                ApplicationStatus.INTERVIEW,
                actor_id=user.id,
                comment="Interview scheduled",
            )
            if candidate.user_id is not None:
                await NotificationService(self.session).stage(
                    candidate.user_id,
                    NotificationType.APPLICATION_STATUS_CHANGED,
                    "Application update",
                    f"Your application for “{job.title}” {CANDIDATE_MESSAGES[ApplicationStatus.INTERVIEW]}.",
                    job_id=job.id,
                    application_id=app.id,
                    dedupe_key=f"app-status:{app.id}:{ApplicationStatus.INTERVIEW.value}",
                )
        when = self._when(iv)
        label = _TYPE_LABEL[iv.interview_type]
        await self._notify(
            ld,
            NotificationType.INTERVIEW_SCHEDULED,
            actor_id=user.id,
            title="Interview scheduled",
            candidate_message=f"{label} for “{job.title}” at {company.name}: {when}.",
            staff_message=f"{label} with {candidate.display_name} for “{job.title}”: {when}.",
            dedupe_key=f"interview-scheduled:{iv.id}",
            recipient_ids=list(participants),
        )
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.scheduled",
            entity_type="interview",
            entity_id=iv.id,
            company_id=job.company_id,
            meta={
                "application_id": str(app.id),
                "interview_type": iv.interview_type.value,
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "participants": [str(u) for u in sorted(participants)],
            },
        )
        try:
            await self.session.commit()
        except DBAPIError as exc:
            await self._raise_db_conflict(
                exc,
                company_id=company_id,
                candidate_id=candidate_id,
                interviewer_ids=interviewers,
                start=start,
                end=end,
                exclude=None,
            )
        await self._invalidate()
        return iv.id

    # ------------------------------------------------------------------------------------------------------------
    # update / reschedule
    # ------------------------------------------------------------------------------------------------------------
    async def update(self, user: User, interview_id: uuid.UUID, data: InterviewUpdate) -> uuid.UUID:
        ld = await self._get_visible(user, interview_id)
        await self._require_manager(user, ld)
        await self._lock(ld)
        iv = ld.interview
        self._require_active(iv, "edited")
        fields = data.model_fields_set

        tz_name = data.timezone if "timezone" in fields and data.timezone else iv.timezone
        tz = ZoneInfo(tz_name)
        new_start = _to_utc(data.start_at, tz) if data.start_at is not None else iv.start_at
        if data.end_at is not None:
            new_end = _to_utc(data.end_at, tz)
        elif data.start_at is not None:
            new_end = new_start + (iv.end_at - iv.start_at)  # moving the start keeps the duration
        else:
            new_end = iv.end_at
        time_changed = new_start != iv.start_at or new_end != iv.end_at
        validate_slot(new_start, new_end, now=_now(), check_past=time_changed)

        new_location = (data.location if "location" in fields else iv.location) or None
        new_url = (data.meeting_url if "meeting_url" in fields else iv.meeting_url) or None
        if not new_location and not new_url:
            raise ValidationFailure(
                "Provide a location or a meeting link (https)", code="LOCATION_OR_LINK_REQUIRED"
            )
        new_type = data.interview_type or iv.interview_type
        new_notes = data.notes if "notes" in fields else iv.notes

        current = {
            p.user_id: p
            for p in (
                await self.session.execute(
                    select(InterviewParticipant)
                    .where(InterviewParticipant.interview_id == iv.id)
                    .with_for_update()
                )
            ).scalars()
        }
        desired: dict[uuid.UUID, ParticipantRole]
        if data.participants is not None:
            desired = await self._resolve_participants(ld.job, data.participants)
        else:
            desired = {uid: p.role for uid, p in current.items()}
        was_interviewer = {uid for uid, p in current.items() if p.role == ParticipantRole.INTERVIEWER}
        interviewers = sorted(uid for uid, r in desired.items() if r == ParticipantRole.INTERVIEWER)
        to_check = (
            interviewers if time_changed else [uid for uid in interviewers if uid not in was_interviewer]
        )
        conflicts = await self._find_conflicts(
            company_id=ld.job.company_id,
            candidate_id=iv.candidate_id if time_changed else None,
            interviewer_ids=to_check,
            start=new_start,
            end=new_end,
            exclude=iv.id,
        )
        if conflicts:
            self._raise_conflict(conflicts)

        details_changed = (
            (new_type != iv.interview_type) or (new_location != iv.location) or (new_url != iv.meeting_url)
        )
        tz_changed = tz_name != iv.timezone
        participants_changed = desired != {uid: p.role for uid, p in current.items()}
        notes_changed = new_notes != iv.notes
        if not (time_changed or details_changed or tz_changed or participants_changed or notes_changed):
            return iv.id  # nothing to do

        version = await self._next_version(iv.id) if (time_changed or details_changed or tz_changed) else 0
        company_id, candidate_id, interview_pk = (
            ld.job.company_id,
            iv.candidate_id,
            iv.id,
        )  # plain values for the failure path
        try:
            iv.interview_type, iv.location, iv.meeting_url, iv.notes, iv.timezone = (
                new_type,
                new_location,
                new_url,
                new_notes,
                tz_name,
            )
            if time_changed:
                iv.start_at, iv.end_at, iv.status = new_start, new_end, InterviewStatus.RESCHEDULED
            await self.session.flush()
            for uid in current.keys() - desired.keys():
                await self.session.delete(current[uid])
            await self.session.flush()
            for uid, p in current.items():
                if uid in desired:
                    p.role = desired[uid]
                    if time_changed:
                        p.during = _slot(new_start, new_end)
            await self.session.flush()
            for uid in sorted(desired.keys() - current.keys()):
                self.session.add(
                    InterviewParticipant(
                        interview_id=iv.id,
                        user_id=uid,
                        role=desired[uid],
                        is_active=True,
                        during=_slot(new_start, new_end),
                    )
                )
            await self.session.flush()
        except DBAPIError as exc:
            await self._raise_db_conflict(
                exc,
                company_id=company_id,
                candidate_id=candidate_id,
                interviewer_ids=interviewers,
                start=new_start,
                end=new_end,
                exclude=interview_pk,
            )

        if time_changed or details_changed or tz_changed:
            when = self._when(iv)
            label = _TYPE_LABEL[iv.interview_type]
            verb = "rescheduled" if time_changed else "updated"
            await self._notify(
                ld,
                NotificationType.INTERVIEW_RESCHEDULED,
                actor_id=user.id,
                title=f"Interview {verb}",
                candidate_message=f"{label} for “{ld.job.title}” at {ld.company.name} was {verb}: {when}.",
                staff_message=f"{label} with {ld.candidate.display_name} for “{ld.job.title}” was {verb}: {when}.",
                dedupe_key=f"interview-rescheduled:{iv.id}:v{version}",
                recipient_ids=list(desired),
            )
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.rescheduled" if time_changed else "interview.updated",
            entity_type="interview",
            entity_id=iv.id,
            company_id=ld.job.company_id,
            meta={"start_at": iv.start_at.isoformat(), "end_at": iv.end_at.isoformat(), "version": version},
        )
        try:
            await self.session.commit()
        except DBAPIError as exc:
            await self._raise_db_conflict(
                exc,
                company_id=company_id,
                candidate_id=candidate_id,
                interviewer_ids=interviewers,
                start=new_start,
                end=new_end,
                exclude=interview_pk,
            )
        await self._invalidate()
        return iv.id

    # ------------------------------------------------------------------------------------------------------------
    # status changes
    # ------------------------------------------------------------------------------------------------------------
    async def _release_slot(self, interview_id: uuid.UUID) -> None:
        await self.session.execute(
            update(InterviewParticipant)
            .where(InterviewParticipant.interview_id == interview_id)
            .values(is_active=False)
        )

    async def cancel(self, user: User, interview_id: uuid.UUID, data: CancelRequest) -> uuid.UUID:
        ld = await self._get_visible(user, interview_id)
        await self._require_manager(user, ld)
        await self._lock(ld)
        iv = ld.interview
        self._require_active(iv, "cancelled")
        iv.status, iv.cancelled_reason = InterviewStatus.CANCELLED, data.reason
        await self.session.flush()
        await self._release_slot(iv.id)
        label = _TYPE_LABEL[iv.interview_type]
        when = self._when(iv)
        await self._notify(
            ld,
            NotificationType.INTERVIEW_CANCELLED,
            actor_id=user.id,
            title="Interview cancelled",
            candidate_message=f"The {label.lower()} for “{ld.job.title}” at {ld.company.name} ({when}) was cancelled. The team will be in touch.",
            staff_message=f"The {label.lower()} with {ld.candidate.display_name} for “{ld.job.title}” ({when}) was cancelled.",
            dedupe_key=f"interview-cancelled:{iv.id}",
        )
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.cancelled",
            entity_type="interview",
            entity_id=iv.id,
            company_id=ld.job.company_id,
            meta={"reason": data.reason},
        )
        await self.session.commit()
        await self._invalidate()
        return iv.id

    async def confirm(self, user: User, interview_id: uuid.UUID) -> uuid.UUID:
        if user.role != Role.CANDIDATE:
            raise PermissionDeniedError("Only the candidate can confirm an interview")
        ld = await self._get_visible(user, interview_id)
        await self._lock(ld)
        iv = ld.interview
        if iv.status == InterviewStatus.CONFIRMED:
            return iv.id  # idempotent
        if iv.status not in (InterviewStatus.SCHEDULED, InterviewStatus.RESCHEDULED):
            raise InvalidStateTransitionError(
                f"A {iv.status.value.lower().replace('_', ' ')} interview cannot be confirmed",
                details={"status": iv.status.value},
            )
        if iv.end_at <= _now():
            raise InvalidStateTransitionError(
                "This interview has already taken place", details={"status": iv.status.value}
            )
        iv.status = InterviewStatus.CONFIRMED
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.confirmed",
            entity_type="interview",
            entity_id=iv.id,
            company_id=iv.company_id,
        )
        await self.session.commit()
        await self._invalidate()
        return iv.id

    async def _finish(self, user: User, interview_id: uuid.UUID, target: InterviewStatus) -> uuid.UUID:
        ld = await self._get_visible(user, interview_id)
        await self._require_manager(user, ld, allow_participant=True)
        await self._lock(ld)
        iv = ld.interview
        verb = "completed" if target == InterviewStatus.COMPLETED else "marked as a no-show"
        self._require_active(iv, verb)
        if iv.start_at > _now():
            raise BusinessRuleError(
                f"An interview that has not started yet cannot be {verb}",
                code="INTERVIEW_NOT_STARTED",
                details={"start_at": iv.start_at.astimezone(UTC).isoformat()},
            )
        iv.status = target
        await self.session.flush()
        await self._release_slot(iv.id)
        record_audit(
            self.session,
            actor_id=user.id,
            action=f"interview.{target.value.lower()}",
            entity_type="interview",
            entity_id=iv.id,
            company_id=iv.company_id,
        )
        await self.session.commit()
        await self._invalidate()
        return iv.id

    async def complete(self, user: User, interview_id: uuid.UUID) -> uuid.UUID:
        return await self._finish(user, interview_id, InterviewStatus.COMPLETED)

    async def no_show(self, user: User, interview_id: uuid.UUID) -> uuid.UUID:
        return await self._finish(user, interview_id, InterviewStatus.NO_SHOW)

    # ------------------------------------------------------------------------------------------------------------
    # feedback (internal: staff only)
    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _require_staff_reader(user: User) -> None:
        if user.role == Role.CANDIDATE or not (user.role in STAFF_ROLES or is_admin(user)):
            raise PermissionDeniedError("Interview feedback is internal to the hiring team")

    @staticmethod
    def _feedback_open(iv: Interview) -> bool:
        return iv.status == InterviewStatus.COMPLETED or (iv.status in _ACTIVE and iv.start_at <= _now())

    def _require_feedback_open(self, iv: Interview) -> None:
        if self._feedback_open(iv):
            return
        if iv.status in (InterviewStatus.CANCELLED, InterviewStatus.NO_SHOW):
            raise BusinessRuleError(
                f"Feedback cannot be recorded for a {iv.status.value.lower().replace('_', ' ')} interview",
                code="FEEDBACK_NOT_ALLOWED",
                details={"status": iv.status.value},
            )
        raise BusinessRuleError(
            "Feedback can only be recorded once the interview has started",
            code="FEEDBACK_TOO_EARLY",
            details={"start_at": iv.start_at.astimezone(UTC).isoformat()},
        )

    async def _feedback_author(self, user: User, interview_id: uuid.UUID) -> Loaded:
        if user.role not in STAFF_ROLES:
            raise PermissionDeniedError("Only the hiring team can record interview feedback")
        return await self._get_visible(user, interview_id)

    def _feedback_out(self, fb: InterviewFeedback, author: str, viewer_id: uuid.UUID) -> FeedbackOut:
        return FeedbackOut(
            id=fb.id,
            interview_id=fb.interview_id,
            author_id=fb.author_id,
            author_name=author,
            rating=fb.rating,
            recommendation=fb.recommendation,
            strengths=fb.strengths,
            weaknesses=fb.weaknesses,
            notes=fb.notes,
            submitted_at=fb.submitted_at,
            is_mine=fb.author_id == viewer_id,
        )

    async def submit_feedback(self, user: User, interview_id: uuid.UUID, data: FeedbackIn) -> FeedbackOut:
        ld = await self._feedback_author(user, interview_id)
        self._require_feedback_open(ld.interview)
        existing = await self.session.scalar(
            select(InterviewFeedback.id).where(
                InterviewFeedback.interview_id == interview_id, InterviewFeedback.author_id == user.id
            )
        )
        if existing:
            raise ConflictError(
                "You have already submitted feedback for this interview; use PUT to update it",
                code="FEEDBACK_ALREADY_SUBMITTED",
            )
        fb = InterviewFeedback(
            interview_id=interview_id,
            author_id=user.id,
            rating=data.rating,
            recommendation=data.recommendation,
            strengths=data.strengths,
            weaknesses=data.weaknesses,
            notes=data.notes,
        )
        self.session.add(fb)
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.feedback_submitted",
            entity_type="interview",
            entity_id=interview_id,
            company_id=ld.interview.company_id,
            meta={"recommendation": data.recommendation.value},
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:  # concurrent double submit: the unique constraint is the final arbiter
            await self.session.rollback()
            raise ConflictError(
                "You have already submitted feedback for this interview; use PUT to update it",
                code="FEEDBACK_ALREADY_SUBMITTED",
            ) from exc
        await self._invalidate()
        await self.session.refresh(fb)
        return self._feedback_out(fb, user.full_name, user.id)

    async def update_feedback(self, user: User, interview_id: uuid.UUID, data: FeedbackIn) -> FeedbackOut:
        ld = await self._feedback_author(user, interview_id)
        if ld.interview.status == InterviewStatus.CANCELLED:
            self._require_feedback_open(ld.interview)
        fb = (
            await self.session.execute(
                select(InterviewFeedback)
                .where(InterviewFeedback.interview_id == interview_id, InterviewFeedback.author_id == user.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if fb is None:
            raise NotFoundError(
                "You have not submitted feedback for this interview yet", code="FEEDBACK_NOT_FOUND"
            )
        fb.rating, fb.recommendation = data.rating, data.recommendation
        fb.strengths, fb.weaknesses, fb.notes = data.strengths, data.weaknesses, data.notes
        record_audit(
            self.session,
            actor_id=user.id,
            action="interview.feedback_updated",
            entity_type="interview",
            entity_id=interview_id,
            company_id=ld.interview.company_id,
            meta={"recommendation": data.recommendation.value},
        )
        await self.session.commit()
        await self._invalidate()
        await self.session.refresh(fb)
        return self._feedback_out(fb, user.full_name, user.id)

    async def list_feedback(self, user: User, interview_id: uuid.UUID) -> FeedbackSummary:
        self._require_staff_reader(user)  # candidates: 403 regardless of ownership - nothing to probe
        ld = await self._get_visible(user, interview_id)
        rows = (
            await self.session.execute(
                select(InterviewFeedback, User.first_name, User.last_name)
                .join(User, User.id == InterviewFeedback.author_id)
                .where(InterviewFeedback.interview_id == ld.interview.id)
                .order_by(InterviewFeedback.submitted_at, InterviewFeedback.id)
            )
        ).all()
        items = [self._feedback_out(fb, f"{fn} {ln}".strip(), user.id) for fb, fn, ln in rows]
        dist = dict.fromkeys(HireRecommendation, 0)
        for it in items:
            dist[it.recommendation] += 1
        avg = round(sum(i.rating for i in items) / len(items), 2) if items else None
        return FeedbackSummary(
            interview_id=ld.interview.id,
            count=len(items),
            average_rating=avg,
            recommendations=dist,
            items=items,
        )

    # ------------------------------------------------------------------------------------------------------------
    # read models
    # ------------------------------------------------------------------------------------------------------------
    async def _participants(self, interview_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ParticipantOut]]:
        if not interview_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    InterviewParticipant.interview_id,
                    InterviewParticipant.user_id,
                    InterviewParticipant.role,
                    User.first_name,
                    User.last_name,
                )
                .join(User, User.id == InterviewParticipant.user_id)
                .where(InterviewParticipant.interview_id.in_(interview_ids))
                .order_by(InterviewParticipant.role, User.last_name, User.first_name, User.id)
            )
        ).all()
        authors = {
            (iid, uid)
            for iid, uid in (
                await self.session.execute(
                    select(InterviewFeedback.interview_id, InterviewFeedback.author_id).where(
                        InterviewFeedback.interview_id.in_(interview_ids)
                    )
                )
            ).all()
        }
        out: dict[uuid.UUID, list[ParticipantOut]] = {i: [] for i in interview_ids}
        for iid, uid, role, fn, ln in rows:
            out[iid].append(
                ParticipantOut(
                    user_id=uid,
                    name=f"{fn} {ln}".strip(),
                    role=role,
                    has_submitted_feedback=(iid, uid) in authors,
                )
            )
        return out

    async def _feedback_counts(self, interview_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not interview_ids:
            return {}
        rows = (
            await self.session.execute(
                select(InterviewFeedback.interview_id, func.count())
                .where(InterviewFeedback.interview_id.in_(interview_ids))
                .group_by(InterviewFeedback.interview_id)
            )
        ).all()
        return {iid: int(n) for iid, n in rows}

    @staticmethod
    def _can_confirm(iv: Interview) -> bool:
        return iv.status in (InterviewStatus.SCHEDULED, InterviewStatus.RESCHEDULED) and iv.end_at > _now()

    def _candidate_view(
        self, iv: Interview, job_id: uuid.UUID, job_title: str, company_name: str, interviewers: list[str]
    ) -> CandidateInterviewView:
        return CandidateInterviewView(
            id=iv.id,
            application_id=iv.application_id,
            job_id=job_id,
            job_title=job_title,
            company_name=company_name,
            interview_type=iv.interview_type,
            start_at=iv.start_at,
            end_at=iv.end_at,
            start_local=_local_iso(iv.start_at, iv.timezone),
            end_local=_local_iso(iv.end_at, iv.timezone),
            timezone=iv.timezone,
            duration_minutes=int((iv.end_at - iv.start_at).total_seconds() // 60),
            location=iv.location,
            meeting_url=iv.meeting_url,
            status=iv.status,
            interviewers=interviewers,
            can_confirm=self._can_confirm(iv),
        )

    async def detail(
        self, user: User, interview_id: uuid.UUID
    ) -> StaffInterviewView | CandidateInterviewView:
        ld = await self._get_visible(user, interview_id)
        iv = ld.interview
        participants = (await self._participants([iv.id]))[iv.id]
        if user.role == Role.CANDIDATE:
            return self._candidate_view(
                iv, ld.job.id, ld.job.title, ld.company.name, [p.name for p in participants]
            )
        counts = await self._feedback_counts([iv.id])
        creator = await self.session.get(User, iv.created_by_id) if iv.created_by_id else None
        mine = bool(
            await self.session.scalar(
                select(
                    exists().where(
                        InterviewFeedback.interview_id == iv.id, InterviewFeedback.author_id == user.id
                    )
                )
            )
        )
        can_manage_stage = is_admin(user) or user.role == Role.RECRUITER
        return StaffInterviewView(
            id=iv.id,
            application_id=iv.application_id,
            job_id=ld.job.id,
            job_title=ld.job.title,
            candidate_id=ld.candidate.id,
            candidate_name=ld.candidate.display_name,
            interview_type=iv.interview_type,
            start_at=iv.start_at,
            end_at=iv.end_at,
            timezone=iv.timezone,
            location=iv.location,
            meeting_url=iv.meeting_url,
            status=iv.status,
            participants=participants,
            feedback_count=counts.get(iv.id, 0),
            company_id=ld.company.id,
            company_name=ld.company.name,
            start_local=_local_iso(iv.start_at, iv.timezone),
            end_local=_local_iso(iv.end_at, iv.timezone),
            duration_minutes=int((iv.end_at - iv.start_at).total_seconds() // 60),
            notes=iv.notes,
            cancelled_reason=iv.cancelled_reason,
            created_by_id=iv.created_by_id,
            created_by_name=creator.full_name if creator else None,
            my_feedback_submitted=mine,
            can_submit_feedback=(user.role in STAFF_ROLES and not mine and self._feedback_open(iv)),
            application=ApplicationStageOut(
                id=ld.application.id,
                status=ld.application.status,
                allowed_next_statuses=staff_targets(ld.application.status) if can_manage_stage else [],
            ),
            created_at=iv.created_at,
            updated_at=iv.updated_at,
        )

    def _scope(self, user: User, stmt: Any) -> Any:
        if user.role == Role.CANDIDATE:
            return stmt.where(CandidateProfile.user_id == user.id)
        if is_admin(user):
            return stmt
        if user.company_id is None or user.role not in STAFF_ROLES:
            return stmt.where(False)
        stmt = stmt.where(Interview.company_id == user.company_id)
        if user.role == Role.HIRING_MANAGER:
            mine = exists().where(
                InterviewParticipant.interview_id == Interview.id, InterviewParticipant.user_id == user.id
            )
            stmt = stmt.where(or_(Job.hiring_manager_id == user.id, mine))
        return stmt

    async def list(
        self,
        user: User,
        *,
        statuses: list[InterviewStatus] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        application_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        upcoming_only: bool = False,
        descending: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StaffInterviewItem | CandidateInterviewView], int]:
        if from_date and to_date and from_date > to_date:
            raise ValidationFailure("from_date must not be after to_date", code="INVALID_DATE_RANGE")
        stmt = (
            select(Interview, Job.id, Job.title, Company.name, CandidateProfile.display_name)
            .join(Application, Application.id == Interview.application_id)
            .join(Job, Job.id == Application.job_id)
            .join(Company, Company.id == Job.company_id)
            .join(CandidateProfile, CandidateProfile.id == Interview.candidate_id)
        )
        stmt = self._scope(user, stmt)
        if statuses:
            stmt = stmt.where(Interview.status.in_(statuses))
        if from_date:
            stmt = stmt.where(Interview.start_at >= datetime.combine(from_date, time.min, UTC))
        if to_date:
            stmt = stmt.where(
                Interview.start_at < datetime.combine(to_date + timedelta(days=1), time.min, UTC)
            )
        if application_id:
            stmt = stmt.where(Interview.application_id == application_id)
        if job_id:
            stmt = stmt.where(Job.id == job_id)
        if candidate_id:
            stmt = stmt.where(Interview.candidate_id == candidate_id)
        if upcoming_only:
            stmt = stmt.where(Interview.status.in_(_ACTIVE), Interview.end_at >= _now())
        order = Interview.start_at.desc() if descending else Interview.start_at.asc()
        rows, total = await paginate(
            self.session, stmt.order_by(order, Interview.id), page=page, page_size=page_size, scalars=False
        )
        ids = [r[0].id for r in rows]
        participants = await self._participants(ids)
        counts = await self._feedback_counts(ids) if user.role != Role.CANDIDATE else {}
        items: list[StaffInterviewItem | CandidateInterviewView] = []
        for iv, jid, jtitle, cname, dname in rows:
            if user.role == Role.CANDIDATE:
                items.append(
                    self._candidate_view(iv, jid, jtitle, cname, [p.name for p in participants[iv.id]])
                )
            else:
                items.append(
                    StaffInterviewItem(
                        id=iv.id,
                        application_id=iv.application_id,
                        job_id=jid,
                        job_title=jtitle,
                        candidate_id=iv.candidate_id,
                        candidate_name=dname,
                        interview_type=iv.interview_type,
                        start_at=iv.start_at,
                        end_at=iv.end_at,
                        timezone=iv.timezone,
                        location=iv.location,
                        meeting_url=iv.meeting_url,
                        status=iv.status,
                        participants=participants[iv.id],
                        feedback_count=counts.get(iv.id, 0),
                    )
                )
        return items, total
