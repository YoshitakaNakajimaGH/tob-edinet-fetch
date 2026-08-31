#!/usr/bin/env python3
"""Minimal Gemini API client for TOB PDF extraction."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from llm_common import build_prompt, load_schema, pdf_to_base64, pdf_to_text


def call_gemini_json(
    *,
    prompt: str,
    api_key: str,
    model: str = "gemini-2.0-flash",
    pdf_paths: list[Path] | None = None,
    timeout: int = 300,
) -> dict:
    parts: list[dict] = [{"text": prompt}]
    for pdf in pdf_paths or []:
        parts.insert(
            0,
            {
                "inline_data": {
                    "mime_type": "application/pdf",
                    "data": pdf_to_base64(pdf),
                }
            },
        )

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts_out = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts_out)
    return json.loads(text)


def extract_from_pdfs(
    *,
    case_meta: dict,
    pdf_paths: list[Path],
    api_key: str,
    model: str,
    schema_path: Path,
    source_note: str = "",
    use_pdf_inline: bool = True,
) -> dict:
    schema = load_schema(schema_path)
    if use_pdf_inline and pdf_paths:
        prompt = build_prompt(case_meta, schema, "(PDF attached)", source_note=source_note)
        return call_gemini_json(prompt=prompt, api_key=api_key, model=model, pdf_paths=pdf_paths)

    combined = []
    for pdf in pdf_paths:
        combined.append(f"=== {pdf.name} ===\n{pdf_to_text(pdf)}")
    prompt = build_prompt(case_meta, schema, "\n\n".join(combined), source_note=source_note)
    return call_gemini_json(prompt=prompt, api_key=api_key, model=model)
