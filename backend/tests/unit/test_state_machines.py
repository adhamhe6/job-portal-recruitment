"""Job and application state machines: the tables are the single source of truth, checked exhaustively."""

from __future__ import annotations

import itertools
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import InvalidStateTransitionError
from app.db.models import ApplicationStatus as A
from app.db.models import JobStatus as J
from app.services.applications import TERMINAL, TRANSITIONS, apply_transition, staff_targets
from app.services.jobs import EDITABLE_STATUSES, JOB_TRANSITIONS, is_open_for_applications


class _Session:
    """Just enough of AsyncSession for ``apply_transition`` (it only stages history rows)."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _app(status: A) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), status=status, status_changed_at=None, rejection_reason=None)


# --- applications -----------------------------------------------------------------------------------------------


def test_every_status_has_an_entry() -> None:
    assert set(TRANSITIONS) == set(A)
    assert set(JOB_TRANSITIONS) == set(J)


@pytest.mark.parametrize(("src", "dst"), list(itertools.product(A, A)))
def test_application_transition_is_accepted_iff_listed(src: A, dst: A) -> None:
    session, app = _Session(), _app(src)
    if dst in TRANSITIONS[src]:
        apply_transition(session, app, dst, actor_id=uuid.uuid4(), comment="because")  # type: ignore[arg-type]
        assert app.status == dst and app.status_changed_at is not None
        assert len(session.added) == 1
        row = session.added[0]
        assert (row.from_status, row.to_status, row.comment) == (src, dst, "because")
    else:
        with pytest.raises(InvalidStateTransitionError) as exc:
            apply_transition(session, app, dst, actor_id=uuid.uuid4())  # type: ignore[arg-type]
        assert exc.value.code == "INVALID_STATE_TRANSITION" and exc.value.status_code == 409
        assert exc.value.details == {"from": src.value, "to": dst.value, "allowed": sorted(s.value for s in TRANSITIONS[src])}
        assert app.status == src and session.added == [], "a rejected transition must not mutate anything"


def test_terminal_states_are_immutable() -> None:
    assert TERMINAL == {A.HIRED, A.REJECTED, A.WITHDRAWN}
    for status in TERMINAL:
        assert TRANSITIONS[status] == frozenset()


def test_happy_path_is_a_chain_and_hired_only_follows_offer() -> None:
    chain = [A.APPLIED, A.SCREENING, A.SHORTLISTED, A.INTERVIEW, A.OFFER, A.HIRED]
    for a, b in itertools.pairwise(chain):
        assert b in TRANSITIONS[a]
    assert [s for s, targets in TRANSITIONS.items() if A.HIRED in targets] == [A.OFFER]
    # no skipping stages
    for i, a in enumerate(chain):
        for b in chain[i + 2 :]:
            assert b not in TRANSITIONS[a], f"{a} -> {b} skips a stage"


def test_rejection_is_possible_from_every_live_state() -> None:
    for status in (A.APPLIED, A.SCREENING, A.SHORTLISTED, A.INTERVIEW, A.OFFER):
        assert A.REJECTED in TRANSITIONS[status]


def test_withdrawal_only_before_shortlisting() -> None:
    assert [s for s, targets in TRANSITIONS.items() if A.WITHDRAWN in targets] == [A.APPLIED, A.SCREENING]


def test_no_backwards_moves_and_no_self_loops() -> None:
    order = {s: i for i, s in enumerate([A.APPLIED, A.SCREENING, A.SHORTLISTED, A.INTERVIEW, A.OFFER, A.HIRED])}
    for src, targets in TRANSITIONS.items():
        assert src not in targets
        for dst in targets:
            if src in order and dst in order:
                assert order[dst] > order[src]


def test_staff_targets_never_offer_withdrawn_and_are_sorted() -> None:
    for status in A:
        targets = staff_targets(status)
        assert A.WITHDRAWN not in targets
        assert targets == sorted(targets, key=lambda s: s.value)
        assert set(targets) == set(TRANSITIONS[status]) - {A.WITHDRAWN}


def test_rejection_comment_is_kept_as_the_reason_and_truncated() -> None:
    app = _app(A.SCREENING)
    apply_transition(_Session(), app, A.REJECTED, actor_id=None, comment="x" * 800)  # type: ignore[arg-type]
    assert app.rejection_reason == "x" * 500
    other = _app(A.SCREENING)
    apply_transition(_Session(), other, A.SHORTLISTED, actor_id=None, comment="strong")  # type: ignore[arg-type]
    assert other.rejection_reason is None


# --- jobs -------------------------------------------------------------------------------------------------------------


def test_job_table_exact_shape() -> None:
    assert JOB_TRANSITIONS == {
        J.DRAFT: {J.PUBLISHED, J.ARCHIVED},
        J.PUBLISHED: {J.PAUSED, J.CLOSED},
        J.PAUSED: {J.PUBLISHED, J.CLOSED},
        J.CLOSED: {J.ARCHIVED},
        J.ARCHIVED: set(),
    }


def test_nothing_returns_to_draft_and_archived_is_terminal() -> None:
    assert all(J.DRAFT not in targets for targets in JOB_TRANSITIONS.values())
    assert JOB_TRANSITIONS[J.ARCHIVED] == frozenset()
    assert all(s not in JOB_TRANSITIONS[s] for s in J)


def test_closed_jobs_cannot_be_reopened() -> None:
    assert J.PUBLISHED not in JOB_TRANSITIONS[J.CLOSED] and J.PAUSED not in JOB_TRANSITIONS[J.CLOSED]


def test_every_state_is_reachable_from_draft_and_every_state_can_reach_archived() -> None:
    def reach(start: J) -> set[J]:
        seen, todo = {start}, [start]
        while todo:
            for nxt in JOB_TRANSITIONS[todo.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    assert reach(J.DRAFT) == set(J)
    assert all(J.ARCHIVED in reach(s) for s in J)


def test_editable_statuses_are_the_non_final_ones() -> None:
    assert EDITABLE_STATUSES == {J.DRAFT, J.PUBLISHED, J.PAUSED}


@pytest.mark.parametrize("status", list(J))
def test_only_published_jobs_accept_applications(status: J) -> None:
    job = SimpleNamespace(status=status, application_deadline=None)
    ok, reason = is_open_for_applications(job)  # type: ignore[arg-type]
    assert ok is (status == J.PUBLISHED)
    assert (reason is None) is ok


def test_deadline_is_inclusive() -> None:
    from datetime import date, timedelta

    today = date(2026, 6, 1)
    job = SimpleNamespace(status=J.PUBLISHED, application_deadline=today)
    assert is_open_for_applications(job, today)[0] is True  # type: ignore[arg-type]
    job.application_deadline = today - timedelta(days=1)
    ok, reason = is_open_for_applications(job, today)  # type: ignore[arg-type]
    assert ok is False and "deadline" in (reason or "")
    job.application_deadline = None
    assert is_open_for_applications(job, today)[0] is True  # type: ignore[arg-type]
