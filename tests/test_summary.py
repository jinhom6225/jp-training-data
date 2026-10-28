"""The success summary sent to Telegram after a publish (진호님 2026-10-29)."""

from __future__ import annotations

from scraper.summary import SummaryFacts, build_summary

URL = "https://jinhom6225.github.io/jp-training-data/meta.json"


def facts(**changes) -> SummaryFacts:
    values = dict(
        total=2112, added=5, removed=3, had_previous=True, changed_prefs=4, zero_prefs=[],
        other_ratio=0.054, tokyo_notices=1, full=False, duration_sec=812.4, meta_url=URL,
    )
    values.update(changes)
    return SummaryFacts(**values)


def test_normal_summary() -> None:
    assert build_summary(facts()) == (
        "✅ 배포 완료: 코스 2,112개\n"
        "직전 대비 +5 / −3 (도도부현 4곳 변동)\n"
        "기타 분야 5.4% · 東京 予告 1건\n"
        "상세: 바뀐 코스만 · 실행 14분\n"
        f"{URL}"
    )


def test_full_run_with_empty_prefectures() -> None:
    text = build_summary(facts(full=True, zero_prefs=["16", "31"], duration_sec=5199))
    assert "상세: 전체 (수요일·전체 실행) · 실행 87분" in text
    assert "0건 도도부현: 16, 31" in text


def test_first_publish_has_no_comparison() -> None:
    text = build_summary(facts(had_previous=False, added=2112, removed=0, changed_prefs=47))
    assert "직전 배포본 없음 (첫 배포)" in text
    assert "+2112" not in text


def test_no_change() -> None:
    assert "직전 대비 변동 없음" in build_summary(facts(added=0, removed=0, changed_prefs=0))
