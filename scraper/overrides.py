"""東京 予告 overrides (research §3.1, plan Phase 1 and Phase 9).

``overrides.json`` (repository root) holds hand-made 予告 entries for
pref 13, written by people from 東京労働局 and TOKYOはたらくネット pages:
``{"entries": [<course object with origin "override">, …]}``. Every entry
must pass the same validator as the published file.

At merge time an entry is hidden once HWIS lists the same school (one
NFKC name contains the other) with a course starting in the entry's
``entryMonth``; rounds that ended before today are dropped, and an entry
with no round left is skipped.

    python -m scraper.overrides --check [overrides.json]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scraper.validate import course_problems

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "overrides.json"
TOKYO = "13"
_PREFIXES = ("東京都立", "都立")


@dataclass(frozen=True)
class Loaded:
    entries: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Merged:
    added: list[dict]
    hidden: list[str]
    expired: list[str]


def _entry_problems(index: int, item: object, seen: set[str]) -> list[str]:
    if not isinstance(item, dict):
        return [f"entries[{index}]: expected object"]
    problems = [f"entries[{index}].{p}" for p in course_problems(item, TOKYO)]
    if item.get("origin") != "override":
        problems.append(f"entries[{index}].origin: must be override")
    course_id = item.get("id")
    if course_id in seen:
        problems.append(f"entries[{index}].id: repeated {course_id}")
    seen.add(str(course_id))
    return problems


def load(path: Path = DEFAULT_PATH) -> Loaded:
    """Entries of ``path`` when every one is valid; a missing file is empty."""
    if not path.exists():
        return Loaded()
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return Loaded(problems=[f"{path.name}: JSON syntax: {error}"])
    entries = root.get("entries") if isinstance(root, dict) else None
    if not isinstance(entries, list):
        return Loaded(problems=[f"{path.name}: expected {{\"entries\": [...]}}"])
    seen: set[str] = set()
    problems = [p for i, item in enumerate(entries) for p in _entry_problems(i, item, seen)]
    return Loaded(entries=[] if problems else entries, problems=problems)


def _school(name: str | None) -> str:
    text = "".join(unicodedata.normalize("NFKC", name or "").split())
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _same_school(notice: dict, course: dict) -> bool:
    a, b = _school(notice.get("name")), _school(course.get("provider"))
    return bool(a and b) and (a in b or b in a)


def _hidden_by(notice: dict, hwis_courses: list[dict]) -> bool:
    month = notice.get("entryMonth")
    return any(
        _same_school(notice, course) and (course.get("trainingStart") or "")[:7] == month
        for course in hwis_courses
    )


def merge(hwis_courses: list[dict], entries: list[dict], *, today: date) -> Merged:
    """Entries to add to pref 13 (copies), and the ids hidden or expired."""
    added: list[dict] = []
    hidden: list[str] = []
    expired: list[str] = []
    for item in entries:
        if _hidden_by(item, hwis_courses):
            hidden.append(item["id"])
            continue
        rounds = [r for r in item["rounds"] if date.fromisoformat(r["end"]) >= today]
        if not rounds:
            expired.append(item["id"])
            continue
        notice = copy.deepcopy(item)
        notice["rounds"] = copy.deepcopy(rounds)
        added.append(notice)
    return Merged(added=added, hidden=hidden, expired=expired)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check overrides.json")
    parser.add_argument("--check", action="store_true", help="validate and exit")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)
    loaded = load(Path(args.path))
    for problem in loaded.problems:
        print(problem)
    if loaded.problems:
        return 1
    print(f"ok: {len(loaded.entries)} entries")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
