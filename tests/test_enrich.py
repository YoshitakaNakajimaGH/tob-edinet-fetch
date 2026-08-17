#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrich_tob import parse_opinion_stance
from extract_fields import (
    clean_extracted_name,
    compute_holding_ratios,
    format_pct,
    parse_period_dates,
    summarize_price,
)


class ParseHelperTests(unittest.TestCase):
    def test_parse_period_western_and_wareki(self) -> None:
        start, end = parse_period_dates("2026年1月7日から2026年2月19日まで")
        self.assertEqual(start, "2026-01-07")
        self.assertEqual(end, "2026-02-19")
        start, end = parse_period_dates("令和７年９月26日から令和８年２月25日まで")
        self.assertEqual(start, "2025-09-26")
        self.assertEqual(end, "2026-02-25")

    def test_extended_period_uses_last_range(self) -> None:
        text = (
            "届出当初の買付け等の期間 2025年12月２日から2026年１月20日まで "
            "延長後の買付け等の期間 2025年12月２日から2026年１月27日まで"
        )
        start, end = parse_period_dates(text)
        self.assertEqual(start, "2025-12-02")
        self.assertEqual(end, "2026-01-27")

    def test_summarize_price(self) -> None:
        self.assertEqual(
            summarize_price("普通株式１株につき、金6,082円とする。"),
            "6,082円/株",
        )
        self.assertEqual(
            summarize_price("<p>公開買付価格は金3,105円です。</p>"),
            "3,105円/株",
        )

    def test_opinion_stance(self) -> None:
        self.assertEqual(parse_opinion_stance("本公開買付けに賛同する。"), "賛同")
        self.assertEqual(parse_opinion_stance("反対の意見を表明する。"), "反対")

    def test_format_pct_accepts_fraction_or_percent(self) -> None:
        self.assertEqual(format_pct("0.8225"), "82.25%")
        self.assertEqual(format_pct("12.34"), "12.34%")

    def test_existing_holding_from_voting_rights(self) -> None:
        existing, special, _ = compute_holding_ratios("100", "50", "1000")
        self.assertEqual(existing, "15%")
        self.assertEqual(special, "5%")

    def test_clean_extracted_name_strips_section_heading(self) -> None:
        self.assertEqual(
            clean_extracted_name("（１）【対象者名】株式会社ライトオン"),
            "株式会社ライトオン",
        )
        self.assertEqual(
            clean_extracted_name("【対象者名】SBI FinTech Solutions株式会社"),
            "SBI FinTech Solutions株式会社",
        )
        self.assertEqual(
            clean_extracted_name("１【対象者名】ID&Eホールディングス株式会社"),
            "ID&Eホールディングス株式会社",
        )
        self.assertEqual(clean_extracted_name("富士ソフト株式会社"), "富士ソフト株式会社")


if __name__ == "__main__":
    unittest.main()
