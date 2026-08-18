# EDINET TOB 一覧・案件取得

金融庁 EDINET API から、公開買付（TOB）関連書類を取得します。

実行は **あなたのPCではなく GitHub Actions（GitHubのサーバ）** で行います。

## 出力フォルダ

普段見るのは **`output/current/`** です。Fetch / Enrich のたびに、同じ内容を日付付きでも残します。日付は **日本時間** です。

```
output/
  current/
    tob_list.csv          … 最新の他社株・書類正本
    tob_cases.csv         … 最新の他社株・案件（業務確認はここ）
    self_tob_list.csv     … 自己株式の公開買付け（書類）
    self_tob_cases.csv    … 自己株式の公開買付け（案件）
  snapshots/
    2026/08/tob_list_20260817.csv
    2026/08/tob_cases_20260817.csv
    2026/08/self_tob_list_20260817.csv
    2026/08/self_tob_cases_20260817.csv
    …（種類ごとに直近20日分）
    trash/                … 21件目以降を移動。さらに古い20件を超えたら削除
```

| ファイル | 内容 |
|----------|------|
| [`output/current/tob_list.csv`](output/current/tob_list.csv) | 他社株の書類正本。1件1行 |
| [`output/current/tob_cases.csv`](output/current/tob_cases.csv) | 他社株の案件。1件1行 |
| [`output/current/self_tob_list.csv`](output/current/self_tob_list.csv) | 自社株TOBの書類。提出者コード＝対象会社コード |
| [`output/current/self_tob_cases.csv`](output/current/self_tob_cases.csv) | 自社株TOBの案件 |

意見表明報告書は独立した案件行にはしません。同じ買付者・対象会社の届出／報告書の行に `OpinionStance`（賛同／反対）を載せます。

同じ日に2回更新すると、その日のスナップショットは上書きされます（スロットは増えません）。

普段の業務確認は `current/tob_cases.csv`、過去の時点の確認は `snapshots/`、誤って古くなった分は `snapshots/trash/` を見ます。

## 初回だけ（管理者）

1. このリポジトリの **Settings → Secrets and variables → Actions**
2. **New repository secret**
3. Name: `EDINET_API_KEY`
4. Value: EDINET で発行した APIキー
5. 保存

APIキー発行: https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1

## 日常の使い方（自分・後継者）

### 1. 一覧を更新する（Fetch TOB）

1. このリポジトリを開く
2. **Actions** タブ
3. 左の **Fetch TOB** を選ぶ
4. **Run workflow**
5. ブランチはマージ後の `master` を選び、**開始年 / 終了年** をドロップダウンから指定（例: `2024` と `2026`）
6. 完了後、`output/current/tob_list.csv` が **DocID 単位で追加・更新** され、`tob_cases.csv` が再生成される。同じ内容が `output/snapshots/年/月/tob_list_YYYYMMDD.csv` にも残る

終了年が今年の場合、取得の終わりは **実行日** までです。既存の詳細列は消しません。

平日の定期実行は、今年の全年ではなく **直近35日** だけを再取得して既存CSVへマージします。

### 2. 詳細を埋める（Enrich TOB）

一覧だけでは価格・期間などは空です。**Enrich TOB** で各書類の XBRL から、その書類が持つ項目だけを列に書きます。

1. **Actions** → **Enrich TOB** → **Run workflow**
2. 初回: `doc_limit` は `0`（全書類）
3. 2回目以降: **only pending**（既定オン）で未処理書類だけ更新
4. 完了後、`output/current/tob_list.csv` の書類行に OfferPrice などが入り、`tob_cases.csv` はそこから再生成される

所要時間の目安: 全書類で十数分（書類数×API呼び出し）。

## tob_cases.csv の見方

左に人が読む項目、右にID類を置いています。

| 列 | 意味 |
|----|------|
| OfferorName | 買付者名（届出書の表紙「届出者の氏名又は名称」） |
| TargetSecCode | 対象会社の証券コード（4桁。意見表明書の提出者コード、または EDINET 提出者リストから補完） |
| TargetName | 対象会社名（見出し「（１）【対象者名】」は除去） |
| Status | 届出中 / 訂正あり / 撤回 / 報告書提出 など |
| OfferPrice | 買付価格（普通株式1株あたり） |
| OfferPeriodStart / End | 買付期間。延長があれば延長後 |
| ExistingHoldingRatio | すでに買付者＋特別関係者が持つ株券等所有割合 |
| SpecialRelatedHoldingRatio | 特別関係者だけの既保有割合 |
| AfterPurchaseRatio | 買付後の実際の株券等所有割合。届出書の予定値（100%など）は使わない。不成立・撤回なら既保有と同じ。実施中は空 |
| SponsorHint | 届出書「買付け等の目的」の（１）本公開買付の概要・二段落目先頭の「Xは、」から取ったスポンサー候補（補助情報） |
| IsMBO | 本文に MBO / マネジメント・バイアウト等の記載があれば `Yes` |
| ValuationMarketMin / Max など | 第1部§4(2)「算定の基礎」の市場株価法・類似上場会社比較法・DCF法の1株当たり株式価値レンジ（円） |
| PlannedSharesMin / Max | 第1部§4(3)「買付予定の株券等の数」の**合計**行の下限・上限（株数） |
| PlannedSharesPlanned | 合計行に上限・下限がなく、買付予定数だけ書かれている場合の株数 |
| PurchaseConsideration | 第1部§8「買付け等に要する資金」の買付代金（a）（単位付き。例: `38,234,567,890円`） |
| TenderOfferAgent | 第1部§7(1)①公開買付代理人（なければ表紙の代理人名称） |
| OpinionStance | 賛同 / 反対 / 意見留保 / 要確認 |
| FinalResultNote | `成立` / `成立（按分）` / `不成立` / `撤回`。報告書の成否本文から判定。撤回届出があれば撤回 |
| TargetDelistingNote | 対象会社の上場廃止状況。`上場廃止済` / `上場廃止予定` / `上場維持`（意見表明本文と EDINET 提出者リストの上場区分から推定） |
| FirstFilingDate / LastUpdateDate | 最初の届出日 / 最終更新日 |
| CaseID 以降 | 書類ID・EDINETコードなど |

案件CSVの詳細列は、書類正本を提出日時の古い順に重ねた **最新状態** です。履歴は `tob_list.csv` に残ります。

## tob_list.csv の見方

書類1件1行です。左側が数値・名称、右側がIDです。

| 列 | 意味 |
|----|------|
| SubmitDateTime / DocTypeName | 提出日時・書類名 |
| OfferorName / TargetSecCode / TargetName | 買付者・対象会社の証券コード・対象会社名 |
| OfferPrice / OfferPeriodStart / End | その書類に書かれた価格・期間 |
| ExistingHoldingRatio | 買付者＋特別関係者の既保有割合 |
| SpecialRelatedHoldingRatio | 特別関係者の既保有割合 |
| AfterPurchaseRatio | その書類に書かれた買付後所有割合（届出書は予定値） |
| OpinionStance / FinalResultNote など | その書類から取れた値だけ。案件の成否は `tob_cases.csv` を見る |
| DocID / ParentDocID / CaseID | 書類ID類（右寄り） |

## 抜き出しロジック（Enrich）

公開買付届出書（240/250）の XBRL CSV から次の要素を使います。

- 買付者名: `FullNameOrNameOfFilerOfNotificationCoverPage`（なければ一覧APIの提出者名）
- 対象会社名: `NameOfSubjectCompanyTextBlock`（先頭の「（１）【対象者名】」などは除去）
- 買付価格: `PriceOfPurchaseEtcTextBlock` から普通株式1株あたり（円・ウォン・株式対価）。同ブロック内「算定の基礎」から評価レンジも抽出
- 買付期間: `PeriodOfPurchaseEtcTextBlock`（2021年版は `OriginalPeriodAtFilingTextBlock`）。延長記載があれば最後の自〜至
- 買付予定株数: `NumberOfShareCertificatesEtcIntendedToPurchaseTextBlock` から**合計**行の下限・上限、または単独の買付予定数
- 買付代金: `FundEtcForPurchaseEtcTextBlock` から 買付代金（a）
- 公開買付代理人: `HowToAcceptTextBlock` の ①公開買付代理人（なければ表紙 `NameOfLegalRepresentativeCoverPage`）
- スポンサー候補: `PurposesOfPurchaseEtcTextBlock`（または `OverviewOfPurchaseEtcTextBlock`）の本公開買付の概要・二段落目
- MBO: 目的・概要・意見表明本文から MBO / マネジメント・バイアウト等を検索
- 既保有割合: 議決権数 (d)+(g) を総議決権 (j) で割る。d=買付者、g=特別関係者
- 買付後割合（書類）: `HoldingRatioOfShareCertificatesEtcAfterPurchaseEtc`（届出書は予定。案件行では使わない）
- 成否: 公開買付報告書の `SuccessOrFailureOfTenderOfferTextBlock` から、応募数と下限・上限を読んで `成立` / `成立（按分）` / `不成立`。撤回届出書があれば `撤回`
- 対象証券コード: 意見表明書（290/300）の `secCode`、または EDINET 提出者リストの証券コード列
- 上場廃止: 意見表明本文の「上場廃止予定」等の記載と、EDINET 提出者リストの上場区分（成立後に `非上場` なら `上場廃止済`）

## 技術メモ（メンテ担当向け）

- 詳細抽出は **書類取得 API type=5**（XBRL ZIP 内の CSV）を使用
- 要素IDの対応は [`taxonomy/`](taxonomy/) に年版ごと保存
- 他社株TOBタクソノミは 2021年版（2020-11-01）が 2026-04-30 まで続き、2026年版（2025-11-01）は 2026-05-01 以後
- 訂正書類は提出年ではなく、親書類と同じタクソノミ版を使う
- Fetch は既存CSVを上書き消去せず、DocID で upsert する
- 自己株式の公開買付けは `self_tob_*.csv` に分け、他社株の `tob_cases.csv` からは外す
- 意見表明だけの行は作らず、同じ会社ペアの届出案件に賛同／反対を載せる
- 結果は `output/current/` が最新。日付付きコピーは `output/snapshots/` に最大20件。それより古いものは `snapshots/trash/` へ移動

### OfferPriceRaw の文字数上限について

EDINET から取得した「買付け等の価格」の**原文**を CSV に保存する列が `OfferPriceRaw` です。届出書の価格欄は非常に長く（算定の基礎・プレミアム率の説明など）、そのまま全部を CSV に入れるとファイルが巨大になったり、Excel で扱いにくくなったりします。

そのため、**先頭から一定文字数だけ**を `OfferPriceRaw` に保存しています（現在は 5000 文字）。一方、CSV に書き込む前の**全文**からは `OfferPrice`（1株あたり価格）や評価レンジ（市場株価法・DCF など）を抽出するので、Enrich 実行時点では後半に書かれた数値も取りこぼしません。

既存 CSV を `--recompute-only` で再計算する場合は、保存済みの `OfferPriceRaw`（短い断片）しか見えないため、5000 文字を超える後半の情報は再抽出できません。全件を埋めるには Enrich TOB の再実行が必要です。

## ローカルで試す場合（任意）

```bash
export EDINET_API_KEY=あなたのキー
python fetch_tob.py --from-year 2025 --to-year 2026
python fetch_tob.py --recent-days 35
python enrich_tob.py --doc-limit 10
python enrich_tob.py --only-pending
python enrich_tob.py --recompute-only
python -m unittest discover -s tests -t . -v
```

## ファイル構成

- `fetch_tob.py` … 一覧取得・既存CSVへの upsert・案件再生成
- `enrich_tob.py` … 書類単位の XBRL 抽出
- `edinet_code_list.py` … EDINET 提出者リスト（証券コード・上場区分）の取得とキャッシュ
- `tob_common.py` … CSV列定義・案件派生
- `taxonomy/` … 年版タクソノミの選択、年度別マッピング、公式資料の抜粋
- `output_store.py` … current / 日付付きスナップショット / ごみ箱
- `.github/workflows/fetch-tob.yml` … 一覧の手動（年指定）／平日の直近35日
- `.github/workflows/enrich-tob.yml` … 詳細抽出（手動のみ）
- `output/current/` … 最新の他社株・自社株CSV
- `output/snapshots/` … 日付付き履歴（直近20件）と `trash/`
