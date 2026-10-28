"""HWIS course detail pages (saved 2026-10-28) → detail values."""

from __future__ import annotations

import re
from datetime import date

import pytest

from scraper import parse_detail
from scraper.parse_list import StructureError
from tests.conftest import five_round_detail, fixture_bytes


def detail(key: str) -> parse_detail.Detail:
    result = parse_detail.parse_detail_page(fixture_bytes(f"detail_{key}.html"))
    assert result is not None
    return result


def test_kyushoku_one_round_with_field_string() -> None:
    d = detail("01-08-13-0515")
    assert d.name == "生成AI活用 アプリ・WEB・システムエンジニア養成(午後)科"
    assert d.kind == "kyushoku"
    assert d.category == "実践コース(IT分野)"
    assert d.status == "募集中"
    assert d.rounds == [parse_detail.DetailRound(1, date(2026, 10, 27), date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 2))]
    assert (d.training_start, d.training_end) == (date(2026, 12, 15), date(2027, 6, 14))
    assert d.hours == "16:00〜20:50"
    assert d.self_cost == "16,137円(教科書代:16,137円 その他:0円)"
    assert d.capacity == 17
    assert d.conditions == "パソコンの基本操作(文字入力)が出来る方。"
    assert d.institution == "株式会社個別教育研究所"
    assert d.facility == "株式会社 個別教育研究所 とぴあITスクール 新宿校第1教室"
    assert d.address == "東京都新宿区西新宿七丁目8番13号栗原ビル7F"


def test_public_three_rounds() -> None:
    d = detail("02-09-14-0013")
    assert d.kind == "public"
    assert [(r.no, r.start, r.end) for r in d.rounds] == [
        (1, date(2026, 10, 1), date(2026, 10, 22)),
        (2, date(2026, 11, 20), date(2026, 12, 1)),
        (3, date(2027, 1, 26), date(2027, 2, 22)),
    ]
    assert d.rounds[1].selection == date(2026, 12, 12)
    assert d.rounds[2].result == date(2027, 3, 16)
    assert d.capacity == 30
    assert d.institution == "神奈川県"
    assert d.address.startswith("神奈川県秦野市")


def test_childcare_course() -> None:
    d = detail("03-08-27-0234")
    assert "【託児付】" in d.name
    assert d.category == "知識等習得専修学校・各種学校等(インセンティブ対象)(介護・医療・福祉分野)"
    assert d.self_cost.startswith("580円")
    assert d.conditions == "特になし"
    assert d.address == "堺市堺区北瓦町2ー3ー6堺東北條ビル3階"


def test_public_category_string() -> None:
    d = detail("02-08-13-0504")
    assert d.category == "離転職者訓練(施設内)(建設関連分野)"
    assert d.institution == "東京都"
    assert d.facility == "城東職業能力開発センター"


def test_gone_page_returns_none() -> None:
    assert parse_detail.parse_detail_page(fixture_bytes("detail_02-08-13-9999.html")) is None


def test_system_error_is_structure_error() -> None:
    with pytest.raises(StructureError):
        parse_detail.parse_detail_page(fixture_bytes("system_error.html"))


def test_page_without_rounds_is_structure_error() -> None:
    html = fixture_bytes("detail_01-08-13-0515.html").decode("utf-8").replace("募集期間", "期間")
    with pytest.raises(StructureError, match="募集期間"):
        parse_detail.parse_detail_page(html.encode("utf-8"))


def test_missing_boxes_become_none() -> None:
    html = fixture_bytes("detail_01-08-13-0515.html").decode("utf-8")
    html = html.replace("募集定員", "定員X").replace("訓練実施機関", "機関X").replace("訓練時間：", "時間：")
    html = html.replace("訓練対象者の条件", "条件X")
    d = parse_detail.parse_detail_page(html.encode("utf-8"))
    assert d is not None
    assert d.capacity is None
    assert d.institution is None
    assert d.hours is None
    assert d.conditions is None
    assert d.facility is not None


def test_bad_round_date_is_structure_error() -> None:
    html = fixture_bytes("detail_01-08-13-0515.html").decode("utf-8").replace("2026年11月11日", "2026年13月11日", 1)
    with pytest.raises(StructureError, match="date"):
        parse_detail.parse_detail_page(html.encode("utf-8"))


def test_blank_text_boxes_become_none() -> None:
    html = fixture_bytes("detail_03-08-27-0234.html").decode("utf-8")
    html = re.sub(r"<div>特になし</div>", "<div>&nbsp;</div>", html)
    d = parse_detail.parse_detail_page(html.encode("utf-8"))
    assert d is not None and d.conditions is None


def test_normalize_text() -> None:
    assert parse_detail.normalize("　ＩｏＴ  科\n（２か月） ") == "IoT 科 (2か月)"
    assert parse_detail.normalize("   ") is None
    assert parse_detail.normalize(None) is None


def test_japanese_date() -> None:
    assert parse_detail.japanese_date("2026年1月5日") == date(2026, 1, 5)
    assert parse_detail.japanese_date("令和8年1月5日") is None
    assert parse_detail.japanese_date("2026年2月30日") is None


def test_label_inside_prose_does_not_hide_the_box() -> None:
    # 訓練内容 of this course says 「訓練期間中から…」 before the real box.
    d = detail("03-08-13-0527")
    assert (d.training_start, d.training_end) == (date(2027, 1, 4), date(2027, 6, 30))
    assert d.hours is not None and d.self_cost is not None


def test_zero_hours_of_e_learning_become_none() -> None:
    html = fixture_bytes("detail_01-08-13-0515.html").decode("utf-8")
    html = html.replace("<span>16:00</span>", "<span>00:00</span>").replace("<span>20:50</span>", "<span>00:00</span>")
    d = parse_detail.parse_detail_page(html.encode("utf-8"))
    assert d is not None and d.hours is None


def test_five_rounds_are_all_read() -> None:
    d = parse_detail.parse_detail_page(five_round_detail())
    assert d is not None
    assert [r.no for r in d.rounds] == [1, 2, 3, 4, 5]
    assert (d.rounds[3].start, d.rounds[4].end) == (date(2027, 2, 23), date(2027, 3, 24))
    assert d.rounds[4].selection == date(2027, 3, 27)
