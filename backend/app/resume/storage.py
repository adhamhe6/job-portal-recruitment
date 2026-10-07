"""Binary storage for uploaded résumé files.

Callers only ever deal with an **opaque, server-generated key** (``resumes/<uuid>/<uuid>.bin``). A key is never derived
from anything the client sent (the original filename lives in the database, for display only), and every storage
implementation must reject keys that could escape its root.

``Storage`` is intentionally tiny (put / open / delete / exists) so an S3-compatible implementation is a drop-in
replacement for ``LocalStorage``: ``put`` → ``put_object`` (multipart upload from the stream), ``open`` → ``get_object``
(spooled to a temporary file), ``delete`` → ``delete_object``, ``exists`` → ``head_object``. Nothing outside this module
touches the filesystem layout, and no API response ever contains a key.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
MAX_KEY_LENGTH = 255
STALE_TEMP_SECONDS = 24 * 3600


class StorageError(Exception):
    """Base class for storage failures (never carries document content)."""


class InvalidStorageKeyError(StorageError):
    """The key is not a well-formed server-generated key (traversal attempt, absolute path, odd characters …)."""


class StorageNotFoundError(StorageError):
    """No object is stored under the key."""


def new_resume_key() -> str:
    """A fresh opaque key. Two random UUIDs: no client-controlled input is ever part of a key."""
    return f"resumes/{uuid.uuid4()}/{uuid.uuid4()}.bin"


def validate_key(key: str) -> str:
    """Return ``key`` if it is a safe relative key, else raise :class:`InvalidStorageKeyError`."""
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
        raise InvalidStorageKeyError("invalid storage key")
    if key.startswith("/") or "\\" in key or "\x00" in key or ".." in key or ":" in key:
        raise InvalidStorageKeyError("invalid storage key")
    segments = key.split("/")
    if len(segments) > 4 or not all(_SEGMENT.match(s) for s in segments):
        raise InvalidStorageKeyError("invalid storage key")
    return key


@runtime_checkable
class Storage(Protocol):
    """Opaque-key blob store."""

    async def put(self, key: str, data: bytes | BinaryIO | AsyncIterator[bytes]) -> int:
        """Store ``data`` atomically under ``key`` (readers never see a partial object). Returns the size in bytes."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Open the object for reading (binary, seekable). Raises :class:`StorageNotFoundError`."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object; deleting a missing object is not an error."""
        ...

    async def exists(self, key: str) -> bool: ...


class LocalStorage:
    """Files below a private root directory (directories ``0700``, files ``0600``, atomic temp-file + rename writes)."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self._tmp = self.root / ".tmp"
        self._ensure_dir(self.root)
        self._ensure_dir(self._tmp)
        self._sweep_stale_temp_files()

    def _sweep_stale_temp_files(self, max_age_seconds: float = STALE_TEMP_SECONDS) -> None:
        """Drop temp files left behind by a process that died mid-write (they are never visible under a real key)."""
        cutoff = time.time() - max_age_seconds
        for path in self._tmp.glob("put-*"):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(0o700)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        # Defence in depth: even a key that passed validation must resolve (symlinks included) below the root.
        if self.root not in path.parents:
            raise InvalidStorageKeyError("invalid storage key")
        return path

    def _write_sync(self, key: str, data: bytes | BinaryIO) -> int:
        final = self._path(key)
        self._ensure_dir(final.parent)
        fd, tmp_name = tempfile.mkstemp(dir=self._tmp, prefix="put-")
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                if isinstance(data, bytes):
                    out.write(data)
                    size = len(data)
                else:
                    while chunk := data.read(CHUNK_SIZE):
                        out.write(chunk)
                        size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp_name, final)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return size

    async def put(self, key: str, data: bytes | BinaryIO | AsyncIterator[bytes]) -> int:
        validate_key(key)
        if isinstance(data, bytes | bytearray) or hasattr(data, "read"):
            payload = bytes(data) if isinstance(data, bytearray) else data
            return await asyncio.to_thread(self._write_sync, key, payload)  # type: ignore[arg-type]
        # Async iterator: spool to the temp directory chunk by chunk, then publish with an atomic rename.
        final = self._path(key)
        await asyncio.to_thread(self._ensure_dir, final.parent)
        fd, tmp_name = await asyncio.to_thread(tempfile.mkstemp, dir=self._tmp, prefix="put-")
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                async for chunk in data:
                    await asyncio.to_thread(out.write, chunk)
                    size += len(chunk)
                await asyncio.to_thread(out.flush)
                await asyncio.to_thread(os.fsync, out.fileno())
            await asyncio.to_thread(os.replace, tmp_name, final)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return size

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise StorageNotFoundError("object not found") from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _delete() -> None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            # Remove the per-object directory when it became empty (never the root or the shared prefix).
            with contextlib.suppress(OSError):
                if path.parent != self.root and path.parent.parent != self.root:
                    path.parent.rmdir()

        await asyncio.to_thread(_delete)

    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return await asyncio.to_thread(path.is_file)

    def wipe(self) -> None:  # pragma: no cover - test helper
        shutil.rmtree(self.root, ignore_errors=True)


@lru_cache
def _build(storage_dir: str) -> Storage:
    return LocalStorage(storage_dir)


def get_storage() -> Storage:
    """Process-wide storage for the configured backend (only ``local`` exists today)."""
    return _build(get_settings().storage_dir)


async def iter_chunks(fileobj: BinaryIO, chunk_size: int = CHUNK_SIZE) -> AsyncIterator[bytes]:
    """Async chunk iterator over a blocking file object (reads happen in a worker thread); closes the file at the end."""
    try:
        while True:
            chunk = await asyncio.to_thread(fileobj.read, chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(fileobj.close)


async def read_bounded(storage: Storage, key: str, max_bytes: int) -> bytes:
    """Read a stored object fully, refusing anything larger than ``max_bytes`` (guards against a swapped/corrupt blob)."""

    def _read() -> bytes:
        with storage.open(key) as f:
            data = f.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise StorageError("stored object exceeds the size limit")
        return data

    return await asyncio.to_thread(_read)
