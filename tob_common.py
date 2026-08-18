#!/usr/bin/env python3
"""TOB一覧・案件CSVで共有する定数とヘルパー。"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from extract_fields import (
    clean_extracted_name,
    detect_mbo,
    extract_sponsor_from_purposes,
    extract_tender_offer_agent,
    format_pct,
    format_sec_code,
    judge_target_delisting,
    judge_tob_result,
    normalize_name,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_valuation_ranges,
    summarize_price,
)
from edinet_code_list import EdinetCodeList, ensure_edinet_code_list

DOC_TYPE_NAMES = {
    "240": "公開買付届出書",
    "250": "訂正公開買付届出書",
    "260": "公開買付撤回届出書",
    "270": "公開買付報告書",
    "280": "訂正公開買付報告書",
    "290": "意見表明報告書",
    "300": "訂正意見表明報告書",
    "310": "対質問回答報告書",
    "320": "訂正対質問回答報告書",
}

DEFAULT_DOC_TYPES = set(DOC_TYPE_NAMES.keys())

ROLE_HINTS = {
    "240": "買付者側（届出・報告）",
    "250": "買付者側（届出・報告）",
    "260": "買付者側（届出・報告）",
    "270": "買付者側（届出・報告）",
    "280": "買付者側（届出・報告）",
    "290": "対象会社側（意見表明）※賛同/反対は本文確認",
    "300": "対象会社側（意見表明）※賛同/反対は本文確認",
    "310": "対質問回答",
    "320": "対質問回答",
}

OFFEROR_SIDE = {"240", "250", "260", "270", "280"}
OPINION_SIDE = {"290", "300"}
REPORT_SIDE = {"270", "280"}
FILING_SIDE = {"240", "250"}
WITHDRAW_SIDE = {"260"}
ANSWER_SIDE = {"310", "320"}

DOC_TYPE_TO_TAXONOMY = {
    "240": "ton",
    "250": "ton",
    "260": "wto",
    "270": "tor",
    "280": "tor",
    "290": "pst",
    "300": "pst",
    "310": "toa",
    "320": "toa",
}

DEFAULT_RECENT_DAYS = 35

# API metadata only. Fetch upsert overwrites these, and keeps extraction columns.
METADATA_FIELDS = [
    "SubmitDateTime",
    "DocTypeCode",
    "DocTypeName",
    "RoleHint",
    "FilerName",
    "FilerSecCode",
    "FilerEdinetCode",
    "SubjectEdinetCode",
    "DocDescription",
    "DocID",
    "PdfFlag",
    "XbrlFlag",
    "ParentDocID",
    "CaseID",
]

# Human-readable values first, identifiers last.
LIST_FIELDS = [
    "SubmitDateTime",
    "DocTypeName",
    "OfferorName",
    "TargetSecCode",
    "TargetName",
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "ExistingHoldingRatio",
    "SpecialRelatedHoldingRatio",
    "AfterPurchaseRatio",
    "SponsorHint",
    "IsMBO",
    "ValuationMarketMin",
    "ValuationMarketMax",
    "ValuationComparableMin",
    "ValuationComparableMax",
    "ValuationDCFMin",
    "ValuationDCFMax",
    "PlannedSharesMin",
    "PlannedSharesMax",
    "PlannedSharesPlanned",
    "PurchaseConsideration",
    "TenderOfferAgent",
    "OpinionStance",
    "FinalResultNote",
    "WithdrawalReason",
    "ResponseNote",
    "RoleHint",
    "DocDescription",
    "ExtractionStatus",
    "FilerName",
    "FilerSecCode",
    "FilerEdinetCode",
    "SubjectEdinetCode",
    "DocTypeCode",
    "DocID",
    "ParentDocID",
    "CaseID",
    "PdfFlag",
    "XbrlFlag",
    "TaxonomyYear",
    "TaxonomyDate",
    "TaxonomySource",
    "OfferPriceRaw",
    "OfferPriceElement",
    "OfferPeriodRaw",
    "OfferPeriodElement",
    "PurposesRaw",
    "PurposesElement",
    "OverviewRaw",
    "OverviewElement",
    "ValuationBasisRaw",
    "IntendedPurchaseRaw",
    "IntendedPurchaseElement",
    "FundRaw",
    "FundElement",
    "ApplicationRaw",
    "ApplicationElement",
    "ExistingHoldingRatioElement",
    "AfterPurchaseRatioElement",
    "OpinionRaw",
    "OpinionElement",
    "FinalResultRaw",
    "FinalResultElement",
    "WithdrawalReasonRaw",
    "WithdrawalReasonElement",
    "ResponseRaw",
    "ResponseElement",
    "ExtractionError",
    "ExtractedAt",
]

EXTRACTION_FIELDS = [key for key in LIST_FIELDS if key not in METADATA_FIELDS]

CASE_FIELDS = [
    "OfferorName",
    "TargetSecCode",
    "TargetName",
    "Status",
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "ExistingHoldingRatio",
    "SpecialRelatedHoldingRatio",
    "AfterPurchaseRatio",
    "SponsorHint",
    "IsMBO",
    "ValuationMarketMin",
    "ValuationMarketMax",
    "ValuationComparableMin",
    "ValuationComparableMax",
    "ValuationDCFMin",
    "ValuationDCFMax",
    "PlannedSharesMin",
    "PlannedSharesMax",
    "PlannedSharesPlanned",
    "PurchaseConsideration",
    "TenderOfferAgent",
    "OpinionStance",
    "FinalResultNote",
    "TargetDelistingNote",
    "FirstFilingDate",
    "LastUpdateDate",
    "HasOpinion",
    "DocCount",
    "EnrichmentStatus",
    "OfferorEdinetCode",
    "TargetEdinetCode",
    "CaseID",
    "LatestFilingDocID",
    "LatestOpinionDocID",
    "LatestReportDocID",
    "LastEnrichedDocID",
    "DocIDList",
]


def empty_extraction() -> dict[str, str]:
    return {key: "" for key in EXTRACTION_FIELDS}


def normalize_doc_type(code: object) -> str | None:
    if code is None:
        return None
    text = str(code).replace("'", "").replace('"', "").strip()
    return text or None


def parse_user_date(value: str) -> date:
    """Accept YYYY/MM/DD or YYYY-MM-DD."""
    text = value.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"日付形式が不正です（YYYY/MM/DD または YYYY-MM-DD）: {value}")


def parse_year(value: str) -> int:
    text = value.strip()
    if not re.fullmatch(r"\d{4}", text):
        raise SystemExit(f"年は YYYY で指定してください: {value}")
    year = int(text)
    if year < 2000 or year > 2100:
        raise SystemExit(f"年が範囲外です: {value}")
    return year


def resolve_range(
    from_year: str | None = None,
    to_year: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    recent_days: int | None = None,
    today: date | None = None,
) -> tuple[date, date, str]:
    """Return (start, end, mode). mode is years / recent / dates."""
    today = today or date.today()
    if recent_days is not None:
        if recent_days < 1:
            raise SystemExit("--recent-days は 1 以上にしてください")
        start = today - timedelta(days=recent_days)
        return start, today, "recent"
    if from_date or to_date:
        if not from_date:
            raise SystemExit("--to-date だけ指定することはできません。--from-date も指定してください")
        start = parse_user_date(from_date)
        end = parse_user_date(to_date) if to_date else today
        if end < start:
            raise SystemExit(f"終了日が開始日より前です: {start} > {end}")
        return start, end, "dates"
    start_y = parse_year(from_year) if from_year else today.year
    end_y = parse_year(to_year) if to_year else today.year
    if end_y < start_y:
        raise SystemExit(f"終了年が開始年より前です: {start_y} > {end_y}")
    start = date(start_y, 1, 1)
    end = date(end_y, 12, 31)
    if end > today:
        end = today
    return start, end, "years"


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_doc_row(row: dict) -> dict:
    out = {key: (row.get(key) or "") for key in LIST_FIELDS}
    if not out.get("AfterPurchaseRatio") and row.get("OwnershipRatio"):
        out["AfterPurchaseRatio"] = format_pct(row.get("OwnershipRatio") or "") or (row.get("OwnershipRatio") or "")
    apply_name_fallbacks(out)
    return out


def apply_name_fallbacks(row: dict) -> None:
    type_code = row.get("DocTypeCode") or ""
    filer = normalize_name(row.get("FilerName") or "")
    if not row.get("OfferorName") and type_code in OFFEROR_SIDE | ANSWER_SIDE:
        row["OfferorName"] = filer
    if not row.get("TargetName") and type_code in OPINION_SIDE:
        row["TargetName"] = filer
    if row.get("OfferorName"):
        row["OfferorName"] = clean_extracted_name(row["OfferorName"])
    if row.get("TargetName"):
        row["TargetName"] = clean_extracted_name(row["TargetName"])


def merge_document_rows(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    """Upsert by DocID. Incoming metadata overwrites; extraction columns are kept."""
    by_id: dict[str, dict] = {}
    added = 0
    updated = 0
    for row in existing:
        normalized = normalize_doc_row(row)
        doc_id = normalized.get("DocID") or ""
        if doc_id:
            by_id[doc_id] = normalized
    for row in incoming:
        normalized = normalize_doc_row(row)
        doc_id = normalized.get("DocID") or ""
        if not doc_id:
            continue
        if doc_id in by_id:
            merged = dict(by_id[doc_id])
            old_meta = {key: merged.get(key, "") for key in METADATA_FIELDS if key != "CaseID"}
            for key in METADATA_FIELDS:
                if key == "CaseID":
                    continue
                merged[key] = normalized.get(key, "") or merged.get(key, "")
            new_meta = {key: merged.get(key, "") for key in METADATA_FIELDS if key != "CaseID"}
            if new_meta != old_meta:
                updated += 1
            by_id[doc_id] = merged
        else:
            by_id[doc_id] = normalized
            added += 1
    rows = list(by_id.values())
    rows.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("FilerName") or ""))
    return rows, added, updated


def is_issuer_tender(row: dict) -> bool:
    """自己株式の公開買付け: 提出者と対象会社の EDINET コードが同じ。"""
    filer = (row.get("FilerEdinetCode") or "").strip()
    subject = (row.get("SubjectEdinetCode") or "").strip()
    return bool(filer and subject and filer == subject)


def partition_issuer_tenders(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    other: list[dict] = []
    issuer: list[dict] = []
    for row in rows:
        if is_issuer_tender(row):
            issuer.append(row)
        else:
            other.append(row)
    return other, issuer


def party_pair(row: dict) -> tuple[str, str]:
    """Return (offeror EDINET, target EDINET) for grouping."""
    filer = (row.get("FilerEdinetCode") or "").strip()
    subject = (row.get("SubjectEdinetCode") or "").strip()
    if (row.get("DocTypeCode") or "") in OPINION_SIDE | ANSWER_SIDE:
        return subject, filer
    return filer, subject


def fallback_case_id(row: dict) -> str:
    offeror, target = party_pair(row)
    return f"fallback:{offeror}|{target}"


def resolve_case_id(row: dict, by_id: dict[str, dict], memo: dict[str, str]) -> str:
    doc_id = row.get("DocID") or ""
    if not doc_id:
        return fallback_case_id(row)
    if doc_id in memo:
        return memo[doc_id]

    seen: list[str] = []
    current_id = doc_id
    external_parent: str | None = None
    root: str | None

    while current_id:
        if current_id in memo:
            root = memo[current_id]
            break
        if current_id in seen:
            root = current_id
            break
        seen.append(current_id)
        current = by_id.get(current_id)
        if current is None:
            external_parent = current_id if current_id != doc_id else None
            root = None
            break
        parent = (current.get("ParentDocID") or "").strip()
        if not parent:
            root = current_id
            break
        if parent not in by_id:
            external_parent = parent
            root = None
            break
        current_id = parent
    else:
        root = doc_id

    if root is None:
        case_id = external_parent or fallback_case_id(row)
    else:
        case_id = root

    for node in seen:
        memo[node] = case_id
    memo[doc_id] = case_id
    return case_id


def assign_case_ids(rows: list[dict]) -> None:
    by_id = {r["DocID"]: r for r in rows if r.get("DocID")}
    memo: dict[str, str] = {}
    for row in rows:
        row["CaseID"] = resolve_case_id(row, by_id, memo)
    reattach_orphan_opinions(rows)


def reattach_orphan_opinions(rows: list[dict]) -> None:
    """Join 意見表明-only groups onto the matching offeror/target filing case.

    訂正意見表明の親が CSV に無いと ParentDocID だけで案件が割れ、
    同じ TOB が「意見表明のみ」行になってしまう。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row.get("CaseID") or fallback_case_id(row)].append(row)

    filing_by_pair: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for case_id, docs in groups.items():
        codes = {d.get("DocTypeCode") for d in docs}
        if not (codes & OFFEROR_SIDE):
            continue
        sample = next((d for d in docs if d.get("DocTypeCode") in OFFEROR_SIDE), docs[0])
        pair = party_pair(sample)
        if not pair[0] or not pair[1]:
            continue
        first = min((d.get("SubmitDateTime") or "") for d in docs)
        filing_by_pair[pair].append((case_id, first))

    for case_id, docs in groups.items():
        codes = {d.get("DocTypeCode") for d in docs}
        if codes & OFFEROR_SIDE:
            continue
        if not (codes & OPINION_SIDE):
            continue
        pair = party_pair(docs[0])
        candidates = filing_by_pair.get(pair) or []
        if not candidates:
            continue
        opinion_time = min((d.get("SubmitDateTime") or "") for d in docs)
        before = [item for item in candidates if item[1] <= opinion_time]
        dest = max(before, key=lambda item: item[1])[0] if before else min(candidates, key=lambda item: item[1])[0]
        if dest == case_id:
            continue
        for doc in docs:
            doc["CaseID"] = dest


def latest_doc(docs: list[dict], type_codes: set[str]) -> dict | None:
    matched = [d for d in docs if d.get("DocTypeCode") in type_codes]
    if not matched:
        return None
    return max(matched, key=lambda d: d.get("SubmitDateTime") or "")


def earliest_doc(docs: list[dict], type_codes: set[str]) -> dict | None:
    matched = [d for d in docs if d.get("DocTypeCode") in type_codes]
    if not matched:
        return None
    return min(matched, key=lambda d: d.get("SubmitDateTime") or "")


def case_status(docs: list[dict]) -> str:
    codes = {d.get("DocTypeCode") for d in docs}
    if "260" in codes:
        return "撤回"
    if codes & REPORT_SIDE:
        return "報告書提出"
    if "250" in codes:
        return "訂正あり"
    if "240" in codes:
        return "届出中"
    if codes & OPINION_SIDE:
        return "意見表明のみ"
    return "関連書類"


def pick_offeror_target(docs: list[dict]) -> tuple[str, str, str, str]:
    """Return OfferorName, TargetName, OfferorEdinetCode, TargetEdinetCode."""
    offeror_docs = [d for d in docs if d.get("DocTypeCode") in OFFEROR_SIDE]
    preferred = sorted(offeror_docs, key=lambda d: d.get("SubmitDateTime") or "")
    if preferred:
        filing_first = earliest_doc(docs, FILING_SIDE) or preferred[0]
        offeror_name = filing_first.get("OfferorName") or filing_first.get("FilerName") or ""
        target_name = filing_first.get("TargetName") or ""
        return (
            offeror_name,
            target_name,
            filing_first.get("FilerEdinetCode") or "",
            filing_first.get("SubjectEdinetCode") or "",
        )

    opinion = latest_doc(docs, OPINION_SIDE)
    if opinion:
        return (
            opinion.get("OfferorName") or "",
            opinion.get("TargetName") or opinion.get("FilerName") or "",
            opinion.get("SubjectEdinetCode") or "",
            opinion.get("FilerEdinetCode") or "",
        )
    first = sorted(docs, key=lambda d: d.get("SubmitDateTime") or "")[0]
    return (
        first.get("OfferorName") or first.get("FilerName") or "",
        first.get("TargetName") or "",
        first.get("FilerEdinetCode") or "",
        first.get("SubjectEdinetCode") or "",
    )


def resolve_target_edinet_code(row: dict) -> str:
    """Return the target company's EDINET code for a document row."""
    type_code = row.get("DocTypeCode") or ""
    if type_code in OPINION_SIDE | ANSWER_SIDE:
        return (row.get("FilerEdinetCode") or "").strip()
    if is_issuer_tender(row):
        return (row.get("FilerEdinetCode") or "").strip()
    return (row.get("SubjectEdinetCode") or "").strip()


def apply_target_sec_code(row: dict, edinet_list: EdinetCodeList | None = None) -> None:
    type_code = row.get("DocTypeCode") or ""
    sec = ""
    if type_code in OPINION_SIDE or is_issuer_tender(row):
        sec = row.get("FilerSecCode") or ""
    if not sec and edinet_list is not None:
        sec = edinet_list.sec_code(resolve_target_edinet_code(row))
    row["TargetSecCode"] = format_sec_code(sec)


def refresh_target_metadata(rows: list[dict], edinet_list: EdinetCodeList | None = None) -> None:
    for row in rows:
        apply_target_sec_code(row, edinet_list)


def resolve_case_target_sec_code(
    docs: list[dict],
    target_edinet: str,
    edinet_list: EdinetCodeList | None = None,
) -> str:
    for doc in docs:
        sec = (doc.get("TargetSecCode") or "").strip()
        if sec:
            return sec
    if edinet_list is not None and target_edinet:
        return format_sec_code(edinet_list.sec_code(target_edinet))
    return ""


def collect_delisting_source_texts(docs: list[dict]) -> list[str]:
    texts: list[str] = []
    for doc in docs:
        raw = (doc.get("OpinionRaw") or "").strip()
        if raw:
            texts.append(raw)
    return texts


def refresh_derived_list_fields(rows: list[dict]) -> None:
    """Recompute short price/result columns from stored Raw text (no API)."""
    for row in rows:
        raw_price = row.get("OfferPriceRaw") or ""
        valuation_text = row.get("ValuationBasisRaw") or raw_price
        if raw_price:
            row["OfferPrice"] = summarize_price(raw_price)
        if valuation_text:
            row.update(parse_valuation_ranges(valuation_text))
        purposes_raw = row.get("PurposesRaw") or ""
        overview_raw = row.get("OverviewRaw") or ""
        opinion_raw = row.get("OpinionRaw") or ""
        if purposes_raw or overview_raw:
            row["SponsorHint"] = extract_sponsor_from_purposes(purposes_raw or overview_raw)
        row["IsMBO"] = detect_mbo([purposes_raw, overview_raw, opinion_raw])
        intended_raw = row.get("IntendedPurchaseRaw") or ""
        if intended_raw:
            row.update(parse_planned_purchase_counts(intended_raw))
        fund_raw = row.get("FundRaw") or ""
        if fund_raw:
            row["PurchaseConsideration"] = parse_purchase_consideration(fund_raw)
        application_raw = row.get("ApplicationRaw") or ""
        if application_raw:
            row["TenderOfferAgent"] = extract_tender_offer_agent(application_raw)
        code = row.get("DocTypeCode") or ""
        if code in WITHDRAW_SIDE:
            row["FinalResultNote"] = "撤回"
        elif code in REPORT_SIDE:
            raw = row.get("FinalResultRaw") or ""
            if raw:
                row["FinalResultNote"] = judge_tob_result(raw)


def overlay_case_from_docs(docs_sorted: list[dict]) -> dict[str, str]:
    """Merge document-level extracted fields in filing order."""
    out = {
        "OfferPrice": "",
        "OfferPeriodStart": "",
        "OfferPeriodEnd": "",
        "ExistingHoldingRatio": "",
        "SpecialRelatedHoldingRatio": "",
        "AfterPurchaseRatio": "",
        "SponsorHint": "",
        "IsMBO": "",
        "ValuationMarketMin": "",
        "ValuationMarketMax": "",
        "ValuationComparableMin": "",
        "ValuationComparableMax": "",
        "ValuationDCFMin": "",
        "ValuationDCFMax": "",
        "PlannedSharesMin": "",
        "PlannedSharesMax": "",
        "PlannedSharesPlanned": "",
        "PurchaseConsideration": "",
        "TenderOfferAgent": "",
        "OpinionStance": "",
        "FinalResultNote": "",
        "TargetName": "",
        "LastEnrichedDocID": "",
    }
    last_enriched = ""
    withdrawn = False
    result_raw = ""
    report_after = ""
    for doc in docs_sorted:
        type_code = doc.get("DocTypeCode") or ""
        doc_id = doc.get("DocID") or ""
        if doc.get("TargetName"):
            out["TargetName"] = doc["TargetName"]
        if (doc.get("ExtractionStatus") or "") in {"done", "partial", "skipped"}:
            last_enriched = doc_id

        if type_code in WITHDRAW_SIDE:
            withdrawn = True
            if doc_id:
                last_enriched = doc_id
            continue

        if type_code in FILING_SIDE:
            if doc.get("OfferPrice"):
                out["OfferPrice"] = doc["OfferPrice"]
            if doc.get("OfferPeriodStart"):
                out["OfferPeriodStart"] = doc["OfferPeriodStart"]
            if doc.get("OfferPeriodEnd"):
                out["OfferPeriodEnd"] = doc["OfferPeriodEnd"]
            if doc.get("ExistingHoldingRatio"):
                out["ExistingHoldingRatio"] = doc["ExistingHoldingRatio"]
            if doc.get("SpecialRelatedHoldingRatio"):
                out["SpecialRelatedHoldingRatio"] = doc["SpecialRelatedHoldingRatio"]
            for key in (
                "SponsorHint",
                "IsMBO",
                "ValuationMarketMin",
                "ValuationMarketMax",
                "ValuationComparableMin",
                "ValuationComparableMax",
                "ValuationDCFMin",
                "ValuationDCFMax",
                "PlannedSharesMin",
                "PlannedSharesMax",
                "PlannedSharesPlanned",
                "PurchaseConsideration",
                "TenderOfferAgent",
            ):
                if doc.get(key):
                    out[key] = doc[key]
            # Filing AfterPurchaseRatio is the *planned* post-offer figure (often 100%).
            # Cases show the actual outcome instead; do not copy the plan here.
        elif type_code in OPINION_SIDE:
            if doc.get("OpinionStance"):
                out["OpinionStance"] = doc["OpinionStance"]
            if doc.get("IsMBO") == "Yes":
                out["IsMBO"] = "Yes"
        elif type_code in REPORT_SIDE:
            if doc.get("FinalResultRaw"):
                result_raw = doc["FinalResultRaw"]
            elif doc.get("FinalResultNote"):
                result_raw = doc["FinalResultNote"]
            if doc.get("OfferPeriodStart"):
                out["OfferPeriodStart"] = doc["OfferPeriodStart"]
            if doc.get("OfferPeriodEnd"):
                out["OfferPeriodEnd"] = doc["OfferPeriodEnd"]
            if doc.get("AfterPurchaseRatio") or doc.get("OwnershipRatio"):
                report_after = doc.get("AfterPurchaseRatio") or format_pct(doc.get("OwnershipRatio") or "")

    result = judge_tob_result(result_raw, withdrawn=withdrawn)
    out["FinalResultNote"] = result
    if result in {"不成立", "撤回"}:
        out["AfterPurchaseRatio"] = out.get("ExistingHoldingRatio") or ""
    elif result.startswith("成立"):
        out["AfterPurchaseRatio"] = report_after
    else:
        out["AfterPurchaseRatio"] = ""

    out["LastEnrichedDocID"] = last_enriched
    return out


def compute_case_enrichment_status(case: dict, docs: list[dict]) -> str:
    if case.get("Status") == "撤回":
        return "done"
    statuses = {(d.get("ExtractionStatus") or "").strip() for d in docs}
    filled = sum(
        1
        for key in (
            "OfferPrice",
            "OfferPeriodStart",
            "OfferPeriodEnd",
            "ExistingHoldingRatio",
            "OpinionStance",
            "FinalResultNote",
        )
        if case.get(key)
    )
    if filled >= 2:
        return "done"
    if filled >= 1:
        return "partial"
    if statuses & {"failed"} and not (statuses & {"done", "partial"}):
        return "failed"
    if statuses <= {"", "pending"}:
        return ""
    return "failed"


def build_cases(rows: list[dict], edinet_list: EdinetCodeList | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        case_id = row.get("CaseID") or fallback_case_id(row)
        groups[case_id].append(row)

    cases: list[dict] = []
    for case_id, docs in groups.items():
        codes = {d.get("DocTypeCode") for d in docs}
        if not (codes & OFFEROR_SIDE):
            # 意見表明・対質問だけのグループは案件行にしない。
            continue
        docs_sorted = sorted(docs, key=lambda d: d.get("SubmitDateTime") or "")
        offeror_name, target_name, offeror_code, target_code = pick_offeror_target(docs_sorted)
        if not offeror_name:
            for doc in docs_sorted:
                if doc.get("DocTypeCode") in OFFEROR_SIDE and (doc.get("OfferorName") or doc.get("FilerName")):
                    offeror_name = doc.get("OfferorName") or doc["FilerName"]
                    break

        first_filing = earliest_doc(docs_sorted, {"240"}) or docs_sorted[0]
        last_doc = docs_sorted[-1]
        latest_filing = latest_doc(docs_sorted, FILING_SIDE)
        latest_opinion = latest_doc(docs_sorted, OPINION_SIDE)
        latest_report = latest_doc(docs_sorted, REPORT_SIDE)
        overlay = overlay_case_from_docs(docs_sorted)
        if overlay.get("TargetName"):
            target_name = overlay["TargetName"]
        overlay["TargetSecCode"] = resolve_case_target_sec_code(docs_sorted, target_code, edinet_list)
        listing = edinet_list.listing_category(target_code) if edinet_list is not None else ""
        overlay["TargetDelistingNote"] = judge_target_delisting(
            overlay.get("FinalResultNote") or "",
            listing,
            collect_delisting_source_texts(docs_sorted),
        )
        has_opinion = "Yes" if latest_opinion or overlay.get("OpinionStance") else "No"
        doc_ids = [d.get("DocID") or "" for d in docs_sorted if d.get("DocID")]
        case = {
            "CaseID": case_id,
            "OfferorName": offeror_name,
            "TargetName": target_name,
            "OfferorEdinetCode": offeror_code,
            "TargetEdinetCode": target_code,
            "FirstFilingDate": (first_filing.get("SubmitDateTime") or "")[:10],
            "LastUpdateDate": (last_doc.get("SubmitDateTime") or "")[:10],
            "Status": case_status(docs_sorted),
            "HasOpinion": has_opinion,
            "LatestFilingDocID": (latest_filing or {}).get("DocID", ""),
            "LatestOpinionDocID": (latest_opinion or {}).get("DocID", ""),
            "LatestReportDocID": (latest_report or {}).get("DocID", ""),
            "DocCount": str(len(docs_sorted)),
            "DocIDList": ";".join(doc_ids),
            **overlay,
        }
        case["OfferorName"] = offeror_name
        case["TargetName"] = overlay.get("TargetName") or target_name
        case["EnrichmentStatus"] = compute_case_enrichment_status(case, docs_sorted)
        cases.append(case)

    cases.sort(key=lambda c: (c.get("FirstFilingDate") or "", c.get("CaseID") or ""))
    return cases


def prepare_pipeline_rows(
    rows: list[dict],
    edinet_list: EdinetCodeList | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Split 自社株, assign case IDs, and build both case tables."""
    refresh_derived_list_fields(rows)
    refresh_target_metadata(rows, edinet_list)
    other, issuer = partition_issuer_tenders(rows)
    assign_case_ids(other)
    assign_case_ids(issuer)
    other.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("FilerName") or ""))
    issuer.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("FilerName") or ""))
    return other, build_cases(other, edinet_list), issuer, build_cases(issuer, edinet_list)
