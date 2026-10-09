"""The demo seed drives the real API; this keeps it from rotting and checks what a demo user will actually see."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.scripts import seed
from app.scripts import seed_data as D

pytestmark = pytest.mark.usefixtures("db")


async def test_the_demo_seed_builds_a_coherent_dataset(session) -> None:  # type: ignore[no-untyped-def]
    assert await seed.run(reset=True) is True

    async def scalar(sql: str) -> int:
        return (await session.execute(text(sql))).scalar_one()

    assert await scalar("SELECT count(*) FROM candidate_profiles") == len(D.CANDIDATES)
    assert await scalar("SELECT count(*) FROM jobs") == len(D.JOBS)
    assert await scalar("SELECT count(*) FROM applications") == len(D.APPLICATIONS)

    # every candidate has a primary résumé that went through the real extraction/parsing pipeline
    assert await scalar("SELECT count(*) FROM resumes WHERE status = 'PROCESSED'") == len(D.CANDIDATES)
    assert await scalar("SELECT count(*) FROM resume_processing_results WHERE status = 'COMPLETED'") == len(
        D.CANDIDATES
    )

    # interviews: a mix of upcoming (scheduled/confirmed) and finished ones, and the finished ones carry feedback
    statuses = {r[0] for r in (await session.execute(text("SELECT DISTINCT status FROM interviews"))).all()}
    assert {"COMPLETED", "CONFIRMED"} <= statuses
    assert await scalar("SELECT count(*) FROM interview_feedback") == await scalar(
        "SELECT count(*) FROM interviews WHERE status = 'COMPLETED'"
    )

    # persisted matches exist for the published jobs, and nothing was left half-processed
    assert await scalar("SELECT count(*) FROM candidate_job_matches") > 0
    assert await scalar("SELECT count(*) FROM background_tasks WHERE status IN ('PENDING','RUNNING')") == 0

    # a second run is a no-op rather than duplicating the demo company data
    assert await seed.run(reset=False) is False
