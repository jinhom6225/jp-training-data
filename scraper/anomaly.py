"""Anomaly detection (research §3.1-5, plan D7).

Any reason blocks the run: nothing is published and the previous Pages
files stay. The four conditions:

1. the national total fell by more than 30% from the previous publish;
2. a page lacked its structure markers (HTML change, error page);
3. more than 10% of detail fetches failed to parse;
4. a prefecture that had 10 or more courses now has none.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_DROP = 0.30
MAX_DETAIL_FAILURE_RATE = 0.10
PREF_ZERO_THRESHOLD = 10


@dataclass(frozen=True)
class RunFacts:
    """What the detector needs from a run."""

    previous_counts: dict[str, int] | None
    counts: dict[str, int]
    structure_errors: list[str]
    detail_attempts: int
    detail_failures: int


def detect(facts: RunFacts, *, force: bool = False) -> list[str]:
    """Reasons to block publishing; empty when the run looks healthy."""
    if force:
        return ["forced anomaly (test run)"]
    reasons: list[str] = []
    total = sum(facts.counts.values())
    if facts.previous_counts:
        previous_total = sum(facts.previous_counts.values())
        if previous_total and total < previous_total * (1 - MAX_DROP):
            reasons.append(f"total fell {previous_total} → {total} (more than {MAX_DROP:.0%})")
        for pref, before in sorted(facts.previous_counts.items()):
            if before >= PREF_ZERO_THRESHOLD and facts.counts.get(pref, 0) == 0:
                reasons.append(f"pref {pref} fell {before} → 0")
    if facts.structure_errors:
        shown = "; ".join(facts.structure_errors[:3])
        reasons.append(f"structure markers missing ({len(facts.structure_errors)}): {shown}")
    if facts.detail_attempts:
        rate = facts.detail_failures / facts.detail_attempts
        if rate > MAX_DETAIL_FAILURE_RATE:
            reasons.append(
                f"detail failures {facts.detail_failures}/{facts.detail_attempts} ({rate:.1%}) over {MAX_DETAIL_FAILURE_RATE:.0%}"
            )
    return reasons
