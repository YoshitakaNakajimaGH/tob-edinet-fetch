#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edinet.edinet_code_list import load_edinet_code_list
from tob.sponsor_hint_llm import (
    build_sponsor_hint_prompt,
    collect_case_text_bundle,
    finalize_llm_sponsor_hint,
    load_sponsor_hint_llm_overlay,
    resolve_case_sponsor_hint_with_llm,
    save_sponsor_hint_llm_overlay,
)
from tob.tob_common import build_cases, normalize_doc_row

FIXTURE = ROOT / "tests" / "fixtures" / "edinet_code_min.csv"


class SponsorHintLlmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edinet = load_edinet_code_list(FIXTURE)

    def test_finalize_pe_fund(self) -> None:
        hint = finalize_llm_sponsor_hint(
            {
                "sponsor_type": "pe_fund",
                "sponsor_name": "The Carlyle Group",
            },
            offeror_name="Keystone Investment Holdings, L.P.",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "The Carlyle Group")

    def test_finalize_offeror_direct_listed(self) -> None:
        hint = finalize_llm_sponsor_hint(
            {
                "sponsor_type": "offeror_direct",
                "sponsor_name": "",
            },
            offeror_name="株式会社ダイセキ",
            offeror_edinet_code="E04931",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "9793")

    def test_finalize_unlisted_spv(self) -> None:
        hint = finalize_llm_sponsor_hint(
            {"sponsor_type": "unlisted_spv", "sponsor_name": ""},
            offeror_name="Bidco KK",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "非上場")

    def test_finalize_rejects_bank_name(self) -> None:
        hint = finalize_llm_sponsor_hint(
            {
                "sponsor_type": "listed_company",
                "sponsor_name": "株式会社みずほ銀行",
            },
            offeror_name="Some BidCo KK",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "")

    def test_collect_case_text_bundle(self) -> None:
        docs = [
            normalize_doc_row(
                {
                    "CaseID": "S100TEST",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2024-01-01",
                    "PurposesRaw": "（１）【本公開買付の概要】公開買付者は、テスト株式会社です。",
                    "OverviewRaw": "",
                }
            )
        ]
        bundle = collect_case_text_bundle(docs)
        self.assertIn("PurposesRaw", bundle)
        self.assertIn("テスト株式会社", bundle)

    def test_build_prompt_contains_metadata(self) -> None:
        prompt = build_sponsor_hint_prompt(
            case_id="S100TEST",
            offeror_name="Offeror KK",
            target_name="Target KK",
            text_bundle="sample text",
        )
        self.assertIn("S100TEST", prompt)
        self.assertIn("Offeror KK", prompt)
        self.assertIn("sponsor_type", prompt)

    def test_sidecar_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidecar.json"
            save_sponsor_hint_llm_overlay(
                {"S100TEST": {"SponsorHintLLM": "KKR", "SponsorHintRule": ""}},
                path,
                model="gemini-3.6-flash",
            )
            loaded = load_sponsor_hint_llm_overlay(path)
            self.assertEqual(loaded["S100TEST"]["SponsorHintLLM"], "KKR")

    def test_build_cases_prefers_llm_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_path = Path(tmp) / "sponsor_hint_llm.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "cases": {
                            "S100TEST": {
                                "SponsorHintLLM": "The Carlyle Group",
                                "SponsorHintRule": "",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from tob import sponsor_hint_llm as shm

            original = shm.DEFAULT_SIDECAR_PATH
            shm.DEFAULT_SIDECAR_PATH = sidecar_path
            try:
                rows = [
                    normalize_doc_row(
                        {
                            "CaseID": "S100TEST",
                            "DocTypeCode": "240",
                            "SubmitDateTime": "2024-01-01",
                            "FilerName": "Keystone Investment Holdings, L.P.",
                            "OfferorName": "Keystone Investment Holdings, L.P.",
                            "PurposesRaw": (
                                "（１）【本公開買付の概要】"
                                "The Carlyle Groupが運用するファンドの公開買付者です。"
                            ),
                        }
                    )
                ]
                cases = build_cases(rows, self.edinet)
                self.assertEqual(len(cases), 1)
                self.assertEqual(cases[0]["SponsorHint"], "The Carlyle Group")
            finally:
                shm.DEFAULT_SIDECAR_PATH = original

    def test_resolve_with_llm_entry(self) -> None:
        docs = [
            normalize_doc_row(
                {
                    "CaseID": "S100TEST",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2024-01-01",
                    "OfferorName": "Keystone Investment Holdings, L.P.",
                    "PurposesRaw": "The Carlyle Groupが運用するファンドです。",
                }
            )
        ]
        hint = resolve_case_sponsor_hint_with_llm(
            docs,
            self.edinet,
            {"SponsorHintLLM": "KKR"},
        )
        self.assertEqual(hint, "KKR")


if __name__ == "__main__":
    unittest.main()
