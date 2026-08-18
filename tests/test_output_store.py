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

from output_store import (
    KEEP_SNAPSHOTS,
    format_range_label,
    list_range_snapshot_files,
    list_trash_range_files,
    next_range_sequence,
    publish_csv,
    range_snapshot_filename,
    resolve_current_csv,
)


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


if __name__ == "__main__":
    unittest.main()
