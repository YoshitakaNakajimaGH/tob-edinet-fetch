#!/usr/bin/env python3
"""Extract TOB fields from case PDFs via Gemini API."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gemini_client import extract_from_pdfs
from llm_common import (
    DEFAULT_CASES,
    DEFAULT_OUTPUT,
    DEFAULT_SCHEMA,
    OUTPUT_FIELDS,
    load_case_meta,
    resolve_gemini_api_key,
    upsert_output,
)

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF_DIR = LAB_ROOT / "pdfs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini-extract TOB fields from case PDFs")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--cases-csv", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))
    args = parser.parse_args()

    api_key = resolve_gemini_api_key()
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set", file=sys.stderr)
        return 1

    pdf_dir = args.pdf_dir / args.case_id
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {pdf_dir}. Run fetch_case_pdfs.py first.", file=sys.stderr)
        return 1

    case_meta = load_case_meta(args.case_id, args.cases_csv)
    extracted = extract_from_pdfs(
        case_meta=case_meta,
        pdf_paths=pdfs,
        api_key=api_key,
        model=args.model,
        schema_path=args.schema,
        source_note=f"CaseID={args.case_id}",
    )

    row = {key: "" for key in OUTPUT_FIELDS}
    row.update({k: str(v) if v is not None else "" for k, v in extracted.items()})
    row["CaseID"] = args.case_id
    row["SourceMode"] = "case_id"
    row["SourceDocID"] = ";".join(p.stem.split("_")[-1] for p in pdfs)
    row["OfferorName"] = case_meta.get("OfferorName") or row.get("OfferorName") or ""
    row["TargetName"] = case_meta.get("TargetName") or row.get("TargetName") or ""
    row["Model"] = args.model
    row["PdfCount"] = str(len(pdfs))
    row["ExtractedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    upsert_output(args.output, row)
    print(f"Wrote {args.output} for CaseID={args.case_id} (model={args.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
