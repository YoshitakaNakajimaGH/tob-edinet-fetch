#!/usr/bin/env python3
"""PE / sponsor name patterns for SponsorHint inference.

Sources (public industry maps, 2024-2025):
- Quzilla/Kujira domestic PE chaos map
- JVCA / Kotora / Antelope major-player lists
- JETRO inbound M&A report (foreign sponsors active in Japan TOB)
"""

from __future__ import annotations

import re

# (regex pattern, canonical display label) — order matters (more specific first).
PE_SPONSOR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Global / inbound (active in Japan TOB)
    (re.compile(r"The\s+Carlyle\s+Group|カーライル(?:・グループ)?", re.I), "The Carlyle Group"),
    (re.compile(r"Goldman\s+Sachs|ゴールドマン・サックス|ザ・ゴールドマン・サックス", re.I), "Goldman Sachs"),
    (re.compile(r"\bKKR\b|ＫＫＲ(?:&Co\.?)?"), "KKR"),
    (re.compile(r"Bain\s+Capital|ベイン・?キャピタル", re.I), "Bain Capital"),
    (re.compile(r"Blackstone|ブラックストーン", re.I), "Blackstone"),
    (re.compile(r"Apollo(?:\s+Global)?|アポロ", re.I), "Apollo"),
    (re.compile(r"\bEQT\b|ＥＱＴ(?:パートナーズ)?"), "EQT"),
    (re.compile(r"TPG(?:\s+Capital)?|ティー・ピー・ジー", re.I), "TPG"),
    (re.compile(r"Warburg\s+Pincus|ウォーバーグ・ピンカス", re.I), "Warburg Pincus"),
    (re.compile(r"Permira|パーミラ", re.I), "Permira"),
    (re.compile(r"Advent(?:\s+International)?|アドベント", re.I), "Advent"),
    (re.compile(r"Silver\s+Lake|シルバーレイク", re.I), "Silver Lake"),
    (re.compile(r"Hellman\s+&?\s+Friedman|ヘルマン", re.I), "Hellman & Friedman"),
    (re.compile(r"Brookfield|ブルックフィールド", re.I), "Brookfield"),
    (re.compile(r"DigitalBridge|デジタルブリッジ", re.I), "DigitalBridge"),
    (re.compile(r"PAG(?:\s+Capital)?|ピー・エー・ジー", re.I), "PAG"),
    (re.compile(r"CVC(?:\s+Capital)?|ＣＶＣ(?:・キャピタル)?"), "CVC"),
    (re.compile(r"MBK\s+Partners|エムビーケーパートナーズ", re.I), "MBK Partners"),
    (re.compile(r"Baring(?:\s+Private\s+Equity)?(?:\s+Asia)?|ベアリング", re.I), "Baring PE Asia"),
    (re.compile(r"CD&R|Clayton\s+Dubilier", re.I), "CD&R"),
    (re.compile(r"KPS\s+Capital", re.I), "KPS Capital"),
    (re.compile(r"LGT\s+Capital", re.I), "LGT Capital Partners"),
    # Japan independent / bank-affiliated PE
    (re.compile(r"アドバンテッジパートナーズ|Advantage\s+Partners", re.I), "Advantage Partners"),
    (re.compile(r"ユニゾン・?キャピタル|Unison\s+Capital", re.I), "Unison Capital"),
    (re.compile(r"インテグラル(?:ホールディングス|コーポレーション)?|Integral(?:\s+Corporation)?", re.I), "Integral"),
    (re.compile(r"J-STAR|Ｊ－ＳＴＡＲ|ジェイスター", re.I), "J-STAR"),
    (re.compile(r"日本産業推進機構|ＮＳＳＫ|NSSK", re.I), "NSSK"),
    (re.compile(r"ポラリス(?:・キャピタル)?(?:・グループ)?|Polaris\s+Capital", re.I), "Polaris Capital Group"),
    (re.compile(r"ティーキャピタル|T\s*Capital(?:\s+Partners)?|Ｔ\s*キャピタル", re.I), "T Capital Partners"),
    (re.compile(r"ロングリーチ(?:・グループ)?|Longreach\s+Group", re.I), "Longreach Group"),
    (re.compile(r"エンデバー・?ユナイテッド|Endeavour\s+United", re.I), "Endeavour United"),
    (re.compile(r"日本産業パートナーズ|Japan\s+Industrial\s+Partners|\bJIP\b|ＪＩＰ"), "Japan Industrial Partners"),
    (re.compile(r"野村キャピタル・?パートナーズ|Nomura\s+Capital\s+Partners", re.I), "Nomura Capital Partners"),
    (re.compile(r"MCP(?:\s+キャピタル|\s+Capital|\s+Partners)?|みずほキャピタル", re.I), "MCP Capital"),
    (re.compile(r"ジャフコ|JAFCO|ＪＡＦＣＯ", re.I), "JAFCO"),
    (re.compile(r"SMBCキャピタル・?パートナーズ", re.I), "SMBC Capital Partners"),
    (re.compile(r"マーキュリア(?:・インベストメント)?|Mercuria\s+Investment", re.I), "Mercuria Investment"),
    (re.compile(r"日本成長投資アライアンス|Ｊ－?ＧＩＡ|J-GIA", re.I), "Japan Growth Investments Alliance"),
    (re.compile(r"丸の内キャピタル|Marunouchi\s+Capital", re.I), "Marunouchi Capital"),
    (re.compile(r"アント・?キャピタル|Ant\s+Capital", re.I), "Ant Capital Partners"),
    (re.compile(r"クレアシオン・?キャピタル|Creacion\s+Capital", re.I), "Creacion Capital"),
    (re.compile(r"ライジング・?ジャパン・?エクイティ|Rising\s+Japan\s+Equity", re.I), "Rising Japan Equity"),
    (re.compile(r"サンライズ(?:・)?キャピタル|CLSA\s+Capital", re.I), "Sunrise Capital"),
    (re.compile(r"ジャパン・?インダストリアル・?ソリューションズ|\bJIS\b|ＪＩＳ", re.I), "Japan Industrial Solutions"),
    (re.compile(r"アイ・?シグマ・?キャピタル|iSigma\s+Capital", re.I), "iSigma Capital"),
    (re.compile(r"アスパラント(?:グループ)?|Aspirant\s+Group", re.I), "Aspirant Group"),
    (re.compile(r"IAパートナーズ|IA\s+Partners", re.I), "IA Partners"),
    (re.compile(r"Basic\s+Capital\s+Management", re.I), "Basic Capital Management"),
    (re.compile(r"マラトンキャピタル|Marathon\s+Capital", re.I), "Marathon Capital Partners"),
    (re.compile(r"雄渾キャピタル|Yuugen\s+Capital", re.I), "Yuugen Capital Partners"),
    (re.compile(r"日本投資ファンド|Ｊ－?ＦＵＮ|J-FUN", re.I), "Japan Investment Fund"),
    (re.compile(r"日本プライベートエクイティ|Japan\s+Private\s+Equity", re.I), "Japan Private Equity"),
    (re.compile(r"産業革新投資機構|\bJIC\b|ＪＩＣ", re.I), "JIC"),
    (re.compile(r"みらいキャピタル|Mirai\s+Capital", re.I), "Mirai Capital"),
    (re.compile(r"ニューホライズン(?:・)?キャピタル", re.I), "New Horizon Capital"),
    (re.compile(r"Integra\s+Holdings|インテグラ(?:ホールディングス)?", re.I), "Integral"),
    (re.compile(r"H\.I\.S\.|エイチ・アイ・エス", re.I), "H.I.S."),
    (re.compile(r"伊藤忠商事|Itochu", re.I), "伊藤忠商事"),
    (re.compile(r"東京海上(?:グループ|キャピタル)", re.I), "東京海上グループ"),
)
