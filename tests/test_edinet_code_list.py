#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edinet.edinet_code_list import (
    UNLISTED_LABEL,
    load_edinet_code_list,
    normalize_company_name,
)


FIXTURE = ROOT / "tests" / "fixtures" / "edinet_code_min.csv"


class EdinetCodeListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edinet = load_edinet_code_list(FIXTURE)

    def test_normalize_company_name(self) -> None:
        self.assertEqual(normalize_company_name("株式会社ダイセキ"), "ダイセキ")

    def test_lookup_by_name_listed(self) -> None:
        info = self.edinet.lookup_by_name("株式会社ダイセキ")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.sec_code, "97930")

    def test_listing_label_listed(self) -> None:
        self.assertEqual(
            self.edinet.listing_label(edinet_code="E04931"),
            "9793",
        )

    def test_listing_label_unlisted(self) -> None:
        self.assertEqual(
            self.edinet.listing_label(edinet_code="E03240"),
            UNLISTED_LABEL,
        )


if __name__ == "__main__":
    unittest.main()
