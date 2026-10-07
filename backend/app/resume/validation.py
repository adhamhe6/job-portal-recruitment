"""Upload validation: never trust the client.

What is checked, in order, while the upload *streams* (the file is never read into memory; it is spooled to an unnamed
temporary file on disk, hashed and size-limited chunk by chunk):

1. the filename is sanitised (path components, control / bidi characters, length) — it is kept for display only;
2. the extension is on the whitelist (``.pdf``, ``.docx``);
3. the **magic bytes** decide what the file really is (``%PDF-`` / ZIP / legacy OLE) — the size limit is applied first,
   so an oversize upload is always a 413 regardless of what it contains;
4. the declared ``Content-Type`` must not contradict the sniffed type;
5. a DOCX must be a sound ZIP package (``[Content_Types].xml`` + ``word/document.xml``) with zip-bomb protection that
   measures the **actual** decompressed size instead of trusting the sizes declared in the archive.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import re
import tempfile
import unicodedata
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import BinaryIO, Protocol

from app.core.config import get_settings
from app.core.errors import PayloadTooLargeError, UnsupportedMediaError, ValidationFailure

MIB = 1024 * 1024
READ_CHUNK = 64 * 1024
MAX_FILENAME_LENGTH = 120
MAX_DOCX_MEMBERS = 1000
MAX_CONTENT_TYPES_BYTES = 1 * MIB
BULK_BODY_CAP_MIB = 256  # absolute ceiling for one bulk request body, whatever files × per-file limit says
MULTIPART_OVERHEAD = 64 * 1024

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # legacy Word (.doc) / any OLE2 container


class DocumentKind(enum.StrEnum):
    PDF = "pdf"
    DOCX = "docx"


CONTENT_TYPES: dict[DocumentKind, str] = {
    DocumentKind.PDF: "application/pdf",
    DocumentKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTENSIONS: dict[str, DocumentKind] = {".pdf": DocumentKind.PDF, ".docx": DocumentKind.DOCX}
_PDF_TYPE_ALIASES = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/acrobat",
        "applications/vnd.pdf",
        "text/pdf",
        "text/x-pdf",
    }
)
_GENERIC_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
_ALLOWED_HINT = ["PDF (.pdf)", "Word (.docx)"]
_FORBIDDEN_CATEGORIES = {
    "Cc",
    "Cf",
    "Cs",
    "Co",
    "Cn",
    "Zl",
    "Zp",
}  # control, format (bidi / zero-width), surrogate, …
_RESERVED_CHARS = re.compile(r'[<>:"|?*]')


class ChunkSource(Protocol):
    async def read(self, size: int = -1, /) -> bytes: ...


@dataclass(slots=True)
class ValidatedUpload:
    """A fully validated upload, spooled on disk (``file`` is positioned at 0). Call :meth:`close` when done."""

    file: BinaryIO
    size: int
    sha256: str
    kind: DocumentKind
    content_type: str
    filename: str  # sanitised, display only
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.file.close()

    def __enter__(self) -> ValidatedUpload:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --- filenames ------------------------------------------------------------------------------------------------


def sanitize_filename(raw: str | None, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Display-safe filename: no path components, control / bidi / zero-width characters, reserved characters; length-limited."""
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) not in _FORBIDDEN_CATEGORIES)
    name = _RESERVED_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "resume"
    if len(name) > max_length:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = f"{stem[: max_length - len(ext) - 1].rstrip(' .')}.{ext}"
        else:
            name = name[:max_length].rstrip(" .")
    return name or "resume"


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def kind_from_extension(filename: str) -> DocumentKind:
    ext = extension_of(filename)
    kind = EXTENSIONS.get(ext)
    if kind is not None:
        return kind
    if ext == ".doc":
        raise UnsupportedMediaError(
            "Legacy Word (.doc) files are not supported. Save the document as .docx or PDF and upload it again.",
            code="UNSUPPORTED_MEDIA_TYPE",
            details={"reason": "LEGACY_DOC", "allowed": _ALLOWED_HINT},
        )
    raise UnsupportedMediaError(
        "Only PDF (.pdf) and Word (.docx) résumés are accepted.",
        code="UNSUPPORTED_MEDIA_TYPE",
        details={"reason": "UNSUPPORTED_EXTENSION", "allowed": _ALLOWED_HINT},
    )


# --- content sniffing -----------------------------------------------------------------------------------------


def sniff_head(head: bytes) -> str:
    """Classify by magic bytes: ``pdf`` | ``zip`` | ``ole`` | ``unknown``."""
    if head.startswith(PDF_MAGIC):
        return "pdf"
    if head.startswith(ZIP_MAGIC):
        return "zip"
    if head.startswith(OLE_MAGIC):
        return "ole"
    return "unknown"


def _check_head(head: bytes, expected: DocumentKind) -> None:
    sniffed = sniff_head(head)
    if sniffed == "ole":
        raise UnsupportedMediaError(
            "This looks like a legacy Word (.doc) or other Office 97-2003 file, which is not supported. "
            "Save it as .docx or PDF.",
            code="UNSUPPORTED_MEDIA_TYPE",
            details={"reason": "LEGACY_DOC", "allowed": _ALLOWED_HINT},
        )
    wanted = "pdf" if expected == DocumentKind.PDF else "zip"
    if sniffed == wanted:
        return
    if sniffed == "unknown":
        raise UnsupportedMediaError(
            f"The file content is not a valid {expected.value.upper()} document.",
            code="UNSUPPORTED_MEDIA_TYPE",
            details={"reason": "CONTENT_NOT_RECOGNISED", "allowed": _ALLOWED_HINT},
        )
    raise UnsupportedMediaError(
        "The file content does not match its extension.",
        code="UNSUPPORTED_MEDIA_TYPE",
        details={"reason": "EXTENSION_MISMATCH", "allowed": _ALLOWED_HINT},
    )


def check_declared_content_type(declared: str | None, kind: DocumentKind) -> None:
    """Reject only a *contradicting* declared type; absent / generic (octet-stream) declarations defer to the sniffed type."""
    value = (declared or "").split(";")[0].strip().lower()
    if value in _GENERIC_TYPES:
        return
    allowed = _PDF_TYPE_ALIASES if kind == DocumentKind.PDF else {CONTENT_TYPES[DocumentKind.DOCX]}
    if value not in allowed:
        raise UnsupportedMediaError(
            "The declared content type does not match the file.",
            code="UNSUPPORTED_MEDIA_TYPE",
            details={"reason": "CONTENT_TYPE_MISMATCH", "allowed": _ALLOWED_HINT},
        )


# --- DOCX package ---------------------------------------------------------------------------------------------


def _bad_docx(reason: str, message: str = "The file is not a valid DOCX document.") -> UnsupportedMediaError:
    return UnsupportedMediaError(
        message, code="UNSUPPORTED_MEDIA_TYPE", details={"reason": reason, "allowed": _ALLOWED_HINT}
    )


def _unsafe_member_name(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return True
    return ".." in PurePosixPath(name).parts


def validate_docx_package(
    fileobj: BinaryIO, *, max_uncompressed: int, max_members: int = MAX_DOCX_MEMBERS
) -> None:
    """Raise unless ``fileobj`` is a sound, bounded DOCX package. Blocking (run it in a thread)."""
    try:
        fileobj.seek(0)
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise _bad_docx("NOT_A_ZIP") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > max_members:
            raise PayloadTooLargeError(
                "The document contains too many internal parts.",
                code="PAYLOAD_TOO_LARGE",
                details={"reason": "TOO_MANY_MEMBERS", "max_members": max_members},
            )
        names: set[str] = set()
        declared_total = 0
        for info in infos:
            if _unsafe_member_name(info.filename):
                raise _bad_docx("UNSAFE_MEMBER_NAME")
            if info.filename in names:
                raise _bad_docx("DUPLICATE_MEMBER")
            names.add(info.filename)
            if info.flag_bits & 0x1:
                raise _bad_docx("ENCRYPTED_MEMBER", "Password-protected documents are not supported.")
            if info.filename.lower().endswith("vbaproject.bin"):
                raise _bad_docx("MACROS", "Documents with macros are not accepted. Save a macro-free .docx.")
            declared_total += info.file_size
            if declared_total > max_uncompressed:
                raise _too_big(max_uncompressed)
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise _bad_docx("MISSING_PARTS")
        # Measure what decompression really produces: the sizes in the central directory can be forged.
        actual = 0
        try:
            for info in infos:
                with zf.open(info) as member:
                    head = b""
                    while chunk := member.read(READ_CHUNK):
                        if info.filename == "[Content_Types].xml" and len(head) < MAX_CONTENT_TYPES_BYTES:
                            head += chunk
                        actual += len(chunk)
                        if actual > max_uncompressed:
                            raise _too_big(max_uncompressed)
                if info.filename == "[Content_Types].xml" and b"wordprocessingml.document.main" not in head:
                    raise _bad_docx("NOT_A_WORD_DOCUMENT")
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError, EOFError, ValueError) as exc:
            raise _bad_docx("CORRUPT_PACKAGE") from exc


def _too_big(limit: int) -> PayloadTooLargeError:
    return PayloadTooLargeError(
        "The document expands to more data than allowed.",
        code="PAYLOAD_TOO_LARGE",
        details={"reason": "DECOMPRESSED_TOO_LARGE", "max_uncompressed_mb": limit // MIB},
    )


# --- streaming intake -----------------------------------------------------------------------------------------


async def iter_upload(source: ChunkSource, chunk_size: int = READ_CHUNK) -> AsyncIterator[bytes]:
    """Adapt an ``UploadFile``-like object to an async chunk iterator."""
    while chunk := await source.read(chunk_size):
        yield chunk


async def receive_upload(
    chunks: AsyncIterator[bytes],
    *,
    filename: str | None,
    declared_content_type: str | None,
    max_bytes: int | None = None,
    max_uncompressed: int | None = None,
) -> ValidatedUpload:
    """Consume ``chunks`` into a validated, disk-spooled upload, enforcing every limit while streaming.

    Raises ``UnsupportedMediaError`` (415), ``PayloadTooLargeError`` (413) or ``ValidationFailure`` (422); the
    spool file is closed (and thereby deleted) on every failure path.
    """
    settings = get_settings()
    limit = max_bytes if max_bytes is not None else settings.max_resume_mb * MIB
    unzipped_limit = (
        max_uncompressed if max_uncompressed is not None else settings.max_docx_uncompressed_mb * MIB
    )

    clean_name = sanitize_filename(filename)
    expected = kind_from_extension(clean_name)

    spool = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115 - unnamed, 0600, closed by ValidatedUpload.close() / the except below
    try:
        digest = hashlib.sha256()
        total = 0
        head = b""
        async for chunk in chunks:
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise PayloadTooLargeError(
                    f"The file is larger than the {limit // MIB} MB limit.",
                    code="PAYLOAD_TOO_LARGE",
                    details={"reason": "FILE_TOO_LARGE", "max_bytes": limit},
                )
            if len(head) < len(OLE_MAGIC):
                head += chunk[: len(OLE_MAGIC) - len(head)]
            digest.update(chunk)
            await asyncio.to_thread(spool.write, chunk)
        if total == 0:
            raise ValidationFailure("The uploaded file is empty.", code="EMPTY_FILE")
        _check_head(head, expected)
        check_declared_content_type(declared_content_type, expected)
        if expected == DocumentKind.DOCX:
            await asyncio.to_thread(validate_docx_package, spool, max_uncompressed=unzipped_limit)
        spool.seek(0)
        return ValidatedUpload(
            file=spool,
            size=total,
            sha256=digest.hexdigest(),
            kind=expected,
            content_type=CONTENT_TYPES[expected],
            filename=clean_name,
        )
    except BaseException:
        spool.close()
        raise


def bulk_body_limit(file_count_limit: int | None = None) -> int:
    """Total request-body ceiling for a bulk upload (files × per-file limit, bounded, plus multipart overhead)."""
    settings = get_settings()
    files = file_count_limit if file_count_limit is not None else settings.max_bulk_import_files
    total_mib = min(files * settings.max_resume_mb, BULK_BODY_CAP_MIB)
    return total_mib * MIB + files * 4096 + MULTIPART_OVERHEAD


def single_body_limit() -> int:
    return get_settings().max_resume_mb * MIB + MULTIPART_OVERHEAD
