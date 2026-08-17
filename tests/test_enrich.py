#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrich_tob import parse_opinion_stance, parse_period_dates, summarize_price


class ParseHelperTests(unittest.TestCase):
    def test_parse_period_dates(self) -> None:
        start, end = parse_period_dates("2026年1月7日から2026年2月19日まで")
        self.assertEqual(start, "2026-01-07")
        self.assertEqual(end, "2026-02-19")

    def test_summarize_price(self) -> None:
        self.assertEqual(
            summarize_price("普通株式１株につき、金6,082円とする。"),
            "6,082円/株",
        )

    def test_opinion_stance(self) -> None:
        self.assertEqual(parse_opinion_stance("本公開買付けに賛同する。"), "賛同")
        self.assertEqual(parse_opinion_stance("反対の意見を表明する。"), "反対")


if __name__ == "__main__":
    unittest.main()
