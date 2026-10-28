"""The published site: pref/01..47.json, meta.json and stats.json.

``meta.json`` carries only the schema keys (data_schema.md) so the app
logs no unknown-key warnings; the run's statistics (counts per field,
``other`` ratio, detail failures) go to ``stats.json`` next to it.

Every file is checked with the app's rules before anything is written, so
a run either writes a complete valid site or nothing.

The previous publish is the comparison base (plan D2): ``load_previous``
downloads it from Pages at the start of a run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scraper.rules import FIELD_IDS, PREF_CODES, SUPPORTED_SCHEMA_VERSION
from scraper.validate import validate_meta_text, validate_pref_text


class PublishError(Exception):
    """A file would break the app's rules; nothing was written."""


@dataclass(frozen=True)
class Previous:
    """The last published site."""

    generated_at: str
    counts: dict[str, int]
    courses: dict[str, list[dict]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _stats(courses: dict[str, list[dict]], generated_at: str, report: dict) -> dict:
    flat = [c for code in PREF_CODES for c in courses.get(code, [])]
    by_field = {f: sum(1 for c in flat if f in c["fields"]) for f in FIELD_IDS}
    other = sum(1 for c in flat if c["fields"] == ["other"])
    return {
        "generatedAt": generated_at,
        "total": len(flat),
        "byPref": {code: len(courses.get(code, [])) for code in PREF_CODES},
        "byKind": {k: sum(1 for c in flat if c["kind"] == k) for k in ("public", "kyushoku")},
        "byField": by_field,
        "otherRatio": round(other / len(flat), 4) if flat else 0.0,
        "overrides": sum(1 for c in flat if c["origin"] == "override"),
        **report,
    }


def write_site(out: Path, courses: dict[str, list[dict]], *, generated_at: datetime, report: dict) -> dict:
    """Write the site under ``out``; returns the stats."""
    stamp = generated_at.isoformat(timespec="seconds")
    check_now = generated_at.astimezone(timezone.utc)
    files: dict[Path, str] = {}
    problems: list[str] = []
    for code in PREF_CODES:
        listed = sorted(courses.get(code, []), key=lambda c: c["id"])
        text = _dump({"schemaVersion": SUPPORTED_SCHEMA_VERSION, "pref": code, "generatedAt": stamp, "courses": listed})
        problems += [f"pref/{code}.json: {p}" for p in validate_pref_text(text, expected_pref=code, now=check_now)]
        files[out / "pref" / f"{code}.json"] = text
    meta = {
        "schemaVersion": SUPPORTED_SCHEMA_VERSION,
        "generatedAt": stamp,
        "prefs": {code: {"count": len(courses.get(code, [])), "generatedAt": stamp} for code in PREF_CODES},
    }
    meta_text = _dump(meta)
    problems += [f"meta.json: {p}" for p in validate_meta_text(meta_text, now=check_now)]
    if problems:
        raise PublishError("; ".join(problems[:10]))
    stats = _stats(courses, stamp, report)
    files[out / "meta.json"] = meta_text
    files[out / "stats.json"] = json.dumps(stats, ensure_ascii=False, indent=1)
    (out / "pref").mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    return stats


def load_previous(base_url: str, fetch: Callable[[str], bytes | None], *, now: datetime) -> Previous | None:
    """The last published site at ``base_url``, or None on a first run.

    A pref file that is missing or breaks the rules is listed in
    ``missing`` (its count still comes from meta) so the run treats its
    courses as unknown instead of comparing with bad data."""
    if not base_url:
        return None
    base = base_url.rstrip("/") + "/"
    meta_bytes = fetch(base + "meta.json")
    if meta_bytes is None:
        return None
    check_now = now.astimezone(timezone.utc)
    meta_text = meta_bytes.decode("utf-8", errors="replace")
    if validate_meta_text(meta_text, now=check_now):
        return None
    meta = json.loads(meta_text)
    counts = {code: entry["count"] for code, entry in meta["prefs"].items()}
    courses: dict[str, list[dict]] = {}
    missing: list[str] = []
    for code in sorted(counts):
        raw = fetch(f"{base}pref/{code}.json")
        text = raw.decode("utf-8", errors="replace") if raw is not None else ""
        if raw is None or validate_pref_text(text, expected_pref=code, now=check_now):
            missing.append(code)
            continue
        courses[code] = json.loads(text)["courses"]
    return Previous(generated_at=meta["generatedAt"], counts=counts, courses=courses, missing=missing)
