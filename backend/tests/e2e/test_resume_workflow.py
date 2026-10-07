"""Résumé workflow: upload → processed → suggestions → review → apply → profile → embeddings → matching."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import (
    CandidateProfile,
    CandidateSkill,
    Notification,
    NotificationType,
    Resume,
    ResumeDocument,
    ResumeProcessingResult,
)
from app.resume.storage import get_storage
from tests import fixtures_resumes as fx
from tests.helpers import create_job, register_candidate, register_employer
from tests.resume_helpers import DOCX, upload, upload_ok

pytestmark = pytest.mark.e2e


async def my_profile(client, cand):
    r = await client.get("/api/v1/candidates/me", headers=cand["h"])
    assert r.status_code == 200, r.text
    return r.json()


async def extracted(client, cand, rid):
    r = await client.get(f"/api/v1/resumes/{rid}/extracted", headers=cand["h"])
    assert r.status_code == 200, r.text
    return r.json()


async def test_upload_is_processed_end_to_end_and_reports_status(client, session):
    cand = await register_candidate(client)
    r = await upload(client, cand, fx.backend_pdf(), "Jane CV.pdf")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PROCESSED" and body["is_primary"] is True and body["duplicate"] is False
    assert body["original_filename"] == "Jane CV.pdf" and body["content_type"] == "application/pdf"
    p = body["processing"]
    assert p["task_status"] == "COMPLETED" and p["progress"] == 100 and p["stage"] == "done"
    assert (
        p["parser_version"] == "v1"
        and p["page_count"] == 1
        and p["text_char_count"] > 500
        and p["was_truncated"] is False
    )
    assert p["has_embedding"] is True and p["embedding_model"] and p["embedding_version"] == "v1"
    assert p["duration_ms"] is not None and p["error_code"] is None and p["attempts"] == 1
    assert body["task_id"] == p["task_id"]

    # the task endpoint tells the same story
    t = await client.get(f"/api/v1/tasks/{body['task_id']}", headers=cand["h"])
    assert t.status_code == 200
    tj = t.json()
    assert tj["status"] == "COMPLETED" and tj["progress"] == 100 and tj["type"] == "PROCESS_RESUME"
    assert (
        tj["result"]["status"] == "PROCESSED"
        and tj["result"]["skills_found"] >= 10
        and tj["result"]["embedding"] is True
    )

    # GET /resumes/{id} and the list agree; the response never leaks storage details
    g = await client.get(f"/api/v1/resumes/{body['id']}", headers=cand["h"])
    assert g.status_code == 200 and g.json()["status"] == "PROCESSED"
    lst = await client.get("/api/v1/resumes", headers=cand["h"])
    assert lst.status_code == 200 and lst.json()["total"] == 1 and lst.json()["items"][0]["id"] == body["id"]
    for text in (r.text, g.text, lst.text):
        assert "storage" not in text and "resumes/" not in text and ".bin" not in text

    # database state
    resume = await session.get(Resume, uuid.UUID(body["id"]))
    assert resume is not None and resume.status.value == "PROCESSED"
    result = (
        await session.execute(
            select(ResumeProcessingResult).where(ResumeProcessingResult.resume_id == resume.id)
        )
    ).scalar_one()
    assert (
        result.status.value == "COMPLETED" and result.embedding is not None and len(result.embedding) == 256
    )
    assert (
        "Jane Doe" in (result.extracted_text or "")
        and result.parsed_data["contact"]["email"] == "jane.doe@example.com"
    )

    # in-app notification, exactly once
    n = await client.get("/api/v1/notifications", headers=cand["h"])
    types = [x["type"] for x in n.json()["items"]]
    assert types.count("RESUME_PROCESSED") == 1


async def test_skills_are_only_suggested_and_the_candidate_index_is_built(client, session):
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, fx.backend_pdf())
    profile = await my_profile(client, cand)
    by_name = {s["skill"]["name"]: s for s in profile["skills"]}
    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes"} <= set(by_name)
    assert all(
        s["source"] == "RESUME" and s["status"] == "SUGGESTED" and 0 < s["confidence"] <= 1
        for s in profile["skills"]
    )
    assert by_name["Python"]["confidence"] > by_name["Celery"]["confidence"]  # listed beats prose-only
    # nothing else was created automatically for a registered candidate
    assert (
        profile["experiences"] == []
        and profile["educations"] == []
        and profile["certifications"] == []
        and profile["languages"] == []
    )
    assert profile["headline"] is None and profile["summary"] is None
    assert profile["primary_resume"]["id"] == body["id"]
    # the candidate's search index + embedding were refreshed from the résumé text
    cp = await session.get(CandidateProfile, uuid.UUID(profile["id"]))
    assert (
        cp is not None
        and cp.embedding is not None
        and "Backend engineer with 8+ years" in (cp.search_text or "")
    )
    assert "Python" in (cp.skills_text or "")


async def test_review_apply_and_match_scores_change(client, session):
    rec = await register_employer(client, "Matchmakers Inc")
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)

    def score_for(items, cid):
        return next((i for i in items if i["candidate_id"] == cid), None)

    before = await client.get(f"/api/v1/matches/jobs/{job['id']}/candidates", headers=rec["h"])
    assert (
        before.status_code == 200 and score_for(before.json()["items"], cand["candidate_id"]) is None
    )  # no data → not in the pool

    body = await upload_ok(client, cand, fx.backend_pdf())
    after_upload = await client.get(f"/api/v1/matches/jobs/{job['id']}/candidates", headers=rec["h"])
    row = score_for(after_upload.json()["items"], cand["candidate_id"])
    assert row is not None, "the processed résumé put the candidate into the job's ranking"
    s1 = row["overall_score"]
    assert (
        s1 > 0.3 and row["breakdown"]["required_skills"] > 0
    )  # SUGGESTED skills already count (non-rejected)

    ex = await extracted(client, cand, body["id"])
    assert ex["parser_version"] == "v1" and ex["contact"]["email"] == "jane.doe@example.com"
    assert (
        ex["years_of_experience"]["basis"] == "employment_history" and ex["years_of_experience"]["value"] > 10
    )
    assert [e["title"] for e in ex["experiences"]] == [
        "Senior Backend Engineer",
        "Backend Developer",
        "Software Engineer",
    ]
    assert all(e["already_on_profile"] is False for e in ex["experiences"])
    sk = {s["name"]: s for s in ex["skills"]}
    assert (
        sk["Python"]["skill_id"]
        and sk["Python"]["status"] == "SUGGESTED"
        and sk["Python"]["already_on_profile"] is False
    )
    assert ex["educations"][0]["degree_level"] == "BACHELOR"

    # apply: confirm all skills, copy the work history, education, certifications, languages and profile fields
    ap = await client.post(
        f"/api/v1/resumes/{body['id']}/extracted/apply",
        headers=cand["h"],
        json={
            "skills": "all",
            "experiences": "all",
            "educations": "all",
            "certifications": "all",
            "languages": "all",
            "fields": ["summary", "headline", "location", "years_experience", "linkedin_url", "github_url"],
        },
    )
    assert ap.status_code == 200, ap.text
    res = ap.json()
    assert (
        res["applied"]["skills"] >= 10
        and res["applied"]["experiences"] == 3
        and res["applied"]["educations"] == 1
    )
    assert res["applied"]["certifications"] >= 2 and res["applied"]["languages"] == 3
    assert set(res["fields_applied"]) == {
        "summary",
        "headline",
        "location",
        "years_experience",
        "linkedin_url",
        "github_url",
    }

    profile = await my_profile(client, cand)
    assert profile["headline"] == "Senior Backend Engineer" and profile["location"] == "Berlin, Germany"
    assert (
        profile["summary"].startswith("Backend engineer with 8+ years")
        and float(profile["years_experience"]) > 10
    )
    assert profile["linkedin_url"] == "https://www.linkedin.com/in/janedoe"
    assert all(s["status"] == "CONFIRMED" and s["source"] == "RESUME" for s in profile["skills"])
    assert len(profile["experiences"]) == 3 and all(e["source"] == "RESUME" for e in profile["experiences"])
    assert profile["educations"][0]["source"] == "RESUME" and {
        lang["language"] for lang in profile["languages"]
    } == {"English", "German", "French"}
    assert any(c["name"].startswith("AWS Certified") for c in profile["certifications"])
    assert next(i for i in profile["completion"]["items"] if i["key"] == "resume")["done"] is True

    # the review view now reflects the profile
    ex2 = await extracted(client, cand, body["id"])
    assert all(e["already_on_profile"] for e in ex2["experiences"]) and all(
        s["already_on_profile"] for s in ex2["skills"]
    )

    # the index, the embedding and the match all moved
    cp = await session.get(CandidateProfile, uuid.UUID(profile["id"]))
    await session.refresh(cp)
    assert cp.embedding is not None
    after_apply = await client.get(f"/api/v1/matches/jobs/{job['id']}/candidates", headers=rec["h"])
    row2 = score_for(after_apply.json()["items"], cand["candidate_id"])
    assert row2 is not None
    assert row2["overall_score"] != s1, "applying experience, education and years changed the match"
    assert row2["overall_score"] > s1 and row2["breakdown"]["experience"] is not None


async def test_apply_never_overwrites_user_data_and_skips_duplicates(client):
    cand = await register_candidate(client)
    h = cand["h"]
    mine = await client.patch(
        "/api/v1/candidates/me",
        headers=h,
        json={"headline": "My own headline", "location": "Hamburg, Germany"},
    )
    assert mine.status_code == 200
    await client.post("/api/v1/candidates/me/skills", headers=h, json={"name": "Python"})  # user-confirmed
    body = await upload_ok(client, cand, fx.backend_pdf())

    # a USER/CONFIRMED skill is not touched by the suggestions
    skills = {s["skill"]["name"]: s for s in (await my_profile(client, cand))["skills"]}
    assert skills["Python"]["source"] == "USER" and skills["Python"]["status"] == "CONFIRMED"
    assert skills["FastAPI"]["source"] == "RESUME"

    req = {"fields": ["headline", "location", "summary"], "experiences": [0], "skills": [0, 1]}
    r1 = (await client.post(f"/api/v1/resumes/{body['id']}/extracted/apply", headers=h, json=req)).json()
    assert r1["fields_applied"] == ["summary"]  # empty field filled
    skipped = {(s["section"], s["reason"]) for s in r1["skipped"]}
    assert ("profile.headline", "FIELD_NOT_EMPTY") in skipped and (
        "profile.location",
        "FIELD_NOT_EMPTY",
    ) in skipped
    prof = await my_profile(client, cand)
    assert prof["headline"] == "My own headline" and prof["location"] == "Hamburg, Germany"

    # applying the same selection again creates nothing new
    r2 = (await client.post(f"/api/v1/resumes/{body['id']}/extracted/apply", headers=h, json=req)).json()
    assert r2["applied"].get("experiences", 0) == 0
    assert any(s["section"] == "experiences" and s["reason"] == "ALREADY_ON_PROFILE" for s in r2["skipped"])
    assert len((await my_profile(client, cand))["experiences"]) == 1

    # overwrite has to be requested explicitly, per field
    r3 = (
        await client.post(
            f"/api/v1/resumes/{body['id']}/extracted/apply",
            headers=h,
            json={"fields": ["headline", "location"], "overwrite": ["headline"]},
        )
    ).json()
    assert r3["fields_applied"] == ["headline"]
    prof = await my_profile(client, cand)
    assert prof["headline"] == "Senior Backend Engineer" and prof["location"] == "Hamburg, Germany"
    bad = await client.post(
        f"/api/v1/resumes/{body['id']}/extracted/apply",
        headers=h,
        json={"fields": ["headline"], "overwrite": ["location"]},
    )
    assert bad.status_code == 422


async def test_corrections_are_stored_as_suggestions_and_never_touch_the_raw_text(client, session):
    cand = await register_candidate(client)
    h = cand["h"]
    body = await upload_ok(client, cand, fx.backend_pdf())
    rid = body["id"]
    raw_before = (
        await session.execute(
            select(ResumeProcessingResult.extracted_text).where(
                ResumeProcessingResult.resume_id == uuid.UUID(rid)
            )
        )
    ).scalar_one()
    ex = await extracted(client, cand, rid)
    assert ex["has_corrections"] is False
    celery = next(s for s in ex["skills"] if s["name"] == "Celery")
    exp0 = ex["experiences"][0]

    patch = await client.patch(
        f"/api/v1/resumes/{rid}/extracted",
        headers=h,
        json={
            "summary": "Corrected summary written by the candidate.",
            "skills": [{"index": celery["index"], "remove": True}],
            "experiences": [
                {"index": exp0["index"], "title": "Staff Backend Engineer", "start_date": "2020-02-01"}
            ],
            "languages": [{"index": 2, "proficiency": "CONVERSATIONAL"}],
            "contact": {"phone": "+49 30 1234567"},
        },
    )
    assert patch.status_code == 200, patch.text
    pj = patch.json()
    assert pj["has_corrections"] is True and pj["summary"] == "Corrected summary written by the candidate."
    assert all(s["name"] != "Celery" for s in pj["skills"])  # removed suggestions are hidden...
    assert {s["index"] for s in pj["skills"]} == {s["index"] for s in ex["skills"]} - {
        celery["index"]
    }  # ...and indices stay stable
    e0 = next(e for e in pj["experiences"] if e["index"] == exp0["index"])
    assert (
        e0["title"] == "Staff Backend Engineer"
        and e0["start_date"] == "2020-02-01"
        and e0["corrected"] is True
    )
    assert next(e for e in pj["experiences"] if e["index"] != exp0["index"])["corrected"] is False
    assert (
        pj["contact"]["phone"] == "+49 30 1234567" and pj["languages"][2]["proficiency"] == "CONVERSATIONAL"
    )

    session.expire_all()
    stored = (
        await session.execute(
            select(ResumeProcessingResult).where(ResumeProcessingResult.resume_id == uuid.UUID(rid))
        )
    ).scalar_one()
    assert stored.extracted_text == raw_before  # the raw text is untouched
    assert stored.parsed_data["has_corrections"] is True

    # corrected values are what gets applied; removed suggestions are skipped by "all"
    ap = await client.post(
        f"/api/v1/resumes/{rid}/extracted/apply",
        headers=h,
        json={"skills": "all", "experiences": [exp0["index"]], "languages": "all"},
    )
    assert ap.status_code == 200
    prof = await my_profile(client, cand)
    assert "Celery" not in {s["skill"]["name"] for s in prof["skills"] if s["status"] == "CONFIRMED"}
    assert (
        prof["experiences"][0]["title"] == "Staff Backend Engineer"
        and prof["experiences"][0]["start_date"] == "2020-02-01"
    )
    assert {lang["language"]: lang["proficiency"] for lang in prof["languages"]}["French"] == "CONVERSATIONAL"

    # validation of corrections
    assert (
        await client.patch(
            f"/api/v1/resumes/{rid}/extracted", headers=h, json={"skills": [{"index": 9999, "remove": True}]}
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/resumes/{rid}/extracted",
            headers=h,
            json={"experiences": [{"index": 0, "start_date": "2021-01-01", "end_date": "2020-01-01"}]},
        )
    ).status_code == 422
    assert (
        await client.patch(f"/api/v1/resumes/{rid}/extracted", headers=h, json={"unknown": 1})
    ).status_code == 422


async def test_experience_missing_required_fields_is_reported_not_guessed(client):
    cand = await register_candidate(client)
    h = cand["h"]
    text = "Sam Rivera\nsam@x.example\n\nExperience\nBarista\nCorner Cafe\n• Served customers every day\n\nSkills\nCustomer Support, Negotiation, Leadership\n"
    body = await upload_ok(client, cand, fx.make_pdf(text))
    ex = await extracted(client, cand, body["id"])
    assert len(ex["experiences"]) == 1
    e = ex["experiences"][0]
    assert e["start_date"] is None and e["missing_for_apply"] == ["start_date"] and e["confidence"] < 0.5
    ap = await client.post(
        f"/api/v1/resumes/{body['id']}/extracted/apply", headers=h, json={"experiences": "all"}
    )
    assert ap.json()["applied"] == {} and ap.json()["skipped"][0]["reason"] == "MISSING_START_DATE"
    # the candidate supplies the missing field, then applies
    await client.patch(
        f"/api/v1/resumes/{body['id']}/extracted",
        headers=h,
        json={"experiences": [{"index": 0, "start_date": "2019-05-01", "end_date": "2021-05-01"}]},
    )
    ap2 = await client.post(
        f"/api/v1/resumes/{body['id']}/extracted/apply", headers=h, json={"experiences": "all"}
    )
    assert ap2.json()["applied"] == {"experiences": 1}


async def test_docx_with_tables_flows_through_the_same_pipeline(client):
    cand = await register_candidate(client)
    body = await upload_ok(client, cand, fx.frontend_docx(tables=True), "alex.docx", content_type=DOCX)
    assert (
        body["status"] == "PROCESSED"
        and body["content_type"] == DOCX
        and body["processing"]["page_count"] is None
    )
    ex = await extracted(client, cand, body["id"])
    names = {s["name"] for s in ex["skills"]}
    assert {"React", "TypeScript", "Next.js", "Tailwind CSS"} <= names and "Python" not in names
    assert ex["contact"]["name"] == "Alex Kim"


async def test_reprocessing_is_idempotent(client, session):
    cand = await register_candidate(client)
    h = cand["h"]
    body = await upload_ok(client, cand, fx.backend_pdf())
    rid = body["id"]
    # the candidate rejects a suggestion and confirms another
    prof = await my_profile(client, cand)
    sk = {s["skill"]["name"]: s for s in prof["skills"]}
    await client.delete(
        f"/api/v1/candidates/me/skills/{sk['Celery']['id']}", headers=h
    )  # RESUME source → REJECTED, remembered
    await client.patch(
        f"/api/v1/candidates/me/skills/{sk['Python']['id']}", headers=h, json={"status": "CONFIRMED"}
    )
    n_before = len(prof["skills"])
    first = await extracted(client, cand, rid)

    r = await client.post(f"/api/v1/resumes/{rid}/process", headers=h)
    assert r.status_code == 202 and r.json()["task_id"]
    again = await client.get(f"/api/v1/resumes/{rid}", headers=h)
    assert again.json()["status"] == "PROCESSED" and again.json()["processing"]["attempts"] == 2
    assert again.json()["task_id"] == r.json()["task_id"]

    prof2 = await my_profile(client, cand)
    sk2 = {s["skill"]["name"]: s for s in prof2["skills"]}
    assert len(prof2["skills"]) == n_before  # no duplicate suggestions
    assert sk2["Celery"]["status"] == "REJECTED"  # a dismissed suggestion is not resurrected
    assert sk2["Python"]["status"] == "CONFIRMED"  # nor is a confirmed one downgraded
    count = await session.scalar(
        select(func.count())
        .select_from(CandidateSkill)
        .where(CandidateSkill.candidate_id == uuid.UUID(prof["id"]))
    )
    assert count == n_before
    second = await extracted(client, cand, rid)
    assert [s["name"] for s in second["skills"]] == [s["name"] for s in first["skills"]]
    docs = await session.scalar(
        select(func.count()).select_from(ResumeDocument).where(ResumeDocument.resume_id == uuid.UUID(rid))
    )
    results = await session.scalar(
        select(func.count())
        .select_from(ResumeProcessingResult)
        .where(ResumeProcessingResult.resume_id == uuid.UUID(rid))
    )
    assert docs == 1 and results == 1
    # one notification for the same résumé document, not one per run
    notes = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.resume_id == uuid.UUID(rid), Notification.type == NotificationType.RESUME_PROCESSED
        )
    )
    assert notes == 1


async def test_identical_upload_returns_the_existing_resume(client, session):
    cand = await register_candidate(client)
    pdf = fx.backend_pdf()
    first = await upload(client, cand, pdf, "one.pdf")
    second = await upload(client, cand, pdf, "renamed-copy.pdf")
    assert first.status_code == 202 and second.status_code == 200
    assert (
        second.json()["id"] == first.json()["id"]
        and second.json()["duplicate"] is True
        and second.json()["original_filename"] == "one.pdf"
    )
    n = await session.scalar(select(func.count()).select_from(Resume))
    assert n == 1
    # a different file is a new résumé; another candidate may upload the same bytes freely
    third = await upload(client, cand, fx.frontend_pdf(), "alex.pdf")
    assert third.status_code == 202 and third.json()["id"] != first.json()["id"]
    other = await register_candidate(client)
    assert (await upload(client, other, pdf, "mine.pdf")).status_code == 202


async def test_primary_selection_and_listing(client, session):
    cand = await register_candidate(client)
    a = await upload_ok(client, cand, fx.backend_pdf(), "a.pdf")
    b = await upload_ok(client, cand, fx.frontend_pdf(), "b.pdf")
    c = await upload_ok(client, cand, fx.nurse_pdf(), "c.pdf", set_primary=False)
    assert (a["is_primary"], b["is_primary"], c["is_primary"]) == (True, True, False)
    lst = (await client.get("/api/v1/resumes", headers=cand["h"])).json()
    assert (
        lst["total"] == 3
        and lst["items"][0]["id"] == b["id"]
        and [i["is_primary"] for i in lst["items"]].count(True) == 1
    )

    p = await client.post(f"/api/v1/resumes/{c['id']}/primary", headers=cand["h"])
    assert p.status_code == 200 and p.json()["is_primary"] is True
    primaries = [
        i for i in (await client.get("/api/v1/resumes", headers=cand["h"])).json()["items"] if i["is_primary"]
    ]
    assert [i["id"] for i in primaries] == [c["id"]]
    # the profile's primary résumé follows, and so does the matching text (nurse content now drives the index)
    assert (await my_profile(client, cand))["primary_resume"]["id"] == c["id"]
    cp = await session.get(CandidateProfile, uuid.UUID(c["candidate_id"]))
    await session.refresh(cp)
    assert "Registered Nurse" in (cp.search_text or "") or "nurse" in (cp.search_text or "").lower()

    # the first résumé of a candidate is primary even when set_primary=false
    fresh = await register_candidate(client)
    only = await upload_ok(client, fresh, fx.nurse_pdf(), set_primary=False)
    assert only["is_primary"] is True


async def test_delete_promotes_next_primary_removes_file_and_refuses_when_in_use(client, session):
    rec = await register_employer(client)
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    h = cand["h"]
    a = await upload_ok(client, cand, fx.backend_pdf(), "a.pdf")
    b = await upload_ok(client, cand, fx.frontend_pdf(), "b.pdf")  # primary
    c = await upload_ok(client, cand, fx.nurse_pdf(), "c.pdf", set_primary=False)

    keys = {
        r: (
            await session.execute(
                select(ResumeDocument.storage_key).where(ResumeDocument.resume_id == uuid.UUID(r))
            )
        ).scalar_one()
        for r in (a["id"], b["id"], c["id"])
    }
    storage = get_storage()
    assert all([await storage.exists(k) for k in keys.values()])

    # delete the primary: the newest remaining résumé (c) becomes primary, the file is gone
    d = await client.delete(f"/api/v1/resumes/{b['id']}", headers=h)
    assert d.status_code == 204
    assert not await storage.exists(keys[b["id"]]) and await storage.exists(keys[a["id"]])
    assert (await client.get(f"/api/v1/resumes/{b['id']}", headers=h)).status_code == 404
    items = (await client.get("/api/v1/resumes", headers=h)).json()["items"]
    assert [(i["id"], i["is_primary"]) for i in items if i["is_primary"]] == [(c["id"], True)]

    # attach a résumé to an application → cannot be deleted (409), nothing is lost
    await client.patch("/api/v1/candidates/me", headers=h, json={"headline": "x"})
    app = await client.post(
        "/api/v1/applications", headers=h, json={"job_id": job["id"], "resume_id": a["id"]}
    )
    assert app.status_code == 201, app.text
    blocked = await client.delete(f"/api/v1/resumes/{a['id']}", headers=h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "RESUME_IN_USE"
    assert (
        await storage.exists(keys[a["id"]])
        and (await client.get(f"/api/v1/resumes/{a['id']}", headers=h)).status_code == 200
    )

    # deleting the last primary candidate leaves a consistent state
    assert (await client.delete(f"/api/v1/resumes/{c['id']}", headers=h)).status_code == 204
    left = (await client.get("/api/v1/resumes", headers=h)).json()["items"]
    assert [(i["id"], i["is_primary"]) for i in left] == [(a["id"], True)]
    assert (await client.delete(f"/api/v1/resumes/{b['id']}", headers=h)).status_code == 404  # already gone


async def test_download_headers_and_content(client):
    cand = await register_candidate(client)
    pdf = fx.backend_pdf()
    body = await upload_ok(client, cand, pdf, "../../Jané's CV: draft.pdf")
    assert (
        body["original_filename"] == "Jané's CV_ draft.pdf"
    )  # path components and reserved characters stripped
    r = await client.get(f"/api/v1/resumes/{body['id']}/file", headers=cand["h"])
    assert r.status_code == 200 and r.content == pdf
    assert r.headers["content-type"] == "application/pdf"
    cd = r.headers["content-disposition"]
    assert (
        cd.startswith("attachment;")
        and "filename*=UTF-8''Jan%C3%A9%27s%20CV_%20draft.pdf" in cd
        and "\r" not in cd
        and "\n" not in cd
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    assert int(r.headers["content-length"]) == len(pdf)

    inline = await client.get(
        f"/api/v1/resumes/{body['id']}/file", headers=cand["h"], params={"inline": "true"}
    )
    assert (
        inline.headers["content-disposition"].startswith("inline;")
        and inline.headers["content-type"] == "application/pdf"
    )

    docx = fx.frontend_docx()
    drow = await upload_ok(client, cand, docx, "alex.docx", content_type=DOCX)
    dr = await client.get(f"/api/v1/resumes/{drow['id']}/file", headers=cand["h"], params={"inline": "true"})
    assert dr.status_code == 200 and dr.content == docx and dr.headers["content-type"] == DOCX
    assert dr.headers["content-disposition"].startswith("attachment;")  # only PDFs are previewed inline
    assert (await client.get(f"/api/v1/resumes/{body['id']}/file")).status_code == 401


async def test_api_uses_content_type_by_sniffing_not_the_client(client):
    cand = await register_candidate(client)
    # a PDF uploaded with no / generic declared type is accepted and stored as application/pdf
    a = await upload(client, cand, fx.backend_pdf(), "a.pdf", content_type="application/octet-stream")
    b = await upload(client, cand, fx.frontend_pdf(), "b.pdf", content_type=None)
    assert a.status_code == 202 and a.json()["content_type"] == "application/pdf"
    assert b.status_code == 202 and b.json()["content_type"] == "application/pdf"


async def test_concurrent_uploads_keep_one_copy_of_identical_files_and_one_primary(client, session):
    import asyncio

    cand = await register_candidate(client)
    pdf = fx.backend_pdf()
    same = await asyncio.gather(*[upload(client, cand, pdf, f"copy{i}.pdf") for i in range(4)])
    assert all(r.status_code in (200, 202) for r in same), [r.text for r in same]
    assert len({r.json()["id"] for r in same}) == 1
    assert await session.scalar(select(func.count()).select_from(Resume)) == 1

    others = [fx.frontend_pdf(), fx.nurse_pdf(), fx.make_pdf("Pat Lee\npat@x.example\nSkills\nPython, Docker, SQL, Redis\n")]
    mixed = await asyncio.gather(*[upload(client, cand, data, f"other{i}.pdf") for i, data in enumerate(others)])
    assert all(r.status_code == 202 for r in mixed), [r.text for r in mixed]
    lst = (await client.get("/api/v1/resumes", headers=cand["h"])).json()
    assert lst["total"] == 4 and [i["is_primary"] for i in lst["items"]].count(True) == 1  # the partial unique index never fired
