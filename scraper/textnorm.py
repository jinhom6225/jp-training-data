"""Text helpers for HWIS pages: NFKC, whitespace and Japanese dates."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import lxml.html

from scraper.errors import StructureError

_SPACE = re.compile(r"\s+")
_JAPANESE_DATE = re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日")
_PARSER = lxml.html.HTMLParser(encoding="utf-8")


def parse_html(content: bytes) -> lxml.html.HtmlElement:
    """HWIS pages are UTF-8; lxml would otherwise guess the encoding."""
    try:
        return lxml.html.fromstring(content, parser=_PARSER)
    except (ValueError, lxml.etree.ParserError) as error:
        raise StructureError(f"not an HTML page: {error}") from error


def _visible(char: str) -> bool:
    return unicodedata.category(char) not in ("Cf", "Cc")


def normalize(text: str | None) -> str | None:
    """NFKC (全角 → 半角 digits and letters), whitespace runs (NBSP, line
    breaks, U+3000 …) → one space, invisible format and control characters
    removed, trimmed; None when nothing is left. The data files carry
    one-line text that passes the app's text rule."""
    if text is None:
        return None
    spaced = _SPACE.sub(" ", unicodedata.normalize("NFKC", text))
    flat = "".join(c for c in spaced if _visible(c)).strip()
    return flat or None


def element_text(element: lxml.html.HtmlElement | None) -> str | None:
    """Normalized text content of ``element``."""
    return None if element is None else normalize(element.text_content())


def japanese_date(text: str | None) -> date | None:
    """``2026年1月5日`` (after NFKC) → date; None for anything else."""
    if text is None:
        return None
    match = _JAPANESE_DATE.search(unicodedata.normalize("NFKC", text))
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def all_japanese_dates(text: str) -> list[str]:
    """Every ``YYYY年M月D日`` substring of ``text`` (after NFKC)."""
    return [m.group(0) for m in _JAPANESE_DATE.finditer(unicodedata.normalize("NFKC", text))]
