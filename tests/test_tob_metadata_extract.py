#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extract_fields import (
    detect_mbo,
    extract_parent_hint,
    extract_sponsor_from_purposes,
    extract_tender_offer_agent,
    extract_valuation_from_purposes,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_valuation_from_sources,
    parse_valuation_ranges,
)
from tob_common import columns_for_enrich_groups, parse_enrich_groups


class SponsorHintTests(unittest.TestCase):
    def test_second_paragraph_subject_before_wa(self) -> None:
        text = (
            "（１）本公開買付の概要\n"
            "公開買付者は、ケイマン諸島法に基づくリミテッド・パートナーシップです。\n"
            "ベインキャピタルは、本公開買付けを通じて対象者株式の非公開化を企図しております。"
        )
        self.assertEqual(extract_sponsor_from_purposes(text), "ベインキャピタル")

    def test_skips_offeror_subject(self) -> None:
        text = (
            "（１）本公開買付の概要\n"
            "第一段落。\n"
            "公開買付者は、本公開買付価格を決定するにあたり、対象者と協議しました。"
        )
        self.assertEqual(extract_sponsor_from_purposes(text), "")


class MboDetectTests(unittest.TestCase):
    def test_detects_mbo_keyword(self) -> None:
        self.assertEqual(detect_mbo(["2025年８月６日付「ＭＢＯの実施及び応募の推奨に関するお知らせ」"]), "Yes")

    def test_ignores_management_presentation(self) -> None:
        self.assertEqual(
            detect_mbo(["対象者からのマネジメントプレゼンテーション等に基づき分析しました。"]),
            "",
        )


class ValuationRangeTests(unittest.TestCase):
    def test_parses_three_methods(self) -> None:
        text = (
            "算定の基礎　市場株価法：1,902円から2,001円 "
            "類似上場会社比較法：978円から1,242円 "
            "DCF法：2,733円から4,501円"
        )
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "1,902")
        self.assertEqual(parsed["ValuationMarketMax"], "2,001")
        self.assertEqual(parsed["ValuationComparableMin"], "978")
        self.assertEqual(parsed["ValuationComparableMax"], "1,242")
        self.assertEqual(parsed["ValuationDCFMin"], "2,733")
        self.assertEqual(parsed["ValuationDCFMax"], "4,501")

    def test_parses_lerz_style(self) -> None:
        text = "算定の基礎 市場株価法：1,675円から1,698円 DCF法　　 ：2,199円から2,783円"
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "1,675")
        self.assertEqual(parsed["ValuationDCFMax"], "2,783")

    def test_parses_fullwidth_dcf_and_tilde(self) -> None:
        text = "算定の基礎 市場株価平均法：997円～1,017円ＤＣＦ法　　　：524円～1,480円"
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "997")
        self.assertEqual(parsed["ValuationMarketMax"], "1,017")
        self.assertEqual(parsed["ValuationDCFMin"], "524")
        self.assertEqual(parsed["ValuationDCFMax"], "1,480")

    def test_parses_valuation_from_purposes_section(self) -> None:
        price = "算定の基礎 第三者算定機関からの算定書は取得しておりません。"
        purposes = (
            "３【買付け等の目的】(3）本公開買付価格の公正性を担保するための措置 "
            "ＳＭＢＣ日興証券は、市場株価法：1,420円から1,480円 "
            "類似上場会社比較法：1,350円から1,510円 "
            "ＤＣＦ法：1,600円から2,100円の範囲で算定しました。"
        )
        parsed = parse_valuation_from_sources(price, purposes)
        self.assertEqual(parsed["ValuationMarketMin"], "1,420")
        self.assertEqual(parsed["ValuationDCFMax"], "2,100")

    def test_extract_valuation_from_purposes_finds_keyword_window(self) -> None:
        text = (
            "背景説明が長く続きます。" * 20
            + "公開買付者は、市場株価法：900円から950円、ＤＣＦ法：1,100円から1,300円と算定。"
        )
        section = extract_valuation_from_purposes(text)
        self.assertIn("市場株価法", section)
        self.assertIn("ＤＣＦ法", section)


class EnrichFieldGroupTests(unittest.TestCase):
    def test_parse_groups_defaults_to_all(self) -> None:
        self.assertEqual(parse_enrich_groups(""), frozenset({"all"}))
        self.assertIsNone(columns_for_enrich_groups(frozenset({"all"})))

    def test_parse_specific_groups(self) -> None:
        groups = parse_enrich_groups("valuation, fund")
        columns = columns_for_enrich_groups(groups)
        self.assertIn("ValuationMarketMin", columns)
        self.assertIn("PurchaseConsideration", columns)
        self.assertNotIn("PlannedSharesPlanned", columns)


class PlannedPurchaseTests(unittest.TestCase):
    def test_parses_floor_and_cap_from_total_row(self) -> None:
        text = (
            "普通株式 上限（100株）下限（50株）"
            "合計 上限（5,467,100株）下限（5,467,100株）"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesMin"], "5,467,100")
        self.assertEqual(parsed["PlannedSharesMax"], "5,467,100")
        self.assertEqual(parsed["PlannedSharesPlanned"], "")

    def test_parses_single_planned_count_on_total(self) -> None:
        text = "普通株式 上限（100株）合計 買付予定数（2,000,000株）"
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,000,000")

    def test_parses_xbrl_table_without_bounds(self) -> None:
        text = (
            "株券等の種類買付予定数買付予定数の下限買付予定数の上限"
            "普通株式2,517,495(株)―(株)―(株)合計2,517,495(株)―(株)―(株)"
            "上限及び下限を設定しておりません"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,517,495")

    def test_parses_fullwidth_share_parentheses(self) -> None:
        text = (
            "普通株式2,448,692（株）―（株）―（株）"
            "合計2,448,692（株）―（株）―（株）"
            "上限及び下限を設定しておりません"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,448,692")

    def test_parses_xbrl_table_with_floor_only(self) -> None:
        text = (
            "普通株式20,252,536(株)4,297,400(株)－(株)"
            "合計20,252,536(株)4,297,400(株)－(株)"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesMin"], "4,297,400")
        self.assertEqual(parsed["PlannedSharesMax"], "")
        self.assertEqual(parsed["PlannedSharesPlanned"], "")


class PurchaseConsiderationTests(unittest.TestCase):
    def test_parses_yen_amount(self) -> None:
        text = "８【買付け等に要する資金】 買付代金（a） 38,234,567,890円 借入金（b）"
        self.assertEqual(parse_purchase_consideration(text), "38,234,567,890円")

    def test_parses_won_amount(self) -> None:
        text = "買付代金(a) 120,000,000ウォン"
        self.assertEqual(parse_purchase_consideration(text), "120,000,000ウォン")

    def test_parses_yen_before_a_marker(self) -> None:
        text = "買付代金(円)(a)3,222,393,600金銭以外の対価"
        self.assertEqual(parse_purchase_consideration(text), "3,222,393,600円")

    def test_parses_fullwidth_yen_marker(self) -> None:
        text = "買付代金（円）(a)97,809,894,000金銭以外"
        self.assertEqual(parse_purchase_consideration(text), "97,809,894,000円")


class ParentHintTests(unittest.TestCase):
    def test_parent_label_pattern(self) -> None:
        text = "株式会社ABCホールディングス（以下「公開買付者親会社」という。）は"
        self.assertEqual(extract_parent_hint(text), "株式会社ABCホールディングス")

    def test_ownership_pattern(self) -> None:
        text = "その発行済株式の全てを株式会社テスト親が所有しており"
        self.assertEqual(extract_parent_hint(text), "株式会社テスト親")

    def test_falls_back_to_sponsor_extraction(self) -> None:
        text = "本公開買付けは、KKR Asia Holdings L.P.（以下「KKR」という。）が行う。"
        hint = extract_parent_hint(text)
        self.assertTrue(hint)
        self.assertIn("KKR", hint)


class TenderOfferAgentTests(unittest.TestCase):
    def test_prefers_cover_page_name(self) -> None:
        self.assertEqual(
            extract_tender_offer_agent("", "野村證券株式会社"),
            "野村證券株式会社",
        )

    def test_parses_application_section(self) -> None:
        text = "（１）【応募の方法】 ①公開買付代理人 名称 みずほ証券株式会社 所在地"
        self.assertEqual(extract_tender_offer_agent(text), "みずほ証券株式会社")


if __name__ == "__main__":
    unittest.main()
