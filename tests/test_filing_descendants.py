"""Filing-rooted document lists, without calling the EDINET API."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

from tob.id_list import (
    build_month_reports,
    default_filing_month,
    fetch_bounds,
    resolve_months,
    window_for_month,
)


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

    def test_default_month_is_the_latest_month_whose_window_has_closed(self) -> None:
        self.assertEqual(default_filing_month(date(2026, 10, 5)), "2026-03")
        start, end = resolve_months("", "", today=date(2026, 10, 5))
        self.assertEqual((start, end), ("2026-03", "2026-03"))

    def test_explicit_month_range(self) -> None:
        start, end = resolve_months("2026-01", "2026-03", today=date(2026, 10, 5))
        self.assertEqual((start, end), ("2026-01", "2026-03"))

    def test_open_window_stops_at_today(self) -> None:
        start, end = fetch_bounds(["2026-06"], 183, date(2026, 10, 5))
        self.assertEqual(start, date(2026, 6, 1))
        self.assertEqual(end, date(2026, 10, 5))

    def test_closed_window_stops_at_the_horizon(self) -> None:
        start, end = fetch_bounds(["2026-01"], 183, date(2026, 10, 5))
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 8, 2))

    def test_script_imports_as_a_module(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        proc = subprocess.run(
            [sys.executable, "-m", "tob.id_list", "--help"],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("documents.json", proc.stdout)
        self.assertIn("--from-month", proc.stdout)


class ReportTests(unittest.TestCase):
    def test_descendants_follow_parent_chain_and_split_by_month(self) -> None:
        rows = [
            _row("S240", "240", "2026-01-15 09:00"),
            _row("S290", "290", "2026-01-16 09:00", "S240", filer="E00002", subject="E00001"),
            _row("S300", "300", "2026-02-01 09:00", "S290", filer="E00002", subject="E00001"),
            _row("S270", "270", "2026-04-01 09:00", "S240"),
            _row("S270LATE", "270", "2026-08-01 09:00", "S240"),
            _row("SFEB", "240", "2026-02-02 09:00"),
            _row("SFEB270", "270", "2026-03-01 09:00", "SFEB"),
            _row("SSELF", "240", "2026-01-20 09:00", filer="E00009", subject="E00009", filer_name="自社"),
            _row("SSELF270", "270", "2026-03-01 09:00", "SSELF", filer="E00009", subject="E00009"),
        ]
        reports = build_month_reports(
            rows,
            ["2026-01", "2026-02"],
            within_days=183,
            today=date(2026, 10, 5),
            failed_days=[],
            daily_tob_counts={"2026-01-15": 2, "2026-08-03": 9},
        )
        by_month = {report["month"]: report for report in reports}
        january = by_month["2026-01"]
        self.assertFalse(january["read_saved_list_csv"])
        self.assertTrue(january["window_closed"])
        self.assertEqual(january["horizon_end"], "2026-08-02")
        self.assertNotIn("2026-08-03", january["daily_tob_counts"])
        self.assertEqual(january["filing_count"], 2)
        self.assertEqual(january["other_filing_count"], 1)
        self.assertEqual(january["issuer_filing_count"], 1)

        other = next(case for case in january["cases"] if case["case_id"] == "S240")
        self.assertEqual(
            [doc["doc_id"] for doc in other["documents"]],
            ["S240", "S290", "S300", "S270"],
        )
        self.assertNotIn("S270LATE", [doc["doc_id"] for doc in other["documents"]])
        self.assertFalse(other["issuer_tender"])

        february = by_month["2026-02"]
        self.assertEqual([case["case_id"] for case in february["cases"]], ["SFEB"])
        self.assertTrue(february["cases"][0]["has_outcome"])

    def test_open_month_is_marked_when_the_horizon_is_still_ahead(self) -> None:
        reports = build_month_reports(
            [_row("SJUN", "240", "2026-06-02 09:00")],
            ["2026-06"],
            within_days=183,
            today=date(2026, 10, 5),
            failed_days=[],
            daily_tob_counts={"2026-06-02": 1},
        )
        self.assertFalse(reports[0]["window_closed"])
        self.assertEqual(reports[0]["fetched_to"], "2026-10-05")
        self.assertEqual(reports[0]["horizon_end"], "2026-12-30")


if __name__ == "__main__":
    unittest.main()
