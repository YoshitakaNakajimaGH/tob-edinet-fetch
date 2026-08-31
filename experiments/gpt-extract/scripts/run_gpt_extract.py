#!/usr/bin/env python3
"""Extract TOB fields from case PDFs via OpenAI API and append to gpt_extract.csv."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.tob_common import read_csv, write_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF_DIR = LAB_ROOT / "pdfs"
DEFAULT_SCHEMA = LAB_ROOT / "schema" / "extract_fields.json"
DEFAULT_OUTPUT = LAB_ROOT / "output" / "gpt_extract.csv"
DEFAULT_CASES = ROOT / "output" / "current" / "tob_cases.csv"

OUTPUT_FIELDS = [
    "CaseID",
    "OfferorName",
    "TargetName",
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "AfterPurchaseRatio",
    "SponsorHint",
    "IsMBO",
    "OpinionStance",
    "FinalResultNote",
    "TargetDelistingNote",
    "TenderOfferAgent",
    "Notes",
    "Model",
    "PdfCount",
    "ExtractedAt",
]

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def pdf_to_text(pdf_path: Path, max_chars: int = 120_000) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf: pip install pypdf") from exc

    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        if not text.strip():
            continue
        chunks.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n".join(chunks)[:max_chars]


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(case_meta: dict, schema: dict, pdf_text: str) -> str:
    field_lines = []
    for field in schema.get("fields", []):
        field_lines.append(f"- {field['name']}: {field['label']} — {field.get('hint', '')}")
    fields_block = "\n".join(field_lines)
    meta = (
        f"CaseID: {case_meta.get('CaseID', '')}\n"
        f"OfferorName: {case_meta.get('OfferorName', '')}\n"
        f"TargetName: {case_meta.get('TargetName', '')}\n"
    )
    return (
        "あなたは日本の公開買付（TOB）書類から数値・固有名詞のみを抽出するアシスタントです。\n"
        "叙事文や前置きは値に含めないでください。\n"
        "不明な項目は空文字 \"\" にしてください。\n\n"
        f"## 案件メタデータ\n{meta}\n"
        f"## 抽出項目\n{fields_block}\n\n"
        "## 書類テキスト\n"
        f"{pdf_text}\n\n"
        "上記テキストから抽出項目だけを JSON オブジェクトで返してください。"
    )


def call_openai(prompt: str, model: str, api_key: str, timeout: int = 300) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Respond with valid JSON only. No markdown fences."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    req = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def load_case_meta(case_id: str, cases_csv: Path) -> dict:
    for row in read_csv(cases_csv):
        if (row.get("CaseID") or "").strip() == case_id:
            return row
    return {"CaseID": case_id}


def upsert_output(path: Path, row: dict) -> None:
    rows = read_csv(path)
    case_id = row.get("CaseID") or ""
    kept = [r for r in rows if (r.get("CaseID") or "") != case_id]
    kept.append(row)
    write_csv(path, kept, OUTPUT_FIELDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="GPT-extract TOB fields from case PDFs")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--cases-csv", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 1

    pdf_dir = args.pdf_dir / args.case_id
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {pdf_dir}. Run fetch_case_pdfs.py first.", file=sys.stderr)
        return 1

    schema = load_schema(args.schema)
    case_meta = load_case_meta(args.case_id, args.cases_csv)

    combined_text_parts: list[str] = []
    for pdf in pdfs:
        combined_text_parts.append(f"=== {pdf.name} ===\n{pdf_to_text(pdf)}")
    combined_text = "\n\n".join(combined_text_parts)

    prompt = build_prompt(case_meta, schema, combined_text)
    try:
        extracted = call_openai(prompt, args.model, api_key)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"OpenAI call failed: {exc}", file=sys.stderr)
        return 1

    row = {key: "" for key in OUTPUT_FIELDS}
    row.update({k: str(v) if v is not None else "" for k, v in extracted.items()})
    row["CaseID"] = args.case_id
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
