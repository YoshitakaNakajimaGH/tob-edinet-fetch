#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from output_store import (
    KEEP_SNAPSHOTS,
    list_snapshot_files,
    list_trash_files,
    publish_csv,
    resolve_current_csv,
    snapshot_path,
)


class OutputStoreTests(unittest.TestCase):
    def test_publish_writes_current_and_dated_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"DocID": "S100AAAA"}]
            latest = publish_csv(root, "tob_list", rows, ["DocID"], day=date(2026, 8, 17))
            self.assertEqual(latest, root / "current" / "tob_list.csv")
            self.assertTrue(latest.exists())
            snap = snapshot_path(root, "tob_list", date(2026, 8, 17))
            self.assertTrue(snap.exists())
            self.assertEqual(snap.name, "tob_list_20260817.csv")
            self.assertEqual(resolve_current_csv(root, "tob_list"), latest)

    def test_old_snapshots_move_to_trash_after_20(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            start = date(2026, 1, 1)
            for i in range(KEEP_SNAPSHOTS + 5):
                day = start + timedelta(days=i)
                publish_csv(root, "tob_list", [{"n": str(i)}], ["n"], day=day)

            live = list_snapshot_files(root, "tob_list")
            trash = list_trash_files(root, "tob_list")
            self.assertEqual(len(live), KEEP_SNAPSHOTS)
            self.assertEqual(len(trash), 5)
            self.assertEqual(live[0][0], date(2026, 1, 1) + timedelta(days=KEEP_SNAPSHOTS + 4))
            self.assertTrue(all(path.parent.name == "trash" for _, path in trash))
            self.assertTrue((root / "current" / "tob_list.csv").exists())

    def test_same_day_overwrite_does_not_consume_a_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish_csv(root, "tob_cases", [{"a": "1"}], ["a"], day=date(2026, 8, 17))
            publish_csv(root, "tob_cases", [{"a": "2"}], ["a"], day=date(2026, 8, 17))
            live = list_snapshot_files(root, "tob_cases")
            self.assertEqual(len(live), 1)
            text = (root / "snapshots" / "2026" / "08" / "tob_cases_20260817.csv").read_text(encoding="utf-8")
            self.assertIn("2", text)


if __name__ == "__main__":
    unittest.main()
