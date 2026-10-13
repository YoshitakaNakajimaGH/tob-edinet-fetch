#!/usr/bin/env python3
"""Write one month's ID list JSON to an explicit path.

The maintained command is `python -m tob.id_list`, which writes
`output/id_lists/YYYY-MM.json`. This wrapper keeps the earlier one-file
experiment command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edinet.edinet_code_list import ensure_edinet_code_list  # noqa: E402
from tob.id_list import (  # noqa: E402
    build_month_reports,
    fetch_bounds,
    fetch_tob_rows,
    iter_months,
    parse_month,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--within-days", type=int, default=183)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--out", required=True)
    parser.add_argument("--edinet-cache", default="cache/edinet/EdinetcodeDlInfo.csv")
    args = parser.parse_args(argv)

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY がありません。", file=sys.stderr)
        return 1

    month = parse_month(args.month)
    today = date.today()
    start, end = fetch_bounds([month], args.within_days, today)
    print(f"Live list API {start.isoformat()} .. {end.isoformat()} (no saved CSV)", flush=True)
    rows, failed, daily = fetch_tob_rows(start, end, api_key, sleep_seconds=args.sleep)
    if not rows and failed:
        print("一覧APIから書類を1件も取れませんでした。", file=sys.stderr)
        return 1

    code_list = None
    try:
        code_list = ensure_edinet_code_list(Path(args.edinet_cache))
    except RuntimeError as exc:
        print(f"提出者リストは使えません。名前は提出者名のみにします: {exc}", flush=True)

    report = build_month_reports(
        rows,
        iter_months(month, month),
        within_days=args.within_days,
        today=today,
        failed_days=failed,
        daily_tob_counts=daily,
        code_list=code_list,
    )[0]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{month}: filings={report['filing_count']} with_outcome={report['filings_with_outcome']}",
        flush=True,
    )
    print(f"Wrote {out}", flush=True)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
