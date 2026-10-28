"""HWIS search result pages (saved 2026-10-28) → list rows."""

from __future__ import annotations

from datetime import date

import pytest

from scraper import parse_list
from scraper.parse_list import StructureError
from tests.conftest import fixture_bytes


def test_first_page() -> None:
    page = parse_list.parse_list_page(fixture_bytes("list_13_p1.html"))
    assert page.total == 48
    assert page.page == 1
    assert page.has_next is True
    assert len(page.rows) == 30
    first = page.rows[0]
    assert first.course_id == "02-08-13-0504"
    assert first.kind == "public"
    assert first.name == "住宅内外装仕上"
    assert first.status == "募集中"
    assert first.opening == date(2026, 12, 1)
    assert first.address.startswith("東京都足立区綾瀬5-6-1")


def test_second_page_is_last() -> None:
    page = parse_list.parse_list_page(fixture_bytes("list_13_p2.html"))
    assert (page.total, page.page, page.has_next, len(page.rows)) == (48, 2, False, 18)
    kyushoku = [r for r in page.rows if r.kind == "kyushoku"]
    assert kyushoku, "page 2 holds 求職者支援訓練 rows"
    assert any(r.course_id == "01-08-13-0515" for r in kyushoku)
    assert all(r.pref == "13" for r in page.rows)


def test_names_are_nfkc_normalized() -> None:
    page = parse_list.parse_list_page(fixture_bytes("list_13_p1.html"))
    names = [r.name for r in page.rows]
    assert "IoTクリエイター" in names
    assert not any("Ｉ" in n for n in names)


def test_empty_result() -> None:
    page = parse_list.parse_list_page(fixture_bytes("list_empty.html"))
    assert (page.total, page.rows, page.has_next) == (0, [], False)


def test_childcare_search_page() -> None:
    page = parse_list.parse_list_page(fixture_bytes("list_childcare_p1.html"))
    assert page.total == 760
    assert len(page.rows) == 30


def test_system_error_page_is_structure_error() -> None:
    with pytest.raises(StructureError, match="system error"):
        parse_list.parse_list_page(fixture_bytes("system_error.html"))


def test_input_error_page_is_structure_error() -> None:
    html = fixture_bytes("list_empty.html").replace(
        "ご希望の条件に合致する情報は見つかりませんでした".encode(), "入力エラーがあります。".encode()
    )
    with pytest.raises(StructureError):
        parse_list.parse_list_page(html)


def test_page_without_markers_is_structure_error() -> None:
    with pytest.raises(StructureError):
        parse_list.parse_list_page("<html><body>maintenance</body></html>".encode())


def test_row_count_mismatch_is_structure_error() -> None:
    html = fixture_bytes("list_13_p1.html").replace(b'class="kyujin mt2"', b'class="other"', 1)
    with pytest.raises(StructureError, match="rows"):
        parse_list.parse_list_page(html)


def test_row_without_detail_link_is_structure_error() -> None:
    html = fixture_bytes("list_13_p1.html").replace(b"action=dispDetailBtn", b"action=x", 1)
    with pytest.raises(StructureError):
        parse_list.parse_list_page(html)


def test_unknown_kind_label_is_kept_out() -> None:
    html = fixture_bytes("list_13_p1.html").replace(
        'nes_label any">公共職業訓練'.encode(), 'nes_label any">障害者訓練'.encode(), 1
    )
    page = parse_list.parse_list_page(html)
    assert len(page.rows) == 29
    assert page.skipped == 1


def test_search_form_fields() -> None:
    fields = parse_list.form_fields(fixture_bytes("search_form.html"))
    names = [n for n, _ in fields]
    assert ("screenId", "GECA150010") in fields
    assert "searchBtn" not in names
    assert not any(n.endswith("SCKBox") or n == "courseShubetsuCKBox" for n in names)


def test_next_page_fields_keep_conditions() -> None:
    fields = parse_list.form_fields(fixture_bytes("list_13_p1.html"))
    assert ("kantouSCKBox", "13") in fields
    assert ("fwListNowPage", "1") in fields
    assert ("courseShubetsuCKBox", "2") in fields
    assert not any(n.startswith("fwListNaviSort") and n != "fwListNaviSort" for n, _ in fields)


def test_form_fields_without_form() -> None:
    with pytest.raises(StructureError):
        parse_list.form_fields(b"<html></html>")
