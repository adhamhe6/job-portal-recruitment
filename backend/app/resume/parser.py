"""Heuristic résumé parser: pure functions, no I/O, no database.

``parse_resume(text)`` turns extracted text into :class:`~app.resume.parsed.ParsedResume` — *suggestions* with confidence
scores. Principles:

* **Honest about reliability.** Anything the parser cannot determine is ``None`` / empty; nothing is guessed to fill a
  gap. Ambiguous layouts lower the confidence instead of producing confident nonsense.
* **No protected attributes.** Age, date of birth, gender, marital status, nationality, photo and similar fields are
  never extracted (the "personal details" section is skipped entirely).
* **Never crashes.** Each sub-parser runs behind a guard; a failure drops that part and records a warning.
* **Bounded.** Inputs are length-capped per line and regexes avoid nested quantifiers.

Layouts understood for experience entries (the date range is the anchor): ``Title / Company | dates``,
``Company — Title  dates``, ``dates  Title, Company``, ``Title at Company (2018-2021)``, and stacked title / company /
dates lines.
"""

from __future__ import annotations

import calendar
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.db.models.enums import EducationLevel
from app.matching.representation import ExperienceItem, total_years_of_experience
from app.resume.lexicon import (
    COMPANY_SUFFIXES,
    COUNTRIES,
    INSTITUTION_WORDS,
    MONTHS,
    PROFICIENCY_WORDS,
    SECTION_ALIASES,
    SPOKEN_LANGUAGES,
    TITLE_WORDS,
    US_STATES,
)
from app.resume.parsed import (
    PARSER_VERSION,
    ParsedCertification,
    ParsedContact,
    ParsedEducation,
    ParsedExperience,
    ParsedLanguage,
    ParsedResume,
    YearsOfExperience,
)
from app.resume.skill_extractor import extract_skills, is_skill_list_line

__all__ = [
    "PARSER_VERSION",
    "DateRange",
    "Section",
    "extract_contact",
    "extract_skills_from_text",
    "find_date_range",
    "map_degree_level",
    "parse_certifications",
    "parse_educations",
    "parse_experiences",
    "parse_languages",
    "parse_resume",
    "split_sections",
]

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 2000
MAX_DESCRIPTION_CHARS = 3000
MAX_SUMMARY_CHARS = 1500
MAX_ENTRIES = 40
HEADER_ZONE_LINES = 14

# --- generic line helpers --------------------------------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[•·▪●◦‣⁃■□◆◇►▶➢✓✔•▪●]|[-–—*]\s+|\d{1,2}[.)]\s+)\s*")
_WORD = re.compile(r"[^\W\d_][\w'’.\-]*", re.UNICODE)
_SEPARATORS = re.compile(r"\s+[|•·]\s+|\s+[–—]\s+|\s+-\s+|\s{3,}|\t+|\s+@\s+|\s+at\s+", re.IGNORECASE)
_EDGE_JUNK = re.compile(r"^[\s|,;:\-–—•·()\[\]/]+|[\s|,;:\-–—•·()\[\]/]+$")


def split_lines(text: str) -> list[str]:
    return [ln.strip()[:MAX_LINE_CHARS] for ln in text.splitlines()]


def is_bullet(line: str) -> bool:
    return bool(_BULLET.match(line))


def strip_bullet(line: str) -> str:
    return _BULLET.sub("", line, count=1).strip()


def _clean_piece(text: str) -> str:
    return _EDGE_JUNK.sub("", text).strip()


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _title_word_count(text: str) -> int:
    return sum(1 for w in _words(text) if w.casefold().strip(".") in TITLE_WORDS)


def _has_company_suffix(text: str) -> bool:
    return any(w.casefold().strip(".,") in COMPANY_SUFFIXES for w in text.split())


_MINOR_WORDS = frozenset(
    {"and", "the", "for", "with", "from", "into", "per", "von", "van", "der", "des", "del", "las", "los"}
)


def _capitalised_ratio(text: str) -> float:
    words = [w for w in _words(text) if len(w) >= 3 and w.casefold() not in _MINOR_WORDS]
    if not words:
        return 0.0
    return sum(1 for w in words if w[0].isupper()) / len(words)


# --- sections ---------------------------------------------------------------------------------------------------

_INLINE_HEADING = re.compile(r"^(?P<h>[^:|]{3,40}?)\s*:\s*(?P<rest>\S.*)$")
_INLINE_OK = frozenset({"skills", "languages", "certifications", "summary"})


@dataclass(slots=True)
class Section:
    key: str
    heading: str
    lines: list[str] = field(default_factory=list)


def _norm_heading(text: str) -> str:
    t = re.sub(r"[^\w&/ ]+|[\d_]+", " ", text.casefold())
    t = re.sub(r"\s+", " ", t).strip()
    tokens = t.split()
    if len(tokens) >= 4 and all(len(tok) == 1 for tok in tokens):  # "S K I L L S"
        t = "".join(tokens)
    t = t.replace(" and ", " & ").replace(" / ", " & ")
    return t


def _heading(line: str, current: str = "header") -> tuple[str, str | None] | None:
    """``(section key, inline content)`` when ``line`` is a section heading, else ``None``.

    Inside a Skills section, ``Languages: Python, Go`` is a sub-label (programming languages), not the spoken-languages
    section: it only counts as a heading when the content actually names spoken languages.
    """
    s = line.strip()
    if not s or len(s) > 90:
        return None
    m = _INLINE_HEADING.match(s)
    if m:
        key = SECTION_ALIASES.get(_norm_heading(m.group("h")))
        rest = m.group("rest").strip()
        if key in _INLINE_OK and not (
            current == "skills"
            and key == "languages"
            and not any(w in SPOKEN_LANGUAGES for w in re.findall(r"[^\W\d_]+", rest.casefold()))
        ):
            return key, rest
    if len(s) <= 50 and not is_bullet(s):
        key = SECTION_ALIASES.get(_norm_heading(s))
        if key:
            return key, None
    return None


def split_sections(lines: Sequence[str]) -> tuple[list[Section], list[str], list[str]]:
    """Split into sections. Returns ``(sections, content_lines, line_sections)`` where the last two are parallel to ``lines``
    (heading lines become empty strings; an inline heading keeps only its content)."""
    sections = [Section("header", "")]
    content: list[str] = []
    owner: list[str] = []
    for line in lines:
        found = _heading(line, sections[-1].key)
        if found:
            key, rest = found
            sections.append(Section(key, line))
            content.append(rest or "")
            owner.append(key if rest else "ignored")
            if rest:
                sections[-1].lines.append(rest)
            continue
        sections[-1].lines.append(line)
        content.append(line)
        owner.append(sections[-1].key)
    return sections, content, owner


def _section_lines(sections: Sequence[Section], key: str) -> list[str]:
    out: list[str] = []
    for s in sections:
        if s.key == key:
            out.extend(s.lines)
    return out


# --- dates ------------------------------------------------------------------------------------------------------

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_YEAR = r"(?:19|20)\d{2}"
_NUM_MONTH = r"(?:0?[1-9]|1[0-2])"
_DATE = (
    rf"(?:{_MONTH}[ \t]*,?[ \t]*{_YEAR}"
    rf"|{_NUM_MONTH}[ \t]*[/.\-][ \t]*{_YEAR}"
    rf"|{_YEAR}[ \t]*[/.\-][ \t]*(?:0[1-9]|1[0-2])(?!\d)"
    rf"|{_YEAR})"
)
_PRESENT = r"(?:present|current(?:ly)?|now|today|ongoing|till[ \t]+(?:date|now)|to[ \t]+date|till[ \t]+present|up[ \t]+to[ \t]+date)"
_RANGE_SEP = r"(?:-|–|—|‑|to|until|till|through|thru|~)"
_RANGE_RE = re.compile(
    rf"(?P<s>{_DATE})[ \t]*{_RANGE_SEP}[ \t]*(?P<e>{_DATE}|{_PRESENT})(?![\w])", re.IGNORECASE
)
_SINCE_RE = re.compile(
    rf"\b(?:since|from)[ \t]+(?P<s>{_DATE})(?![\w])|(?P<s2>{_DATE})[ \t]*(?:to|till|until)[ \t]+(?:date|now|present)(?![\w])",
    re.IGNORECASE,
)
_PRESENT_RE = re.compile(rf"^{_PRESENT}$", re.IGNORECASE)
_MONTH_RE = re.compile(_MONTH, re.IGNORECASE)
_YEAR_RE = re.compile(_YEAR)
_NUMERIC_MONTH_YEAR = re.compile(rf"^({_NUM_MONTH})[ \t]*[/.\-][ \t]*({_YEAR})$")
_YEAR_MONTH = re.compile(rf"^({_YEAR})[ \t]*[/.\-][ \t]*(0[1-9]|1[0-2])$")


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date | None
    end: date | None
    is_current: bool
    span: tuple[int, int]


def _token_to_date(token: str, *, end: bool, today: date) -> date | None:
    """First day of the month for a start, last day for an end; year-only → Jan 1 / Dec 31. Ends are clamped to today."""
    tok = token.strip()
    month: int | None = None
    year: int | None = None
    m = _NUMERIC_MONTH_YEAR.match(tok)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
    else:
        m2 = _YEAR_MONTH.match(tok)
        if m2:
            year, month = int(m2.group(1)), int(m2.group(2))
        else:
            ym = _YEAR_RE.search(tok)
            if not ym:
                return None
            year = int(ym.group(0))
            mm = _MONTH_RE.search(tok[: ym.start()])
            if mm:
                month = MONTHS[mm.group(0).lower()[:3]]
    if not (1950 <= year <= 2100):
        return None
    if month is None:
        month_for_calc = 12 if end else 1
        day = 31 if end else 1
    else:
        month_for_calc = month
        day = calendar.monthrange(year, month)[1] if end else 1
    try:
        d = date(year, month_for_calc, day)
    except ValueError:
        return None
    if end and d > today:
        d = today
    return d


def find_date_range(line: str, today: date | None = None) -> DateRange | None:
    """Find a date range ("Jan 2020 – Present", "2018-2021", "03/2019 - 08/2021", "since 2020") in ``line``."""
    today = today or date.today()
    m = _RANGE_RE.search(line)
    if m:
        start = _token_to_date(m.group("s"), end=False, today=today)
        if start is None or start > today:
            return None
        end_tok = m.group("e").strip()
        if _PRESENT_RE.match(end_tok):
            return DateRange(start, None, True, m.span())
        end = _token_to_date(end_tok, end=True, today=today)
        if end is None or end < start:
            return None
        return DateRange(start, end, False, m.span())
    s = _SINCE_RE.search(line)
    if s:
        start = _token_to_date(s.group("s") or s.group("s2"), end=False, today=today)
        if start and start <= today:
            return DateRange(start, None, True, s.span())
    return None


# --- contact ---------------------------------------------------------------------------------------------------------

_EMAIL = re.compile(
    r"(?<![\w.+\-])[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9\-]{1,63})*\.[A-Za-z]{2,24}\b"
)
_IMAGE_TLDS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp"})
_PHONE = re.compile(r"(?<![\w/])(\+?\(?\d[\d \t().\-]{6,22}\d)(?![\w/])")
_PHONE_LABEL = re.compile(r"\b(?:phone|tel|telephone|mobile|cell|mob|call|whatsapp)\b", re.IGNORECASE)
_LINKEDIN = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/([A-Za-z0-9\-_%]{2,100})", re.IGNORECASE
)
_GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9\-]{0,38}))", re.IGNORECASE
)
_GITHUB_RESERVED = frozenset(
    {"orgs", "features", "sponsors", "about", "topics", "marketplace", "login", "settings", "pricing"}
)
_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>()\[\]\"',;|]+")
_BARE_DOMAIN = re.compile(
    r"(?i)(?<![\w@./])((?:[a-z0-9\-]+\.)+(?:com|io|dev|me|net|org|co|ai|app|tech|design|site|xyz)(?:/[^\s<>()\[\]\"',;|]*)?)(?![\w@])"
)
_NOT_PORTFOLIO_HOSTS = (
    "linkedin.com",
    "github.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "medium.com",
    "t.me",
)
_BARE_STOPLIST = frozenset(
    {
        "asp.net",
        "socket.io",
        "vb.net",
        "chart.js",
        "d3.js",
        "three.js",
        "node.js",
        "next.js",
        "vue.js",
        "react.js",
        "express.js",
    }
)
_NAME_TOKEN = re.compile(r"^[^\W\d_]+(?:['’.\-][^\W\d_]+)*\.?$", re.UNICODE)
_NAME_PARTICLES = frozenset(
    {
        "van",
        "von",
        "de",
        "der",
        "den",
        "del",
        "della",
        "di",
        "da",
        "dos",
        "du",
        "la",
        "le",
        "bin",
        "ibn",
        "al",
        "el",
        "bint",
        "ben",
        "ter",
        "ten",
        "af",
        "y",
        "e",
    }
)
_NAME_STOPWORDS = frozenset(
    {
        "resume",
        "résumé",
        "curriculum",
        "vitae",
        "cv",
        "profile",
        "summary",
        "contact",
        "address",
        "phone",
        "email",
        "e-mail",
        "linkedin",
        "github",
        "portfolio",
        "location",
        "page",
        "objective",
        "skills",
        "experience",
        "education",
        "references",
        "declaration",
        "personal",
        "details",
        "information",
        "mobile",
        "tel",
        "website",
        "available",
        "open",
    }
)
_HONORIFICS = frozenset(
    {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "prof", "prof.", "eng", "eng.", "sir"}
)
_LOCATION_LABEL = re.compile(
    r"^(?:location|address|city|based in|located in|residence)\s*[:\-]\s*(.+)$", re.IGNORECASE
)
_LOCATION_SHAPE = re.compile(
    r"^[^\W\d_][\w.'’\- ]{1,40},\s*[^\W\d_][\w.'’\- ]{1,40}(?:,\s*[^\W\d_][\w.'’\- ]{1,40})?$", re.UNICODE
)


def _valid_email(addr: str) -> bool:
    local, _, domain = addr.rpartition("@")
    if ".." in addr or len(addr) > 254 or local.endswith(".") or local.startswith("."):
        return False
    return domain.rsplit(".", 1)[-1].lower() not in _IMAGE_TLDS


def _find_email(lines: Sequence[str]) -> str | None:
    for line in lines:
        for m in _EMAIL.finditer(line):
            if _valid_email(m.group(0)):
                return m.group(0).lower()
    return None


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        return None
    if re.fullmatch(rf"\(?{_YEAR}\)?[\s\-–./]+\(?{_YEAR}\)?", raw.strip()):
        return None
    cleaned = re.sub(r"\s+", " ", raw).strip(" .-")
    if len(cleaned) > 32:
        cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned if len(cleaned) <= 32 else None


def _find_phone(lines: Sequence[str]) -> str | None:
    for line in lines:
        if re.search(r"\bfax\b", line, re.IGNORECASE):
            continue
        scrub = _RANGE_RE.sub(" ", _EMAIL.sub(" ", line))
        for m in _PHONE.finditer(scrub):
            phone = _clean_phone(m.group(1))
            if phone:
                return phone
    return None


def _normalise_url(raw: str) -> str | None:
    url = raw.rstrip(".,;:)'\"")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url if 8 < len(url) <= 300 else None


def _find_urls(
    zone: Sequence[str], everywhere: Sequence[str], links: Sequence[str]
) -> tuple[str | None, str | None, str | None]:
    """``(linkedin, github, portfolio)``. Profile URLs are taken from anywhere; a portfolio URL only from the header zone
    or an explicit hyperlink target labelled by the header text, to avoid picking up project links."""
    haystack = [*everywhere, *links]
    linkedin = github = portfolio = None
    for text in haystack:
        if linkedin is None and (m := _LINKEDIN.search(text)):
            linkedin = f"https://www.linkedin.com/in/{m.group(1).rstrip('/')}"
        if github is None and (g := _GITHUB.search(text)) and g.group(1).lower() not in _GITHUB_RESERVED:
            github = f"https://github.com/{g.group(1)}"
    for text in [*zone, *links[:5]]:
        scrub = _EMAIL.sub(" ", text)
        candidates = [m.group(0) for m in _URL.finditer(scrub)]
        if text in zone:
            candidates += [
                m.group(1) for m in _BARE_DOMAIN.finditer(scrub) if m.group(1).lower() not in _BARE_STOPLIST
            ]
        for cand in candidates:
            low = cand.lower()
            if any(h in low for h in _NOT_PORTFOLIO_HOSTS) or low.startswith("mailto:"):
                continue
            portfolio = _normalise_url(cand)
            if portfolio:
                break
        if portfolio:
            break
    return linkedin, github, portfolio


_CREDENTIALS = re.compile(
    r"(?:\s*,\s*|\s+)(?:[A-Z]{2,5}|Ph\.?D\.?|M\.?D\.?)(?:\s*,\s*(?:[A-Z]{2,5}|Ph\.?D\.?))*\s*$"
)


def _plausible_name(piece: str) -> str | None:
    text = re.sub(r"^(?:name\s*[:\-]\s*)", "", piece.strip(), flags=re.IGNORECASE)
    if "," in text:  # "Maria Gonzalez, RN" / "Jane Doe, PhD": drop trailing credentials
        text = _CREDENTIALS.sub("", text, count=1)
    text = _clean_piece(text)
    if not text or any(ch.isdigit() for ch in text) or "@" in text or "/" in text:
        return None
    tokens = [t for t in text.split() if t.casefold() not in _HONORIFICS]
    if not 2 <= len(tokens) <= 5:
        return None
    low = {t.casefold().strip(".,") for t in tokens}
    if low & _NAME_STOPWORDS or _title_word_count(text) or _has_company_suffix(text):
        return None
    for tok in tokens:
        if not _NAME_TOKEN.match(tok):
            return None
        if tok.casefold() in _NAME_PARTICLES:
            continue
        if tok[0].isalpha() and tok[0].islower() and tok.upper() != tok.lower() and tok[0] != tok[0].upper():
            return None  # lower-case word that is not a particle: this is prose, not a name
    if text.isupper() or text.islower():
        text = " ".join(
            t if t.casefold() in _NAME_PARTICLES else t.capitalize() for t in " ".join(tokens).split()
        )
    else:
        text = " ".join(tokens)
    return text[:100]


def _find_name(zone: Sequence[str]) -> tuple[str | None, int | None]:
    for idx, line in enumerate(zone):
        if not line.strip():
            continue
        for piece in re.split(r"\s*[|•·]\s*|\s{3,}|\t+", line):
            name = _plausible_name(piece)
            if name:
                return name, idx
    return None, None


def _looks_like_location(text: str) -> bool:
    if not _LOCATION_SHAPE.match(text):
        return False
    last = text.rsplit(",", 1)[-1].strip().casefold().rstrip(".")
    return last in COUNTRIES or last in US_STATES or last.replace(".", "") in COUNTRIES


def _find_location(zone: Sequence[str]) -> str | None:
    for line in zone:
        m = _LOCATION_LABEL.match(line.strip())
        if m:
            value = _clean_piece(m.group(1))[:100]
            if value and "@" not in value and not any(ch.isdigit() for ch in value[:3]):
                return value
    for line in zone:
        for piece in re.split(r"\s*[|•·]\s*|\s{3,}|\t+|\s+[–—]\s+", line):
            piece = _clean_piece(piece)
            if "@" in piece or piece.lower().startswith(("http", "www")):
                continue
            if _looks_like_location(piece):
                return piece
    return None


def extract_contact(
    lines: Sequence[str], links: Sequence[str] = (), zone: Sequence[str] | None = None
) -> tuple[ParsedContact, int | None]:
    """Contact details. ``zone`` = the header lines; returns the contact and the index of the name line within the zone."""
    zone = list(zone if zone is not None else [ln for ln in lines if ln.strip()][:HEADER_ZONE_LINES])
    name, name_idx = _find_name(zone[:10])
    mailto = [link[7:].split("?")[0] for link in links if link.lower().startswith("mailto:")]
    email = _find_email(zone) or _find_email(mailto) or _find_email(lines)
    phone = _find_phone(zone)
    if phone is None:
        phone = _find_phone([ln for ln in lines if _PHONE_LABEL.search(ln)])
    linkedin, github, portfolio = _find_urls(zone, lines, links)
    return (
        ParsedContact(
            name=name,
            email=email,
            phone=phone,
            linkedin_url=linkedin,
            github_url=github,
            portfolio_url=portfolio,
            location=_find_location(zone),
        ),
        name_idx,
    )


# --- experience -------------------------------------------------------------------------------------------------------

_STRIP_PARENS_DATES = re.compile(r"[\(\[]\s*[\)\]]")


def _looks_like_header(line: str) -> bool:
    """A short, title/company-like line (not a bullet, not a sentence, not a skills enumeration)."""
    s = line.strip()
    if not s or is_bullet(s) or len(s) > 90 or len(s.split()) > 10:
        return False
    if s.endswith(".") and not _has_company_suffix(s.split()[-1] if s.split() else ""):
        return False
    if is_skill_list_line(s) or s.count(",") >= 3:
        return False
    ratio = _capitalised_ratio(s)
    # Strongly capitalised lines are headers; title / company vocabulary needs at least half the words capitalised too,
    # so "Mentored junior engineers" (a description) is not mistaken for a job title.
    return ratio >= 0.8 or (
        bool(_title_word_count(s) or _has_company_suffix(s)) and ratio >= 0.5 and len(s.split()) <= 8
    )


def _looks_like_location_piece(text: str) -> bool:
    t = text.strip()
    if t.casefold() in {"remote", "hybrid", "on-site", "onsite"}:
        return True
    if _has_company_suffix(t) or _INSTITUTION.search(t):
        return False
    return _looks_like_location(t) or t.casefold().rstrip(".") in COUNTRIES


def _is_region(text: str) -> bool:
    t = text.strip().casefold().rstrip(".")
    return t in US_STATES or t in COUNTRIES


def _split_company_location(text: str) -> tuple[str, str | None]:
    """``"Acme Corp, Berlin"`` → company + location; ``"Seton Hospital, Austin, TX"`` → company + ``"Austin, TX"``;
    ``"Acme, Inc."`` stays whole."""
    if "," not in text:
        return text, None
    parts = [p.strip() for p in text.split(",")]
    if len(parts) >= 3 and _is_region(parts[-1]) and parts[-2] and len(parts[-2].split()) <= 3:
        return ", ".join(parts[:-2]), ", ".join(parts[-2:])
    head, tail = ", ".join(parts[:-1]), parts[-1]
    if not head or not tail or tail.casefold().rstrip(".") in COMPANY_SUFFIXES:
        return text, None
    if (
        len(tail.split()) <= 3
        and tail[0].isupper()
        and not _title_word_count(tail)
        and not any(c.isdigit() for c in tail)
    ):
        return head, tail
    return text, None


_PAREN_GROUP = re.compile(r"\(([^()]{2,60})\)")


def _split_header_text(text: str) -> list[str]:
    located: list[str] = []
    for m in _PAREN_GROUP.finditer(text):  # "Alibaba Cloud (Hangzhou, China)": the parenthesis is the location
        if _looks_like_location_piece(m.group(1)):
            located.append(m.group(1).strip())
            text = text.replace(m.group(0), " ")
    parts = [p for p in (_clean_piece(x) for x in _SEPARATORS.split(text)) if p]
    parts.extend(located)
    out: list[str] = []
    for part in parts:
        if "," in part:  # "Senior Engineer, Acme Corp" → two pieces; "Acme Corp, Berlin" stays together
            head, _, tail = part.partition(",")
            if _title_word_count(head) and not _title_word_count(tail) and tail.strip():
                out.extend([_clean_piece(head), _clean_piece(tail)])
                continue
        out.append(part)
    return out


def _assign_roles(pieces: list[str]) -> tuple[str | None, str | None, str | None, float]:
    """Pick title / company / location among header pieces. Returns also a confidence bonus."""
    pieces = [p for p in pieces if p]
    if not pieces:
        return None, None, None, 0.0
    location: str | None = None
    remaining = list(pieces)
    for p in reversed(pieces):
        if len(pieces) > 1 and _looks_like_location_piece(p) and not _title_word_count(p):
            location = p
            remaining.remove(p)
            break
    title: str | None = None
    best = 0
    for p in remaining:
        score = _title_word_count(p)
        if score > best:
            title, best = p, score
    if title is not None:
        remaining.remove(title)
    company: str | None = None
    for p in remaining:
        if _has_company_suffix(p):
            company = p
            break
    if company is None and remaining:
        company = remaining[0]
    bonus = 0.0
    if title is None and company is not None:
        # No title vocabulary matched: the first piece is conventionally the title, the second the company.
        if len(pieces) >= 2 and location is None:
            title, company = pieces[0], pieces[1]
        elif _has_company_suffix(company):
            title = None
        else:
            title, company = company, None
    else:
        bonus = 0.15 if title else 0.0
    if company:
        company, company_loc = _split_company_location(company)
        location = location or company_loc
    return title, company or None, location, bonus


@dataclass(slots=True)
class _Anchor:
    idx: int
    rng: DateRange
    remainder: str
    before: list[int] = field(default_factory=list)
    after: list[int] = field(default_factory=list)


def _remainder(line: str, rng: DateRange) -> str:
    text = (line[: rng.span[0]] + " " + line[rng.span[1] :]).strip()
    text = _STRIP_PARENS_DATES.sub(" ", text)
    return _clean_piece(text)


def _is_anchor_line(line: str, rng: DateRange | None) -> bool:
    if rng is None or is_bullet(line) or len(line) > 140:
        return False
    rest = _remainder(line, rng)
    return not (len(rest) > 100 or len(rest.split()) > 14 or (rest.endswith(".") and len(rest.split()) > 6))


def parse_experiences(lines: Sequence[str], today: date | None = None) -> list[ParsedExperience]:
    today = today or date.today()
    lines = list(lines)
    anchors: list[_Anchor] = []
    for i, line in enumerate(lines):
        rng = find_date_range(line, today)
        if _is_anchor_line(line, rng):
            assert rng is not None
            anchors.append(_Anchor(i, rng, _remainder(line, rng)))
    if not anchors:
        return _parse_undated_experiences(lines)

    floor = -1  # nothing before this index may be claimed as a header of the current entry
    for a in anchors:
        j = a.idx - 1
        while j > floor and len(a.before) < 2 and lines[j].strip() and _looks_like_header(lines[j]):
            a.before.insert(0, j)
            j -= 1
        if not a.before and not a.remainder:  # dates on their own line first, title / company underneath
            j = a.idx + 1
            while j < len(lines) and len(a.after) < 2 and lines[j].strip() and _looks_like_header(lines[j]):
                a.after.append(j)
                j += 1
        floor = max([a.idx, *a.after])

    entries: list[ParsedExperience] = []
    for k, a in enumerate(anchors):
        end = (
            anchors[k + 1].before[0]
            if k + 1 < len(anchors) and anchors[k + 1].before
            else (anchors[k + 1].idx if k + 1 < len(anchors) else len(lines))
        )
        first_desc = max([a.idx, *a.after]) + 1
        pieces: list[str] = []
        for j in a.before:
            pieces.extend(_split_header_text(lines[j]))
        pieces.extend(_split_header_text(a.remainder))
        for j in a.after:
            pieces.extend(_split_header_text(lines[j]))
        title, company, location, bonus = _assign_roles(pieces)
        inherited = False
        if title and not company and entries and len([p for p in pieces if p]) == 1 and entries[-1].company:
            # Several roles under one employer: "Senior PM  2018 – Present" / "PM  2015 – 2018" under one company heading.
            company, inherited = entries[-1].company, True
        desc_lines = [strip_bullet(x) for x in lines[first_desc:end] if x.strip()]
        description = "\n".join(desc_lines)[:MAX_DESCRIPTION_CHARS] or None
        if not (title or company):
            continue
        has_dates = a.rng.start is not None
        confidence = 0.4 + (0.2 if has_dates else 0.0) + bonus + (0.15 if company else 0.0) - (0.1 if inherited else 0.0)
        entries.append(
            ParsedExperience(
                title=(title or None) and title[:200],
                company=(company or None) and company[:200],
                location=(location or None) and location[:200],
                start_date=a.rng.start,
                end_date=a.rng.end,
                is_current=a.rng.is_current,
                description=description,
                confidence=round(min(confidence, 0.95), 2),
            )
        )
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def _parse_undated_experiences(lines: Sequence[str]) -> list[ParsedExperience]:
    """No date anchors at all: group header-like lines followed by bullets / prose. Low confidence, dates unknown."""
    entries: list[ParsedExperience] = []
    header: list[str] = []
    desc: list[str] = []

    def flush() -> None:
        if not header:
            return
        pieces: list[str] = []
        for h in header:
            pieces.extend(_split_header_text(h))
        title, company, location, _ = _assign_roles(pieces)
        if title or company:
            entries.append(
                ParsedExperience(
                    title=title,
                    company=company,
                    location=location,
                    description="\n".join(strip_bullet(d) for d in desc if d.strip())[:MAX_DESCRIPTION_CHARS]
                    or None,
                    confidence=0.35,
                )
            )

    for line in lines:
        if not line.strip():
            continue
        if _looks_like_header(line) and (not desc or len(header) == 0):
            if desc:
                flush()
                header, desc = [], []
            if len(header) < 3:
                header.append(line)
        elif _looks_like_header(line) and desc and not is_bullet(line):
            flush()
            header, desc = [line], []
        else:
            desc.append(line)
    flush()
    return entries[:MAX_ENTRIES]


# --- education ----------------------------------------------------------------------------------------------------------

_CAP = r"(?-i:[A-Z][a-z]+)"
_OF_FIELD = rf"(?: of {_CAP}(?: {_CAP})?(?: (?:and|&) {_CAP})?)?"
_DEGREE_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(ph\.?\s?d\.?|d\.?\s?phil\.?|doctorate|doctor of [A-Za-z]+|ed\.?d\.?|d\.?b\.?a\.?)(?![\w])",
            re.IGNORECASE,
        ),
        "DOCTORATE",
        "long",
    ),
    (
        re.compile(
            rf"\b(master(?:'?s)?(?: degree)?{_OF_FIELD}|m\.?\s?sc\.?|m\.?\s?eng\.?|m\.?\s?b\.?\s?a\.?|m\.?\s?phil\.?|m\.?\s?p\.?\s?h\.?|m\.?\s?f\.?\s?a\.?|ll\.?m\.?|m\.?\s?res\.?|m\.?\s?tech\.?|m\.?\s?p\.?\s?a\.?|m\.?\s?s\.?\s?w\.?|m\.?\s?ed\.?)(?![\w])",
            re.IGNORECASE,
        ),
        "MASTER",
        "long",
    ),
    (
        re.compile(
            rf"\b(bachelor(?:'?s)?(?: degree)?{_OF_FIELD}|b\.?\s?sc\.?|b\.?\s?eng\.?|b\.?\s?tech\.?|b\.?\s?b\.?\s?a\.?|b\.?\s?com\.?|b\.?\s?f\.?\s?a\.?|ll\.?b\.?|b\.?\s?s\.?\s?n\.?|b\.?\s?ed\.?|undergraduate degree)(?![\w])",
            re.IGNORECASE,
        ),
        "BACHELOR",
        "long",
    ),
    (
        re.compile(
            rf"\b(associate(?:'?s)?(?: degree)?{_OF_FIELD}|a\.?a\.?s\.?|higher national diploma|hnd)(?![\w])",
            re.IGNORECASE,
        ),
        "ASSOCIATE",
        "long",
    ),
    (
        re.compile(
            r"\b(high school(?: diploma)?|secondary school|highschool|ged|a-levels?|abitur|general education diploma)(?![\w])",
            re.IGNORECASE,
        ),
        "HIGH_SCHOOL",
        "long",
    ),
)
# Two-letter abbreviations collide with state codes / words (MA, MS, BA, BS, AS, AA): only at the start of a degree piece.
_AMBIGUOUS_DEGREES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|[-–—(|]\s*)(M\.?S\.?|M\.?A\.?)(?=\s*(?:\(|,|in\b|of\b|-|–|—|[A-Z]))"), "MASTER"),
    (re.compile(r"(?:^|[-–—(|]\s*)(B\.?S\.?|B\.?A\.?)(?=\s*(?:\(|,|in\b|of\b|-|–|—|[A-Z]))"), "BACHELOR"),
    (re.compile(r"(?:^|[-–—(|]\s*)(A\.?S\.?|A\.?A\.?)(?=\s*(?:\(|,|in\b|of\b|-|–|—|[A-Z]))"), "ASSOCIATE"),
)
_FIELD_AFTER = re.compile(
    r"^\s*(?:\((?:hons|honours|honors)\.?\)\s*)?(?:\([A-Za-z.\s]{2,12}\)\s*)?(?:(?:in|of|:|,|-|–|—)\s*)?(?P<f>[A-Z][A-Za-z&/'’\- ]{2,70}?)(?=\s*(?:,|\(|\||—|–|\s-\s|\d{4}|·|•|$))"
)
_GPA = re.compile(r"\b(?:gpa|cgpa|grade)\b.*$", re.IGNORECASE)
_INSTITUTION = re.compile(r"\b(" + "|".join(INSTITUTION_WORDS) + r")\b", re.IGNORECASE)


def map_degree_level(text: str) -> str | None:
    """Map degree wording (BSc, B.Sc., Bachelor of …, MBA, MSc, PhD, Associate …) to an ``EducationLevel`` value."""
    found = _find_degree(text)
    return found[1] if found else None


def _find_degree(text: str) -> tuple[str, str, int] | None:
    """``(matched degree text, level, end offset)`` — earliest match wins."""
    best: tuple[int, str, str, int] | None = None
    for pattern, level, _ in _DEGREE_PATTERNS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.group(1), level, m.end())
    for pattern, level in _AMBIGUOUS_DEGREES:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(1), m.group(1), level, m.end(1))
    if best is None:
        return None
    return best[1].strip(), best[2], best[3]


def _institution_piece(text: str) -> str | None:
    for part in re.split(r"\s*[|•·]\s*|\s+[–—]\s+|\s+-\s+|,\s*(?=\d{4})|\s{3,}", text):
        part = _clean_piece(re.sub(r"\(?\b(?:19|20)\d{2}\b.*$", "", part))
        if _INSTITUTION.search(part) and len(part) <= 120:
            # "University of X, B.Sc. Computer Science": keep the institution part only
            chunks = [c.strip() for c in part.split(",")]
            for chunk in chunks:
                if _INSTITUTION.search(chunk) and not _find_degree(chunk):
                    return chunk
            return chunks[0] if _INSTITUTION.search(chunks[0]) else part
    return None


def parse_educations(lines: Sequence[str], today: date | None = None) -> list[ParsedEducation]:
    today = today or date.today()
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_inst = cur_deg = False
    for raw in lines:
        line = strip_bullet(raw)
        if not line:
            continue
        has_inst = bool(_INSTITUTION.search(line))
        has_deg = _find_degree(line) is not None
        if cur and ((has_inst and cur_inst) or (has_deg and cur_deg)):
            chunks.append(cur)
            cur, cur_inst, cur_deg = [], False, False
        cur.append(line)
        cur_inst |= has_inst
        cur_deg |= has_deg
    if cur:
        chunks.append(cur)

    out: list[ParsedEducation] = []
    for chunk in chunks:
        text = " | ".join(chunk)
        degree_found = _find_degree(text)
        institution = None
        for ln in chunk:
            institution = _institution_piece(ln)
            if institution:
                break
        if not degree_found and not institution:
            continue
        years = [
            int(y)
            for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", _GPA.sub("", text))
            if 1950 <= int(y) <= 2100
        ]
        start_year = end_year = None
        if len(years) >= 2:
            start_year, end_year = min(years[0], years[1]), max(years[0], years[1])
        elif len(years) == 1:
            end_year = years[0]
        degree = level = field_of_study = None
        if degree_found:
            degree, level, end_off = degree_found
            m = _FIELD_AFTER.match(text[end_off:])
            if m:
                cand = _clean_piece(m.group("f"))
                if (
                    cand
                    and not _INSTITUTION.search(cand)
                    and not _find_degree(cand)
                    and len(cand.split()) <= 8
                ):
                    field_of_study = cand
        if institution is None and degree_found:
            # Institution without a keyword (MIT, KTH, Stanford): a capitalised comma piece next to the degree.
            for piece in re.split(r"\s*[|,]\s*|\s+[–—]\s+", text):
                piece = _clean_piece(re.sub(r"\(?\b(?:19|20)\d{2}\b.*$", "", piece))
                if (
                    piece
                    and piece != field_of_study
                    and not _find_degree(piece)
                    and piece[0].isupper()
                    and len(piece.split()) <= 5
                    and not _GPA.search(piece)
                ):
                    if field_of_study and piece in field_of_study:
                        continue
                    institution = piece
                    break
        if not institution:
            continue
        confidence = (
            0.45
            + (0.2 if level else 0.0)
            + (0.1 if _INSTITUTION.search(institution) else 0.0)
            + (0.1 if end_year else 0.0)
            + (0.05 if field_of_study else 0.0)
        )
        out.append(
            ParsedEducation(
                institution=institution[:200],
                degree=degree[:200] if degree else None,
                degree_level=level,
                field_of_study=field_of_study[:200] if field_of_study else None,
                start_year=start_year,
                end_year=end_year,
                confidence=round(min(confidence, 0.95), 2),
            )
        )
        if len(out) >= MAX_ENTRIES:
            break
    return out


# --- certifications ------------------------------------------------------------------------------------------------------

_KNOWN_CERTS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (
        re.compile(
            r"\bAWS Certified (?:Solutions Architect|Developer|SysOps Administrator|DevOps Engineer|Cloud Practitioner|Security|Machine Learning|Data Analytics|Database|Advanced Networking)(?:\s*[-–—]\s*|\s+)?(?:Associate|Professional|Specialty|Foundational)?"
        ),
        None,
    ),
    (
        re.compile(r"\bCertified Kubernetes (?:Administrator|Application Developer|Security Specialist)\b"),
        None,
    ),
    (
        re.compile(
            r"\b(?:Google|GCP) (?:Professional )?Cloud (?:Architect|Engineer|Developer|Security Engineer|DevOps Engineer)(?: Certified)?\b"
        ),
        None,
    ),
    (re.compile(r"\bMicrosoft Certified:?\s+[A-Z][A-Za-z0-9 \-]+?(?=[,;|\n(]|$)"), None),
    (re.compile(r"\bCertified Scrum Master\b"), None),
    (re.compile(r"\bProject Management Professional\b"), None),
    (re.compile(r"\b(?:PMP|CKAD|CKA|CKS|CISSP|CISM|CEH|CCNA|CCNP|CAPM|PRINCE2|ITIL)\b"), None),
)
_CERT_ISSUER_BY = re.compile(r"\b(?:issued by|by)\s+([A-Z][\w&.\- ]{2,60})$")
_MONTH_YEAR = re.compile(rf"({_MONTH})[ \t]*,?[ \t]*({_YEAR})", re.IGNORECASE)


def _tidy_cert_text(text: str) -> str:
    """Trim separators but keep a balanced ``(CKA)``."""
    t = text.strip(" ,;:-–—")
    if t.endswith(")") and t.count(")") > t.count("("):
        t = t[:-1].rstrip(" ,;:-–—")
    if t.startswith("(") and t.count("(") > t.count(")"):
        t = t[1:].lstrip(" ,;:-–—")
    return re.sub(r"\s+", " ", t)


def _cert_from_line(line: str) -> ParsedCertification | None:
    text = strip_bullet(line)
    if not text or len(text) > 160 or (text.endswith(".") and len(text.split()) > 12):
        return None
    issued_on: date | None = None
    issued_year: int | None = None
    my = _MONTH_YEAR.search(text)
    if my:
        d = _token_to_date(my.group(0), end=False, today=date(2100, 1, 1))
        issued_on = d
        issued_year = d.year if d else None
    else:
        ym = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)
        if ym:
            issued_year = int(ym.group(1))
    issuer = None
    paren = re.search(r"\(([^()]{2,60})\)", text)
    body = text
    if paren and not re.fullmatch(rf".*{_YEAR}.*", paren.group(1)):
        inner = _clean_piece(paren.group(1))
        # "(CKA)" / "(RN)" is the certification's own abbreviation and stays in the name; anything else is the issuer.
        if not re.fullmatch(r"[A-Z][A-Z0-9+\-]{1,9}", inner):
            issuer = inner
            body = body.replace(paren.group(0), " ")
    parts = [
        p
        for p in (
            _tidy_cert_text(x) for x in re.split(r"\s+[|•·]\s+|\s+[–—-]\s+|,\s+(?=\d{4}|[A-Z]{2,}\b)", body)
        )
        if p
    ]
    if not parts:
        return None
    name = _tidy_cert_text(
        re.sub(rf"\b{_MONTH}[ \t]*,?[ \t]*{_YEAR}\b|\b{_YEAR}\b", "", parts[0], flags=re.IGNORECASE)
    )
    # keep "Associate"/"Professional" level suffixes that belong to the certification name
    if len(parts) > 1 and re.match(
        r"^(?:Associate|Professional|Specialty|Foundational|Practitioner)\b", parts[1]
    ):
        name = f"{name} – {parts[1].split(',')[0].strip()}"
        parts = parts[:1] + parts[2:]
    if issuer is None and len(parts) > 1:
        cand = _tidy_cert_text(
            re.sub(rf"\b{_MONTH}[ \t]*,?[ \t]*{_YEAR}\b|\b{_YEAR}\b", "", parts[1], flags=re.IGNORECASE)
        )
        if cand and len(cand) <= 80 and not cand.isdigit():
            issuer = cand
    if not name or len(name) < 2 or not any(ch.isalpha() for ch in name):
        return None
    name = re.sub(r"\s+", " ", name).strip()
    return ParsedCertification(
        name=name[:200],
        issuer=issuer[:200] if issuer else None,
        issued_on=issued_on,
        issued_year=issued_year,
        confidence=0.8,
    )


def parse_certifications(
    section_lines: Sequence[str], all_lines: Sequence[str] = ()
) -> list[ParsedCertification]:
    out: list[ParsedCertification] = []
    seen: set[str] = set()

    def add(cert: ParsedCertification) -> None:
        key = re.sub(r"[^a-z0-9]+", "", cert.name.casefold())
        if key and not any(key in s or s in key for s in seen):
            seen.add(key)
            out.append(cert)

    for line in section_lines:
        for piece in re.split(r"\s*;\s*", line) if ";" in line else [line]:
            cert = _cert_from_line(piece) if piece.strip() else None
            if cert:
                add(cert)
    for line in all_lines:
        if len(line) > 400:
            continue
        for pattern, _ in _KNOWN_CERTS:
            for m in pattern.finditer(line):
                add(ParsedCertification(name=_clean_piece(m.group(0)), confidence=0.6))
    return out[:MAX_ENTRIES]


# --- languages ----------------------------------------------------------------------------------------------------------------

_PROFICIENCY_ORDER = [(level, sorted(words, key=len, reverse=True)) for level, words in PROFICIENCY_WORDS]


def _proficiency(text: str) -> str | None:
    low = text.casefold()
    for level, words in _PROFICIENCY_ORDER:
        for w in words:
            if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low):
                return level
    return None


def parse_languages(lines: Sequence[str]) -> list[ParsedLanguage]:
    out: dict[str, ParsedLanguage] = {}
    for raw in lines:
        line = strip_bullet(raw)
        if not line or len(line) > 300:
            continue
        tokens = [t for t in re.split(r"[,;|•·\n]|\s{3,}", line) if t.strip()]
        for tok in tokens:
            m = re.match(r"^\s*([^\W\d_]+)", tok, re.UNICODE)
            name = SPOKEN_LANGUAGES.get(m.group(1).casefold()) if m else None
            if not name:
                continue
            rest = tok[m.end() :] if m else ""
            out.setdefault(
                name.lower(),
                ParsedLanguage(
                    language=name,
                    proficiency=_proficiency(rest),
                    confidence=0.8 if _proficiency(rest) else 0.7,
                ),
            )
    return list(out.values())


# --- summary / headline / years ----------------------------------------------------------------------------------------------

_STATED_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})(?:\.\d)?\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)['’]?\s*(?:of\s+)?(?:(?:[A-Za-z\-]+)\s+){0,3}?experience",
    re.IGNORECASE,
)


def _stated_years(text: str) -> float | None:
    values = [float(m.group(1)) for m in _STATED_YEARS.finditer(text) if 0 < float(m.group(1)) <= 60]
    return max(values) if values else None


def _estimate_years(
    experiences: Sequence[ParsedExperience], text: str, today: date
) -> YearsOfExperience | None:
    items = [
        ExperienceItem(e.title or "", e.company or "", e.start_date, e.end_date)
        for e in experiences
        if e.start_date
    ]
    computed = total_years_of_experience(items, today) if items else None
    stated = _stated_years(text)
    if computed is not None and computed > 0:
        return YearsOfExperience(
            value=min(computed, 70.0), basis="employment_history", computed=computed, stated=stated
        )
    if stated is not None:
        return YearsOfExperience(value=min(stated, 70.0), basis="stated", computed=computed, stated=stated)
    return None


def _headline(
    zone: Sequence[str], name_idx: int | None, experiences: Sequence[ParsedExperience]
) -> tuple[str | None, float | None]:
    start = (name_idx + 1) if name_idx is not None else 0
    for line in zone[start : start + 4]:
        first = _clean_piece(re.split(r"\s*[|•·]\s*|\s+[–—]\s+", line.strip())[0])
        if (
            first
            and 3 <= len(first) <= 120
            and _title_word_count(first)
            and "@" not in first
            and not any(ch.isdigit() for ch in first)
        ):
            return first[:200], 0.7
    for e in experiences:
        if e.title:
            return e.title[:200], 0.5
    return None, None


# --- orchestration --------------------------------------------------------------------------------------------------------------


def extract_skills_from_text(text: str):  # type: ignore[no-untyped-def]
    """Convenience for tests / callers with raw text: sections the text, then mines skills."""
    lines = split_lines(text)
    _, content, owner = split_sections(lines)
    return extract_skills(content, owner)


def _guard(name: str, warnings: list[str], fn, default):  # type: ignore[no-untyped-def]
    try:
        return fn()
    except Exception as exc:  # parser bugs must never fail a résumé; the part is dropped and flagged
        logger.error("resume parser step failed", extra={"step": name, "error": type(exc).__name__})
        warnings.append(f"{name.upper()}_PARSE_FAILED")
        return default


def parse_resume(text: str, *, links: Sequence[str] = (), today: date | None = None) -> ParsedResume:
    """Parse extracted résumé text into suggestions. ``links`` are hyperlink targets found in the document."""
    today = today or date.today()
    warnings: list[str] = []
    lines = split_lines(text)
    sections, content, owner = split_sections(lines)
    header_lines = [ln for ln in sections[0].lines if ln.strip()][:HEADER_ZONE_LINES]
    zone = header_lines if header_lines else [ln for ln in lines if ln.strip()][:HEADER_ZONE_LINES]

    contact, name_idx = _guard(
        "contact", warnings, lambda: extract_contact(lines, links, zone), (ParsedContact(), None)
    )
    experiences = _guard(
        "experience", warnings, lambda: parse_experiences(_section_lines(sections, "experience"), today), []
    )
    educations = _guard(
        "education", warnings, lambda: parse_educations(_section_lines(sections, "education"), today), []
    )
    certifications = _guard(
        "certification",
        warnings,
        lambda: parse_certifications(
            _section_lines(sections, "certifications"),
            [ln for ln, o in zip(content, owner, strict=True) if o != "ignored"],
        ),
        [],
    )
    languages = _guard(
        "language", warnings, lambda: parse_languages(_section_lines(sections, "languages")), []
    )
    skills = _guard("skills", warnings, lambda: extract_skills(content, owner), [])
    summary_lines = [ln for ln in _section_lines(sections, "summary") if ln.strip()]
    summary = " ".join(strip_bullet(ln) for ln in summary_lines)[:MAX_SUMMARY_CHARS] or None
    years = _guard("years", warnings, lambda: _estimate_years(experiences, text, today), None)
    headline, headline_conf = _guard(
        "headline", warnings, lambda: _headline(zone, name_idx, experiences), (None, None)
    )

    present = [
        s.key for s in sections if s.key not in ("header", "ignored") and any(ln.strip() for ln in s.lines)
    ]
    if not experiences and "experience" not in present:
        warnings.append("NO_EXPERIENCE_SECTION")
    if any(e.start_date is None for e in experiences):
        warnings.append("SOME_EXPERIENCE_WITHOUT_DATES")
    return ParsedResume(
        contact=contact,
        headline=headline,
        headline_confidence=headline_conf,
        summary=summary,
        skills=skills,
        experiences=experiences,
        educations=educations,
        certifications=certifications,
        languages=languages,
        years_of_experience=years,
        sections=list(dict.fromkeys(present)),
        warnings=warnings,
    )


_ = (EducationLevel,)  # the level strings emitted above are EducationLevel values (asserted in tests)
