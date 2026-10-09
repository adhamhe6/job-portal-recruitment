"""Upload validation: magic bytes, MIME spoofing, size limits while streaming, zip bombs, hostile filenames."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import AsyncIterator

import pytest

from app.core.errors import PayloadTooLargeError, UnsupportedMediaError, ValidationFailure
from app.resume.validation import (
    CONTENT_TYPES,
    MIB,
    DocumentKind,
    bulk_body_limit,
    check_declared_content_type,
    extension_of,
    kind_from_extension,
    receive_upload,
    sanitize_filename,
    sniff_head,
    validate_docx_package,
)
from tests import fixtures_resumes as fx

PDF = "application/pdf"
DOCX = CONTENT_TYPES[DocumentKind.DOCX]


async def stream(data: bytes, size: int = 4096) -> AsyncIterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def receive(data: bytes, name: str = "cv.pdf", ctype: str | None = PDF, **kw):
    return await receive_upload(stream(data), filename=name, declared_content_type=ctype, **kw)


def reason(exc: pytest.ExceptionInfo[Exception]) -> str:
    return str(getattr(exc.value, "details", {}).get("reason"))


# --- filenames ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cv.pdf", "cv.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\jane\\Desktop\\CV final.pdf", "CV final.pdf"),
        ("/var/tmp/x/../cv.docx", "cv.docx"),
        ("evil\x00.pdf", "evil.pdf"),
        ("a\r\nContent-Disposition: x.pdf", "aContent-Disposition_ x.pdf"),
        ("name\u202egpj.exe.pdf", "namegpj.exe.pdf"),  # right-to-left override removed
        ("zero\u200bwidth.pdf", "zerowidth.pdf"),
        ("  .hidden.pdf  ", "hidden.pdf"),
        ('CV: Jane <Doe> | "final"?.pdf', "CV_ Jane _Doe_ _ _final__.pdf"),
        ("", "resume"),
        (None, "resume"),
        ("///", "resume"),
        ("....", "resume"),
        ("Zoë Müller – Lebenslauf.pdf", "Zoë Müller – Lebenslauf.pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_length_limit_keeps_extension():
    name = sanitize_filename("a" * 500 + ".pdf")
    assert len(name) <= 120 and name.endswith(".pdf")
    assert len(sanitize_filename("b" * 500)) <= 120


@pytest.mark.parametrize(
    ("name", "ext"), [("cv.PDF", ".pdf"), ("cv.tar.docx", ".docx"), ("noext", ""), (".pdf", "")]
)
def test_extension_of(name, ext):
    assert extension_of(name) == ext


def test_extension_whitelist():
    assert kind_from_extension("a.pdf") == DocumentKind.PDF
    assert kind_from_extension("a.DOCX") == DocumentKind.DOCX
    for bad in ("a.doc", "a.exe", "a.pdf.exe", "a", "a.rtf", "a.txt", "a.docm", "a.html", "a.zip"):
        with pytest.raises(UnsupportedMediaError) as exc:
            kind_from_extension(bad)
        assert exc.value.status_code == 415 and exc.value.code == "UNSUPPORTED_MEDIA_TYPE"
    with pytest.raises(UnsupportedMediaError) as exc:
        kind_from_extension("legacy.doc")
    assert reason(exc) == "LEGACY_DOC"


# --- sniffing + declared type -------------------------------------------------------------------------------------


def test_sniff_head():
    assert sniff_head(b"%PDF-1.7\n") == "pdf"
    assert sniff_head(b"PK\x03\x04rest") == "zip"
    assert sniff_head(fx.OLE_DOC[:8]) == "ole"
    assert sniff_head(b"MZ\x90\x00") == "unknown" and sniff_head(b"") == "unknown"


@pytest.mark.parametrize(
    "declared",
    [
        None,
        "",
        "application/octet-stream",
        "application/pdf",
        "application/pdf; charset=binary",
        "APPLICATION/PDF",
        "application/x-pdf",
    ],
)
def test_declared_type_accepted_for_pdf(declared):
    check_declared_content_type(declared, DocumentKind.PDF)


@pytest.mark.parametrize(
    "declared", ["image/png", "text/html", "application/msword", DOCX, "application/zip", "application/json"]
)
def test_declared_type_mismatch_for_pdf(declared):
    with pytest.raises(UnsupportedMediaError) as exc:
        check_declared_content_type(declared, DocumentKind.PDF)
    assert exc.value.status_code == 415 and reason(exc) == "CONTENT_TYPE_MISMATCH"


def test_declared_type_for_docx():
    check_declared_content_type(DOCX, DocumentKind.DOCX)
    check_declared_content_type("application/octet-stream", DocumentKind.DOCX)
    with pytest.raises(UnsupportedMediaError):
        check_declared_content_type(PDF, DocumentKind.DOCX)


# --- accepted uploads ----------------------------------------------------------------------------------------------


async def test_valid_pdf_is_accepted_with_hash_size_and_rewound_file():
    data = fx.backend_pdf()
    up = await receive(data, "../../Jane's CV.pdf")
    with up:
        assert up.kind == DocumentKind.PDF and up.content_type == PDF
        assert up.size == len(data) and up.sha256 == hashlib.sha256(data).hexdigest()
        assert up.filename == "Jane's CV.pdf"
        assert up.file.read() == data  # rewound to the start


async def test_valid_docx_is_accepted():
    data = fx.backend_docx()
    with await receive(data, "cv.docx", DOCX) as up:
        assert up.kind == DocumentKind.DOCX and up.content_type == DOCX and up.size == len(data)


async def test_generic_declared_type_defers_to_sniffed_content():
    with await receive(fx.backend_pdf(), "cv.pdf", "application/octet-stream") as up:
        assert up.content_type == PDF
    with await receive(fx.backend_pdf(), "cv.pdf", None) as up:
        assert up.kind == DocumentKind.PDF


# --- rejected uploads -----------------------------------------------------------------------------------------------


async def test_empty_file_rejected():
    with pytest.raises(ValidationFailure) as exc:
        await receive(b"")
    assert exc.value.status_code == 422 and exc.value.code == "EMPTY_FILE"


async def test_oversize_rejected_while_streaming_without_reading_the_rest():
    consumed = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal consumed
        yield b"%PDF-1.7\n"
        while True:  # an unbounded upload: only a streaming limit can stop it
            consumed += 1
            yield b"0" * 65536

    with pytest.raises(PayloadTooLargeError) as exc:
        await receive_upload(endless(), filename="cv.pdf", declared_content_type=PDF, max_bytes=1 * MIB)
    assert exc.value.status_code == 413 and exc.value.code == "PAYLOAD_TOO_LARGE"
    assert consumed <= 1 * MIB // 65536 + 2


async def test_size_limit_defaults_to_settings_and_exact_limit_is_accepted():
    from app.core.config import get_settings

    limit = get_settings().max_resume_mb * MIB
    body = b"%PDF-1.7\n" + b"0" * (limit - 9)
    with await receive(body) as up:
        assert up.size == limit
    with pytest.raises(PayloadTooLargeError):
        await receive(body + b"0")


async def test_oversize_wins_over_content_checks():
    with pytest.raises(PayloadTooLargeError):
        await receive(b"x" * (2 * MIB), max_bytes=1 * MIB)  # garbage content, but the limit is reported first


@pytest.mark.parametrize(
    ("data", "name", "expected_reason"),
    [
        (fx.backend_docx(), "cv.pdf", "EXTENSION_MISMATCH"),  # DOCX bytes named .pdf
        (fx.backend_pdf(), "cv.docx", "EXTENSION_MISMATCH"),  # PDF bytes named .docx
        (fx.EXE, "cv.pdf", "CONTENT_NOT_RECOGNISED"),  # executable renamed
        (fx.EXE, "cv.docx", "CONTENT_NOT_RECOGNISED"),
        (b"just some text", "cv.pdf", "CONTENT_NOT_RECOGNISED"),
        (b"<html><script>alert(1)</script></html>", "cv.pdf", "CONTENT_NOT_RECOGNISED"),
        (fx.OLE_DOC, "cv.docx", "LEGACY_DOC"),  # legacy Word renamed .docx
        (fx.OLE_DOC, "cv.pdf", "LEGACY_DOC"),
        (b"%PD", "cv.pdf", "CONTENT_NOT_RECOGNISED"),  # truncated magic
    ],
)
async def test_magic_bytes_decide_not_the_extension_or_mime(data, name, expected_reason):
    # the client claims a perfectly matching MIME type; the content still gives it away
    claimed = PDF if name.endswith(".pdf") else DOCX
    with pytest.raises(UnsupportedMediaError) as exc:
        await receive(data, name, claimed)
    assert exc.value.status_code == 415 and reason(exc) == expected_reason


@pytest.mark.parametrize("name", ["cv.doc", "cv.exe", "cv", "cv.pdf.exe", "cv.docm", "cv.html", "cv.zip"])
async def test_extension_not_on_whitelist_rejected_even_with_valid_pdf_content(name):
    with pytest.raises(UnsupportedMediaError):
        await receive(fx.backend_pdf(), name)


async def test_declared_content_type_must_not_contradict_content():
    with pytest.raises(UnsupportedMediaError) as exc:
        await receive(fx.backend_pdf(), "cv.pdf", "image/png")
    assert reason(exc) == "CONTENT_TYPE_MISMATCH"


# --- DOCX package safety ----------------------------------------------------------------------------------------------


async def test_zip_bomb_is_rejected_as_too_large_when_decompressed():
    bomb = fx.zip_bomb_docx(60)
    assert len(bomb) < 1 * MIB  # tiny on the wire, 60 MB once inflated
    with pytest.raises(PayloadTooLargeError) as exc:
        await receive(bomb, "cv.docx", DOCX)
    assert exc.value.status_code == 413 and reason(exc) == "DECOMPRESSED_TOO_LARGE"


def test_decompressed_size_is_measured_against_the_configured_limit():
    bomb = io.BytesIO(fx.zip_bomb_docx(3))
    with pytest.raises(PayloadTooLargeError):
        validate_docx_package(bomb, max_uncompressed=1 * MIB)
    validate_docx_package(bomb, max_uncompressed=10 * MIB)  # same file passes a larger limit


def test_too_many_members_rejected():
    members = {f"word/media/{i}.txt": b"x" for i in range(30)}
    members.update({"[Content_Types].xml": fx.CONTENT_TYPES_XML, "word/document.xml": b"<w:document/>"})
    with pytest.raises(PayloadTooLargeError) as exc:
        validate_docx_package(io.BytesIO(fx.zip_bytes(members)), max_uncompressed=10 * MIB, max_members=10)
    assert reason(exc) == "TOO_MANY_MEMBERS"


@pytest.mark.parametrize(
    ("data", "expected_reason"),
    [
        (fx.traversal_docx(), "UNSAFE_MEMBER_NAME"),
        (
            fx.zip_bytes(
                {"[Content_Types].xml": fx.CONTENT_TYPES_XML, "word/document.xml": b"x", "/abs/evil": b"x"}
            ),
            "UNSAFE_MEMBER_NAME",
        ),
        (
            fx.zip_bytes(
                {"[Content_Types].xml": fx.CONTENT_TYPES_XML, "word/document.xml": b"x", "C:/evil": b"x"}
            ),
            "UNSAFE_MEMBER_NAME",
        ),
        (fx.macro_docx(), "MACROS"),
        (fx.xlsx_like(), "MISSING_PARTS"),
        (fx.zip_bytes({"hello.txt": b"hi"}), "MISSING_PARTS"),
        (
            fx.zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"}),
            "NOT_A_WORD_DOCUMENT",
        ),
        (b"PK\x03\x04" + b"garbage" * 50, "NOT_A_ZIP"),
    ],
)
async def test_docx_package_rules(data, expected_reason):
    with pytest.raises(UnsupportedMediaError) as exc:
        await receive(data, "cv.docx", DOCX)
    assert exc.value.status_code == 415 and reason(exc) == expected_reason


async def test_corrupt_member_crc_is_rejected():
    good = bytearray(
        fx.zip_bytes(
            {
                "[Content_Types].xml": fx.CONTENT_TYPES_XML,
                "word/document.xml": b"<w:document>hello hello hello</w:document>",
            },
            compression=zipfile.ZIP_STORED,
        )
    )
    idx = bytes(good).index(b"hello hello")
    good[idx] ^= 0xFF  # flip a byte inside the stored data: the CRC no longer matches
    with pytest.raises(UnsupportedMediaError) as exc:
        await receive(bytes(good), "cv.docx", DOCX)
    assert reason(exc) == "CORRUPT_PACKAGE"


async def test_duplicate_member_names_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", fx.CONTENT_TYPES_XML)
        zf.writestr("word/document.xml", b"<w:document/>")
        with pytest.warns(UserWarning, match="Duplicate name"):
            zf.writestr("word/document.xml", b"<w:document>other</w:document>")
    with pytest.raises(UnsupportedMediaError) as exc:
        await receive(buf.getvalue(), "cv.docx", DOCX)
    assert reason(exc) == "DUPLICATE_MEMBER"


def test_bulk_body_limit_scales_with_file_count_but_is_capped():
    assert bulk_body_limit(10) < bulk_body_limit(100) <= bulk_body_limit(10_000)
    assert bulk_body_limit(10_000) <= 257 * MIB + 10_000 * 4096 + 64 * 1024
