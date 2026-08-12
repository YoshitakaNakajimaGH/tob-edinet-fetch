#!/usr/bin/env python3
"""
EDINET API から TOB（公開買付）関連書類の一覧を取得し、CSV に保存する。

流れ:
  1. 環境変数 EDINET_API_KEY を読む
  2. 期間を決める（今年 / 過去1年 / 開始日指定）
  3. 日付を1日ずつ回す
  4. 書類一覧 API を呼ぶ
  5. docTypeCode 240-320 だけ残す
  6. output/tob_list.csv に保存する
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

CSV_FIELDS = [
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
]


def normalize_doc_type(code: object) -> str | None:
    if code is None:
        return None
    text = str(code).replace("'", "").replace('"', "").strip()
    return text or None


def resolve_range(period: str, from_date: str | None, to_date: str | None) -> tuple[date, date]:
    today = date.today()
    if from_date:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date) if to_date else today
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


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="EDINET TOB一覧を取得してCSV出力する")
    parser.add_argument(
        "--period",
        choices=["this_year", "past_year"],
        default="this_year",
        help="取得期間（from/to 未指定時）",
    )
    parser.add_argument("--from-date", help="開始日 YYYY-MM-DD")
    parser.add_argument("--to-date", help="終了日 YYYY-MM-DD")
    parser.add_argument(
        "--out",
        default="output/tob_list.csv",
        help="出力CSVパス",
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

    rows.sort(key=lambda r: (r["SubmitDateTime"], r["DocTypeCode"], r["FilerName"]))
    write_csv(out_path, rows)
    print(f"ヒット件数: {len(rows)}")
    print(f"CSV出力: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
