#!/usr/bin/env python3
"""
self_tob_list.csv の各書類行について XBRL (type=5) から自社株TOBの詳細を抽出し、
書類単位の列を埋めたうえで self_tob_cases.csv を再生成する。

届出書 (240/250) から:
  買付期間、普通株式の買付価格、合計の買付予定数、公開買付代理人、買付代金
報告書 (270/280) から:
  買付期間、按分の有無
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from edinet.edinet_code_list import DEFAULT_CACHE_PATH, ensure_edinet_code_list
from tob.enrich_tob import (
    AMENDMENT_TYPES,
    apply_names,
    fetch_document_zip,
    first_fact,
    parent_taxonomy_year,
    parse_xbrl_csv_from_zip,
    pending_status,
    summarize_text,
    utc_now_iso,
)
from tob.extract_fields import (
    clean_extracted_name,
    detect_prorata_used,
    extract_tender_offer_agent,
    parse_period_dates,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    summarize_price,
)
from tob.output_store import load_all_list_rows, publish_context_from_meta, publish_tob_outputs
from tob.taxonomy import TaxonomyCatalog, resolve_taxonomy_year
from tob.tob_common import (
    DOC_TYPE_TO_TAXONOMY,
    FILING_SIDE,
    REPORT_SIDE,
    WITHDRAW_SIDE,
    SELF_ENRICH_FIELD_GROUPS,
    SELF_ENRICH_GROUP_NAMES,
    apply_name_fallbacks,
    columns_for_enrich_groups,
    parse_enrich_groups,
    partition_issuer_tenders,
    prepare_pipeline_rows,
    should_update_field,
)


def expected_fields_for_issuer_type(type_code: str) -> tuple[str, ...]:
    if type_code in FILING_SIDE:
        return ("OfferPrice", "OfferPeriodStart", "OfferPeriodEnd", "PlannedSharesPlanned")
    if type_code in REPORT_SIDE:
        return ("OfferPeriodStart", "ProrataUsed")
    if type_code in WITHDRAW_SIDE:
        return ("WithdrawalReason",)
    return ()


def compute_issuer_doc_status(row: dict, extracted_ok: bool) -> str:
    if (row.get("XbrlFlag") or "").strip() == "0":
        return "skipped"
    if not extracted_ok:
        return "failed"
    expected = expected_fields_for_issuer_type(row.get("DocTypeCode") or "")
    filled = sum(1 for key in expected if row.get(key))
    if expected and filled == 0:
        return "partial"
    if filled >= 1:
        return "done"
    return "partial"


def apply_issuer_facts_to_row(
    row: dict,
    facts: dict[str, list[str]],
    mapping: dict,
    *,
    selected: frozenset[str] | None = None,
) -> None:
    type_code = row.get("DocTypeCode") or ""
    tax_key = DOC_TYPE_TO_TAXONOMY.get(type_code)
    fields = mapping.get(tax_key, {}) if tax_key else {}
    apply_names(row, facts, fields, selected)

    if type_code in FILING_SIDE or tax_key == "ton":
        price_text, price_eid = first_fact(facts, fields.get("offer_price_text", []))
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        intended_text, intended_eid = first_fact(facts, fields.get("intended_purchase_text", []))
        fund_text, fund_eid = first_fact(facts, fields.get("fund_text", []))
        application_text, application_eid = first_fact(facts, fields.get("application_text", []))
        agent_name, agent_eid = first_fact(facts, fields.get("agent_name", []))
        start, end = parse_period_dates(period_text)
        if should_update_field("OfferPriceRaw", selected) and price_text:
            row["OfferPriceRaw"] = price_text[:5000]
            row["OfferPrice"] = summarize_price(price_text)
            row["OfferPriceElement"] = price_eid
        if should_update_field("OfferPeriodRaw", selected) and period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if should_update_field("IntendedPurchaseRaw", selected) and intended_text:
            row["IntendedPurchaseRaw"] = intended_text[:2000]
            row["IntendedPurchaseElement"] = intended_eid
            row.update(parse_planned_purchase_counts(intended_text))
        if should_update_field("FundRaw", selected) and fund_text:
            row["FundRaw"] = fund_text[:2000]
            row["FundElement"] = fund_eid
            row["PurchaseConsideration"] = parse_purchase_consideration(fund_text)
        if should_update_field("TenderOfferAgent", selected) and (application_text or agent_name):
            if application_text:
                row["ApplicationRaw"] = application_text[:1500]
                row["ApplicationElement"] = application_eid
            row["TenderOfferAgent"] = extract_tender_offer_agent(application_text, agent_name)

    if type_code in REPORT_SIDE or tax_key == "tor":
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        acquired_text, acquired_eid = first_fact(facts, fields.get("acquired_shares_text", []))
        prorata_text, prorata_eid = first_fact(facts, fields.get("prorata_calculation_text", []))
        start, end = parse_period_dates(period_text)
        if should_update_field("OfferPeriodRaw", selected) and period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if should_update_field("AcquiredSharesRaw", selected) and acquired_text:
            row["AcquiredSharesRaw"] = acquired_text[:2000]
            row["AcquiredSharesElement"] = acquired_eid
        if should_update_field("ProrataCalculationRaw", selected) and prorata_text:
            row["ProrataCalculationRaw"] = prorata_text[:2000]
            row["ProrataCalculationElement"] = prorata_eid
        if should_update_field("ProrataUsed", selected) and (acquired_text or prorata_text):
            row["ProrataUsed"] = detect_prorata_used(acquired_text, prorata_text)

    if type_code in WITHDRAW_SIDE or tax_key == "wto":
        reason_text, reason_eid = first_fact(facts, fields.get("withdrawal_reason_text", []))
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        if should_update_field("WithdrawalReasonRaw", selected) and reason_text:
            row["WithdrawalReasonRaw"] = reason_text[:1000]
            row["WithdrawalReason"] = summarize_text(reason_text)
            row["WithdrawalReasonElement"] = reason_eid
        if should_update_field("OfferPeriodRaw", selected) and period_text:
            start, end = parse_period_dates(period_text)
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid


def enrich_issuer_document(
    row: dict,
    catalog: TaxonomyCatalog,
    by_id: dict[str, dict],
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
    *,
    selected: frozenset[str] | None = None,
) -> None:
    doc_id = row.get("DocID") or ""
    type_code = row.get("DocTypeCode") or ""
    xbrl_flag = (row.get("XbrlFlag") or "").strip()
    row["ExtractedAt"] = utc_now_iso()
    row["ExtractionError"] = ""

    if xbrl_flag == "0":
        row["ExtractionStatus"] = "skipped"
        row["ExtractionError"] = "no_xbrl"
        return

    zip_path = fetch_document_zip(doc_id, api_key, cache_dir, force)
    time.sleep(sleep)
    if not zip_path:
        row["ExtractionStatus"] = "failed"
        row["ExtractionError"] = "download_failed"
        return

    facts, zip_text = parse_xbrl_csv_from_zip(zip_path)
    if not facts:
        row["ExtractionStatus"] = "failed"
        row["ExtractionError"] = "empty_facts"
        return

    year, tax_date, source = resolve_taxonomy_year(
        catalog,
        submit_datetime=row.get("SubmitDateTime") or "",
        parent_year=parent_taxonomy_year(row, by_id),
        facts=facts,
        zip_text=zip_text,
        is_amendment=type_code in AMENDMENT_TYPES,
        issuer=True,
        doc_type_code=type_code,
    )
    mapping = catalog.merged_mapping_for_doc(year, type_code, issuer=True)
    row["TaxonomyYear"] = year
    row["TaxonomyDate"] = tax_date or str(mapping.get("taxonomy_date") or "")
    row["TaxonomySource"] = source
    apply_issuer_facts_to_row(row, facts, mapping, selected=selected)
    apply_name_fallbacks(row)
    if row.get("OfferorName"):
        row["OfferorName"] = clean_extracted_name(row["OfferorName"])
    if row.get("TargetName"):
        row["TargetName"] = clean_extracted_name(row["TargetName"])
    row["ExtractionStatus"] = compute_issuer_doc_status(row, extracted_ok=True)


def enrich_issuer_documents(
    rows: list[dict],
    catalog: TaxonomyCatalog,
    api_key: str,
    cache_dir: Path,
    force: bool,
    sleep: float,
    only_pending: bool,
    doc_limit: int,
    *,
    selected: frozenset[str] | None = None,
) -> int:
    by_id = {r.get("DocID") or "": r for r in rows if r.get("DocID")}
    processed = 0
    for row in rows:
        if only_pending and not pending_status(row.get("ExtractionStatus") or ""):
            continue
        if doc_limit > 0 and processed >= doc_limit:
            break
        doc_id = row.get("DocID") or ""
        print(f"enrich self {doc_id} type={row.get('DocTypeCode')}", flush=True)
        enrich_issuer_document(row, catalog, by_id, api_key, cache_dir, force, sleep, selected=selected)
        processed += 1
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="自社株TOB書類CSVをXBRLから詳細化する")
    parser.add_argument("--output-dir", default="output", help="結果フォルダ（current / snapshots）")
    parser.add_argument("--taxonomy-dir", default="taxonomy")
    parser.add_argument("--cache-dir", default="cache/docs")
    parser.add_argument(
        "--edinet-cache",
        default=str(DEFAULT_CACHE_PATH),
        help="EDINET提出者リストCSVのキャッシュ先",
    )
    parser.add_argument("--doc-limit", type=int, default=0, help="0=全書類")
    parser.add_argument("--only-pending", action="store_true", help="未抽出の書類のみ")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5, help="API呼び出し間隔（秒）。429等が出たら1.0に増やす")
    parser.add_argument(
        "--recompute-only",
        action="store_true",
        help="APIを使わず、既存の Raw 列から価格・応募/買付数・案件を再計算する",
    )
    parser.add_argument(
        "--fields",
        default="all",
        help=(
            "更新する列グループ（カンマ区切り）。"
            "all / basic / planned_shares / fund / agent / result"
        ),
    )
    args = parser.parse_args()
    enrich_groups = parse_enrich_groups(args.fields, allowed=SELF_ENRICH_GROUP_NAMES)
    selected = columns_for_enrich_groups(enrich_groups, group_map=SELF_ENRICH_FIELD_GROUPS)

    output_dir = Path(args.output_dir)
    edinet_list = ensure_edinet_code_list(Path(args.edinet_cache))
    rows = load_all_list_rows(output_dir)
    if not rows:
        print("self_tob_list.csv がありません。先に fetch_tob.py を実行してください。", file=sys.stderr)
        return 1

    other, issuer = partition_issuer_tenders(rows)
    if args.recompute_only:
        other, cases, issuer, issuer_cases = prepare_pipeline_rows(
            rows,
            edinet_list,
            selected=selected,
        )
        _list_out, _cases_out = publish_tob_outputs(
            output_dir,
            other,
            cases,
            self_list_rows=issuer,
            self_case_rows=issuer_cases,
            **publish_context_from_meta(output_dir),
        )
        print(f"既存Rawから再計算（APIなし） fields={args.fields}")
        print(f"自社株: {len(issuer)} docs / {len(issuer_cases)} cases")
        print(f"他社株: {len(other)} docs / {len(cases)} cases")
        return 0

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY が必要です", file=sys.stderr)
        return 1

    issuer.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("DocID") or ""))
    catalog = TaxonomyCatalog(Path(args.taxonomy_dir))
    processed = enrich_issuer_documents(
        issuer,
        catalog,
        api_key,
        Path(args.cache_dir),
        args.force_refresh,
        args.sleep,
        args.only_pending,
        args.doc_limit,
        selected=selected,
    )
    other, cases, issuer, issuer_cases = prepare_pipeline_rows(
        other + issuer,
        edinet_list,
        selected=selected,
    )
    _list_out, _cases_out = publish_tob_outputs(
        output_dir,
        other,
        cases,
        self_list_rows=issuer,
        self_case_rows=issuer_cases,
        **publish_context_from_meta(output_dir),
    )
    print(f"処理書類: {processed} fields={args.fields}（自社株のみ）")
    print(f"自社株: {len(issuer)} docs / {len(issuer_cases)} cases")
    print(f"他社株: {len(other)} docs / {len(cases)} cases（変更なし）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
