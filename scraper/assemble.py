"""Which details to fetch and how a run's course list is put together.

Detail targets (plan Phase 1 run order):

- full mode (first run, weekly refresh): every listed course;
- normal mode: new courses, courses whose list values (name, 開講日,
  募集状況) differ from the previous publish, courses with a round ending
  within 14 days, and every course of a prefecture whose previous file
  could not be read;
- D7 recheck: a previously published HWIS course that is still open but
  missing from the list. It is kept only if its detail page still shows a
  round ending today or later.

A listed course that was not fetched, or whose fetch failed, keeps its
previous record (a copy with the current childcare flag). Courses whose
rounds all ended are dropped, and so is any course that breaks the app's
rules (logged with the reason).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from scraper.collect import DetailResult
from scraper.parse_list import ListRow
from scraper.record import build_course, clip, last_end
from scraper.rules import TEXT_LIMITS
from scraper.validate import course_problems

log = logging.getLogger(__name__)
NEAR_DEADLINE_DAYS = 14


@dataclass(frozen=True)
class Targets:
    fetch: list[str]
    recheck: list[str]


@dataclass(frozen=True)
class Assembly:
    courses: dict[str, list[dict]]
    built: int
    reused: int
    missing: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    ended: list[str] = field(default_factory=list)
    invalid: dict[str, list[str]] = field(default_factory=dict)


def _rounds(course: dict) -> list[tuple[date, date]]:
    return [(date.fromisoformat(r["start"]), date.fromisoformat(r["end"])) for r in course["rounds"]]


def status_on(course: dict, today: date) -> str | None:
    """募集中 / 募集前 / None (ended) of a published course on ``today``."""
    rounds = _rounds(course)
    if any(start <= today <= end for start, end in rounds):
        return "募集中"
    if any(start > today for start, _ in rounds):
        return "募集前"
    return None


def _changed(row: ListRow, course: dict, today: date) -> bool:
    if clip(row.name, TEXT_LIMITS["name"]) != course["name"]:
        return True
    if row.opening is not None and row.opening.isoformat() != course.get("trainingStart"):
        return True
    return row.status in ("募集中", "募集前") and row.status != status_on(course, today)


def _near_deadline(course: dict, today: date) -> bool:
    horizon = today + timedelta(days=NEAR_DEADLINE_DAYS)
    return any(today <= end <= horizon for _, end in _rounds(course))


def detail_targets(
    rows: dict[str, ListRow],
    previous: dict[str, dict],
    unknown_prefs: set[str],
    today: date,
    *,
    full: bool,
) -> Targets:
    """Ids to fetch, and previous ids to recheck (D7)."""
    fetch = []
    for course_id in sorted(rows):
        course = previous.get(course_id)
        if (
            full
            or course is None
            or rows[course_id].pref in unknown_prefs
            or _changed(rows[course_id], course, today)
            or _near_deadline(course, today)
        ):
            fetch.append(course_id)
    recheck = sorted(
        course_id for course_id, course in previous.items()
        if course_id not in rows and course["origin"] == "hwis" and last_end(course) >= today
    )
    return Targets(fetch=fetch, recheck=recheck)


def _reuse(course: dict, childcare: set[str] | None) -> dict:
    copied = copy.deepcopy(course)
    if childcare is not None:
        copied["childcare"] = course["id"] in childcare or "託児" in course["name"]
    return copied


def assemble(
    rows: dict[str, ListRow],
    previous: dict[str, dict],
    fetched: DetailResult,
    *,
    childcare: set[str] | None,
    today: date,
    recheck: list[str],
) -> Assembly:
    """Courses per prefecture code for this run."""
    picked: dict[str, dict] = {}
    built = reused = 0
    missing: list[str] = []
    for course_id in sorted(set(rows) | set(recheck)):
        row = rows.get(course_id)
        detail = fetched.details.get(course_id)
        if detail is not None:
            picked[course_id] = build_course(
                course_id, detail,
                childcare=childcare is not None and course_id in childcare,
                checked_at=fetched.fetched_at[course_id], today=today,
                fallback_kind=row.kind if row else None,
                fallback_address=row.address if row else None,
            )
            built += 1
        elif row is not None and course_id in previous and course_id not in fetched.gone:
            picked[course_id] = _reuse(previous[course_id], childcare)
            reused += 1
        elif row is not None and course_id not in fetched.gone:
            missing.append(course_id)
    courses: dict[str, list[dict]] = {}
    ended: list[str] = []
    invalid: dict[str, list[str]] = {}
    for course_id, course in picked.items():
        pref = course_id.split("-")[2]
        if last_end(course) < today:
            ended.append(course_id)
            continue
        problems = course_problems(course, pref)
        if problems:
            invalid[course_id] = problems
            log.warning("dropping %s: %s", course_id, "; ".join(problems))
            continue
        courses.setdefault(pref, []).append(course)
    return Assembly(courses=courses, built=built, reused=reused, missing=missing,
                    gone=sorted(fetched.gone), ended=ended, invalid=invalid)
