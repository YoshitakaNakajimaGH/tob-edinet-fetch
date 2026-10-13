# 休止した取得経路

2026-10 に、サイト更新で使っていない Actions・実験・古い CSV 出力をここへ移しました。GitHub が実行するのは `.github/workflows/` だけなので、ここにあるワークフローは動きません。

2027-10 以降、戻す予定がなければ削除してよいです。

## 移したもの

- `workflows/` … Fetch TOB、Enrich TOB、Enrich Self TOB、Sponsor Hint LLM、GPT Extract Lab、Filing descendants live trial、GitHub Pages の Actions デプロイ
- `experiments/` … スポンサーヒントの LLM 実験、GPT 抽出実験、書類子孫の試行
- `output/current/` … 以前の `tob_list.csv` / `tob_cases.csv` など
- `output/snapshots/` … その履歴

## 残しているもの

サイトの更新は、リポジトリ直下の IDリスト作成フローと案件JSON作成フローです。XBRL を読む Python は `tob/enrich_tob.py` などに残しています。案件 JSON がその関数をまだ呼ぶためです。Pages は master の `/docs` を branch 公開しています。
