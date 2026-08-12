#!/usr/bin/env python3
"""
tob_list.csv / tob_cases.csv を読み、各書類の XBRL (type=5) から詳細を抽出して
tob_cases.csv の空列を埋める。

流れ:
  1. tob_cases.csv と tob_list.csv を読む
  2. 案件ごとに書類を提出日時順に処理
  3. documents/{docID}?type=5 で ZIP 取得 → CSV パース
  4. taxonomy_fields.json の要素IDから値を抽出
  5. 書類種別ごとの上書きルールで案件1行を更新
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"

DOC_TYPE_TO_TAXONOMY = {
    "240": "ton",
    "250": "ton",
    "260": "ton",
    "270": "tor",
    "280": "tor",
    "290": "pst",
    "300": "pst",
}

FILING_TYPES = {"240", "250"}
OPINION_TYPES = {"290", "300"}
REPORT_TYPES = {"270", "280"}
WITHDRAW_TYPE = "260"

CASE_FIELDS = [
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
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "OwnershipRatio",
    "OpinionStance",
    "FinalResultNote",
    "EnrichmentStatus",
    "LastEnrichedDocID",
]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_taxonomy(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def parse_xbrl_csv_from_zip(zip_path: Path) -> dict[str, list[str]]:
    """Return element_id -> list of values from XBRL-to-CSV inside ZIP."""
    facts: dict[str, list[str]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            return facts
        raw = zf.read(csv_names[0])
    text = None
    for enc in ("utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return facts

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(reader, None)
    for row in reader:
        if len(row) < 9:
            continue
        elem = row[0].strip().strip('"')
        val = row[8].strip().strip('"')
        if not elem or val in ("", "－", "-", "―"):
            continue
        facts.setdefault(elem, []).append(val)
    return facts


def first_fact(facts: dict[str, list[str]], element_ids: list[str]) -> str:
    for eid in element_ids:
        vals = facts.get(eid)
        if vals:
            for v in vals:
                if v and v not in ("－", "-", "―"):
                    return v
    return ""


def parse_period_dates(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    # 2026年1月7日 ... 2026年2月19日
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
    # Common pattern: 普通株式１株につき、金6,082円
    m = re.search(r"普通株式[^。]*?金\s*([\d,]+)\s*円", text)
    if m:
        return f"{m.group(1)}円/株"
    m = re.search(r"金\s*([\d,]+)\s*円", text)
    if m:
        return f"{m.group(1)}円"
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
    if "成立" in text or "成功" in text:
        return text[:300]
    if "不成立" in text or "失敗" in text:
        return text[:300]
    return text[:300]


def extract_from_doc(
    doc_row: dict,
    taxonomy: dict,
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
) -> dict:
    doc_id = doc_row.get("DocID") or ""
    type_code = doc_row.get("DocTypeCode") or ""
    xbrl_flag = (doc_row.get("XbrlFlag") or "").strip()

    if xbrl_flag == "0":
        return {"skipped": True, "reason": "no_xbrl"}

    zip_path = fetch_document_zip(doc_id, api_key, cache_dir, force)
    time.sleep(sleep)
    if not zip_path:
        return {"skipped": True, "reason": "download_failed"}

    facts = parse_xbrl_csv_from_zip(zip_path)
    if not facts:
        return {"skipped": True, "reason": "empty_facts"}

    tax_key = DOC_TYPE_TO_TAXONOMY.get(type_code)
    if not tax_key:
        return {"skipped": True, "reason": "unsupported_type"}

    fields = taxonomy.get(tax_key, {})
    out: dict[str, str] = {"doc_id": doc_id, "type_code": type_code}

    if tax_key == "ton":
        price_text = first_fact(facts, fields.get("offer_price_text", []))
        period_text = first_fact(facts, fields.get("period_text", []))
        ratio = first_fact(facts, fields.get("ownership_ratio", []))
        start, end = parse_period_dates(period_text)
        out["offer_price"] = summarize_price(price_text)
        out["period_start"] = start
        out["period_end"] = end
        out["ownership_ratio"] = ratio
    elif tax_key == "pst":
        opinion_text = first_fact(facts, fields.get("opinion_text", []))
        out["opinion_stance"] = parse_opinion_stance(opinion_text)
        out["opinion_raw"] = opinion_text[:500]
    elif tax_key == "tor":
        period_text = first_fact(facts, fields.get("period_text", []))
        result_text = first_fact(facts, fields.get("final_result_text", []))
        ratio = first_fact(facts, fields.get("ownership_ratio", []))
        start, end = parse_period_dates(period_text)
        out["period_start"] = start
        out["period_end"] = end
        out["ownership_ratio"] = ratio
        out["final_result"] = summarize_result(result_text)

    out["skipped"] = False
    return out


def apply_extraction(case: dict, extracted: dict) -> None:
    if extracted.get("skipped"):
        return

    type_code = extracted.get("type_code", "")
    doc_id = extracted.get("doc_id", "")

    if type_code == WITHDRAW_TYPE:
        case["Status"] = "撤回"
        case["LastEnrichedDocID"] = doc_id
        return

    if type_code in FILING_TYPES:
        if extracted.get("offer_price"):
            case["OfferPrice"] = extracted["offer_price"]
        if extracted.get("period_start"):
            case["OfferPeriodStart"] = extracted["period_start"]
        if extracted.get("period_end"):
            case["OfferPeriodEnd"] = extracted["period_end"]
        if extracted.get("ownership_ratio"):
            case["OwnershipRatio"] = extracted["ownership_ratio"]

    if type_code in OPINION_TYPES:
        if extracted.get("opinion_stance"):
            case["OpinionStance"] = extracted["opinion_stance"]
            case["HasOpinion"] = "Yes"

    if type_code in REPORT_TYPES:
        if extracted.get("final_result"):
            case["FinalResultNote"] = extracted["final_result"]
        if extracted.get("period_start"):
            case["OfferPeriodStart"] = extracted["period_start"]
        if extracted.get("period_end"):
            case["OfferPeriodEnd"] = extracted["period_end"]
        if extracted.get("ownership_ratio"):
            case["OwnershipRatio"] = extracted["ownership_ratio"]

    case["LastEnrichedDocID"] = doc_id


def compute_enrichment_status(case: dict) -> str:
    if case.get("Status") == "撤回":
        return "done"
    filled = sum(
        1
        for k in (
            "OfferPrice",
            "OfferPeriodStart",
            "OfferPeriodEnd",
            "OwnershipRatio",
            "OpinionStance",
            "FinalResultNote",
        )
        if case.get(k)
    )
    if filled >= 2:
        return "done"
    if filled >= 1:
        return "partial"
    return "failed"


def enrich_cases(
    cases: list[dict],
    list_rows: list[dict],
    taxonomy: dict,
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
    only_pending: bool,
) -> None:
    by_case: dict[str, list[dict]] = {}
    for row in list_rows:
        cid = row.get("CaseID") or ""
        if cid:
            by_case.setdefault(cid, []).append(row)

    for case in cases:
        case_id = case.get("CaseID") or ""
        if not case_id:
            continue
        if only_pending and case.get("EnrichmentStatus") in ("done", "partial"):
            continue

        docs = sorted(by_case.get(case_id, []), key=lambda r: r.get("SubmitDateTime") or "")
        print(f"enrich {case_id} ({len(docs)} docs)", flush=True)

        had_success = False
        for doc in docs:
            extracted = extract_from_doc(doc, taxonomy, api_key, cache_dir, force, sleep)
            if not extracted.get("skipped"):
                had_success = True
                apply_extraction(case, extracted)

        if had_success:
            case["EnrichmentStatus"] = compute_enrichment_status(case)
        elif not case.get("EnrichmentStatus"):
            case["EnrichmentStatus"] = "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description="TOB案件CSVをXBRLから詳細化する")
    parser.add_argument("--cases", default="output/tob_cases.csv")
    parser.add_argument("--list", default="output/tob_list.csv")
    parser.add_argument("--taxonomy", default="taxonomy_fields.json")
    parser.add_argument("--cache-dir", default="cache/docs")
    parser.add_argument("--case-limit", type=int, default=0, help="0=全案件")
    parser.add_argument("--only-pending", action="store_true", help="未enrichのみ")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY が必要です", file=sys.stderr)
        return 1

    cases_path = Path(args.cases)
    list_path = Path(args.list)
    taxonomy_path = Path(args.taxonomy)
    cache_dir = Path(args.cache_dir)

    if not cases_path.exists() or not list_path.exists():
        print("tob_cases.csv / tob_list.csv がありません。先に fetch_tob.py を実行してください。", file=sys.stderr)
        return 1

    taxonomy = load_taxonomy(taxonomy_path)
    cases = read_csv(cases_path)
    list_rows = read_csv(list_path)

    if args.case_limit > 0:
        target_cases = cases[: args.case_limit]
    else:
        target_cases = cases

    enrich_cases(
        target_cases,
        list_rows,
        taxonomy,
        api_key,
        cache_dir,
        args.force_refresh,
        args.sleep,
        args.only_pending,
    )

    write_csv(cases_path, cases, CASE_FIELDS)
    print(f"更新: {cases_path} ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
