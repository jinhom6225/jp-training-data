"""Collection over the fake HWIS: paging, retries, childcare, details, cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scraper import collect
from scraper.errors import BlockedError
from scraper.hwis_client import HwisClient
from tests.fakes import FakeClock, FakeTransport
from tests.hwis_site import FakeHwis

JST = timezone(timedelta(hours=9))


def client_for(site: FakeHwis) -> tuple[HwisClient, FakeTransport]:
    clock = FakeClock()
    transport = FakeTransport(clock, site)
    return HwisClient(transport, monotonic=clock.monotonic, sleep=clock.sleep), transport


def test_pref_conditions() -> None:
    assert collect.pref_conditions("13") == [
        ("kantouSCKBox", "13"), ("courseShubetsuCKBox", "1"), ("courseShubetsuCKBox", "2"),
    ]
    assert collect.pref_conditions("01")[0] == ("hokkaidoTohokuSCKBox", "1")
    assert collect.pref_conditions("24")[0] == ("toukaiSCKBox", "24")
    assert collect.pref_conditions("47")[0] == ("kyusyu_OkinawSCKBox", "47")
    assert len({collect.pref_conditions(f"{i:02d}")[0][0] for i in range(1, 48)}) == 8


def test_collect_lists_pages_through_tokyo() -> None:
    client, transport = client_for(FakeHwis())
    result = collect.collect_lists(client, ["13", "31"])
    assert len(result.rows) == 48
    assert result.announced == {"13": 48, "31": 0}
    assert result.errors == []
    assert sum(1 for c in transport.calls if "fwListNaviBtnNext" in dict(c.data or [])) == 1


def test_list_failure_is_retried_then_reported() -> None:
    site = FakeHwis(pref_pages={"13": ["system_error.html"]})
    client, transport = client_for(site)
    result = collect.collect_lists(client, ["13"])
    assert result.rows == {}
    assert result.errors and "13" in result.errors[0]
    assert sum(1 for c in transport.calls if c.method == "GET") == 2


def test_paging_that_loses_rows_is_an_error() -> None:
    site = FakeHwis(pref_pages={"13": ["list_13_p1.html", "list_13_p1.html"]})
    client, _ = client_for(site)
    assert collect.collect_lists(client, ["13"]).errors


def test_childcare_ids() -> None:
    client, _ = client_for(FakeHwis(childcare_pages=["list_13_p1.html", "list_13_p2.html"]))
    ids = collect.collect_childcare(client)
    assert ids is not None and "01-08-13-0515" in ids


def test_childcare_failure_returns_none() -> None:
    client, _ = client_for(FakeHwis(childcare_pages=["system_error.html"]))
    assert collect.collect_childcare(client) is None


def test_fetch_details_sorts_outcomes(tmp_path: Path) -> None:
    site = FakeHwis(gone={"02-08-13-0001"}, broken_detail={"02-08-13-0002"})
    client, _ = client_for(site)
    cache = collect.Cache(tmp_path)
    result = collect.fetch_details(
        client, ["01-08-13-0515", "02-08-13-0001", "02-08-13-0002"],
        now=lambda: datetime(2026, 10, 28, 6, 50, tzinfo=JST), cache=cache,
    )
    assert set(result.details) == {"01-08-13-0515"}
    assert result.gone == {"02-08-13-0001"}
    assert set(result.failures) == {"02-08-13-0002"}
    assert result.attempts == 3
    assert result.fetched_at["01-08-13-0515"] == datetime(2026, 10, 28, 6, 50, tzinfo=JST)
    offline = collect.fetch_details(None, ["01-08-13-0515", "09-09-09-9999"], now=lambda: None, cache=cache)
    assert set(offline.details) == {"01-08-13-0515"}
    assert offline.fetched_at["01-08-13-0515"] == datetime(2026, 10, 28, 6, 50, tzinfo=JST)
    assert "09-09-09-9999" in offline.failures


def test_blocked_stops_detail_fetching() -> None:
    client, _ = client_for(FakeHwis(status=403))
    with pytest.raises(BlockedError):
        collect.fetch_details(client, ["01-08-13-0515"], now=lambda: None)


def test_cache_round_trip(tmp_path: Path) -> None:
    client, _ = client_for(FakeHwis())
    lists = collect.collect_lists(client, ["13"])
    cache = collect.Cache(tmp_path)
    cache.save_lists(lists)
    cache.save_childcare({"01-08-13-0515"})
    again = cache.load_lists()
    assert again.rows == lists.rows and again.announced == lists.announced
    assert cache.load_childcare() == {"01-08-13-0515"}
    cache.save_childcare(None)
    assert cache.load_childcare() is None


def _ids(n: int) -> list[str]:
    return [f"02-08-13-{i:04d}" for i in range(1, n + 1)]


def test_ten_consecutive_detail_failures_stop_the_run() -> None:
    ids = _ids(12)
    client, transport = client_for(FakeHwis(broken_detail=set(ids[:10])))
    with pytest.raises(BlockedError, match="consecutive"):
        collect.fetch_details(client, ids, now=lambda: None)
    asked = {"-".join((c.params or {}).get(k, "") for k in ("kRNShubetsu_Detail", "shinseiNendo_Detail", "tDFKNo_Detail", "kRNTsuban_Detail")) for c in transport.calls}
    assert ids[10] not in asked


def test_failure_rate_over_ten_percent_after_fifty_stops_the_run() -> None:
    ids = _ids(60)
    broken = {i for n, i in enumerate(ids, start=1) if n % 8 == 0}  # 12.5 %, never 10 in a row
    client, _ = client_for(FakeHwis(broken_detail=broken))
    with pytest.raises(BlockedError, match="rate"):
        collect.fetch_details(client, ids, now=lambda: None)


def test_failure_rate_of_ten_percent_is_tolerated() -> None:
    ids = _ids(60)
    broken = {i for n, i in enumerate(ids, start=1) if n % 10 == 0}
    client, _ = client_for(FakeHwis(broken_detail=broken))
    result = collect.fetch_details(client, ids, now=lambda: None)
    assert len(result.failures) == 6


def test_offline_rebuild_has_no_circuit_breaker(tmp_path: Path) -> None:
    result = collect.fetch_details(None, _ids(12), now=lambda: None, cache=collect.Cache(tmp_path))
    assert len(result.failures) == 12


def test_three_failed_prefectures_in_a_row_stop_the_run() -> None:
    pages = {code: ["system_error.html"] for code in ("13", "14", "15")}
    client, transport = client_for(FakeHwis(pref_pages=pages))
    with pytest.raises(BlockedError, match="3 prefectures"):
        collect.collect_lists(client, ["13", "14", "15", "16"])
    assert not any(("toukaiSCKBox", "16") in (c.data or []) or ("kousinetu_HokurikuSCKBox", "16") in (c.data or []) for c in transport.calls)


def test_two_failed_prefectures_then_success_continue() -> None:
    pages = {"14": ["system_error.html"], "15": ["system_error.html"], "13": ["list_13_p1.html", "list_13_p2.html"]}
    client, _ = client_for(FakeHwis(pref_pages=pages))
    result = collect.collect_lists(client, ["14", "15", "13", "16"])
    assert len(result.errors) == 2 and len(result.rows) == 48
