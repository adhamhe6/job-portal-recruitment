"""Recruiter bulk import: validation per file, duplicates, failures, imported candidates, tenancy, idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.cache.redis_cache import get_cache
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.db.database import get_sessionmaker
from app.db.models import (
    BulkImportItem,
    CandidateProfile,
    CandidateSource,
    Experience,
    ImportItemStatus,
    Notification,
    NotificationType,
    Resume,
    TaskType,
)
from app.resume.storage import get_storage
from app.services.tasks import TaskStore
from app.workers.tasks import TaskContext
from tests import fixtures_resumes as fx
from tests.helpers import add_staff, create_job, register_candidate, register_employer
from tests.resume_helpers import (
    DOCX,
    PDF,
    bulk_upload,
    clean_storage,  # noqa: F401  (fixture)
    task_of,
)

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("clean_storage")]

BACKEND = ("jane.pdf", fx.backend_pdf(), PDF)
FRONTEND = ("alex.docx", fx.frontend_docx(), DOCX)
NURSE = ("maria.pdf", fx.nurse_pdf(), PDF)
NO_IDENTITY = (
    "anon.pdf",
    fx.make_pdf(
        "Skills\nPython, Docker, SQL\n\nExperience\nEngineer, Acme   2020 - 2022\n• Built things for customers all day long"
    ),
    PDF,
)
SAME_PERSON_DIFFERENT_FILE = ("jane-v2.pdf", fx.make_pdf(fx.BACKEND_TEXT + "\nCertifications\nCISSP"), PDF)


def storage_files() -> list[str]:
    root = get_storage().root  # type: ignore[attr-defined]
    return sorted(str(p) for p in root.rglob("*") if p.is_file())


async def batch_of(client, rec, batch_id):
    r = await client.get(f"/api/v1/resumes/bulk-imports/{batch_id}", headers=rec["h"])
    assert r.status_code == 200, r.text
    return r.json()


def by_name(batch):
    return {i["filename"]: i for i in batch["items"]}


async def test_bulk_import_end_to_end(client, session):
    rec = await register_employer(client, "Talent Hunters")
    job = await create_job(client, rec, publish=True)
    files = [
        BACKEND,
        FRONTEND,
        ("jane-copy.pdf", BACKEND[1], PDF),  # identical bytes
        SAME_PERSON_DIFFERENT_FILE,  # same e-mail, different file
        ("corrupt.pdf", fx.malformed_pdf(), PDF),
        ("scan.pdf", fx.scanned_pdf(), PDF),
        NO_IDENTITY,
        ("virus.pdf", fx.EXE, PDF),  # rejected at upload
        ("old.doc", fx.OLE_DOC, "application/msword"),
        ("empty.pdf", b"", PDF),
    ]
    r = await bulk_upload(client, rec, files)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] == 7 and body["task_id"] and body["message"] is None
    rejected = {x["filename"]: x for x in body["rejected"]}
    assert set(rejected) == {"virus.pdf", "old.doc", "empty.pdf"}
    assert (
        rejected["virus.pdf"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
        and rejected["empty.pdf"]["code"] == "EMPTY_FILE"
    )
    assert all(x["reason"] for x in body["rejected"])

    task = await task_of(client, rec, body["task_id"])
    assert (
        task["status"] == "COMPLETED"
        and task["progress"] == 100
        and task["stage"] == "done"
        and task["type"] == "BULK_RESUME_IMPORT"
    )
    assert task["result"] == {
        "batch_id": body["batch_id"],
        "created": 2,
        "duplicates": 2,
        "failed": 3,
        "total": 7,
    }

    batch = await batch_of(client, rec, body["batch_id"])
    assert batch["status"] == "COMPLETED" and batch["total_files"] == 7 and batch["finished_at"]
    assert batch["counts"] == {"pending": 0, "created": 2, "duplicate": 2, "failed": 3}
    items = by_name(batch)
    assert items["jane.pdf"]["status"] == "CREATED" and items["alex.docx"]["status"] == "CREATED"
    assert (
        items["jane-copy.pdf"]["status"] == "DUPLICATE"
        and items["jane-copy.pdf"]["error_code"] == "DUPLICATE_FILE"
    )
    assert items["jane-copy.pdf"]["candidate_id"] == items["jane.pdf"]["candidate_id"]
    assert (
        items["jane-v2.pdf"]["status"] == "DUPLICATE"
        and items["jane-v2.pdf"]["error_code"] == "DUPLICATE_CANDIDATE"
    )
    assert items["jane-v2.pdf"]["candidate_id"] == items["jane.pdf"]["candidate_id"]
    assert (
        items["corrupt.pdf"]["error_code"] == "MALFORMED_DOCUMENT"
        and items["scan.pdf"]["error_code"] == "NO_TEXT_EXTRACTED"
    )
    assert (
        items["anon.pdf"]["status"] == "FAILED"
        and items["anon.pdf"]["error_code"] == "NO_CANDIDATE_IDENTIFIED"
    )
    assert "OCR is not enabled" in items["scan.pdf"]["error_message"]
    assert "storage" not in str(batch) and "sha256" not in str(batch)

    # only the created items keep a stored file
    assert len(storage_files()) == 2
    # in-app notification for the importer
    note = (await client.get("/api/v1/notifications", headers=rec["h"])).json()["items"]
    done = [n for n in note if n["type"] == "BULK_IMPORT_COMPLETED"]
    assert len(done) == 1 and "2 candidates imported" in done[0]["message"]

    # the imported candidates are company-private IMPORTED profiles with data from the résumé
    jane_id, alex_id = items["jane.pdf"]["candidate_id"], items["alex.docx"]["candidate_id"]
    jane = (await client.get(f"/api/v1/candidates/{jane_id}", headers=rec["h"])).json()
    assert jane["source"] == "IMPORTED" and jane["access"] == "FULL" and jane["display_name"] == "Jane Doe"
    assert jane["email"] == "jane.doe@example.com" and jane["phone"] == "+49 151 2345 6789"
    assert (
        jane["headline"] == "Senior Backend Engineer"
        and jane["location"] == "Berlin, Germany"
        and float(jane["years_experience"]) > 10
    )
    assert {s["skill"]["name"] for s in jane["skills"]} >= {"Python", "FastAPI", "PostgreSQL", "Docker"}
    assert all(s["source"] == "RESUME" and s["status"] == "SUGGESTED" for s in jane["skills"])
    assert len(jane["experiences"]) == 3 and all(e["source"] == "RESUME" for e in jane["experiences"])
    assert jane["educations"][0]["degree_level"] == "BACHELOR" and len(jane["languages"]) == 3
    assert (
        len(jane["resumes"]) == 1
        and jane["resumes"][0]["is_primary"]
        and jane["resumes"][0]["status"] == "PROCESSED"
    )

    cp = await session.get(CandidateProfile, uuid.UUID(jane_id))
    assert (
        cp.source == CandidateSource.IMPORTED
        and cp.user_id is None
        and str(cp.sourced_by_company_id) == rec["company_id"]
    )
    assert (
        cp.contact_email == "jane.doe@example.com" and cp.embedding is not None and cp.is_searchable is False
    )

    # ... visible in recruiter candidate search, by name, skill and filters
    s1 = await client.get("/api/v1/search/candidates", headers=rec["h"], params={"q": "Jane"})
    assert [i["id"] for i in s1.json()["items"]] == [jane_id] and s1.json()["items"][0][
        "source"
    ] == "IMPORTED"
    s2 = await client.get("/api/v1/search/candidates", headers=rec["h"], params={"skill": "TypeScript"})
    assert [i["id"] for i in s2.json()["items"]] == [alex_id]
    s3 = await client.get("/api/v1/search/candidates", headers=rec["h"], params={"min_experience": 10})
    assert jane_id in {i["id"] for i in s3.json()["items"]}

    # ... and ranked for the company's published job without any extra step
    ranked = await client.get(f"/api/v1/matches/jobs/{job['id']}/candidates", headers=rec["h"])
    scores = {i["candidate_id"]: i["overall_score"] for i in ranked.json()["items"]}
    assert (
        jane_id in scores and alex_id in scores and scores[jane_id] > scores[alex_id]
    )  # backend engineer beats the frontend one

    # the résumé of an imported candidate can be downloaded / reviewed by the sourcing company
    rid = jane["resumes"][0]["id"]
    assert (await client.get(f"/api/v1/resumes/{rid}/file", headers=rec["h"])).content == BACKEND[1]
    ex = await client.get(f"/api/v1/resumes/{rid}/extracted", headers=rec["h"])
    assert ex.status_code == 200 and ex.json()["contact"]["email"] == "jane.doe@example.com"
    assert all(
        e["already_on_profile"] for e in ex.json()["experiences"]
    )  # imported straight into the profile


async def test_imported_candidates_and_batches_are_private_to_the_sourcing_company(client):
    rec_a = await register_employer(client, "Source Co")
    rec_b = await register_employer(client, "Rival Co")
    hm = await add_staff(client, rec_a, "HIRING_MANAGER")
    body = (await bulk_upload(client, rec_a, [BACKEND])).json()
    batch = await batch_of(client, rec_a, body["batch_id"])
    cid, rid = batch["items"][0]["candidate_id"], None
    rid = (await client.get(f"/api/v1/candidates/{cid}", headers=rec_a["h"])).json()["resumes"][0]["id"]

    # rival company: no search hits, no candidate, no résumé, no batch
    assert (await client.get("/api/v1/search/candidates", headers=rec_b["h"], params={"q": "Jane"})).json()[
        "total"
    ] == 0
    assert (await client.get(f"/api/v1/candidates/{cid}", headers=rec_b["h"])).status_code == 404
    assert (await client.get(f"/api/v1/resumes/{rid}", headers=rec_b["h"])).status_code == 404
    assert (await client.get(f"/api/v1/resumes/{rid}/file", headers=rec_b["h"])).status_code == 404
    assert (await client.get(f"/api/v1/resumes/{rid}/extracted", headers=rec_b["h"])).status_code == 404
    assert (
        await client.patch(f"/api/v1/resumes/{rid}/extracted", headers=rec_b["h"], json={"summary": "x"})
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/resumes/{rid}/extracted/apply", headers=rec_b["h"], json={"skills": "all"}
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/resumes/bulk-imports/{body['batch_id']}", headers=rec_b["h"])
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/resumes/bulk-imports/{body['batch_id']}/process", headers=rec_b["h"])
    ).status_code == 404
    assert (await client.get("/api/v1/resumes/bulk-imports", headers=rec_b["h"])).json()["total"] == 0
    # a hiring manager has no relationship to a sourced candidate
    assert (await client.get(f"/api/v1/resumes/{rid}", headers=hm["h"])).status_code == 404
    assert (await client.get(f"/api/v1/candidates/{cid}", headers=hm["h"])).status_code == 404
    # the same file can be imported independently by the rival company
    rival = (await bulk_upload(client, rec_b, [BACKEND])).json()
    rb = await batch_of(client, rec_b, rival["batch_id"])
    assert rb["items"][0]["status"] == "CREATED" and rb["items"][0]["candidate_id"] != cid

    # company-scoped, paginated list
    lst = await client.get("/api/v1/resumes/bulk-imports", headers=rec_a["h"], params={"page_size": 1})
    assert (
        lst.status_code == 200
        and lst.json()["total"] == 1
        and lst.json()["items"][0]["id"] == body["batch_id"]
    )
    assert (
        lst.json()["items"][0]["counts"]["created"] == 1 and lst.json()["items"][0]["status"] == "COMPLETED"
    )


async def test_sourcing_recruiter_can_review_and_apply_for_imported_candidates(client):
    rec = await register_employer(client)
    body = (await bulk_upload(client, rec, [NURSE])).json()
    cid = (await batch_of(client, rec, body["batch_id"]))["items"][0]["candidate_id"]
    cand = (await client.get(f"/api/v1/candidates/{cid}", headers=rec["h"])).json()
    rid = cand["resumes"][0]["id"]
    assert cand["display_name"] == "Maria Gonzalez" and cand["educations"][0]["field_of_study"] == "Nursing"

    patch = await client.patch(
        f"/api/v1/resumes/{rid}/extracted",
        headers=rec["h"],
        json={"headline": "ICU Nurse", "skills": [{"index": 0, "remove": True}]},
    )
    assert patch.status_code == 200 and patch.json()["headline"] == "ICU Nurse"
    ap = await client.post(
        f"/api/v1/resumes/{rid}/extracted/apply",
        headers=rec["h"],
        json={"fields": ["headline"], "overwrite": ["headline"], "skills": "all", "experiences": "all"},
    )
    assert ap.status_code == 200
    assert ap.json()["applied"].get("experiences", 0) == 0  # already imported: no duplicates
    cand2 = (await client.get(f"/api/v1/candidates/{cid}", headers=rec["h"])).json()
    assert cand2["headline"] == "ICU Nurse" and len(cand2["experiences"]) == 2
    statuses = [s["status"] for s in cand2["skills"] if s["source"] == "RESUME"]
    assert (
        statuses.count("SUGGESTED") == 1 and statuses.count("CONFIRMED") == len(statuses) - 1
    )  # the removed suggestion stays unconfirmed
    # reprocessing keeps the profile intact (the structured import happens once, at creation)
    assert (await client.post(f"/api/v1/resumes/{rid}/process", headers=rec["h"])).status_code == 202
    cand3 = (await client.get(f"/api/v1/candidates/{cid}", headers=rec["h"])).json()
    assert len(cand3["experiences"]) == 2 and cand3["headline"] == "ICU Nurse"


async def test_duplicates_against_registered_candidates(client):
    rec = await register_employer(client)
    visible = await register_candidate(
        client, email="maria.gonzalez@example.com"
    )  # marketplace opt-in (default)
    hidden = await register_candidate(client, email="alex.kim@mail.example")
    await client.patch("/api/v1/candidates/me", headers=hidden["h"], json={"is_searchable": False})
    body = (await bulk_upload(client, rec, [NURSE, FRONTEND, BACKEND])).json()
    items = by_name(await batch_of(client, rec, body["batch_id"]))
    assert (
        items["maria.pdf"]["status"] == "DUPLICATE"
        and items["maria.pdf"]["candidate_id"] == visible["candidate_id"]
    )
    assert "registered" in items["maria.pdf"]["error_message"]
    assert (
        items["alex.docx"]["status"] == "DUPLICATE" and items["alex.docx"]["candidate_id"] is None
    )  # not visible → not linked
    assert items["jane.pdf"]["status"] == "CREATED"


async def test_bulk_import_is_idempotent_on_redelivery(client, session):
    rec = await register_employer(client)
    body = (
        await bulk_upload(client, rec, [BACKEND, FRONTEND, ("corrupt.pdf", fx.malformed_pdf(), PDF)])
    ).json()
    before = await batch_of(client, rec, body["batch_id"])
    n_candidates = await session.scalar(
        select(func.count())
        .select_from(CandidateProfile)
        .where(CandidateProfile.source == CandidateSource.IMPORTED)
    )
    n_experiences = await session.scalar(select(func.count()).select_from(Experience))

    from app.resume.tasks import handle_bulk_import

    ctx = TaskContext(
        task_id=uuid.UUID(body["task_id"]),
        type=TaskType.BULK_RESUME_IMPORT,
        params={"batch_id": body["batch_id"]},
        created_by_id=None,
        company_id=uuid.UUID(rec["company_id"]),
        attempt=1,
        sessionmaker=get_sessionmaker(),
        cache=get_cache(),
        store=TaskStore(get_sessionmaker()),
    )
    result = await handle_bulk_import(ctx)  # the same task delivered a second time
    assert result["created"] == 2 and result["failed"] == 1 and result["total"] == 3
    after = await batch_of(client, rec, body["batch_id"])
    assert after["counts"] == before["counts"] and [i["status"] for i in after["items"]] == [
        i["status"] for i in before["items"]
    ]
    assert (
        await session.scalar(
            select(func.count())
            .select_from(CandidateProfile)
            .where(CandidateProfile.source == CandidateSource.IMPORTED)
        )
        == n_candidates
    )
    assert await session.scalar(select(func.count()).select_from(Experience)) == n_experiences
    assert await session.scalar(select(func.count()).select_from(Resume)) == 2
    notes = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.type == NotificationType.BULK_IMPORT_COMPLETED)
    )
    assert notes == 1  # the completion notification is idempotent too


async def test_files_bracket_field_and_filename_sanitising(client):
    rec = await register_employer(client)
    r = await bulk_upload(client, rec, [("../../etc/jane.pdf", BACKEND[1], PDF), FRONTEND], field="files[]")
    assert r.status_code == 202 and r.json()["accepted"] == 2
    names = set(by_name(await batch_of(client, rec, r.json()["batch_id"])))
    assert names == {"jane.pdf", "alex.docx"}


async def test_request_level_validation(client, monkeypatch):
    rec = await register_employer(client)
    # nothing attached
    assert (await client.post("/api/v1/resumes/bulk-imports", headers=rec["h"])).status_code == 422
    # no file is acceptable → 422 with every reason listed
    r = await bulk_upload(client, rec, [("a.exe", fx.EXE, None), ("b.pdf", b"", PDF)])
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_VALID_FILES"
    assert {x["filename"] for x in r.json()["error"]["details"]["rejected"]} == {"a.exe", "b.pdf"}
    # too many files
    monkeypatch.setattr(get_settings(), "max_bulk_import_files", 2)
    many = await bulk_upload(client, rec, [BACKEND, FRONTEND, NURSE])
    assert many.status_code == 422 and many.json()["error"]["code"] == "TOO_MANY_FILES"
    assert storage_files() == []  # a refused request leaves nothing behind


async def test_queue_outage_keeps_files_and_the_batch_can_be_restarted(client):
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    class Down:
        async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None:
            raise ServiceUnavailableError("down")

    rec = await register_employer(client)
    app.state.dispatcher = Down()
    r = await bulk_upload(client, rec, [BACKEND, FRONTEND])
    assert (
        r.status_code == 202
        and r.json()["task_id"] is None
        and r.json()["accepted"] == 2
        and "process" in r.json()["message"].lower()
    )
    batch = await batch_of(client, rec, r.json()["batch_id"])
    assert batch["status"] == "FAILED" and batch["counts"]["pending"] == 2 and len(storage_files()) == 2

    app.state.dispatcher = InlineDispatcher()
    retry = await client.post(
        f"/api/v1/resumes/bulk-imports/{r.json()['batch_id']}/process", headers=rec["h"]
    )
    assert retry.status_code == 202
    done = await batch_of(client, rec, r.json()["batch_id"])
    assert done["status"] == "COMPLETED" and done["counts"] == {
        "pending": 0,
        "created": 2,
        "duplicate": 0,
        "failed": 0,
    }
    assert (
        await client.post(f"/api/v1/resumes/bulk-imports/{r.json()['batch_id']}/process", headers=rec["h"])
    ).status_code == 409


async def test_one_unexpected_error_does_not_fail_the_batch(client, session, monkeypatch):
    import app.resume.bulk as bulk

    real = bulk.analyze
    calls = {"n": 0}

    async def flaky(data, kind):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("secret jane.doe@example.com internals")
        return await real(data, kind)

    monkeypatch.setattr(bulk, "analyze", flaky)
    rec = await register_employer(client)
    r = await bulk_upload(client, rec, [BACKEND, FRONTEND])
    task = await task_of(client, rec, r.json()["task_id"])
    assert task["status"] == "COMPLETED" and task["result"]["created"] == 1 and task["result"]["failed"] == 1
    items = by_name(await batch_of(client, rec, r.json()["batch_id"]))
    bad = items["jane.pdf"]
    assert (
        bad["status"] == "FAILED"
        and bad["error_code"] == "INTERNAL_ERROR"
        and "secret" not in str(bad)
        and "jane.doe" not in str(bad)
    )
    assert items["alex.docx"]["status"] == "CREATED"
    rows = (await session.execute(select(BulkImportItem.status))).scalars().all()
    assert sorted(s.value for s in rows) == ["CREATED", "FAILED"]
    assert ImportItemStatus.PENDING not in rows
    _ = datetime.now(UTC)
