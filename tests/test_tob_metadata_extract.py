#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tob.extract_fields import (
    EXPLICIT_EMPTY,
    build_value_history,
    detect_mbo,
    extract_sponsor_from_purposes,
    extract_tender_offer_agent,
    extract_valuation_from_purposes,
    format_premium,
    parse_offer_report_counts,
    parse_planned_purchase_counts,
    parse_purchase_consideration,
    parse_reference_market_prices,
    parse_valuation_advisors,
    parse_valuation_from_sources,
    parse_valuation_ranges,
)
from tob.tob_common import columns_for_enrich_groups, parse_enrich_groups


class SponsorHintTests(unittest.TestCase):
    def test_second_paragraph_subject_before_wa(self) -> None:
        text = (
            "（１）本公開買付の概要\n"
            "公開買付者は、ケイマン諸島法に基づくリミテッド・パートナーシップです。\n"
            "ベインキャピタルは、本公開買付けを通じて対象者株式の非公開化を企図しております。"
        )
        self.assertEqual(extract_sponsor_from_purposes(text), "ベインキャピタル")

    def test_skips_offeror_subject(self) -> None:
        text = (
            "（１）本公開買付の概要\n"
            "第一段落。\n"
            "公開買付者は、本公開買付価格を決定するにあたり、対象者と協議しました。"
        )
        self.assertEqual(extract_sponsor_from_purposes(text), "")


class MboDetectTests(unittest.TestCase):
    def test_detects_mbo_keyword(self) -> None:
        self.assertEqual(detect_mbo(["2025年８月６日付「ＭＢＯの実施及び応募の推奨に関するお知らせ」"]), "Yes")

    def test_ignores_management_presentation(self) -> None:
        self.assertEqual(
            detect_mbo(["対象者からのマネジメントプレゼンテーション等に基づき分析しました。"]),
            "",
        )


class ValuationRangeTests(unittest.TestCase):
    def test_parses_three_methods(self) -> None:
        text = (
            "算定の基礎　市場株価法：1,902円から2,001円 "
            "類似上場会社比較法：978円から1,242円 "
            "DCF法：2,733円から4,501円"
        )
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "1,902")
        self.assertEqual(parsed["ValuationMarketMax"], "2,001")
        self.assertEqual(parsed["ValuationComparableMin"], "978")
        self.assertEqual(parsed["ValuationComparableMax"], "1,242")
        self.assertEqual(parsed["ValuationDCFMin"], "2,733")
        self.assertEqual(parsed["ValuationDCFMax"], "4,501")

    def test_parses_lerz_style(self) -> None:
        text = "算定の基礎 市場株価法：1,675円から1,698円 DCF法　　 ：2,199円から2,783円"
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "1,675")
        self.assertEqual(parsed["ValuationDCFMax"], "2,783")

    def test_parses_fullwidth_dcf_and_tilde(self) -> None:
        text = "算定の基礎 市場株価平均法：997円～1,017円ＤＣＦ法　　　：524円～1,480円"
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "997")
        self.assertEqual(parsed["ValuationMarketMax"], "1,017")
        self.assertEqual(parsed["ValuationDCFMin"], "524")
        self.assertEqual(parsed["ValuationDCFMax"], "1,480")

    def test_parses_valuation_from_purposes_section(self) -> None:
        price = "算定の基礎 第三者算定機関からの算定書は取得しておりません。"
        purposes = (
            "３【買付け等の目的】(3）本公開買付価格の公正性を担保するための措置 "
            "ＳＭＢＣ日興証券は、市場株価法：1,420円から1,480円 "
            "類似上場会社比較法：1,350円から1,510円 "
            "ＤＣＦ法：1,600円から2,100円の範囲で算定しました。"
        )
        parsed = parse_valuation_from_sources(price, purposes)
        self.assertEqual(parsed["ValuationMarketMin"], "1,420")
        self.assertEqual(parsed["ValuationDCFMax"], "2,100")

    def test_parses_kijun_hijun_method_labels(self) -> None:
        text = (
            "市場株価基準方式：1,083円から1,258円 "
            "類似会社比準方式：1,110円から1,223円 "
            "ＤＣＦ方式：1,243円から1,522円"
        )
        parsed = parse_valuation_ranges(text)
        self.assertEqual(parsed["ValuationMarketMin"], "1,083")
        self.assertEqual(parsed["ValuationComparableMax"], "1,223")
        self.assertEqual(parsed["ValuationDCFMax"], "1,522")

    def test_prefers_special_committee_third_party_valuation(self) -> None:
        purposes = (
            "③　対象者における独立したファイナンシャル・アドバイザー及び第三者算定機関からの"
            "株式価値算定書の取得（ⅱ）対象者株式に係る算定の概要 "
            "ＰｗＣは市場株価基準方式：1,083円から1,258円 "
            "類似会社比準方式：1,110円から1,223円 "
            "ＤＣＦ方式：1,243円から1,522円 "
            "⑤　特別委員会における独立した第三者算定機関からの株式価値算定書及び"
            "フェアネス・オピニオンの取得 "
            "プルータスは市場株価法：1,083円から1,258円 "
            "ＤＣＦ方式：1,106円から1,615円"
        )
        parsed = parse_valuation_from_sources("", purposes)
        self.assertEqual(parsed["ValuationMarketMin"], "1,083")
        self.assertEqual(parsed["ValuationDCFMin"], "1,106")
        self.assertEqual(parsed["ValuationDCFMax"], "1,615")
        self.assertEqual(parsed["ValuationComparableMin"], "")

    def test_falls_back_to_independent_advisor_when_price_empty(self) -> None:
        purposes = (
            "③　対象者における独立したファイナンシャル・アドバイザー及び第三者算定機関"
            "（ⅱ）対象者株式に係る算定の概要 "
            "市場株価基準方式：900円から1,000円 ＤＣＦ方式：1,100円から1,200円"
        )
        parsed = parse_valuation_from_sources("", purposes)
        self.assertEqual(parsed["ValuationMarketMin"], "900")
        self.assertEqual(parsed["ValuationDCFMax"], "1,200")

    def test_extract_valuation_from_purposes_finds_keyword_window(self) -> None:
        text = (
            "背景説明が長く続きます。" * 20
            + "公開買付者は、市場株価法：900円から950円、ＤＣＦ法：1,100円から1,300円と算定。"
        )
        section = extract_valuation_from_purposes(text)
        self.assertIn("市場株価法", section)
        self.assertIn("ＤＣＦ法", section)


class EnrichFieldGroupTests(unittest.TestCase):
    def test_parse_groups_defaults_to_all(self) -> None:
        self.assertEqual(parse_enrich_groups(""), frozenset({"all"}))
        self.assertIsNone(columns_for_enrich_groups(frozenset({"all"})))

    def test_parse_specific_groups(self) -> None:
        groups = parse_enrich_groups("valuation, fund")
        columns = columns_for_enrich_groups(groups)
        self.assertIn("ValuationMarketMin", columns)
        self.assertIn("PurchaseConsideration", columns)
        self.assertNotIn("PlannedSharesPlanned", columns)


class PlannedPurchaseTests(unittest.TestCase):
    def test_unparsed_text_stays_blank(self) -> None:
        parsed = parse_planned_purchase_counts("公開買付の概要のみ")
        self.assertEqual(parsed["PlannedSharesMin"], "")
        self.assertEqual(parsed["PlannedSharesMax"], "")
        self.assertEqual(parsed["PlannedSharesPlanned"], "")

    def test_parses_floor_and_cap_from_total_row(self) -> None:
        text = (
            "普通株式 上限（100株）下限（50株）"
            "合計 上限（5,467,100株）下限（5,467,100株）"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesMin"], "5,467,100")
        self.assertEqual(parsed["PlannedSharesMax"], "5,467,100")
        self.assertEqual(parsed["PlannedSharesPlanned"], "")

    def test_parses_single_planned_count_on_total(self) -> None:
        text = "普通株式 上限（100株）合計 買付予定数（2,000,000株）"
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,000,000")

    def test_parses_xbrl_table_without_bounds(self) -> None:
        text = (
            "株券等の種類買付予定数買付予定数の下限買付予定数の上限"
            "普通株式2,517,495(株)―(株)―(株)合計2,517,495(株)―(株)―(株)"
            "上限及び下限を設定しておりません"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,517,495")
        self.assertEqual(parsed["PlannedSharesMin"], EXPLICIT_EMPTY)
        self.assertEqual(parsed["PlannedSharesMax"], EXPLICIT_EMPTY)

    def test_parses_fullwidth_share_parentheses(self) -> None:
        text = (
            "普通株式2,448,692（株）―（株）―（株）"
            "合計2,448,692（株）―（株）―（株）"
            "上限及び下限を設定しておりません"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "2,448,692")
        self.assertEqual(parsed["PlannedSharesMin"], EXPLICIT_EMPTY)

    def test_parses_xbrl_table_with_floor_only(self) -> None:
        text = (
            "普通株式20,252,536(株)4,297,400(株)－(株)"
            "合計20,252,536(株)4,297,400(株)－(株)"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesMin"], "4,297,400")
        self.assertEqual(parsed["PlannedSharesMax"], EXPLICIT_EMPTY)
        self.assertEqual(parsed["PlannedSharesPlanned"], "20,252,536")

    def test_parses_all_three_from_total_row(self) -> None:
        text = (
            "（３）【買付予定の株券等の数】"
            "株券等の種類買付予定数買付予定数の下限買付予定数の上限"
            "普通株式16,280,645（株）13,615,600（株）16,280,645（株）"
            "合計16,280,645（株）13,615,600（株）16,280,645（株）"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "16,280,645")
        self.assertEqual(parsed["PlannedSharesMin"], "13,615,600")
        self.assertEqual(parsed["PlannedSharesMax"], "16,280,645")

    def test_parses_planned_when_min_set_and_max_dash(self) -> None:
        text = (
            "株券等の種類買付予定数買付予定数の下限買付予定数の上限"
            "普通株式41,650,969(株)12,133,398(株)―(株)"
            "合計41,650,969(株)12,133,398(株)―(株)"
            "(注１)買付予定数の下限(12,133,398株)に満たない場合"
        )
        parsed = parse_planned_purchase_counts(text)
        self.assertEqual(parsed["PlannedSharesPlanned"], "41,650,969")
        self.assertEqual(parsed["PlannedSharesMin"], "12,133,398")
        self.assertEqual(parsed["PlannedSharesMax"], EXPLICIT_EMPTY)


class PurchaseConsiderationTests(unittest.TestCase):
    def test_parses_yen_amount(self) -> None:
        text = "８【買付け等に要する資金】 買付代金（a） 38,234,567,890円 借入金（b）"
        self.assertEqual(parse_purchase_consideration(text), "38,234,567,890円")

    def test_parses_won_amount(self) -> None:
        text = "買付代金(a) 120,000,000ウォン"
        self.assertEqual(parse_purchase_consideration(text), "120,000,000ウォン")

    def test_parses_yen_before_a_marker(self) -> None:
        text = "買付代金(円)(a)3,222,393,600金銭以外の対価"
        self.assertEqual(parse_purchase_consideration(text), "3,222,393,600円")

    def test_parses_fullwidth_yen_marker(self) -> None:
        text = "買付代金（円）(a)97,809,894,000金銭以外"
        self.assertEqual(parse_purchase_consideration(text), "97,809,894,000円")


class TenderOfferAgentTests(unittest.TestCase):
    def test_prefers_cover_page_name(self) -> None:
        self.assertEqual(
            extract_tender_offer_agent("", "野村證券株式会社"),
            "野村證券株式会社",
        )

    def test_strips_address_after_company_name(self) -> None:
        self.assertEqual(
            extract_tender_offer_agent(
                "",
                "ＳＭＢＣ日興証券株式会社 東京都千代田区丸の内三丁目３番１号",
            ),
            "ＳＭＢＣ日興証券株式会社",
        )
        self.assertEqual(
            extract_tender_offer_agent(
                "",
                "三菱ＵＦＪモルガン・スタンレー証券株式会社　東京都千代田区大手町一丁目９番２号",
            ),
            "三菱ＵＦＪモルガン・スタンレー証券株式会社",
        )

    def test_parses_application_section(self) -> None:
        text = "（１）【応募の方法】 ①公開買付代理人 名称 みずほ証券株式会社 所在地"
        self.assertEqual(extract_tender_offer_agent(text), "みずほ証券株式会社")


class ReferencePriceTests(unittest.TestCase):
    def test_announcement_close_and_one_month_average(self) -> None:
        text = (
            "本公開買付けの公表日の前営業日である2021年７月26日の東京証券取引所市場第一部における"
            "対象者株式の終値(3,035円)、同日までの直近１ヶ月間、直近３ヶ月間及び直近６ヶ月間の"
            "終値単純平均値(3,048円、3,009円及び2,925円)の推移を参考にしました。"
        )
        parsed = parse_reference_market_prices(text)
        self.assertEqual(parsed["ReferencePricePriorClose"], "3,035円")
        self.assertEqual(parsed["ReferencePrice1M"], "3,048円")

    def test_ignores_precedent_premium_sentence(self) -> None:
        text = (
            "ＭＢＯ事例におけるプレミアムの実例（公表日前営業日の終値、過去１ヶ月間の"
            "終値単純平均値におけるプレミアム率の中央値）を参考としました。"
        )
        parsed = parse_reference_market_prices(text)
        self.assertEqual(parsed["ReferencePricePriorClose"], "")
        self.assertEqual(parsed["ReferencePrice1M"], "")

    def test_ignores_filing_date_prior_close(self) -> None:
        text = "本書提出日の前営業日である2021年８月20日の終値1,811円に対して3.37％のディスカウント"
        parsed = parse_reference_market_prices(text)
        self.assertEqual(parsed["ReferencePricePriorClose"], "")

    def test_conflicting_closes_stay_blank(self) -> None:
        text = (
            "公表日の前営業日の終値(1,000円)。"
            "別の記載で公表日の前営業日の終値(2,000円)。"
        )
        parsed = parse_reference_market_prices(text)
        self.assertEqual(parsed["ReferencePricePriorClose"], "")

    def test_premium_uses_same_document_offer_price(self) -> None:
        self.assertEqual(format_premium("3,810円/株", "3,035円"), "+25.5%")

    def test_premium_rejects_non_yen_offer(self) -> None:
        self.assertEqual(format_premium("株式対価 0.5株", "3,035円"), "")


class ValuationAdvisorTests(unittest.TestCase):
    def test_two_advisors(self) -> None:
        text = (
            "ＰｗＣは市場株価基準方式：1,083円から1,258円"
            "類似会社比準方式：1,110円から1,223円"
            "ＤＣＦ方式：1,243円から1,522円。"
            "プルータスは市場株価法：1,083円から1,258円"
            "ＤＣＦ方式：1,106円から1,615円。"
        )
        parsed = parse_valuation_advisors(text)
        self.assertIn("ＰｗＣ", parsed)
        self.assertIn("プルータス", parsed)
        self.assertIn("DCF法 1,106〜1,615円", parsed)

    def test_single_advisor_stays_blank(self) -> None:
        text = "ＳＭＢＣ日興証券は、市場株価法：1,420円から1,480円 ＤＣＦ法：1,600円から2,100円"
        self.assertEqual(parse_valuation_advisors(text), "")


class ReportCountTests(unittest.TestCase):
    def test_full_purchase_copies_tendered_count(self) -> None:
        text = (
            "応募株券等の数の合計(4,785,854株)が買付予定数の下限(3,611,900株)以上と"
            "なりましたので、応募株券等の全部の買付け等を行います。"
        )
        parsed = parse_offer_report_counts(text)
        self.assertEqual(parsed["ApplicationCount"], "4,785,854")
        self.assertEqual(parsed["PurchaseCount"], "4,785,854")

    def test_proration_does_not_invent_purchase_count(self) -> None:
        text = (
            "応募株券等の数の合計(10,000株)が上限を超え、あん分比例により買付け等を行います。"
        )
        parsed = parse_offer_report_counts(text)
        self.assertEqual(parsed["ApplicationCount"], "10,000")
        self.assertEqual(parsed["PurchaseCount"], "")


class ChangeHistoryTests(unittest.TestCase):
    def test_history_requires_a_change(self) -> None:
        docs = [
            {"DocTypeCode": "240", "SubmitDateTime": "2021-08-04", "OfferPrice": "1,380円/株"},
            {"DocTypeCode": "250", "SubmitDateTime": "2021-09-09", "OfferPrice": "1,398円/株"},
        ]
        self.assertEqual(
            build_value_history(docs, "OfferPrice"),
            "2021-08-04 1,380円/株 → 2021-09-09 1,398円/株",
        )

    def test_unchanged_price_is_blank(self) -> None:
        docs = [
            {"DocTypeCode": "240", "SubmitDateTime": "2021-08-04", "OfferPrice": "1,380円/株"},
            {"DocTypeCode": "250", "SubmitDateTime": "2021-08-20", "OfferPrice": "1,380円/株"},
        ]
        self.assertEqual(build_value_history(docs, "OfferPrice"), "")


if __name__ == "__main__":
    unittest.main()
