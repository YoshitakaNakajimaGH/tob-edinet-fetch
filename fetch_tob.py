#!/usr/bin/env python3
"""
EDINET API から TOB（公開買付）関連書類の一覧を取得し、CSV に保存する。

流れ:
  1. 環境変数 EDINET_API_KEY を読む
  2. 期間を決める（開始年〜終了年 / 直近N日 / 日付指定）
  3. 日付を1日ずつ回す
  4. 書類一覧 API を呼ぶ
  5. docTypeCode 240-320 だけ残す
  6. 既存の output/tob_list.csv に DocID で upsert する（抽出列は消さない）
  7. ParentDocID で案件にまとめ output/tob_cases.csv を再生成する
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from tob_common import (
    CASE_FIELDS,
    DEFAULT_DOC_TYPES,
    DEFAULT_RECENT_DAYS,
    DOC_TYPE_NAMES,
    LIST_FIELDS,
    ROLE_HINTS,
    assign_case_ids,
    build_cases,
    merge_document_rows,
    normalize_doc_type,
    read_csv,
    resolve_range,
    write_csv,
)

API_BASE = "https://api.edinet-fsa.go.jp/api/v2/documents.json"


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


def main() -> int:
    parser = argparse.ArgumentParser(description="EDINET TOB一覧を取得してCSV出力する")
    parser.add_argument("--from-year", help="開始年 YYYY")
    parser.add_argument("--to-year", help="終了年 YYYY（省略時は今年。今年なら実行日まで）")
    parser.add_argument(
        "--recent-days",
        type=int,
        help=f"直近N日を再取得して既存CSVへ upsert（定期更新向け、既定 {DEFAULT_RECENT_DAYS}）",
    )
    parser.add_argument("--from-date", help="開始日 YYYY/MM/DD（上級者向け）")
    parser.add_argument("--to-date", help="終了日 YYYY/MM/DD（上級者向け）")
    parser.add_argument("--out", default="output/tob_list.csv", help="書類一覧CSVパス")
    parser.add_argument("--cases-out", default="output/tob_cases.csv", help="案件一覧CSVパス")
    parser.add_argument("--cache-dir", default="cache", help="日次レスポンスのキャッシュ先")
    parser.add_argument("--sleep", type=float, default=1.2, help="API呼び出し間隔（秒）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="既存CSVとマージせず、この実行で取れた書類だけで上書きする",
    )
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print(
            "EDINET_API_KEY がありません。"
            "GitHub Secrets か環境変数に設定してください。",
            file=sys.stderr,
        )
        return 1

    start, end, mode = resolve_range(
        from_year=args.from_year,
        to_year=args.to_year,
        from_date=args.from_date,
        to_date=args.to_date,
        recent_days=args.recent_days,
    )
    cache_dir = Path(args.cache_dir)
    out_path = Path(args.out)
    cases_path = Path(args.cases_out)

    days = (end - start).days + 1
    print(f"期間: {start} 〜 {end}（{days} 日, mode={mode}）")

    incoming: list[dict] = []
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
                incoming.append(row)

        if not from_cache:
            time.sleep(args.sleep)
        current += timedelta(days=1)

    print(f"今回ヒット: {len(incoming)}")
    if args.replace:
        rows = incoming
        added, updated = len(incoming), 0
    else:
        existing = read_csv(out_path)
        rows, added, updated = merge_document_rows(existing, incoming)
        print(f"既存: {len(existing)} / 追加: {added} / メタデータ更新: {updated}")

    assign_case_ids(rows)
    rows.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("FilerName") or ""))
    write_csv(out_path, rows, LIST_FIELDS)
    print(f"書類件数: {len(rows)}")
    print(f"CSV出力: {out_path}")

    cases = build_cases(rows)
    write_csv(cases_path, cases, CASE_FIELDS)
    print(f"案件件数: {len(cases)}")
    print(f"案件CSV出力: {cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
