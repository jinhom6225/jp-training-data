"""Fake transport and clock for the HWIS client tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from scraper.hwis_client import TransportError

Responder = Callable[["Call"], tuple[int, bytes]]


@dataclass
class Call:
    method: str
    url: str
    params: dict[str, str] | None
    data: list[tuple[str, str]] | None
    use_cookies: bool
    started: float
    headers: dict[str, str]


class FakeClock:
    """Time only moves when the client sleeps or a request takes time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class FakeTransport:
    clock: FakeClock
    responder: Responder
    latency: float = 0.3
    calls: list[Call] = field(default_factory=list)
    cookie_resets: int = 0

    def send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None,
        data: list[tuple[str, str]] | None,
        use_cookies: bool,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        call = Call(method, url, params, data, use_cookies, self.clock.now, dict(headers))
        self.calls.append(call)
        self.clock.now += self.latency
        result = self.responder(call)
        if isinstance(result, Exception):
            raise result
        return result

    def reset_cookies(self) -> None:
        self.cookie_resets += 1


def timeout_error() -> TransportError:
    return TransportError("timed out")
