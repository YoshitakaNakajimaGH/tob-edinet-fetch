# EDINET TOB 一覧取得

金融庁 EDINET API から、公開買付（TOB）関連書類の一覧を取得し、`output/tob_list.csv` に保存します。

実行は **あなたのPCではなく GitHub Actions（GitHubのサーバ）** で行います。

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
5. 期間（`this_year` = 今年 / `past_year` = 過去1年）を選んで実行
6. 完了後、[`output/tob_list.csv`](output/tob_list.csv) を開く／ダウンロード

平日は自動でも走ります（日本時間の朝あたり）。手動実行もいつでもできます。

## CSV の見方

| 列 | 意味 |
|----|------|
| SubmitDateTime | 提出日時 |
| DocTypeName | 書類名（公開買付届出書、意見表明報告書など） |
| RoleHint | 買付者側 / 対象会社側 の目安 |
| FilerName | 提出者 |
| SubjectEdinetCode | 公開買付の対象会社コード |
| DocDescription | 書類概要 |
| DocID | EDINET上の書類ID |

意見表明報告書があると、対象会社側の動きが分かります。賛同か反対かは本文（PDF）の確認が必要です。

## ローカルで試す場合（任意）

```bash
set EDINET_API_KEY=あなたのキー
python fetch_tob.py --period this_year
```

## ファイル構成

- `fetch_tob.py` … 取得処理（この1本）
- `.github/workflows/fetch-tob.yml` … 手動／定期実行の定義
- `output/tob_list.csv` … 最新結果
- `README.md` … この説明
