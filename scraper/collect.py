"""Collection steps over ``HwisClient`` (plan Phase 1 run order).

- ``collect_lists``: one search per prefecture with both course types
  (公共職業訓練 + 求職者支援訓練) and the default 募集期間 (today onward, so
  募集中 + 募集前), paged with 次へ. A failed search is retried once with a
  new session; a second failure is reported as a structure error.
- ``collect_childcare``: the national 託児サービスあり search → course ids.
- ``fetch_details``: detail pages one by one; a broken page is retried once.

``Cache`` keeps list rows and raw detail pages on disk so a run can be
rebuilt offline (``run.py --from-cache``), e.g. after a keyword change,
without asking HWIS again.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable

from scraper.errors import FetchError, StructureError
from scraper.hwis_client import HwisClient
from scraper.parse_detail import Detail, parse_detail_page
from scraper.parse_list import ListRow, parse_list_page

log = logging.getLogger(__name__)

COURSE_TYPES = [("courseShubetsuCKBox", "1"), ("courseShubetsuCKBox", "2")]
CHILDCARE = [("tJServiceAriCKBox", "1")]
MAX_PAGES = 150
_REGIONS = (
    ("hokkaidoTohokuSCKBox", 1, 7),
    ("kantouSCKBox", 8, 14),
    ("kousinetu_HokurikuSCKBox", 15, 20),
    ("toukaiSCKBox", 21, 24),
    ("kinkiSCKBox", 25, 30),
    ("tyugokuSCKBox", 31, 35),
    ("sikokuSCKBox", 36, 39),
    ("kyusyu_OkinawSCKBox", 40, 47),
)


def pref_conditions(code: str) -> list[tuple[str, str]]:
    """Search fields for one prefecture and both course types."""
    number = int(code)
    box = next(name for name, low, high in _REGIONS if low <= number <= high)
    return [(box, str(number)), *COURSE_TYPES]


def _search(client: HwisClient, conditions: list[tuple[str, str]]) -> tuple[list[ListRow], int]:
    content = client.search(client.start_session(), conditions)
    page = parse_list_page(content)
    rows, skipped = list(page.rows), page.skipped
    while page.has_next:
        if page.page >= MAX_PAGES:
            raise StructureError(f"more than {MAX_PAGES} pages")
        content = client.next_page(content)
        following = parse_list_page(content)
        if following.page != page.page + 1 or following.total != page.total:
            raise StructureError(f"paging out of step: page {page.page} → {following.page}")
        rows += following.rows
        skipped += following.skipped
        page = following
    if len(rows) + skipped != page.total:
        raise StructureError(f"collected {len(rows) + skipped} rows of {page.total}")
    return rows, page.total


def _search_with_retry(client: HwisClient, conditions: list[tuple[str, str]], label: str) -> tuple[list[ListRow], int]:
    try:
        return _search(client, conditions)
    except (StructureError, FetchError) as error:
        log.warning("%s: search failed (%s), retrying once", label, error)
    return _search(client, conditions)


@dataclass(frozen=True)
class ListResult:
    """Rows by course id (first seen wins), the count each prefecture
    search announced, and searches that failed twice."""

    rows: dict[str, ListRow] = field(default_factory=dict)
    announced: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def collect_lists(client: HwisClient, prefs: Iterable[str]) -> ListResult:
    rows: dict[str, ListRow] = {}
    announced: dict[str, int] = {}
    errors: list[str] = []
    for code in prefs:
        try:
            found, total = _search_with_retry(client, pref_conditions(code), f"pref {code}")
        except (StructureError, FetchError) as error:
            errors.append(f"pref {code}: {error}")
            log.error("pref %s: list failed twice: %s", code, error)
            continue
        announced[code] = total
        for row in found:
            rows.setdefault(row.course_id, row)
        log.info("pref %s: %d listed (%d unique so far)", code, total, len(rows))
    return ListResult(rows=rows, announced=announced, errors=errors)


def collect_childcare(client: HwisClient) -> set[str] | None:
    """Ids of the 託児サービスあり search, or None when it failed twice."""
    try:
        found, total = _search_with_retry(client, [*COURSE_TYPES, *CHILDCARE], "childcare")
    except (StructureError, FetchError) as error:
        log.error("childcare search failed twice: %s", error)
        return None
    log.info("childcare: %d courses", total)
    return {row.course_id for row in found}


class Cache:
    """Raw pages and list rows of a run, for offline rebuilds."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "details").mkdir(parents=True, exist_ok=True)

    def save_lists(self, result: ListResult) -> None:
        rows = [{**asdict(r), "opening": r.opening.isoformat() if r.opening else None} for r in result.rows.values()]
        data = {"rows": rows, "announced": result.announced, "errors": result.errors}
        (self.root / "lists.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load_lists(self) -> ListResult:
        data = json.loads((self.root / "lists.json").read_text(encoding="utf-8"))
        rows = {}
        for raw in data["rows"]:
            opening = date.fromisoformat(raw["opening"]) if raw["opening"] else None
            rows[raw["course_id"]] = ListRow(**{**raw, "opening": opening})
        return ListResult(rows=rows, announced=data["announced"], errors=data["errors"])

    def save_childcare(self, ids: set[str] | None) -> None:
        data = None if ids is None else sorted(ids)
        (self.root / "childcare.json").write_text(json.dumps(data), encoding="utf-8")

    def load_childcare(self) -> set[str] | None:
        data = json.loads((self.root / "childcare.json").read_text(encoding="utf-8"))
        return None if data is None else set(data)

    def put_detail(self, course_id: str, content: bytes, fetched_at: datetime) -> None:
        (self.root / "details" / f"{course_id}.html").write_bytes(content)
        (self.root / "details" / f"{course_id}.at").write_text(fetched_at.isoformat(), encoding="utf-8")

    def get_detail(self, course_id: str) -> tuple[bytes, datetime] | None:
        page = self.root / "details" / f"{course_id}.html"
        stamp = self.root / "details" / f"{course_id}.at"
        if not page.exists() or not stamp.exists():
            return None
        return page.read_bytes(), datetime.fromisoformat(stamp.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class DetailResult:
    details: dict[str, Detail]
    fetched_at: dict[str, datetime]
    gone: set[str]
    failures: dict[str, str]
    attempts: int


def _fetch_one(client: HwisClient, course_id: str) -> tuple[bytes, Detail | None]:
    try:
        content = client.detail(course_id)
        return content, parse_detail_page(content)
    except (StructureError, FetchError) as error:
        log.warning("detail %s failed (%s), retrying once", course_id, error)
    content = client.detail(course_id)
    return content, parse_detail_page(content)


def fetch_details(
    client: HwisClient | None,
    ids: Iterable[str],
    *,
    now: Callable[[], datetime | None],
    cache: Cache | None = None,
) -> DetailResult:
    """Detail of every id. Without a client the pages come from ``cache``
    only. ``BlockedError`` propagates and stops the run."""
    details: dict[str, Detail] = {}
    fetched_at: dict[str, datetime] = {}
    gone: set[str] = set()
    failures: dict[str, str] = {}
    targets = list(ids)
    for index, course_id in enumerate(targets, start=1):
        try:
            if client is None:
                cached = cache.get_detail(course_id) if cache else None
                if cached is None:
                    raise FetchError("not in cache")
                content, stamp = cached
                detail = parse_detail_page(content)
            else:
                content, detail = _fetch_one(client, course_id)
                stamp = now()
                if cache is not None and stamp is not None:
                    cache.put_detail(course_id, content, stamp)
        except (StructureError, FetchError) as error:
            failures[course_id] = str(error)
            continue
        if detail is None:
            gone.add(course_id)
        else:
            details[course_id] = detail
            if stamp is not None:
                fetched_at[course_id] = stamp
        if index % 100 == 0:
            log.info("details %d/%d (failures %d, gone %d)", index, len(targets), len(failures), len(gone))
    return DetailResult(details, fetched_at, gone, failures, attempts=len(targets))
