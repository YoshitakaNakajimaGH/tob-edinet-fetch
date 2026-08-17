#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taxonomy import TaxonomyCatalog, resolve_taxonomy_year
from tob_common import (
    CASE_FIELDS,
    LIST_FIELDS,
    assign_case_ids,
    build_cases,
    merge_document_rows,
    normalize_doc_row,
    partition_issuer_tenders,
    resolve_range,
)



class ResolveRangeTests(unittest.TestCase):
    def test_year_range_clips_current_year_to_today(self) -> None:
        start, end, mode = resolve_range(
            from_year="2024",
            to_year="2026",
            today=date(2026, 8, 17),
        )
        self.assertEqual(mode, "years")
        self.assertEqual(start, date(2024, 1, 1))
        self.assertEqual(end, date(2026, 8, 17))

    def test_single_past_year_uses_full_calendar_year(self) -> None:
        start, end, mode = resolve_range(
            from_year="2025",
            to_year="2025",
            today=date(2026, 8, 17),
        )
        self.assertEqual(mode, "years")
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 12, 31))

    def test_recent_days_for_scheduled_update(self) -> None:
        start, end, mode = resolve_range(recent_days=35, today=date(2026, 8, 17))
        self.assertEqual(mode, "recent")
        self.assertEqual(start, date(2026, 7, 13))
        self.assertEqual(end, date(2026, 8, 17))

    def test_rejects_inverted_years(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_range(from_year="2026", to_year="2024", today=date(2026, 8, 17))


class MergeAndCaseTests(unittest.TestCase):
    def test_upsert_keeps_extraction_columns(self) -> None:
        existing = [
            normalize_doc_row(
                {
                    "DocID": "S100AAAA",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-01-10 10:00",
                    "FilerName": "Old Name",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "OfferPrice": "1,000円/株",
                    "ExtractionStatus": "done",
                }
            )
        ]
        incoming = [
            {
                "DocID": "S100AAAA",
                "DocTypeCode": "240",
                "SubmitDateTime": "2026-01-10 10:00",
                "FilerName": "New Name",
                "FilerEdinetCode": "E11111",
                "SubjectEdinetCode": "E22222",
            },
            {
                "DocID": "S100BBBB",
                "DocTypeCode": "250",
                "SubmitDateTime": "2026-01-20 10:00",
                "ParentDocID": "S100AAAA",
                "FilerName": "New Name",
                "FilerEdinetCode": "E11111",
                "SubjectEdinetCode": "E22222",
            },
        ]
        rows, added, updated = merge_document_rows(existing, incoming)
        by_id = {r["DocID"]: r for r in rows}
        self.assertEqual(added, 1)
        self.assertEqual(updated, 1)
        self.assertEqual(by_id["S100AAAA"]["FilerName"], "New Name")
        self.assertEqual(by_id["S100AAAA"]["OfferPrice"], "1,000円/株")
        self.assertEqual(by_id["S100AAAA"]["ExtractionStatus"], "done")
        self.assertEqual(by_id["S100BBBB"]["OfferPrice"], "")

    def test_cases_are_derived_from_document_rows(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100AAAA",
                    "CaseID": "S100AAAA",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-01-10 10:00",
                    "FilerName": "Buyer KK",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "OfferPrice": "1,000円/株",
                    "OfferPeriodStart": "2026-01-11",
                    "TargetName": "（１）【対象者名】Target KK",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100BBBB",
                    "CaseID": "S100AAAA",
                    "ParentDocID": "S100AAAA",
                    "DocTypeCode": "250",
                    "SubmitDateTime": "2026-01-20 10:00",
                    "FilerName": "Buyer KK",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "OfferPrice": "1,100円/株",
                    "OfferPeriodStart": "2026-01-11",
                    "OfferPeriodEnd": "2026-02-20",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100CCCC",
                    "CaseID": "S100AAAA",
                    "ParentDocID": "S100AAAA",
                    "DocTypeCode": "290",
                    "SubmitDateTime": "2026-01-21 10:00",
                    "FilerName": "Target KK",
                    "FilerEdinetCode": "E22222",
                    "SubjectEdinetCode": "E11111",
                    "OpinionStance": "賛同",
                    "ExtractionStatus": "done",
                }
            ),
        ]
        cases = build_cases(rows)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case["CaseID"], "S100AAAA")
        self.assertEqual(case["OfferPrice"], "1,100円/株")
        self.assertEqual(case["OfferPeriodEnd"], "2026-02-20")
        self.assertEqual(case["OpinionStance"], "賛同")
        self.assertEqual(case["HasOpinion"], "Yes")
        self.assertEqual(case["Status"], "訂正あり")
        self.assertEqual(case["EnrichmentStatus"], "done")
        self.assertEqual(case["OfferorName"], "Buyer KK")
        self.assertEqual(case["TargetName"], "Target KK")
        self.assertNotIn("UltimateParentName", case)

    def test_issuer_tender_is_split_off(self) -> None:
        other, issuer = partition_issuer_tenders(
            [
                normalize_doc_row(
                    {
                        "DocID": "S100SELF",
                        "DocTypeCode": "240",
                        "FilerEdinetCode": "E11111",
                        "SubjectEdinetCode": "E11111",
                        "FilerName": "Self KK",
                    }
                ),
                normalize_doc_row(
                    {
                        "DocID": "S100OTHR",
                        "DocTypeCode": "240",
                        "FilerEdinetCode": "E11111",
                        "SubjectEdinetCode": "E22222",
                        "FilerName": "Buyer KK",
                    }
                ),
            ]
        )
        self.assertEqual([r["DocID"] for r in issuer], ["S100SELF"])
        self.assertEqual([r["DocID"] for r in other], ["S100OTHR"])

    def test_orphan_opinion_joins_matching_filing_case(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-01-10 10:00",
                    "FilerName": "Buyer KK",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "TargetName": "Target KK",
                    "OfferPrice": "1,000円/株",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100OPN",
                    "DocTypeCode": "300",
                    "SubmitDateTime": "2026-01-21 10:00",
                    "ParentDocID": "S100MISSING",
                    "FilerName": "Target KK",
                    "FilerEdinetCode": "E22222",
                    "SubjectEdinetCode": "E11111",
                    "OpinionStance": "賛同",
                    "ExtractionStatus": "done",
                }
            ),
        ]
        assign_case_ids(rows)
        self.assertEqual(rows[0]["CaseID"], rows[1]["CaseID"])
        cases = build_cases(rows)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["Status"], "届出中")
        self.assertEqual(cases[0]["OpinionStance"], "賛同")
        self.assertEqual(cases[0]["HasOpinion"], "Yes")

    def test_opinion_only_group_is_not_a_case_row(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100OPN",
                    "CaseID": "S100OPN",
                    "DocTypeCode": "290",
                    "FilerName": "Target KK",
                    "FilerEdinetCode": "E22222",
                    "SubjectEdinetCode": "E11111",
                    "OpinionStance": "賛同",
                }
            )
        ]
        cases = build_cases(rows)
        self.assertEqual(cases, [])

    def test_two_filings_same_parties_stay_separate(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100ONE",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-01-10 10:00",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "FilerName": "Buyer KK",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100TWO",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-06-01 10:00",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "FilerName": "Buyer KK",
                }
            ),
        ]
        assign_case_ids(rows)
        self.assertNotEqual(rows[0]["CaseID"], rows[1]["CaseID"])
        self.assertEqual(len(build_cases(rows)), 2)

    def test_human_columns_come_before_ids(self) -> None:
        self.assertLess(LIST_FIELDS.index("OfferPrice"), LIST_FIELDS.index("DocID"))
        self.assertLess(LIST_FIELDS.index("TargetSecCode"), LIST_FIELDS.index("TargetName"))
        self.assertLess(LIST_FIELDS.index("ExistingHoldingRatio"), LIST_FIELDS.index("CaseID"))
        self.assertGreater(LIST_FIELDS.index("DocID"), LIST_FIELDS.index("TargetName"))
        self.assertLess(CASE_FIELDS.index("TargetSecCode"), CASE_FIELDS.index("TargetName"))
        self.assertLess(CASE_FIELDS.index("FinalResultNote"), CASE_FIELDS.index("TargetDelistingNote"))
        self.assertNotIn("UltimateParentName", LIST_FIELDS)
        self.assertNotIn("UltimateParentNote", LIST_FIELDS)
        self.assertNotIn("WithdrawalReason", CASE_FIELDS)

    def test_failed_offer_uses_existing_ratio_not_planned_after(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "CaseID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-01-10 10:00",
                    "FilerName": "Daiseki",
                    "FilerEdinetCode": "E04931",
                    "SubjectEdinetCode": "E33382",
                    "TargetName": "大阪油化工業株式会社",
                    "ExistingHoldingRatio": "0%",
                    "AfterPurchaseRatio": "100%",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100REPORT",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "270",
                    "SubmitDateTime": "2025-02-13 11:30",
                    "FilerName": "Daiseki",
                    "FilerEdinetCode": "E04931",
                    "SubjectEdinetCode": "E33382",
                    "FinalResultRaw": (
                        "応募株券等の総数(462,165株)が買付予定数の下限(655,300株)に満たなかったため、"
                        "応募株券等の全部の買付け等を行いません。"
                    ),
                    "ExtractionStatus": "done",
                }
            ),
        ]
        case = build_cases(rows)[0]
        self.assertEqual(case["FinalResultNote"], "不成立")
        self.assertEqual(case["AfterPurchaseRatio"], "0%")
        self.assertNotIn("WithdrawalReason", case)

    def test_withdrawal_sets_final_note_and_keeps_existing_ratio(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "CaseID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-04-04 10:00",
                    "FilerName": "Nidec",
                    "FilerEdinetCode": "E01975",
                    "SubjectEdinetCode": "E01496",
                    "ExistingHoldingRatio": "0.0428%",
                    "AfterPurchaseRatio": "100%",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100WD",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "260",
                    "SubmitDateTime": "2025-05-09 10:00",
                    "FilerName": "Nidec",
                    "FilerEdinetCode": "E01975",
                    "SubjectEdinetCode": "E01496",
                    "WithdrawalReason": "対象者が対応方針を導入したため撤回する。",
                    "ExtractionStatus": "done",
                }
            ),
        ]
        case = build_cases(rows)[0]
        self.assertEqual(case["Status"], "撤回")
        self.assertEqual(case["FinalResultNote"], "撤回")
        self.assertEqual(case["AfterPurchaseRatio"], "0.0428%")

    def test_in_progress_does_not_copy_planned_after_ratio(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "CaseID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2026-08-01 10:00",
                    "FilerName": "Buyer KK",
                    "FilerEdinetCode": "E11111",
                    "SubjectEdinetCode": "E22222",
                    "OfferPrice": "1,000円/株",
                    "ExistingHoldingRatio": "42.3%",
                    "AfterPurchaseRatio": "100%",
                    "ExtractionStatus": "done",
                }
            )
        ]
        case = build_cases(rows)[0]
        self.assertEqual(case["Status"], "届出中")
        self.assertEqual(case["FinalResultNote"], "")
        self.assertEqual(case["AfterPurchaseRatio"], "")

    def test_successful_report_keeps_actual_after_ratio(self) -> None:
        rows = [
            normalize_doc_row(
                {
                    "DocID": "S100FILING",
                    "CaseID": "S100FILING",
                    "DocTypeCode": "240",
                    "SubmitDateTime": "2025-06-23 10:00",
                    "FilerName": "NFK",
                    "FilerEdinetCode": "E01648",
                    "SubjectEdinetCode": "E33345",
                    "ExistingHoldingRatio": "29.265%",
                    "AfterPurchaseRatio": "52.06%",
                    "ExtractionStatus": "done",
                }
            ),
            normalize_doc_row(
                {
                    "DocID": "S100REPORT",
                    "CaseID": "S100FILING",
                    "ParentDocID": "S100FILING",
                    "DocTypeCode": "270",
                    "SubmitDateTime": "2025-08-05 16:00",
                    "FilerName": "NFK",
                    "FilerEdinetCode": "E01648",
                    "SubjectEdinetCode": "E33345",
                    "AfterPurchaseRatio": "52.06%",
                    "FinalResultRaw": (
                        "応募株券等の総数（979,000株）が買付予定数の下限（457,200株）に達し、"
                        "かつ、買付予定数の上限（502,500株）を超えたため、あん分比例の方式により決済を行います。"
                    ),
                    "ExtractionStatus": "done",
                }
            ),
        ]
        case = build_cases(rows)[0]
        self.assertEqual(case["FinalResultNote"], "成立（按分）")
        self.assertEqual(case["AfterPurchaseRatio"], "52.06%")

    def test_normalize_strips_target_heading(self) -> None:
        row = normalize_doc_row(
            {
                "DocID": "S100AAAA",
                "DocTypeCode": "240",
                "TargetName": "（１）【対象者名】株式会社ライトオン",
                "FilerName": "Buyer KK",
            }
        )
        self.assertEqual(row["TargetName"], "株式会社ライトオン")
        self.assertNotIn("UltimateParentName", row)


class TaxonomyCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = TaxonomyCatalog(ROOT / "taxonomy")

    def test_2022_inherits_2021_mapping(self) -> None:
        mapping = self.catalog.mapping_for_year(2022)
        self.assertIn(
            "jptoo-ton_cor:OriginalPeriodAtFilingTextBlock",
            mapping["ton"]["period_text"],
        )
        self.assertEqual(mapping["inherits"], "2021")

    def test_estimate_uses_2021_before_may_2026(self) -> None:
        self.assertEqual(self.catalog.estimate_year(date(2026, 4, 30)), "2021")
        self.assertEqual(self.catalog.estimate_year(date(2026, 5, 1)), "2026")

    def test_detect_from_2026_element_ids(self) -> None:
        facts = {"jptoo-ton_cor:PeriodOfPurchaseEtcTextBlock": ["2026年5月1日から"]}
        self.assertEqual(self.catalog.detect_from_facts(facts), "2026")

    def test_amendment_inherits_parent_year(self) -> None:
        year, tax_date, source = resolve_taxonomy_year(
            self.catalog,
            submit_datetime="2026-06-01 10:00",
            parent_year="2021",
            is_amendment=True,
        )
        self.assertEqual(year, "2021")
        self.assertEqual(tax_date, "2020-11-01")
        self.assertEqual(source, "parent")


if __name__ == "__main__":
    unittest.main()
