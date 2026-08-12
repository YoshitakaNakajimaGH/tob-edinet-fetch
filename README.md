# EDINET TOB 一覧・案件取得

金融庁 EDINET API から、公開買付（TOB）関連書類を取得します。

実行は **あなたのPCではなく GitHub Actions（GitHubのサーバ）** で行います。

## 出力ファイル（2つ）

| ファイル | 内容 |
|----------|------|
| [`output/tob_list.csv`](output/tob_list.csv) | **書類ごと**の生一覧（消さない） |
| [`output/tob_cases.csv`](output/tob_cases.csv) | **案件ごと**の最新1行（届出・訂正・報告書・意見表明を紐づけ＋詳細項目） |

普段の業務確認は `tob_cases.csv`、抜け漏れや履歴の確認は `tob_list.csv` を使います。

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
5. **Start date** に開始日（例: `2025/01/01`）。End date 空欄＝今日
6. 完了後、`tob_list.csv` と `tob_cases.csv`（メタデータ部分）が更新される

平日は自動でも走ります（開始日未指定＝今年1/1〜今日）。

### 2. 詳細を埋める（Enrich TOB）

一覧だけでは価格・期間などは空です。**Enrich TOB** で XBRL から詳細列を埋めます。

1. **Actions** → **Enrich TOB** → **Run workflow**
2. 初回: `case_limit` は `0`（全案件）
3. 2回目以降: **only pending** にチェックを入れると、未処理案件だけ更新
4. 完了後、`tob_cases.csv` の OfferPrice などが埋まる

所要時間の目安: 全案件で十数分（書類数×API呼び出し）。

## tob_cases.csv の見方

| 列 | 意味 |
|----|------|
| CaseID | 案件キー（多くの場合、最初の公開買付届出書の DocID） |
| OfferorName | 買付者名 |
| TargetEdinetCode | 対象会社の EDINET コード |
| FirstFilingDate / LastUpdateDate | 最初の届出日 / 最終更新日 |
| Status | 届出中 / 訂正あり / 撤回 / 報告書提出 など |
| HasOpinion | 意見表明の有無 |
| **OfferPrice** | 買付価格（届出・訂正から抽出） |
| **OfferPeriodStart / End** | 買付期間 |
| **OwnershipRatio** | 買付後の保有比率（数値） |
| **OpinionStance** | 賛同 / 反対 / 意見留保 / 要確認 |
| **FinalResultNote** | 公開買付報告書の結果要約 |
| **EnrichmentStatus** | done / partial / failed |
| Latest*DocID / DocIDList | 関連書類 |

### 詳細の上書きルール

府令の様式に対応する XBRL タクソノミから抽出し、提出日時の古い順にマージします。

- 公開買付届出書（240）→ 価格・期間・保有比率を初回セット
- 訂正届出書（250）→ 同項目を上書き
- 意見表明（290/300）→ 賛同/反対などをセット
- 公開買付報告書（270/280）→ 最終結果・期間・比率を反映
- 撤回（260）→ Status を撤回に

`EnrichmentStatus=failed` の案件は、意見表明のみ・XBRLなしなどが多いです。`tob_list.csv` の DocID から EDINET で原本を確認してください。

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

## 技術メモ（メンテ担当向け）

- 詳細抽出は **書類取得 API type=5**（XBRL ZIP 内の CSV）を使用
- 要素IDの対応は [`taxonomy_fields.json`](taxonomy_fields.json) に定義（2021年版タクソノミ実測）
- タクソノミは年度で変わるため、年1回程度の見直しが必要

## ローカルで試す場合（任意）

```bash
set EDINET_API_KEY=あなたのキー
python fetch_tob.py --from-date 2025/01/01
python enrich_tob.py --case-limit 10
python enrich_tob.py --only-pending
```

## ファイル構成

- `fetch_tob.py` … 一覧取得・案件紐づけ
- `enrich_tob.py` … XBRL から詳細抽出
- `taxonomy_fields.json` … タクソノミ要素マップ
- `.github/workflows/fetch-tob.yml` … 一覧の手動／定期実行
- `.github/workflows/enrich-tob.yml` … 詳細抽出（手動のみ）
- `output/tob_list.csv` … 書類一覧
- `output/tob_cases.csv` … 案件一覧（詳細込み）
