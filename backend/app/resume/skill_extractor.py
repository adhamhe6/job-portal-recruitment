"""Ontology-driven skill mining for résumé text.

The skill list is ``app.matching.skills.ONTOLOGY`` (canonical names + aliases). Matching is a single compiled,
word-boundary regex that understands ``C++``, ``C#``, ``.NET``, ``Node.js``, ``CI/CD`` and friends and prefers the
longest term at a position (``React Native`` beats ``React``).

Precision rules (the point of this module — résumés are full of words like *Go*, *R*, *Excel*, *react*, *rest*):

* **Ambiguous skills** (``ambiguous=True`` in the ontology: Go, R, C, Rust, Swift, Ruby, Flask, Express, Excel, Spark …)
  are accepted **only in a skills-like context**: inside a Skills section, or on a list line (comma / pipe / bullet
  separated) where at least three tokens — and most of the line — are recognised skills. A bare "Go" or "Golang" inside a
  sentence is not enough.
* **Weak terms** (common English words that are also aliases: ``rest``, ``lean``, ``monitoring`` …) follow the same
  rule; short aliases (``ml``, ``hr``, ``js`` …) are accepted in prose only when written in upper case; a few
  capitalised names (``React``, ``Vue``, ``Bash`` …) only when capitalised.
* Emails and URLs are blanked out before matching, so ``john.react@x.com`` or ``github.com/u/go-tools`` add nothing.

Confidence is a heuristic, not a probability: higher when the skill is listed, lower when only mentioned in prose,
rising a little with repeated mentions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from app.matching.skills import ONTOLOGY, OntologySkill
from app.resume.lexicon import SKILL_EXCLUDED_SECTIONS
from app.resume.parsed import ParsedSkill

MAX_SKILLS = 60
LIST_MIN_SKILL_TOKENS = 3
LIST_MIN_RATIO = 0.6

# Accepted only in a skills-like context.
WEAK_WORDS = frozenset(
    {
        "spring",
        "rest",
        "node",
        "lean",
        "epic",
        "shell",
        "lambda",
        "torch",
        "elk",
        "documentation",
        "monitoring",
        "security",
        "analytics",
        "coaching",
        "sourcing",
        "forecasting",
        "presentations",
        "logistics",
        "procurement",
        "prospecting",
        "branding",
        "transformers",
        "dbt",
    }
)
# Short aliases: in prose they must be written in upper case (or exactly as in the ontology).
WEAK_SHORT = frozenset({"ml", "hr", "tf", "sh", "py", "js", "ts", "ux", "icu", "s3", "ec2", "sap", "ga4"})
# Common English words that are also technology names: in prose they must be capitalised.
CAPITAL_ONLY = frozenset(
    {"react", "angular", "vue", "bash", "dart", "elixir", "looker", "confluence", "sass"}
)

_SPACE_RUN = re.compile(r"[\s\-]+")
_SLASH_SPACES = re.compile(r"\s*/\s*")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
# Only unmistakable URLs: a bare "asp.net" or "node.js" must stay matchable as a skill.
_URL = re.compile(
    r"(?:https?://|www\.)\S+|\b(?:github|gitlab|bitbucket|linkedin|twitter|medium)\.com/\S*", re.IGNORECASE
)
_LIST_SEP = re.compile(r"[,;|•·▪●◦‣⁃•\t]+|\s{3,}")
_LABEL = re.compile(r"^\s*[A-Za-z][A-Za-z &/+#.\-]{1,35}:\s+")
_PAREN = re.compile(r"\([^)]*\)")
_TRAILING_ETC = re.compile(r"\b(?:etc\.?|and more|others?)\s*$", re.IGNORECASE)
_LEADING_AND = re.compile(r"^(?:and|&)\s+", re.IGNORECASE)


def norm_term(text: str) -> str:
    """Comparison form of a term / matched text: case-folded, hyphens and blanks collapsed, slashes unspaced."""
    return _SPACE_RUN.sub(" ", _SLASH_SPACES.sub("/", text.casefold())).strip()


def _term_regex(term: str) -> str:
    pieces: list[str] = []
    for part in re.split(r"([\s\-]+|/)", term):
        if not part:
            continue
        if part == "/":
            pieces.append(r"\s*/\s*")
        elif part.strip(" -") == "":
            pieces.append(r"[\s\-]+")
        else:
            pieces.append(re.escape(part))
    body = "".join(pieces)
    tail = r"(?![A-Za-z0-9_@])" if term[-1] in "+#" else r"(?![A-Za-z0-9_+#&@])"
    return body + tail


@dataclass(frozen=True, slots=True)
class _Matcher:
    regex: re.Pattern[str]
    skills: dict[str, OntologySkill]  # norm_term -> skill


def _build() -> _Matcher:
    by_norm: dict[str, OntologySkill] = {}
    for skill in ONTOLOGY:
        for term in (skill.name, *skill.aliases):
            by_norm.setdefault(norm_term(term), skill)
    terms = sorted({t for s in ONTOLOGY for t in (s.name, *s.aliases)}, key=len, reverse=True)
    pattern = r"(?<![A-Za-z0-9_@])(?:" + "|".join(_term_regex(t) for t in terms) + ")"
    return _Matcher(re.compile(pattern, re.IGNORECASE), by_norm)


_MATCHER = _build()


def blank_contacts(line: str) -> str:
    """Replace e-mail addresses and URLs by spaces (same length) so they cannot produce skill matches."""
    return _URL.sub(lambda m: " " * len(m.group(0)), _EMAIL.sub(lambda m: " " * len(m.group(0)), line))


def _token_skills(token: str) -> int:
    """Number of skills a single list token consists of entirely (0 when it is not just a skill name)."""
    tok = _PAREN.sub(" ", token).strip(" .:-–—*")
    tok = _TRAILING_ETC.sub("", tok).strip(" .")
    tok = _LEADING_AND.sub("", tok).strip()
    if not tok:
        return 0
    if norm_term(tok) in _MATCHER.skills:
        return 1
    parts = [p for p in re.split(r"\s*/\s*", tok) if p]
    if len(parts) > 1 and all(norm_term(p) in _MATCHER.skills for p in parts):
        return len(parts)
    return 0


def is_skill_list_line(line: str) -> bool:
    """True when ``line`` looks like an enumeration of skills (so ambiguous names in it can be trusted)."""
    text = _LABEL.sub("", line, count=1)
    tokens = [t for t in _LIST_SEP.split(text) if t.strip()]
    if len(tokens) < LIST_MIN_SKILL_TOKENS:
        return False
    skill_tokens = sum(1 for t in tokens if _token_skills(t) > 0)
    skills = sum(_token_skills(t) for t in tokens)
    return skills >= LIST_MIN_SKILL_TOKENS and skill_tokens / len(tokens) >= LIST_MIN_RATIO


def _hyphen_compound(line: str, start: int, end: int) -> bool:
    """``go-getter`` / ``R-squared``: the match is one half of a hyphenated word, not a skill mention."""
    before = line[start - 1] if start > 0 else ""
    after = line[end] if end < len(line) else ""
    nxt = line[end + 1] if end + 1 < len(line) else ""
    prev = line[start - 2] if start > 1 else ""
    return (after == "-" and nxt.isalnum()) or (before == "-" and prev.isalnum())


def _accept(skill: OntologySkill, matched: str, line: str, start: int, end: int, in_context: bool) -> bool:
    key = norm_term(matched)
    if in_context:
        return not (skill.ambiguous and _hyphen_compound(line, start, end))
    if skill.ambiguous or key in WEAK_WORDS:
        return False
    if key in WEAK_SHORT and not (matched.isupper() or matched == skill.name):
        return False
    return not (key in CAPITAL_ONLY and not matched[0].isupper())


def extract_skills(lines: Sequence[str], line_sections: Sequence[str]) -> list[ParsedSkill]:
    """Mine skills from ``lines``; ``line_sections[i]`` is the section key of ``lines[i]`` (``"skills"``, ``"experience"`` …)."""
    mentions: dict[str, int] = defaultdict(int)
    listed: dict[str, bool] = defaultdict(bool)
    ambiguous: dict[str, bool] = {}
    for line, section in zip(lines, line_sections, strict=True):
        if not line.strip() or section in SKILL_EXCLUDED_SECTIONS:
            continue
        text = blank_contacts(line)
        in_context = section == "skills" or is_skill_list_line(text)
        for m in _MATCHER.regex.finditer(text):
            skill = _MATCHER.skills.get(norm_term(m.group(0)))
            if skill is None or not _accept(skill, m.group(0), text, m.start(), m.end(), in_context):
                continue
            mentions[skill.name] += 1
            ambiguous[skill.name] = skill.ambiguous
            if in_context:
                listed[skill.name] = True
    out = [
        ParsedSkill(
            name=name,
            confidence=_confidence(count, listed[name], ambiguous[name]),
            mentions=count,
            listed=listed[name],
        )
        for name, count in mentions.items()
    ]
    out.sort(key=lambda s: (-s.confidence, -s.mentions, s.name.lower()))
    return out[:MAX_SKILLS]


def _confidence(mentions: int, listed: bool, ambiguous: bool) -> float:
    if listed:
        base = 0.8 if ambiguous else 0.9
        bonus = 0.05 if mentions >= 2 else 0.0
        return round(min(base + bonus, 0.98), 2)
    return round({1: 0.55, 2: 0.65}.get(mentions, 0.75), 2)
