"""The short success notice sent after a publish (진호님 2026-10-29).

run.py writes it to ``out/summary.txt`` only when the site was written;
the workflow sends it after the Pages deploy succeeded, for the morning
schedule and for every manual run. Numbers and prefecture codes only: no
HWIS text, no secrets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SummaryFacts:
    total: int
    added: int
    removed: int
    had_previous: bool
    changed_prefs: int
    zero_prefs: list[str]
    other_ratio: float
    tokyo_notices: int
    full: bool
    duration_sec: float
    meta_url: str


def _comparison(facts: SummaryFacts) -> str:
    if not facts.had_previous:
        return "직전 배포본 없음 (첫 배포)"
    if not (facts.added or facts.removed or facts.changed_prefs):
        return "직전 대비 변동 없음"
    return f"직전 대비 +{facts.added} / −{facts.removed} (도도부현 {facts.changed_prefs}곳 변동)"


def build_summary(facts: SummaryFacts) -> str:
    """Five or six short Korean lines."""
    detail = "전체 (수요일·전체 실행)" if facts.full else "바뀐 코스만"
    lines = [
        f"✅ 배포 완료: 코스 {facts.total:,}개",
        _comparison(facts),
        f"기타 분야 {facts.other_ratio * 100:.1f}% · 東京 予告 {facts.tokyo_notices}건",
        f"상세: {detail} · 실행 {round(facts.duration_sec / 60)}분",
    ]
    if facts.zero_prefs:
        lines.insert(2, "0건 도도부현: " + ", ".join(facts.zero_prefs))
    lines.append(facts.meta_url)
    return "\n".join(lines)
