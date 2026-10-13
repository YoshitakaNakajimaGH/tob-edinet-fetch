#!/usr/bin/env python3
"""Download one EDINET PDF by DocID or viewer URL."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from llm_common import parse_edinet_doc_id
from tob.tob_common import read_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIST = ROOT / "output" / "current" / "tob_list.csv"
DEFAULT_PDF_DIR = LAB_ROOT / "pdfs"
API_DOC = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"


def download_pdf(doc_id: str, api_key: str, dest: Path, timeout: int = 180) -> None:
    query = urllib.parse.urlencode({"type": "1", "Subscription-Key": api_key})
    url = f"{API_DOC.format(doc_id=doc_id)}?{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    if not payload.startswith(b"%PDF"):
        raise RuntimeError(f"{doc_id}: response is not a PDF ({len(payload)} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)


def lookup_doc_row(doc_id: str, list_csv: Path) -> dict:
    for row in read_csv(list_csv):
        if (row.get("DocID") or "").strip() == doc_id:
            return row
    return {"DocID": doc_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one EDINET PDF")
    parser.add_argument("--doc-id", help="DocID such as S100M232")
    parser.add_argument("--url", help="EDINET viewer URL")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_PDF_DIR / "by-doc")
    args = parser.parse_args()

    doc_id = parse_edinet_doc_id(args.doc_id or args.url or "")
    if not doc_id:
        parser.error("Provide --doc-id or --url")

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY is not set", file=sys.stderr)
        return 1

    row = lookup_doc_row(doc_id, DEFAULT_LIST)
    type_code = row.get("DocTypeCode") or "000"
    type_name = (row.get("DocTypeName") or "doc").replace("/", "-")
    submit = (row.get("SubmitDateTime") or "")[:10].replace("/", "-")
    dest = args.out_dir / f"{submit}_{type_code}_{type_name}_{doc_id}.pdf"
    download_pdf(doc_id, api_key, dest)
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
