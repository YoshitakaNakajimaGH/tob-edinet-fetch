#!/usr/bin/env python3
"""Run fetch + GPT extract for one case, or process the next pending queue row."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.tob_common import read_csv, write_csv

LAB_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
QUEUE_CSV = LAB_ROOT / "cases" / "queue.csv"
DEFAULT_CASES = ROOT / "output" / "current" / "tob_cases.csv"

QUEUE_FIELDS = ["CaseID", "OfferorName", "TargetName", "Status", "LastRunAt", "Model", "Notes"]


def run_script(name: str, *args: str) -> int:
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def seed_queue(limit: int, cases_csv: Path) -> None:
    cases = read_csv(cases_csv)
    existing = {(r.get("CaseID") or "").strip() for r in read_csv(QUEUE_CSV)}
    rows = read_csv(QUEUE_CSV)
    added = 0
    for case in cases:
        case_id = (case.get("CaseID") or "").strip()
        if not case_id or case_id in existing:
            continue
        rows.append(
            {
                "CaseID": case_id,
                "OfferorName": case.get("OfferorName") or "",
                "TargetName": case.get("TargetName") or "",
                "Status": "pending",
                "LastRunAt": "",
                "Model": "",
                "Notes": "",
            }
        )
        existing.add(case_id)
        added += 1
        if added >= limit:
            break
    write_csv(QUEUE_CSV, rows, QUEUE_FIELDS)
    print(f"Seeded {added} cases into {QUEUE_CSV}")


def next_pending() -> dict | None:
    for row in read_csv(QUEUE_CSV):
        if (row.get("Status") or "").strip() == "pending":
            return row
    return None


def update_queue(case_id: str, status: str, model: str = "", notes: str = "") -> None:
    rows = read_csv(QUEUE_CSV)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        if (row.get("CaseID") or "").strip() == case_id:
            row["Status"] = status
            row["LastRunAt"] = now
            if model:
                row["Model"] = model
            if notes:
                row["Notes"] = notes
    write_csv(QUEUE_CSV, rows, QUEUE_FIELDS)


def clean_pdfs(case_id: str, pdf_dir: Path) -> None:
    target = pdf_dir / case_id
    if not target.exists():
        return
    for pdf in target.glob("*.pdf"):
        pdf.unlink()
    try:
        target.rmdir()
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PDFs and GPT-extract one TOB case")
    parser.add_argument("--case-id", help="CaseID to process")
    parser.add_argument("--from-queue", action="store_true", help="Process next pending queue row")
    parser.add_argument("--seed-queue", type=int, metavar="N", help="Add N cases from tob_cases.csv")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--clean-pdfs", action="store_true", help="Delete PDFs after successful extract")
    parser.add_argument("--cases-csv", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()

    if args.seed_queue:
        seed_queue(args.seed_queue, args.cases_csv)
        return 0

    case_id = args.case_id
    if args.from_queue:
        row = next_pending()
        if not row:
            print("No pending cases in queue")
            return 0
        case_id = row.get("CaseID") or ""

    if not case_id:
        parser.error("Specify --case-id or --from-queue")

    rc = run_script("fetch_case_pdfs.py", "--case-id", case_id)
    if rc != 0:
        update_queue(case_id, "failed", notes="fetch failed")
        return rc

    rc = run_script("run_gpt_extract.py", "--case-id", case_id, "--model", args.model)
    if rc != 0:
        update_queue(case_id, "failed", notes="gpt extract failed")
        return rc

    update_queue(case_id, "done", model=args.model)
    if args.clean_pdfs:
        clean_pdfs(case_id, LAB_ROOT / "pdfs")
        print(f"Cleaned PDFs for {case_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
