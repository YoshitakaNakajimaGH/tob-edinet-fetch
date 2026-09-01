#!/usr/bin/env python3
"""LLM-assisted SponsorHint inference from enriched CSV text."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from edinet.edinet_code_list import EdinetCodeList
from tob.extract_fields import (
    UNLISTED_LABEL,
    PE_CANONICAL_LABELS,
    extract_overview_section,
    extract_pe_sponsor_name,
    is_acceptable_sponsor_name,
    sanitize_sponsor_name,
    strip_html,
)

FILING_SIDE = {"240", "250"}
OFFEROR_SIDE = {"240", "250", "260", "270", "280"}

DEFAULT_SIDECAR_PATH = Path("output/current/sponsor_hint_llm.json")

TEXT_FIELDS = (
    "PurposesRaw",
    "OverviewRaw",
    "CorporationInfoRaw",
    "OfficerHistoryRaw",
    "MajorShareholdersRaw",
)

FINANCING_NOISE_RE = re.compile(
    r"^(?:株式会社)?(?:みずほ|三菱UFJ|三井住友|横浜|神奈川|福井|りそな|住友|日本)?銀行$",
)

SPONSOR_TYPE_ALIASES = {
    "listed_company": "listed_company",
    "listed_parent": "listed_company",
    "pe_fund": "pe_fund",
    "pe": "pe_fund",
    "unlisted_spv": "unlisted_spv",
    "unlisted": "unlisted_spv",
    "offeror_direct": "offeror_direct",
    "direct": "offeror_direct",
    "unknown": "unknown",
}


def normalize_sponsor_type(value: str) -> str:
    key = (value or "").strip().lower()
    return SPONSOR_TYPE_ALIASES.get(key, "unknown")


def _earliest_doc(docs: list[dict], type_codes: set[str]) -> dict | None:
    candidates = [doc for doc in docs if (doc.get("DocTypeCode") or "") in type_codes]
    if not candidates:
        return None
    return min(candidates, key=lambda doc: doc.get("SubmitDateTime") or "")


def collect_case_text_bundle(docs: list[dict], *, max_chars: int = 14_000) -> str:
    """Aggregate filing-side narrative text for LLM input."""
    filing = _earliest_doc(docs, FILING_SIDE) or next(
        (doc for doc in docs if (doc.get("DocTypeCode") or "") in OFFEROR_SIDE),
        docs[0] if docs else None,
    )
    if not filing:
        return ""

    parts: list[str] = []
    for field in TEXT_FIELDS:
        value = (filing.get(field) or "").strip()
        if value:
            parts.append(f"## {field}\n{value}")

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    overview = extract_overview_section(combined)
    if overview and len(combined) > max_chars:
        head = combined[:4000]
        tail_budget = max_chars - len(head) - len(overview) - 32
        if tail_budget > 0:
            return f"{head}\n\n## 本公開買付の概要（抜粋）\n{overview[:tail_budget]}"
    return combined[:max_chars]


def build_sponsor_hint_prompt(
    *,
    case_id: str,
    offeror_name: str,
    target_name: str,
    text_bundle: str,
) -> str:
    return (
        "あなたは日本の公開買付（TOB）書類から、経済的スポンサー（実質的な買収者）を特定するアシスタントです。\n"
        "公開買付者（届出上の買付者）と、実質的に資金提供・意思決定を行う主体を区別してください。\n\n"
        "## 除外（スポンサーにしない）\n"
        "- 融資銀行・メザニン出資者（議決権なしの優先出資のみ）\n"
        "- 公開買付代理人、監査法人、対象会社\n"
        "- 資金調達のための貸付人のみ\n\n"
        "## 優先（スポンサー候補）\n"
        "- 公開買付者の完全親会社（上場親会社を優先）\n"
        "- PE / ファンドの運用主体（Carlyle, KKR, Bain 等）\n"
        "- 上場会社が直接買付する場合は買付者本人\n"
        "- 経営陣のみの MBO SPV は unlisted_spv\n\n"
        "## 案件メタデータ\n"
        f"CaseID: {case_id}\n"
        f"OfferorName: {offeror_name}\n"
        f"TargetName: {target_name}\n\n"
        "## 書類テキスト\n"
        f"{text_bundle}\n\n"
        "次の JSON のみを返してください:\n"
        "{\n"
        '  "sponsor_type": "listed_company | pe_fund | unlisted_spv | offeror_direct | unknown",\n'
        '  "sponsor_name": "正式名称（不明なら空文字）",\n'
        '  "confidence": "high | medium | low",\n'
        '  "reason": "1文の根拠"\n'
        "}"
    )


def _match_pe_label(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    from_catalog = extract_pe_sponsor_name(raw)
    if from_catalog:
        return from_catalog
    cleaned = sanitize_sponsor_name(raw)
    if cleaned in PE_CANONICAL_LABELS:
        return cleaned
    from_catalog = extract_pe_sponsor_name(cleaned)
    if from_catalog:
        return from_catalog
    if is_acceptable_sponsor_name(cleaned):
        return cleaned
    return ""


def _lookup_listed_label(
    name: str,
    *,
    edinet_list: EdinetCodeList | None,
    edinet_code: str = "",
) -> str:
    if edinet_list is None or not name:
        return ""
    label = edinet_list.listing_label(name=name, edinet_code=edinet_code)
    if label and label.isdigit():
        return label
    if label == UNLISTED_LABEL:
        return UNLISTED_LABEL
    return ""


def finalize_llm_sponsor_hint(
    llm_response: dict,
    *,
    offeror_name: str,
    offeror_edinet_code: str = "",
    edinet_list: EdinetCodeList | None = None,
) -> str:
    """Map structured LLM output to SponsorHint (PE name / sec code / 非上場 / blank)."""
    sponsor_type = normalize_sponsor_type(str(llm_response.get("sponsor_type") or ""))
    raw_sponsor_name = str(llm_response.get("sponsor_name") or "")
    sponsor_name = sanitize_sponsor_name(raw_sponsor_name)

    if FINANCING_NOISE_RE.match(sponsor_name):
        return ""

    if sponsor_type == "unlisted_spv":
        return UNLISTED_LABEL

    if sponsor_type == "offeror_direct":
        label = _lookup_listed_label(
            offeror_name,
            edinet_list=edinet_list,
            edinet_code=offeror_edinet_code,
        )
        if label:
            return label
        pe = _match_pe_label(offeror_name)
        return pe or UNLISTED_LABEL

    if sponsor_type == "pe_fund":
        pe = _match_pe_label(raw_sponsor_name)
        return pe

    if sponsor_type == "listed_company":
        if not raw_sponsor_name and not sponsor_name:
            return ""
        label = _lookup_listed_label(raw_sponsor_name or sponsor_name, edinet_list=edinet_list)
        if label and label.isdigit():
            return label
        pe = _match_pe_label(raw_sponsor_name)
        if pe:
            return pe
        if label == UNLISTED_LABEL:
            return UNLISTED_LABEL
        if is_acceptable_sponsor_name(sponsor_name):
            return UNLISTED_LABEL
        return ""

    if sponsor_type == "unknown":
        return ""

    return ""


def load_sponsor_hint_llm_overlay(path: Path = DEFAULT_SIDECAR_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, dict):
        return {}
    return cases


def save_sponsor_hint_llm_overlay(
    cases: dict[str, dict],
    path: Path = DEFAULT_SIDECAR_PATH,
    *,
    model: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": model,
        "cases": cases,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_case_sponsor_hint_with_llm(
    docs: list[dict],
    edinet_list: EdinetCodeList | None = None,
    llm_entry: dict | None = None,
) -> str:
    """Prefer LLM sidecar SponsorHint when present; otherwise rule-based."""
    from tob.tob_common import resolve_case_sponsor_hint

    rule_hint = resolve_case_sponsor_hint(docs, edinet_list)
    if llm_entry:
        llm_hint = (llm_entry.get("SponsorHintLLM") or "").strip()
        if llm_hint:
            return llm_hint
    return rule_hint


def case_rule_hint(docs: list[dict], edinet_list: EdinetCodeList | None = None) -> str:
    from tob.tob_common import resolve_case_sponsor_hint

    return resolve_case_sponsor_hint(docs, edinet_list)


def plain_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", strip_html(text)))
