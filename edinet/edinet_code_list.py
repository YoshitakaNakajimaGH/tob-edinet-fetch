#!/usr/bin/env python3
"""EDINET提出者リスト（証券コード・上場区分）の読み込み。"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

LISTED_CATEGORY = "上場"
UNLISTED_CATEGORY = "非上場"
UNLISTED_LABEL = "非上場"

EDINET_CODE_ZIP_URL = (
    "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
)
DEFAULT_CACHE_PATH = Path("cache/edinet/EdinetcodeDlInfo.csv")
DEFAULT_MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class EdinetFilerInfo:
    listing_category: str
    sec_code: str
    name: str


def normalize_company_name(name: str) -> str:
    """Normalize filer names for EDINET code list lookup."""
    text = (name or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    for token in (
        "株式会社",
        "(株)",
        "（株）",
        "有限会社",
        "合同会社",
        "合名会社",
        "合資会社",
    ):
        text = text.replace(token, "")
    # Drop parenthetical English aliases: Foo（Bar Baz）→ Foo
    text = re.sub(r"\([^)]*\)", "", text)
    return text.casefold()


class EdinetCodeList:
    def __init__(self, by_edinet: dict[str, EdinetFilerInfo]) -> None:
        self._by_edinet = by_edinet
        by_name: dict[str, EdinetFilerInfo] = {}
        listed_by_name: dict[str, EdinetFilerInfo] = {}
        unlisted_by_name: dict[str, EdinetFilerInfo] = {}
        for info in by_edinet.values():
            key = normalize_company_name(info.name)
            if not key:
                continue
            if key not in by_name:
                by_name[key] = info
            if info.listing_category == LISTED_CATEGORY and info.sec_code:
                listed_by_name[key] = info
            elif info.listing_category == UNLISTED_CATEGORY:
                unlisted_by_name.setdefault(key, info)
        self._by_name = by_name
        self._listed_by_name = listed_by_name
        self._unlisted_by_name = unlisted_by_name

    def get(self, edinet_code: str) -> EdinetFilerInfo | None:
        code = (edinet_code or "").strip()
        if not code:
            return None
        return self._by_edinet.get(code)

    def lookup_by_name(self, name: str) -> EdinetFilerInfo | None:
        key = normalize_company_name(name)
        if not key:
            return None
        return self._by_name.get(key)

    def listing_category(self, edinet_code: str) -> str:
        info = self.get(edinet_code)
        return info.listing_category if info else ""

    def sec_code(self, edinet_code: str) -> str:
        info = self.get(edinet_code)
        return info.sec_code if info else ""

    @staticmethod
    def _format_sec_code(raw: str) -> str:
        sec = (raw or "").strip()
        if sec.isdigit() and len(sec) == 5:
            return sec[:4]
        if sec.isdigit() and len(sec) == 4:
            return sec
        return sec

    def listing_label(
        self,
        *,
        name: str = "",
        edinet_code: str = "",
    ) -> str:
        """Return 4-digit sec code for listed filers, 非上場 for known unlisted, else ''."""
        if name:
            key = normalize_company_name(name)
            listed = self._listed_by_name.get(key)
            if listed and listed.sec_code:
                return self._format_sec_code(listed.sec_code)
            unlisted = self._unlisted_by_name.get(key)
            if unlisted:
                return UNLISTED_LABEL

        info = self.get(edinet_code) if edinet_code else None
        if info is None and name:
            info = self.lookup_by_name(name)
        if info is None:
            return ""
        if info.listing_category == LISTED_CATEGORY and info.sec_code:
            return self._format_sec_code(info.sec_code)
        if info.listing_category == UNLISTED_CATEGORY:
            return UNLISTED_LABEL
        return ""


def _parse_csv_text(text: str) -> dict[str, EdinetFilerInfo]:
    rows = csv.reader(io.StringIO(text))
    next(rows, None)  # download date line
    next(rows, None)  # header
    by_edinet: dict[str, EdinetFilerInfo] = {}
    for row in rows:
        if len(row) < 12:
            continue
        edinet = row[0].strip().strip('"')
        if not edinet:
            continue
        by_edinet[edinet] = EdinetFilerInfo(
            listing_category=row[2].strip().strip('"'),
            sec_code=row[11].strip().strip('"'),
            name=row[6].strip().strip('"'),
        )
    return by_edinet


def load_edinet_code_list(path: Path) -> EdinetCodeList:
    text = path.read_text(encoding="cp932", errors="replace")
    return EdinetCodeList(_parse_csv_text(text))


def download_edinet_code_list(cache_path: Path = DEFAULT_CACHE_PATH, timeout: int = 120) -> Path:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(EDINET_CODE_ZIP_URL, timeout=timeout) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        csv_name = next(name for name in zf.namelist() if name.lower().endswith(".csv"))
        cache_path.write_bytes(zf.read(csv_name))
    return cache_path


def ensure_edinet_code_list(
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: date | None = None,
    force: bool = False,
) -> EdinetCodeList:
    today = today or date.today()
    stale = True
    if cache_path.exists() and not force:
        modified = date.fromtimestamp(cache_path.stat().st_mtime)
        stale = today - modified > timedelta(days=max_age_days)
    if force or not cache_path.exists() or stale:
        try:
            download_edinet_code_list(cache_path)
        except (URLError, OSError, zipfile.BadZipFile, StopIteration) as exc:
            if not cache_path.exists():
                raise RuntimeError(f"EDINET code list download failed: {exc}") from exc
    return load_edinet_code_list(cache_path)
