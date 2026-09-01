#!/usr/bin/env python3
"""Run Gemini on enriched CSV text to infer SponsorHint for all TOB cases."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GPT_SCRIPTS = ROOT / "experiments" / "gpt-extract" / "scripts"
if str(GPT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GPT_SCRIPTS))

from edinet.edinet_code_list import ensure_edinet_code_list  # noqa: E402
from gemini_client import call_gemini_json  # noqa: E402
from llm_common import resolve_gemini_api_key  # noqa: E402
from llm_common import DEFAULT_GEMINI_MODEL  # noqa: E402
from tob.sponsor_hint_llm import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    build_sponsor_hint_prompt,
    case_rule_hint,
    collect_case_text_bundle,
    finalize_llm_sponsor_hint,
    load_sponsor_hint_llm_overlay,
    save_sponsor_hint_llm_overlay,
)
from tob.tob_common import CASE_FIELDS, read_csv, write_csv  # noqa: E402

LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "output" / "current" / "tob_cases.csv"
DEFAULT_LIST = ROOT / "output" / "current" / "tob_list.csv"
DEFAULT_DIFF = LAB_ROOT / "output" / "sponsor_hint_diff.csv"
DEFAULT_SLEEP = 6.5  # ~9 RPM under free-tier Flash limits

DIFF_FIELDS = [
    "CaseID",
    "OfferorName",
    "TargetName",
    "SponsorHintRule",
    "SponsorHintLLM",
    "SponsorHintApplied",
    "Match",
    "SponsorType",
    "Confidence",
    "Reason",
    "Model",
    "ProcessedAt",
]


def group_docs_by_case(list_csv: Path) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in read_csv(list_csv):
        case_id = (row.get("CaseID") or "").strip()
        if case_id:
            groups[case_id].append(row)
    return groups


def pick_cases(
    *,
    cases_csv: Path,
    list_csv: Path,
    only_blank: bool,
    only_diff: bool,
    sidecar: dict[str, dict],
    case_id: str,
) -> list[dict]:
    cases = read_csv(cases_csv)
    docs_by_case = group_docs_by_case(list_csv)
    edinet = ensure_edinet_code_list()

    selected: list[dict] = []
    for row in cases:
        cid = (row.get("CaseID") or "").strip()
        if not cid:
            continue
        if case_id and cid != case_id:
            continue
        docs = docs_by_case.get(cid, [])
        if not docs:
            continue
        rule_hint = case_rule_hint(docs, edinet)
        current_hint = (row.get("SponsorHint") or "").strip()
        if only_blank and current_hint:
            continue
        existing = sidecar.get(cid, {})
        if only_diff and existing.get("SponsorHintLLM"):
            llm_hint = (existing.get("SponsorHintLLM") or "").strip()
            if llm_hint == rule_hint:
                continue
        selected.append(
            {
                "case_row": row,
                "docs": docs,
                "rule_hint": rule_hint,
            }
        )
    return selected


def apply_to_cases_csv(cases_csv: Path, sidecar: dict[str, dict]) -> int:
    rows = read_csv(cases_csv)
    updated = 0
    for row in rows:
        cid = (row.get("CaseID") or "").strip()
        entry = sidecar.get(cid) or {}
        llm_hint = (entry.get("SponsorHintLLM") or "").strip()
        if llm_hint:
            row["SponsorHint"] = llm_hint
            updated += 1
    if updated:
        fieldnames = list(rows[0].keys()) if rows else CASE_FIELDS
        write_csv(cases_csv, rows, fieldnames)
    return updated


def run(args: argparse.Namespace) -> int:
    sidecar_path = Path(args.sidecar)
    sidecar = load_sponsor_hint_llm_overlay(sidecar_path)
    selected = pick_cases(
        cases_csv=Path(args.cases_csv),
        list_csv=Path(args.list_csv),
        only_blank=args.only_blank,
        only_diff=args.only_diff,
        sidecar=sidecar,
        case_id=(args.case_id or "").strip(),
    )
    if args.limit:
        selected = selected[args.offset : args.offset + args.limit]

    if not selected:
        print("No cases selected.")
        return 0

    api_key = resolve_gemini_api_key()
    if not api_key and not args.dry_run:
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 1

    edinet = ensure_edinet_code_list()
    diff_rows: list[dict] = []
    processed = 0

    for item in selected:
        row = item["case_row"]
        docs = item["docs"]
        cid = row["CaseID"]
        offeror = row.get("OfferorName") or ""
        target = row.get("TargetName") or ""
        offeror_code = row.get("OfferorEdinetCode") or ""
        rule_hint = item["rule_hint"]
        text_bundle = collect_case_text_bundle(docs, max_chars=args.max_chars)

        if not text_bundle.strip():
            print(f"{cid}: skip (no text)")
            continue

        prompt = build_sponsor_hint_prompt(
            case_id=cid,
            offeror_name=offeror,
            target_name=target,
            text_bundle=text_bundle,
        )

        llm_raw: dict = {}
        llm_hint = ""
        if args.dry_run:
            print(f"{cid}: dry-run ({len(text_bundle)} chars, rule={rule_hint!r})")
        else:
            llm_raw = call_gemini_json(
                prompt=prompt,
                api_key=api_key,
                model=args.model,
            )
            llm_hint = finalize_llm_sponsor_hint(
                llm_raw,
                offeror_name=offeror,
                offeror_edinet_code=offeror_code,
                edinet_list=edinet,
            )
            processed += 1
            if processed < len(selected):
                time.sleep(args.sleep)

        applied = llm_hint or rule_hint
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        sidecar[cid] = {
            "SponsorHintLLM": llm_hint,
            "SponsorHintRule": rule_hint,
            "sponsor_type": llm_raw.get("sponsor_type", ""),
            "sponsor_name": llm_raw.get("sponsor_name", ""),
            "confidence": llm_raw.get("confidence", ""),
            "reason": llm_raw.get("reason", ""),
            "model": args.model,
            "updated_at": now,
        }
        diff_rows.append(
            {
                "CaseID": cid,
                "OfferorName": offeror,
                "TargetName": target,
                "SponsorHintRule": rule_hint,
                "SponsorHintLLM": llm_hint,
                "SponsorHintApplied": applied,
                "Match": "Yes" if llm_hint == rule_hint else "No",
                "SponsorType": llm_raw.get("sponsor_type", ""),
                "Confidence": llm_raw.get("confidence", ""),
                "Reason": llm_raw.get("reason", ""),
                "Model": args.model if not args.dry_run else "",
                "ProcessedAt": now if not args.dry_run else "",
            }
        )
        if not args.dry_run:
            print(f"{cid}: rule={rule_hint!r} llm={llm_hint!r} type={llm_raw.get('sponsor_type')}")

    if not args.dry_run:
        save_sponsor_hint_llm_overlay(sidecar, sidecar_path, model=args.model)
        diff_path = Path(args.diff_csv)
        write_csv(diff_path, diff_rows, DIFF_FIELDS)
        print(f"Saved sidecar: {sidecar_path} ({len(sidecar)} cases)")
        print(f"Saved diff: {diff_path} ({len(diff_rows)} rows)")
        if args.apply_cases:
            count = apply_to_cases_csv(Path(args.cases_csv), sidecar)
            print(f"Updated tob_cases.csv SponsorHint for {count} cases")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-csv", default=str(DEFAULT_CASES))
    parser.add_argument("--list-csv", default=str(DEFAULT_LIST))
    parser.add_argument("--sidecar", default=str(DEFAULT_SIDECAR_PATH))
    parser.add_argument("--diff-csv", default=str(DEFAULT_DIFF))
    parser.add_argument("--case-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--only-blank", action="store_true")
    parser.add_argument("--only-diff", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-cases", action="store_true")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL)
    parser.add_argument("--max-chars", type=int, default=14_000)
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
