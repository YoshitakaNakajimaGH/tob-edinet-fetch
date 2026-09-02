#!/usr/bin/env python3
"""Shared helpers for GPT / Gemini extraction experiments."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from tob.tob_common import parse_edinet_doc_id, read_csv, write_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = LAB_ROOT / "schema" / "extract_fields.json"
DEFAULT_OUTPUT = LAB_ROOT / "output" / "gpt_extract.csv"
DEFAULT_CASES = Path(__file__).resolve().parents[3] / "output" / "current" / "tob_cases.csv"

OUTPUT_FIELDS = [
    "CaseID",
    "SourceDocID",
    "SourceMode",
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


def load_schema(path: Path = DEFAULT_SCHEMA) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(case_meta: dict, schema: dict, pdf_text: str, *, source_note: str = "") -> str:
    field_lines = []
    for field in schema.get("fields", []):
        field_lines.append(f"- {field['name']}: {field['label']} — {field.get('hint', '')}")
    fields_block = "\n".join(field_lines)
    meta = (
        f"CaseID: {case_meta.get('CaseID', '')}\n"
        f"OfferorName: {case_meta.get('OfferorName', '')}\n"
        f"TargetName: {case_meta.get('TargetName', '')}\n"
    )
    source = f"## 取得元\n{source_note}\n\n" if source_note else ""
    return (
        "あなたは日本の公開買付（TOB）書類から数値・固有名詞のみを抽出するアシスタントです。\n"
        "叙事文や前置きは値に含めないでください。\n"
        "不明な項目は空文字 \"\" にしてください。\n\n"
        f"{source}"
        f"## 案件メタデータ\n{meta}\n"
        f"## 抽出項目\n{fields_block}\n\n"
        "## 書類テキスト\n"
        f"{pdf_text}\n\n"
        "上記テキストから抽出項目だけを JSON オブジェクトで返してください。"
    )


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


def pdf_to_base64(pdf_path: Path) -> str:
    import base64

    return base64.b64encode(pdf_path.read_bytes()).decode("ascii")


def load_case_meta(case_id: str, cases_csv: Path = DEFAULT_CASES) -> dict:
    for row in read_csv(cases_csv):
        if (row.get("CaseID") or "").strip() == case_id:
            return row
    return {"CaseID": case_id}


def upsert_output(path: Path, row: dict) -> None:
    rows = read_csv(path)
    key = ((row.get("CaseID") or ""), (row.get("SourceMode") or ""), (row.get("SourceDocID") or ""))
    kept = [
        r
        for r in rows
        if (
            (r.get("CaseID") or ""),
            (r.get("SourceMode") or ""),
            (r.get("SourceDocID") or ""),
        )
        != key
    ]
    kept.append(row)
    write_csv(path, kept, OUTPUT_FIELDS)


def resolve_gemini_api_key() -> str:
    import os

    for name in ("GEMINI_API_KEY", "GEMINIAPIKEY", "GOOGLE_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


# Hints only — resolve_gemini_model() picks from the live ListModels API first.
DEFAULT_GEMINI_MODEL = ""
GEMINI_MODEL_PREFERENCES = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
# Backward-compatible alias for tests / callers
GEMINI_MODEL_FALLBACKS = GEMINI_MODEL_PREFERENCES


_MODEL_LIST_CACHE: dict[str, list[str]] = {}


def list_gemini_models(api_key: str) -> list[str]:
    """Return model IDs that support generateContent for this API key."""
    cached = _MODEL_LIST_CACHE.get(api_key)
    if cached is not None:
        return cached
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models: list[str] = []
    for item in payload.get("models") or []:
        name = str(item.get("name") or "")
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" in methods:
            models.append(name.removeprefix("models/"))
    sorted_models = sorted(models)
    _MODEL_LIST_CACHE[api_key] = sorted_models
    return sorted_models


def _model_score(name: str) -> tuple[int, int, int, int, int, str]:
    """Higher is better: flash > non-flash, stable > preview, newer version."""
    lower = name.lower()
    nums = [int(part) for part in re.findall(r"\d+", name)]
    major = nums[0] if nums else 0
    minor = nums[1] if len(nums) > 1 else 0
    patch = nums[2] if len(nums) > 2 else 0
    is_flash = 1 if "flash" in lower else 0
    is_stable = 0 if ("preview" in lower or "exp" in lower) else 1
    return (is_flash, is_stable, major, minor, patch, name)


def resolve_gemini_model(api_key: str, preferred: str = "") -> str:
    """Pick the best generateContent model available for this API key."""
    available = list_gemini_models(api_key)
    if not available:
        raise RuntimeError(
            "No Gemini generateContent models available for this API key. "
            "Check GEMINI_API_KEY and Google AI Studio project access."
        )
    if preferred and preferred in available:
        return preferred
    for candidate in GEMINI_MODEL_PREFERENCES:
        if candidate in available:
            return candidate
    return max(available, key=_model_score)
