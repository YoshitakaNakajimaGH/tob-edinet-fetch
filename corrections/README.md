# 修正用 CSV

`overrides.csv` に、生成結果へ残したいセルだけを書きます。案件JSON作成フローは、機械が書いた `output/case_summaries/all.csv` を残したまま、このファイルを重ねた結果を `docs/data/all.csv` と `docs/data/self_tob.csv` に書きます。

- 列名はまとめ CSV と同じです。ヘッダは空の `overrides.csv` に入っています。
- 直す案件の行だけを追加します。`caseId` は必須です。
- 空欄のセルは変えません。値を消したいときは、セルに `-` など明示の文字を入れます。
- 同じ `caseId` を二行書くと、その実行は止まります。
- 知らない列名でも止まります。
- `caseId` がまとめ CSV に無い行は無視し、ログに出します。

サイトが見るのは `docs/data/` の方です。`output/case_summaries/` は修正前の生成結果です。
