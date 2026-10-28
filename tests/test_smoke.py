"""Access check (plan 1-0, D3): search form, 東京 list, one detail."""

from __future__ import annotations

from scraper import smoke
from scraper.hwis_client import HwisClient
from tests.fakes import FakeClock, FakeTransport
from tests.hwis_site import FakeHwis


def client(site: FakeHwis) -> HwisClient:
    clock = FakeClock()
    return HwisClient(FakeTransport(clock, site), monotonic=clock.monotonic, sleep=clock.sleep)


def test_smoke_passes_on_working_site() -> None:
    notices: list[str] = []
    assert smoke.check(client(FakeHwis()), notify=notices.append) is True
    assert "OK" in notices[0] and "48" in notices[0]


def test_smoke_fails_on_block_or_bad_pages() -> None:
    for site in (FakeHwis(status=403), FakeHwis(pref_pages={"13": ["system_error.html"]}),
                 FakeHwis(pref_pages={"13": ["list_empty.html"]}), FakeHwis(gone={"02-08-13-0504"})):
        notices: list[str] = []
        assert smoke.check(client(site), notify=notices.append) is False
        assert "FAILED" in notices[0]
