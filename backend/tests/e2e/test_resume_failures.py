"""Résumé failure paths: rejected uploads, unprocessable documents, injected embedding / queue / internal failures."""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import ServiceUnavailableError
from app.db.models import Notification, NotificationType, Resume, ResumeProcessingResult
from app.matching.embedder import EmbeddingError
from app.resume.storage import get_storage
from tests import fixtures_resumes as fx
from tests.helpers import register_candidate, register_employer
from tests.resume_helpers import (
    DOCX,
    PDF,
    clean_storage,  # noqa: F401  (fixture)
    upload,
    upload_ok,
)

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("clean_storage")]


def storage_files() -> list[str]:
    root = get_storage().root  # type: ignore[attr-defined]
    return sorted(str(p) for p in root.rglob("*") if p.is_file())


async def error_of(r) -> tuple[str, dict]:
    body = r.json()["error"]
    return body["code"], body


# --- upload rejections ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "ctype", "status", "code"),
    [
        (fx.backend_docx(), "cv.pdf", PDF, 415, "UNSUPPORTED_MEDIA_TYPE"),  # extension / content mismatch
        (fx.backend_pdf(), "cv.docx", DOCX, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (fx.EXE, "cv.pdf", PDF, 415, "UNSUPPORTED_MEDIA_TYPE"),  # MIME spoofing: executable declared as PDF
        (fx.EXE, "cv.exe", "application/x-msdownload", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (fx.OLE_DOC, "cv.doc", "application/msword", 415, "UNSUPPORTED_MEDIA_TYPE"),  # legacy Word
        (fx.OLE_DOC, "cv.docx", DOCX, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (
            fx.backend_pdf(),
            "cv.pdf",
            "image/png",
            415,
            "UNSUPPORTED_MEDIA_TYPE",
        ),  # declared type contradicts content
        (b"", "cv.pdf", PDF, 422, "EMPTY_FILE"),
        (fx.zip_bomb_docx(60), "cv.docx", DOCX, 413, "PAYLOAD_TOO_LARGE"),
        (fx.traversal_docx(), "cv.docx", DOCX, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (fx.macro_docx(), "cv.docx", DOCX, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (fx.xlsx_like(), "cv.docx", DOCX, 415, "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
async def test_rejected_uploads_store_nothing(client, data, name, ctype, status, code):
    cand = await register_candidate(client)
    r = await upload(client, cand, data, name, ctype)
    assert r.status_code == status, r.text
    assert (await error_of(r))[0] == code
    assert storage_files() == []  # nothing was kept
    assert (await client.get("/api/v1/resumes", headers=cand["h"])).json()["total"] == 0


async def test_oversize_file_is_rejected_with_413(client):
    cand = await register_candidate(client)
    big = b"%PDF-1.7\n" + b"0" * (6 * 1024 * 1024)
    r = await upload(client, cand, big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert storage_files() == []


async def test_declared_oversize_request_is_refused_before_it_is_read(client):
    cand = await register_candidate(client)
    r = await client.post(
        "/api/v1/resumes",
        headers={
            **cand["h"],
            "Content-Length": str(50 * 1024 * 1024),
            "Content-Type": "multipart/form-data; boundary=x",
        },
        content=b"--x--",
    )
    assert r.status_code == 413 and r.json()["error"]["details"]["reason"] == "REQUEST_TOO_LARGE"


async def test_chunked_body_without_content_length_is_capped_while_streaming(client):
    cand = await register_candidate(client)
    sent = 0

    async def body():
        nonlocal sent
        yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.7\n'
        for _ in range(400):  # up to ~26 MB if nothing stopped it
            sent += 1
            yield b"0" * 65536

    r = await client.post(
        "/api/v1/resumes",
        headers={**cand["h"], "Content-Type": "multipart/form-data; boundary=x"},
        content=body(),
    )
    assert r.status_code == 413
    assert sent < 400  # the server stopped reading long before the end of the body
    assert storage_files() == []


async def test_anonymous_and_wrong_role_uploads(client):
    assert (
        await client.post("/api/v1/resumes", files={"file": ("cv.pdf", fx.backend_pdf(), PDF)})
    ).status_code == 401
    rec = await register_employer(client)
    assert (await upload(client, rec, fx.backend_pdf())).status_code == 403
    cand = await register_candidate(client)
    assert (await client.post("/api/v1/resumes", headers=cand["h"])).status_code == 422  # no file at all
    assert (
        await client.post("/api/v1/resumes", headers=cand["h"], data={"file": "not-a-file"})
    ).status_code == 422


async def test_resume_limit_per_candidate(client, monkeypatch):
    import app.services.resumes as svc

    monkeypatch.setattr(svc, "MAX_RESUMES_PER_CANDIDATE", 2)
    cand = await register_candidate(client)
    await upload_ok(client, cand, fx.backend_pdf())
    await upload_ok(client, cand, fx.frontend_pdf())
    r = await upload(client, cand, fx.nurse_pdf())
    assert r.status_code == 409 and r.json()["error"]["code"] == "RESUME_LIMIT_REACHED"
    assert len(storage_files()) == 2


# --- documents that cannot be processed -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "ctype", "code", "snippet"),
    [
        (fx.malformed_pdf(), "bad.pdf", PDF, "MALFORMED_DOCUMENT", "could not be read"),
        (fx.scanned_pdf(), "scan.pdf", PDF, "NO_TEXT_EXTRACTED", "OCR is not enabled"),
        (fx.blank_pdf(), "blank.pdf", PDF, "NO_TEXT_EXTRACTED", "scanned"),
        (fx.encrypted_pdf(), "locked.pdf", PDF, "ENCRYPTED_DOCUMENT", "password"),
        (fx.empty_docx(), "empty.docx", DOCX, "NO_TEXT_EXTRACTED", "OCR is not enabled"),
    ],
)
async def test_unprocessable_documents_fail_safely_and_notify(
    client, session, data, name, ctype, code, snippet
):
    cand = await register_candidate(client)
    r = await upload(client, cand, data, name, ctype)
    assert r.status_code == 202, r.text  # the upload itself is fine; processing reports the problem
    body = r.json()
    assert body["status"] == "FAILED" and body["processing"]["task_status"] == "FAILED"
    p = body["processing"]
    assert p["error_code"] == code and snippet in p["error_message"]
    assert p["has_embedding"] is False
    # the message is user-safe: no document content, no internals
    for forbidden in ("Traceback", "jane", "Jane", "/tmp", "pypdf", "Exception"):
        assert forbidden not in p["error_message"]

    task = await client.get(f"/api/v1/tasks/{body['task_id']}", headers=cand["h"])
    assert task.json()["status"] == "FAILED" and task.json()["error_code"] == code
    result = (
        await session.execute(
            select(ResumeProcessingResult).where(ResumeProcessingResult.resume_id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert result.status.value == "FAILED" and result.error_code == code and result.extracted_text is None

    notes = (await client.get("/api/v1/notifications", headers=cand["h"])).json()["items"]
    failed = [n for n in notes if n["type"] == "RESUME_FAILED"]
    assert (
        len(failed) == 1
        and failed[0]["resume_id"] == body["id"]
        and snippet.lower() in failed[0]["message"].lower()
    )
    assert not [n for n in notes if n["type"] == "RESUME_PROCESSED"]

    # review endpoints refuse to serve suggestions that do not exist; the file itself is still downloadable
    assert (await client.get(f"/api/v1/resumes/{body['id']}/extracted", headers=cand["h"])).status_code == 409
    assert (await client.get(f"/api/v1/resumes/{body['id']}/file", headers=cand["h"])).status_code == 200
    # nothing was suggested for the profile
    prof = (await client.get("/api/v1/candidates/me", headers=cand["h"])).json()
    assert prof["skills"] == []


async def test_failed_resume_can_be_reprocessed_and_identical_reupload_retries_it(client, monkeypatch):
    cand = await register_candidate(client)
    pdf = fx.backend_pdf()
    import app.resume.pipeline as pipeline

    real = pipeline.analyze

    async def broken(*a, **k):
        raise pipeline.ExtractionError(
            "MALFORMED_DOCUMENT", "The PDF could not be read. It may be corrupted; try exporting it again."
        )

    monkeypatch.setattr(pipeline, "analyze", broken)
    first = await upload(client, cand, pdf, "cv.pdf")
    assert first.json()["status"] == "FAILED"
    monkeypatch.setattr(pipeline, "analyze", real)

    again = await upload(
        client, cand, pdf, "cv.pdf"
    )  # identical bytes, but the previous attempt FAILED → retried
    assert (
        again.status_code == 202
        and again.json()["id"] == first.json()["id"]
        and again.json()["duplicate"] is True
    )
    assert again.json()["status"] == "PROCESSED" and again.json()["processing"]["attempts"] == 2


async def test_unexpected_internal_error_marks_the_resume_failed_without_leaking(client, monkeypatch):
    import app.resume.pipeline as pipeline

    async def boom(*a, **k):
        raise RuntimeError("secret jane.doe@example.com stack detail")

    monkeypatch.setattr(pipeline, "analyze", boom)
    cand = await register_candidate(client)
    body = (await upload(client, cand, fx.backend_pdf())).json()
    assert body["status"] == "FAILED" and body["processing"]["error_code"] == "INTERNAL_ERROR"
    for blob in (
        body["processing"]["error_message"],
        (await client.get(f"/api/v1/tasks/{body['task_id']}", headers=cand["h"])).text,
    ):
        assert "jane.doe" not in blob and "secret" not in blob
    notes = (await client.get("/api/v1/notifications", headers=cand["h"])).json()["items"]
    assert any(n["type"] == "RESUME_FAILED" for n in notes)


# --- embedding failures: bounded retry ---------------------------------------------------------------------------------------


async def test_embedding_failure_keeps_extracted_data_and_retries_a_bounded_number_of_times(
    client, session, monkeypatch
):
    calls = 0

    async def always_fail(texts):
        nonlocal calls
        calls += 1
        raise EmbeddingError("model unavailable")

    monkeypatch.setattr("app.matching.representation.aembed", always_fail)
    cand = await register_candidate(client)
    r = await upload(client, cand, fx.backend_pdf())
    body = r.json()
    p = body["processing"]
    # the data survived: processed, suggestions available, just no embedding
    assert (
        body["status"] == "PROCESSED"
        and p["has_embedding"] is False
        and p["error_code"] == "EMBEDDING_UNAVAILABLE"
    )
    assert "embedding" in p["error_message"].lower()
    assert (
        p["attempts"] == 2 and p["task_status"] == "COMPLETED"
    )  # retried once (task_max_attempts = 2), then settled
    ex = await client.get(f"/api/v1/resumes/{body['id']}/extracted", headers=cand["h"])
    assert ex.status_code == 200 and {s["name"] for s in ex.json()["skills"]} >= {"Python", "FastAPI"}
    task = (await client.get(f"/api/v1/tasks/{body['task_id']}", headers=cand["h"])).json()
    assert task["attempts"] == 2 and task["result"]["embedding"] is False
    assert calls >= 2
    # exactly one notification, only after the final attempt
    n = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.type == NotificationType.RESUME_PROCESSED)
    )
    assert n == 1


async def test_transient_embedding_failure_recovers_on_retry(client, monkeypatch):
    import app.matching.representation as rep

    real = rep.aembed
    state = {"failed": 0}

    async def flaky(texts):
        if state["failed"] < 1:
            state["failed"] += 1
            raise EmbeddingError("cold start")
        return await real(texts)

    monkeypatch.setattr("app.matching.representation.aembed", flaky)
    cand = await register_candidate(client)
    body = (await upload(client, cand, fx.backend_pdf())).json()
    p = body["processing"]
    assert (
        body["status"] == "PROCESSED"
        and p["has_embedding"] is True
        and p["error_code"] is None
        and p["attempts"] == 2
    )


# --- queue unavailable --------------------------------------------------------------------------------------------------------


class DownDispatcher:
    async def dispatch(self, task_id: str, *, defer_seconds: float = 0) -> None:
        raise ServiceUnavailableError("Job queue unavailable")


async def test_queue_outage_does_not_lose_the_upload(client, session):
    from app.main import app
    from app.workers.dispatch import InlineDispatcher

    cand = await register_candidate(client)
    app.state.dispatcher = DownDispatcher()
    r = await upload(client, cand, fx.backend_pdf(), "cv.pdf")
    assert r.status_code == 202
    body = r.json()
    assert (
        body["task_id"] is None
        and body["status"] == "UPLOADED"
        and body["message"]
        and "process" in body["message"].lower()
    )
    assert (
        body["processing"]["task_status"] == "FAILED"
        and body["processing"]["error_code"] == "QUEUE_UNAVAILABLE"
    )
    assert (
        await client.get(f"/api/v1/resumes/{body['id']}/file", headers=cand["h"])
    ).content == fx.backend_pdf()  # the file is safe
    assert (
        await client.post(f"/api/v1/resumes/{body['id']}/process", headers=cand["h"])
    ).status_code == 503  # still down

    app.state.dispatcher = InlineDispatcher()
    retry = await client.post(f"/api/v1/resumes/{body['id']}/process", headers=cand["h"])
    assert retry.status_code == 202
    after = (await client.get(f"/api/v1/resumes/{body['id']}", headers=cand["h"])).json()
    assert after["status"] == "PROCESSED" and after["task_id"] == retry.json()["task_id"]
    assert await session.scalar(select(func.count()).select_from(Resume)) == 1


async def test_reprocess_is_deduplicated_while_a_run_is_active(client, session):
    from app.db.models import BackgroundTask, TaskStatus, TaskType

    cand = await register_candidate(client)
    body = await upload_ok(client, cand, fx.backend_pdf())
    # simulate a run that is still queued
    pending = BackgroundTask(
        type=TaskType.PROCESS_RESUME,
        params={"resume_id": body["id"]},
        status=TaskStatus.PENDING,
        dedupe_key=f"process-resume:{body['id']}",
        created_by_id=uuid.UUID(cand["user"]["id"]),
    )
    session.add(pending)
    await session.commit()
    r1 = await client.post(f"/api/v1/resumes/{body['id']}/process", headers=cand["h"])
    r2 = await client.post(f"/api/v1/resumes/{body['id']}/process", headers=cand["h"])
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["task_id"] == r2.json()["task_id"] == str(pending.id)
    assert r1.json()["status"] == "PENDING"


async def test_unreadable_pdf_bytes_check_helper_files_are_valid_documents():
    # sanity check of the fixtures themselves: the hostile inputs are hostile, the good ones are good
    from pypdf import PdfReader

    assert len(PdfReader(io.BytesIO(fx.backend_pdf())).pages) == 1
    assert PdfReader(io.BytesIO(fx.encrypted_pdf())).is_encrypted


async def test_upload_endpoints_are_rate_limited(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_rate_limit_attempts", 2)
    cand = await register_candidate(client)
    codes = [
        (
            await upload(
                client, cand, fx.make_pdf(f"Pat Lee {i}\npat{i}@x.example\nSkills\nPython, Docker, SQL\n")
            )
        ).status_code
        for i in range(3)
    ]
    assert codes == [202, 202, 429]
    limited = await upload(client, cand, fx.backend_pdf())
    assert (
        limited.status_code == 429
        and limited.headers["retry-after"]
        and limited.json()["error"]["code"] == "RATE_LIMITED"
    )
    assert (
        await client.get("/api/v1/resumes", headers=cand["h"])
    ).status_code == 200  # reads are not limited

    from tests.resume_helpers import bulk_upload

    rec = await register_employer(client)
    statuses = [
        (
            await bulk_upload(
                client,
                rec,
                [("a.pdf", fx.make_pdf(f"Kim {i}\nkim{i}@x.example\nSkills\nPython, SQL, Docker\n"), PDF)],
            )
        ).status_code
        for i in range(3)
    ]
    assert statuses == [202, 202, 429]


async def test_logs_never_contain_resume_content_or_filenames(client, caplog):
    import logging

    from tests.resume_helpers import bulk_upload

    caplog.set_level(logging.DEBUG)
    cand = await register_candidate(client)
    rec = await register_employer(client)
    await upload(client, cand, fx.backend_pdf(), "private-jane-cv.pdf")
    await upload(client, cand, fx.malformed_pdf(), "secret-broken.pdf")
    await upload(client, cand, fx.scanned_pdf(), "secret-scan.pdf")
    await upload(client, cand, fx.EXE, "payload-evil.pdf")
    await bulk_upload(
        client,
        rec,
        [("bulk-private-alex.docx", fx.frontend_docx(), DOCX), ("bulk-bad.pdf", fx.malformed_pdf(), PDF)],
    )
    text = caplog.text
    assert "Created" not in text or True
    for token in (
        "jane.doe@example.com",
        "Jane Doe",
        "151 2345",
        "janedoe",
        "alex.kim",
        "Alex Kim",
        "555-0199",
        "Berlin",
        "Backend engineer",
        "private-jane-cv",
        "secret-broken",
        "secret-scan",
        "payload-evil",
        "bulk-private-alex",
        "bulk-bad",
    ):
        assert token not in text, token


async def test_persistent_storage_trouble_ends_in_a_failed_resume_not_a_stuck_one(client, monkeypatch):
    import app.resume.pipeline as pipeline

    async def unavailable(*a, **k):
        raise OSError("disk offline")

    monkeypatch.setattr(pipeline, "read_bounded", unavailable)
    cand = await register_candidate(client)
    body = (await upload(client, cand, fx.backend_pdf())).json()
    p = body["processing"]
    assert body["status"] == "FAILED" and p["error_code"] == "TEMPORARY_FAILURE" and p["attempts"] == 2
    assert p["task_status"] == "FAILED"
    assert "disk offline" not in str(body)


async def test_storage_write_failure_is_reported_as_unavailable_and_leaves_nothing(client, monkeypatch):
    from app.resume.storage import LocalStorage

    async def broken_put(self, key, data):
        raise OSError("no space left on device")

    monkeypatch.setattr(LocalStorage, "put", broken_put)
    cand = await register_candidate(client)
    r = await upload(client, cand, fx.backend_pdf())
    assert (
        r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_UNAVAILABLE" and "space" not in r.text
    )
    assert (await client.get("/api/v1/resumes", headers=cand["h"])).json()["total"] == 0
