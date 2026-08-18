#!/usr/bin/env python3
"""
tob_list.csv の各書類行について XBRL (type=5) から詳細を抽出し、
書類単位の列を埋めたうえで tob_cases.csv を再生成する。

流れ:
  1. tob_list.csv を読む
  2. 未抽出（または指定）の書類を提出日時順に処理
  3. documents/{docID}?type=5 で ZIP 取得 → CSV パース
  4. 書類自身のタクソノミ版を判定し、年度別 mapping で値を抽出
  5. 書類行を更新し、案件CSVは書類正本から派生させる
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from extract_fields import (
    clean_extracted_name,
    compute_holding_ratios,
    detect_mbo,
    extract_sponsor_from_purposes,
    extract_tender_offer_agent,
    extract_valuation_basis_section,
    extract_valuation_from_purposes,
    format_pct,
    judge_tob_result,
    parse_holding_pct_from_text,
    parse_period_dates,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_valuation_from_sources,
    summarize_price,
)
from output_store import load_all_list_rows, publish_context_from_meta, publish_tob_outputs
from edinet_code_list import DEFAULT_CACHE_PATH, ensure_edinet_code_list
from taxonomy import TaxonomyCatalog, resolve_taxonomy_year
from tob_common import (
    ANSWER_SIDE,
    DOC_TYPE_TO_TAXONOMY,
    FILING_SIDE,
    OPINION_SIDE,
    REPORT_SIDE,
    WITHDRAW_SIDE,
    apply_name_fallbacks,
    columns_for_enrich_groups,
    parse_enrich_groups,
    partition_issuer_tenders,
    prepare_pipeline_rows,
    should_update_field,
)

PURPOSES_RAW_LIMIT = 15000

DOC_API = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
AMENDMENT_TYPES = {"250", "260", "280", "300", "320"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_document_zip(doc_id: str, api_key: str, cache_dir: Path, force: bool) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{doc_id}.zip"
    if out.exists() and not force:
        return out
    query = urllib.parse.urlencode({"type": "5", "Subscription-Key": api_key})
    url = f"{DOC_API.format(doc_id=doc_id)}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            out.write_bytes(resp.read())
        return out
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code} for {doc_id}", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  download failed {doc_id}: {exc}", file=sys.stderr)
        return None


def parse_xbrl_csv_from_zip(zip_path: Path) -> tuple[dict[str, list[str]], str]:
    """Return (element_id -> values, concatenated zip text for taxonomy detection)."""
    facts: dict[str, list[str]] = {}
    zip_text_parts: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        zip_text_parts.extend(zf.namelist())
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            return facts, "\n".join(zip_text_parts)
        raw = zf.read(csv_names[0])
    text = None
    for enc in ("utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return facts, "\n".join(zip_text_parts)
    zip_text_parts.append(text[:4000])

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader, None)
    for row in reader:
        if len(row) < 9:
            continue
        elem = row[0].strip().strip('"')
        val = row[8].strip().strip('"')
        if not elem or val in ("", "－", "-", "―"):
            continue
        facts.setdefault(elem, []).append(val)
    return facts, "\n".join(zip_text_parts)


def first_fact(facts: dict[str, list[str]], element_ids: list[str]) -> tuple[str, str]:
    for eid in element_ids:
        vals = facts.get(eid)
        if vals:
            for val in vals:
                if val and val not in ("－", "-", "―"):
                    return val, eid
    return "", ""


def parse_opinion_stance(text: str) -> str:
    if not text:
        return ""
    if "反対" in text and "賛同" not in text:
        return "反対"
    if "賛同" in text:
        return "賛同"
    if "意見留保" in text or "留保" in text:
        return "意見留保"
    if "中立" in text:
        return "中立"
    return "要確認"


def summarize_text(text: str, limit: int = 300) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())[:limit]


def expected_fields_for_type(type_code: str) -> tuple[str, ...]:
    if type_code in FILING_SIDE:
        return ("OfferPrice", "OfferPeriodStart", "OfferPeriodEnd", "ExistingHoldingRatio")
    if type_code in OPINION_SIDE:
        return ("OpinionStance",)
    if type_code in REPORT_SIDE:
        return ("FinalResultNote", "OfferPeriodStart")
    if type_code in WITHDRAW_SIDE:
        return ("FinalResultNote",)
    if type_code in ANSWER_SIDE:
        return ("ResponseNote",)
    return ()


def compute_doc_status(row: dict, extracted_ok: bool) -> str:
    if (row.get("XbrlFlag") or "").strip() == "0":
        return "skipped"
    if not extracted_ok:
        return "failed"
    expected = expected_fields_for_type(row.get("DocTypeCode") or "")
    filled = sum(1 for key in expected if row.get(key))
    if expected and filled == 0:
        return "partial"
    if filled >= 1:
        return "done"
    return "partial"


def apply_names(row: dict, facts: dict[str, list[str]], fields: dict, selected: frozenset[str] | None) -> None:
    offeror, _ = first_fact(facts, fields.get("offeror_name", []))
    target, _ = first_fact(facts, fields.get("target_name", []))
    if should_update_field("OfferorName", selected) and offeror:
        row["OfferorName"] = clean_extracted_name(offeror.split("\n")[0])
    if should_update_field("TargetName", selected) and target:
        row["TargetName"] = clean_extracted_name(target.split("\n")[0])


def apply_holdings(row: dict, facts: dict[str, list[str]], fields: dict, selected: frozenset[str] | None) -> None:
    if selected is not None and not selected & {
        "ExistingHoldingRatio",
        "ExistingHoldingRatioElement",
        "SpecialRelatedHoldingRatio",
        "AfterPurchaseRatio",
        "AfterPurchaseRatioElement",
    }:
        return
    offeror_votes, existing_eid = first_fact(facts, fields.get("offeror_voting_rights", []))
    special_votes, _ = first_fact(facts, fields.get("special_voting_rights", []))
    total_votes, _ = first_fact(facts, fields.get("total_voting_rights", []))
    existing, special, _ = compute_holding_ratios(offeror_votes, special_votes, total_votes)
    if should_update_field("ExistingHoldingRatio", selected) and existing:
        row["ExistingHoldingRatio"] = existing
        row["ExistingHoldingRatioElement"] = existing_eid
    if should_update_field("SpecialRelatedHoldingRatio", selected) and special:
        row["SpecialRelatedHoldingRatio"] = special
    if should_update_field("ExistingHoldingRatio", selected) and not row.get("ExistingHoldingRatio"):
        holding_text, holding_eid = first_fact(facts, fields.get("existing_holding_text", []))
        parsed = parse_holding_pct_from_text(holding_text)
        if parsed:
            row["ExistingHoldingRatio"] = parsed
            row["ExistingHoldingRatioElement"] = holding_eid
    if should_update_field("SpecialRelatedHoldingRatio", selected) and not row.get("SpecialRelatedHoldingRatio"):
        special_text, _ = first_fact(facts, fields.get("special_holding_text", []))
        parsed = parse_holding_pct_from_text(special_text)
        if parsed:
            row["SpecialRelatedHoldingRatio"] = parsed
    after, after_eid = first_fact(
        facts,
        fields.get("after_purchase_ratio", []) or fields.get("ownership_ratio", []),
    )
    if should_update_field("AfterPurchaseRatio", selected) and after:
        row["AfterPurchaseRatio"] = format_pct(after)
        row["AfterPurchaseRatioElement"] = after_eid


def apply_facts_to_row(
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
        purposes_text, purposes_eid = first_fact(facts, fields.get("purposes_text", []))
        overview_text, overview_eid = first_fact(facts, fields.get("overview_text", []))
        intended_text, intended_eid = first_fact(facts, fields.get("intended_purchase_text", []))
        fund_text, fund_eid = first_fact(facts, fields.get("fund_text", []))
        application_text, application_eid = first_fact(facts, fields.get("application_text", []))
        agent_name, agent_eid = first_fact(facts, fields.get("agent_name", []))
        start, end = parse_period_dates(period_text)
        if should_update_field("OfferPriceRaw", selected) and price_text:
            row["OfferPriceRaw"] = price_text[:5000]
            row["OfferPrice"] = summarize_price(price_text)
            row["OfferPriceElement"] = price_eid
            if should_update_field("ValuationBasisRaw", selected):
                basis = extract_valuation_basis_section(price_text)
                if basis:
                    row["ValuationBasisRaw"] = basis[:2500]
        if should_update_field("OfferPeriodRaw", selected) and period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if should_update_field("PurposesRaw", selected) and purposes_text:
            row["PurposesRaw"] = purposes_text[:PURPOSES_RAW_LIMIT]
            row["PurposesElement"] = purposes_eid
        if should_update_field("OverviewRaw", selected) and overview_text:
            row["OverviewRaw"] = overview_text[:2000]
            row["OverviewElement"] = overview_eid
        if selected is None or selected & {
            "ValuationMarketMin",
            "ValuationMarketMax",
            "ValuationComparableMin",
            "ValuationComparableMax",
            "ValuationDCFMin",
            "ValuationDCFMax",
            "ValuationBasisRaw",
        }:
            valuation = parse_valuation_from_sources(price_text, purposes_text, overview_text)
            if any(valuation.values()):
                row.update(valuation)
            elif should_update_field("ValuationBasisRaw", selected):
                purposes_basis = extract_valuation_from_purposes(purposes_text)
                if purposes_basis and not row.get("ValuationBasisRaw"):
                    row["ValuationBasisRaw"] = purposes_basis[:2500]
        sponsor_source = purposes_text or overview_text
        if should_update_field("SponsorHint", selected) and sponsor_source:
            row["SponsorHint"] = extract_sponsor_from_purposes(sponsor_source)
        if should_update_field("IsMBO", selected):
            row["IsMBO"] = detect_mbo([purposes_text, overview_text])
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
        apply_holdings(row, facts, fields, selected)

    if type_code in OPINION_SIDE or tax_key == "pst":
        opinion_text, opinion_eid = first_fact(facts, fields.get("opinion_text", []))
        if should_update_field("OpinionRaw", selected) and opinion_text:
            row["OpinionRaw"] = opinion_text[:1000]
            row["OpinionStance"] = parse_opinion_stance(opinion_text)
            row["OpinionElement"] = opinion_eid
            if should_update_field("IsMBO", selected) and not row.get("IsMBO"):
                row["IsMBO"] = detect_mbo([opinion_text])

    if type_code in REPORT_SIDE or tax_key == "tor":
        period_text, period_eid = first_fact(facts, fields.get("period_text", []))
        result_text, result_eid = first_fact(facts, fields.get("final_result_text", []))
        start, end = parse_period_dates(period_text)
        if should_update_field("OfferPeriodRaw", selected) and period_text:
            row["OfferPeriodRaw"] = period_text[:1000]
            row["OfferPeriodStart"] = start
            row["OfferPeriodEnd"] = end
            row["OfferPeriodElement"] = period_eid
        if should_update_field("FinalResultRaw", selected) and result_text:
            row["FinalResultRaw"] = result_text[:1000]
            row["FinalResultNote"] = judge_tob_result(result_text)
            row["FinalResultElement"] = result_eid
        apply_holdings(row, facts, fields, selected)

    if type_code in WITHDRAW_SIDE or tax_key == "wto":
        if should_update_field("FinalResultNote", selected):
            row["FinalResultNote"] = "撤回"
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

    if type_code in ANSWER_SIDE or tax_key == "toa":
        response_text, response_eid = first_fact(facts, fields.get("response_text", []))
        if should_update_field("ResponseRaw", selected) and response_text:
            row["ResponseRaw"] = response_text[:1000]
            row["ResponseNote"] = summarize_text(response_text)
            row["ResponseElement"] = response_eid


def parent_taxonomy_year(row: dict, by_id: dict[str, dict]) -> str:
    parent_id = (row.get("ParentDocID") or "").strip()
    parent = by_id.get(parent_id) if parent_id else None
    if parent:
        return (parent.get("TaxonomyYear") or "").strip()
    return ""


def enrich_document(
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
    )
    mapping = catalog.mapping_for_year(year)
    row["TaxonomyYear"] = year
    row["TaxonomyDate"] = tax_date or str(mapping.get("taxonomy_date") or "")
    row["TaxonomySource"] = source
    apply_facts_to_row(row, facts, mapping, selected=selected)
    apply_name_fallbacks(row)
    row["ExtractionStatus"] = compute_doc_status(row, extracted_ok=True)


def pending_status(status: str) -> bool:
    return status not in {"done", "partial", "skipped"}


def enrich_documents(
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
        print(f"enrich {doc_id} type={row.get('DocTypeCode')}", flush=True)
        enrich_document(row, catalog, by_id, api_key, cache_dir, force, sleep, selected=selected)
        processed += 1
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="TOB書類CSVをXBRLから詳細化する")
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
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument(
        "--recompute-only",
        action="store_true",
        help="APIを使わず、既存の Raw 列から価格要約・成否・案件の買付後割合を再計算する",
    )
    parser.add_argument(
        "--fields",
        default="all",
        help=(
            "更新する列グループ（カンマ区切り）。"
            "all / basic / valuation / planned_shares / fund / sponsor / agent / holdings / opinion / result"
        ),
    )
    args = parser.parse_args()
    enrich_groups = parse_enrich_groups(args.fields)
    selected = columns_for_enrich_groups(enrich_groups)

    output_dir = Path(args.output_dir)
    edinet_list = ensure_edinet_code_list(Path(args.edinet_cache))
    rows = load_all_list_rows(output_dir)
    if not rows:
        print("tob_list.csv がありません。先に fetch_tob.py を実行してください。", file=sys.stderr)
        return 1

    if args.recompute_only:
        other, cases, issuer, issuer_cases = prepare_pipeline_rows(
            rows,
            edinet_list,
            selected=selected,
        )
        list_out, _cases_out = publish_tob_outputs(
            output_dir,
            other,
            cases,
            self_list_rows=issuer,
            self_case_rows=issuer_cases,
            **publish_context_from_meta(output_dir),
        )
        print(f"既存Rawから再計算（APIなし） fields={args.fields}")
        print(f"他社株: {list_out} ({len(other)} docs / {len(cases)} cases)")
        print(f"自社株: {len(issuer)} docs / {len(issuer_cases)} cases")
        return 0

    api_key = os.environ.get("EDINET_API_KEY", "").strip()
    if not api_key:
        print("EDINET_API_KEY が必要です", file=sys.stderr)
        return 1

    other, issuer = partition_issuer_tenders(rows)
    other.sort(key=lambda r: (r.get("SubmitDateTime") or "", r.get("DocTypeCode") or "", r.get("DocID") or ""))
    catalog = TaxonomyCatalog(Path(args.taxonomy_dir))
    processed = enrich_documents(
        other,
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
    list_out, cases_out = publish_tob_outputs(
        output_dir,
        other,
        cases,
        self_list_rows=issuer,
        self_case_rows=issuer_cases,
        **publish_context_from_meta(output_dir),
    )
    print(f"処理書類: {processed} fields={args.fields}（自社株 {len(issuer)} 件は他社株CSVから除外）")
    print(f"他社株: {list_out} ({len(other)} docs / {len(cases)} cases)")
    print(f"自社株: {len(issuer)} docs / {len(issuer_cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
