"""The single HTTP client for HWIS (plan Phase 1, research raw §2-1).

Every request goes through ``HwisClient``: one at a time, at least 1.5 s
after the previous response ended, 20 s timeout, one retry on a timeout,
connection error or 5xx, and an immediate ``BlockedError`` on 403/429
(plan D3). Search pages need the session cookie (``initDisp`` GET, then
POSTs); detail pages are fetched without cookies.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Protocol
from urllib.parse import urlencode

import requests

from scraper.errors import BlockedError, FetchError
from scraper.parse_list import form_fields

BASE_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA150010.do"
SCREEN = "GECA150010"
USER_AGENT = (
    "jp-training-data/1.0 (+https://github.com/jinhom6225/jp-training-data; "
    "course deadline alert data, 1 request per 1.5 s)"
)
MIN_INTERVAL = 1.5
TIMEOUT = 20.0
_COURSE_ID = re.compile(r"([0-9]{2})-([0-9]{2})-([0-9]{2})-([0-9]{4})")
_BLOCKED = (403, 429)


class TransportError(Exception):
    """Timeout or connection failure below HTTP."""


class Transport(Protocol):
    """What the client needs from HTTP (a fake in tests)."""

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
    ) -> tuple[int, bytes]: ...

    def reset_cookies(self) -> None: ...


class RequestsTransport:
    """``requests`` transport: one cookie session for searches, a fresh
    cookie-less request for details. Redirects are not followed."""

    def __init__(self) -> None:
        self._session = requests.Session()

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
        try:
            if use_cookies:
                response = self._session.request(
                    method, url, params=params, data=data, timeout=timeout, headers=headers, allow_redirects=False
                )
            else:
                response = requests.request(
                    method, url, params=params, data=data, timeout=timeout, headers=headers, allow_redirects=False
                )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise TransportError(str(error)) from error
        return response.status_code, response.content

    def reset_cookies(self) -> None:
        self._session.cookies.clear()


class HwisClient:
    """Spaced, retried access to the HWIS search and detail pages."""

    def __init__(
        self,
        transport: Transport,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL,
        timeout: float = TIMEOUT,
        user_agent: str = USER_AGENT,
    ) -> None:
        if min_interval < MIN_INTERVAL:
            raise ValueError(f"min_interval must be at least {MIN_INTERVAL} s (site policy)")
        self._transport = transport
        self._monotonic = monotonic
        self._sleep = sleep
        self._min_interval = min_interval
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent, "Accept-Language": "ja"}
        self._last_end: float | None = None
        self.request_count = 0

    @staticmethod
    def detail_params(course_id: str) -> dict[str, str]:
        match = _COURSE_ID.fullmatch(course_id)
        if match is None:
            raise ValueError(f"not an HWIS course id: {course_id!r}")
        kind, year, pref, serial = match.groups()
        return {
            "screenId": SCREEN,
            "action": "dispDetailBtn",
            "kRNShubetsu_Detail": kind,
            "shinseiNendo_Detail": year,
            "tDFKNo_Detail": pref,
            "kRNTsuban_Detail": serial,
        }

    @classmethod
    def detail_url(cls, course_id: str) -> str:
        """The public detail URL (the app's 原文 link)."""
        return f"{BASE_URL}?{urlencode(cls.detail_params(course_id))}"

    def _wait(self) -> None:
        if self._last_end is None:
            return
        remaining = self._min_interval - (self._monotonic() - self._last_end)
        if remaining > 0:
            self._sleep(remaining)

    def _once(self, method: str, params: dict[str, str] | None, data: list[tuple[str, str]] | None, cookies: bool) -> tuple[int, bytes]:
        self._wait()
        self.request_count += 1
        try:
            return self._transport.send(
                method, BASE_URL, params=params, data=data, use_cookies=cookies,
                timeout=self._timeout, headers=self._headers,
            )
        finally:
            self._last_end = self._monotonic()

    def _request(self, method: str, *, params: dict[str, str] | None = None, data: list[tuple[str, str]] | None = None, cookies: bool) -> bytes:
        problem = ""
        for _attempt in range(2):
            try:
                status, content = self._once(method, params, data, cookies)
            except TransportError as error:
                problem = f"transport: {error}"
                continue
            if status in _BLOCKED:
                raise BlockedError(f"HWIS answered {status}")
            if status == 200:
                return content
            problem = f"HTTP {status}"
            if status < 500:
                break
        raise FetchError(f"{method} {params or ''} failed: {problem}")

    def start_session(self) -> list[tuple[str, str]]:
        """New cookie session: GET the search form and return its fields."""
        self._transport.reset_cookies()
        content = self._request("GET", params={"screenId": SCREEN, "action": "initDisp"}, cookies=True)
        return form_fields(content)

    def search(self, base: list[tuple[str, str]], conditions: list[tuple[str, str]]) -> bytes:
        """POST a search: the form's fields + ``conditions`` + 検索."""
        return self._request("POST", data=base + conditions + [("searchBtn", "検索")], cookies=True)

    def next_page(self, page: bytes) -> bytes:
        """POST the result page's own form back with 次へ."""
        return self._request("POST", data=form_fields(page) + [("fwListNaviBtnNext", "次へ＞")], cookies=True)

    def detail(self, course_id: str) -> bytes:
        """GET a detail page without cookies."""
        return self._request("GET", params=self.detail_params(course_id), cookies=False)
