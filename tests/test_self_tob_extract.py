#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.extract_fields import judge_self_tob_result, parse_self_tob_report_counts
from tob.taxonomy import TaxonomyCatalog


class SelfTobReportCountTests(unittest.TestCase):
    def test_parses_application_and_purchase(self) -> None:
        text = (
            "（１）【買付け等を行った上場株券等の数】\n"
            "普通株式　応募数（1,234,567株）　買付数（1,000,000株）"
        )
        parsed = parse_self_tob_report_counts(text)
        self.assertEqual(parsed["ApplicationCount"], "1,234,567")
        self.assertEqual(parsed["PurchaseCount"], "1,000,000")
        self.assertEqual(parsed["ProrataUsed"], "Yes")

    def test_prorata_from_calculation_block(self) -> None:
        acquired = "普通株式　応募数（500株）　買付数（500株）"
        prorata = "あん分比例方式により買付け等を行いました。"
        parsed = parse_self_tob_report_counts(acquired, prorata)
        self.assertEqual(parsed["ProrataUsed"], "Yes")
        self.assertEqual(judge_self_tob_result(acquired, prorata), "成立（按分）")

    def test_no_prorata_when_equal(self) -> None:
        text = "普通株式　応募数（100株）　買付数（100株）"
        parsed = parse_self_tob_report_counts(text)
        self.assertEqual(parsed["ProrataUsed"], "No")
        self.assertEqual(judge_self_tob_result(text), "成立")


class IssuerTaxonomyTests(unittest.TestCase):
    def test_issuer_mapping_loads(self) -> None:
        catalog = TaxonomyCatalog(ROOT / "tob" / "taxonomy")
        mapping = catalog.mapping_for_year(2021, issuer=True)
        self.assertIn("ton", mapping)
        self.assertIn("jptoi_cor:PriceOfPurchaseEtcTextBlock", mapping["ton"]["offer_price_text"])

    def test_detects_issuer_facts(self) -> None:
        catalog = TaxonomyCatalog(ROOT / "tob" / "taxonomy")
        facts = {"jptoi_cor:FundForPurchaseEtcTextBlock": ["dummy"]}
        year = catalog.detect_from_facts(facts, issuer=True)
        self.assertEqual(year, "2026")


if __name__ == "__main__":
    unittest.main()
