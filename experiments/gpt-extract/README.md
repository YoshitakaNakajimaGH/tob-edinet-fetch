# GPT Extract Lab（TOB PDF → CSV 実験場）

公開買付（TOB）案件について、EDINET から **PDF を一時取得** し、ChatGPT（OpenAI API）で必要項目だけを抜き取って **専用 CSV** に書き込む実験用フォルダです。

## 想定フロー

```mermaid
flowchart LR
  A[tob_cases.csv] --> B[cases/queue.csv]
  B --> C[fetch_case_pdfs.py]
  C --> D[pdfs/CaseID/*.pdf]
  D --> E[run_gpt_extract.py]
  E --> F[output/gpt_extract.csv]
  F --> G[既存 enrich 結果と比較]
```

1. **案件を選ぶ** — `cases/queue.csv` に `CaseID` を登録（または `--case-id` で直接指定）
2. **PDF を取得** — EDINET API で届出書・報告書・意見表明などを `pdfs/{CaseID}/` に保存（Git には載せない）
3. **GPT で抽出** — 軽量モデル（既定: `gpt-4o-mini`）で 1 案件ずつ実行
4. **CSV に追記** — `output/gpt_extract.csv` に 1 行（または書類ごと）で書き込み
5. **検証** — 本番の XBRL 抽出結果（`output/current/tob_cases.csv`）と突合

## ディレクトリ構成

```
experiments/gpt-extract/
├── README.md              … このファイル
├── cases/
│   └── queue.csv          … 処理キュー（pending / done / failed）
├── schema/
│   └── extract_fields.json … GPT に渡す抽出項目定義
├── pdfs/                  … 一時 PDF（.gitignore）
├── output/
│   └── gpt_extract.csv    … GPT 抽出結果
└── scripts/
    ├── fetch_case_pdfs.py … PDF ダウンロード
    ├── run_gpt_extract.py … OpenAI API で抽出
    └── run_one_case.py    … 1 案件を fetch → extract まで実行
```

## 必要な環境変数

| 変数 | 用途 |
|---|---|
| `EDINET_API_KEY` | PDF 取得（本番 Fetch と同じ） |
| `OPENAI_API_KEY` | GPT 抽出 |

ローカルでは `.env` を置いてもよいですが、**コミットしない** でください。

## 使い方（ローカル）

```bash
# リポジトリルートで
export EDINET_API_KEY=...
export OPENAI_API_KEY=...

# 1) PDF を取得（例: CaseID S100M232）
python experiments/gpt-extract/scripts/fetch_case_pdfs.py --case-id S100M232

# 2) GPT で抽出（軽量モデル）
python experiments/gpt-extract/scripts/run_gpt_extract.py --case-id S100M232

# または 1+2 をまとめて
python experiments/gpt-extract/scripts/run_one_case.py --case-id S100M232
```

### キューを回す

`cases/queue.csv` の `Status=pending` を上から 1 件処理:

```bash
python experiments/gpt-extract/scripts/run_one_case.py --from-queue
```

案件をキューに追加（先頭 5 件を pending で登録）:

```bash
python experiments/gpt-extract/scripts/run_one_case.py --seed-queue 5
```

## 軽量モデルで回し続けるイメージ

- **1 案件 = 数 MB の PDF + 1 API 呼び出し** なので、`gpt-4o-mini` 等の小型モデル向き
- cron や GitHub Actions の **手動 workflow** で `--from-queue` を定期実行すれば、少しずつ CSV が育つ
- PDF は処理後 `--clean-pdfs` で削除可能（ディスク節約）

## 本番パイプラインとの関係

| | 本番 (`tob/enrich_tob.py`) | この実験場 |
|---|---|---|
| 入力 | XBRL (type=5) | PDF (type=1) |
| 出力 | `output/current/tob_list.csv` | `experiments/gpt-extract/output/gpt_extract.csv` |
| 目的 | 安定・再現可能な全件処理 | GPT 抽出の精度・コスト検証 |

精度が確認できた項目だけ、本番のルールベース抽出や SponsorHint 推論へフィードバックする想定です。

## オプション依存

PDF テキスト化に `pypdf` を使います（未インストール時は `pip install pypdf`）。

```bash
pip install pypdf
```
