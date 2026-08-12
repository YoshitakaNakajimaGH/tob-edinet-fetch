# EDINET TOB 一覧・案件取得

金融庁 EDINET API から、公開買付（TOB）関連書類を取得します。

実行は **あなたのPCではなく GitHub Actions（GitHubのサーバ）** で行います。

## 出力ファイル（2つ）

| ファイル | 内容 |
|----------|------|
| [`output/tob_list.csv`](output/tob_list.csv) | **書類ごと**の生一覧（消さない） |
| [`output/tob_cases.csv`](output/tob_cases.csv) | **案件ごと**の最新1行（届出・訂正・報告書・意見表明を紐づけ） |

普段の業務確認は `tob_cases.csv`、抜け漏れや履歴の確認は `tob_list.csv` を使います。

## 初回だけ（管理者）

1. このリポジトリの **Settings → Secrets and variables → Actions**
2. **New repository secret**
3. Name: `EDINET_API_KEY`
4. Value: EDINET で発行した APIキー
5. 保存

APIキー発行: https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1

## 日常の使い方（自分・後継者）

1. このリポジトリを開く
2. 上の **Actions** タブ
3. 左の **Fetch TOB** を選ぶ
4. 右の **Run workflow**
5. **Start date** に開始日を入れる（例: `2025/01/01` または `2025-01-01`）
6. End date は空欄なら今日まで
7. 実行後、上記2つの CSV が更新される

平日は自動でも走ります（開始日未指定＝今年1/1〜今日）。手動実行もいつでもできます。

## tob_cases.csv の見方

| 列 | 意味 |
|----|------|
| CaseID | 案件キー（多くの場合、最初の公開買付届出書の DocID） |
| OfferorName | 買付者名 |
| TargetEdinetCode | 対象会社の EDINET コード |
| FirstFilingDate / LastUpdateDate | 最初の届出日 / 最終更新日 |
| Status | 届出中 / 訂正あり / 撤回 / 報告書提出 など |
| HasOpinion | 意見表明の有無 |
| Latest*DocID | 最新の届出・意見表明・報告書の DocID |
| DocIDList | 紐づいた書類ID一覧 |

空欄の列（OfferPrice, OfferPeriodStart/End, OwnershipRatio, OpinionStance など）は、将来 PDF から価格・期間・保有比率・賛同/反対を入れて**同じ行を上書き更新**するための予約列です。

将来の更新イメージ:

- 公開買付届出書 → 価格・期間・保有比率を初回セット
- 訂正届出書 → 同じ項目を新しい値で上書き
- 公開買付報告書 → 最終結果を反映
- 意見表明報告書 → 賛同／反対をセット

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

## ローカルで試す場合（任意）

```bash
set EDINET_API_KEY=あなたのキー
python fetch_tob.py --from-date 2025/01/01
```

## ファイル構成

- `fetch_tob.py` … 取得・案件紐づけ（この1本）
- `.github/workflows/fetch-tob.yml` … 手動／定期実行
- `output/tob_list.csv` … 書類一覧
- `output/tob_cases.csv` … 案件一覧
- `README.md` … この説明
