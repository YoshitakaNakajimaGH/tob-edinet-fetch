#!/usr/bin/env python3
"""Minimal Gemini API client for TOB PDF extraction."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from llm_common import (
    build_prompt,
    load_schema,
    list_gemini_models,
    pdf_to_base64,
    pdf_to_text,
    resolve_gemini_model,
)


def _gemini_generate_url(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _models_to_try(model: str, api_key: str) -> list[str]:
    """Build an ordered model list: explicit choice, resolved model, then API flash models."""
    ordered: list[str] = []
    for candidate in (model, resolve_gemini_model(api_key, preferred=model)):
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    for candidate in list_gemini_models(api_key):
        if "flash" in candidate.lower() and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _parse_json_response(payload: dict, *, model: str) -> dict:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates ({model}): {payload}")
    parts_out = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts_out)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned non-JSON text ({model}): {text[:300]}"
        ) from exc


def call_gemini_json(
    *,
    prompt: str,
    api_key: str,
    model: str = "",
    pdf_paths: list[Path] | None = None,
    timeout: int = 300,
    max_retries: int = 3,
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
    payload_bytes = json.dumps(body).encode("utf-8")
    errors: list[str] = []
    resolved = model or resolve_gemini_model(api_key)

    for candidate in _models_to_try(resolved, api_key):
        for attempt in range(max_retries):
            url = f"{_gemini_generate_url(candidate)}?key={api_key}"
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                errors.append(f"{candidate}: HTTP {exc.code} {detail}")
                if exc.code in {404, 400}:
                    break
                if exc.code == 429 and attempt + 1 < max_retries:
                    time.sleep(20 * (attempt + 1))
                    continue
                if exc.code == 429:
                    break
                break
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"Gemini API network error for model {candidate}: {exc}"
                ) from exc
            else:
                return _parse_json_response(payload, model=candidate)

    tried = ", ".join(_models_to_try(resolved, api_key))
    joined = "; ".join(errors)
    available = ", ".join(list_gemini_models(api_key)[:12])
    raise RuntimeError(
        "Gemini API call failed for all candidate models. "
        f"Tried: {tried}. Errors: {joined}. "
        f"Available (sample): {available}"
    )


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
