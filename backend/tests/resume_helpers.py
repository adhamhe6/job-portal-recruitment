"""Helpers for résumé tests (kept separate from the shared ``tests/helpers.py``)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.resume.storage import get_storage

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def upload(
    client: AsyncClient,
    who: dict[str, Any],
    data: bytes,
    name: str = "cv.pdf",
    content_type: str | None = PDF,
    *,
    set_primary: bool | None = None,
) -> Response:
    files = {"file": (name, data, content_type)} if content_type is not None else {"file": (name, data)}
    form = {} if set_primary is None else {"set_primary": "true" if set_primary else "false"}
    return await client.post("/api/v1/resumes", headers=who["h"], files=files, data=form)


async def upload_ok(
    client: AsyncClient, who: dict[str, Any], data: bytes, name: str = "cv.pdf", **kw: Any
) -> dict[str, Any]:
    r = await upload(client, who, data, name, **kw)
    assert r.status_code in (200, 202), r.text
    return r.json()  # type: ignore[no-any-return]


async def bulk_upload(
    client: AsyncClient, who: dict[str, Any], files: list[tuple[str, bytes, str | None]], field: str = "files"
) -> Response:
    parts = [(field, (name, data, ctype)) if ctype else (field, (name, data)) for name, data, ctype in files]
    return await client.post("/api/v1/resumes/bulk-imports", headers=who["h"], files=parts)


async def task_of(client: AsyncClient, who: dict[str, Any], task_id: str) -> dict[str, Any]:
    r = await client.get(f"/api/v1/tasks/{task_id}", headers=who["h"])
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


@pytest.fixture
def clean_storage() -> Iterator[None]:
    """The tests share one storage directory for the whole session: start each test that counts files from empty."""
    root = get_storage().root  # type: ignore[attr-defined]
    for child in root.glob("resumes/*"):
        shutil.rmtree(child, ignore_errors=True)
    yield
