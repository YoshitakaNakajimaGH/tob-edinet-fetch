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


def detect_prorata_used(acquired_text: str, prorata_text: str = "") -> str:
    """Return Yes/No for 按分 without populating application/purchase counts."""
    return parse_self_tob_report_counts(acquired_text, prorata_text).get("ProrataUsed", "")


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
    # 「上場を維持するために必要なコスト」は、上場をやめる理由であり、維持決定ではない。
    return bool(
        re.search(
            r"上場廃止を企図しておらず|上場廃止を企図していない|"
            r"上場が維持される予定|上場が維持される|"
            r"上場を維持する予定|上場を維持します|上場を維持いたします",
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
    r"公開買付者ら|対象者グループ|本取引|本公開買付|本デュー|"
    r"今般|この度|本件(?:両)?公開買付|本件両公開買付けに関連して)"
)

PARENT_NAME_BLOCKLIST = frozenset(
    {
        "東京証券取引所",
        "株式会社東京証券取引所",
        "大阪証券取引所",
        "株式会社大阪証券取引所",
        "名古屋証券取引所",
        "福岡証券取引所",
        "札幌証券取引所",
        "AP及び本ファンド",
        "本ファンド",
    }
)

FUND_OFFEROR_RE = re.compile(
    r"ファンド|Fund|L\.P\.|LLC|LLP|SPC|Limited\s+Partnership|"
    r"リミテッド・パートナーシップ|Investment\s+Holdings|インベストメント|"
    r"BidCo|HoldCo|バリュー・ファンド|Value\s+Fund",
    re.IGNORECASE,
)

FUND_CONTEXT_RE = re.compile(
    r"リミテッド・パートナーシップ|ケイマン諸島法|\bL\.P\.|"
    r"(?:PE|ＰＥ)(?:ファンド|ファンド運用)|プライベート・?エクイティ(?:ファンド)?|"
    r"(?:本|当該|当)(?:ファンド|リミテッド)|"
    r"(?:GP|ＧＰ)(?:投資|ファンド)|有限責任組合|"
    r"(?:持分|出資)(?:の全て|を全て|全部)(?:を)?(?:保有|所有|運用).{0,60}(?:ファンド|Fund|L\.P\.|組合|キャピタル)|"
    r"(?:ファンド|Fund|L\.P\.|組合|キャピタル).{0,80}(?:持分|出資)(?:の全て|を全て|全部)(?:を)?(?:保有|所有|運用)",
    re.IGNORECASE,
)

from tob.pe_sponsor_catalog import PE_SPONSOR_RULES

UNLISTED_LABEL = "非上場"

PE_CANONICAL_LABELS = frozenset(label for _, label in PE_SPONSOR_RULES)

NARRATIVE_SPONSOR_RE = re.compile(
    r"今般|この度|本件(?:両)?公開買付|に関連して|所有割合|前提条件|第三者割当|"
    r"が運用する|当該プライベート|各企業並びに|関係会社及び|設立された資産運用|"
    r"その発行済|及びそのグループ|は当該|を目的として|を主たる|を主な|"
    r"^その|^本件|^今般|^この度|^公開買付者|^LP[（(]|^LLP[（(]|^SATM及び|"
    r"直接的又|が直接的",
)

COMPANY_NAME_HINT_RE = re.compile(
    r"株式会社|有限会社|合同会社|ホールディングス|グループ|"
    r"Co\.|Ltd|LLC|LLP|L\.P\.|Limited|Partners|Capital|キャピタル|ファンド|"
    r"Inc\.|Corp\.|Corporation|Pte\.?\s*Ltd|SBIHD",
    re.IGNORECASE,
)


def sanitize_sponsor_name(name: str) -> str:
    """Trim narrative noise and incomplete parenthetical aliases from a sponsor name."""
    candidate = re.sub(r"\s+", "", strip_html(name)).strip("　 ")
    candidate = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", candidate)
    candidate = re.sub(r"[（(]以下[「『][^」』]*$", "", candidate)
    candidate = re.sub(r"[（(][^）)]*$", "", candidate)
    candidate = re.sub(r"及びそのグループ.*$", "", candidate)
    candidate = re.sub(r"が運用する.*$", "", candidate)
    candidate = re.sub(r"は当該.*$", "", candidate)
    alias = re.search(r"^(.+?)[（(]以下[「『]([^」』]+)[」』]", candidate)
    if alias:
        candidate = alias.group(1) or alias.group(2)
    split_and = re.match(r"^(?:LLC|LLP|LP|Inc|Ltd)及び(.+)$", candidate, re.I)
    if split_and:
        candidate = split_and.group(1)
    if re.match(r"^(?:であり|一方|加え|なお|また|更に|他方|もっとも|加えて)", candidate):
        company = re.search(
            r"((?:株式会社|有限会社|合同会社).{1,40}|[^、。]{2,40}?(?:株式会社|ホールディングス|グループ))$",
            candidate,
        )
        if company:
            candidate = company.group(1)
    candidate = candidate.strip("、。，．及びはがをにの")
    if candidate == "SBIHD":
        candidate = "SBIホールディングス"
    return candidate[:80]


def is_acceptable_sponsor_name(name: str) -> bool:
    if not name or name in PARENT_NAME_BLOCKLIST:
        return False
    if name in PE_CANONICAL_LABELS:
        return True
    if SPONSOR_SUBJECT_SKIP.match(name):
        return False
    if NARRATIVE_SPONSOR_RE.search(name):
        return False
    if re.search(r"[「」]", name):
        return False
    if re.search(r"について|以外|（注|から\d|円", name):
        return False
    if re.match(r"^(?:加え|一方|なお|また|であり|又は|本件|本取引|公開買付|対象者)", name):
        return False
    if "、" in name:
        return False
    if name.endswith(("（", "(", "、", "及び", "である", "に", "を", "が", "は", "及")):
        return False
    if len(name) > 60 and not COMPANY_NAME_HINT_RE.search(name):
        return False
    if not COMPANY_NAME_HINT_RE.search(name) and len(name) > 24:
        return False
    return True


def _finalize_sponsor_candidate(name: str) -> str:
    cleaned = sanitize_sponsor_name(name)
    if not is_acceptable_sponsor_name(cleaned):
        return ""
    return cleaned


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
    return _finalize_sponsor_candidate(subject[:80])


_OVERVIEW_HEAD = re.compile(
    r"(?:[（(]\s*[1１]\s*[)）]\s*)?"
    r"(?:本件両|本両|本件|本)?公開買付(?:け)?の概要"
)
_OVERVIEW_END = re.compile(r"[（(]\s*[2２]\s*[)）]|【[^】]{1,30}】")


def offer_overview_window(text: str, limit: int = 1800) -> str:
    """Plain text right after （１）本公開買付の概要, until （２） or the next 【heading】.

    Sponsor names are read only from this opening. A mention later in the
    filing (directors' former employers, product standards, corporate history)
    is not a sponsor.
    """
    if not text:
        return ""
    plain = strip_html(text)
    match = _OVERVIEW_HEAD.search(plain)
    if not match:
        return ""
    rest = plain[match.end() :]
    end = _OVERVIEW_END.search(rest)
    chunk = rest[: end.start()] if end else rest
    return chunk.strip()[:limit]


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


_PARENT_LABEL_PATTERN = re.compile(
    r"([^。、\n]{2,80}?)[（(]以下[「『]"
    r"(?:公開買付者親会社|.+?親会社|.+?ファンド|.+?グループ)"
)


def _clean_parent_candidate(name: str) -> str:
    candidate = re.sub(r"\s+", "", strip_html(name)).strip("　 ")
    candidate = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", candidate)
    if not candidate or SPONSOR_SUBJECT_SKIP.match(candidate):
        return ""
    if len(candidate) < 2 or len(candidate) > 80:
        return ""
    return candidate


def _reject_parent_candidate(name: str) -> str:
    return _finalize_sponsor_candidate(name)


def extract_pe_sponsor_name(text: str) -> str:
    if not text:
        return ""
    plain = strip_html(text)
    # A full filing is searched only in the opening of （１）本公開買付の概要.
    # A short snippet with no heading is still scanned, so catalog tests stay local.
    if _OVERVIEW_HEAD.search(plain):
        plain = offer_overview_window(plain)
        if not plain:
            return ""
    for pattern, label in PE_SPONSOR_RULES:
        if pattern.search(plain):
            return label
    compact = re.sub(r"\s+", "", plain)
    for pattern in (
        r"((?:[A-ZＡ-Ｚ][A-ZＡ-Ｚ0-9・･\s]{1,40}?)(?:ファンド|Fund|キャピタル|Capital))",
        r"((?:[A-ZＡ-Ｚ]{2,}(?:[・･\s][A-ZＡ-Ｚ]{2,}){0,4})[^。、（(]{0,24}(?:ファンド|Fund|キャピタル|Capital))",
    ):
        match = re.search(pattern, compact)
        if match:
            raw = re.split(r"[（(]以下", match.group(1))[0]
            cleaned = _finalize_sponsor_candidate(raw)
            if cleaned:
                return cleaned
    return ""


def is_fund_offeror(
    offeror_name: str,
    *,
    purposes_raw: str = "",
    overview_raw: str = "",
    offeror_edinet_code: str = "",
    edinet_list: object | None = None,
) -> bool:
    if edinet_list is not None:
        label = edinet_list.listing_label(name=offeror_name, edinet_code=offeror_edinet_code)
        if label and label.isdigit():
            return False
    if FUND_OFFEROR_RE.search(offeror_name or ""):
        return True
    overview = extract_overview_section(f"{purposes_raw}\n{overview_raw}") or purposes_raw
    return bool(FUND_CONTEXT_RE.search(overview))


def extract_parent_company_name(text: str) -> str:
    """Extract parent/sponsor company name from narrative text."""
    if not text:
        return ""
    plain = strip_html(text)
    compact = re.sub(r"\s+", "", plain)

    label_match = _PARENT_LABEL_PATTERN.search(plain)
    if label_match:
        cleaned = _reject_parent_candidate(label_match.group(1))
        if cleaned:
            return cleaned

    for pattern in (
        r"([^（(、。\n]{2,40})（以下[^）]{0,80}）が(?:その|公開買付者の)?発行済(?:株式|持分)の(?:全て|全部)を(?:所有|保有)",
        r"公開買付者親会社(?:である|は|として)?([^。、\n（(]{2,80}?)[（(]以下",
        r"親会社(?:である|は|として)?([^。、\n（(]{2,80}?)[（(]以下",
        r"公開買付者の完全親会社(?:である|は|として)?([^。、\n（(]{2,80}?)(?:は|が|を|の|に)",
        r"完全親会社(?:である|は|として)?([^。、\n（(]{2,80}?)(?:は|が|を|の|に)",
        r"([^。、\n（(]{2,80}?)が公開買付者の完全親会社",
        r"資産運用会社である([^（(]{2,60}?)[（(]以下",
        r"([^。、\n（(]{2,80}?)及びその完全子会社",
        r"その(?:完全)?(?:親会社|子会社)(?:である|は|として)?([^。、\n（(]{2,80}?)[（(]以下",
        r"([^。、\n（(]{2,80}?)(?:の(?:完全子会社|子会社)である|を(?:完全)?子会社化)",
        r"([^。、\n（(]{2,80}?)が(?:その|当該)?(?:持分|出資|株式)(?:の全て|を全て|全部)(?:を)?(?:保有|所有|運用)",
    ):
        match = re.search(pattern, compact)
        if match:
            cleaned = _reject_parent_candidate(match.group(1))
            if cleaned:
                return cleaned
    return ""


def extract_mbo_sponsor_signal(text: str) -> bool:
    """True when narrative indicates an individual owns 100% of the offeror (MBO SPV)."""
    if not text:
        return False
    compact = re.sub(r"\s+", "", strip_html(text))
    return bool(
        re.search(
            r"代表取締役[^。]{0,40}?(?:氏|が)[^。]{0,80}?(?:100%|１００％|全部|全て|すべて)(?:を)?(?:所有|保有)",
            compact,
        )
        or re.search(
            r"発行済(?:株式|出資)(?:の全て|を全て|全部)(?:を)?[^。]{0,40}?(?:氏|が)(?:所有|保有)",
            compact,
        )
    )


def extract_parent_hint(text: str) -> str:
    """Rule-based parent/sponsor name from 買付け等の目的 (no web search)."""
    if not text:
        return ""
    parent = extract_parent_company_name(text)
    if parent:
        return parent
    pe = extract_pe_sponsor_name(text)
    if pe:
        return pe
    sponsor = extract_sponsor_from_purposes(text)
    if sponsor:
        return sponsor
    return ""


def resolve_sponsor_hint(
    *,
    offeror_name: str = "",
    offeror_edinet_code: str = "",
    purposes_raw: str = "",
    overview_raw: str = "",
    opinion_raw: str = "",
    corporation_info_raw: str = "",
    major_shareholders_raw: str = "",
    officer_history_raw: str = "",
    is_mbo: str = "",
    edinet_list: object | None = None,
) -> str:
    """Unified SponsorHint: fund/PE name, listed sec code, 非上場, or blank."""
    purposes = purposes_raw or ""
    overview = overview_raw or ""
    opinion = opinion_raw or ""
    combined = "\n".join(
        part
        for part in (
            purposes,
            overview,
            corporation_info_raw,
            major_shareholders_raw,
            officer_history_raw,
            opinion,
        )
        if part
    )

    if edinet_list is not None:
        listed_offeror = edinet_list.listing_label(
            name=offeror_name,
            edinet_code=offeror_edinet_code,
        )
        if listed_offeror and listed_offeror.isdigit():
            return listed_offeror

    window = offer_overview_window("\n".join(part for part in (purposes, overview) if part))
    if is_fund_offeror(
        offeror_name,
        purposes_raw=purposes,
        overview_raw=overview,
        offeror_edinet_code=offeror_edinet_code,
        edinet_list=edinet_list,
    ):
        for extractor in (extract_pe_sponsor_name, extract_parent_company_name, extract_sponsor_from_purposes):
            value = extractor(window)
            if not value:
                continue
            if value in PE_CANONICAL_LABELS:
                return value
            finalized = _finalize_sponsor_candidate(value)
            if finalized:
                return finalized
        return ""

    parent_name = extract_parent_company_name(window) or extract_sponsor_from_purposes(window)
    parent_name = _finalize_sponsor_candidate(parent_name)
    if not parent_name:
        pe_name = extract_pe_sponsor_name(window)
        if pe_name:
            return pe_name
    mbo = is_mbo == "Yes" or detect_mbo([combined, opinion]) == "Yes"
    if mbo and (extract_mbo_sponsor_signal(opinion or combined) or not parent_name):
        return UNLISTED_LABEL

    listing_label = ""
    if edinet_list is not None:
        if parent_name:
            listing_label = edinet_list.listing_label(name=parent_name)
            if listing_label:
                return listing_label
            return UNLISTED_LABEL
        listing_label = edinet_list.listing_label(
            name=offeror_name,
            edinet_code=offeror_edinet_code,
        )
        if listing_label:
            return listing_label

    if parent_name:
        return UNLISTED_LABEL
    return ""


_MBO_DEFINITION = re.compile(
    r"[「『]?(?:いわゆる)?マネジメント[・･]?バイアウト[（(](?:ＭＢＯ|MBO)[)）][」』]?とは[^。]{0,220}。"
)
_MBO_POSITIVE = re.compile(
    r"(?:本取引|本公開買付).{0,80}(?:マネジメント[・･]?バイアウト|ＭＢＯ|MBO)"
    r".{0,40}該当(?:します|する(?!もの)|し(?!ない|ません|ておりません))|"
    r"(?:マネジメント[・･]?バイアウト|ＭＢＯ|MBO).{0,16}の一環|"
    r"(?:マネジメント[・･]?バイアウト|ＭＢＯ|MBO)として(?:実施|行われ)|"
    r"「(?:ＭＢＯ|MBO)の実施|"
    r"本(?:ＭＢＯ|MBO)(?:公開買付|取引|を|の|に|で)|"
    r"経営陣(?:による|が).{0,24}(?:公開買付|ＴＯＢ|TOB)"
)
_MBO_REJECT_AFTER = re.compile(
    r"該当しない|該当しません|該当いたしません|該当せず|"
    r"ではなく|ではありません|ものではない"
)


def detect_mbo(texts: list[str]) -> str:
    """Return 'Yes' only when this deal is described as an MBO.

    A mention that the deal is not an MBO, a definition footnote, a premium
    precedent (事例), or the listing-rule category ＭＢＯ等 does not count.
    """
    combined = "\n".join(text for text in texts if text)
    if not combined:
        return ""
    compact = re.sub(r"\s+", "", strip_html(combined))
    compact = compact.replace("マネジメントプレゼンテーション", "")
    compact = _MBO_DEFINITION.sub("", compact)
    compact = re.sub(r"(?:ＭＢＯ|MBO)等", "", compact)
    for match in _MBO_POSITIVE.finditer(compact):
        tail = compact[match.end() : match.end() + 24]
        if _MBO_REJECT_AFTER.search(tail):
            continue
        sentence_start = compact.rfind("。", 0, match.start()) + 1
        sentence = compact[sentence_start : match.end() + 24]
        if "事例" in sentence:
            continue
        return "Yes"
    return ""


_CURRENT_MARKET = re.compile(
    r"(プライム市場|スタンダード市場|グロース市場|"
    r"札幌証券取引所本則市場|札幌証券取引所アンビシャス|"
    r"福岡証券取引所|"
    r"名古屋証券取引所プレミア市場|名古屋証券取引所メイン市場|名古屋証券取引所ネクスト市場)"
)
_MARKET_LABELS = {
    "プライム市場": "東証プライム",
    "スタンダード市場": "東証スタンダード",
    "グロース市場": "東証グロース",
    "札幌証券取引所本則市場": "札証本則",
    "札幌証券取引所アンビシャス": "札証アンビシャス",
    "福岡証券取引所": "福証",
    "名古屋証券取引所プレミア市場": "名証プレミア",
    "名古屋証券取引所メイン市場": "名証メイン",
    "名古屋証券取引所ネクスト市場": "名証ネクスト",
}
_ALREADY_UNLISTED = re.compile(
    r"(?:対象者|当社)は非上場会社(?!となる)|"
    r"非上場会社である(?:対象者|当社)|"
    r"非上場会社のため|"
    r"(?:対象者|当社)株式は金融商品取引所に上場していない"
)


def detect_target_listing_status(text: str) -> str:
    """Current listing venue of the target, from the filing narrative.

    Shareholder-community names and 'already unlisted' beat a historical
    listing sentence. A market counts only when the same clause says the
    shares are listed, and a sentence about the offeror is ignored when a
    target sentence is available.
    """
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    if not compact:
        return ""
    best: tuple[int, int, str] | None = None
    for match in _CURRENT_MARKET.finditer(compact):
        after = compact[match.end() : match.end() + 16]
        if "上場" not in after:
            continue
        before = compact[max(0, match.start() - 90) : match.start()]
        score = 0
        if "本書提出日現在" in before:
            score += 5
        if re.search(r"対象者株式|当社株式|対象者の普通|当社の普通", before):
            score += 3
        if re.search(r"公開買付者(?:親会社|及び)?$", before[-20:]):
            score -= 4
        label = _MARKET_LABELS[match.group(1)]
        if "名古屋" in before[-30:] and label.startswith("東証"):
            continue
        candidate = (score, -match.start(), label)
        if best is None or candidate > best:
            best = candidate
    if best is not None and best[0] > 0:
        return best[2]
    if re.search(r"株主コミュニティ(?:の組成|における|銘柄)|に株主コミュニティ", compact):
        return "株主コミュニティ"
    if _ALREADY_UNLISTED.search(compact):
        return "非上場"
    if best is not None:
        return best[2]
    return ""


def parse_fairness_measures(text: str) -> dict[str, bool | None]:
    """Flags for the standard fairness measures. Unknown stays None."""
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    empty: dict[str, bool | None] = {
        "specialCommittee": None,
        "thirdPartyValuation": None,
        "legalAdvisor": None,
        "marketCheck": None,
        "majorityOfMinority": None,
    }
    if not compact:
        return empty

    special: bool | None = None
    if re.search(r"特別委員会を設置|特別委員会の設置", compact):
        special = True
    elif re.search(r"特別委員会は設置して(?:おりません|いない)", compact):
        special = False

    obtained = bool(
        re.search(
            r"株式価値算定書を取得|算定書を取得した|算定書を取得いたし|"
            r"第三者算定機関からの株式価値算定書の取得|算定書の取得|"
            r"第三者算定機関として|第三者算定機関に対して",
            compact,
        )
    )
    denied = bool(
        re.search(
            r"算定書は取得しておりません|算定書を取得しておりません|"
            r"第三者算定機関からの株式価値算定書は取得しておりません",
            compact,
        )
    )
    valuation: bool | None = True if obtained else False if denied else None

    legal: bool | None = (
        True
        if re.search(r"リーガル・アドバイザー|法律事務所からの助言|独立した法律事務所", compact)
        else None
    )

    market: bool | None = None
    if re.search(
        r"他の買付者からの買付機会を確保|対抗的な買付け等を行う機会を確保|"
        r"取引保護条項を含む合意(?:等)?(?:を|は)[^。]{0,24}(?:行って|して)おりません",
        compact,
    ):
        market = True
    elif re.search(r"取引保護条項を含む合意を(?:行って|して)おります", compact):
        market = False

    minority: bool | None = None
    if re.search(r"マジョリティ[・･]?オブ[・･]?マイノリティ|MajorityofMinority", compact, re.IGNORECASE):
        for sentence in re.split(r"。", compact):
            if "マジョリティ" not in sentence and "Minority" not in sentence:
                continue
            if re.search(r"設定して(?:おりません|いない|いません)|設定はして(?:おりません|いない)", sentence):
                minority = False
                break
            if re.search(r"設定して(?:おります|いる|います)|を設定し(?:、|た|ます)", sentence):
                minority = True
    return {
        "specialCommittee": special,
        "thirdPartyValuation": valuation,
        "legalAdvisor": legal,
        "marketCheck": market,
        "majorityOfMinority": minority,
    }


_AGREED_PARTY = re.compile(
    r"である([^（(]{2,40})[（(]以下[「『]([^」』]{1,40})[」』]といいます[。）)]+"
    r"[^。]{0,180}?所有株式(?:数)?[：:]([\d,，]+)株[、，]"
    r"所有割合(?:[（(]注[^)）]{0,8}[)）])?[：:]([\d.]+)[％%]"
)


def parse_agreed_tender(text: str) -> dict[str, object]:
    """Shares and ratio the offeror has already agreed will be tendered.

    The aggregate is the 本応募合意 total when the filing states one, otherwise
    the largest 合計で figure in an agreement sentence. Individual parties are
    kept when the name and the holding sit in the same sentence.
    """
    empty: dict[str, object] = {"shares": None, "ratio": None, "parties": []}
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    if not compact or "所有割合" not in compact or "応募" not in compact:
        return empty

    parties: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for match in _AGREED_PARTY.finditer(compact):
        name = match.group(2) or match.group(1)
        shares = _parse_int(match.group(3))
        ratio = _percent_ratio(match.group(4))
        if shares is None or ratio is None:
            continue
        key = (name, shares)
        if key in seen:
            continue
        seen.add(key)
        parties.append({"name": name, "shares": shares, "ratio": ratio})

    shares, ratio = _agreed_aggregate(compact)
    if shares is None and parties:
        shares = sum(int(item["shares"]) for item in parties)
        ratio = round(sum(float(item["ratio"]) for item in parties), 6)
    return {"shares": shares, "ratio": ratio, "parties": parties}


def _percent_ratio(raw: str) -> float | None:
    try:
        return round(float(raw) / 100, 6)
    except ValueError:
        return None


def _agreed_aggregate(compact: str) -> tuple[int | None, float | None]:
    labeled = re.search(
        r"本応募合意株主[^。]{0,220}?所有株式[：:]([\d,，]+)株[、，]所有割合[：:]([\d.]+)[％%]",
        compact,
    )
    if labeled:
        return _parse_int(labeled.group(1)), _percent_ratio(labeled.group(2))
    best: tuple[int, float] | None = None
    for match in re.finditer(r"合計で([\d,，]+)株[、，]所有割合[：:]([\d.]+)[％%]", compact):
        before = compact[max(0, match.start() - 90) : match.start()]
        if "応募" not in before and "合意" not in before:
            continue
        shares = _parse_int(match.group(1))
        ratio = _percent_ratio(match.group(2))
        if shares is None or ratio is None:
            continue
        if best is None or shares > best[0]:
            best = (shares, ratio)
    if best:
        return best
    return None, None


def parse_explicit_zero_holdings(text: str) -> dict[str, bool]:
    """True only when the filing states that holding is zero.

    A sentence about the offeror does not zero the special-related ratio.
    The いずれも sentence does, because it lists the offeror and the related parties together.
    """
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    existing = False
    special = False
    for match in re.finditer(
        r"(?:対象者|当社)株式を(?:所有|保有)して(?:おりません|いない)",
        compact,
    ):
        window = compact[max(0, match.start() - 160) : match.end()]
        if "公開買付者" not in window:
            continue
        existing = True
        if "いずれも" in window or "特別関係者" in window:
            special = True
    return {"existing": existing, "special": special}


def _party_name(raw: str) -> str:
    text = re.sub(r"（注\d*）|\(注\d*\)", "", raw or "")
    text = re.split(r"[（(]以下", text)[0]
    text = re.sub(r"^.*(?:本書提出日現在、|現在、)", "", text)
    text = text.rsplit("）", 1)[-1].rsplit(")", 1)[-1]
    text = text.rsplit("である", 1)[-1]
    text = text.strip(" 、，の")
    if not text or len(text) > 80 or "東京証券取引所" in text:
        return ""
    return text


def _overview_window(text: str) -> str:
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    stop = re.search(r"本公開買付けの実施を決定するに至った背景|対象者が本公開買付けに賛同するに至った", compact)
    if stop:
        compact = compact[: stop.start()]
    return compact[:4000]


def parse_buyer_structure(text: str, offeror_name: str = "") -> dict[str, str | None]:
    """Offeror, the fund or parent that owns it, and the manager, from the overview.

    Names that are not in that opening are left null. This does not look up EDINET.
    """
    opening = _overview_window(text)
    direct = ""
    manager = ""
    managed = re.search(
        r"([^（(。]{2,40})[（(]以下[^）)]{0,80}[）)]によって管理・運営される"
        r"([^（(]{2,80})(?:[（(]以下[^）)]{0,80}[）)])?"
        r"が公開買付者の発行済株式の(?:全部|全て|すべて)を所有",
        opening,
    )
    if managed:
        manager = _party_name(managed.group(1))
        direct = _party_name(managed.group(2))
    if not manager:
        served = re.search(
            r"([^（(。]{2,40})(?:[（(]以下「([^」]{2,40})」[^）)]{0,20}[）)])?がサービスを提供するファンド",
            opening,
        )
        if served:
            manager = _party_name(served.group(2) or served.group(1))
    if not direct:
        labeled = re.search(r"([^（(、。]{2,40})[（(]以下「公開買付者親会社」", opening)
        if labeled:
            direct = _party_name(labeled.group(1))
    ultimate = ""
    parent = re.search(r"の親会社である([^（(、。]{2,40})", opening[:2500])
    if parent:
        ultimate = _party_name(parent.group(1))
    buyer_type = None
    fund_owned = bool(manager) or bool(re.search(r"ファンド|投資事業有限責任組合|有限責任組合", direct))
    formed = "設立された株式会社" in opening
    if fund_owned and formed:
        buyer_type = "PE-backed SPC"
    elif not formed and re.search(r"公開買付者は、本書提出日現在、.{0,280}?所有しており", opening):
        buyer_type = "Strategic"
    return {
        "offeror": (offeror_name or "").strip() or None,
        "directParent": direct or None,
        "fundManager": manager or None,
        "ultimateSponsor": ultimate or None,
        "buyerType": buyer_type,
    }


def _money_amount(raw: str, unit: str) -> int | None:
    number = _parse_int(raw)
    if number is None:
        return None
    if unit == "千円":
        return number * 1000
    if unit == "百万円":
        return number * 1_000_000
    return number


def _lender_names(clause: str) -> list[str]:
    """The party named immediately before から. Several defined banks stay as a list."""
    fragment = clause.rsplit("。", 1)[-1]
    tail = fragment.rsplit("、", 1)[-1]
    tail = re.split(r"[（(]以下", tail)[0].strip("）)、，の ")
    if 2 <= len(tail) <= 40 and not tail.endswith("までに") and "といいます" not in tail:
        return [tail]
    names: list[str] = []
    for short in re.findall(r"以下「([^」]{2,30})」", clause):
        if short.startswith("本") or "総称" in short or "併せて" in short or short in names:
            continue
        names.append(short)
    return names


def _funding_window(compact: str) -> str:
    """The paragraph that says how the tender will be paid for.

    A cross-reference to section 8 is enough of an anchor. The own-cash sentence
    has no section number. Balance-sheet borrowings sit outside this window.
    """
    anchor = re.search(r"預金又は借入金等", compact)
    if anchor:
        chunk = compact[anchor.end() : anchor.end() + 900]
        stop = re.search(r"なお、対象者|なお、当社", chunk)
        if stop and stop.start() > 30:
            chunk = chunk[: stop.start()]
        return chunk
    own = re.search(r".{0,160}新たな資金調達は想定しておりません。?", compact)
    return own.group(0) if own else ""


def _defined_names(phrase: str) -> list[str]:
    names: list[str] = []
    for short in re.findall(r"以下「([^」]{2,30})」", phrase):
        if short.startswith("本") or "総称" in short or "併せて" in short or short in names:
            continue
        names.append(short)
    return names


def _party_tail(phrase: str) -> str | None:
    tail = phrase.rsplit("。", 1)[-1].rsplit("、", 1)[-1]
    tail = tail.rsplit("である", 1)[-1]
    tail = re.split(r"及び|並びに", tail)[-1]
    tail = re.split(r"までに", tail)[-1]
    tail = re.split(r"[（(]", tail)[0].strip("、 ）)の")
    if tail in {"金融機関", "銀行"} or not (2 <= len(tail) <= 40):
        return None
    if any(word in tail for word in ("資金", "予定", "記載", "一定")):
        return None
    return tail


def _lenders_without_cap(window: str) -> list[str]:
    """Banks named before 借入れ when the filing gives no cap."""
    match = re.search(r"(.{2,500}?)からの?(?:借入れ|借入|融資)", window)
    if not match:
        return []
    phrase = match.group(1)
    names = _defined_names(phrase)
    if names:
        return names
    tail = _party_tail(phrase)
    return [tail] if tail else []


def _equity_source_without_cap(window: str) -> str | None:
    match = re.search(r"から(?:の)?(?:一定の)?出資", window)
    if not match:
        return None
    clause = window[max(0, match.start() - 120) : match.start()]
    names = _defined_names(clause)
    if names:
        return names[-1]
    return _party_tail(clause)


def parse_financing(text: str) -> dict[str, object]:
    """Equity and debt for the tender, plus a pledge flag.

    A stated cap is kept as a cap. A bank named without a cap is still a lender,
    with amount null. Own cash and an explicit refusal of new funding set
    selfFunded. That refusal, with no loan beside it, is debt 0. A missing
    sentence stays null. Term-loan splits are included only when stated.
    """
    compact = re.sub(r"\s+", "", strip_html(text or ""))
    empty: dict[str, object] = {
        "equity": None,
        "equitySource": None,
        "debt": None,
        "lenders": [],
        "targetSharesPledged": None,
        "selfFunded": None,
    }
    if not compact:
        return empty
    equity = re.search(
        r"から([^0-9０-９]{0,60})([\d,，]+)(円|千円|百万円)を(?:上限|限度)と(?:して|する)出資",
        compact,
    )
    debt = re.search(
        r"から([^0-9０-９]{0,80})([\d,，]+)(円|千円|百万円)を(?:上限|限度)として借入",
        compact,
    )
    if equity:
        empty["equity"] = _money_amount(equity.group(2), equity.group(3))
        source = _lender_names(compact[max(0, equity.start() - 80) : equity.start()])
        empty["equitySource"] = source[0] if source else None
    if debt:
        empty["debt"] = _money_amount(debt.group(2), debt.group(3))
        clause = compact[max(0, debt.start() - 400) : debt.start()]
        names = _lender_names(clause)
        amount = empty["debt"] if len(names) == 1 else None
        empty["lenders"] = [{"name": name, "amount": amount} for name in names]
    window = _funding_window(compact)
    if window and not empty["lenders"]:
        empty["lenders"] = [{"name": name, "amount": None} for name in _lenders_without_cap(window)]
    if window and empty["equitySource"] is None:
        empty["equitySource"] = _equity_source_without_cap(window)
    if window and re.search(r"自己資金|自己資本|手元現金|新たな資金調達は想定しておりません", window):
        empty["selfFunded"] = True
    if (
        empty["debt"] is None
        and not empty["lenders"]
        and window
        and "新たな資金調達は想定しておりません" in window
        and not re.search(r"借入れ|借入|融資", window)
    ):
        empty["debt"] = 0
    if re.search(r"担保に供されることは予定されておりません|担保提供は予定されておりません", compact):
        empty["targetSharesPledged"] = False
    elif re.search(r"取得する(?:対象者|当社)株式が担保に供される", compact):
        empty["targetSharesPledged"] = True
    return empty


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
    patterns = (
        rf"{label_pattern}[：:\s]*([\d,，]+)\s*円\s*(?:から|～|〜|~|-)\s*([\d,，]+)\s*円",
        rf"{label_pattern}[：:\s]*([\d,，]+)円\s*(?:から|～|〜|~|-)\s*([\d,，]+)円",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _comma_number(match.group(1)), _comma_number(match.group(2))
    compact = re.sub(r"\s+", "", text)
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return _comma_number(match.group(1)), _comma_number(match.group(2))
    return "", ""


_VALUATION_PURPOSE_MARKERS = (
    "市場株価法",
    "市場株価平均法",
    "類似上場会社比較法",
    "類似会社比較法",
    "ＤＣＦ法",
    "DCF法",
    "株式価値算定書",
    "算定書",
    "第三者算定機関",
    "フェアネス・オピニオン",
)


def extract_valuation_from_purposes(text: str, *, limit: int = 8000) -> str:
    """Return valuation-relevant passages from 買付け等の目的 when absent from price."""
    if not text:
        return ""
    plain = strip_html(text)
    section_patterns = (
        r"[(（]3[)）][^。\n]{0,80}(?:公正性|算定|価格の決定|価格)",
        r"[(（]2[)）][^。\n]{0,120}(?:意思決定|算定|協議|背景|経緯)",
        r"本公開買付価格の公正性",
        r"株式価値の算定",
        r"第三者算定機関",
    )
    for pattern in section_patterns:
        match = re.search(pattern, plain)
        if not match:
            continue
        chunk = plain[match.start() : match.start() + limit]
        if any(marker in chunk for marker in _VALUATION_PURPOSE_MARKERS):
            return chunk[:limit]
    best_idx = -1
    for marker in _VALUATION_PURPOSE_MARKERS:
        idx = plain.find(marker)
        if idx >= 0 and (best_idx < 0 or idx < best_idx):
            best_idx = idx
    if best_idx >= 0:
        return plain[max(0, best_idx - 400) : best_idx + limit][:limit]
    return ""


def _empty_valuation_ranges() -> dict[str, str]:
    return {
        "ValuationMarketMin": "",
        "ValuationMarketMax": "",
        "ValuationComparableMin": "",
        "ValuationComparableMax": "",
        "ValuationDCFMin": "",
        "ValuationDCFMax": "",
    }


def parse_valuation_ranges(text: str) -> dict[str, str]:
    """Parse per-method share-value ranges from 算定の基礎."""
    basis = extract_valuation_basis_section(text, limit=5000) or strip_html(text)
    plain = strip_html(text)
    parsed = _parse_valuation_ranges_from_text(basis)
    if not any(parsed.values()) and plain and plain != basis:
        parsed = _parse_valuation_ranges_from_text(plain)
    return parsed


def _parse_valuation_ranges_from_text(text: str) -> dict[str, str]:
    compact = re.sub(r"\s+", " ", text)
    market_min, market_max = _parse_yen_range(
        r"市場株価(?:平均法|基準方式|法)",
        compact,
    )
    comparable_min, comparable_max = _parse_yen_range(
        r"類似(?:上場)?(?:会社)?比(?:較|準)(?:法|方式)",
        compact,
    )
    dcf_min, dcf_max = _parse_yen_range(
        r"(?:DCF|ＤＣＦ|DC|ＤＣ)[FＦ]?(?:法|方式)",
        compact,
    )
    return {
        "ValuationMarketMin": market_min,
        "ValuationMarketMax": market_max,
        "ValuationComparableMin": comparable_min,
        "ValuationComparableMax": comparable_max,
        "ValuationDCFMin": dcf_min,
        "ValuationDCFMax": dcf_max,
    }


def extract_special_committee_valuation(text: str, *, limit: int = 8000) -> str:
    """Section ⑤: 特別委員会の第三者算定機関による株式価値算定（優先ソース）。"""
    if not text:
        return ""
    plain = strip_html(text)
    section_patterns = (
        r"⑤[^\n]{0,240}特別委員会[^\n]{0,240}第三者算定",
        r"特別委員会における独立した第三者算定機関",
        r"⑤\s*特別委員会",
        r"フェアネス・オピニオン[^。\n]{0,120}算定",
        r"独立した第三者算定機関からの株式価値算定書及びフェアネス",
    )
    for pattern in section_patterns:
        match = re.search(pattern, plain)
        if not match:
            continue
        chunk = plain[match.start() : match.start() + limit]
        if any(marker in chunk for marker in _VALUATION_PURPOSE_MARKERS):
            return chunk[:limit]
    return ""


def extract_independent_advisor_valuation(text: str, *, limit: int = 8000) -> str:
    """Section ③: 対象者側 FA / 第三者算定機関の算定概要（フォールバック）。"""
    if not text:
        return ""
    plain = strip_html(text)
    section_patterns = (
        r"③[^\n]{0,240}独立したファイナンシャル・アドバイザー",
        r"独立したファイナンシャル・アドバイザー及び第三者算定機関",
        r"（ⅱ）対象者株式に係る算定の概要",
        r"対象者における独立したファイナンシャル",
        r"対象者株式に係る算定の概要",
    )
    for pattern in section_patterns:
        match = re.search(pattern, plain)
        if not match:
            continue
        chunk = plain[match.start() : match.start() + limit]
        if any(marker in chunk for marker in _VALUATION_PURPOSE_MARKERS):
            return chunk[:limit]
    return ""


def parse_valuation_from_sources(*texts: str) -> dict[str, str]:
    """Try third-party ⑤, price basis, purposes, then FA ③ passages."""
    for text in texts:
        if not text:
            continue
        section = extract_special_committee_valuation(text)
        if section:
            parsed = _parse_valuation_ranges_from_text(section)
            if any(parsed.values()):
                return parsed

    for text in texts:
        if not text:
            continue
        parsed = parse_valuation_ranges(text)
        if any(parsed.values()):
            return parsed

    for text in texts:
        if not text:
            continue
        section = extract_valuation_from_purposes(text)
        if section:
            parsed = _parse_valuation_ranges_from_text(section)
            if any(parsed.values()):
                return parsed

    for text in texts:
        if not text:
            continue
        section = extract_independent_advisor_valuation(text)
        if section:
            parsed = _parse_valuation_ranges_from_text(section)
            if any(parsed.values()):
                return parsed

    return _empty_valuation_ranges()


_METHOD_LABELS = (
    ("市場株価", "市場株価法"),
    ("類似", "類似会社比較法"),
    ("ＤＣＦ", "DCF法"),
    ("DCF", "DCF法"),
    ("ディスカウント", "DCF法"),
)


def _method_label(raw: str) -> str:
    for needle, label in _METHOD_LABELS:
        if needle in raw:
            return label
    return ""


def parse_board_opinion(text: str) -> str:
    """Board conclusion inside an opinion text block.

    One of 賛同・応募推奨 / 賛同 / 反対 / 中立 / 判断留保, or blank when the
    opening of the block does not state a conclusion. Later narrative that
    mentions both 賛同 and 反対 does not override the earliest conclusion.
    """
    if not text:
        return ""
    compact = re.sub(r"\s+", "", strip_html(text))
    head = compact[:1200]
    if not head:
        return ""
    patterns = (
        ("oppose", re.compile(r"反対する旨|反対の意見|本公開買付けに反対|応募しないことを推奨")),
        ("support", re.compile(r"賛同する旨|賛同の意見|本公開買付けに賛同")),
        ("reserve", re.compile(r"意見を留保|意見留保|判断を留保|判断留保")),
        ("neutral", re.compile(r"中立")),
    )
    found: list[tuple[int, str]] = []
    for label, pattern in patterns:
        match = pattern.search(head)
        if match:
            found.append((match.start(), label))
    if not found:
        return ""
    found.sort()
    kind = found[0][1]
    if kind == "oppose":
        return "反対"
    if kind == "reserve":
        return "判断留保"
    if kind == "neutral":
        return "中立"
    recommend = re.search(r"応募することを推奨|応募を推奨|応募推奨", head)
    support = next(item for item in found if item[1] == "support")
    if recommend and abs(recommend.start() - support[0]) <= 80:
        return "賛同・応募推奨"
    return "賛同"


def hostile_from_opinion(stance: str) -> str:
    """Yes / No from the initial board stance. Blank when the stance is not a yes/no."""
    if stance == "反対":
        return "Yes"
    if stance in {"賛同", "賛同・応募推奨"}:
        return "No"
    return ""


def parse_valuation_records(text: str) -> list[dict[str, object]]:
    """One record per named advisor. Ranges are not merged across advisors.

    A passage with ranges but no advisor name becomes one record with an empty
    advisor. A second range for the same method on the same advisor is ignored.
    """
    plain = re.sub(r"\s+", "", strip_html(text or ""))
    if not plain:
        return []
    range_re = re.compile(
        r"(市場株価(?:平均法|基準方式|法)|類似(?:上場)?(?:会社)?比(?:較|準)(?:法|方式)|"
        r"(?:ディスカウンテッド・キャッシュ・フロー|DCF|ＤＣＦ)(?:法|方式))"
        r"[：:]?([\d,，]+)円(?:から|～|〜|~|-|－)([\d,，]+)円"
    )
    name_re = re.compile(r"([^。、（）()]{2,40})(?:は|による)")
    reject = ("公開買付", "対象者", "市場株価", "算定結果", "下記", "以下", "本意見")
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    def start(name: str) -> dict[str, object]:
        return {
            "advisor": name,
            "marketMin": None,
            "marketMax": None,
            "comparableMin": None,
            "comparableMax": None,
            "dcfMin": None,
            "dcfMax": None,
        }

    def assign(record: dict[str, object], label: str, low: str, high: str) -> None:
        method = _method_label(label)
        key = {"市場株価法": "market", "類似会社比較法": "comparable", "DCF法": "dcf"}.get(method)
        if not key:
            return
        min_key = f"{key}Min"
        max_key = f"{key}Max"
        if record[min_key] is not None:
            return
        record[min_key] = _parse_int(low)
        record[max_key] = _parse_int(high)

    for match in range_re.finditer(plain):
        lookback = plain[max(0, match.start() - 80) : match.start()]
        name = ""
        found = name_re.findall(lookback)
        if found:
            candidate = found[-1]
            if not any(word in candidate for word in reject) and len(candidate) <= 40:
                name = candidate
        if current is None:
            current = start(name)
            records.append(current)
        elif name and name != current["advisor"]:
            current = start(name)
            records.append(current)
        assign(current, match.group(1), match.group(2), match.group(3))
    return [record for record in records if any(record[key] is not None for key in (
        "marketMin",
        "comparableMin",
        "dcfMin",
    ))]


def parse_valuation_advisors(*texts: str) -> str:
    """Return per-advisor ranges when two or more advisors are explicit.

    A single advisor stays in the existing Valuation* columns. This string is
    blank unless at least two named advisors each have one or more ranges.
    """
    plain = re.sub(r"\s+", "", strip_html("\n".join(text for text in texts if text)))
    if not plain:
        return ""
    range_re = re.compile(
        r"(市場株価(?:平均法|基準方式|法)|類似(?:上場)?(?:会社)?比(?:較|準)(?:法|方式)|"
        r"(?:ディスカウンテッド・キャッシュ・フロー|DCF|ＤＣＦ)(?:法|方式))"
        r"[：:]([\d,，]+)円(?:から|～|〜|~|-|－)([\d,，]+)円"
    )
    name_re = re.compile(r"([^。、（）()]{2,40})(?:は|による)")
    reject = ("公開買付", "対象者", "市場株価", "算定結果", "下記", "以下")
    advisors: list[tuple[str, list[str]]] = []
    current_name = ""
    current_parts: list[str] = []
    last_end = -1
    for match in range_re.finditer(plain):
        gap = match.start() - last_end if last_end >= 0 else 0
        lookback = plain[max(0, match.start() - 80) : match.start()]
        name = ""
        found = name_re.findall(lookback)
        if found:
            candidate = found[-1]
            if not any(word in candidate for word in reject) and len(candidate) <= 40:
                name = candidate
        if name and name != current_name:
            if current_name and current_parts:
                advisors.append((current_name, current_parts))
            current_name = name
            current_parts = []
        elif gap > 180 and current_parts:
            if current_name:
                advisors.append((current_name, current_parts))
            current_name = name
            current_parts = []
        label = _method_label(match.group(1))
        if not label or not current_name:
            last_end = match.end()
            continue
        piece = f"{label} {_comma_number(match.group(2))}〜{_comma_number(match.group(3))}円"
        if piece not in current_parts:
            current_parts.append(piece)
        last_end = match.end()
    if current_name and current_parts:
        advisors.append((current_name, current_parts))
    unique: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for name, parts in advisors:
        if name in seen or not parts:
            continue
        seen.add(name)
        unique.append((name, parts))
    if len(unique) < 2:
        return ""
    return "; ".join(f"{name}（{'、'.join(parts)}）" for name, parts in unique)


def _yen_amount(raw: str) -> str:
    return _comma_number(raw)


def parse_reference_market_price_details(text: str) -> dict[str, str]:
    """Announcement prior-close and 1/3/6-month averages, without a 円 suffix.

    Only the clause that states 公表日の前営業日 and then 終値 is accepted.
    Precedent-premium sentences and 本書提出日の前営業日 are ignored.
    Conflicting closes, or conflicting averages, stay blank.
    """
    empty = {"priorClose": "", "avg1m": "", "avg3m": "", "avg6m": ""}
    plain = re.sub(r"\s+", "", strip_html(text or ""))
    if "公表日" not in plain or "前営業日" not in plain:
        return empty
    closes: set[str] = set()
    triples: set[tuple[str, str, str]] = set()
    singles: set[str] = set()
    month_re = re.compile(
        r"(?:直近|過去)?[1１][ヶかカ]月間、(?:直近|過去)?[3３][ヶかカ]月間及び"
        r"(?:直近|過去)?[6６][ヶかカ]月間の終値単純平均値[（(]"
        r"([\d,，]+)円[、，]([\d,，]+)円(?:及び|[、，])([\d,，]+)円"
    )
    single_month_re = re.compile(
        r"(?:直近|過去)[1１][ヶかカ]月間の終値単純平均値[（(]?([\d,，]+)円"
    )
    for match in re.finditer(r"公表日の前営業日|公表日前営業日", plain):
        window = plain[match.end() : match.end() + 420]
        stop = re.search(r"。|公表日の前営業日|公表日前営業日", window)
        if stop:
            window = window[: stop.start()]
        window = plain[match.start() : match.end()] + window
        head = window[:90]
        if any(word in head for word in ("実例", "中央値", "事例", "プレミアムの")):
            continue
        before_average = re.split(r"終値単純平均|終値の単純平均", window, maxsplit=1)[0]
        found = re.findall(r"終値[（(]([\d,，]+)円[)）]", before_average)
        if not found:
            found = re.findall(r"(?<!平均)終値([\d,，]+)円", before_average)
        if len(set(found)) != 1:
            continue
        closes.add(_yen_amount(found[0]))
        triple = month_re.search(window)
        if triple:
            triples.add(
                (
                    _yen_amount(triple.group(1)),
                    _yen_amount(triple.group(2)),
                    _yen_amount(triple.group(3)),
                )
            )
            continue
        single = single_month_re.search(window)
        if not single:
            continue
        preceding = window[max(0, single.start() - 24) : single.start()]
        if re.search(r"[3３6６][ヶかカ]月", preceding):
            continue
        if "％" in window[single.end() : single.end() + 6]:
            continue
        singles.add(_yen_amount(single.group(1)))
    if len(closes) != 1:
        return empty
    avg1m = avg3m = avg6m = ""
    if len(triples) == 1 and not singles:
        avg1m, avg3m, avg6m = next(iter(triples))
    elif len(triples) == 0 and len(singles) == 1:
        avg1m = next(iter(singles))
    return {
        "priorClose": next(iter(closes)),
        "avg1m": avg1m,
        "avg3m": avg3m,
        "avg6m": avg6m,
    }


def parse_reference_market_prices(text: str) -> dict[str, str]:
    """Extract announcement prior-close and 1-month average, or blanks."""
    details = parse_reference_market_price_details(text)
    return {
        "ReferencePricePriorClose": f"{details['priorClose']}円" if details["priorClose"] else "",
        "ReferencePrice1M": f"{details['avg1m']}円" if details["avg1m"] else "",
    }


def parse_offer_yen_per_share(offer_price: str) -> int | None:
    """Return yen per share only for a single cash price, not a range or stock deal."""
    text = re.sub(r"\s+", "", offer_price or "")
    match = re.fullmatch(r"([\d,，]+)円(?:/株)?", text)
    if not match:
        return None
    return _parse_int(match.group(1))


def format_premium(offer_price: str, reference_yen: str) -> str:
    """Premium of the same document's offer price versus a reference yen price.

    Blank unless both values are a single yen amount and the result is within
    -90% to +1000%. No premium is inferred from a percentage already in the text.
    """
    offer = parse_offer_yen_per_share(offer_price)
    reference = _parse_int(re.sub(r"[^\d]", "", reference_yen or ""))
    if offer is None or reference is None or reference <= 0 or offer <= 0:
        return ""
    pct = (offer - reference) / reference * 100
    if pct < -90 or pct > 1000:
        return ""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def parse_offer_report_counts(result_text: str, acquired_text: str = "") -> dict[str, str]:
    """Tendered and purchased shares from a tender-offer report.

    Purchased shares are copied from the tendered count only when the report
    states that every tendered share is purchased. Proration leaves the
    purchased count blank unless the acquired-shares text has its own number.
    """
    empty = {"ApplicationCount": "", "PurchaseCount": ""}
    tendered, _, _ = parse_tob_result_counts(result_text)
    acquired = re.sub(r"\s+", "", strip_html(acquired_text or ""))
    purchase = _first_count(
        acquired,
        (
            r"買付(?:け等)?(?:株数|数|普通株式数)[（(]([\d,，]+)(?:株|口|個)",
            r"買付け等を行った株券等の数[（(]([\d,，]+)(?:株|口|個)",
        ),
    )
    compact = re.sub(r"\s+", "", strip_html(result_text or ""))
    buy_all = "全部の買付け等を行います" in compact or "全部の買付けを行います" in compact
    prorata = "あん分比例" in compact or "按分比例" in compact
    if purchase is None and tendered is not None and buy_all and not prorata:
        purchase = tendered
    if tendered is None and purchase is None:
        return empty
    return {
        "ApplicationCount": f"{tendered:,}" if tendered is not None else "",
        "PurchaseCount": f"{purchase:,}" if purchase is not None else "",
    }


def build_value_history(docs: list[dict], field: str) -> str:
    """Filing-order history of a field. Blank unless the value actually changes."""
    points: list[str] = []
    previous = ""
    filings = [doc for doc in docs if (doc.get("DocTypeCode") or "") in {"240", "250"}]
    for doc in filings:
        value = (doc.get(field) or "").strip()
        if not value or value == previous:
            continue
        day = (doc.get("SubmitDateTime") or "")[:10]
        points.append(f"{day} {value}".strip())
        previous = value
    if len(points) < 2:
        return ""
    return " → ".join(points)


def _is_dash_count(token: str) -> bool:
    stripped = (token or "").strip()
    if not stripped:
        return True
    dash_chars = set("―－—-−‑ー")
    return all(ch in dash_chars for ch in stripped)


_SHARE_UNIT = r"(?:株|口|個)"
_SHARE_PAREN = rf"(?:\({_SHARE_UNIT}\)|（{_SHARE_UNIT}）)"
_SHARE_SUFFIX = rf"(?:{_SHARE_PAREN}|{_SHARE_UNIT})?"
_DASH_CHARS = "―－—-−‑ー"
EXPLICIT_EMPTY = "-"


def _planned_table_found(section: str) -> bool:
    if re.search(rf"合計[\d,，]+{_SHARE_SUFFIX}?", section):
        return True
    if re.search(r"合計.{0,40}(?:上限|下限|買付予定数)", section):
        return True
    return bool("買付予定の株券等の数" in section and "合計" in section)


def _format_planned_field(
    value: int | None,
    *,
    table_found: bool,
    explicit_none: bool = False,
) -> str:
    if not table_found:
        return ""
    if value is not None:
        return f"{value:,}"
    if explicit_none:
        return EXPLICIT_EMPTY
    return ""


def _extract_planned_purchase_section(compact: str) -> str:
    """Isolate section (3) table text and stop before footnotes / next heading."""
    start = -1
    for marker in (
        "（３）【買付予定の株券等の数】",
        "(３)【買付予定の株券等の数】",
        "【買付予定の株券等の数】",
        "買付予定の株券等の数",
    ):
        idx = compact.find(marker)
        if idx >= 0:
            start = idx
            break
    if start < 0:
        total_matches = list(re.finditer(r"合計", compact))
        if total_matches:
            start = max(0, total_matches[-1].start() - 500)
        else:
            return compact[:1200]
    tail = compact[start:]
    for stop in (r"\(注", r"（注", r"４【", r"4【", r"５【", r"5【"):
        match = re.search(stop, tail)
        if match:
            tail = tail[: match.start()]
    return tail[:1200]


def _parse_total_row_counts(
    section: str,
) -> tuple[int | None, int | None, int | None, bool, bool]:
    """Parse 合計 row; return (planned, floor, cap, floor_is_dash, cap_is_dash)."""
    match = re.search(rf"合計([\d,，]+){_SHARE_SUFFIX}(.*)", section)
    if not match:
        return None, None, None, False, False
    planned = _parse_int(match.group(1))
    rest = re.split(r"(?:\(注|（注|４【|4【)", match.group(2), maxsplit=1)[0][:200]
    tokens = re.findall(
        rf"([{_DASH_CHARS}]|[\d,，]+){_SHARE_SUFFIX}",
        rest,
    )
    floor = None
    cap = None
    floor_dash = False
    cap_dash = False
    if tokens:
        if _is_dash_count(tokens[0]):
            floor_dash = True
        else:
            floor = _parse_int(tokens[0])
        if len(tokens) > 1:
            if _is_dash_count(tokens[1]):
                cap_dash = True
            else:
                cap = _parse_int(tokens[1])
    return planned, floor, cap, floor_dash, cap_dash


def parse_planned_purchase_counts(text: str) -> dict[str, str]:
    """Return planned share counts from the 合計 row in section 4(3).

    Blank = could not extract (no table). ``-`` = extracted but explicitly empty in filing.
    """
    empty = {
        "PlannedSharesMin": "",
        "PlannedSharesMax": "",
        "PlannedSharesPlanned": "",
    }
    if not text:
        return empty
    compact = re.sub(r"\s+", "", strip_html(text))
    section = _extract_planned_purchase_section(compact)
    table_found = _planned_table_found(section)
    if not table_found:
        return empty

    no_floor = bool(re.search(r"下限(?:及び上限)?[をは]?(?:設定して|定めて)おりません", section))
    no_cap = bool(re.search(r"上限(?:及び下限)?[をは]?(?:設定して|定めて)おりません", section))

    table_planned, table_floor, table_cap, floor_dash, cap_dash = _parse_total_row_counts(section)

    floor_val = None if no_floor else table_floor
    cap_val = None if no_cap else table_cap

    table_tail = section.split("合計")[-1] if "合計" in section else section
    if floor_val is None and not no_floor and not floor_dash:
        floor_val = _last_bound(table_tail, "下限")
    if cap_val is None and not no_cap and not cap_dash:
        cap_val = _last_bound(table_tail, "上限")

    planned_val = table_planned
    if planned_val is None:
        for pattern in (
            rf"買付予定数[（(]?([\d,，]+){_SHARE_SUFFIX}",
            r"買付予定数[（(]([\d,，]+)(?:株|口|個)[)）]",
            r"買付予定数[（(]?([\d,，]+)(?:株|口|個)",
        ):
            match = re.search(pattern, section)
            if match:
                planned_val = _parse_int(match.group(1))
                if planned_val is not None:
                    break

    return {
        "PlannedSharesMin": _format_planned_field(
            floor_val,
            table_found=table_found,
            explicit_none=no_floor or floor_dash,
        ),
        "PlannedSharesMax": _format_planned_field(
            cap_val,
            table_found=table_found,
            explicit_none=no_cap or cap_dash,
        ),
        "PlannedSharesPlanned": _format_planned_field(planned_val, table_found=table_found),
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
    patterns = (
        r"買付代金\(円\)\s*\([ａaAＡ]\)\s*([\d,，]+)",
        r"買付代金（円）\s*\([ａaAＡ]\)\s*([\d,，]+)",
        r"買付代金[（(]?[ａaAＡ][)）]?[：:\s]*([\d,，]+)\s*(円|ウォン|ドル|USD|米ドル)",
        r"買付代金[（(]?[ａaAＡ][)）]?[：:\s]*([\d,，]+)\s*(?:円|ウォン|ドル|USD|米ドル)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        if match.lastindex == 1:
            return f"{_comma_number(match.group(1))}円"
        unit = match.group(2)
        if unit == "USD":
            unit = "米ドル"
        return f"{_comma_number(match.group(1))}{unit}"
    return ""


def _trim_agent_name(text: str) -> str:
    candidate = clean_extracted_name(text)
    candidate = re.sub(r"\s+(?:名称|氏名又は名称)\s*$", "", candidate).strip()
    candidate = re.sub(r"\s+(?:所在地|最寄|電話).*$", "", candidate).strip()
    parts = re.split(r"[\s　]+", candidate, maxsplit=1)
    if len(parts) == 2:
        tail = parts[1]
        if re.match(r"^(?:〒|[一-龥]{2,4}[都道府県])", tail) or re.search(
            r"[都道府県].*(?:丁目|番地|番|号)",
            tail,
        ):
            candidate = parts[0].strip()
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
        r"[①１]\s*公開買付代理人\s*([^\n\r。]{2,80})",
        plain,
    )
    if match:
        candidate = re.sub(r"^(?:名称|氏名又は名称)\s*", "", match.group(1))
        candidate = _trim_agent_name(candidate)
        if candidate and not candidate.startswith("("):
            return candidate
    # XBRLの表は「公開買付代理人」の次のセルが社名で、①や「名称」が無い。
    match = re.search(
        r"公開買付代理人\s*(?!は|の|における|以外|に)([^\n。]{2,80})",
        plain,
    )
    if match:
        candidate = re.sub(r"^(?:名称|氏名又は名称)\s*", "", match.group(1))
        candidate = _trim_agent_name(candidate)
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
    if detect_target_listing_status(combined) in {"株主コミュニティ", "非上場"}:
        return ""
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
