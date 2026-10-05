#!/usr/bin/env python3
"""Replay a filing-rooted document list from a local list CSV.

This does not call EDINET. A from-scratch run is
`fetch_from_api.py`, which downloads documents.json and then uses
`collect()` below. Related documents are those whose ParentDocID chain
leads back to a doc type 240 filing.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_dt(value: str) -> datetime | None:
    text = (value or "").strip()
    for fmt, size in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def collect(rows: list[dict], *, month: str, within_days: int) -> list[dict]:
    children: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        parent = (row.get("ParentDocID") or "").strip()
        if parent:
            children[parent].append(row)

    def descendants(root_id: str) -> list[dict]:
        found: list[dict] = []
        seen: set[str] = set()
        stack = [root_id]
        while stack:
            parent = stack.pop()
            for child in children.get(parent, []):
                doc_id = child.get("DocID") or ""
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                found.append(child)
                stack.append(doc_id)
        found.sort(key=lambda doc: doc.get("SubmitDateTime") or "")
        return found

    filings = [
        row
        for row in rows
        if row.get("DocTypeCode") == "240" and (row.get("SubmitDateTime") or "").startswith(month)
    ]
    filings.sort(key=lambda row: row.get("SubmitDateTime") or "")

    cases: list[dict] = []
    for root in filings:
        start = parse_dt(root.get("SubmitDateTime") or "")
        docs = [root, *descendants(root.get("DocID") or "")]
        kept = []
        for doc in docs:
            submitted = parse_dt(doc.get("SubmitDateTime") or "")
            if start and submitted and (submitted - start).days > within_days:
                continue
            kept.append(doc)
        type_counts: dict[str, int] = defaultdict(int)
        for doc in kept:
            type_counts[doc.get("DocTypeCode") or ""] += 1
        cases.append(
            {
                "case_id": root.get("DocID") or "",
                "filing_date": (root.get("SubmitDateTime") or "")[:10],
                "offeror_name": root.get("OfferorName") or root.get("FilerName") or "",
                "target_name": root.get("TargetName") or "",
                "target_sec_code": root.get("TargetSecCode") or "",
                "offeror_edinet_code": root.get("FilerEdinetCode") or "",
                "target_edinet_code": root.get("SubjectEdinetCode") or "",
                "doc_count": len(kept),
                "type_counts": dict(type_counts),
                "has_outcome": any(doc.get("DocTypeCode") in {"260", "270", "280"} for doc in kept),
                "documents": [
                    {
                        "doc_id": doc.get("DocID") or "",
                        "doc_type_code": doc.get("DocTypeCode") or "",
                        "doc_type_name": doc.get("DocTypeName") or "",
                        "submit_date": (doc.get("SubmitDateTime") or "")[:10],
                        "parent_doc_id": doc.get("ParentDocID") or "",
                    }
                    for doc in kept
                ],
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-csv", default="output/current/tob_list.csv")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--within-days", type=int, default=183, help="Keep documents submitted within this many days of the filing")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with Path(args.list_csv).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cases = collect(rows, month=args.month, within_days=args.within_days)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with_outcome = sum(1 for case in cases if case["has_outcome"])
    print(f"{args.month}: {len(cases)} filings, {with_outcome} with an outcome document within {args.within_days} days")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
