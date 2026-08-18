"""年度別TOBタクソノミの読み込みと版選択。"""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime
from pathlib import Path

DEFAULT_TAXONOMY_DIR = Path(__file__).resolve().parent

FILING_DOC_TYPES = frozenset({"240", "250"})
SIDE_DOC_TYPES = frozenset({"260", "270", "280", "290", "300", "310", "320"})


class TaxonomyCatalog:
    def __init__(self, taxonomy_dir: Path | None = None) -> None:
        self.taxonomy_dir = Path(taxonomy_dir or DEFAULT_TAXONOMY_DIR)
        manifest_path = self.taxonomy_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"taxonomy manifest がありません: {manifest_path}")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.versions: dict[str, dict] = {}
        for item in self.manifest.get("versions") or []:
            year = str(item.get("year") or "")
            if year:
                self.versions[year] = item
        self._mapping_cache: dict[str, dict] = {}

    def available_years(self) -> list[int]:
        return sorted(int(y) for y in self.versions)

    def mapping_for_year(self, year: str | int, *, issuer: bool = False) -> dict:
        year_key = str(year)
        cache_key = f"{year_key}:{'issuer' if issuer else 'other'}"
        if cache_key in self._mapping_cache:
            return self._mapping_cache[cache_key]
        item = self.versions.get(year_key)
        if not item:
            raise KeyError(f"未登録のタクソノミ年です: {year}")
        if item.get("inherits"):
            mapping = dict(self.mapping_for_year(item["inherits"], issuer=issuer))
            mapping["year"] = int(year_key)
            mapping["inherits"] = str(item["inherits"])
            mapping["note"] = item.get("note") or mapping.get("note", "")
            self._mapping_cache[cache_key] = mapping
            return mapping
        rel_key = "issuer_mapping" if issuer else "mapping"
        rel = item.get(rel_key)
        if not rel:
            raise KeyError(f"{year} の {rel_key} パスがありません")
        path = self.taxonomy_dir / rel
        mapping = json.loads(path.read_text(encoding="utf-8"))
        self._mapping_cache[cache_key] = mapping
        return mapping

    def estimate_year(self, submit_day: date | None) -> str:
        return self.estimate_year_for_doc(submit_day, "")

    def estimate_year_for_doc(
        self,
        submit_day: date | None,
        doc_type_code: str = "",
        *,
        issuer: bool = False,
    ) -> str:
        if submit_day is None:
            years = self.available_years()
            return str(years[-1] if years else "2021")

        matched: list[str] = []
        for year in reversed(self.available_years()):
            item = self.versions[str(year)]
            if item.get("status") == "alias":
                continue
            if not _doc_type_matches(item, doc_type_code, issuer=issuer):
                continue
            start = _parse_iso_date(item.get("applies_from"))
            end = _parse_iso_date(item.get("applies_to"))
            if start and submit_day < start:
                continue
            if end and submit_day > end:
                continue
            matched.append(str(year))
        if matched:
            return matched[0]

        if submit_day < date(2021, 1, 1):
            if issuer and "2014" in self.versions:
                return "2014"
            if doc_type_code in FILING_DOC_TYPES and "2014" in self.versions:
                return "2014"
            if doc_type_code in SIDE_DOC_TYPES and "2013" in self.versions:
                return "2013"

        return self._estimate_by_date_only(submit_day)

    def _estimate_by_date_only(self, submit_day: date) -> str:
        chosen = None
        for year in self.available_years():
            item = self.versions[str(year)]
            start = _parse_iso_date(item.get("applies_from"))
            end = _parse_iso_date(item.get("applies_to"))
            if item.get("status") == "alias":
                continue
            if start and submit_day < start:
                continue
            if end and submit_day > end:
                continue
            chosen = str(year)
        if chosen:
            return chosen
        years = self.available_years()
        return str(years[-1] if years else "2021")

    def fallback_years(
        self,
        primary_year: str,
        doc_type_code: str = "",
        *,
        issuer: bool = False,
    ) -> list[str]:
        """Primary 版で取れない要素向けに、古い/新しい版の要素IDを足す候補。"""
        fallbacks: list[str] = []
        primary = str(primary_year)

        def add(*years: str) -> None:
            for year in years:
                if year != primary and year in self.versions and year not in fallbacks:
                    fallbacks.append(year)

        if primary == "2026":
            add("2021")
        elif primary == "2021":
            if issuer or doc_type_code in FILING_DOC_TYPES:
                add("2014")
            elif doc_type_code in SIDE_DOC_TYPES:
                add("2013")
        elif primary == "2014":
            add("2021")
        elif primary == "2013":
            add("2021")
        return fallbacks

    def merged_mapping_for_doc(
        self,
        year: str | int,
        doc_type_code: str = "",
        *,
        issuer: bool = False,
    ) -> dict:
        """Primary 版の要素IDを先頭に、フォールバック版の要素IDを後ろにマージする。"""
        primary_year = str(year)
        merged = copy.deepcopy(self.mapping_for_year(primary_year, issuer=issuer))
        fallback_years = self.fallback_years(primary_year, doc_type_code, issuer=issuer)
        if not fallback_years:
            return merged
        for alt_year in fallback_years:
            alt = self.mapping_for_year(alt_year, issuer=issuer)
            _merge_mapping_sections(merged, alt)
        merged["merged_fallback_years"] = fallback_years
        return merged

    def detect_from_facts(self, facts: dict[str, list[str]], *, issuer: bool = False) -> str | None:
        names = set(facts)
        key = "issuer_detection_markers" if issuer else "detection_markers"
        markers = self.manifest.get(key) or {}
        for year in reversed(self.available_years()):
            year_key = str(year)
            element_ids = markers.get(year_key) or []
            if any(eid in names for eid in element_ids):
                return year_key
        return None

    def detect_from_text(self, text: str) -> str | None:
        if not text:
            return None
        dates = set(re.findall(r"20\d{2}-\d{2}-\d{2}", text))
        for year in reversed(self.available_years()):
            item = self.versions[str(year)]
            tax_date = item.get("taxonomy_date")
            if tax_date and tax_date in dates and item.get("status") != "alias":
                return str(year)
        return None


def _doc_type_matches(item: dict, doc_type_code: str, *, issuer: bool = False) -> bool:
    doc_types = item.get("doc_types")
    if not doc_types:
        if issuer:
            return bool(item.get("issuer_mapping"))
        return bool(item.get("mapping"))
    if not doc_type_code:
        return False
    return doc_type_code in doc_types


def _merge_mapping_sections(target: dict, source: dict) -> None:
    for section, fields in source.items():
        if section in {"year", "taxonomy_date", "note", "source_url", "inherits", "merged_fallback_years"}:
            continue
        if not isinstance(fields, dict):
            continue
        bucket = target.setdefault(section, {})
        if not isinstance(bucket, dict):
            continue
        for field, element_ids in fields.items():
            if not isinstance(element_ids, list):
                continue
            existing = list(bucket.get(field) or [])
            for eid in element_ids:
                if eid not in existing:
                    existing.append(eid)
            bucket[field] = existing


def _parse_iso_date(value: object) -> date | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def parse_submit_day(submit_datetime: str) -> date | None:
    text = (submit_datetime or "")[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_taxonomy_year(
    catalog: TaxonomyCatalog,
    *,
    submit_datetime: str = "",
    parent_year: str = "",
    facts: dict[str, list[str]] | None = None,
    zip_text: str = "",
    is_amendment: bool = False,
    issuer: bool = False,
    doc_type_code: str = "",
) -> tuple[str, str, str]:
    """Return (year, taxonomy_date, source). source is detected/parent/estimated."""
    detected = None
    if facts:
        detected = catalog.detect_from_facts(facts, issuer=issuer)
    if not detected and zip_text:
        detected = catalog.detect_from_text(zip_text)
    if detected:
        item = catalog.versions.get(detected, {})
        return detected, item.get("taxonomy_date") or "", "detected"
    if is_amendment and parent_year and parent_year in catalog.versions:
        item = catalog.versions[parent_year]
        while item.get("inherits"):
            parent_year = str(item["inherits"])
            item = catalog.versions.get(parent_year, {})
        return parent_year, item.get("taxonomy_date") or "", "parent"
    year = catalog.estimate_year_for_doc(
        parse_submit_day(submit_datetime),
        doc_type_code,
        issuer=issuer,
    )
    item = catalog.versions.get(year, {})
    return year, item.get("taxonomy_date") or "", "estimated"
