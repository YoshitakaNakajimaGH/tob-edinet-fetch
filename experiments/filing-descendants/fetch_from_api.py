#!/usr/bin/env python3
"""Build a filing-rooted document list from the EDINET list API.

Does not read output/current/tob_list.csv or any other saved list.
For one calendar month of doc type 240, downloads documents.json for
every day from the 1st of that month through `within_days` after month-end,
keeps doc types 240-320, then walks ParentDocID downward from each filing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

from edinet.edinet_code_list import EdinetCodeList, ensure_edinet_code_list
from tob.fetch_tob import fetch_day, row_from_doc
from tob.tob_common import is_issuer_tender

from run_filing_descendants import collect


def window_for_month(month: str, within_days: int) -> tuple[date, date]:
    """First day of `month` through `within_days` after the last day."""
    year_text, month_text = month.split("-", 1)
    year, mon = int(year_text), int(month_text)
    if mon < 1 or mon > 12:
        raise ValueError(f"invalid month: {month}")
    start = date(year, mon, 1)
    last = date(year, mon, monthrange(year, mon)[1])
    return start, last + timedelta(days=within_days)


def _metadata_status(payload: dict) -> str:
    metadata = payload.get("metadata") or {}
    return str(metadata.get("status") or "")


def fetch_day_with_retry(day: date, api_key: str, *, attempts: int = 5) -> dict:
    """Call the list API. Auth failures stop the run. Other errors retry."""
    delay = 2.0
    last_error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            payload = fetch_day(day, api_key)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code in (401, 403):
                raise SystemExit(f"EDINET API rejected the key (HTTP {exc.code}).")
            last_error = f"HTTP {exc.code} {body}"
        except Exception as exc:  # noqa: BLE001 - retry transient network failures
            last_error = str(exc)
        else:
            status = _metadata_status(payload)
            if status in ("", "200", "404"):
                if status == "404":
                    return {"metadata": payload.get("metadata") or {}, "results": []}
                return payload
            if status in ("401", "403"):
                raise SystemExit(f"EDINET API rejected the key (status {status}).")
            last_error = f"status {status}"
        if attempt < attempts:
            print(f"  retry {attempt}/{attempts - 1} in {delay:.0f}s: {last_error}", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(last_error)


def fetch_tob_rows(
    start: date,
    end: date,
    api_key: str,
    *,
    sleep_seconds: float,
) -> tuple[list[dict], list[str], dict[str, int]]:
    rows: list[dict] = []
    failed: list[str] = []
    daily: dict[str, int] = {}
    total_days = (end - start).days + 1
    current = start
    index = 0
    while current <= end:
        index += 1
        key = current.isoformat()
        try:
            payload = fetch_day_with_retry(current, api_key)
        except RuntimeError as exc:
            failed.append(key)
            daily[key] = -1
            print(f"[{index}/{total_days}] {key} FAILED {exc}", flush=True)
        else:
            day_rows = []
            for doc in payload.get("results") or []:
                row = row_from_doc(doc)
                if row:
                    day_rows.append(row)
            rows.extend(day_rows)
            daily[key] = len(day_rows)
            print(
                f"[{index}/{total_days}] {key} tob={len(day_rows)} cumulative={len(rows)}",
                flush=True,
            )
        time.sleep(sleep_seconds)
        current += timedelta(days=1)
    return rows, failed, daily


def _apply_code_list(cases: list[dict], rows: list[dict], code_list: EdinetCodeList | None) -> None:
    by_id = {row.get("DocID") or "": row for row in rows}
    for case in cases:
        root = by_id.get(case.get("case_id") or "", {})
        case["issuer_tender"] = is_issuer_tender(root)
        if code_list is None:
            continue
        subject = root.get("SubjectEdinetCode") or ""
        info = code_list.get(subject)
        if info and info.name:
            case["target_name"] = info.name
        label = code_list.listing_label(edinet_code=subject)
        if label:
            case["target_sec_code"] = label


def build_report(
    rows: list[dict],
    *,
    month: str,
    within_days: int,
    fetched_from: date,
    fetched_to: date,
    failed_days: list[str],
    daily_tob_counts: dict[str, int],
    code_list: EdinetCodeList | None = None,
) -> dict:
    cases = collect(rows, month=month, within_days=within_days)
    _apply_code_list(cases, rows, code_list)
    issuer = [case for case in cases if case.get("issuer_tender")]
    other = [case for case in cases if not case.get("issuer_tender")]

    def _with_outcome(group: list[dict]) -> int:
        return sum(1 for case in group if case.get("has_outcome"))

    return {
        "source": "edinet-api-v2-documents.json",
        "read_saved_list_csv": False,
        "month": month,
        "within_days": within_days,
        "fetched_from": fetched_from.isoformat(),
        "fetched_to": fetched_to.isoformat(),
        "failed_days": failed_days,
        "daily_tob_counts": daily_tob_counts,
        "tob_document_count": len(rows),
        "filing_count": len(cases),
        "issuer_filing_count": len(issuer),
        "other_filing_count": len(other),
        "filings_with_outcome": _with_outcome(cases),
        "issuer_filings_with_outcome": _with_outcome(issuer),
        "other_filings_with_outcome": _with_outcome(other),
        "cases": cases,
    }


def _print_summary(report: dict) -> None:
    print(
        f"{report['month']}: API {report['fetched_from']}..{report['fetched_to']} "
        f"tob_docs={report['tob_document_count']} "
        f"filings={report['filing_count']} "
        f"(other={report['other_filing_count']}, issuer={report['issuer_filing_count']}) "
        f"with_outcome={report['filings_with_outcome']} "
        f"failed_days={len(report['failed_days'])}",
        flush=True,
    )
    for case in report["cases"]:
        kind = "issuer" if case.get("issuer_tender") else "other"
        counts = " ".join(f"{code}:{count}" for code, count in sorted(case["type_counts"].items()))
        print(
            f"  {case['case_id']} {case['filing_date']} {kind} "
            f"docs={case['doc_count']} outcome={case['has_outcome']} {counts} "
            f"{case['offeror_name']} -> {case['target_name']}",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--within-days", type=int, default=183)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--edinet-cache",
        default="cache/edinet/EdinetcodeDlInfo.csv",
        help="提出者リストのキャッシュ。名前解決にだけ使う",
    )
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY がありません。", file=sys.stderr)
        return 1

    start, end = window_for_month(args.month, args.within_days)
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

    report = build_report(
        rows,
        month=args.month,
        within_days=args.within_days,
        fetched_from=start,
        fetched_to=end,
        failed_days=failed,
        daily_tob_counts=daily,
        code_list=code_list,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(report)
    print(f"Wrote {out}", flush=True)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
