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


def _comma_number(raw: str) -> str:
    return raw.replace("，", ",")


def summarize_price(text: str) -> str:
    """Summarize consideration as yen/share, won/share, or share-for-share."""
    if not text:
        return ""
    compact = re.sub(r"\s+", "", strip_html(text))
    match = re.search(
        r"普通株式[1１]株につき、?(?:公開買付者(?:の)?)?普通株式([0-9]+(?:\.[0-9]+)?)株",
        compact,
    )
    if match:
        return f"株式対価 {match.group(1)}株"
    match = re.search(r"[1１]株につき、?金?([\d,，]+)ウォン", compact)
    if match:
        return f"{_comma_number(match.group(1))}ウォン/株"
    match = re.search(r"普通株式[1１]株につき、?金?([\d,，]+)円", compact)
    if match:
        return f"{_comma_number(match.group(1))}円/株"
    match = re.search(r"[1１]株につき、?金?([\d,，]+)円", compact)
    if match:
        return f"{_comma_number(match.group(1))}円/株"
    match = re.search(r"普通株式[^。]{0,40}?金([\d,，]+)円", compact)
    if match:
        return f"{_comma_number(match.group(1))}円/株"
    match = re.search(r"(?:公開買付価格|買付け等の価格)[^。]{0,40}?金([\d,，]+)円", compact)
    if match:
        return f"{_comma_number(match.group(1))}円/株"
    match = re.search(r"金([\d,，]+)円", compact)
    if match:
        return f"{_comma_number(match.group(1))}円"
    return compact[:200]


RESULT_SUCCESS = "成立"
RESULT_SUCCESS_PRORATA = "成立（按分）"
RESULT_FAILURE = "不成立"
RESULT_WITHDRAWN = "撤回"

def _parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = raw.replace(",", "").replace("，", "")
    if not digits.isdigit():
        return None
    return int(digits)


def parse_tob_result_counts(text: str) -> tuple[int | None, int | None, int | None]:
    """Return (tendered, minimum, maximum) share/unit counts from the result text."""
    if not text:
        return None, None, None
    compact = re.sub(r"\s+", "", strip_html(text))
    tendered = None
    for pattern in (
        r"応募(?:株券等|投資口|株式|新株予約権)(?:の(?:総数|合計|数の合計))?[（(]([\d,，]+)(?:株|口|個)",
        r"応募(?:株券等|投資口|株式)の(?:総数|合計|数の合計)は([\d,，]+)(?:株|口)",
        r"総数[（(]([\d,，]+)(?:株|口)",
    ):
        match = re.search(pattern, compact)
        if match:
            tendered = _parse_int(match.group(1))
            break
    if tendered is None and re.search(r"応募[^.。]{0,40}ありませんでした|応募株券等はありませんでした", compact):
        tendered = 0

    no_floor = bool(re.search(r"下限(?:及び上限)?[をは]?(?:設定して|定めて)おりません", compact))
    no_cap = bool(re.search(r"上限(?:及び下限)?[をは]?(?:設定して|定めて)おりません", compact))
    floor = None if no_floor else _last_bound(compact, "下限")
    cap = None if no_cap else _last_bound(compact, "上限")
    return tendered, floor, cap


def _last_bound(compact: str, label: str) -> int | None:
    matches = re.findall(rf"{label}[（(]([\d,，]+)(?:株|口|個)", compact)
    if matches:
        return _parse_int(matches[-1])
    return None


def judge_tob_result(text: str, *, withdrawn: bool = False) -> str:
    """Classify a TOB as 成立 / 成立（按分） / 不成立 / 撤回 from the report text."""
    if withdrawn:
        return RESULT_WITHDRAWN
    if not text or not str(text).strip():
        return ""
    compact = re.sub(r"\s+", "", strip_html(text))

    prorata = "あん分比例" in compact or "按分比例" in compact or (
        "上限を超えた" in compact and "超えなかった" not in compact
    )
    buy_none = "全部の買付け等を行いません" in compact and "超える部分" not in compact
    buy_all = "全部の買付け等を行います" in compact or "全部の買付けを行います" in compact
    below_min = bool(re.search(r"下限.{0,80}満たなかった", compact)) or bool(
        re.search(r"下限.{0,80}満たないため", compact)
    )
    tender_none = bool(
        re.search(
            r"応募(?:された)?(?:対象者)?(?:普通株式|株券等|投資口|株式)[^.。]{0,30}ありませんでした"
            r"|応募株券等はありませんでした"
            r"|買付け等の対象となる株券等はありません",
            compact,
        )
    )

    if below_min or (buy_none and not prorata):
        return RESULT_FAILURE
    if tender_none and not buy_all:
        return RESULT_FAILURE
    if prorata:
        return RESULT_SUCCESS_PRORATA
    if buy_all:
        return RESULT_SUCCESS

    tendered, floor, cap = parse_tob_result_counts(compact)
    if tendered is not None:
        if floor is not None and tendered < floor:
            return RESULT_FAILURE
        if cap is not None and tendered > cap:
            return RESULT_SUCCESS_PRORATA
        return RESULT_SUCCESS
    return ""


def _first_count(compact: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            value = _parse_int(match.group(1))
            if value is not None:
                return value
    return None


def parse_self_tob_report_counts(acquired_text: str, prorata_text: str = "") -> dict[str, str]:
    """Parse 応募数・買付数・按分 from self-tender report text blocks."""
    empty = {
        "ApplicationCount": "",
        "PurchaseCount": "",
        "ProrataUsed": "",
    }
    if not acquired_text and not prorata_text:
        return empty

    compact = re.sub(r"\s+", "", strip_html(acquired_text))
    prorata_compact = re.sub(r"\s+", "", strip_html(prorata_text))

    application = _first_count(
        compact,
        (
            r"応募(?:株数|数|普通株式数|上場株券等数)[（(]([\d,，]+)(?:株|口|個)",
            r"応募(?:された)?(?:普通株式|上場株券等|株券等)(?:の)?(?:数|総数|合計)[（(]([\d,，]+)(?:株|口|個)",
            r"応募(?:普通株式|上場株券等|株券等)[^。]{0,30}?([\d,，]+)(?:株|口|個)",
        ),
    )
    purchase = _first_count(
        compact,
        (
            r"買付(?:株数|数|普通株式数|上場株券等数)[（(]([\d,，]+)(?:株|口|個)",
            r"買付け等(?:を行った|により取得した|により買い付けた)(?:普通株式|上場株券等|株券等)(?:の)?(?:数|総数|合計)[（(]([\d,，]+)(?:株|口|個)",
            r"買付(?:普通株式|上場株券等|株券等)[^。]{0,30}?([\d,，]+)(?:株|口|個)",
        ),
    )

    prorata = bool(prorata_compact.strip())
    if not prorata:
        prorata = bool(re.search(r"あん分比例|按分比例", compact))
    if not prorata and prorata_compact:
        prorata = bool(re.search(r"あん分比例|按分比例", prorata_compact))
    if not prorata and application is not None and purchase is not None and application > purchase:
        prorata = True

    prorata_used = ""
    if application is not None or purchase is not None or prorata_compact:
        prorata_used = "Yes" if prorata else "No"

    return {
        "ApplicationCount": f"{application:,}" if application is not None else "",
        "PurchaseCount": f"{purchase:,}" if purchase is not None else "",
        "ProrataUsed": prorata_used,
    }


def judge_self_tob_result(acquired_text: str, prorata_text: str = "", *, withdrawn: bool = False) -> str:
    """Classify a self-tender report as 成立 / 成立（按分） / 不成立 / 撤回."""
    if withdrawn:
        return RESULT_WITHDRAWN
    counts = parse_self_tob_report_counts(acquired_text, prorata_text)
    application_raw = counts.get("ApplicationCount") or ""
    purchase_raw = counts.get("PurchaseCount") or ""
    application = _parse_int(application_raw.replace(",", "")) if application_raw else None
    purchase = _parse_int(purchase_raw.replace(",", "")) if purchase_raw else None
    prorata = counts.get("ProrataUsed") == "Yes"

    combined = re.sub(r"\s+", "", strip_html(acquired_text + "\n" + prorata_text))
    if re.search(r"全部の買付け等を行いません|下限.{0,80}満たなかった|応募(?:株券等|普通株式)はありませんでした", combined):
        return RESULT_FAILURE
    if purchase == 0 or (application == 0 and purchase is not None):
        return RESULT_FAILURE
    if prorata:
        return RESULT_SUCCESS_PRORATA
    if purchase is not None and purchase > 0:
        return RESULT_SUCCESS
    return judge_tob_result(combined)


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


def format_sec_code(raw: str) -> str:
    """Normalize EDINET/API 5-digit securities codes to a 4-digit ticker."""
    text = (raw or "").strip()
    if not text:
        return ""
    digits = text.replace("，", ",").replace(",", "")
    if digits.isdigit() and len(digits) == 5:
        return digits[:4]
    return text


DELISTING_DONE = "上場廃止済"
DELISTING_PLANNED = "上場廃止予定"
LISTING_MAINTAINED = "上場維持"


def has_listing_maintain_signal(text: str) -> bool:
    if not text:
        return False
    compact = re.sub(r"\s+", "", strip_html(text))
    return bool(
        re.search(
            r"上場廃止を企図しておらず|上場廃止を企図していない|上場が維持される予定|上場を維持|上場が維持される",
            compact,
        )
    )


def has_delisting_planned_signal(text: str) -> bool:
    if not text:
        return False
    compact = re.sub(r"\s+", "", strip_html(text))
    if has_listing_maintain_signal(compact):
        return False
    return bool(
        re.search(
            r"上場廃止となる予定|上場廃止を企図|上場廃止となる可能性|上場廃止される|"
            r"上場廃止となる|非公開化することを企図|株式の非公開化|完全子会社化|完全子会社とする",
            compact,
        )
    )


SPONSOR_SUBJECT_SKIP = re.compile(
    r"^(?:公開買付者|対象者|当社|本公開|普通株式|株券|本書|前記|上記|なお|また|さらに|ただし|但し|"
    r"公開買付者ら|対象者グループ|本取引|本公開買付|本デュー)"
)


def _split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    text = strip_html(text)
    chunks = re.split(r"\n\s*\n+", text)
    if len(chunks) <= 1:
        chunks = re.split(r"(?<=[。．])\s+", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _subject_before_wa(text: str) -> str:
    match = re.match(r"^(.{1,80}?)は、", text.strip())
    if not match:
        return ""
    subject = match.group(1).strip()
    subject = re.sub(r"^[（(][^）)]*[）)]\s*", "", subject)
    subject = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", subject)
    if not subject or SPONSOR_SUBJECT_SKIP.match(subject):
        return ""
    if len(subject) < 2:
        return ""
    return subject[:80]


def extract_overview_section(text: str) -> str:
    """Return the (1) 本公開買付の概要 subsection from purposes/overview text."""
    if not text:
        return ""
    plain = strip_html(text)
    match = re.search(
        r"(?:[(（]?\s*[1１]\s*[)）]?\s*)?(?:【)?本公開買付(?:け)?の概要(?:】)?(.+?)"
        r"(?=(?:[(（]?\s*[2２]\s*[)）]?)|(?:【)?本公開買付(?:け)?の|算定の|"
        r"(?:[(（]?\s*[2２]\s*[)）]?\s*)?(?:【)?本公開買付|$)",
        plain,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return ""


def extract_sponsor_from_purposes(text: str) -> str:
    """Extract the subject before 'は、' in the 2nd paragraph of 本公開買付の概要."""
    overview = extract_overview_section(text)
    if not overview:
        overview = text
    paragraphs = _split_paragraphs(overview)
    if len(paragraphs) >= 2:
        sponsor = _subject_before_wa(paragraphs[1])
        if sponsor:
            return sponsor
    for paragraph in paragraphs[1:3]:
        sponsor = _subject_before_wa(paragraph)
        if sponsor:
            return sponsor
    return ""


MBO_PATTERN = re.compile(
    r"ＭＢＯ|MBO|マネジメント[・･]?バイアウト|"
    r"経営陣(?:による|が).{0,24}(?:公開買付|ＴＯＢ|TOB)|"
    r"本ＭＢＯ(?:公開買付|取引)"
)


def detect_mbo(texts: list[str]) -> str:
    """Return 'Yes' when the filing narrative indicates an MBO."""
    combined = "\n".join(text for text in texts if text)
    if not combined:
        return ""
    compact = re.sub(r"\s+", "", strip_html(combined))
    if "マネジメントプレゼンテーション" in compact:
        compact = compact.replace("マネジメントプレゼンテーション", "")
    return "Yes" if MBO_PATTERN.search(compact) else ""


def extract_valuation_basis_section(text: str, *, limit: int = 2500) -> str:
    """Return the 算定の基礎 portion of the price text block."""
    if not text:
        return ""
    plain = strip_html(text)
    match = re.search(
        r"算定の基礎(.+?)(?:算定の経緯|（本公開買付価格|（注|※|$)",
        plain,
        flags=re.DOTALL,
    )
    if match:
        return match.group(0)[:limit]
    idx = plain.find("算定の基礎")
    if idx >= 0:
        return plain[idx : idx + limit]
    return ""


def _parse_yen_range(label_pattern: str, text: str) -> tuple[str, str]:
    match = re.search(
        rf"{label_pattern}[：:\s]*([\d,，]+)\s*円\s*(?:から|～|〜|~|-)\s*([\d,，]+)\s*円",
        text,
    )
    if not match:
        return "", ""
    return _comma_number(match.group(1)), _comma_number(match.group(2))


def parse_valuation_ranges(text: str) -> dict[str, str]:
    """Parse per-method share-value ranges from 算定の基礎."""
    basis = extract_valuation_basis_section(text, limit=5000) or strip_html(text)
    compact = re.sub(r"\s+", " ", basis)
    market_min, market_max = _parse_yen_range(r"市場株価(?:法|平均法)", compact)
    comparable_min, comparable_max = _parse_yen_range(
        r"類似(?:上場)?(?:会社)?比較法",
        compact,
    )
    dcf_min, dcf_max = _parse_yen_range(r"(?:DC|ＤＣ)F法", compact)
    return {
        "ValuationMarketMin": market_min,
        "ValuationMarketMax": market_max,
        "ValuationComparableMin": comparable_min,
        "ValuationComparableMax": comparable_max,
        "ValuationDCFMin": dcf_min,
        "ValuationDCFMax": dcf_max,
    }


def parse_planned_purchase_counts(text: str) -> dict[str, str]:
    """Return planned share counts from the 合計 row in section 4(3)."""
    empty = {
        "PlannedSharesMin": "",
        "PlannedSharesMax": "",
        "PlannedSharesPlanned": "",
    }
    if not text:
        return empty
    compact = re.sub(r"\s+", "", strip_html(text))
    total_matches = list(re.finditer(r"合計", compact))
    section = compact[total_matches[-1].start() : total_matches[-1].start() + 800] if total_matches else compact

    no_floor = bool(re.search(r"下限(?:及び上限)?[をは]?(?:設定して|定めて)おりません", section))
    no_cap = bool(re.search(r"上限(?:及び下限)?[をは]?(?:設定して|定めて)おりません", section))
    floor = None if no_floor else _last_bound(section, "下限")
    cap = None if no_cap else _last_bound(section, "上限")

    planned = ""
    if floor is None and cap is None:
        match = re.search(r"買付予定数[（(]?([\d,，]+)(?:株|口|個)", section)
        if match:
            value = _parse_int(match.group(1))
            if value is not None:
                planned = f"{value:,}"

    return {
        "PlannedSharesMin": f"{floor:,}" if floor is not None else "",
        "PlannedSharesMax": f"{cap:,}" if cap is not None else "",
        "PlannedSharesPlanned": planned,
    }


def parse_planned_purchase_bounds(text: str) -> tuple[str, str]:
    """Backward-compatible wrapper for min/max only."""
    parsed = parse_planned_purchase_counts(text)
    return parsed["PlannedSharesMin"], parsed["PlannedSharesMax"]


def parse_purchase_consideration(text: str) -> str:
    """Extract 買付代金（a) from section 8 with its currency unit."""
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", strip_html(text))
    match = re.search(
        r"買付代金[（(]?[ａaAＡ][)）]?[：:\s]*([\d,，]+)\s*(円|ウォン|ドル|USD|米ドル)",
        compact,
    )
    if match:
        unit = match.group(2)
        if unit == "USD":
            unit = "米ドル"
        return f"{_comma_number(match.group(1))}{unit}"
    return ""


def _trim_agent_name(text: str) -> str:
    candidate = clean_extracted_name(text)
    candidate = re.sub(r"\s+(?:名称|氏名又は名称)\s*$", "", candidate).strip()
    candidate = re.sub(r"\s+(?:所在地|最寄|電話).*$", "", candidate).strip()
    return candidate[:120]


def extract_tender_offer_agent(application_text: str, cover_agent_name: str = "") -> str:
    """Extract the tender offer agent from section 7(1) or the cover page."""
    cover = _trim_agent_name(cover_agent_name)
    if cover and cover not in {"－", "-", "該当なし", "なし"}:
        return cover
    if not application_text:
        return ""
    plain = strip_html(application_text)
    match = re.search(
        r"[①１]\s*公開買付代理人.{0,160}?(?:名称|氏名又は名称)[:：]?\s*([^\n\r、。]{2,120})",
        plain,
    )
    if match:
        return _trim_agent_name(match.group(1))
    match = re.search(
        r"[①１]\s*公開買付代理人\s*([^。\n\r]{2,120}?)(?:所在地|最寄|電話|②|$)",
        plain,
    )
    if match:
        candidate = _trim_agent_name(match.group(1))
        if candidate and not candidate.startswith("("):
            return candidate
    return ""


def judge_target_delisting(
    result_note: str,
    listing_category: str,
    texts: list[str],
) -> str:
    """Infer whether the target is delisted or expected to delist."""
    result = (result_note or "").strip()
    if result in {"不成立", "撤回"}:
        return ""

    combined = "\n".join(text for text in texts if text)
    maintain = has_listing_maintain_signal(combined)
    planned = has_delisting_planned_signal(combined)
    listing = (listing_category or "").strip()

    if listing == "非上場" and result.startswith("成立"):
        return DELISTING_DONE
    if maintain:
        return LISTING_MAINTAINED
    if planned:
        return DELISTING_PLANNED
    return ""
