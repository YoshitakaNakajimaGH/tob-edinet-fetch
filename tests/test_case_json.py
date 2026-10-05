import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tob.case_json import (
    build_case_json,
    case_output_path,
    document_from_xbrl,
    documents_from_id_case,
    main,
    write_case_json,
)
from tob.taxonomy import TaxonomyCatalog
from tob.extract_fields import parse_board_opinion, parse_reference_market_price_details, parse_valuation_records


PRICE = (
    "普通株式1株につき、金955円"
    "本公開買付けの公表日の前営業日である2021年７月26日の東京証券取引所における"
    "対象者株式の終値(1,000円)、同日までの直近１ヶ月間、直近３ヶ月間及び直近６ヶ月間の"
    "終値単純平均値(980円、960円及び940円)の推移を参考にしました。"
    "算定の基礎 株式会社甲は、市場株価法：900円～1,000円、DCF法：1,100円～1,200円。"
)

AMENDED_PRICE = "普通株式1株につき、金1,050円"

OPINION_OPPOSE = "対象者は、本公開買付けに反対する旨の意見を表明する。"
OPINION_SUPPORT = "対象者は、本公開買付けに賛同する旨の意見を表明するとともに、応募することを推奨する。"

PLANNED = (
    "株券等の種類買付予定数買付予定数の下限買付予定数の上限"
    "普通株式2,517,495(株)―(株)―(株)合計2,517,495(株)―(株)―(株)"
    "上限及び下限を設定しておりません"
)

TWO_ADVISORS = (
    "株式会社Ａは、市場株価法：896円～1,071円、類似会社比較法：834円～1,432円、"
    "ＤＣＦ法：1,224円～1,436円と算定した。"
    "株式会社Ｂは、市場株価法：896円～1,071円、類似会社比較法：919円～1,361円、"
    "ＤＣＦ法：983円～1,453円と算定した。"
)


def _doc(**kwargs):
    base = {
        "docId": "S100AAAA",
        "docTypeCode": "240",
        "submitDate": "2026-03-02",
        "offerorName": "買付者株式会社",
        "targetName": "対象株式会社",
        "offerorEdinetCode": "E00001",
        "targetEdinetCode": "E00002",
        "texts": {},
        "numbers": {},
    }
    texts = dict(base["texts"])
    texts.update(kwargs.pop("texts", {}))
    numbers = dict(base["numbers"])
    numbers.update(kwargs.pop("numbers", {}))
    base.update(kwargs)
    base["texts"] = texts
    base["numbers"] = numbers
    return base


class RuleParserTests(unittest.TestCase):
    def test_board_opinion_labels(self) -> None:
        self.assertEqual(parse_board_opinion(OPINION_OPPOSE), "反対")
        self.assertEqual(parse_board_opinion(OPINION_SUPPORT), "賛同・応募推奨")
        self.assertEqual(parse_board_opinion("対象者は判断を留保する。"), "判断留保")
        self.assertEqual(parse_board_opinion(""), "")

    def test_reference_prices_keep_three_and_six_month_averages(self) -> None:
        parsed = parse_reference_market_price_details(PRICE)
        self.assertEqual(parsed["priorClose"], "1,000")
        self.assertEqual(parsed["avg1m"], "980")
        self.assertEqual(parsed["avg3m"], "960")
        self.assertEqual(parsed["avg6m"], "940")

    def test_advisors_stay_separate(self) -> None:
        records = parse_valuation_records(TWO_ADVISORS)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["advisor"], "株式会社Ａ")
        self.assertEqual(records[0]["dcfMin"], 1224)
        self.assertEqual(records[0]["dcfMax"], 1436)
        self.assertEqual(records[1]["advisor"], "株式会社Ｂ")
        self.assertEqual(records[1]["dcfMin"], 983)
        self.assertEqual(records[1]["dcfMax"], 1453)
        self.assertNotEqual(records[0]["dcfMin"], records[1]["dcfMin"])


class CaseJsonTests(unittest.TestCase):
    def _case(self):
        filing = _doc(
            texts={
                "offerPrice": PRICE,
                "period": "自2026年3月2日至2026年4月13日",
                "intendedPurchase": PLANNED,
                "fund": "買付代金（円）(ａ)1,256,546,025",
                "application": "公開買付代理人 名称 大和証券株式会社 所在地 東京都",
                "purposes": "本取引はMBOとして実施する。親会社は丸紅株式会社である。上場廃止を企図している。",
            },
            numbers={"offerorVotes": "0", "specialVotes": "100", "totalVotes": "1000", "afterPurchaseRatio": ""},
        )
        amendment = _doc(
            docId="S100BBBB",
            docTypeCode="250",
            submitDate="2026-03-20",
            texts={"offerPrice": AMENDED_PRICE, "period": "自2026年3月2日至2026年4月27日"},
        )
        opinion_first = _doc(
            docId="S100CCCC",
            docTypeCode="290",
            submitDate="2026-03-02",
            texts={"opinion": OPINION_OPPOSE},
        )
        opinion_later = _doc(
            docId="S100DDDD",
            docTypeCode="300",
            submitDate="2026-03-21",
            texts={"opinion": OPINION_SUPPORT},
        )
        report = _doc(
            docId="S100EEEE",
            docTypeCode="270",
            submitDate="2026-04-14",
            texts={
                "finalResult": "応募株券等の全部の買付け等を行います。",
                "acquiredShares": "",
            },
            numbers={"afterPurchaseRatio": "86.72"},
        )
        return build_case_json(
            "2026-03",
            [filing, opinion_first, amendment, opinion_later, report],
        )

    def test_core_types_and_hostile_initial(self) -> None:
        case = self._case()
        core = case["core"]
        self.assertEqual(case["caseId"], "S100AAAA")
        self.assertEqual(case["filingMonth"], "2026-03")
        self.assertEqual(core["OfferPrice"], 1050)
        self.assertEqual(core["OfferPeriodEnd"], "2026-04-27")
        self.assertEqual(core["ExistingHoldingRatio"], 0.0)
        self.assertEqual(core["SpecialRelatedHoldingRatio"], 0.1)
        self.assertEqual(core["AfterPurchaseRatio"], 0.8672)
        self.assertEqual(core["PlannedSharesPlanned"], 2517495)
        self.assertIsNone(core["PlannedSharesMin"])
        self.assertIsNone(core["PlannedSharesMax"])
        self.assertEqual(core["PurchaseConsideration"], 1256546025)
        self.assertEqual(core["IsMBO"], "Yes")
        self.assertEqual(core["IsHostileInitial"], "Yes")
        self.assertEqual(core["OpinionStance"], "賛同・応募推奨")
        self.assertEqual(core["Status"], "成立")
        self.assertEqual(core["TargetEdinetCode"], "E00002")
        self.assertEqual(core["TargetDelistingNote"], "上場廃止予定")
        self.assertEqual(
            core["DocIDList"],
            ["S100AAAA", "S100CCCC", "S100BBBB", "S100DDDD", "S100EEEE"],
        )
        links = case["pdfLinks"]
        self.assertEqual(
            links["firstFiling"],
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100AAAA.pdf",
        )
        self.assertEqual(
            links["latestFiling"],
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100BBBB.pdf",
        )
        self.assertEqual(
            links["firstOpinion"],
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100CCCC.pdf",
        )
        self.assertEqual(
            links["latestOpinion"],
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100DDDD.pdf",
        )
        self.assertEqual(
            links["latestReport"],
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100EEEE.pdf",
        )
        self.assertIsNone(links["withdrawal"])
        self.assertEqual(len(links["documents"]), 5)
        self.assertTrue(all(item["pdfUrl"].endswith(".pdf") for item in links["documents"]))

    def test_premiums_use_reference_prices_not_a_scraped_percent(self) -> None:
        case = self._case()
        self.assertEqual(case["referencePrices"]["priorClose"], 1000)
        self.assertEqual(case["referencePrices"]["avg1m"], 980)
        self.assertEqual(case["referencePrices"]["avg3m"], 960)
        self.assertEqual(case["referencePrices"]["avg6m"], 940)
        self.assertEqual(case["premiums"]["vsPriorClose"], 0.05)
        self.assertTrue(case["premiums"]["computed"])

    def test_change_on_one_amendment_shares_a_number(self) -> None:
        changes = self._case()["changes"]
        price = next(item for item in changes if item["item"] == "OfferPrice")
        period = next(item for item in changes if item["item"] == "OfferPeriodEnd")
        opinion = next(item for item in changes if item["item"] == "OpinionStance")
        self.assertEqual(price["changeNo"], period["changeNo"])
        self.assertEqual(price["before"], 955)
        self.assertEqual(price["after"], 1050)
        self.assertEqual(price["sourceDocId"], "S100BBBB")
        self.assertIsNone(price["description"])
        self.assertEqual(opinion["before"], "反対")
        self.assertEqual(opinion["after"], "賛同・応募推奨")
        self.assertNotEqual(opinion["changeNo"], price["changeNo"])

    def test_offeror_and_target_valuations_are_not_folded_together(self) -> None:
        filing = _doc(texts={"offerPrice": PRICE})
        opinion = _doc(
            docId="S100OP01",
            docTypeCode="290",
            submitDate="2026-03-03",
            texts={"opinion": TWO_ADVISORS},
        )
        case = build_case_json("2026-03", [filing, opinion])
        sides = {item["side"] for item in case["valuations"]}
        self.assertEqual(sides, {"offeror", "target"})
        target = [item for item in case["valuations"] if item["side"] == "target"]
        self.assertEqual(len(target), 2)
        self.assertEqual({item["dcfMin"] for item in target}, {1224, 983})
        offeror = [item for item in case["valuations"] if item["side"] == "offeror"]
        self.assertEqual(offeror[0]["dcfMin"], 1100)
        self.assertTrue(all(item["current"] for item in target))

    def test_stock_price_block_is_used_when_the_price_block_has_no_close(self) -> None:
        filing = _doc(
            texts={
                "offerPrice": "普通株式1株につき、金2,000円",
                "recentSharePrices": (
                    "公表日の前営業日の終値(1,500円)、直近１ヶ月間、直近３ヶ月間及び直近６ヶ月間の"
                    "終値単純平均値(1,480円、1,460円及び1,400円)"
                ),
            }
        )
        case = build_case_json("2026-03", [filing])
        self.assertEqual(case["referencePrices"]["priorClose"], 1500)
        self.assertEqual(case["referencePrices"]["avg6m"], 1400)
        self.assertIsNone(case["core"]["IsHostileInitial"])
        self.assertIsNone(case["core"]["IsMBO"])

    def test_after_ratio_is_not_recomputed_from_votes(self) -> None:
        filing = _doc(
            numbers={"offerorVotes": "10", "specialVotes": "10", "totalVotes": "100"},
        )
        case = build_case_json("2026-03", [filing])
        self.assertEqual(case["core"]["ExistingHoldingRatio"], 0.1)
        self.assertIsNone(case["core"]["AfterPurchaseRatio"])

    def test_writes_under_the_filing_month_folder(self) -> None:
        case = build_case_json("2026-03", [_doc()])
        with tempfile.TemporaryDirectory() as tmp:
            path = write_case_json(case, Path(tmp))
            self.assertEqual(path, Path(tmp) / "2026" / "03" / "S100AAAA.json")
            self.assertTrue(path.is_file())
            self.assertEqual(case_output_path("2026-03", "S100AAAA", Path(tmp)), path)

    def test_document_from_xbrl_keeps_full_text_and_stock_price_element(self) -> None:
        long_text = "あ" * 6000
        mapping = {
            "ton": {
                "offer_price_text": ["jptoo-ton_cor:PriceOfPurchaseEtcTextBlock"],
                "recent_share_prices_text": [
                    "jptoo-ton_cor:InformationAboutRecentSharePricesAndTradingVolumeTextBlock"
                ],
            }
        }
        facts = {
            "jptoo-ton_cor:PriceOfPurchaseEtcTextBlock": [long_text],
            "jptoo-ton_cor:InformationAboutRecentSharePricesAndTradingVolumeTextBlock": ["終値"],
        }
        doc = document_from_xbrl({"DocID": "S100ZZZZ", "DocTypeCode": "240"}, facts, mapping)
        self.assertEqual(len(doc["texts"]["offerPrice"]), 6000)
        self.assertEqual(doc["texts"]["recentSharePrices"], "終値")
        self.assertTrue(doc["pdfUrl"].endswith("S100ZZZZ.pdf"))

    def test_pdf_links_remain_when_xbrl_is_missing(self) -> None:
        case = {
            "case_id": "S100AAAA",
            "issuer_tender": False,
            "offeror_name": "買付者株式会社",
            "target_name": "対象株式会社",
            "offeror_edinet_code": "E00001",
            "target_edinet_code": "E00002",
            "documents": [
                {
                    "doc_id": "S100AAAA",
                    "doc_type_code": "240",
                    "submit_date": "2026-03-02",
                    "parent_doc_id": "",
                },
                {
                    "doc_id": "S100CCCC",
                    "doc_type_code": "290",
                    "submit_date": "2026-03-02",
                    "parent_doc_id": "S100AAAA",
                },
            ],
        }
        built = build_case_json(
            "2026-03",
            documents_from_id_case(case, {"S100AAAA": None, "S100CCCC": None}, TaxonomyCatalog()),
            case_id="S100AAAA",
        )
        self.assertEqual(built["core"]["OfferorName"], "買付者株式会社")
        self.assertEqual(built["core"]["TargetEdinetCode"], "E00002")
        self.assertTrue(built["pdfLinks"]["firstFiling"].endswith("/S100AAAA.pdf"))
        self.assertTrue(built["pdfLinks"]["firstOpinion"].endswith("/S100CCCC.pdf"))
        self.assertEqual(built["documents"][0]["xbrlStatus"], "no_xbrl")

    def test_missing_id_list_stops_before_the_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                ["--from-month", "2026-03", "--id-list-dir", tmp, "--as-of", "2026-10-05"]
            )
        self.assertEqual(code, 1)

    def test_module_help(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-m", "tob.case_json", "--help"],
            cwd=tempfile.gettempdir(),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--from-month", result.stdout)


if __name__ == "__main__":
    unittest.main()
