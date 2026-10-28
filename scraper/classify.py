"""Field classification (research §3.3) driven by fields.yml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from scraper.rules import FIELD_IDS

TABLE_PATH = Path(__file__).with_name("fields.yml")
_CONSUMED = "\u0000"


@dataclass(frozen=True)
class Category:
    match: str
    fields: tuple[str, ...]
    broad: bool = False


@dataclass(frozen=True)
class Table:
    categories: tuple[Category, ...]
    keywords: dict[str, tuple[str, ...]]
    # keyword → fields, longest keyword first
    ordered: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...]


def _check_fields(fields: list[str], where: str) -> tuple[str, ...]:
    unknown = [f for f in fields if f not in FIELD_IDS or f == "other"]
    if unknown:
        raise ValueError(f"{where}: unknown field ids {unknown}")
    return tuple(fields)


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    if keyword.isascii():
        body = re.escape(keyword)
        if len(keyword) <= 2:
            body = rf"(?<![A-Za-z]){body}(?![A-Za-z])"
        return re.compile(body, re.IGNORECASE)
    return re.compile(re.escape(keyword))


def load_table(path: Path = TABLE_PATH) -> Table:
    """Read and check fields.yml."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categories = tuple(
        Category(c["match"], _check_fields(c["fields"], f"category {c['match']}"), bool(c.get("broad")))
        for c in raw.get("categories") or []
    )
    keywords = {
        field: tuple(words or [])
        for field, words in (raw.get("keywords") or {}).items()
    }
    _check_fields(list(keywords), "keywords")
    by_keyword: dict[str, set[str]] = {}
    for field, words in keywords.items():
        for word in words:
            by_keyword.setdefault(word, set()).add(field)
    ordered = tuple(
        (word, _keyword_pattern(word), tuple(sorted(fields, key=FIELD_IDS.index)))
        for word, fields in sorted(by_keyword.items(), key=lambda item: (-len(item[0]), item[0]))
    )
    return Table(categories=categories, keywords=keywords, ordered=ordered)


@lru_cache(maxsize=1)
def _default_table() -> Table:
    return load_table()


def _name_fields(name: str, table: Table) -> set[str]:
    found: set[str] = set()
    rest = name
    for _word, pattern, fields in table.ordered:
        if pattern.search(rest):
            found.update(fields)
            rest = pattern.sub(_CONSUMED, rest)
    return found


def classify(name: str, category: str | None, table: Table | None = None) -> list[str]:
    """Field ids of a course, in canonical order; ``["other"]`` when no
    category or keyword matches."""
    table = table or _default_table()
    exact: set[str] = set()
    broad: set[str] = set()
    rest = category or ""
    for item in sorted(table.categories, key=lambda c: -len(c.match)):
        if item.match in rest:
            (broad if item.broad else exact).update(item.fields)
            rest = rest.replace(item.match, _CONSUMED)
    from_name = _name_fields(name, table)
    fields = exact | from_name or broad
    if not fields:
        return ["other"]
    return sorted(fields, key=FIELD_IDS.index)
