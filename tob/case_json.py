"""案件ごとの抽出JSON。

IDリスト（output/id_lists）とは別の output/cases/YYYY/MM/{届出DocID}.json に置く。
中身はXBRLの要素IDで場所を決め、そのブロックの中だけを読む。生成AIの要約は入れない。
不明は null。本当に0と読めた数だけ 0。比率は 0.3538 のような小数。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

from tob.enrich_tob import AMENDMENT_TYPES, fetch_document_zip, first_fact, parse_xbrl_csv_from_zip
from tob.extract_fields import (
    LISTING_MAINTAINED,
    DELISTING_PLANNED,
    clean_extracted_name,
    extract_parent_company_name,
    extract_pe_sponsor_name,
    extract_special_committee_valuation,
    extract_sponsor_from_purposes,
    detect_mbo,
    detect_target_listing_status,
    extract_tender_offer_agent,
    extract_valuation_basis_section,
    extract_valuation_from_purposes,
    has_delisting_planned_signal,
    has_listing_maintain_signal,
    hostile_from_opinion,
    parse_agreed_tender,
    parse_fairness_measures,
    parse_board_opinion,
    parse_number,
    parse_offer_report_counts,
    parse_offer_yen_per_share,
    parse_period_dates,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_reference_market_price_details,
    parse_valuation_records,
    summarize_price,
    judge_tob_result,
    _parse_int,
)
from tob.id_list import iter_months, resolve_months
from tob.taxonomy import TaxonomyCatalog, resolve_taxonomy_year
from tob.tob_common import (
    ANSWER_SIDE,
    DOC_TYPE_NAMES,
    FILING_SIDE,
    OPINION_SIDE,
    REPORT_SIDE,
    WITHDRAW_SIDE,
    edinet_pdf_url,
)

CASE_SCHEMA = "tob-case-1"
DEFAULT_CASE_DIR = Path("output/cases")
DEFAULT_ID_LIST_DIR = Path("output/id_lists")

_TEXT_FIELDS = (
    ("offer_price_text", "offerPrice"),
    ("period_text", "period"),
    ("purposes_text", "purposes"),
    ("overview_text", "overview"),
    ("intended_purchase_text", "intendedPurchase"),
    ("fund_text", "fund"),
    ("application_text", "application"),
    ("agent_name", "agentName"),
    ("existing_holding_text", "existingHolding"),
    ("special_holding_text", "specialHolding"),
    ("opinion_text", "opinion"),
    ("final_result_text", "finalResult"),
    ("acquired_shares_text", "acquiredShares"),
    ("withdrawal_reason_text", "withdrawalReason"),
    ("recent_share_prices_text", "recentSharePrices"),
    ("stock_prices_text", "stockPrices"),
)

_CHANGE_ITEMS = (
    "OfferPrice",
    "OfferPeriodStart",
    "OfferPeriodEnd",
    "PlannedSharesMin",
    "PlannedSharesMax",
    "PlannedSharesPlanned",
    "PurchaseConsideration",
    "TenderOfferAgent",
    "OpinionStance",
)


def case_output_path(filing_month: str, case_id: str, root: Path | None = None) -> Path:
    """output/cases/YYYY/MM/{case_id}.json"""
    year, month = _split_month(filing_month)
    doc_id = (case_id or "").strip()
    if not doc_id:
        raise ValueError("case_id が空です")
    base = Path(root) if root is not None else DEFAULT_CASE_DIR
    return base / year / f"{int(month):02d}" / f"{doc_id}.json"


def write_case_json(document: dict, root: Path | None = None) -> Path:
    month = document.get("filingMonth") or ""
    case_id = document.get("caseId") or ""
    path = case_output_path(month, case_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def document_from_xbrl(row: dict, facts: dict[str, list[str]], mapping: dict) -> dict:
    """One EDINET document: full taxonomy text, no CSV length cap."""
    type_code = str(row.get("DocTypeCode") or row.get("docTypeCode") or "")
    tax_key = {
        "240": "ton",
        "250": "ton",
        "260": "wto",
        "270": "tor",
        "280": "tor",
        "290": "pst",
        "300": "pst",
        "310": "toa",
        "320": "toa",
    }.get(type_code, "")
    fields = mapping.get(tax_key, {}) if tax_key else {}
    texts: dict[str, str] = {}
    for source_key, dest_key in _TEXT_FIELDS:
        value, _element = first_fact(facts, fields.get(source_key, []))
        texts[dest_key] = value or ""
    after, _ = first_fact(facts, fields.get("after_purchase_ratio", []))
    offeror_votes, _ = first_fact(facts, fields.get("offeror_voting_rights", []))
    special_votes, _ = first_fact(facts, fields.get("special_voting_rights", []))
    total_votes, _ = first_fact(facts, fields.get("total_voting_rights", []))
    doc_id = str(row.get("DocID") or row.get("docId") or "")
    submit = str(row.get("SubmitDateTime") or row.get("submitDateTime") or row.get("submitDate") or "")[:10]
    offeror_fact, _ = first_fact(facts, fields.get("offeror_name", []))
    target_fact, _ = first_fact(facts, fields.get("target_name", []))
    offeror_name = clean_extracted_name(offeror_fact.split("\n")[0]) if offeror_fact else ""
    target_name = clean_extracted_name(target_fact.split("\n")[0]) if target_fact else ""
    return {
        "docId": doc_id,
        "docTypeCode": type_code,
        "submitDate": submit,
        "parentDocId": str(row.get("ParentDocID") or row.get("parentDocID") or row.get("parentDocId") or ""),
        "pdfUrl": edinet_pdf_url(doc_id),
        "xbrlStatus": str(row.get("xbrlStatus") or ""),
        "offerorName": offeror_name or str(row.get("OfferorName") or row.get("offerorName") or ""),
        "targetName": target_name or str(row.get("TargetName") or row.get("targetName") or ""),
        "offerorEdinetCode": str(row.get("OfferorEdinetCode") or row.get("FilerEdinetCode") or ""),
        "targetEdinetCode": str(row.get("TargetEdinetCode") or row.get("SubjectEdinetCode") or ""),
        "issuerTender": bool(row.get("issuerTender") or row.get("IssuerTender")),
        "texts": texts,
        "numbers": {
            "afterPurchaseRatio": after or "",
            "offerorVotes": offeror_votes or "",
            "specialVotes": special_votes or "",
            "totalVotes": total_votes or "",
        },
    }


def build_case_json(filing_month: str, documents: list[dict], *, case_id: str = "") -> dict:
    """Assemble one portable case file from per-document taxonomy text."""
    _split_month(filing_month)
    docs = [_normalize_document(item) for item in documents]
    docs_by_date = sorted(docs, key=lambda item: (item["submitDate"], item["docId"]))
    root = _root_filing(docs_by_date)
    resolved_id = case_id or (root["docId"] if root else (docs_by_date[0]["docId"] if docs_by_date else ""))
    filings = [item for item in docs_by_date if item["docTypeCode"] in FILING_SIDE]
    opinions = [item for item in docs_by_date if item["docTypeCode"] in OPINION_SIDE]
    reports = [item for item in docs_by_date if item["docTypeCode"] in REPORT_SIDE]
    withdrawals = [item for item in docs_by_date if item["docTypeCode"] in WITHDRAW_SIDE]

    latest_filing = _latest_with_votes(filings) or (filings[-1] if filings else None)
    first_opinion = opinions[0] if opinions else None
    latest_opinion = opinions[-1] if opinions else None
    latest_report = reports[-1] if reports else None

    price_source = _latest_with_text(filings, "offerPrice") or latest_filing
    period_source = _latest_with_text(reports, "period") or _latest_with_text(filings, "period")
    planned_source = _latest_with_text(filings, "intendedPurchase")
    fund_source = _latest_with_text(filings, "fund")
    agent_source = _latest_with_text(filings, "application") or _latest_with_text(filings, "agentName")

    offer_price = _offer_price_number(price_source)
    start, end = _period(period_source)
    planned = parse_planned_purchase_counts((planned_source or {}).get("texts", {}).get("intendedPurchase", ""))
    consideration = _yen_number(
        parse_purchase_consideration((fund_source or {}).get("texts", {}).get("fund", ""))
    )
    agent = ""
    if agent_source:
        agent = extract_tender_offer_agent(
            agent_source["texts"].get("application", ""),
            agent_source["texts"].get("agentName", ""),
        )

    initial_stance = parse_board_opinion((first_opinion or {}).get("texts", {}).get("opinion", ""))
    latest_stance = parse_board_opinion((latest_opinion or {}).get("texts", {}).get("opinion", ""))
    hostile = hostile_from_opinion(initial_stance)

    result_text = (latest_report or {}).get("texts", {}).get("finalResult", "")
    acquired = (latest_report or {}).get("texts", {}).get("acquiredShares", "")
    withdrawn = bool(withdrawals)
    result_note = judge_tob_result(result_text, withdrawn=withdrawn)
    counts = parse_offer_report_counts(result_text, acquired) if latest_report else {}

    names = _names(docs_by_date)
    holdings = _holdings(latest_filing, latest_report)
    references = _reference_prices(filings)
    premiums = _premiums(offer_price, references)
    valuations = _valuations(docs_by_date)
    changes = _changes(docs_by_date)
    narrative = _narrative(filings, opinions)
    delisting_narrative = _delisting_narrative(filings, opinions)
    listing_status = detect_target_listing_status(narrative) or None

    return {
        "schema": CASE_SCHEMA,
        "caseId": resolved_id,
        "filingMonth": filing_month,
        "issuerTender": any(item["issuerTender"] for item in docs),
        "core": {
            "OfferorName": names["offeror"] or None,
            "SponsorHint": _sponsor_hint(filings) or None,
            "TargetEdinetCode": names["targetCode"] or None,
            "OfferorEdinetCode": names["offerorCode"] or None,
            "TargetName": names["target"] or None,
            "Status": _status(result_note, reports, withdrawals),
            "OfferPrice": offer_price,
            "OfferPeriodStart": start or None,
            "OfferPeriodEnd": end or None,
            "ExistingHoldingRatio": holdings["existing"],
            "SpecialRelatedHoldingRatio": holdings["special"],
            "AfterPurchaseRatio": holdings["after"],
            "IsMBO": _is_mbo(filings, opinions),
            "IsHostileInitial": hostile or None,
            "PlannedSharesMin": _count_or_none(planned["PlannedSharesMin"]),
            "PlannedSharesMax": _count_or_none(planned["PlannedSharesMax"]),
            "PlannedSharesPlanned": _count_or_none(planned["PlannedSharesPlanned"]),
            "PurchaseConsideration": consideration,
            "TenderOfferAgent": agent or None,
            "OpinionStance": latest_stance or None,
            "FinalResultNote": result_note or None,
            "ApplicationCount": _count_or_none(counts.get("ApplicationCount", "")),
            "PurchaseCount": _count_or_none(counts.get("PurchaseCount", "")),
            "TargetDelistingNote": _delisting_note(result_note, delisting_narrative, result_text),
            "TargetListingStatus": listing_status,
            "DocIDList": [item["docId"] for item in docs_by_date if item["docId"]],
        },
        "pdfLinks": _pdf_links(docs_by_date),
        "referencePrices": references,
        "premiums": premiums,
        "agreedTender": parse_agreed_tender(narrative),
        "fairnessMeasures": parse_fairness_measures(narrative),
        "valuations": valuations,
        "changes": changes,
        "timeline": _timeline(docs_by_date),
        "documents": [_public_document(item) for item in docs_by_date],
    }


def _split_month(filing_month: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", filing_month or "")
    if not match:
        raise ValueError(f"filing_month は YYYY-MM です: {filing_month}")
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise ValueError(f"filing_month は YYYY-MM です: {filing_month}")
    return match.group(1), match.group(2)


def _normalize_document(raw: dict) -> dict:
    texts = dict(raw.get("texts") or {})
    for _source, key in _TEXT_FIELDS:
        texts.setdefault(key, "")
    numbers = dict(raw.get("numbers") or {})
    submit = str(raw.get("submitDate") or raw.get("SubmitDateTime") or "")[:10]
    return {
        "docId": str(raw.get("docId") or raw.get("DocID") or ""),
        "docTypeCode": str(raw.get("docTypeCode") or raw.get("DocTypeCode") or ""),
        "submitDate": submit,
        "parentDocId": str(raw.get("parentDocId") or raw.get("ParentDocID") or ""),
        "pdfUrl": edinet_pdf_url(str(raw.get("docId") or raw.get("DocID") or "")) or str(raw.get("pdfUrl") or ""),
        "xbrlStatus": str(raw.get("xbrlStatus") or ""),
        "offerorName": str(raw.get("offerorName") or raw.get("OfferorName") or ""),
        "targetName": str(raw.get("targetName") or raw.get("TargetName") or ""),
        "offerorEdinetCode": str(raw.get("offerorEdinetCode") or raw.get("OfferorEdinetCode") or ""),
        "targetEdinetCode": str(raw.get("targetEdinetCode") or raw.get("TargetEdinetCode") or ""),
        "issuerTender": bool(raw.get("issuerTender")),
        "texts": texts,
        "numbers": numbers,
    }


def _public_document(item: dict) -> dict:
    return {
        "docId": item["docId"],
        "docTypeCode": item["docTypeCode"],
        "docTypeName": DOC_TYPE_NAMES.get(item["docTypeCode"], ""),
        "submitDate": item["submitDate"] or None,
        "parentDocId": item["parentDocId"] or None,
        "pdfUrl": item["pdfUrl"] or None,
        "xbrlStatus": item.get("xbrlStatus") or None,
        "texts": {key: value or None for key, value in item["texts"].items()},
    }


def _first_url(docs: list[dict], codes: set[str]) -> str | None:
    for item in docs:
        if item["docTypeCode"] in codes and item.get("pdfUrl"):
            return item["pdfUrl"]
    return None


def _last_url(docs: list[dict], codes: set[str]) -> str | None:
    found = [item["pdfUrl"] for item in docs if item["docTypeCode"] in codes and item.get("pdfUrl")]
    return found[-1] if found else None


def _pdf_links(docs: list[dict]) -> dict:
    """Public PDF URLs. These come from the DocID and do not need XBRL."""
    return {
        "firstFiling": _first_url(docs, {"240"}),
        "latestFiling": _last_url(docs, FILING_SIDE),
        "firstOpinion": _first_url(docs, {"290"}),
        "latestOpinion": _last_url(docs, OPINION_SIDE),
        "latestReport": _last_url(docs, REPORT_SIDE),
        "withdrawal": _last_url(docs, WITHDRAW_SIDE),
        "documents": [
            {
                "docId": item["docId"],
                "docTypeCode": item["docTypeCode"],
                "docTypeName": DOC_TYPE_NAMES.get(item["docTypeCode"], ""),
                "submitDate": item["submitDate"] or None,
                "pdfUrl": item["pdfUrl"] or None,
            }
            for item in docs
            if item.get("docId")
        ],
    }


def _root_filing(docs: list[dict]) -> dict | None:
    filings = [item for item in docs if item["docTypeCode"] == "240"]
    if filings:
        return filings[0]
    filings = [item for item in docs if item["docTypeCode"] in FILING_SIDE]
    return filings[0] if filings else None


def _latest_with_votes(docs: list[dict]) -> dict | None:
    found = [
        item
        for item in docs
        if (item.get("numbers") or {}).get("totalVotes") or (item.get("numbers") or {}).get("offerorVotes")
    ]
    return found[-1] if found else None


def _latest_with_text(docs: list[dict], key: str) -> dict | None:
    found = [item for item in docs if (item["texts"].get(key) or "").strip()]
    return found[-1] if found else None


def _names(docs: list[dict]) -> dict[str, str]:
    offeror = target = offeror_code = target_code = ""
    for item in docs:
        if item["docTypeCode"] in FILING_SIDE | REPORT_SIDE | WITHDRAW_SIDE:
            offeror = item["offerorName"] or offeror
            target = item["targetName"] or target
            offeror_code = item["offerorEdinetCode"] or offeror_code
            target_code = item["targetEdinetCode"] or target_code
    return {
        "offeror": offeror,
        "target": target,
        "offerorCode": offeror_code,
        "targetCode": target_code,
    }


def _offer_price_number(source: dict | None) -> int | None:
    if not source:
        return None
    summary = summarize_price(source["texts"].get("offerPrice", ""))
    return parse_offer_yen_per_share(summary)


def _period(source: dict | None) -> tuple[str, str]:
    if not source:
        return "", ""
    return parse_period_dates(source["texts"].get("period", ""))


def _yen_number(text: str) -> int | None:
    if not text or "円" not in text:
        return None
    if any(unit in text for unit in ("ウォン", "ドル")):
        return None
    return _parse_int(re.sub(r"[^\d]", "", text))


def _count_or_none(value: str) -> int | None:
    text = (value or "").strip()
    if not text or text == "-":
        return None
    return _parse_int(text)


def _ratio_decimal(value: str) -> float | None:
    number = parse_number(value)
    if number is None:
        return None
    if abs(number) > 1.5:
        number = number / 100
    return round(number, 6)


def _votes_ratio(part: str, total: str) -> float | None:
    numerator = parse_number(part)
    denominator = parse_number(total)
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 6)


def _holdings(filing: dict | None, report: dict | None) -> dict[str, float | None]:
    """Offeror ratio is D/J. Special is G/J. Do not add G into the offeror ratio.

    After-purchase uses the report's stated element, then the filing's stated
    element. It is not recomputed from the voting-rights counts.
    """
    source = filing or {}
    numbers = source.get("numbers") or {}
    after_source = report or filing or {}
    after_raw = (after_source.get("numbers") or {}).get("afterPurchaseRatio", "")
    if not after_raw and filing and report:
        after_raw = (filing.get("numbers") or {}).get("afterPurchaseRatio", "")
    return {
        "existing": _votes_ratio(numbers.get("offerorVotes", ""), numbers.get("totalVotes", "")),
        "special": _votes_ratio(numbers.get("specialVotes", ""), numbers.get("totalVotes", "")),
        "after": _ratio_decimal(after_raw),
    }


def _sponsor_hint(filings: list[dict]) -> str:
    """Name written in the filing text. No EDINET-list lookup and no model."""
    for item in reversed(filings):
        text = "\n".join(
            part
            for part in (
                item["texts"].get("purposes", ""),
                item["texts"].get("overview", ""),
            )
            if part
        )
        if not text:
            continue
        for extractor in (extract_pe_sponsor_name, extract_parent_company_name, extract_sponsor_from_purposes):
            name = extractor(text)
            if name:
                return name
    return ""


def _section_text(docs: list[dict], keys: tuple[str, ...]) -> str:
    parts = []
    for item in docs:
        for key in keys:
            text = item["texts"].get(key, "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _narrative(filings: list[dict], opinions: list[dict]) -> str:
    """Purpose, price and opinion text. Price repeats the fairness measures."""
    return _section_text(filings + opinions, ("purposes", "overview", "offerPrice", "opinion"))


def _delisting_narrative(filings: list[dict], opinions: list[dict]) -> str:
    """Purpose and opinion only. The price block also discusses other deals."""
    return _section_text(filings + opinions, ("purposes", "overview", "opinion"))


def _is_mbo(filings: list[dict], opinions: list[dict]) -> str | None:
    chunks = []
    for item in filings + opinions:
        chunks.append(item["texts"].get("purposes", ""))
        chunks.append(item["texts"].get("overview", ""))
        chunks.append(item["texts"].get("opinion", ""))
    if not any(part.strip() for part in chunks if part):
        return None
    return "Yes" if detect_mbo(chunks) == "Yes" else "No"


def _reference_prices(filings: list[dict]) -> dict[str, int | None]:
    """Price block first, then the stock-price taxonomy blocks. Conflicts become null."""
    keys = ("offerPrice", "recentSharePrices", "stockPrices")
    details = []
    for item in reversed(filings):
        for key in keys:
            parsed = parse_reference_market_price_details(item["texts"].get(key, ""))
            if parsed["priorClose"]:
                details.append(parsed)
                break
        if details:
            break
    if not details:
        return {"priorClose": None, "avg1m": None, "avg3m": None, "avg6m": None}
    parsed = details[0]
    return {
        "priorClose": _parse_int(parsed["priorClose"]),
        "avg1m": _parse_int(parsed["avg1m"]) if parsed["avg1m"] else None,
        "avg3m": _parse_int(parsed["avg3m"]) if parsed["avg3m"] else None,
        "avg6m": _parse_int(parsed["avg6m"]) if parsed["avg6m"] else None,
    }


def _premiums(offer: int | None, references: dict[str, int | None]) -> dict[str, float | None]:
    def one(ref: int | None) -> float | None:
        if offer is None or ref is None or offer <= 0 or ref <= 0:
            return None
        ratio = (offer - ref) / ref
        if ratio < -0.9 or ratio > 10:
            return None
        return round(ratio, 4)

    values = {
        "vsPriorClose": one(references.get("priorClose")),
        "vs1m": one(references.get("avg1m")),
        "vs3m": one(references.get("avg3m")),
        "vs6m": one(references.get("avg6m")),
    }
    values["computed"] = any(value is not None for value in values.values())
    return values


def _tag_records(text: str, *, side: str, doc: dict) -> list[dict]:
    tagged = []
    for index, record in enumerate(parse_valuation_records(text), start=1):
        tagged.append(
            {
                "advisor": record["advisor"] or None,
                "side": side,
                "marketMin": record["marketMin"],
                "marketMax": record["marketMax"],
                "comparableMin": record["comparableMin"],
                "comparableMax": record["comparableMax"],
                "dcfMin": record["dcfMin"],
                "dcfMax": record["dcfMax"],
                "sourceDocId": doc["docId"],
                "sourceDate": doc["submitDate"] or None,
                "orderInSource": index,
            }
        )
    return tagged


def _valuations(docs: list[dict]) -> list[dict]:
    """Offeror ranges and target/committee ranges stay in separate records."""
    found: list[dict] = []
    for doc in docs:
        texts = doc["texts"]
        if doc["docTypeCode"] in OPINION_SIDE:
            found.extend(_tag_records(texts.get("opinion", ""), side="target", doc=doc))
            continue
        if doc["docTypeCode"] not in FILING_SIDE:
            continue
        committee = extract_special_committee_valuation(texts.get("offerPrice", "")) or extract_special_committee_valuation(
            texts.get("purposes", "")
        )
        if committee:
            found.extend(_tag_records(committee, side="target", doc=doc))
        basis = extract_valuation_basis_section(texts.get("offerPrice", ""), limit=8000)
        offeror_text = basis or texts.get("offerPrice", "")
        if committee and committee in offeror_text:
            offeror_text = offeror_text.replace(committee, "", 1)
        offeror_records = _tag_records(offeror_text, side="offeror", doc=doc)
        if not offeror_records:
            purposes = texts.get("purposes", "")
            if committee and committee in purposes:
                purposes = purposes.replace(committee, "", 1)
            section = extract_valuation_from_purposes(purposes, limit=8000) or purposes
            offeror_records = _tag_records(section, side="offeror", doc=doc)
        found.extend(offeror_records)
    latest: dict[str, str] = {}
    for record in found:
        latest[record["side"]] = record["sourceDocId"]
    for record in found:
        record["current"] = record["sourceDocId"] == latest.get(record["side"])
    return found


def _snapshot(doc: dict) -> dict[str, object]:
    texts = doc["texts"]
    price = _offer_price_number(doc) if texts.get("offerPrice") else None
    start, end = parse_period_dates(texts.get("period", "")) if texts.get("period") else ("", "")
    planned = (
        parse_planned_purchase_counts(texts["intendedPurchase"])
        if texts.get("intendedPurchase")
        else {}
    )
    consideration = (
        _yen_number(parse_purchase_consideration(texts["fund"])) if texts.get("fund") else None
    )
    agent = ""
    if texts.get("application") or texts.get("agentName"):
        agent = extract_tender_offer_agent(texts.get("application", ""), texts.get("agentName", ""))
    stance = parse_board_opinion(texts.get("opinion", "")) if texts.get("opinion") else ""
    return {
        "OfferPrice": price,
        "OfferPeriodStart": start or None,
        "OfferPeriodEnd": end or None,
        "PlannedSharesMin": _count_or_none(planned.get("PlannedSharesMin", "")),
        "PlannedSharesMax": _count_or_none(planned.get("PlannedSharesMax", "")),
        "PlannedSharesPlanned": _count_or_none(planned.get("PlannedSharesPlanned", "")),
        "PurchaseConsideration": consideration,
        "TenderOfferAgent": agent or None,
        "OpinionStance": stance or None,
    }


def _changes(docs: list[dict]) -> list[dict]:
    """First observation is the baseline. Later differences share one ChangeNo per document."""
    baseline: dict[str, object] = {}
    seen: set[str] = set()
    changes: list[dict] = []
    number = 0
    for doc in docs:
        if doc["docTypeCode"] in ANSWER_SIDE:
            continue
        current = _snapshot(doc)
        if not any(value is not None for value in current.values()):
            continue
        diffs: list[tuple[str, object, object]] = []
        for item in _CHANGE_ITEMS:
            value = current.get(item)
            if value is None:
                continue
            if item not in seen:
                baseline[item] = value
                seen.add(item)
                continue
            if baseline.get(item) != value:
                diffs.append((item, baseline.get(item), value))
                baseline[item] = value
        if not diffs:
            continue
        number += 1
        for item, before, after in diffs:
            changes.append(
                {
                    "changeNo": f"Change-{number}",
                    "date": doc["submitDate"] or None,
                    "item": item,
                    "before": before,
                    "after": after,
                    "description": None,
                    "sourceDocId": doc["docId"],
                    "sourceUrl": doc["pdfUrl"] or None,
                }
            )
    return changes


def _timeline(docs: list[dict]) -> list[dict]:
    rows = []
    for doc in docs:
        code = doc["docTypeCode"]
        if code in FILING_SIDE and code == "240":
            kind = "start"
        elif code == "250":
            kind = "amendment"
        elif code in OPINION_SIDE:
            kind = "opinion"
        elif code in REPORT_SIDE:
            kind = "result"
        elif code in WITHDRAW_SIDE:
            kind = "withdrawal"
        elif code in ANSWER_SIDE:
            kind = "qa"
        else:
            kind = "other"
        rows.append(
            {
                "date": doc["submitDate"] or None,
                "kind": kind,
                "docId": doc["docId"],
                "docTypeCode": code,
                "label": DOC_TYPE_NAMES.get(code, code),
            }
        )
    return rows


def _status(result_note: str, reports: list[dict], withdrawals: list[dict]) -> str:
    if withdrawals or result_note == "撤回":
        return "撤回"
    if result_note.startswith("不成立"):
        return "不成立"
    if result_note.startswith("成立"):
        return "成立"
    if reports:
        return "結果報告書提出"
    return "公開買付中"


def id_list_path(month: str, directory: Path | None = None) -> Path:
    year_month = f"{_split_month(month)[0]}-{_split_month(month)[1]}"
    base = Path(directory) if directory is not None else DEFAULT_ID_LIST_DIR
    return base / f"{year_month}.json"


def documents_from_id_case(
    case: dict,
    bundles: dict[str, tuple[dict[str, list[str]], str] | None],
    catalog: TaxonomyCatalog,
) -> list[dict]:
    """Turn one ID-list case into document dicts. Missing XBRL still keeps the PDF URL."""
    issuer = bool(case.get("issuer_tender"))
    parent_year = ""
    documents: list[dict] = []
    for raw in case.get("documents") or []:
        doc_id = str(raw.get("doc_id") or raw.get("docId") or "")
        type_code = str(raw.get("doc_type_code") or raw.get("docTypeCode") or "")
        bundle = bundles.get(doc_id)
        facts: dict[str, list[str]] = {}
        zip_text = ""
        if bundle:
            facts, zip_text = bundle
        year = ""
        mapping: dict = {}
        if facts or zip_text:
            year, _tax_date, _source = resolve_taxonomy_year(
                catalog,
                submit_datetime=str(raw.get("submit_date") or ""),
                parent_year=parent_year,
                facts=facts,
                zip_text=zip_text,
                is_amendment=type_code in AMENDMENT_TYPES,
                issuer=issuer,
                doc_type_code=type_code,
            )
            mapping = catalog.merged_mapping_for_doc(year, type_code, issuer=issuer)
            if type_code == "240" and year:
                parent_year = year
        if bundle is None:
            status = "no_xbrl"
        elif facts:
            status = "ok"
        else:
            status = "empty"
        row = {
            "DocID": doc_id,
            "DocTypeCode": type_code,
            "submitDate": str(raw.get("submit_date") or "")[:10],
            "ParentDocID": str(raw.get("parent_doc_id") or ""),
            "OfferorName": case.get("offeror_name") or "",
            "TargetName": case.get("target_name") or "",
            "OfferorEdinetCode": case.get("offeror_edinet_code") or "",
            "TargetEdinetCode": case.get("target_edinet_code") or "",
            "issuerTender": issuer,
            "xbrlStatus": status,
        }
        documents.append(document_from_xbrl(row, facts, mapping))
    return documents


def build_cases_for_month(
    report: dict,
    *,
    catalog: TaxonomyCatalog,
    api_key: str,
    cache_dir: Path,
    out_dir: Path,
    force: bool = False,
    sleep: float = 0.5,
) -> tuple[list[Path], list[str]]:
    """Download each document's XBRL and write output/cases/YYYY/MM/{DocID}.json."""
    month = str(report.get("month") or "")
    written: list[Path] = []
    failures: list[str] = []
    for case in report.get("cases") or []:
        case_id = str(case.get("case_id") or "")
        bundles: dict[str, tuple[dict[str, list[str]], str] | None] = {}
        for raw in case.get("documents") or []:
            doc_id = str(raw.get("doc_id") or "")
            if not doc_id:
                continue
            cached = (cache_dir / f"{doc_id}.zip").exists() and not force
            zip_path = fetch_document_zip(doc_id, api_key, cache_dir, force)
            if not cached and sleep:
                time.sleep(sleep)
            if zip_path is None:
                bundles[doc_id] = None
                failures.append(doc_id)
                continue
            try:
                bundles[doc_id] = parse_xbrl_csv_from_zip(zip_path)
            except (zipfile.BadZipFile, OSError) as exc:
                print(f"  unreadable zip {doc_id}: {exc}", file=sys.stderr)
                bundles[doc_id] = None
                failures.append(doc_id)
        documents = documents_from_id_case(case, bundles, catalog)
        payload = build_case_json(month, documents, case_id=case_id)
        payload["issuerTender"] = bool(case.get("issuer_tender")) or payload["issuerTender"]
        path = write_case_json(payload, out_dir)
        written.append(path)
        print(f"Wrote {path}", flush=True)
    return written, failures


def _load_id_list(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IDリストの月ごとに、案件JSONをXBRLから作る")
    parser.add_argument("--from-month", default="", help="開始月 YYYY-MM。空欄なら183日の窓が閉じた直近の月")
    parser.add_argument("--to-month", default="", help="終了月 YYYY-MM。空欄なら開始月と同じ")
    parser.add_argument("--id-list-dir", default=str(DEFAULT_ID_LIST_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_CASE_DIR))
    parser.add_argument("--cache-dir", default="cache/docs")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--force", action="store_true", help="キャッシュ済みXBRLも再取得する")
    parser.add_argument("--as-of", default="", help="開始月を決める基準日 YYYY-MM-DD。空なら今日")
    args = parser.parse_args(argv)

    from datetime import date

    try:
        today = date.fromisoformat(args.as_of) if args.as_of else date.today()
        start_month, end_month = resolve_months(args.from_month, args.to_month, today=today)
        months = iter_months(start_month, end_month)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    id_dir = Path(args.id_list_dir)
    missing = [month for month in months if not id_list_path(month, id_dir).is_file()]
    if missing:
        print(
            "IDリストがありません: " + ", ".join(missing) + "。先にIDリスト作成フローを実行してください。",
            file=sys.stderr,
        )
        return 1

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY がありません。", file=sys.stderr)
        return 1

    catalog = TaxonomyCatalog()
    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.out_dir)
    failures: list[str] = []
    for month in months:
        report = _load_id_list(id_list_path(month, id_dir))
        print(f"cases {month} filings={report.get('filing_count')}", flush=True)
        _written, month_failures = build_cases_for_month(
            report,
            catalog=catalog,
            api_key=api_key,
            cache_dir=cache_dir,
            out_dir=out_dir,
            force=args.force,
            sleep=args.sleep,
        )
        failures.extend(month_failures)
    if failures:
        print(f"XBRLを取れなかった書類: {len(failures)}", file=sys.stderr)
    return 0


def _delisting_note(result_note: str, narrative: str, result_text: str) -> str | None:
    if result_note in {"不成立", "撤回"}:
        return None
    combined = "\n".join(part for part in (narrative, result_text) if part)
    if not combined:
        return None
    if detect_target_listing_status(combined) in {"株主コミュニティ", "非上場"}:
        return None
    if has_listing_maintain_signal(combined):
        return LISTING_MAINTAINED
    if has_delisting_planned_signal(combined):
        return DELISTING_PLANNED
    return None


if __name__ == "__main__":
    raise SystemExit(main())
