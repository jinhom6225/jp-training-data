"""Detail → pref/NN.json course object (data_schema.md)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scraper import parse_detail, record
from scraper.validate import course_problems
from tests.conftest import five_round_detail, fixture_bytes

JST = timezone(timedelta(hours=9))
CHECKED = datetime(2026, 10, 28, 6, 41, tzinfo=JST)


def detail(key: str) -> parse_detail.Detail:
    result = parse_detail.parse_detail_page(fixture_bytes(f"detail_{key}.html"))
    assert result is not None
    return result


def build(key: str, today: date = date(2026, 10, 28), childcare: bool = False) -> dict:
    return record.build_course(key, detail(key), childcare=childcare, checked_at=CHECKED, today=today)


@pytest.mark.parametrize("key", ["01-08-13-0515", "02-08-13-0504", "02-09-14-0013", "03-08-27-0234"])
def test_fixture_courses_are_valid(key: str) -> None:
    course = build(key)
    assert course_problems(course, key.split("-")[2]) == []


def test_kyushoku_course_values() -> None:
    course = build("01-08-13-0515")
    assert course["id"] == "01-08-13-0515"
    assert course["origin"] == "hwis"
    assert course["kind"] == "kyushoku"
    assert course["fields"] == ["it"]
    assert course["city"] == "新宿区"
    assert course["rounds"] == [{"no": 1, "start": "2026-10-27", "end": "2026-11-11"}]
    assert course["trainingStart"] == "2026-12-15"
    assert course["selectionDate"] == "2026-11-26"
    assert course["resultDate"] == "2026-12-02"
    assert course["capacity"] == 17
    assert course["provider"] == "株式会社 個別教育研究所 とぴあITスクール 新宿校第1教室"
    assert course["phone"] is None
    assert course["childcare"] is False
    assert course["checkedAt"] == "2026-10-28T06:41:00+09:00"
    assert course["sourceUrl"].startswith("https://www.hellowork.mhlw.go.jp/kensaku/GECA150010.do?")
    assert "sourceName" not in course and "entryMonth" not in course


def test_selection_dates_follow_the_current_or_next_round() -> None:
    assert build("02-09-14-0013", today=date(2026, 10, 28))["selectionDate"] == "2026-12-12"
    assert build("02-09-14-0013", today=date(2026, 10, 15))["selectionDate"] == "2026-10-31"
    assert build("02-09-14-0013", today=date(2027, 3, 1))["selectionDate"] == "2027-03-06"


def test_childcare_from_search_or_name() -> None:
    assert build("02-08-13-0504", childcare=True)["childcare"] is True
    assert build("03-08-27-0234", childcare=False)["childcare"] is True


def test_city_from_address_without_prefecture() -> None:
    assert build("03-08-27-0234")["city"] == "堺市堺区"


@pytest.mark.parametrize(
    ("address", "city"),
    [
        ("東京都足立区綾瀬5-6-1", "足立区"),
        ("神奈川県秦野市桜町2-1-3", "秦野市"),
        ("大阪府大阪市北区梅田1-1", "大阪市北区"),
        ("千葉県市川市八幡1-1", "市川市"),
        ("三重県四日市市諏訪町1-5", "四日市市"),
        ("広島県廿日市市下平良1-1", "廿日市市"),
        ("石川県野々市市三納1-1", "野々市市"),
        ("奈良県大和郡山市北郡山町248", "大和郡山市"),
        ("福島県郡山市虎丸町1-1", "郡山市"),
        ("富山県中新川郡上市町横法音寺1", "中新川郡上市町"),
        ("北海道上川郡東神楽町1", "上川郡東神楽町"),
        ("沖縄県島尻郡南風原町字1", "島尻郡南風原町"),
        ("福岡県小郡市小郡255-1", "小郡市"),
        ("さいたま市大宮区桜木町1", "さいたま市大宮区"),
        ("新宿区西新宿1-1", "新宿区"),
        ("東京都港区浜松町1丁目20番8号山市", "港区"),
        ("東京都東村山市本町1", "東村山市"),
        ("東京都町田市森野1", "町田市"),
        ("東京都大島町元町1", "大島町"),
        ("", None),
        (None, None),
        ("番地のみ", None),
    ],
)
def test_city_from_address(address: str | None, city: str | None) -> None:
    assert record.city_from_address(address) == city


def test_long_texts_are_cut_to_the_limits() -> None:
    assert record.clip("あ" * 301, 300) == "あ" * 299 + "…"
    assert record.clip("𠮷" * 60, 100) == "𠮷" * 49 + "…"
    assert record.clip("short", 300) == "short"
    assert record.clip(None, 10) is None


def test_bad_capacity_becomes_none() -> None:
    d = detail("01-08-13-0515")
    bad = parse_detail.Detail(**{**d.__dict__, "capacity": 0})
    course = record.build_course("01-08-13-0515", bad, childcare=False, checked_at=CHECKED, today=date(2026, 10, 28))
    assert course["capacity"] is None


def test_provider_falls_back_to_institution() -> None:
    d = detail("01-08-13-0515")
    bare = parse_detail.Detail(**{**d.__dict__, "facility": None})
    course = record.build_course("01-08-13-0515", bare, childcare=False, checked_at=CHECKED, today=date(2026, 10, 28))
    assert course["provider"] == "株式会社個別教育研究所"


def test_hidden_characters_are_removed_by_normalize() -> None:
    assert parse_detail.normalize("Web​デザイン­科") == "Webデザイン科"


def test_last_open_end() -> None:
    course = build("02-09-14-0013")
    assert record.last_end(course) == date(2027, 2, 22)


def test_five_round_course_is_published_whole() -> None:
    d = parse_detail.parse_detail_page(five_round_detail())
    assert d is not None
    course = record.build_course("02-09-14-0013", d, childcare=False, checked_at=CHECKED, today=date(2027, 3, 1))
    assert [r["no"] for r in course["rounds"]] == [1, 2, 3, 4, 5]
    assert course["selectionDate"] == "2027-03-15"
    assert course_problems(course, "14") == []
