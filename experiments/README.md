# experiments/

本番パイプライン（`tob/fetch_tob.py` / `tob/enrich_tob.py`）とは切り離した **試作・検証用** の置き場です。

| ディレクトリ | 目的 |
|---|---|
| [`gpt-extract/`](gpt-extract/) | ChatGPT 等で TOB 提出書・報告書 PDF から情報を抜き取り、専用 CSV に書き込む実験 |
| [`sponsor-hint-llm/`](sponsor-hint-llm/) | Enrich 済み CSV テキストを Gemini に渡し SponsorHint を推論・更新 |

本番の `output/current/` には手を入れず、ここだけで試行錯誤できます。
