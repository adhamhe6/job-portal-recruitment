"""Text extraction from PDF (pypdf) and DOCX (python-docx).

Third-party parsers are fed hostile input, so every call is wrapped: whatever they raise is converted to an
:class:`ExtractionError` carrying a **safe** code and message (never text from the document). CPU-bound work runs in a
worker thread under a timeout so a pathological file cannot stall the event loop. OCR is out of scope: image-only
documents fail honestly with ``NO_TEXT_EXTRACTED``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.resume.validation import DocumentKind

logger = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # structural warnings only; keep the worker log quiet

MAX_PDF_PAGES = 30
EXTRACTION_TIMEOUT_SECONDS = 60.0
MIN_TEXT_CHARS = 20  # fewer non-space characters than this = effectively no text
MAX_LINKS = 50
_MAX_TABLE_DEPTH = 3

E_ENCRYPTED = "ENCRYPTED_DOCUMENT"
E_MALFORMED = "MALFORMED_DOCUMENT"
E_NO_TEXT = "NO_TEXT_EXTRACTED"
E_TIMEOUT = "EXTRACTION_TIMEOUT"


class ExtractionError(Exception):
    """Expected extraction failure with a code and a user-safe message (no document content)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    page_count: int | None
    was_truncated: bool
    links: tuple[str, ...] = field(default=())
    pages_failed: int = 0


# --- normalisation ---------------------------------------------------------------------------------------------

_STRIP_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}
_SOFT_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_HORIZONTAL_WS = re.compile(r"[ \t  -   　]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def normalize_text(raw: str) -> str:
    """Normalise whitespace and Unicode without changing wording.

    NFKC folds ligatures / full-width forms, control and zero-width characters are dropped, runs of blanks collapse,
    three or more newlines collapse to one blank line, and words hyphenated across a line break (``develop-\\nment``) are
    re-joined — only when both halves are lowercase letters, so ranges like ``2018-\\n2021`` are left alone.
    """
    text = unicodedata.normalize("NFKC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = text.replace("­", "")
    text = "".join(
        ch if ch in "\n\t" or unicodedata.category(ch) not in _STRIP_CATEGORIES else " " for ch in text
    )
    text = _HORIZONTAL_WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _SOFT_HYPHEN_BREAK.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


# --- PDF -------------------------------------------------------------------------------------------------------


def _pdf_links(page: Any) -> Iterator[str]:
    annots = page.get("/Annots")
    if not annots:
        return
    for ref in annots:
        try:
            action = ref.get_object().get("/A")
            uri = action.get_object().get("/URI") if action is not None else None
        except Exception:
            continue
        if isinstance(uri, str) and uri:
            yield uri.strip()


def _extract_pdf(
    data: bytes, *, max_pages: int, char_budget: int
) -> tuple[list[str], int, bool, list[str], int]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = bool(reader.decrypt(""))  # many PDFs are "encrypted" with an empty user password
            except Exception:  # missing crypto backend, unsupported scheme …
                decrypted = False
            if not decrypted:
                raise ExtractionError(
                    E_ENCRYPTED, "This PDF is password-protected. Remove the password and upload it again."
                )
        total_pages = len(reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            E_MALFORMED, "The PDF could not be read. It may be corrupted; try exporting it again."
        ) from exc
    if total_pages == 0:
        raise ExtractionError(E_MALFORMED, "The PDF contains no pages.")

    pages: list[str] = []
    links: list[str] = []
    failed = 0
    used = 0
    for index in range(min(total_pages, max_pages)):
        try:
            page = reader.pages[index]
            pages.append(page.extract_text() or "")
            if len(links) < MAX_LINKS:
                links.extend(_pdf_links(page))
        except Exception:  # one bad page must not lose the others
            failed += 1
            continue
        used += len(pages[-1])
        if used > char_budget:
            break
    attempted = min(total_pages, max_pages)
    if failed and failed == attempted:
        raise ExtractionError(
            E_MALFORMED, "The PDF could not be read. It may be corrupted; try exporting it again."
        )
    return pages, total_pages, total_pages > max_pages, links[:MAX_LINKS], failed


# --- DOCX ------------------------------------------------------------------------------------------------------


def _docx_block_lines(parent: Any, doc: Any, depth: int = 0) -> Iterator[str]:
    """Yield text lines of a body / header / cell element in document order (paragraphs, tables, content controls)."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in parent.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            yield Paragraph(child, doc).text
        elif tag == qn("w:tbl") and depth < _MAX_TABLE_DEPTH:
            table = Table(child, doc)
            for row in table.rows:
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:  # merged cells repeat
                        continue
                    seen.add(id(cell._tc))
                    yield from _docx_block_lines(cell._tc, doc, depth + 1)
        elif tag == qn("w:sdt"):  # content controls wrap a lot of résumé-template content
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _docx_block_lines(content, doc, depth)


def _extract_docx(data: bytes) -> tuple[list[str], list[str]]:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    try:
        doc = Document(io.BytesIO(data))
        lines: list[str] = []
        try:  # headers frequently hold the name / contact line in Word templates
            seen_headers: set[str] = set()
            for section in doc.sections:
                header = section.header
                if header.is_linked_to_previous:
                    continue
                header_lines = [ln for ln in _docx_block_lines(header._element, doc) if ln.strip()]
                key = "\n".join(header_lines)
                if key and key not in seen_headers:
                    seen_headers.add(key)
                    lines.extend(header_lines)
        except Exception:  # optional part: ignore a broken header, keep the body
            lines = []
        lines.extend(_docx_block_lines(doc.element.body, doc))
        links = [
            rel.target_ref
            for rel in doc.part.rels.values()
            if rel.reltype == RT.HYPERLINK and rel.is_external and isinstance(rel.target_ref, str)
        ][:MAX_LINKS]
    except Exception as exc:
        raise ExtractionError(
            E_MALFORMED, "The Word document could not be read. It may be corrupted."
        ) from exc
    return lines, links


# --- public API ------------------------------------------------------------------------------------------------


def extract_sync(
    data: bytes, kind: DocumentKind, *, max_chars: int, max_pages: int = MAX_PDF_PAGES
) -> ExtractedText:
    """Blocking extraction (use :func:`extract_document` from async code)."""
    char_budget = max_chars * 2
    links: list[str]
    if kind == DocumentKind.PDF:
        pages, page_count, pages_truncated, links, failed = _extract_pdf(
            data, max_pages=max_pages, char_budget=char_budget
        )
        raw = "\n\n".join(pages)
        page_total: int | None = page_count
    else:
        lines, links = _extract_docx(data)
        raw = "\n".join(lines)
        pages_truncated, failed, page_total = False, 0, None

    text = normalize_text(raw)
    if len(re.sub(r"\s", "", text)) < MIN_TEXT_CHARS:
        raise ExtractionError(
            E_NO_TEXT,
            "No readable text was found in this document. It looks scanned or image-only, and OCR is not enabled. "
            "Upload a text-based PDF or a Word document.",
        )
    truncated = pages_truncated
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
        truncated = True
    return ExtractedText(
        text=text, page_count=page_total, was_truncated=truncated, links=tuple(links), pages_failed=failed
    )


async def extract_document(
    data: bytes,
    kind: DocumentKind,
    *,
    max_chars: int,
    max_pages: int = MAX_PDF_PAGES,
    timeout: float = EXTRACTION_TIMEOUT_SECONDS,
) -> ExtractedText:
    """Extract text off the event loop with a timeout. Never raises anything but :class:`ExtractionError`."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(extract_sync, data, kind, max_chars=max_chars, max_pages=max_pages),
            timeout=timeout,
        )
    except ExtractionError:
        raise
    except TimeoutError as exc:
        raise ExtractionError(E_TIMEOUT, "Reading the document took too long and was stopped.") from exc
    except (
        Exception
    ) as exc:  # defensive: parsers can raise anything (RecursionError, MemoryError subclasses of Exception …)
        logger.error("unexpected extraction failure", extra={"error": type(exc).__name__})
        raise ExtractionError(E_MALFORMED, "The document could not be read.") from exc
