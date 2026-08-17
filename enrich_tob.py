#!/usr/bin/env python3
"""
tob_list.csv の各書類行について XBRL (type=5) から詳細を抽出し、
書類単位の列を埋めたうえで tob_cases.csv を再生成する。

流れ:
  1. tob_list.csv を読む
  2. 未抽出（または指定）の書類を提出日時順に処理
  3. documents/{docID}?type=5 で ZIP 取得 → CSV パース
  4. 書類自身のタクソノミ版を判定し、年度別 mapping で値を抽出
  5. 書類行を更新し、案件CSVは書類正本から派生させる
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from taxonomy import TaxonomyCatalog, resolve_taxonomy_year
from tob_common import (
    ANSWER_SIDE,
    CASE_FIELDS,
    DOC_TYPE_TO_TAXONOMY,
    FILING_SIDE,
    LIST_FIELDS,
    OPINION_SIDE,
    REPORT_SIDE,
    WITHDRAW_SIDE,
    assign_case_ids,
    build_cases,
    normalize_doc_row,
    read_csv,
    write_csv,
)

DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
AMENDMENT_TYPES = {"250", "260", "280", "300", "320"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_document_zip(doc_id: str, api_key: str, cache_dir: Path, force: bool) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{doc_id}.zip"
    if out.exists() and not force:
        return out
    query = urllib.parse.urlencode({"type": "5", "Subscription-Key": api_key})
    url = f"{DOC_API.format(doc_id=doc_id)}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            out.write_bytes(resp.read())
        return out
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code} for {doc_id}", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  download failed {doc_id}: {exc}", file=sys.stderr)
        return None


def parse_xbrl_csv_from_zip(zip_path: Path) -> tuple[dict[str, list[str]], str]:
    """Return (element_id -> values, concatenated zip text for taxonomy detection)."""
    facts: dict[str, list[str]] = {}
    zip_text_parts: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        zip_text_parts.extend(zf.namelist())
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            return facts, "\n".join(zip_text_parts)
        raw = zf.read(csv_names[0])
    text = None
    for enc in ("utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return facts, "\n".join(zip_text_parts)
    zip_text_parts.append(text[:4000])

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader, None)
    for row in reader:
        if len(row) < 9:
            continue
        elem = row[0].strip().strip('"')
        val = row[8].strip().strip('"')
        if not elem or val in ("", "－", "-", "―"):
            continue
        facts.setdefault(elem, []).append(val)
    return facts, "\n".join(zip_text_parts)


def first_fact(facts: dict[str, list[str]], element_ids: list[str]) -> tuple[str, str]:
    for eid in element_ids:
        vals = facts.get(eid)
        if vals:
            for val in vals:
                if val and val not in ("－", "-", "―"):
                    return val, eid
    return "", ""


def parse_period_dates(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    dates = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    iso = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in dates]
    if len(iso) >= 2:
        return iso[0], iso[1]
    if len(iso) == 1:
        return iso[0], ""
    return "", ""


def summarize_price(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text.strip())
    match = re.search(r"普通株式[^。]*?金\s*([\d,]+)\s*円", text)
    if match:
        return f"{match.group(1)}円/株"
    match = re.search(r"金\s*([\d,]+)\s*円", text)
    if match:
        return f"{match.group(1)}円"
    return text[:200]


def parse_opinion_stance(text: str) -> str:
    if not text:
        return ""
    if "反対" in text and "賛同" not in text:
        return "反対"
    if "賛同" in text:
        return "賛同"
    if "意見留保" in text or "留保" in text:
        return "意見留保"
    if "中立" in text:
        return "中立"
    return "要確認"


def summarize_result(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text.strip())
    return text[:300]


def summarize_text(text: str, limit: int = 300) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())[:limit]


def expected_fields_for_type(type_code: str) -> tuple[str, ...]:
    if type_code in FILING_SIDE:
        return ("OfferPrice", "OfferPeriodStart", "OfferPeriodEnd", "OwnershipRatio")
    if type_code in OPINION_SIDE:
        return ("OpinionStance",)
    if type_code in REPORT_SIDE:
        return ("FinalResultNote", "OfferPeriodStart", "OwnershipRatio")
    if type_code in WITHDRAW_SIDE:
        return ("WithdrawalReason",)
    if type_code in ANSWER_SIDE:
        return ("ResponseNote",)
    return ()


def compute_doc_status(row: dict, extracted_ok: bool) -> str:
    if (row.get("XbrlFlag") or "").strip() == "0":
        return "skipped"
    if not extracted_ok:
        return "failed"
    expected = expected_fields_for_type(row.get("DocTypeCode") or "")
    filled = sum(1 for key in expected if row.get(key))
    if expected and filled == 0:
        return "partial"
    if filled >= 1:
        return "done"
    return "partial"


def apply_facts_to_row(row: dict, facts: dict[str, list[str]], mapping: dict) -> None:
    type_code = row.get("DocTypeCode") or ""
    tax_key = DOC_TYPE_TO_TAXONOMY.get(type_code)
    fields = mapping.get(tax_key, {}) if tax_key else {}

    if type_code in FILING_SIDE or tax_key == "ton":
        price_text, price_eid = first_fact(facts, fields.get("offer_price_text", []))
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        ratio, ratio_eid = first_fact(facts, fields.get("ownership_ratio", []))
        start, end = parse_period_dates(period_text)
        if price_text:
            row["OfferPriceRaw"] = price_text[:1000]
            row["OfferPrice"] = summarize_price(price_text)
            row["OfferPriceElement"] = price_eid
        if period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if ratio:
            row["OwnershipRatio"] = ratio
            row["OwnershipRatioElement"] = ratio_eid

    if type_code in OPINION_SIDE or tax_key == "pst":
        opinion_text, opinion_eid = first_fact(facts, fields.get("opinion_text", []))
        if opinion_text:
            row["OpinionRaw"] = opinion_text[:1000]
            row["OpinionStance"] = parse_opinion_stance(opinion_text)
            row["OpinionElement"] = opinion_eid

    if type_code in REPORT_SIDE or tax_key == "tor":
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        result_text, result_eid = first_fact(facts, fields.get("final_result_text", []))
        ratio, ratio_eid = first_fact(facts, fields.get("ownership_ratio", []))
        start, end = parse_period_dates(period_text)
        if period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if ratio:
            row["OwnershipRatio"] = ratio
            row["OwnershipRatioElement"] = ratio_eid
        if result_text:
            row["FinalResultRaw"] = result_text[:1000]
            row["FinalResultNote"] = summarize_result(result_text)
            row["FinalResultElement"] = result_eid

    if type_code in WITHDRAW_SIDE or tax_key == "wto":
        reason_text, reason_eid = first_fact(facts, fields.get("withdrawal_reason_text", []))
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        if reason_text:
            row["WithdrawalReasonRaw"] = reason_text[:1000]
            row["WithdrawalReason"] = summarize_text(reason_text)
            row["WithdrawalReasonElement"] = reason_eid
        if period_text:
            start, end = parse_period_dates(period_text)
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid

    if type_code in ANSWER_SIDE or tax_key == "toa":
        response_text, response_eid = first_fact(facts, fields.get("response_text", []))
        if response_text:
            row["ResponseRaw"] = response_text[:1000]
            row["ResponseNote"] = summarize_text(response_text)
            row["ResponseElement"] = response_eid


def parent_taxonomy_year(row: dict, by_id: dict[str, dict]) -> str:
    parent_id = (row.get("ParentDocID") or "").strip()
    parent = by_id.get(parent_id) if parent_id else None
    if parent:
        return (parent.get("TaxonomyYear") or "").strip()
    return ""


def enrich_document(
    row: dict,
    catalog: TaxonomyCatalog,
    by_id: dict[str, dict],
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
) -> None:
    doc_id = row.get("DocID") or ""
    type_code = row.get("DocTypeCode") or ""
    xbrl_flag = (row.get("XbrlFlag") or "").strip()
    row["ExtractedAt"] = utc_now_iso()
    row["ExtractionError"] = ""

    if xbrl_flag == "0":
        row["ExtractionStatus"] = "skipped"
        row["ExtractionError"] = "no_xbrl"
        return

    zip_path = fetch_document_zip(doc_id, api_key, cache_dir, force)
    time.sleep(sleep)
    if not zip_path:
        row["ExtractionStatus"] = "failed"
        row["ExtractionError"] = "download_failed"
        return

    facts, zip_text = parse_xbrl_csv_from_zip(zip_path)
    if not facts:
        row["ExtractionStatus"] = "failed"
        row["ExtractionError"] = "empty_facts"
        return

    year, tax_date, source = resolve_taxonomy_year(
        catalog,
        submit_datetime=row.get("SubmitDateTime") or "",
        parent_year=parent_taxonomy_year(row, by_id),
        facts=facts,
        zip_text=zip_text,
        is_amendment=type_code in AMENDMENT_TYPES,
    )
    mapping = catalog.mapping_for_year(year)
    row["TaxonomyYear"] = year
    row["TaxonomyDate"] = tax_date or str(mapping.get("taxonomy_date") or "")
    row["TaxonomySource"] = source
    apply_facts_to_row(row, facts, mapping)
    row["ExtractionStatus"] = compute_doc_status(row, extracted_ok=True)


def pending_status(status: str) -> bool:
    return status not in {"done", "partial", "skipped"}


def enrich_documents(
    rows: list[dict],
    catalog: TaxonomyCatalog,
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
    only_pending: bool,
    doc_limit: int,
) -> int:
    by_id = {r.get("DocID") or "": r for r in rows if r.get("DocID")}
    processed = 0
    for row in rows:
        if only_pending and not pending_status(row.get("ExtractionStatus") or ""):
            continue
        if doc_limit > 0 and processed >= doc_limit:
            break
        doc_id = row.get("DocID") or ""
        print(f"enrich {doc_id} type={row.get('DocTypeCode')}", flush=True)
        enrich_document(row, catalog, by_id, api_key, cache_dir, force, sleep)
        processed += 1
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="TOB書類CSVをXBRLから詳細化する")
    parser.add_argument("--list", default="output/tob_list.csv")
    parser.add_argument("--cases", default="output/tob_cases.csv")
    parser.add_argument("--taxonomy-dir", default="taxonomy")
    parser.add_argument("--cache-dir", default="cache/docs")
    parser.add_argument("--doc-limit", type=int, default=0, help="0=全書類")
    parser.add_argument("--only-pending", action="store_true", help="未抽出の書類のみ")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY が必要です", file=sys.stderr)
        return 1

    list_path = Path(args.list)
    cases_path = Path(args.cases)
    if not list_path.exists():
        print("tob_list.csv がありません。先に fetch_tob.py を実行してください。", file=sys.stderr)
        return 1

    catalog = TaxonomyCatalog(Path(args.taxonomy_dir))
    rows = [normalize_doc_row(r) for r in read_csv(list_path)]
    rows.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("DocID") or ""))
    processed = enrich_documents(
        rows,
        catalog,
        api_key,
        Path(args.cache_dir),
        args.force_refresh,
        args.sleep,
        args.only_pending,
        args.doc_limit,
    )
    assign_case_ids(rows)
    write_csv(list_path, rows, LIST_FIELDS)
    cases = build_cases(rows)
    write_csv(cases_path, cases, CASE_FIELDS)
    print(f"処理書類: {processed}")
    print(f"更新: {list_path} ({len(rows)} docs)")
    print(f"案件再生成: {cases_path} ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
