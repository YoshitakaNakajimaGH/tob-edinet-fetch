#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edinet.edinet_code_list import EdinetCodeList, load_edinet_code_list
from tob.extract_fields import (
    UNLISTED_LABEL,
    extract_pe_sponsor_name,
    extract_sponsor_from_purposes,
    is_fund_offeror,
    is_acceptable_sponsor_name,
    offer_overview_window,
    resolve_sponsor_hint,
    sanitize_sponsor_name,
)
from tob.tob_common import assign_case_ids, build_cases, normalize_doc_row, resolve_case_sponsor_hint

FIXTURE = ROOT / "tests" / "fixtures" / "edinet_code_min.csv"


class SponsorHintInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edinet = load_edinet_code_list(FIXTURE)

    def test_pe_fund_returns_sponsor_name(self) -> None:
        text = (
            "（１）本公開買付の概要\n"
            "公開買付者は、ケイマン諸島法に基づくリミテッド・パートナーシップです。\n"
            "The Carlyle Group（以下「カーライル」といいます。）がその持分の全てを保有・運用しております。"
        )
        self.assertTrue(is_fund_offeror("Keystone Investment Holdings, L.P.", purposes_raw=text))
        self.assertEqual(
            resolve_sponsor_hint(
                offeror_name="Keystone Investment Holdings, L.P.",
                purposes_raw=text,
            ),
            "The Carlyle Group",
        )

    def test_listed_offeror_returns_sec_code(self) -> None:
        hint = resolve_sponsor_hint(
            offeror_name="株式会社ダイセキ",
            offeror_edinet_code="E04931",
            purposes_raw="（１）本公開買付の概要 公開買付者は、対象者株式の取得を目的とします。",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "9793")

    def test_unlisted_offeror_returns_label(self) -> None:
        hint = resolve_sponsor_hint(
            offeror_name="株式会社ライトオン",
            offeror_edinet_code="E03240",
            purposes_raw="（１）本公開買付の概要 公開買付者は、対象者株式の取得を目的とします。",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, UNLISTED_LABEL)

    def test_mbo_spv_returns_unlisted(self) -> None:
        opinion = (
            "公開買付者は、対象者の代表取締役社長である山田弘直氏が、"
            "公開買付者の発行済株式の全部を所有し、かつ、代表取締役を務めているとのことです。"
        )
        hint = resolve_sponsor_hint(
            offeror_name="山田マーケティング株式会社",
            purposes_raw="（１）本公開買付の概要 公開買付者は、2021年４月28日付で設立された株式会社です。",
            opinion_raw=opinion,
            is_mbo="Yes",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, UNLISTED_LABEL)

    def test_blocklist_tse_not_used(self) -> None:
        text = "公開買付者は、株式会社東京証券取引所市場第一部に上場している対象者株式を取得します。"
        self.assertEqual(
            resolve_sponsor_hint(
                offeror_name="Some BidCo KK",
                purposes_raw=text,
                edinet_list=self.edinet,
            ),
            "",
        )

    def test_overview_window_ignores_later_name_drops(self) -> None:
        text = (
            "（１）本公開買付けの概要\n"
            "公開買付者は、SBIHDグループの完全子会社です。\n"
            "（２）本公開買付けの背景\n"
            "社外取締役の出身母体にゴールドマン・サックス証券株式会社がある。"
            "日本工業規格（ＪＩＳ規格）に準拠する。Optia Partners株式会社の株式を取得した。"
        )
        window = offer_overview_window(text)
        self.assertIn("SBIHD", window)
        self.assertNotIn("ゴールドマン", window)
        self.assertEqual(extract_pe_sponsor_name(text), "")

    def test_extract_pe_sponsor_bain(self) -> None:
        text = "ベインキャピタルは、本公開買付けを通じて対象者株式の非公開化を企図しております。"
        self.assertEqual(extract_pe_sponsor_name(text), "Bain Capital")

    def test_extract_pe_sponsor_goldman_sachs(self) -> None:
        text = "ザ・ゴールドマン・サックス・グループ・インク（以下「ゴールドマン・サックス」といいます。）"
        self.assertEqual(extract_pe_sponsor_name(text), "Goldman Sachs")

    def test_extract_pe_sponsor_advantage_partners(self) -> None:
        text = "株式会社アドバンテッジパートナーズ（以下「AP」といいます。）が投資関連サービスを提供"
        self.assertEqual(extract_pe_sponsor_name(text), "Advantage Partners")

    def test_parent_company_full_parent_pattern(self) -> None:
        from tob.extract_fields import extract_parent_company_name

        text = "公開買付者の完全親会社である日本郵便は対象者株式を所有しておりません"
        self.assertEqual(extract_parent_company_name(text), "日本郵便")

    def test_sanitize_rejects_narrative_fragment(self) -> None:
        self.assertFalse(is_acceptable_sponsor_name("本件両公開買付けに関連して、公開買付者"))
        self.assertFalse(is_acceptable_sponsor_name("今般、公開買付者"))
        self.assertEqual(sanitize_sponsor_name("XYZGroup,L.P.(以下「本ファンド"), "XYZGroup,L.P.")

    def test_extract_sponsor_from_purposes_rejects_narrative(self) -> None:
        text = (
            "（１）本件両公開買付けの概要\n"
            "本件両公開買付けに関連して、公開買付者は、Fortress Investment Group LLCの関係法人です。"
        )
        self.assertEqual(extract_sponsor_from_purposes(text), "")

    def test_ontario_resolves_fortress_not_narrative(self) -> None:
        purposes = (
            "（１）本件両公開買付けの概要\n"
            "公開買付者は、FIG及びそのグループ（以下「Fortress」といいます。）の関係法人である"
            "Ontario Holdings I LLCが出資をしております。"
        )
        hint = resolve_sponsor_hint(
            offeror_name="Ｏｎｔａｒｉｏ合同会社",
            purposes_raw=purposes,
        )
        self.assertEqual(hint, "Fortress Investment Group")

    def test_sbi_parent_resolves_listed_sec_code(self) -> None:
        purposes = (
            "（１）本公開買付けの概要\n"
            "公開買付者の完全親会社であるSBIHDは、対象者株式を所有する筆頭株主です。"
        )
        hint = resolve_sponsor_hint(
            offeror_name="SBI地銀ホールディングス株式会社",
            purposes_raw=purposes,
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "8473")

    def test_listed_strategic_not_treated_as_fund(self) -> None:
        purposes = (
            "（１）本公開買付の概要 公開買付者は出光興産株式会社です。"
            "公開買付者は、対象者を完全子会社化するため本公開買付けを実施します。"
        )
        hint = resolve_sponsor_hint(
            offeror_name="出光興産株式会社",
            offeror_edinet_code="E01084",
            purposes_raw=purposes,
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, "5019")

    def test_name_lookup_unlisted_when_edinet_code_empty(self) -> None:
        hint = resolve_sponsor_hint(
            offeror_name="株式会社ツクイホールディングス",
            offeror_edinet_code="E36390",
            purposes_raw="（１）本公開買付の概要 公開買付者は対象者の親会社です。",
            edinet_list=self.edinet,
        )
        self.assertEqual(hint, UNLISTED_LABEL)

    def test_case_level_resolution(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-01-10 10:00",
                    "FilerName": "株式会社ダイセキ",
                    "FilerEdinetCode": "E04931",
                    "SubjectEdinetCode": "E33382",
                    "PurposesRaw": "（１）本公開買付の概要 公開買付者は、対象者株式の取得を目的とします。",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100OPN",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "290",
                    "SubmitDateTime": "2025-01-20 10:00",
                    "OpinionRaw": "意見表明",
                }
            ),
        ]
        assign_case_ids(rows)
        case = build_cases(rows, self.edinet)[0]
        self.assertEqual(case["SponsorHint"], "9793")
        self.assertEqual(resolve_case_sponsor_hint(rows, self.edinet), "9793")


if __name__ == "__main__":
    unittest.main()
