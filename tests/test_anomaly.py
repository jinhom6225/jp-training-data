"""Anomaly rules (research §3.1-5, plan D7): any one blocks publishing."""

from __future__ import annotations

from scraper.anomaly import RunFacts, detect

PREVIOUS = {"13": 50, "27": 40, "40": 10}


def facts(**changes) -> RunFacts:
    base = dict(
        previous_counts=PREVIOUS,
        counts={"13": 50, "27": 40, "40": 10},
        structure_errors=[],
        detail_attempts=100,
        detail_failures=0,
    )
    base.update(changes)
    return RunFacts(**base)


def test_normal_run_has_no_anomaly() -> None:
    assert detect(facts()) == []


def test_drop_of_29_percent_is_fine_31_is_not() -> None:
    assert detect(facts(counts={"13": 30, "27": 34, "40": 7})) == []  # 71 of 100
    reasons = detect(facts(counts={"13": 30, "27": 32, "40": 7}))  # 69 of 100
    assert any("total" in r for r in reasons)


def test_structure_marker_missing() -> None:
    reasons = detect(facts(structure_errors=["pref 13: result page without the 「N件中」 count"]))
    assert any("structure" in r for r in reasons)


def test_detail_failure_rate_over_ten_percent() -> None:
    assert detect(facts(detail_failures=10)) == []
    assert any("detail" in r for r in detail_reasons(11))


def detail_reasons(failures: int) -> list[str]:
    return detect(facts(detail_failures=failures))


def test_prefecture_with_ten_or_more_now_zero() -> None:
    assert any("40" in r for r in detect(facts(counts={"13": 50, "27": 40, "40": 0})))


def test_prefecture_below_ten_may_go_to_zero() -> None:
    previous = {"13": 50, "27": 40, "40": 9}
    assert detect(facts(previous_counts=previous, counts={"13": 50, "27": 40, "40": 0})) == []


def test_first_run_checks_only_structure_and_details() -> None:
    assert detect(facts(previous_counts=None, counts={"13": 1})) == []
    assert detect(facts(previous_counts=None, detail_failures=50)) != []


def test_no_details_fetched() -> None:
    assert detect(facts(detail_attempts=0, detail_failures=0)) == []


def test_forced_anomaly() -> None:
    assert detect(facts(), force=True) == ["forced anomaly (test run)"]
