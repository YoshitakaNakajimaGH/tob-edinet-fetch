# TOBリスト取得ロジック（引き継ぎ）

この文書は、GitHub 上の `master`（`tob/` パッケージ）が今やっている処理を、別環境の Jupyter へ移すための説明です。期間の指定方法は後から変えてよい前提で、**変えてよい箇所**と**変えると案件の意味が壊れる箇所**を分けて書いています。

対象コードの入口は次の3つです。

| 順番 | コマンド | 役割 |
|------|----------|------|
| 1 | `python -m tob.fetch_tob` | 書類の一覧（メタデータ）を取る |
| 2 | `python -m tob.enrich_tob` | 他社株の XBRL から中身を取る |
| 3 | `python -m tob.enrich_self_tob` | 自社株の XBRL から中身を取る（必要なときだけ） |

普段見る表は `output/current/tob_cases.csv`（案件1行）です。書類1行は `output/current/tob_list.csv` です。

---

## 1. 全体の順番

理解の近いところと、違うところがあります。

近いところ: 期間を決める → その期間に**提出された書類**を集める → 同じ案件の書類をまとめる → 中身を取る。

違うところ: EDINET は「案件ID」を返しません。一覧APIが返すのは**書類ID（DocID）**と、訂正なら**親書類ID（ParentDocID）**です。案件ID（CaseID）は、こちらが親を辿って後から付けます。

```
期間（提出日）
  → 1日ずつ書類一覧 API
  → docTypeCode 240〜320 だけ残す（書類IDのリスト）
  → 既存CSVへ DocID で追記・更新
  → 提出者コード = 相手方コード なら自社株、それ以外は他社株
  → ParentDocID を根まで辿り、根の DocID を CaseID にする
  → 孤立した意見表明だけ、買付者コードと対象会社コードで届出案件に付ける
  → 案件1行（tob_cases.csv）を書類行から再生成
  → 各書類の XBRL（type=5）を取り、タクソノミの要素IDで文章・数値を読む
  → 読んだ文章を列に分解し、もう一度案件行を再生成
```

期間を「暦年」から「毎月、未完了の案件だけ」に変えても、上の **CaseID の付け方**と **タクソノミの読み方**はそのまま使えます。変えるのは「どの提出日の書類をAPIに取りに行くか」です。

---

## 2. 期間の決め方（後から変えてよい部分）

実装は `tob/tob_common.py` の `resolve_range()` です。次の3モードがあります。

| モード | 指定 | 開始 | 終了 |
|--------|------|------|------|
| `years` | `--from-year` `--to-year` | 開始年の1月1日 | 終了年の12月31日。今年なら実行日まで |
| `dates` | `--from-date` `--to-date` | その日 | その日（終了省略なら実行日） |
| `recent` | `--recent-days` | 実行日のN日前（既定の定期更新は35日） | 実行日 |

APIに渡す日付は**書類の提出日**です。公開買付の開始日や終了日ではありません。

### 毎月・案件ベースに変えるとき

一覧APIは「その日に提出された全書類」しか返しません。案件IDで「この案件の続きだけ」とは聞けません。

毎月更新するなら、現実的なのは次です。

1. 直近1か月（または直近35日）の提出分だけ一覧を取り、DocID で既存CSVにマージする。今の `--recent-days` がこれです。
2. マージ後に CaseID を**全書類で付け直す**。新しい訂正・報告書・意見表明が、過去の届出（期間の外にある親）に繋がります。
3. 中身（Enrich）は、新しく来た書類と、まだ `ExtractionStatus` が空の書類だけ取る（`--only-pending`）。

案件が「今月も生きているか」は、その CaseID の書類に報告書（270/280）も撤回（260）も無いこと、で判断できます。分析用に毎月スナップショットを残すなら、`output/snapshots/` に日付付きCSVをコピーする層を足します。取得ロジック自体は同じです。

`--replace` は既存CSVを捨てて、今回の期間だけで上書きします。毎月更新では使いません。

---

## 3. EDINET のどこから何を取るか

使うAPIは2つです。キーは環境変数 `EDINET_API_KEY` です。発行ページは https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1 です。

### 3.1 書類一覧（Fetch）

```
GET https://api.edinet-fsa.go.jp/api/v2/documents.json
  ?date=YYYY-MM-DD
  &type=2
  &Subscription-Key=APIキー
```

`type=2` はメタデータの一覧です。本文もXBRLもここにはありません。1日1回呼び、`results` 配列の各書類を見ます。応答は `cache/YYYY-MM-DD.json` に保存し、再実行時はその日を呼びません。

残すのは `docTypeCode` が次の9種だけです。これ以外（有価証券報告書など）は捨てます。

| docTypeCode | 書類 | 誰が提出するか | タクソノミ略号 |
|-------------|------|----------------|----------------|
| 240 | 公開買付届出書 | 買付者 | `ton` |
| 250 | 訂正公開買付届出書 | 買付者 | `ton` |
| 260 | 公開買付撤回届出書 | 買付者 | `wto` |
| 270 | 公開買付報告書 | 買付者 | `tor` |
| 280 | 訂正公開買付報告書 | 買付者 | `tor` |
| 290 | 意見表明報告書 | 対象会社 | `pst` |
| 300 | 訂正意見表明報告書 | 対象会社 | `pst` |
| 310 | 対質問回答報告書 | 質問を受けた側 | `toa` |
| 320 | 訂正対質問回答報告書 | 質問を受けた側 | `toa` |

一覧APIの項目と、CSVに書く列は次のとおりです。実装は `tob/fetch_tob.py` の `row_from_doc()` です。

| APIの項目 | CSV列 | 意味 |
|-----------|-------|------|
| `submitDateTime` | `SubmitDateTime` | 提出日時 |
| `docTypeCode` | `DocTypeCode` | 上の表 |
| `filerName` | `FilerName` | 提出者の名前（表示用。案件の判定には使わない） |
| `secCode` | `FilerSecCode` | 提出者の証券コード。5桁のことがある |
| `edinetCode` | `FilerEdinetCode` | 提出者のEDINETコード（例 `E05733`） |
| `subjectEdinetCode` | `SubjectEdinetCode` | 相手方のEDINETコード |
| `docID` | `DocID` | 書類ID（例 `S100M436`） |
| `parentDocID` | `ParentDocID` | 訂正・報告・意見が指す親の書類ID。当初届出は空 |
| `docDescription` | `DocDescription` | 書類の説明 |
| `pdfFlag` / `xbrlFlag` | `PdfFlag` / `XbrlFlag` | PDF / XBRL の有無。`xbrlFlag` が `0` の書類は中身を取りに行かない |

この時点では `CaseID` は空です。価格・期間・意見も空です。

PDFのURLはAPIではなく、書類IDから組み立てます。

```
https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{DocID}.pdf
```

### 3.2 書類の中身（Enrich）

```
GET https://api.edinet-fsa.go.jp/api/v2/documents/{DocID}
  ?type=5
  &Subscription-Key=APIキー
```

`type=5` は XBRL の ZIP です。中の CSV が「要素ID → 値」の表です。ZIP は `cache/docs/` に残します。

会社の証券コードと上場区分は、書類APIとは別の提出者リストです。

```
https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip
```

中の `EdinetcodeDlInfo.csv` を `cache/edinet/` に置き、EDINETコードから証券コード（4桁）と上場／非上場を引きます。実装は `edinet/edinet_code_list.py` です。

---

## 4. 書類を案件にまとめる

実装は `tob/tob_common.py` の `assign_case_ids()` → `resolve_case_id()` → `reattach_orphan_opinions()` です。

### 4.1 買付者と対象会社

名前では判定しません。EDINETコードの役割で決めます。

届出・訂正・撤回・報告（240〜280）では、提出者 = 買付者、相手方 = 対象会社です。

意見表明・対質問（290〜320）では提出者が逆なので、コード上で入れ替えます（`party_pair()`）。意見表明の提出者コードが対象会社、相手方コードが買付者です。

自社株TOBは、提出者コードと相手方コードが同じ書類です（`is_issuer_tender()`）。先に `self_tob_list.csv` / `self_tob_cases.csv` へ分け、他社株とは混ぜません。

### 4.2 CaseID

各書類の `ParentDocID` を、手元のCSVの中で親が無くなるまで辿ります。親が無い書類（通常は最初の240）の **DocID が CaseID** です。

```
S100MBZL（訂正届出 250） → ParentDocID S100L8UR（当初届出 240） → CaseID = S100L8UR
S100MBZT（訂正報告 280） → … → 同じ S100L8UR
```

同じ買付者・同じ対象会社でも、最初の届出が別なら別案件です。再TOBはまとめません。

親書類が今回のCSVに無いとき（取得期間の外にある当初届出など）は、欠けている親の DocID を CaseID にします。それも無いときは `fallback:買付者コード|対象会社コード` です。

訂正意見表明の親がCSVに無く、意見表明だけのグループが残ることがあります。そのときは、同じ（買付者コード, 対象会社コード）の届出案件のうち、意見表明の提出日以前で一番新しいものに付けます（`reattach_orphan_opinions()`）。

意見表明だけのグループは案件行を作りません。

### 4.3 案件の状態

`case_status()` の優先順です。

1. 260 がある → `撤回`
2. 270 または 280 がある → `報告書提出`
3. 250 がある → `訂正あり`
4. 240 がある → `届出中`
5. 290 または 300 だけ → `意見表明のみ`（通常は案件行にしない）

---

## 5. タクソノミ（XBRLの項目名）

XBRLの値は、日本語の列名ではなく要素IDで入っています。対応表は `tob/taxonomy/mappings/` です。適用期間は `tob/taxonomy/manifest.json` と `tob/taxonomy/README.md` にあります。

要素IDの接頭辞は書類の種類です。

| 接頭辞 | 書類 |
|--------|------|
| `jptoo-ton_cor:` | 他社株の届出・訂正届出 |
| `jptoo-tor_cor:` | 他社株の報告書・訂正報告書 |
| `jptoo-pst_cor:` | 他社株の意見表明・訂正意見表明 |
| `jptoo-wto_cor:` | 他社株の撤回 |
| `jptoo-toa_cor:` | 他社株の対質問回答 |
| `jptoi_cor:` | 自社株TOB（全種別でこの接頭辞） |

### 5.1 どの年版を使うか

金融庁の他社株TOBタクソノミは毎年は変わりません。提出日と書類種別で版を決め、訂正は**元書類と同じ版**です。提出年だけでは決めません。

| 版 | タクソノミ日付 | 主な対象 | 提出日の目安 |
|----|----------------|----------|----------------|
| 2013 | 2013-08-31 | 報告・意見・撤回・回答 | 〜2020-12-31 |
| 2014 | 2014-03-31 | 届出 240/250 | 〜2020-12-31 |
| 2014 自社株 | 2014-07-31 | 自社株の全種別 | 〜2020-12-31 |
| 2021 | 2020-11-01 | 他社株の全種別 | 2021-01-01〜2026-04-30 |
| 2022〜2025 | （2021の別名） | 年次改訂なし | 2021版のまま |
| 2026 | 2025-11-01 | 他社株・自社株 | 2026-05-01以後に公告開始するもの |

選択の順番（`TaxonomySource` 列に理由が入る）:

1. ZIP内の要素IDから判定（`detected`）
2. 親書類の `TaxonomyYear` を継承（`parent`）。訂正はここが本筋
3. 書類種別と提出日から推定（`estimated`）
4. その版で要素が取れなければ、新しい版から古い版の順に要素IDを足して再試行

### 5.2 2021年版で読んでいる要素（他社株）

対応表は `tob/taxonomy/mappings/2021.json` です。2026年版は要素名が一部違いますが、役割は同じです。値の多くは「項目ごとの長い文章」で、価格や株数は後から文章を解析しています。

届出・訂正届出（`ton`）:

| 役割 | 要素ID | 入るCSV列の例 |
|------|--------|----------------|
| 買付者名 | `FullNameOrNameOfFilerOfNotificationCoverPage` | `OfferorName` |
| 対象会社名 | `NameOfSubjectCompanyTextBlock` | `TargetName` |
| 買付価格の文章 | `PriceOfPurchaseEtcTextBlock` | `OfferPrice`、算定レンジ、公表日前営業日の終値 |
| 買付期間 | `OriginalPeriodAtFilingTextBlock` または `PeriodOfPurchaseEtcTextBlock` | `OfferPeriodStart` / `End` |
| 買付予定数 | `NumberOfShareCertificatesEtcIntendedToPurchaseTextBlock` | `PlannedSharesPlanned` / `Min` / `Max` |
| 買付資金 | `FundEtcForPurchaseEtcTextBlock` | `PurchaseConsideration` |
| 応募方法 | `HowToAcceptTextBlock` | `TenderOfferAgent` |
| 買付け等の目的 | `PurposesOfPurchaseEtcTextBlock` | `PurposesRaw`。スポンサー、MBO、算定、株価の文章 |
| 公開買付の概要 | `OverviewOfPurchaseEtcTextBlock` | `OverviewRaw` |
| 買付後保有割合 | `HoldingRatioOfShareCertificatesEtcAfterPurchaseEtc` | 届出時点の計画値。案件行の買付後割合には使わない |
| 買付者の議決権 | `...OwnedByTenderOfferorD` | `ExistingHoldingRatio` の材料 |
| 特別関係者の議決権 | `...OwnedBySpecialInterestPartiesG` | `SpecialRelatedHoldingRatio` の材料 |
| 総議決権 | `...AllShareholdersEtcOfSubjectCompanyJ` | 割合の分母 |
| 買付者と特別関係者の保有 | `TotalHolding...TenderOfferorAndSpecialInterestPartiesTextBlock` | 割合の文章 |
| 特別関係者の保有 | `TotalHolding...SpecialInterestPartiesTextBlock` | 割合の文章 |
| 法人情報 | `InformationAboutCorporationTextBlock` | Raw として保持 |
| 役員履歴 | `OfficialTitleJobTitleNameDateOfBirthAndJobHistoryTextBlock` | Raw として保持 |
| 大株主 | `MajorShareholdersInformationAboutTenderOfferorTextBlock` | Raw として保持 |
| 表紙の代理人名 | `NameOfLegalRepresentativeCoverPage` | `TenderOfferAgent` の候補 |

意見表明（`pst`）:

| 役割 | 要素ID | CSV列 |
|------|--------|-------|
| 買付者の記載 | `NameAndResidentialAddressOrLocationOfTenderOfferorTextBlock` | 名前の補助 |
| 提出者（対象会社） | `NameOfFilerCoverPage` | `TargetName` |
| 意見の本文 | `OpinionAndBasisAndReasonOfOpinionRegardingSaidTenderOfferTextBlock` | `OpinionStance`（賛同 / 反対など） |

報告書（`tor`）:

| 役割 | 要素ID | CSV列 |
|------|--------|-------|
| 成否の文章 | `SuccessOrFailureOfTenderOfferTextBlock` | `FinalResultNote`、`ApplicationCount`、`PurchaseCount` |
| 期間 | `TenderOfferPeriodTextBlock` | 期間を報告書の値で上書き |
| 取得株数の文章 | `NumberOfShareCertificatesEtcAcquiredByPurchaseEtcTextBlock` | 買付数の補助 |
| 買付後保有割合 | `HoldingRatioOfShareCertificatesEtcAfterPurchaseEtc` | 成立時の `AfterPurchaseRatio` |

撤回（`wto`）: 撤回理由 `ReasonForWithdrawalEtcTextBlock`、期間 `TenderOfferPeriodTextBlock`。

対質問回答（`toa`）: 回答本文 `ResponsesToInquiriesTextBlock`。案件の主な数値には使いません。

自社株は `mappings/issuer_2021.json` と `issuer_2026.json` の `jptoi_cor:` です。保有比率・スポンサー・意見・成立要約は自社株の案件CSVには出しません。

---

## 6. 文章から列にする順番

Enrich は書類ごとに、次の順です（`tob/enrich_tob.py` の `apply_facts_to_row()`）。

1. タクソノミ版を決める
2. その版の要素IDで ZIP 内 CSV から値を取る
3. 届出なら、価格・期間・目的・予定数・資金・代理人・保有割合を列にする
4. 意見表明なら、意見の文章から賛同／反対を取る
5. 報告書なら、成否の文章から成立／不成立／按分と、応募株数を取る
6. 撤回なら、状態を撤回にする
7. 全書類が終わったら、CaseID ごとに案件行を作り直す

価格・レンジ・株数・プレミアムは、要素IDの値が最初から数値とは限りません。`PriceOfPurchaseEtcTextBlock` などの文章を `tob/extract_fields.py` で読んでいます。

案件行は書類を提出日の古い順に重ね、**後の書類が同じ項目を上書き**します。例外が2つあります。

- 買付後の保有割合は、届出に書いてある計画値（100% など）を使わず、報告書にある実績だけを使います。不成立・撤回のときは既存保有割合を入れます。
- 公表日前営業日の終値と1か月平均は、最初に取れた届出の文を維持します。後の訂正で別の株価に置き換えません。プレミアムはその書類の買付価格との差です。

価格や買付代金が訂正で変わったときだけ、`PriceChangeHistory` と `ConsiderationChangeHistory` に「日付 値 → 日付 値」で残します。変わっていなければ空です。

応募株数は報告書の「応募株券等の数の合計」です。買付株数は、報告書が「全部の買付け等を行います」と書いているときだけ応募株数と同じにします。按分のときは空欄です。

算定機関ごとのレンジ（`ValuationAdvisors`）は、名前とレンジが隣り合って2社以上あるときだけ入れます。1社分は `ValuationMarketMin` など既存の6列です。

株価は次のときだけ入れます。

- 「公表日の前営業日」の直後に、終値として円の金額がある
- 1か月平均は、その同じ文で「1か月、3か月、6か月」の順に平均が並んでいるときの1番目、または1か月だけが明示されているとき
- 事例のプレミアム率、中央値、「本書提出日の前営業日」の株価は使わない
- 終値が複数あり食い違う文章は空欄

---

## 7. 出力ファイル

| ファイル | 1行の意味 |
|----------|-----------|
| `output/current/tob_list.csv` | 他社株の書類 |
| `output/current/tob_cases.csv` | 他社株の案件 |
| `output/current/self_tob_list.csv` | 自社株の書類 |
| `output/current/self_tob_cases.csv` | 自社株の案件 |
| `output/current/fetch_meta.json` | 最後に取った提出日の範囲 |
| `output/snapshots/` | 同じ範囲を再実行したときのコピー |

既存の詳細列は、同じ DocID の再取得では消しません。一覧APIで上書きするのは提出日・書類種別・提出者コードなどのメタデータだけです（`merge_document_rows()`）。

---

## 8. Jupyter へ移すとき

フォルダごと置き、ノートの作業ディレクトリを `README.md` と `tob/` がある階層にします。`tob/` だけを別フォルダへ出すと import が壊れます。

```python
import os
os.environ["EDINET_API_KEY"] = "あなたのキー"

# 初回や年の取り直し
!python -m tob.fetch_tob --from-year 2024 --to-year 2026

# 毎月の更新（期間の変え方はここだけ）
!python -m tob.fetch_tob --recent-days 35

# 未処理の書類だけ中身を取る
!python -m tob.enrich_tob --only-pending
```

APIを使わず、既に保存してある文章から列だけ計算し直すときは次です。

```python
!python -m tob.enrich_tob --recompute-only
```

追加の `pip` パッケージは、この取得処理には不要です。標準ライブラリだけで動きます。Python は 3.12 を想定しています。

通信先は次の2ホストです。社内ネットで止まるときは、ここが届くかを先に確認します。

- `api.edinet-fsa.go.jp`（一覧と XBRL）
- `disclosure2dl.edinet-fsa.go.jp`（PDFと提出者リスト）

---

## 9. この仕組みでは取れないもの

次はタクソノミの項目ではなく、書類本文の要約です。別処理（保存したテキストを読む）に回しています。

- 規制承認の名前（HSR、FINRA など）と、そのタイムラインの見出し
- 案件背景や意見の短い要約
- 当初から敵対的だったか、フェアネス・オピニオンを維持したか
- キーパーソンの個人名（`SponsorHint` は会社・ファンド名まで）
