"""Pipeline exceptions."""

from __future__ import annotations


class StructureError(Exception):
    """An HWIS page lacks the markers the parsers rely on (HTML changed, a
    システムエラー or 入力エラー page, or a truncated response)."""


class BlockedError(Exception):
    """HWIS answered 403 or 429, or refused the connection repeatedly:
    stop the run at once (plan D3) instead of retrying."""


class FetchError(Exception):
    """A request failed after its one retry."""
