#!/usr/bin/env python3
"""
EDINET API から TOB（公開買付）関連書類の一覧を取得し、CSV に保存する。

流れ:
  1. 環境変数 EDINET_API_KEY を読む
  2. 期間を決める（開始日指定 / 今年 / 過去1年）
  3. 日付を1日ずつ回す
  4. 書類一覧 API を呼ぶ
  5. docTypeCode 240-320 だけ残す
  6. output/tob_list.csv（書類ごと）を保存する
  7. ParentDocID で案件にまとめ output/tob_cases.csv を保存する
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

API_BASE = "https://api.edinet-fsa.go.jp/api/v2/documents.json"

DOC_TYPE_NAMES = {
    "240": "公開買付届出書",
    "250": "訂正公開買付届出書",
    "260": "公開買付撤回届出書",
    "270": "公開買付報告書",
    "280": "訂正公開買付報告書",
    "290": "意見表明報告書",
    "300": "訂正意見表明報告書",
    "310": "対質問回答報告書",
    "320": "訂正対質問回答報告書",
}

DEFAULT_DOC_TYPES = set(DOC_TYPE_NAMES.keys())

ROLE_HINTS = {
    "240": "買付者側（届出・報告）",
    "250": "買付者側（届出・報告）",
    "260": "買付者側（届出・報告）",
    "270": "買付者側（届出・報告）",
    "280": "買付者側（届出・報告）",
    "290": "対象会社側（意見表明）※賛同/反対は本文確認",
    "300": "対象会社側（意見表明）※賛同/反対は本文確認",
    "310": "対質問回答",
    "320": "対質問回答",
}

OFFEROR_SIDE = {"240", "250", "260", "270", "280"}
OPINION_SIDE = {"290", "300"}
REPORT_SIDE = {"270", "280"}
FILING_SIDE = {"240", "250"}

LIST_FIELDS = [
    "SubmitDateTime",
    "DocTypeCode",
    "DocTypeName",
    "RoleHint",
    "FilerName",
    "FilerSecCode",
    "FilerEdinetCode",
    "SubjectEdinetCode",
    "DocDescription",
    "DocID",
    "PdfFlag",
    "XbrlFlag",
    "ParentDocID",
    "CaseID",
]

CASE_FIELDS = [
    # filled now from list metadata
    "CaseID",
    "OfferorName",
    "OfferorEdinetCode",
    "TargetEdinetCode",
    "FirstFilingDate",
    "LastUpdateDate",
    "Status",
    "HasOpinion",
    "LatestFilingDocID",
    "LatestOpinionDocID",
    "LatestReportDocID",
    "DocCount",
    "DocIDList",
    # reserved for future PDF/XBRL enrichment (leave empty for now)
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "OwnershipRatio",
    "OpinionStance",
    "FinalResultNote",
    "EnrichmentStatus",
    "LastEnrichedDocID",
]


def normalize_doc_type(code: object) -> str | None:
    if code is None:
        return None
    text = str(code).replace("'", "").replace('"', "").strip()
    return text or None


def parse_user_date(value: str) -> date:
    """Accept YYYY/MM/DD or YYYY-MM-DD."""
    text = value.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"日付形式が不正です（YYYY/MM/DD または YYYY-MM-DD）: {value}")


def resolve_range(period: str, from_date: str | None, to_date: str | None) -> tuple[date, date]:
    today = date.today()
    if from_date:
        start = parse_user_date(from_date)
        end = parse_user_date(to_date) if to_date else today
    elif period == "past_year":
        start = today - timedelta(days=365)
        end = today
    else:
        start = date(today.year, 1, 1)
        end = today
    if end < start:
        raise SystemExit(f"終了日が開始日より前です: {start} > {end}")
    return start, end


def fetch_day(day: date, api_key: str, timeout: int = 120) -> dict:
    query = urllib.parse.urlencode(
        {
            "date": day.isoformat(),
            "type": "2",
            "Subscription-Key": api_key,
        }
    )
    url = f"{API_BASE}?{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def row_from_doc(doc: dict) -> dict | None:
    type_code = normalize_doc_type(doc.get("docTypeCode"))
    if not type_code or type_code not in DEFAULT_DOC_TYPES:
        return None
    return {
        "SubmitDateTime": doc.get("submitDateTime") or "",
        "DocTypeCode": type_code,
        "DocTypeName": DOC_TYPE_NAMES.get(type_code, type_code),
        "RoleHint": ROLE_HINTS.get(type_code, ""),
        "FilerName": doc.get("filerName") or "",
        "FilerSecCode": doc.get("secCode") or "",
        "FilerEdinetCode": doc.get("edinetCode") or "",
        "SubjectEdinetCode": doc.get("subjectEdinetCode") or "",
        "DocDescription": doc.get("docDescription") or "",
        "DocID": doc.get("docID") or "",
        "PdfFlag": doc.get("pdfFlag") or "",
        "XbrlFlag": doc.get("xbrlFlag") or "",
        "ParentDocID": doc.get("parentDocID") or "",
        "CaseID": "",
    }


def load_cache(cache_dir: Path, day: date) -> dict | None:
    path = cache_dir / f"{day.isoformat()}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(cache_dir: Path, day: date, payload: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{day.isoformat()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fallback_case_id(row: dict) -> str:
    offeror = row.get("FilerEdinetCode") or ""
    target = row.get("SubjectEdinetCode") or ""
    # Opinion filings swap roles in EDINET metadata; normalize roughly.
    if row.get("DocTypeCode") in OPINION_SIDE:
        offeror, target = target, offeror
    return f"fallback:{offeror}|{target}"


def resolve_case_id(row: dict, by_id: dict[str, dict], memo: dict[str, str]) -> str:
    doc_id = row.get("DocID") or ""
    if not doc_id:
        return fallback_case_id(row)
    if doc_id in memo:
        return memo[doc_id]

    seen: list[str] = []
    current_id = doc_id
    external_parent: str | None = None

    while current_id:
        if current_id in memo:
            root = memo[current_id]
            break
        if current_id in seen:
            root = current_id
            break
        seen.append(current_id)
        current = by_id.get(current_id)
        if current is None:
            # Parent points outside the fetched window.
            external_parent = current_id if current_id != doc_id else None
            root = None
            break
        parent = (current.get("ParentDocID") or "").strip()
        if not parent:
            root = current_id
            break
        if parent not in by_id:
            external_parent = parent
            root = None
            break
        current_id = parent
    else:
        root = doc_id

    if root is None:
        case_id = external_parent or fallback_case_id(row)
    else:
        case_id = root

    for node in seen:
        memo[node] = case_id
    memo[doc_id] = case_id
    return case_id


def assign_case_ids(rows: list[dict]) -> None:
    by_id = {r["DocID"]: r for r in rows if r.get("DocID")}
    memo: dict[str, str] = {}
    for row in rows:
        row["CaseID"] = resolve_case_id(row, by_id, memo)


def latest_doc(docs: list[dict], type_codes: set[str]) -> dict | None:
    matched = [d for d in docs if d.get("DocTypeCode") in type_codes]
    if not matched:
        return None
    return max(matched, key=lambda d: d.get("SubmitDateTime") or "")


def earliest_doc(docs: list[dict], type_codes: set[str]) -> dict | None:
    matched = [d for d in docs if d.get("DocTypeCode") in type_codes]
    if not matched:
        return None
    return min(matched, key=lambda d: d.get("SubmitDateTime") or "")


def case_status(docs: list[dict]) -> str:
    codes = {d.get("DocTypeCode") for d in docs}
    if "260" in codes:
        return "撤回"
    if codes & REPORT_SIDE:
        return "報告書提出"
    if "250" in codes:
        return "訂正あり"
    if "240" in codes:
        return "届出中"
    if codes & OPINION_SIDE:
        return "意見表明のみ"
    return "関連書類"


def pick_offeror_target(docs: list[dict]) -> tuple[str, str, str]:
    """Return OfferorName, OfferorEdinetCode, TargetEdinetCode."""
    offeror_docs = [d for d in docs if d.get("DocTypeCode") in OFFEROR_SIDE]
    preferred = sorted(offeror_docs, key=lambda d: d.get("SubmitDateTime") or "")
    if preferred:
        # Prefer values from the earliest filing-side doc, else any offeror-side.
        filing_first = earliest_doc(docs, FILING_SIDE) or preferred[0]
        return (
            filing_first.get("FilerName") or "",
            filing_first.get("FilerEdinetCode") or "",
            filing_first.get("SubjectEdinetCode") or "",
        )

    opinion = latest_doc(docs, OPINION_SIDE)
    if opinion:
        # On opinion filings, filer is target and subject is often the offeror.
        return (
            "",
            opinion.get("SubjectEdinetCode") or "",
            opinion.get("FilerEdinetCode") or "",
        )
    # last resort
    first = sorted(docs, key=lambda d: d.get("SubmitDateTime") or "")[0]
    return (
        first.get("FilerName") or "",
        first.get("FilerEdinetCode") or "",
        first.get("SubjectEdinetCode") or "",
    )


def build_cases(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        case_id = row.get("CaseID") or fallback_case_id(row)
        groups[case_id].append(row)

    cases: list[dict] = []
    for case_id, docs in groups.items():
        docs_sorted = sorted(docs, key=lambda d: d.get("SubmitDateTime") or "")
        offeror_name, offeror_code, target_code = pick_offeror_target(docs_sorted)

        # If offeror name missing but we have an offeror-side doc later, fill name.
        if not offeror_name:
            for d in docs_sorted:
                if d.get("DocTypeCode") in OFFEROR_SIDE and d.get("FilerName"):
                    offeror_name = d["FilerName"]
                    break

        first_filing = earliest_doc(docs_sorted, {"240"}) or docs_sorted[0]
        last_doc = docs_sorted[-1]
        latest_filing = latest_doc(docs_sorted, FILING_SIDE)
        latest_opinion = latest_doc(docs_sorted, OPINION_SIDE)
        latest_report = latest_doc(docs_sorted, REPORT_SIDE)
        has_opinion = "Yes" if latest_opinion else "No"
        doc_ids = [d.get("DocID") or "" for d in docs_sorted if d.get("DocID")]

        cases.append(
            {
                "CaseID": case_id,
                "OfferorName": offeror_name,
                "OfferorEdinetCode": offeror_code,
                "TargetEdinetCode": target_code,
                "FirstFilingDate": (first_filing.get("SubmitDateTime") or "")[:10],
                "LastUpdateDate": (last_doc.get("SubmitDateTime") or "")[:10],
                "Status": case_status(docs_sorted),
                "HasOpinion": has_opinion,
                "LatestFilingDocID": (latest_filing or {}).get("DocID", ""),
                "LatestOpinionDocID": (latest_opinion or {}).get("DocID", ""),
                "LatestReportDocID": (latest_report or {}).get("DocID", ""),
                "DocCount": str(len(docs_sorted)),
                "DocIDList": ";".join(doc_ids),
                "OfferPrice": "",
                "OfferPeriodStart": "",
                "OfferPeriodEnd": "",
                "OwnershipRatio": "",
                "OpinionStance": "",
                "FinalResultNote": "",
                "EnrichmentStatus": "",
                "LastEnrichedDocID": "",
            }
        )

    cases.sort(key=lambda c: (c.get("FirstFilingDate") or "", c.get("CaseID") or ""))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="EDINET TOB一覧を取得してCSV出力する")
    parser.add_argument(
        "--period",
        choices=["this_year", "past_year"],
        default="this_year",
        help="取得期間（from/to 未指定時）",
    )
    parser.add_argument(
        "--from-date",
        help="開始日 YYYY/MM/DD または YYYY-MM-DD",
    )
    parser.add_argument(
        "--to-date",
        help="終了日 YYYY/MM/DD または YYYY-MM-DD（省略時は今日）",
    )
    parser.add_argument(
        "--out",
        default="output/tob_list.csv",
        help="書類一覧CSVパス",
    )
    parser.add_argument(
        "--cases-out",
        default="output/tob_cases.csv",
        help="案件一覧CSVパス",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache",
        help="日次レスポンスのキャッシュ先",
    )
    parser.add_argument("--sleep", type=float, default=1.2, help="API呼び出し間隔（秒）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print(
            "EDINET_API_KEY がありません。"
            "GitHub Secrets か環境変数に設定してください。",
            file=sys.stderr,
        )
        return 1

    start, end = resolve_range(args.period, args.from_date, args.to_date)
    cache_dir = Path(args.cache_dir)
    out_path = Path(args.out)
    cases_path = Path(args.cases_out)

    days = (end - start).days + 1
    print(f"期間: {start} 〜 {end}（{days} 日）")

    rows: list[dict] = []
    current = start
    index = 0
    while current <= end:
        index += 1
        print(f"[{index}/{days}] {current.isoformat()}", flush=True)
        payload = None if args.no_cache else load_cache(cache_dir, current)
        from_cache = payload is not None
        if payload is None:
            try:
                payload = fetch_day(current, api_key)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                print(f"  警告: HTTP {exc.code} - {body[:200]}", file=sys.stderr)
                current += timedelta(days=1)
                time.sleep(args.sleep)
                continue
            except Exception as exc:  # noqa: BLE001 - 1日失敗しても全体は継続
                print(f"  警告: {exc}", file=sys.stderr)
                current += timedelta(days=1)
                time.sleep(args.sleep)
                continue
            if not args.no_cache:
                save_cache(cache_dir, current, payload)

        for doc in payload.get("results") or []:
            row = row_from_doc(doc)
            if row:
                rows.append(row)

        if not from_cache:
            time.sleep(args.sleep)
        current += timedelta(days=1)

    assign_case_ids(rows)
    rows.sort(key=lambda r: (r["SubmitDateTime"], r["DocTypeCode"], r["FilerName"]))
    write_csv(out_path, rows, LIST_FIELDS)
    print(f"ヒット件数: {len(rows)}")
    print(f"CSV出力: {out_path}")

    cases = build_cases(rows)
    write_csv(cases_path, cases, CASE_FIELDS)
    print(f"案件件数: {len(cases)}")
    print(f"案件CSV出力: {cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
