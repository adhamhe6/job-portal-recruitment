"""Demo-data stages that need more than a JSON body: résumé files and interviews.

Both stages go through the real HTTP API (in-process), exactly like a browser would:

* **Résumés** — a PDF is rendered from each candidate's seeded profile and uploaded to ``POST /resumes``; the real extraction and
  parsing pipeline then runs. The extracted *suggestions* are intentionally left for the candidate to review, so the demo shows the
  review flow instead of silently rewriting the profile.
* **Interviews** — scheduled through ``POST /interviews``. Interviews for applications that already moved past the interview stage
  are moved into the past (the API rightly refuses to *create* one in the past), then completed with real feedback.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import text

from app.db.database import get_engine

if TYPE_CHECKING:
    from app.scripts.seed import Seeder

logger = logging.getLogger("seed")

PAST_STAGES = {"OFFER", "HIRED"}  # an application that went on to one of these had its interview already
FEEDBACK = [
    (5, "STRONG_HIRE", "Excellent depth and communication.", "None significant.", "Move to offer."),
    (4, "HIRE", "Solid fundamentals and clear reasoning.", "Less exposure to our exact stack.", "Hire."),
    (
        3,
        "HIRE",
        "Good potential and a collaborative style.",
        "Needs more seniority for the scope.",
        "Hire at a lower level.",
    ),
]


def render_resume_pdf(cd: dict[str, Any]) -> bytes:
    """A plain, parseable single-column résumé built from the candidate's seeded profile data."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, spaceAfter=2, alignment=0)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=3)
    body = styles["BodyText"]

    def p(txt: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(txt), style)

    now_year = datetime.now(UTC).year
    flow: list[Any] = [
        p(f"{cd['first']} {cd['last']}", h1),
        p(cd["headline"]),
        p(f"{cd['email']}  |  {cd['location']}"),
    ]
    links = cd.get("links") or {}
    if links:
        flow.append(p("  |  ".join(str(v) for v in links.values())))
    flow += [p("Summary", h2), p(cd["summary"]), p("Skills", h2), p(", ".join(s[0] for s in cd["skills"]))]
    flow.append(p("Experience", h2))
    for title, company, start_ago, end_ago, desc in cd["experiences"]:
        start = now_year - int(start_ago)
        end = "Present" if end_ago is None else str(now_year - int(end_ago))
        flow += [p(f"{title} — {company}  ({start} – {end})"), p(desc), Spacer(1, 3 * mm)]
    flow.append(p("Education", h2))
    for school, _level, degree, field, start, end in cd["education"]:
        flow.append(p(f"{degree}, {school} — {field}  ({start} – {end})"))
    if cd.get("certifications"):
        flow.append(p("Certifications", h2))
        flow += [p(f"{name} — {issuer}") for name, issuer in cd["certifications"]]
    if cd.get("languages"):
        flow.append(p("Languages", h2))
        flow.append(p(", ".join(f"{n} ({lvl.title()})" for n, lvl in cd["languages"])))
    buf = io.BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{cd['first']} {cd['last']} — résumé",
        author=f"{cd['first']} {cd['last']}",
    ).build(flow)
    return buf.getvalue()


async def resumes(seeder: Seeder) -> None:
    """Upload one generated PDF résumé per candidate (primary), through the real upload + parsing pipeline."""
    for key, cand in seeder.candidates.items():
        pdf = render_resume_pdf(cand["data"])
        files = {"file": (f"{cand['data']['first']}_{cand['data']['last']}_CV.pdf", pdf, "application/pdf")}
        res = await seeder.c.post(
            "/api/v1/resumes", headers=cand["h"], files=files, data={"set_primary": "true"}
        )
        body = await seeder._ok(res, (200, 201, 202))
        cand["resume_id"] = body["id"]
        logger.info("résumé uploaded for %s", key)
    logger.info("résumés seeded: %d", len(seeder.candidates))


async def schedule_interview(seeder: Seeder, rec_app: dict[str, Any], hint: int) -> None:
    """Called right after an application reaches INTERVIEW; schedules a real interview for it."""
    job = seeder.jobs[rec_app["job"]]
    rec = seeder.recruiters[job["company"]]
    participants = [{"user_id": rec["user"]["id"], "role": "INTERVIEWER"}]
    hm = job["data"].get("hiring_manager")
    if hm:
        participants.append({"user_id": seeder.staff[hm]["id"], "role": "INTERVIEWER"})
    past = bool(set(rec_app["path"]) & PAST_STAGES)
    # Unique slots (one per interview) so no interviewer or candidate is ever double-booked.
    base = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    start = base + timedelta(days=2 + hint * 1, hours=hint % 5)
    kinds = ["PHONE_SCREEN", "TECHNICAL", "BEHAVIORAL", "PANEL"]
    body = {
        "application_id": rec_app["id"],
        "interview_type": kinds[hint % len(kinds)],
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=45 if hint % 2 else 60)).isoformat(),
        "timezone": "Europe/Berlin",
        "meeting_url": f"https://meet.example.com/talentlens-demo-{hint:02d}",
        "notes": "Demo interview created by the seed script.",
        "participants": participants,
    }
    iv = await seeder._ok(await seeder.c.post("/api/v1/interviews", headers=rec["h"], json=body), (200, 201))
    entry = {"id": iv["id"], "past": past, "app": rec_app, "company": job["company"], "n": hint}
    seeder.interviews.append(entry)


async def finish_interviews(seeder: Seeder) -> None:
    """Confirm some upcoming interviews; move finished ones into the past, complete them and add feedback."""
    now = datetime.now(UTC)
    upcoming = 0
    for entry in seeder.interviews:
        rec = seeder.recruiters[entry["company"]]
        iv_id = entry["id"]
        cand = seeder.candidates[entry["app"]["cand"]]
        if not entry["past"]:
            upcoming += 1
            if upcoming % 2 == 0:  # the candidate confirms every other upcoming interview
                await seeder._ok(
                    await seeder.c.post(f"/api/v1/interviews/{iv_id}/confirm", headers=cand["h"])
                )
            continue
        start = (now - timedelta(days=5 + entry["n"] * 2)).replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        # ``interviews.during`` is generated from start/end; the participants keep their own copy of the slot.
        async with get_engine().begin() as conn:
            await conn.execute(
                text("UPDATE interviews SET start_at=:s, end_at=:e WHERE id=CAST(:id AS uuid)"),
                {"s": start, "e": end, "id": iv_id},
            )
            await conn.execute(
                text(
                    "UPDATE interview_participants SET during=tstzrange(:s, :e, '[)') "
                    "WHERE interview_id=CAST(:id AS uuid)"
                ),
                {"s": start, "e": end, "id": iv_id},
            )
        await seeder._ok(await seeder.c.post(f"/api/v1/interviews/{iv_id}/complete", headers=rec["h"]))
        rating, recommendation, strengths, weaknesses, notes = FEEDBACK[entry["n"] % len(FEEDBACK)]
        await seeder._ok(
            await seeder.c.post(
                f"/api/v1/interviews/{iv_id}/feedback",
                headers=rec["h"],
                json={
                    "rating": rating,
                    "recommendation": recommendation,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "notes": notes,
                },
            ),
            (200, 201),
        )
    logger.info("interviews seeded: %d", len(seeder.interviews))
