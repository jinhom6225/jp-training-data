"""HWIS client: ≥1.5 s spacing, cookie-less details, paging fields,
one retry, and an immediate stop on 403/429 (plan Phase 1, D3)."""

from __future__ import annotations

import pytest

from scraper.errors import BlockedError, FetchError
from scraper.hwis_client import BASE_URL, HwisClient, TransportError
from tests.conftest import fixture_bytes
from tests.fakes import Call, FakeClock, FakeTransport


def make(responder, latency: float = 0.3) -> tuple[HwisClient, FakeTransport, FakeClock]:
    clock = FakeClock()
    transport = FakeTransport(clock, responder, latency=latency)
    client = HwisClient(transport, monotonic=clock.monotonic, sleep=clock.sleep, user_agent="test-agent")
    return client, transport, clock


def ok(_: Call) -> tuple[int, bytes]:
    return 200, b"<html></html>"


def test_requests_are_spaced_from_the_end_of_the_previous_one() -> None:
    client, transport, _ = make(ok, latency=0.4)
    for key in ["02-08-13-0504", "01-08-13-0515", "02-09-14-0013"]:
        client.detail(key)
    starts = [c.started for c in transport.calls]
    for earlier, later in zip(starts, starts[1:]):
        assert later - (earlier + 0.4) >= 1.5 - 1e-9


def test_no_wait_before_the_first_request_or_after_a_long_gap() -> None:
    client, _, clock = make(ok)
    client.detail("02-08-13-0504")
    assert clock.sleeps == []
    clock.now += 10
    client.detail("02-08-13-0504")
    assert clock.sleeps == []


def test_detail_is_a_cookieless_get_with_the_four_keys() -> None:
    client, transport, _ = make(ok)
    client.detail("02-08-13-0504")
    call = transport.calls[0]
    assert (call.method, call.url, call.use_cookies) == ("GET", BASE_URL, False)
    assert call.params == {
        "screenId": "GECA150010",
        "action": "dispDetailBtn",
        "kRNShubetsu_Detail": "02",
        "shinseiNendo_Detail": "08",
        "tDFKNo_Detail": "13",
        "kRNTsuban_Detail": "0504",
    }
    assert call.headers["User-Agent"] == "test-agent"


def test_detail_url_matches_the_link_format() -> None:
    assert HwisClient.detail_url("02-08-13-0504") == (
        f"{BASE_URL}?screenId=GECA150010&action=dispDetailBtn&kRNShubetsu_Detail=02"
        "&shinseiNendo_Detail=08&tDFKNo_Detail=13&kRNTsuban_Detail=0504"
    )


def test_session_search_and_next_page() -> None:
    pages = {"init": fixture_bytes("search_form.html"), "p1": fixture_bytes("list_13_p1.html")}

    def responder(call: Call) -> tuple[int, bytes]:
        if call.method == "GET":
            return 200, pages["init"]
        return 200, pages["p1"]

    client, transport, _ = make(responder)
    base = client.start_session()
    assert transport.cookie_resets == 1
    first = client.search(base, [("kantouSCKBox", "13")])
    client.next_page(first)
    init, search, nxt = transport.calls
    assert init.params == {"screenId": "GECA150010", "action": "initDisp"} and init.use_cookies
    assert search.method == "POST" and search.use_cookies
    assert ("kantouSCKBox", "13") in search.data and ("searchBtn", "検索") in search.data
    assert ("fwListNaviBtnNext", "次へ＞") in nxt.data
    assert ("fwListNowPage", "1") in nxt.data and ("kantouSCKBox", "13") in nxt.data
    assert all(name != "searchBtn" for name, _ in nxt.data)


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_statuses_stop_without_retry(status: int) -> None:
    client, transport, _ = make(lambda _: (status, b""))
    with pytest.raises(BlockedError):
        client.detail("02-08-13-0504")
    assert len(transport.calls) == 1


def test_server_error_is_retried_once() -> None:
    answers = iter([(503, b""), (200, b"ok")])
    client, transport, _ = make(lambda _: next(answers))
    assert client.detail("02-08-13-0504") == b"ok"
    assert len(transport.calls) == 2
    assert transport.calls[1].started - transport.calls[0].started >= 1.5


def test_two_failures_raise_fetch_error() -> None:
    client, transport, _ = make(lambda _: (500, b""))
    with pytest.raises(FetchError):
        client.detail("02-08-13-0504")
    assert len(transport.calls) == 2


def test_timeout_is_retried_once() -> None:
    answers = iter([TransportError("timed out"), (200, b"ok")])
    client, transport, _ = make(lambda _: next(answers))
    assert client.detail("02-08-13-0504") == b"ok"


def test_repeated_connection_failures_raise_fetch_error() -> None:
    client, _, _ = make(lambda _: TransportError("refused"))
    with pytest.raises(FetchError):
        client.detail("02-08-13-0504")


def test_not_found_is_not_retried() -> None:
    client, transport, _ = make(lambda _: (404, b""))
    with pytest.raises(FetchError):
        client.detail("02-08-13-0504")
    assert len(transport.calls) == 1


def test_counts_requests() -> None:
    client, _, _ = make(ok)
    client.detail("02-08-13-0504")
    client.detail("02-08-13-0505")
    assert client.request_count == 2


def test_rejects_bad_course_id() -> None:
    client, _, _ = make(ok)
    with pytest.raises(ValueError):
        client.detail("../etc")


def test_min_interval_cannot_go_below_policy() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError):
        HwisClient(FakeTransport(clock, ok), min_interval=1.0)


class _Response:
    def __init__(self, chunks: list[bytes], status: int = 200, length: str | None = None) -> None:
        self._chunks = chunks
        self.status_code = status
        self.headers = {} if length is None else {"Content-Length": length}
        self.closed = False

    def iter_content(self, chunk_size: int):
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def _transport(monkeypatch: pytest.MonkeyPatch, response: _Response):
    import requests

    from scraper.hwis_client import RequestsTransport

    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        return response

    monkeypatch.setattr(requests, "request", fake)
    transport = RequestsTransport(max_bytes=10)
    monkeypatch.setattr(transport._session, "request", fake)
    return transport, seen


@pytest.mark.parametrize("cookies", [True, False])
def test_transport_streams_small_bodies(monkeypatch: pytest.MonkeyPatch, cookies: bool) -> None:
    response = _Response([b"abc", b"def"])
    transport, seen = _transport(monkeypatch, response)
    status, body = transport.send("GET", BASE_URL, params=None, data=None, use_cookies=cookies, timeout=1, headers={})
    assert (status, body) == (200, b"abcdef")
    assert seen["stream"] is True and seen["allow_redirects"] is False
    assert response.closed


def test_transport_rejects_a_large_declared_body(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, _ = _transport(monkeypatch, _Response([b"x"], length="11"))
    with pytest.raises(FetchError, match="bytes"):
        transport.send("GET", BASE_URL, params=None, data=None, use_cookies=False, timeout=1, headers={})


def test_transport_rejects_a_large_streamed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b"123456", b"789012"])
    transport, _ = _transport(monkeypatch, response)
    with pytest.raises(FetchError, match="bytes"):
        transport.send("GET", BASE_URL, params=None, data=None, use_cookies=False, timeout=1, headers={})
    assert response.closed


def test_oversized_body_is_not_retried() -> None:
    client, transport, _ = make(lambda _: FetchError("body over 5 MB"))
    with pytest.raises(FetchError):
        client.detail("02-08-13-0504")
    assert len(transport.calls) == 1


def test_default_cap_is_five_megabytes() -> None:
    from scraper.hwis_client import MAX_RESPONSE_BYTES

    assert MAX_RESPONSE_BYTES == 5 * 1024 * 1024
