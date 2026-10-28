"""Format rules shared with the app (plan D8, data_schema.md).

Each function is a port of the app's Dart rule named in its docstring, and
all of them are asserted against scraper/rule_cases.json (a copy of the
app's tools/rule_cases.json). Python and Dart regexes differ in two ways
that matter here, so every pattern below:

- spells digits as ``[0-9]`` (Python's ``\\d`` also matches full-width digits);
- is applied with ``re.fullmatch`` (Python's ``$`` also matches before a
  trailing newline).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

FIELD_IDS: tuple[str, ...] = (
    "it", "office", "medical", "care", "design", "building", "manufacturing", "other",
)
KINDS: tuple[str, ...] = ("public", "kyushoku")
ORIGINS: tuple[str, ...] = ("hwis", "override")

ALLOWED_DOMAINS: tuple[str, ...] = (
    "hellowork.mhlw.go.jp",
    "jsite.mhlw.go.jp",
    "hataraku.metro.tokyo.lg.jp",
)

TEXT_LIMITS: dict[str, int] = {
    "name": 100,
    "city": 40,
    "address": 120,
    "hours": 80,
    "selfCost": 80,
    "conditions": 300,
    "provider": 100,
    "sourceName": 60,
    "targetCourse": 100,
    "sourceUrl": 500,
}

SUPPORTED_SCHEMA_VERSION = 1
MAX_META_BYTES = 64 * 1024
MAX_PREF_BYTES = 1024 * 1024
MAX_COURSES_PER_FILE = 2000
MAX_ROUNDS = 3
MAX_FIELDS_PER_COURSE = 8
MAX_TARGET_COURSES = 20
MAX_CAPACITY = 999
MAX_FUTURE_SKEW = timedelta(days=7)

PREF_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 48))


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, the unit of Dart's ``String.length``."""
    return len(text.encode("utf-16-le")) // 2


# --- URLs (url_rules.dart hostAllowed) ---------------------------------------

_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*):")
_AUTHORITY = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://([^/?#]*)")
_ASCII_HOST_CHARS = re.compile(r"[A-Za-z0-9.-]+")
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def url_scheme(url: str) -> str:
    """Lowercased scheme read from the raw text, or '' when there is none."""
    match = _SCHEME.match(url)
    return match.group(1).lower() if match else ""


def host_allowed(url: str, domains: tuple[str, ...] | list[str] = ALLOWED_DOMAINS) -> bool:
    """True for an https URL whose host is, or is under, one of ``domains``.

    Decided on the raw text like the Dart rule: the authority (between
    ``://`` and the first ``/``, ``?`` or ``#``) must be a plain ASCII host,
    so userinfo, ports, ``%``, ``\\``, control or non-ASCII characters, empty
    labels and a trailing dot are rejected. ``urlsplit`` is not used because
    it drops tabs and newlines.
    """
    if url_scheme(url) != "https":
        return False
    match = _AUTHORITY.match(url)
    if match is None:
        return False
    authority = match.group(1)
    if not _ASCII_HOST_CHARS.fullmatch(authority):
        return False
    host = authority.lower()
    if not _HOST.fullmatch(host):
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


# --- Phones (phone_rules.dart phoneOk) ----------------------------------------

_JAPANESE_PHONE = re.compile(r"0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}")
_REFUSED_PHONE = re.compile(r"(?:00|010|0990)")


def phone_ok(phone: str) -> bool:
    """Japanese number in the data format: ``0`` + three hyphenated groups,
    10 or 11 half-width digits, never ``00…``, ``010…`` or ``0990…``."""
    if not _JAPANESE_PHONE.fullmatch(phone) or _REFUSED_PHONE.match(phone):
        return False
    digits = len(phone) - phone.count("-")
    return 10 <= digits <= 11


# --- Text (text_phone_rules.dart textOk) --------------------------------------


def _is_hidden(char: str) -> bool:
    category = unicodedata.category(char)
    if category == "Cc":
        return char != "\n"
    if category in ("Cf", "Zl", "Zp"):
        return True
    return category == "Zs" and char not in (" ", "　")


def _is_foreign_digit(char: str) -> bool:
    return unicodedata.category(char) == "Nd" and not ("0" <= char <= "9")


def non_ascii_digits(text: str) -> list[str]:
    """Every decimal digit in ``text`` that is not ASCII 0-9."""
    return [c for c in text if _is_foreign_digit(c)]


def hidden_characters(text: str) -> list[str]:
    """Hidden characters in ``text`` as ``U+XXXX``."""
    return [f"U+{ord(c):04X}" for c in text if _is_hidden(c)]


def text_ok(text: str) -> bool:
    """No non-ASCII decimal digit and no hidden character (LF allowed)."""
    return not any(_is_foreign_digit(c) or _is_hidden(c) for c in text)


# --- Dates (calendar_date.dart) -----------------------------------------------

_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_ISO_INSTANT = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?"
    r"(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
_YEAR_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


def parse_iso_date(value: object) -> date | None:
    """Strict ``YYYY-MM-DD`` real calendar day (year ≥ 1), else None."""
    if not isinstance(value, str):
        return None
    match = _ISO_DATE.fullmatch(value)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_iso_instant(value: object) -> datetime | None:
    """Strict ISO 8601 instant with an explicit offset, as UTC, else None."""
    if not isinstance(value, str):
        return None
    match = _ISO_INSTANT.fullmatch(value)
    if match is None or parse_iso_date(match.group(1)) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def is_year_month(value: object) -> bool:
    """``YYYY-MM`` with a month 01-12 (``entryMonth``)."""
    return isinstance(value, str) and _YEAR_MONTH.fullmatch(value) is not None


def is_too_far_ahead(instant: datetime, now: datetime) -> bool:
    """True when ``instant`` is more than seven days after ``now``."""
    return instant > now + MAX_FUTURE_SKEW


# --- Ids (course_rules.dart courseIdOk) ---------------------------------------

_HWIS_ID = re.compile(r"[0-9]{2}-[0-9]{2}-([0-9]{2})-[0-9]{4}")
_TOKYO_ID = re.compile(r"tokyo-[a-z0-9-]{1,48}")


def course_id_ok(course_id: str, pref: str, origin: str) -> bool:
    """HWIS id whose third group is ``pref``; ``tokyo-…`` only for overrides in 13."""
    if origin == "hwis":
        match = _HWIS_ID.fullmatch(course_id)
        return match is not None and match.group(1) == pref
    if origin == "override":
        return pref == "13" and _TOKYO_ID.fullmatch(course_id) is not None
    return False


# --- Rounds (course_rules.dart roundProblems) ---------------------------------


@dataclass(frozen=True)
class Round:
    """One 募集期間 round."""

    no: int
    start: date
    end: date


def round_problems(rounds: list[Round]) -> list[str]:
    """1-3 rounds, ``no`` 1-3 strictly ascending, ``start ≤ end``, and
    neither date goes back from the previous round (touching and
    overlapping rounds pass)."""
    problems: list[str] = []
    if not rounds:
        problems.append("rounds: at least one round")
    if len(rounds) > MAX_ROUNDS:
        problems.append(f"rounds: over {MAX_ROUNDS}")
    previous: Round | None = None
    for i, current in enumerate(rounds):
        if not 1 <= current.no <= MAX_ROUNDS:
            problems.append(f"rounds[{i}].no: 1 to {MAX_ROUNDS}")
        if current.start > current.end:
            problems.append(f"rounds[{i}]: start is after end")
        if previous is not None and (
            current.no <= previous.no or current.start < previous.start or current.end < previous.end
        ):
            problems.append(f"rounds[{i}]: goes back from round {previous.no}")
        previous = current
    return problems
