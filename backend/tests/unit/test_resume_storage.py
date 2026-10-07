"""LocalStorage: opaque keys, traversal rejection, atomic writes, private permissions."""

from __future__ import annotations

import io
import os
import re
import stat
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.resume.storage import (
    InvalidStorageKeyError,
    LocalStorage,
    Storage,
    StorageError,
    StorageNotFoundError,
    iter_chunks,
    new_resume_key,
    read_bounded,
    validate_key,
)

KEY = "resumes/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222.bin"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "store")


def test_local_storage_satisfies_the_protocol(storage):
    assert isinstance(storage, Storage)


def test_generated_keys_are_opaque_and_unique():
    keys = {new_resume_key() for _ in range(50)}
    assert len(keys) == 50
    for k in keys:
        assert re.fullmatch(r"resumes/[0-9a-f\-]{36}/[0-9a-f\-]{36}\.bin", k)
        assert validate_key(k) == k


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../etc/passwd",
        "resumes/../../etc/passwd",
        "/etc/passwd",
        "/abs/path.bin",
        "resumes\\evil",
        "resumes//double.bin",
        "resumes/ok/..hidden",
        "resumes/a\x00b",
        "C:/windows/x",
        "a/b/c/d/e/f.bin",
        "x" * 300,
        ".tmp/put-123",
        "resumes/.hidden/file.bin",
        "resumes/spa ce/file.bin",
        "resumes/uni\u202e/file.bin",
    ],
)
async def test_unsafe_keys_rejected_by_every_operation(storage, key):
    with pytest.raises(InvalidStorageKeyError):
        validate_key(key)
    with pytest.raises(InvalidStorageKeyError):
        await storage.put(key, b"x")
    with pytest.raises(InvalidStorageKeyError):
        storage.open(key)
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete(key)
    with pytest.raises(InvalidStorageKeyError):
        await storage.exists(key)


async def test_symlink_escape_is_rejected(storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"top secret")
    (storage.root / "resumes").mkdir()
    (storage.root / "resumes" / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(InvalidStorageKeyError):
        storage.open("resumes/link/secret.bin")
    with pytest.raises(InvalidStorageKeyError):
        await storage.put("resumes/link/new.bin", b"x")
    assert not (outside / "new.bin").exists()


async def test_put_open_exists_delete_roundtrip(storage):
    assert not await storage.exists(KEY)
    assert await storage.put(KEY, b"hello world") == 11
    assert await storage.exists(KEY)
    with storage.open(KEY) as f:
        assert f.read() == b"hello world"
    await storage.delete(KEY)
    assert not await storage.exists(KEY)
    await storage.delete(KEY)  # idempotent
    with pytest.raises(StorageNotFoundError):
        storage.open(KEY)


async def test_put_accepts_file_objects_and_async_iterators(storage):
    assert await storage.put(KEY, io.BytesIO(b"abc" * 100_000)) == 300_000

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 70_000

    key2 = new_resume_key()
    assert await storage.put(key2, chunks()) == 350_000
    with storage.open(key2) as f:
        assert len(f.read()) == 350_000


async def test_files_and_directories_are_private(storage):
    await storage.put(KEY, b"data")
    path = storage.root / KEY
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(storage.root.stat().st_mode) == 0o700


async def test_failed_write_leaves_no_partial_object_and_no_temp_file(storage):
    async def exploding() -> AsyncIterator[bytes]:
        yield b"first half"
        raise RuntimeError("connection lost mid-upload")

    with pytest.raises(RuntimeError):
        await storage.put(KEY, exploding())
    assert not await storage.exists(KEY)
    assert list((storage.root / ".tmp").iterdir()) == []


async def test_overwrite_is_atomic_readers_see_old_or_new_never_a_mix(storage):
    await storage.put(KEY, b"A" * 1000)
    reader = storage.open(KEY)  # an open handle keeps seeing the old, complete content
    await storage.put(KEY, b"B" * 2000)
    assert reader.read() == b"A" * 1000
    reader.close()
    with storage.open(KEY) as f:
        assert f.read() == b"B" * 2000


async def test_failed_overwrite_keeps_previous_content(storage):
    await storage.put(KEY, b"original")

    async def exploding() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await storage.put(KEY, exploding())
    with storage.open(KEY) as f:
        assert f.read() == b"original"


async def test_delete_removes_empty_object_directory_but_not_the_root(storage):
    await storage.put(KEY, b"x")
    await storage.delete(KEY)
    assert not (storage.root / KEY).parent.exists()
    assert storage.root.exists()


async def test_read_bounded_and_iter_chunks(storage):
    await storage.put(KEY, b"z" * 100_000)
    assert len(await read_bounded(storage, KEY, 100_000)) == 100_000
    with pytest.raises(StorageError):
        await read_bounded(storage, KEY, 99_999)
    seen = b""
    async for chunk in iter_chunks(storage.open(KEY), 4096):
        assert len(chunk) <= 4096
        seen += chunk
    assert seen == b"z" * 100_000


def test_root_is_created_private(tmp_path):
    target = tmp_path / "a" / "b"
    s = LocalStorage(target)
    assert stat.S_IMODE(os.stat(s.root).st_mode) == 0o700
