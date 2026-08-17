#!/usr/bin/env python3
"""TOB書類テキスト／数値ファクトからの項目抽出。"""

from __future__ import annotations

import html
import re


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)</(td|th)>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def normalize_name(text: str) -> str:
    if not text:
        return ""
    text = strip_html(text)
    text = re.sub(r"\s+", " ", text).strip(" 　\n\r\t「」『』")
    text = text.replace("㈱", "株式会社")
    return text[:120]


HEADING_PREFIX = re.compile(
    r"^(?:[(（]?\s*[0-9０-９一二三四五六七八九十]+\s*[)）.．]?\s*)?【[^】]+】\s*"
)
LABEL_PREFIX = re.compile(
    r"^(?:対象者名|届出者の氏名又は名称|公開買付者の氏名又は名称)\s*[:：]?\s*"
)


def clean_extracted_name(text: str) -> str:
    """Strip XBRL section headings such as '（１）【対象者名】' from a company name."""
    text = normalize_name(text)
    if not text:
        return ""
    for _ in range(3):
        cleaned = HEADING_PREFIX.sub("", text).strip()
        cleaned = LABEL_PREFIX.sub("", cleaned).strip()
        if cleaned == text:
            break
        text = cleaned
    return text[:120]


def parse_number(value: str) -> float | None:
    if value is None:
        return None
    text = strip_html(str(value))
    text = text.replace(",", "").replace("，", "").replace("％", "").replace("%", "")
    text = text.strip()
    if not text or text in {"－", "-", "―", "なし", "該当なし"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def format_pct(value: float | str | None) -> str:
    number = parse_number(str(value)) if not isinstance(value, float) else value
    if number is None:
        return ""
    # XBRL sometimes stores 82.25% as 0.8225.
    if 0 < abs(number) <= 1.5:
        number *= 100
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{text}%"


def wareki_to_year(era: str, year: int) -> int:
    if era in {"令和", "令"}:
        return 2018 + year
    if era in {"平成", "平"}:
        return 1988 + year
    if era in {"昭和", "昭"}:
        return 1925 + year
    return year


def parse_jp_dates(text: str) -> list[str]:
    if not text:
        return []
    text = strip_html(text)
    found: list[str] = []
    for era, year, month, day in re.findall(r"(令和|平成|昭和|令|平|昭)\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text):
        y = 1 if year == "元" else int(year)
        found.append(f"{wareki_to_year(era, y)}-{int(month):02d}-{int(day):02d}")
    for year, month, day in re.findall(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text):
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        if iso not in found:
            found.append(iso)
    return found


def parse_period_dates(text: str) -> tuple[str, str]:
    """Return offer start/end. If the period was extended, use the last 自/至 pair."""
    if not text:
        return "", ""
    text = strip_html(text)
    ranges: list[tuple[str, str]] = []
    pattern = re.compile(
        r"(?:自\s*)?((?:令和|平成|昭和|令|平|昭)?\s*(?:元|\d{1,4})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
        r"\s*(?:から|～|〜|至)\s*"
        r"((?:令和|平成|昭和|令|平|昭)?\s*(?:元|\d{1,4})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
    )
    for start_raw, end_raw in pattern.findall(text):
        starts = parse_jp_dates(start_raw)
        ends = parse_jp_dates(end_raw)
        if starts and ends:
            ranges.append((starts[0], ends[0]))
    if ranges:
        return ranges[-1]
    dates = parse_jp_dates(text)
    if len(dates) >= 2:
        return dates[0], dates[-1]
    if len(dates) == 1:
        return dates[0], ""
    return "", ""


def summarize_price(text: str) -> str:
    if not text:
        return ""
    text = strip_html(text)
    text = re.sub(r"\s+", " ", text)
    match = re.search(r"普通株式[^。]{0,40}?金\s*([\d,，]+)\s*円", text)
    if match:
        amount = match.group(1).replace("，", ",")
        return f"{amount}円/株"
    match = re.search(r"(?:公開買付価格|買付け等の価格)[^。]{0,40}?金\s*([\d,，]+)\s*円", text)
    if match:
        amount = match.group(1).replace("，", ",")
        return f"{amount}円/株"
    match = re.search(r"金\s*([\d,，]+)\s*円", text)
    if match:
        amount = match.group(1).replace("，", ",")
        return f"{amount}円"
    return text[:200]


def compute_holding_ratios(
    offeror_votes: str,
    special_votes: str,
    total_votes: str,
) -> tuple[str, str, str]:
    """Return (existing offeror+special, special-only, formatted empty after-purchase placeholder)."""
    d = parse_number(offeror_votes) or 0.0
    g = parse_number(special_votes) or 0.0
    j = parse_number(total_votes)
    if not j:
        return "", "", ""
    existing = format_pct((d + g) / j * 100)
    special = format_pct(g / j * 100)
    return existing, special, ""


def parse_holding_pct_from_text(text: str) -> str:
    if not text:
        return ""
    text = strip_html(text)
    match = re.search(r"(?:所有割合|株券等所有割合)[^\d]{0,20}(\d+(?:\.\d+)?)\s*[%％]", text)
    if match:
        return format_pct(float(match.group(1)))
    percents = re.findall(r"(\d+(?:\.\d+)?)\s*[%％]", text)
    if percents:
        return format_pct(float(percents[-1]))
    return ""
