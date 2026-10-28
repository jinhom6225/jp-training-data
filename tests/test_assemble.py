"""Which details a run fetches and how the course list is put together
(plan Phase 1 run order, D7)."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

from scraper import assemble, parse_detail
from scraper.collect import DetailResult
from scraper.parse_list import ListRow
from tests.conftest import five_round_detail, fixture_bytes, load_rule_cases

JST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 20)
BASE = load_rule_cases()["bases"]["hwis"]


def prev(course_id: str, **changes) -> dict:
    course = copy.deepcopy(BASE)
    course.update(id=course_id, name="OA事務科", trainingStart="2027-01-08",
                  rounds=[{"no": 1, "start": "2026-10-01", "end": "2026-11-26"}])
    course.update(changes)
    return course


def row(course_id: str, **changes) -> ListRow:
    values = dict(course_id=course_id, kind="kyushoku", name="OA事務科", status="募集中",
                  opening=date(2027, 1, 8), address="東京都新宿区西新宿1")
    values.update(changes)
    return ListRow(**values)


def test_full_mode_fetches_every_listed_course() -> None:
    rows = {i: row(i) for i in ("01-08-13-0001", "01-08-13-0002")}
    targets = assemble.detail_targets(rows, {}, set(), TODAY, full=True)
    assert targets.fetch == ["01-08-13-0001", "01-08-13-0002"]
    assert targets.recheck == []


def test_normal_mode_fetches_new_changed_and_near_deadline_courses() -> None:
    previous = {
        "01-08-13-0001": prev("01-08-13-0001"),
        "01-08-13-0002": prev("01-08-13-0002", name="旧名称"),
        "01-08-13-0003": prev("01-08-13-0003", trainingStart="2027-02-01"),
        "01-08-13-0004": prev("01-08-13-0004", rounds=[{"no": 1, "start": "2026-11-01", "end": "2026-11-26"}]),
        "01-08-13-0005": prev("01-08-13-0005", rounds=[{"no": 1, "start": "2026-10-01", "end": "2026-11-03"}]),
        "01-08-13-0006": prev("01-08-13-0006"),
        "01-08-13-0007": prev("01-08-13-0007", rounds=[{"no": 1, "start": "2026-10-01", "end": "2026-10-19"}]),
    }
    rows = {i: row(i) for i in [f"01-08-13-000{n}" for n in range(1, 6)] + ["01-08-13-0009"]}
    targets = assemble.detail_targets(rows, previous, set(), TODAY, full=False)
    # 0002 name changed, 0003 opening changed, 0004 status (募集前 → 募集中),
    # 0005 ends within 14 days, 0009 new.
    assert targets.fetch == ["01-08-13-0002", "01-08-13-0003", "01-08-13-0004", "01-08-13-0005", "01-08-13-0009"]
    # 0006 vanished from the list while still open → D7 recheck; 0007 ended.
    assert targets.recheck == ["01-08-13-0006"]


def test_unknown_prefecture_is_fetched_in_full() -> None:
    rows = {"01-08-27-0001": row("01-08-27-0001")}
    previous = {"01-08-27-0001": prev("01-08-27-0001")}
    assert assemble.detail_targets(rows, previous, {"27"}, TODAY, full=False).fetch == ["01-08-27-0001"]


def detail(key: str) -> parse_detail.Detail:
    result = parse_detail.parse_detail_page(fixture_bytes(f"detail_{key}.html"))
    assert result is not None
    return result


def results(details: dict, gone: set | None = None, failures: dict | None = None) -> DetailResult:
    stamp = datetime(2026, 10, 20, 6, 45, tzinfo=JST)
    return DetailResult(details=details, fetched_at={k: stamp for k in details}, gone=gone or set(),
                        failures=failures or {}, attempts=len(details) + len(gone or ()) + len(failures or {}))


def test_assemble_builds_reuses_and_rechecks() -> None:
    rows = {
        "01-08-13-0515": row("01-08-13-0515"),
        "01-08-13-0001": row("01-08-13-0001"),
        "01-08-13-0002": row("01-08-13-0002"),
        "01-08-13-0003": row("01-08-13-0003"),
    }
    previous = {
        "01-08-13-0001": prev("01-08-13-0001"),
        "01-08-13-0002": prev("01-08-13-0002"),
        "02-08-13-0504": prev("02-08-13-0504"),
        "02-08-13-0999": prev("02-08-13-0999"),
    }
    fetched = results(
        {"01-08-13-0515": detail("01-08-13-0515"), "02-08-13-0504": detail("02-08-13-0504")},
        gone={"02-08-13-0999"},
        failures={"01-08-13-0002": "HTTP 500", "01-08-13-0003": "system error"},
    )
    out = assemble.assemble(rows, previous, fetched, childcare={"01-08-13-0001"}, today=TODAY,
                            recheck=["02-08-13-0504", "02-08-13-0999"])
    ids = sorted(c["id"] for c in out.courses["13"])
    # built: 0515; reused: 0001 (not fetched) and 0002 (fetch failed);
    # recheck kept: 0504; gone: 0999; 0003 failed with no previous → missing.
    assert ids == ["01-08-13-0001", "01-08-13-0002", "01-08-13-0515", "02-08-13-0504"]
    assert out.built == 2 and out.reused == 2
    assert out.missing == ["01-08-13-0003"]
    assert out.gone == ["02-08-13-0999"]
    reused = next(c for c in out.courses["13"] if c["id"] == "01-08-13-0001")
    assert reused["childcare"] is True
    assert previous["01-08-13-0001"]["childcare"] is False


def test_assemble_drops_invalid_and_ended_courses() -> None:
    rows = {"01-08-13-0515": row("01-08-13-0515"), "01-08-13-0001": row("01-08-13-0001")}
    previous = {"01-08-13-0001": prev("01-08-13-0001", phone="bad")}
    fetched = results({"01-08-13-0515": detail("01-08-13-0515")})
    out = assemble.assemble(rows, previous, fetched, childcare=None, today=date(2026, 11, 12), recheck=[])
    assert out.courses == {}
    assert out.ended == ["01-08-13-0515"]
    assert list(out.invalid) == ["01-08-13-0001"]


def test_assemble_uses_list_kind_when_detail_has_none() -> None:
    d = detail("01-08-13-0515")
    bare = parse_detail.Detail(**{**d.__dict__, "kind": None})
    rows = {"01-08-13-0515": row("01-08-13-0515", kind="public")}
    out = assemble.assemble(rows, {}, results({"01-08-13-0515": bare}), childcare=set(), today=TODAY, recheck=[])
    assert out.courses["13"][0]["kind"] == "public"


def test_course_status() -> None:
    course = prev("x", rounds=[{"no": 1, "start": "2026-10-01", "end": "2026-10-10"},
                               {"no": 2, "start": "2026-11-01", "end": "2026-11-10"}])
    assert assemble.status_on(course, date(2026, 10, 5)) == "募集中"
    assert assemble.status_on(course, date(2026, 10, 20)) == "募集前"
    assert assemble.status_on(course, date(2026, 11, 20)) is None


def test_four_and_five_round_courses_are_kept() -> None:
    d = parse_detail.parse_detail_page(five_round_detail())
    assert d is not None
    four = parse_detail.Detail(**{**d.__dict__, "rounds": d.rounds[:4]})
    rows = {"02-09-14-0013": row("02-09-14-0013", kind="public"), "02-09-14-0014": row("02-09-14-0014", kind="public")}
    out = assemble.assemble(rows, {}, results({"02-09-14-0013": d, "02-09-14-0014": four}),
                            childcare=set(), today=TODAY, recheck=[])
    assert out.invalid == {}
    assert sorted(len(c["rounds"]) for c in out.courses["14"]) == [4, 5]
