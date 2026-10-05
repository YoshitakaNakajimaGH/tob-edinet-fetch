#!/usr/bin/env python3
"""届出書を起点に、EDINET一覧APIから書類IDリストを作る。

保存済みの tob_list.csv は読まない。対象月の1日から、月末の within_days 日後
（実行日がそれより前なら実行日）まで documents.json を取り、書類種別 240-320 を
ParentDocID で届出書（240）の下へつなぐ。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from edinet.edinet_code_list import EdinetCodeList, ensure_edinet_code_list
from tob.fetch_tob import fetch_day, row_from_doc
from tob.tob_common import is_issuer_tender

DEFAULT_WITHIN_DAYS = 183
DEFAULT_OUT_DIR = "output/id_lists"
MAX_MONTHS = 24
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str) -> str:
    text = (value or "").strip()
    match = _MONTH.fullmatch(text)
    if not match:
        raise ValueError(f"月は YYYY-MM で指定してください: {value}")
    year, mon = int(match.group(1)), int(match.group(2))
    if mon < 1 or mon > 12:
        raise ValueError(f"月は YYYY-MM で指定してください: {value}")
    return f"{year:04d}-{mon:02d}"


def shift_month(day: date, delta: int) -> date:
    index = day.year * 12 + (day.month - 1) + delta
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, 1)


def default_filing_month(today: date, within_days: int = DEFAULT_WITHIN_DAYS) -> str:
    """Newest filing month whose document window has fully elapsed.

    A month is ready when today is on or after (last day + within_days).
    Stored cases reached a report within 182 days, so 183 days covers them.
    """
    cursor = date(today.year, today.month, 1)
    for _ in range(36):
        cursor = shift_month(cursor, -1)
        label = f"{cursor.year:04d}-{cursor.month:02d}"
        _, horizon = window_for_month(label, within_days)
        if today >= horizon:
            return label
    raise ValueError("183日の窓が閉じた月が見つかりません")


def resolve_months(
    start: str,
    end: str,
    *,
    today: date,
    within_days: int = DEFAULT_WITHIN_DAYS,
) -> tuple[str, str]:
    start_text = (start or "").strip()
    end_text = (end or "").strip()
    if not start_text:
        start_text = default_filing_month(today, within_days)
    else:
        start_text = parse_month(start_text)
    if not end_text:
        end_text = start_text
    else:
        end_text = parse_month(end_text)
    if end_text < start_text:
        raise ValueError(f"終了月が開始月より前です: {start_text} .. {end_text}")
    months = iter_months(start_text, end_text)
    if len(months) > MAX_MONTHS:
        raise ValueError(f"一度に指定できるのは {MAX_MONTHS} ヶ月までです")
    return start_text, end_text


def iter_months(start: str, end: str) -> list[str]:
    year, mon = (int(part) for part in start.split("-"))
    last_year, last_mon = (int(part) for part in end.split("-"))
    months: list[str] = []
    while (year, mon) <= (last_year, last_mon):
        months.append(f"{year:04d}-{mon:02d}")
        mon += 1
        if mon == 13:
            year += 1
            mon = 1
    return months


def window_for_month(month: str, within_days: int) -> tuple[date, date]:
    """First day of `month` through `within_days` after the last day."""
    year_text, month_text = parse_month(month).split("-", 1)
    year, mon = int(year_text), int(month_text)
    start = date(year, mon, 1)
    last = date(year, mon, monthrange(year, mon)[1])
    return start, last + timedelta(days=within_days)


def fetch_bounds(months: list[str], within_days: int, today: date) -> tuple[date, date]:
    """API range covering every month, stopped at today when the horizon is still open."""
    start = window_for_month(months[0], within_days)[0]
    end = start
    for month in months:
        _, horizon = window_for_month(month, within_days)
        end = max(end, min(horizon, today))
    if end < start:
        raise ValueError(f"指定期間は {today.isoformat()} より先なので、まだ取得できません")
    return start, end


def month_fetch_end(month: str, within_days: int, today: date) -> tuple[date, date, bool]:
    start, horizon = window_for_month(month, within_days)
    fetched_to = min(horizon, today)
    return start, fetched_to, today >= horizon


def parse_dt(value: str) -> datetime | None:
    text = (value or "").strip()
    for fmt, size in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def collect(rows: list[dict], *, month: str, within_days: int) -> list[dict]:
    children: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        parent = (row.get("ParentDocID") or "").strip()
        if parent:
            children[parent].append(row)

    def descendants(root_id: str) -> list[dict]:
        found: list[dict] = []
        seen: set[str] = set()
        stack = [root_id]
        while stack:
            parent = stack.pop()
            for child in children.get(parent, []):
                doc_id = child.get("DocID") or ""
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                found.append(child)
                stack.append(doc_id)
        found.sort(key=lambda doc: doc.get("SubmitDateTime") or "")
        return found

    filings = [
        row
        for row in rows
        if row.get("DocTypeCode") == "240" and (row.get("SubmitDateTime") or "").startswith(month)
    ]
    filings.sort(key=lambda row: row.get("SubmitDateTime") or "")

    cases: list[dict] = []
    for root in filings:
        start = parse_dt(root.get("SubmitDateTime") or "")
        docs = [root, *descendants(root.get("DocID") or "")]
        kept = []
        for doc in docs:
            submitted = parse_dt(doc.get("SubmitDateTime") or "")
            if start and submitted and (submitted - start).days > within_days:
                continue
            kept.append(doc)
        type_counts: dict[str, int] = defaultdict(int)
        for doc in kept:
            type_counts[doc.get("DocTypeCode") or ""] += 1
        cases.append(
            {
                "case_id": root.get("DocID") or "",
                "filing_date": (root.get("SubmitDateTime") or "")[:10],
                "offeror_name": root.get("OfferorName") or root.get("FilerName") or "",
                "target_name": root.get("TargetName") or "",
                "target_sec_code": root.get("TargetSecCode") or "",
                "offeror_edinet_code": root.get("FilerEdinetCode") or "",
                "target_edinet_code": root.get("SubjectEdinetCode") or "",
                "doc_count": len(kept),
                "type_counts": dict(type_counts),
                "has_outcome": any(doc.get("DocTypeCode") in {"260", "270", "280"} for doc in kept),
                "documents": [
                    {
                        "doc_id": doc.get("DocID") or "",
                        "doc_type_code": doc.get("DocTypeCode") or "",
                        "doc_type_name": doc.get("DocTypeName") or "",
                        "submit_date": (doc.get("SubmitDateTime") or "")[:10],
                        "parent_doc_id": doc.get("ParentDocID") or "",
                    }
                    for doc in kept
                ],
            }
        )
    return cases


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


def _slice_days(
    daily: dict[str, int],
    failed: list[str],
    start: date,
    end: date,
) -> tuple[dict[str, int], list[str]]:
    start_key, end_key = start.isoformat(), end.isoformat()
    sliced = {key: count for key, count in daily.items() if start_key <= key <= end_key}
    sliced_failed = [key for key in failed if start_key <= key <= end_key]
    return sliced, sliced_failed


def build_report(
    rows: list[dict],
    *,
    month: str,
    within_days: int,
    fetched_from: date,
    fetched_to: date,
    horizon_end: date,
    as_of: date,
    window_closed: bool,
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
        "as_of": as_of.isoformat(),
        "fetched_from": fetched_from.isoformat(),
        "fetched_to": fetched_to.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "window_closed": window_closed and not failed_days,
        "failed_days": failed_days,
        "daily_tob_counts": daily_tob_counts,
        "tob_document_count": sum(count for count in daily_tob_counts.values() if count > 0),
        "filing_count": len(cases),
        "issuer_filing_count": len(issuer),
        "other_filing_count": len(other),
        "filings_with_outcome": _with_outcome(cases),
        "issuer_filings_with_outcome": _with_outcome(issuer),
        "other_filings_with_outcome": _with_outcome(other),
        "cases": cases,
    }


def build_month_reports(
    rows: list[dict],
    months: list[str],
    *,
    within_days: int,
    today: date,
    failed_days: list[str],
    daily_tob_counts: dict[str, int],
    code_list: EdinetCodeList | None = None,
) -> list[dict]:
    reports: list[dict] = []
    for month in months:
        start, horizon = window_for_month(month, within_days)
        fetched_to = min(horizon, today)
        daily, failed = _slice_days(daily_tob_counts, failed_days, start, fetched_to)
        reports.append(
            build_report(
                rows,
                month=month,
                within_days=within_days,
                fetched_from=start,
                fetched_to=fetched_to,
                horizon_end=horizon,
                as_of=today,
                window_closed=today >= horizon,
                failed_days=failed,
                daily_tob_counts=daily,
                code_list=code_list,
            )
        )
    return reports


def write_reports(reports: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for report in reports:
        path = out_dir / f"{report['month']}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _print_summary(report: dict) -> None:
    closed = "closed" if report["window_closed"] else "open"
    print(
        f"{report['month']}: API {report['fetched_from']}..{report['fetched_to']} "
        f"horizon={report['horizon_end']} window={closed} "
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-month", default="", help="開始月 YYYY-MM。空なら183日の窓が閉じた直近の月")
    parser.add_argument("--to-month", default="", help="終了月 YYYY-MM。空なら開始月と同じ")
    parser.add_argument("--within-days", type=int, default=DEFAULT_WITHIN_DAYS)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--as-of", default="", help="基準日 YYYY-MM-DD。空なら今日")
    parser.add_argument(
        "--edinet-cache",
        default="cache/edinet/EdinetcodeDlInfo.csv",
        help="提出者リストのキャッシュ。名前解決にだけ使う",
    )
    args = parser.parse_args(argv)

    try:
        today = date.fromisoformat(args.as_of) if args.as_of else date.today()
        start_month, end_month = resolve_months(
            args.from_month,
            args.to_month,
            today=today,
            within_days=args.within_days,
        )
        months = iter_months(start_month, end_month)
        fetch_start, fetch_end = fetch_bounds(months, args.within_days, today)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY がありません。", file=sys.stderr)
        return 1

    print(
        f"ID list {start_month}..{end_month} "
        f"API {fetch_start.isoformat()}..{fetch_end.isoformat()} (no saved CSV)",
        flush=True,
    )
    rows, failed, daily = fetch_tob_rows(fetch_start, fetch_end, api_key, sleep_seconds=args.sleep)
    if not rows and failed:
        print("一覧APIから書類を1件も取れませんでした。", file=sys.stderr)
        return 1

    code_list = None
    try:
        code_list = ensure_edinet_code_list(Path(args.edinet_cache))
    except RuntimeError as exc:
        print(f"提出者リストは使えません。名前は提出者名のみにします: {exc}", flush=True)

    reports = build_month_reports(
        rows,
        months,
        within_days=args.within_days,
        today=today,
        failed_days=failed,
        daily_tob_counts=daily,
        code_list=code_list,
    )
    written = write_reports(reports, Path(args.out_dir))
    for report, path in zip(reports, written):
        _print_summary(report)
        print(f"Wrote {path}", flush=True)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
