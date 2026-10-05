#!/usr/bin/env python3
"""Replay a filing-rooted document list from a local list CSV.

This does not call EDINET. The maintained command is `python -m tob.id_list`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.id_list import collect  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-csv", default="output/current/tob_list.csv")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--within-days", type=int, default=183, help="Keep documents submitted within this many days of the filing")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with Path(args.list_csv).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cases = collect(rows, month=args.month, within_days=args.within_days)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with_outcome = sum(1 for case in cases if case["has_outcome"])
    print(f"{args.month}: {len(cases)} filings, {with_outcome} with an outcome document within {args.within_days} days")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
