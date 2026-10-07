"""Interviews: scheduling, rescheduling, candidate confirmation, outcome and internal feedback."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CacheDep, CurrentUser, Pagination, SessionDep, require
from app.core.security import Permission
from app.db.models import InterviewStatus, User
from app.schemas.common import COMMON_ERRORS, ErrorResponse, Page
from app.schemas.interview import (
    CancelRequest,
    FeedbackIn,
    FeedbackOut,
    FeedbackSummary,
    InterviewCreate,
    InterviewDetail,
    InterviewListEntry,
    InterviewUpdate,
)
from app.services.interviews import InterviewService

router = APIRouter(prefix="/interviews", tags=["Interviews"], responses=COMMON_ERRORS)


def _svc(session: SessionDep, cache: CacheDep) -> InterviewService:
    return InterviewService(session, cache)


Svc = Annotated[InterviewService, Depends(_svc)]
Scheduler = Annotated[User, Depends(require(Permission.SCHEDULE_INTERVIEWS))]
Viewer = Annotated[User, Depends(require(Permission.VIEW_INTERVIEWS))]
FeedbackAuthor = Annotated[User, Depends(require(Permission.PROVIDE_FEEDBACK))]

_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "INTERVIEW_CONFLICT (candidate or interviewer already booked) or an invalid state transition",
    }
}


@router.post(
    "",
    response_model=InterviewDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule an interview (recruiters)",
    description=(
        "Only SHORTLISTED or INTERVIEW applications can be scheduled (`APPLICATION_NOT_INTERVIEWABLE` otherwise). Scheduling the first "
        "interview moves a SHORTLISTED application to INTERVIEW. Participants must be active recruiters / hiring managers of the same "
        "company (a hiring manager only for jobs assigned to them) and at least one must be an INTERVIEWER. The candidate and every "
        "interviewer are protected against double-booking: a clash returns `409 INTERVIEW_CONFLICT` with the clashing time window, "
        "also when two requests race (the database exclusion constraint decides)."
    ),
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def schedule_interview(data: InterviewCreate, user: Scheduler, svc: Svc) -> InterviewDetail:
    interview_id = await svc.schedule(user, data)
    return await svc.detail(user, interview_id)


@router.get(
    "",
    response_model=Page[InterviewListEntry],
    summary="List interviews visible to me",
    description=(
        "Candidates see their own interviews (logistics only); recruiters their company's; hiring managers the ones they take part in "
        "or for jobs assigned to them. Sorted by start time. `from_date`/`to_date` are inclusive calendar dates in UTC. "
        "`upcoming_only` keeps SCHEDULED/CONFIRMED/RESCHEDULED interviews that have not ended yet."
    ),
)
async def list_interviews(
    user: Viewer,
    svc: Svc,
    p: Pagination,
    status_: Annotated[
        list[InterviewStatus] | None, Query(alias="status", description="Repeatable status filter")
    ] = None,
    from_date: Annotated[date | None, Query(description="First day (UTC) to include")] = None,
    to_date: Annotated[date | None, Query(description="Last day (UTC) to include")] = None,
    application_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    upcoming_only: bool = False,
    sort: Annotated[str, Query(pattern="^(start_asc|start_desc)$")] = "start_asc",
) -> Page[InterviewListEntry]:
    items, total = await svc.list(
        user,
        statuses=status_,
        from_date=from_date,
        to_date=to_date,
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        upcoming_only=upcoming_only,
        descending=sort == "start_desc",
        page=p.page,
        page_size=p.page_size,
    )
    return Page.build(items, page=p.page, page_size=p.page_size, total=total)


@router.get(
    "/{interview_id}",
    response_model=InterviewDetail,
    summary="Interview detail",
    description=(
        "Staff get the full record (internal notes, participants, feedback counters and the application's `allowed_next_statuses` so the "
        "UI can offer *Advance to OFFER / Reject*). Candidates get a restricted representation without any internal data."
    ),
)
async def get_interview(interview_id: uuid.UUID, user: Viewer, svc: Svc) -> InterviewDetail:
    return await svc.detail(user, interview_id)


@router.patch(
    "/{interview_id}",
    response_model=InterviewDetail,
    summary="Reschedule or edit an interview (recruiters)",
    description=(
        "Changing the time moves the interview to RESCHEDULED (the candidate must confirm again), re-checks conflicts and notifies the "
        "candidate and participants. Details-only edits (location, link, type, participants, notes) do not change the status."
    ),
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def update_interview(
    interview_id: uuid.UUID, data: InterviewUpdate, user: Scheduler, svc: Svc
) -> InterviewDetail:
    await svc.update(user, interview_id, data)
    return await svc.detail(user, interview_id)


@router.post(
    "/{interview_id}/cancel",
    response_model=InterviewDetail,
    summary="Cancel an interview (recruiters)",
    description="Frees the candidate's and interviewers' calendar slot immediately and notifies everyone. The reason is internal.",
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def cancel_interview(
    interview_id: uuid.UUID, data: CancelRequest, user: Scheduler, svc: Svc
) -> InterviewDetail:
    await svc.cancel(user, interview_id, data)
    return await svc.detail(user, interview_id)


@router.post(
    "/{interview_id}/confirm",
    response_model=InterviewDetail,
    summary="Confirm attendance (candidate)",
    description="SCHEDULED / RESCHEDULED → CONFIRMED. Idempotent. Only the candidate of the interview can confirm.",
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def confirm_interview(interview_id: uuid.UUID, user: Viewer, svc: Svc) -> InterviewDetail:
    await svc.confirm(user, interview_id)
    return await svc.detail(user, interview_id)


@router.post(
    "/{interview_id}/complete",
    response_model=InterviewDetail,
    summary="Mark an interview as completed (staff)",
    description="Allowed once the start time has passed. Recruiters, admins and participating hiring managers.",
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def complete_interview(interview_id: uuid.UUID, user: Viewer, svc: Svc) -> InterviewDetail:
    await svc.complete(user, interview_id)
    return await svc.detail(user, interview_id)


@router.post(
    "/{interview_id}/no-show",
    response_model=InterviewDetail,
    summary="Record that the candidate did not show up (staff)",
    description="Allowed once the start time has passed. The application's stage is not changed automatically.",
    responses={**COMMON_ERRORS, **_CONFLICT},
)
async def no_show_interview(interview_id: uuid.UUID, user: Viewer, svc: Svc) -> InterviewDetail:
    await svc.no_show(user, interview_id)
    return await svc.detail(user, interview_id)


@router.post(
    "/{interview_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit my feedback (interviewers, recruiters, hiring managers)",
    description=(
        "One feedback entry per author and interview (`409 FEEDBACK_ALREADY_SUBMITTED` otherwise - use PUT to update). Only possible "
        "after the interview started (or once it is COMPLETED). Recording feedback does not change the application's stage."
    ),
    responses={**COMMON_ERRORS, 409: {"model": ErrorResponse, "description": "FEEDBACK_ALREADY_SUBMITTED"}},
)
async def submit_feedback(
    interview_id: uuid.UUID, data: FeedbackIn, user: FeedbackAuthor, svc: Svc
) -> FeedbackOut:
    return await svc.submit_feedback(user, interview_id, data)


@router.put(
    "/{interview_id}/feedback",
    response_model=FeedbackOut,
    summary="Update my feedback",
    description="Replaces the caller's own feedback entry (rating, recommendation and texts). `submitted_at` keeps the time of the first submission.",
    responses={
        **COMMON_ERRORS,
        404: {
            "model": ErrorResponse,
            "description": "No feedback submitted yet (FEEDBACK_NOT_FOUND) or interview not visible",
        },
    },
)
async def update_feedback(
    interview_id: uuid.UUID, data: FeedbackIn, user: FeedbackAuthor, svc: Svc
) -> FeedbackOut:
    return await svc.update_feedback(user, interview_id, data)


@router.get(
    "/{interview_id}/feedback",
    response_model=FeedbackSummary,
    summary="All feedback for an interview (staff only)",
    description="Internal. Candidates always receive 403. Includes the rating average and the recommendation distribution.",
)
async def list_feedback(interview_id: uuid.UUID, user: CurrentUser, svc: Svc) -> FeedbackSummary:
    return await svc.list_feedback(user, interview_id)
