"""年度別TOBタクソノミの読み込みと版選択。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

DEFAULT_TAXONOMY_DIR = Path(__file__).resolve().parent


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

    def mapping_for_year(self, year: str | int) -> dict:
        year_key = str(year)
        if year_key in self._mapping_cache:
            return self._mapping_cache[year_key]
        item = self.versions.get(year_key)
        if not item:
            raise KeyError(f"未登録のタクソノミ年です: {year}")
        if item.get("inherits"):
            mapping = dict(self.mapping_for_year(item["inherits"]))
            mapping["year"] = int(year_key)
            mapping["inherits"] = str(item["inherits"])
            mapping["note"] = item.get("note") or mapping.get("note", "")
            self._mapping_cache[year_key] = mapping
            return mapping
        rel = item.get("mapping")
        if not rel:
            raise KeyError(f"{year} の mapping パスがありません")
        path = self.taxonomy_dir / rel
        mapping = json.loads(path.read_text(encoding="utf-8"))
        self._mapping_cache[year_key] = mapping
        return mapping

    def estimate_year(self, submit_day: date | None) -> str:
        if submit_day is None:
            years = self.available_years()
            return str(years[-1] if years else "2021")
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
        return str(years[0] if years else "2021")

    def detect_from_facts(self, facts: dict[str, list[str]]) -> str | None:
        names = set(facts)
        markers = self.manifest.get("detection_markers") or {}
        for year, element_ids in markers.items():
            if any(eid in names for eid in element_ids):
                return str(year)
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
) -> tuple[str, str, str]:
    """Return (year, taxonomy_date, source). source is detected/parent/estimated."""
    detected = None
    if facts:
        detected = catalog.detect_from_facts(facts)
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
    year = catalog.estimate_year(parse_submit_day(submit_datetime))
    item = catalog.versions.get(year, {})
    return year, item.get("taxonomy_date") or "", "estimated"
