#!/usr/bin/env python3
"""Rewrite current CSV document links to EDINET PDF URLs."""

from __future__ import annotations

import argparse
from pathlib import Path

from edinet.edinet_code_list import ensure_edinet_code_list
from tob.output_store import (
    CASES_STEM,
    LIST_STEM,
    SELF_CASES_STEM,
    SELF_LIST_STEM,
    current_path,
    load_all_list_rows,
)
from tob.tob_common import (
    CASE_FIELDS,
    LIST_FIELDS,
    SELF_CASE_FIELDS,
    SELF_LIST_FIELDS,
    prepare_pipeline_rows,
    write_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="output", help="output root (current/*.csv)")
    args = parser.parse_args()

    root = Path(args.output_dir)
    rows = load_all_list_rows(root)
    if not rows:
        print("No list rows found.")
        return 0

    edinet = ensure_edinet_code_list()
    other, cases, issuer, self_cases = prepare_pipeline_rows(rows, edinet)

    write_csv(current_path(root, LIST_STEM), other, LIST_FIELDS)
    write_csv(current_path(root, CASES_STEM), cases, CASE_FIELDS)
    write_csv(current_path(root, SELF_LIST_STEM), issuer, SELF_LIST_FIELDS)
    write_csv(current_path(root, SELF_CASES_STEM), self_cases, SELF_CASE_FIELDS)

    print(
        f"Updated PDF URLs: tob_list={len(other)}, tob_cases={len(cases)}, "
        f"self_tob_list={len(issuer)}, self_tob_cases={len(self_cases)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
