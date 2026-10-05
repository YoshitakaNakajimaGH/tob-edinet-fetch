"""Filing-rooted document lists, without calling the EDINET API."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "filing-descendants"))

from fetch_from_api import build_report, window_for_month  # noqa: E402


def _row(
    doc_id: str,
    type_code: str,
    submitted: str,
    parent: str = "",
    *,
    filer: str = "E00001",
    subject: str = "E00002",
    filer_name: str = "買付者",
) -> dict:
    return {
        "DocID": doc_id,
        "DocTypeCode": type_code,
        "DocTypeName": type_code,
        "SubmitDateTime": submitted,
        "ParentDocID": parent,
        "FilerName": filer_name,
        "FilerEdinetCode": filer,
        "SubjectEdinetCode": subject,
        "OfferorName": "",
        "TargetName": "",
        "TargetSecCode": "",
    }


class WindowTests(unittest.TestCase):
    def test_january_2026_plus_183_days_ends_on_august_2(self) -> None:
        start, end = window_for_month("2026-01", 183)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 8, 2))

    def test_script_imports_when_cwd_is_not_the_repo(self) -> None:
        script = Path(__file__).resolve().parents[1] / "experiments" / "filing-descendants" / "fetch_from_api.py"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("documents.json", proc.stdout)


class ReportTests(unittest.TestCase):
    def test_descendants_follow_parent_chain_and_skip_saved_csv_fields(self) -> None:
        rows = [
            _row("S240", "240", "2026-01-15 09:00"),
            _row("S290", "290", "2026-01-16 09:00", "S240", filer="E00002", subject="E00001"),
            _row("S300", "300", "2026-02-01 09:00", "S290", filer="E00002", subject="E00001"),
            _row("S270", "270", "2026-04-01 09:00", "S240"),
            _row("S270LATE", "270", "2026-08-01 09:00", "S240"),
            _row("SFEB", "240", "2026-02-02 09:00"),
            _row("SSELF", "240", "2026-01-20 09:00", filer="E00009", subject="E00009", filer_name="自社"),
            _row("SSELF270", "270", "2026-03-01 09:00", "SSELF", filer="E00009", subject="E00009"),
        ]
        report = build_report(
            rows,
            month="2026-01",
            within_days=183,
            fetched_from=date(2026, 1, 1),
            fetched_to=date(2026, 8, 2),
            failed_days=[],
            daily_tob_counts={"2026-01-15": 2},
        )
        self.assertFalse(report["read_saved_list_csv"])
        self.assertEqual(report["source"], "edinet-api-v2-documents.json")
        self.assertEqual(report["filing_count"], 2)
        self.assertEqual(report["other_filing_count"], 1)
        self.assertEqual(report["issuer_filing_count"], 1)
        self.assertEqual(report["other_filings_with_outcome"], 1)
        self.assertEqual(report["issuer_filings_with_outcome"], 1)

        other = next(case for case in report["cases"] if case["case_id"] == "S240")
        self.assertEqual(
            [doc["doc_id"] for doc in other["documents"]],
            ["S240", "S290", "S300", "S270"],
        )
        self.assertNotIn("S270LATE", [doc["doc_id"] for doc in other["documents"]])
        self.assertTrue(other["has_outcome"])
        self.assertFalse(other["issuer_tender"])

        issuer = next(case for case in report["cases"] if case["case_id"] == "SSELF")
        self.assertTrue(issuer["issuer_tender"])
        self.assertEqual(issuer["doc_count"], 2)


if __name__ == "__main__":
    unittest.main()
