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
    extract_sponsor_from_purposes,
    extract_tender_offer_agent,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_valuation_ranges,
)


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


class PurchaseConsiderationTests(unittest.TestCase):
    def test_parses_yen_amount(self) -> None:
        text = "８【買付け等に要する資金】 買付代金（a） 38,234,567,890円 借入金（b）"
        self.assertEqual(parse_purchase_consideration(text), "38,234,567,890円")

    def test_parses_won_amount(self) -> None:
        text = "買付代金(a) 120,000,000ウォン"
        self.assertEqual(parse_purchase_consideration(text), "120,000,000ウォン")


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
