#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edinet.edinet_code_list import load_edinet_code_list
from tob.extract_fields import (
    DELISTING_DONE,
    DELISTING_PLANNED,
    LISTING_MAINTAINED,
    format_sec_code,
    judge_target_delisting,
)
from tob.tob_common import build_cases, normalize_doc_row, refresh_target_metadata


class TargetMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cache = ROOT / "tests" / "fixtures" / "edinet_code_min.csv"
        cls.edinet_list = load_edinet_code_list(cache)

    def test_format_sec_code_strips_check_digit(self) -> None:
        self.assertEqual(format_sec_code("41240"), "4124")
        self.assertEqual(format_sec_code("90660"), "9066")
        self.assertEqual(format_sec_code("2371"), "2371")

    def test_delisting_judgement(self) -> None:
        planned_text = "当社株式が上場廃止となる予定であることを前提として行われたものです。"
        maintain_text = (
            "公開買付者が本公開買付けにおいて本投資法人投資口の上場廃止を企図しておらず、"
            "本公開買付け後も本投資法人投資口の上場が維持される予定であるため"
        )
        self.assertEqual(
            judge_target_delisting("成立", "上場", [planned_text]),
            DELISTING_PLANNED,
        )
        self.assertEqual(
            judge_target_delisting("成立", "非上場", [planned_text]),
            DELISTING_DONE,
        )
        self.assertEqual(
            judge_target_delisting("成立", "上場", [maintain_text]),
            LISTING_MAINTAINED,
        )
        self.assertEqual(judge_target_delisting("不成立", "上場", [planned_text]), "")

    def test_case_includes_target_sec_and_delisting(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "CaseID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-05-12 10:00",
                    "FilerName": "Buyer",
                    "FilerEdinetCode": "E40649",
                    "SubjectEdinetCode": "E04320",
                    "TargetName": "株式会社日新",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100OPN",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "290",
                    "SubmitDateTime": "2025-05-13 10:00",
                    "FilerName": "株式会社日新",
                    "FilerSecCode": "90660",
                    "FilerEdinetCode": "E04320",
                    "SubjectEdinetCode": "E40649",
                    "OpinionRaw": "当社株式が上場廃止となる予定であることを前提として行われたものです。",
                    "OpinionStance": "賛同",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100REPORT",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "270",
                    "SubmitDateTime": "2025-06-20 10:00",
                    "FilerName": "Buyer",
                    "FilerEdinetCode": "E40649",
                    "SubjectEdinetCode": "E04320",
                    "FinalResultRaw": "応募株券等の全部の買付け等を行います。",
                    "ExtractionStatus": "done",
                }
            ),
        ]
        refresh_target_metadata(rows, self.edinet_list)
        case = build_cases(rows, self.edinet_list)[0]
        self.assertEqual(case["TargetSecCode"], "9066")
        self.assertEqual(case["TargetDelistingNote"], DELISTING_DONE)
        self.assertIn("TargetSecCode", case)
        self.assertIn("TargetDelistingNote", case)


if __name__ == "__main__":
    unittest.main()
