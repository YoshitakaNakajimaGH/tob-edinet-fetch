#!/usr/bin/env python3
"""Download EDINET PDFs for one TOB case into experiments/gpt-extract/pdfs/{CaseID}/."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.tob_common import read_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIST = ROOT / "output" / "current" / "tob_list.csv"
DEFAULT_CASES = ROOT / "output" / "current" / "tob_cases.csv"
DEFAULT_PDF_DIR = LAB_ROOT / "pdfs"

API_DOC = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"


def load_case_doc_ids(case_id: str, list_csv: Path, cases_csv: Path) -> list[dict]:
    """Return document rows for CaseID from tob_list, falling back to DocIDList on cases CSV."""
    rows = read_csv(list_csv)
    matched = [r for r in rows if (r.get("CaseID") or "").strip() == case_id]
    if matched:
        return matched

    for case in read_csv(cases_csv):
        if (case.get("CaseID") or "").strip() != case_id:
            continue
        doc_ids = [d.strip() for d in (case.get("DocIDList") or "").split(";") if d.strip()]
        by_id = {r.get("DocID"): r for r in rows}
        return [by_id[d] for d in doc_ids if d in by_id]
    return []


def download_pdf(doc_id: str, api_key: str, dest: Path, timeout: int = 180) -> None:
    query = urllib.parse.urlencode({"type": "1", "Subscription-Key": api_key})
    url = f"{API_DOC.format(doc_id=doc_id)}?{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)


def safe_filename(doc: dict) -> str:
    doc_id = doc.get("DocID") or "unknown"
    type_code = doc.get("DocTypeCode") or "000"
    type_name = (doc.get("DocTypeName") or "doc").replace("/", "-")
    submit = (doc.get("SubmitDateTime") or "")[:10].replace("/", "-")
    return f"{submit}_{type_code}_{type_name}_{doc_id}.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch TOB case PDFs from EDINET")
    parser.add_argument("--case-id", required=True, help="CaseID (e.g. S100M232)")
    parser.add_argument("--list-csv", type=Path, default=DEFAULT_LIST)
    parser.add_argument("--cases-csv", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--force", action="store_true", help="Re-download even if PDF exists")
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY is not set", file=sys.stderr)
        return 1

    docs = load_case_doc_ids(args.case_id, args.list_csv, args.cases_csv)
    if not docs:
        print(f"No documents found for CaseID={args.case_id}", file=sys.stderr)
        return 1

    out_dir = args.pdf_dir / args.case_id
    downloaded = 0
    skipped = 0
    for doc in docs:
        if (doc.get("PdfFlag") or "").strip() not in {"1", "true", "True"}:
            print(f"  skip (no PDF): {doc.get('DocID')} {doc.get('DocTypeName')}")
            continue
        dest = out_dir / safe_filename(doc)
        if dest.exists() and args.skip_existing and not args.force:
            skipped += 1
            continue
        try:
            download_pdf(doc.get("DocID") or "", api_key, dest)
            downloaded += 1
            print(f"  saved: {dest.name}")
        except urllib.error.HTTPError as exc:
            print(f"  HTTP {exc.code} for {doc.get('DocID')}", file=sys.stderr)

    print(f"CaseID={args.case_id}: downloaded={downloaded}, skipped={skipped}, dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
