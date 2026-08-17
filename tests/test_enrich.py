#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrich_tob import parse_opinion_stance
from extract_fields import (
    clean_extracted_name,
    compute_holding_ratios,
    format_pct,
    judge_tob_result,
    parse_period_dates,
    parse_tob_result_counts,
    summarize_price,
)


class ParseHelperTests(unittest.TestCase):
    def test_parse_period_western_and_wareki(self) -> None:
        start, end = parse_period_dates("2026年1月7日から2026年2月19日まで")
        self.assertEqual(start, "2026-01-07")
        self.assertEqual(end, "2026-02-19")
        start, end = parse_period_dates("令和７年９月26日から令和８年２月25日まで")
        self.assertEqual(start, "2025-09-26")
        self.assertEqual(end, "2026-02-25")

    def test_extended_period_uses_last_range(self) -> None:
        text = (
            "届出当初の買付け等の期間 2025年12月２日から2026年１月20日まで "
            "延長後の買付け等の期間 2025年12月２日から2026年１月27日まで"
        )
        start, end = parse_period_dates(text)
        self.assertEqual(start, "2025-12-02")
        self.assertEqual(end, "2026-01-27")

    def test_summarize_price(self) -> None:
        self.assertEqual(
            summarize_price("普通株式１株につき、金6,082円とする。"),
            "6,082円/株",
        )
        self.assertEqual(
            summarize_price("<p>公開買付価格は金3,105円です。</p>"),
            "3,105円/株",
        )
        self.assertEqual(
            summarize_price("株券普通株式１株につき、9,850円新株予約権証券第５回新株予約権 １個につき、1,277,000円"),
            "9,850円/株",
        )
        self.assertEqual(
            summarize_price("対象者普通株式１株につき、金4,309ウォン新株予約権証券―"),
            "4,309ウォン/株",
        )
        self.assertEqual(
            summarize_price("対象者普通株式１株につき、公開買付者普通株式9.34株を割当て交付（株式交付比率：9.34）"),
            "株式対価 9.34株",
        )

    def test_opinion_stance(self) -> None:
        self.assertEqual(parse_opinion_stance("本公開買付けに賛同する。"), "賛同")
        self.assertEqual(parse_opinion_stance("反対の意見を表明する。"), "反対")

    def test_format_pct_accepts_fraction_or_percent(self) -> None:
        self.assertEqual(format_pct("0.8225"), "82.25%")
        self.assertEqual(format_pct("12.34"), "12.34%")

    def test_existing_holding_from_voting_rights(self) -> None:
        existing, special, _ = compute_holding_ratios("100", "50", "1000")
        self.assertEqual(existing, "15%")
        self.assertEqual(special, "5%")

    def test_clean_extracted_name_strips_section_heading(self) -> None:
        self.assertEqual(
            clean_extracted_name("（１）【対象者名】株式会社ライトオン"),
            "株式会社ライトオン",
        )
        self.assertEqual(
            clean_extracted_name("【対象者名】SBI FinTech Solutions株式会社"),
            "SBI FinTech Solutions株式会社",
        )
        self.assertEqual(
            clean_extracted_name("１【対象者名】ID&Eホールディングス株式会社"),
            "ID&Eホールディングス株式会社",
        )
        self.assertEqual(clean_extracted_name("富士ソフト株式会社"), "富士ソフト株式会社")


class ResultJudgeTests(unittest.TestCase):
    def test_failure_below_minimum(self) -> None:
        text = (
            "本公開買付けにおいては、本公開買付けに応募された株券等(以下「応募株券等」といいます。)"
            "の総数が買付予定数の下限(655,300株)に満たない場合は、応募株券等の全部の買付け等を"
            "行わない旨の条件を付しておりましたが、応募株券等の総数(462,165株)が買付予定数の"
            "下限(655,300株)に満たなかったため、応募株券等の全部の買付け等を行いません。"
        )
        self.assertEqual(judge_tob_result(text), "不成立")
        self.assertEqual(parse_tob_result_counts(text), (462165, 655300, None))

    def test_success_within_cap(self) -> None:
        text = (
            "応募株券等の総数(350,000株)が買付予定数の下限(350,000株)に達し、"
            "かつ、買付予定数の上限(350,000株)を超えなかったため、応募株券等の全部の買付け等を行います。"
        )
        self.assertEqual(judge_tob_result(text), "成立")

    def test_success_prorata_over_max(self) -> None:
        text = (
            "応募株券等の総数（979,000株）が買付予定数の下限（457,200株）に達し、"
            "かつ、買付予定数の上限（502,500株）を超えたため、その超える部分の全部又は一部の"
            "買付け等を行わないものとし、あん分比例の方式により、株券等の買付け等に係る受渡し"
            "その他の決済を行います。"
        )
        self.assertEqual(judge_tob_result(text), "成立（按分）")
        self.assertEqual(parse_tob_result_counts(text), (979000, 457200, 502500))

    def test_no_tenders_is_failure(self) -> None:
        text = (
            "本公開買付けに応募された対象者普通株式（以下「応募株券等」といいます。）は"
            "ありませんでしたので、本公開買付けにおいて買付け等の対象となる株券等はありません。"
        )
        self.assertEqual(judge_tob_result(text), "不成立")

    def test_no_min_max_still_success(self) -> None:
        text = (
            "日韓公開買付けにおいては、買付予定数の上限及び下限を設定しておりません。"
            "したがって、本公開買付けに応募された対象者普通株式（以下「応募株券等」といいます。）"
            "と韓国公開買付けに応募された対象者ＫＤＲの全部の買付け等を行います。"
            "なお、本公開買付けにおいては、応募株券等はありませんでしたので、本公開買付けにおいて"
            "買付け等の対象となる株券等はありません。"
        )
        self.assertEqual(judge_tob_result(text), "成立")

    def test_withdrawal_flag(self) -> None:
        self.assertEqual(judge_tob_result("", withdrawn=True), "撤回")


if __name__ == "__main__":
    unittest.main()
