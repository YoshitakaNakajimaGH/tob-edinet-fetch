# EDINET TOB 一覧・案件取得

金融庁 EDINET API から、公開買付（TOB）関連書類を取得します。

実行は **あなたのPCではなく GitHub Actions（GitHubのサーバ）** で行います。

## 出力ファイル（2つ）

| ファイル | 内容 |
|----------|------|
| [`output/tob_list.csv`](output/tob_list.csv) | **正本**。書類1件につき1行。メタデータと、その書類から取れた詳細列 |
| [`output/tob_cases.csv`](output/tob_cases.csv) | **派生**。案件1件につき1行。書類正本から最新状態を再生成 |

普段の業務確認は `tob_cases.csv`、訂正前後の価格変化など履歴の確認は `tob_list.csv` を使います。

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
5. **Start year / End year** に西暦4桁（例: `2024` と `2026`）
6. 完了後、`tob_list.csv` が **DocID 単位で追加・更新** され、`tob_cases.csv` が再生成される

入力を空にすると、**今年1月1日〜実行日** を取得します。既存の詳細列は消しません。

平日の定期実行は、今年の全年ではなく **直近35日** だけを再取得して既存CSVへマージします。

### 2. 詳細を埋める（Enrich TOB）

一覧だけでは価格・期間などは空です。**Enrich TOB** で各書類の XBRL から、その書類が持つ項目だけを列に書きます。

1. **Actions** → **Enrich TOB** → **Run workflow**
2. 初回: `doc_limit` は `0`（全書類）
3. 2回目以降: **only pending**（既定オン）で未処理書類だけ更新
4. 完了後、`tob_list.csv` の書類行に OfferPrice などが入り、`tob_cases.csv` はそこから再生成される

所要時間の目安: 全書類で十数分（書類数×API呼び出し）。

## tob_cases.csv の見方

| 列 | 意味 |
|----|------|
| CaseID | 案件キー（多くの場合、最初の公開買付届出書の DocID） |
| OfferorName | 買付者名 |
| TargetEdinetCode | 対象会社の EDINET コード |
| FirstFilingDate / LastUpdateDate | 最初の届出日 / 最終更新日 |
| Status | 届出中 / 訂正あり / 撤回 / 報告書提出 など |
| HasOpinion | 意見表明の有無 |
| **OfferPrice** | 買付価格（届出・訂正の最新値） |
| **OfferPeriodStart / End** | 買付期間（最新値） |
| **OwnershipRatio** | 買付後の保有比率（最新値） |
| **OpinionStance** | 賛同 / 反対 / 意見留保 / 要確認 |
| **FinalResultNote** | 公開買付報告書の結果要約 |
| **WithdrawalReason** | 撤回理由 |
| **EnrichmentStatus** | done / partial / failed |
| Latest*DocID / DocIDList | 関連書類 |

案件CSVの詳細列は、書類正本を提出日時の古い順に重ねた **最新状態** です。履歴そのものは `tob_list.csv` に残ります。

- 公開買付届出書（240）→ 価格・期間・保有比率を初回セット
- 訂正届出書（250）→ 同項目を上書き
- 意見表明（290/300）→ 賛同/反対などをセット
- 公開買付報告書（270/280）→ 最終結果・期間・比率を反映
- 撤回（260）→ Status を撤回に

## tob_list.csv の見方

| 列 | 意味 |
|----|------|
| SubmitDateTime | 提出日時 |
| DocTypeName | 書類名 |
| RoleHint | 買付者側 / 対象会社側 の目安 |
| FilerName | 提出者 |
| SubjectEdinetCode | 対象（または意見表明時の相手方）コード |
| DocID / ParentDocID | 書類ID / 親書類ID |
| CaseID | 紐づいた案件ID |
| OfferPrice など | **その書類から取れた値だけ**（他書類の値は混ぜない） |
| TaxonomyYear / TaxonomySource | 使ったタクソノミ年版と判定方法 |
| ExtractionStatus | pending / done / partial / failed / skipped |

## 技術メモ（メンテ担当向け）

- 詳細抽出は **書類取得 API type=5**（XBRL ZIP 内の CSV）を使用
- 要素IDの対応は [`taxonomy/`](taxonomy/) に年版ごと保存
- 他社株TOBタクソノミは 2021年版（2020-11-01）が 2026-04-30 まで続き、2026年版（2025-11-01）は 2026-05-01 以後
- 訂正書類は提出年ではなく、親書類と同じタクソノミ版を使う
- Fetch は既存CSVを上書き消去せず、DocID で upsert する

## ローカルで試す場合（任意）

```bash
export EDINET_API_KEY=あなたのキー
python fetch_tob.py --from-year 2025 --to-year 2026
python fetch_tob.py --recent-days 35
python enrich_tob.py --doc-limit 10
python enrich_tob.py --only-pending
python -m unittest discover -s tests -t . -v
```

## ファイル構成

- `fetch_tob.py` … 一覧取得・既存CSVへの upsert・案件再生成
- `enrich_tob.py` … 書類単位の XBRL 抽出
- `tob_common.py` … CSV列定義・案件派生
- `taxonomy/` … 年版タクソノミの選択、年度別マッピング、公式資料の抜粋
- `.github/workflows/fetch-tob.yml` … 一覧の手動（年指定）／平日の直近35日
- `.github/workflows/enrich-tob.yml` … 詳細抽出（手動のみ）
- `output/tob_list.csv` … 書類正本
- `output/tob_cases.csv` … 案件の最新状態
