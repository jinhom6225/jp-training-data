"""Pipeline exceptions."""

from __future__ import annotations


class StructureError(Exception):
    """An HWIS page lacks the markers the parsers rely on (HTML changed, a
    システムエラー or 入力エラー page, or a truncated response)."""


class BlockedError(Exception):
    """Stop the run at once (plan D3) instead of retrying: HWIS answered 403
    or 429, or the circuit breaker in ``collect`` tripped (10 detail
    failures in a row, a detail failure rate over 10% after 50 attempts,
    or 3 prefecture searches failing in a row)."""


class FetchError(Exception):
    """A request failed after its one retry."""
