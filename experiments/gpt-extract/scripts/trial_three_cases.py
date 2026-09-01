#!/usr/bin/env python3
"""Trial Gemini extraction on 3 tob_cases.csv rows (URL path vs CaseID path)."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fetch_doc_pdf import download_pdf, lookup_doc_row
from gemini_client import extract_from_pdfs
from llm_common import (
    DEFAULT_CASES,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OUTPUT,
    OUTPUT_FIELDS,
    load_case_meta,
    parse_edinet_doc_id,
    resolve_gemini_api_key,
    upsert_output,
)
from tob.tob_common import read_csv, write_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIST = ROOT / "output" / "current" / "tob_list.csv"
PDF_ROOT = LAB_ROOT / "pdfs" / "trial"


def pick_cases(cases_csv: Path, limit: int) -> list[dict]:
    rows = [r for r in read_csv(cases_csv) if (r.get("LatestFilingUrl") or "").strip()]
    return rows[:limit]


def case_doc_rows(case_id: str) -> list[dict]:
    rows = [r for r in read_csv(DEFAULT_LIST) if (r.get("CaseID") or "").strip() == case_id]
    if rows:
        return rows
    case = load_case_meta(case_id, DEFAULT_CASES)
    doc_ids = [d.strip() for d in (case.get("DocIDList") or "").split(";") if d.strip()]
    by_id = {r.get("DocID"): r for r in read_csv(DEFAULT_LIST)}
    return [by_id[d] for d in doc_ids if d in by_id]


def safe_pdf_name(doc: dict) -> str:
    doc_id = doc.get("DocID") or "unknown"
    type_code = doc.get("DocTypeCode") or "000"
    type_name = (doc.get("DocTypeName") or "doc").replace("/", "-")
    submit = (doc.get("SubmitDateTime") or "")[:10].replace("/", "-")
    return f"{submit}_{type_code}_{type_name}_{doc_id}.pdf"


def trial_from_url(case: dict, edinet_key: str, gemini_key: str, model: str, dry_run: bool) -> dict:
    case_id = case.get("CaseID") or ""
    url = case.get("LatestFilingUrl") or ""
    doc_id = parse_edinet_doc_id(url)
    result = {
        "CaseID": case_id,
        "SourceMode": "edinet_url",
        "SourceDocID": doc_id,
        "LatestFilingUrl": url,
        "status": "pending",
        "detail": "",
    }
    if not doc_id:
        result["status"] = "failed"
        result["detail"] = "Could not parse DocID from LatestFilingUrl"
        return result

    pdf_dir = PDF_ROOT / case_id / "from_url"
    pdf_path = pdf_dir / safe_pdf_name(lookup_doc_row(doc_id, DEFAULT_LIST))
    result["pdf_path"] = str(pdf_path)

    if dry_run:
        result["status"] = "dry_run"
        result["detail"] = "Would download PDF via EDINET API and send to Gemini"
        return result

    try:
        download_pdf(doc_id, edinet_key, pdf_path)
        extracted = extract_from_pdfs(
            case_meta=case,
            pdf_paths=[pdf_path],
            api_key=gemini_key,
            model=model,
            schema_path=LAB_ROOT / "schema" / "extract_fields.json",
            source_note=f"LatestFilingUrl={url}",
        )
        result["status"] = "ok"
        result["extracted"] = extracted
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError) as exc:
        result["status"] = "failed"
        result["detail"] = str(exc)
    return result


def trial_from_case_id(case: dict, edinet_key: str, gemini_key: str, model: str, dry_run: bool) -> dict:
    case_id = case.get("CaseID") or ""
    docs = case_doc_rows(case_id)
    pdf_docs = [d for d in docs if (d.get("PdfFlag") or "").strip() in {"1", "true", "True"}]
    result = {
        "CaseID": case_id,
        "SourceMode": "case_id",
        "SourceDocID": ";".join(d.get("DocID") or "" for d in pdf_docs),
        "doc_count": len(pdf_docs),
        "status": "pending",
        "detail": "",
    }

    if not pdf_docs:
        result["status"] = "failed"
        result["detail"] = "No PDF-flagged documents for CaseID"
        return result

    pdf_dir = PDF_ROOT / case_id / "from_case"
    pdf_paths = [pdf_dir / safe_pdf_name(doc) for doc in pdf_docs]
    result["pdf_paths"] = [str(p) for p in pdf_paths]

    if dry_run:
        result["status"] = "dry_run"
        result["detail"] = f"Would download {len(pdf_docs)} PDFs and send to Gemini"
        return result

    try:
        for doc, path in zip(pdf_docs, pdf_paths, strict=True):
            download_pdf(doc.get("DocID") or "", edinet_key, path)
        extracted = extract_from_pdfs(
            case_meta=case,
            pdf_paths=pdf_paths,
            api_key=gemini_key,
            model=model,
            schema_path=LAB_ROOT / "schema" / "extract_fields.json",
            source_note=f"CaseID={case_id}; docs={result['SourceDocID']}",
        )
        result["status"] = "ok"
        result["extracted"] = extracted
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError) as exc:
        result["status"] = "failed"
        result["detail"] = str(exc)
    return result


def save_extract_row(case: dict, mode: str, doc_id: str, extracted: dict, model: str, pdf_count: int) -> None:
    row = {key: "" for key in OUTPUT_FIELDS}
    row.update({k: str(v) if v is not None else "" for k, v in extracted.items()})
    row["CaseID"] = case.get("CaseID") or ""
    row["SourceMode"] = mode
    row["SourceDocID"] = doc_id
    row["OfferorName"] = case.get("OfferorName") or row.get("OfferorName") or ""
    row["TargetName"] = case.get("TargetName") or row.get("TargetName") or ""
    row["Model"] = model
    row["PdfCount"] = str(pdf_count)
    row["ExtractedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upsert_output(DEFAULT_OUTPUT, row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trial Gemini on 3 cases")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    parser.add_argument("--dry-run", action="store_true", help="Analyze paths without API calls")
    parser.add_argument("--mode", choices=("url", "case", "both"), default="both")
    args = parser.parse_args()

    edinet_key = os.environ.get("EDINET_API_KEY", "").strip()
    gemini_key = resolve_gemini_api_key()
    if not args.dry_run and (not edinet_key or not gemini_key):
        missing = []
        if not edinet_key:
            missing.append("EDINET_API_KEY")
        if not gemini_key:
            missing.append("GEMINI_API_KEY")
        print(f"Missing: {', '.join(missing)}", file=sys.stderr)
        print("Use --dry-run to inspect URL/CaseID resolution without keys.", file=sys.stderr)
        return 1

    cases = pick_cases(DEFAULT_CASES, args.limit)
    if not cases:
        print("No cases with LatestFilingUrl found", file=sys.stderr)
        return 1

    report_rows = []
    for case in cases:
        print(f"\n=== {case.get('CaseID')} {case.get('OfferorName','')[:40]} ===")
        if args.mode in {"url", "both"}:
            url_result = trial_from_url(case, edinet_key, gemini_key, args.model, args.dry_run)
            print(f"  [url]  status={url_result['status']} doc={url_result.get('SourceDocID')} detail={url_result.get('detail')}")
            report_rows.append(url_result)
            if url_result.get("status") == "ok":
                save_extract_row(
                    case,
                    "edinet_url",
                    url_result.get("SourceDocID") or "",
                    url_result["extracted"],
                    args.model,
                    1,
                )
        if args.mode in {"case", "both"}:
            case_result = trial_from_case_id(case, edinet_key, gemini_key, args.model, args.dry_run)
            print(
                f"  [case] status={case_result['status']} docs={case_result.get('doc_count')} detail={case_result.get('detail')}"
            )
            report_rows.append(case_result)
            if case_result.get("status") == "ok":
                save_extract_row(
                    case,
                    "case_id",
                    case_result.get("SourceDocID") or "",
                    case_result["extracted"],
                    args.model,
                    int(case_result.get("doc_count") or 0),
                )

    report_path = LAB_ROOT / "output" / "trial_report.json"
    import json

    report_path.write_text(json.dumps(report_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote report: {report_path}")
    if any(r.get("status") == "ok" for r in report_rows):
        print(f"Updated: {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
