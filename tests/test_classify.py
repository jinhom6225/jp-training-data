"""Field classification (research §3.3): HWIS 分類 string first, then
course-name keywords, ``other`` when neither matches."""

from __future__ import annotations

import pytest

from scraper import classify
from scraper.rules import FIELD_IDS


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        # it
        ("生成AI活用 アプリ・WEB・システムエンジニア養成(午後)科", "実践コース(IT分野)", ["it"]),
        ("Javaプログラマー養成科", None, ["it"]),
        ("ネットワーク構築科", "離転職者訓練(委託)", ["it"]),
        # office
        ("OA事務科", None, ["office"]),
        ("簿記・経理実務科", "実践コース(営業・販売・事務分野)", ["office"]),
        ("貿易実務科(3か月)【託児付】", None, ["office"]),
        # medical
        ("医療事務科", "実践コース(医療事務分野)", ["medical"]),
        ("調剤薬局事務科", None, ["medical"]),
        # care
        ("介護職員初任者研修科", "実践コース(介護福祉分野)", ["care"]),
        ("介護職員実務者研修科", None, ["care"]),
        ("保育スタッフ養成科", None, ["care"]),
        # design
        ("Webデザイナー養成科", "実践コース(デザイン分野)", ["design"]),
        ("グラフィックデザイン科", None, ["design"]),
        # building
        ("電気工事科", None, ["building"]),
        ("住宅内外装仕上", "離転職者訓練(施設内)(建設関連分野)", ["building"]),
        ("マンション維持管理", None, ["building"]),
        ("ビル設備管理科", None, ["building"]),
        # manufacturing
        ("溶接加工科", None, ["manufacturing"]),
        ("機械加工技術科", None, ["manufacturing"]),
        ("金属加工科", None, ["manufacturing"]),
        # public 分類 strings seen in the first national collection
        ("溶接マスター科", "普通課程(高卒1年課程)(金属関連分野)", ["manufacturing"]),
        ("精密加工科", "離転職者訓練(施設内)(機械関連分野)", ["manufacturing"]),
        ("電気設備技術科", "離転職者訓練(施設内)(電気関連分野)", ["building"]),
        ("FAロボット科", "普通課程(高卒1年課程)(電気関連分野)", ["building", "manufacturing"]),
        ("樹脂成形科", "離転職者訓練(施設内)(その他の製造関連分野)", ["manufacturing"]),
        ("自動車工学科", "普通課程(高卒2年課程)(輸送サービス分野)", ["other"]),
        ("美容師科", "実践コース(理容・美容関連分野)", ["other"]),
        # several fields
        ("Webデザイン+プログラミング基礎科(4か月)", None, ["it", "design"]),
        ("建築CADオペレーター科(3か月)【託児付】", None, ["design", "building"]),
        # other
        ("自動車整備科", None, ["other"]),
        ("調理師養成科", None, ["other"]),
        ("ネイリストマスター養成科", "基礎コース", ["other"]),
    ],
)
def test_classify(name: str, category: str | None, expected: list[str]) -> None:
    assert classify.classify(name, category) == expected


def test_every_field_has_at_least_two_cases() -> None:
    table = classify.load_table()
    for field in FIELD_IDS:
        if field == "other":
            continue
        assert len(table.keywords[field]) >= 2, field


def test_fields_are_in_canonical_order_and_unique() -> None:
    fields = classify.classify("介護事務とWebデザインとPython", "実践コース(医療事務分野)")
    assert fields == sorted(set(fields), key=FIELD_IDS.index)
    assert "other" not in fields


def test_ascii_keywords_match_whole_words_only() -> None:
    assert classify.classify("SUITケース販売", None) != ["it"]
    assert "it" in classify.classify("IT基礎科", None)


def test_table_rejects_unknown_field(tmp_path) -> None:
    bad = tmp_path / "fields.yml"
    bad.write_text("categories: []\nkeywords:\n  cooking: [調理]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        classify.load_table(bad)
