#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.output_store import (
    KEEP_SNAPSHOTS,
    format_range_label,
    list_range_snapshot_files,
    list_trash_range_files,
    load_all_list_rows,
    next_range_sequence,
    publish_csv,
    publish_tob_outputs,
    range_snapshot_filename,
    read_fetch_meta,
    resolve_current_csv,
)
from tob.tob_common import merge_document_rows, normalize_doc_row


class OutputStoreTests(unittest.TestCase):
    RANGE = "202001-202012"

    def test_publish_writes_current_and_range_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"DocID": "S100AAAA"}]
            latest = publish_csv(
                root,
                "tob_list",
                rows,
                ["DocID"],
                range_label=self.RANGE,
                day=date(2026, 8, 17),
            )
            self.assertEqual(latest, root / "current" / "tob_list.csv")
            self.assertTrue(latest.exists())
            snap = root / "snapshots" / range_snapshot_filename("tob_list", self.RANGE, 1)
            self.assertTrue(snap.exists())
            self.assertEqual(snap.name, "tob_list_202001-202012_0001.csv")
            self.assertEqual(resolve_current_csv(root, "tob_list"), latest)

    def test_same_day_rerun_increments_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = date(2026, 8, 17)
            publish_csv(root, "tob_cases", [{"a": "1"}], ["a"], range_label=self.RANGE, day=day)
            publish_csv(root, "tob_cases", [{"a": "2"}], ["a"], range_label=self.RANGE, day=day)
            live = list_range_snapshot_files(root, "tob_cases", self.RANGE)
            self.assertEqual([seq for seq, _ in live], [1, 2])
            text = live[-1][1].read_text(encoding="utf-8")
            self.assertIn("2", text)

    def test_different_day_same_range_continues_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish_csv(
                root,
                "tob_list",
                [{"n": "1"}],
                ["n"],
                range_label=self.RANGE,
                day=date(2026, 8, 17),
            )
            publish_csv(
                root,
                "tob_list",
                [{"n": "2"}],
                ["n"],
                range_label=self.RANGE,
                day=date(2026, 8, 18),
            )
            live = list_range_snapshot_files(root, "tob_list", self.RANGE)
            self.assertEqual([seq for seq, _ in live], [1, 2])

    def test_old_snapshots_move_to_trash_after_20(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            start = date(2026, 1, 1)
            for i in range(KEEP_SNAPSHOTS + 5):
                day = start + timedelta(days=i)
                publish_csv(root, "tob_list", [{"n": str(i)}], ["n"], range_label=self.RANGE, day=day)

            live = list_range_snapshot_files(root, "tob_list", self.RANGE)
            trash = list_trash_range_files(root, "tob_list", self.RANGE)
            self.assertEqual(len(live), KEEP_SNAPSHOTS)
            self.assertEqual(len(trash), 5)
            self.assertTrue(all(path.parent.name == "trash" for _, path in trash))
            self.assertTrue((root / "current" / "tob_list.csv").exists())

    def test_format_range_label(self) -> None:
        self.assertEqual(
            format_range_label(date(2020, 1, 15), date(2020, 12, 31)),
            "202001-202012",
        )

    def test_next_range_sequence_uses_jst_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap = root / "snapshots" / range_snapshot_filename("tob_list", self.RANGE, 1)
            snap.parent.mkdir(parents=True)
            snap.write_text("x", encoding="utf-8")
            jst = timezone(timedelta(hours=9))
            noon_jst = datetime(2026, 8, 17, 12, 0, tzinfo=jst).timestamp()
            import os

            os.utime(snap, (noon_jst, noon_jst))
            self.assertEqual(next_range_sequence(root, "tob_list", self.RANGE, day=date(2026, 8, 17)), 2)

    def test_recent_merge_preserves_existing_rows_and_fetch_meta(self) -> None:
        """Simulates --recent-days upsert: merge into current CSV, keep full-range meta."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full_range = "201701-202608"
            full_start = date(2017, 1, 1)
            full_end = date(2026, 8, 18)
            existing = [
                normalize_doc_row(
                    {
                        "DocID": f"S100{i:04d}",
                        "DocTypeCode": "240",
                        "SubmitDateTime": "2017-01-10 10:00",
                        "FilerName": "Buyer KK",
                        "FilerEdinetCode": "E11111",
                        "SubjectEdinetCode": "E22222",
                    }
                )
                for i in range(50)
            ]
            publish_tob_outputs(
                root,
                existing,
                [],
                range_label=full_range,
                fetch_meta={"start": full_start, "end": full_end, "mode": "years"},
            )
            prior = read_fetch_meta(root)
            self.assertIsNotNone(prior)
            assert prior is not None

            incoming = [
                {
                    "DocID": "S100NEW1",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-08-20 10:00",
                    "FilerName": "New Buyer",
                    "FilerEdinetCode": "E99999",
                    "SubjectEdinetCode": "E88888",
                }
            ]
            merged, added, updated = merge_document_rows(load_all_list_rows(root), incoming)
            self.assertEqual(added, 1)
            self.assertEqual(len(merged), 51)

            recent_end = date(2026, 8, 20)
            publish_tob_outputs(
                root,
                merged,
                [],
                range_label=str(prior["range_label"]),
                fetch_meta={
                    "start": date.fromisoformat(str(prior["start"])),
                    "end": recent_end,
                    "mode": str(prior.get("mode") or "years"),
                },
            )
            self.assertEqual(len(load_all_list_rows(root)), 51)
            meta = read_fetch_meta(root)
            self.assertIsNotNone(meta)
            assert meta is not None
            self.assertEqual(meta["range_label"], full_range)
            self.assertEqual(meta["mode"], "years")
            self.assertEqual(meta["start"], "2017-01-01")
            self.assertEqual(meta["end"], "2026-08-20")


if __name__ == "__main__":
    unittest.main()
