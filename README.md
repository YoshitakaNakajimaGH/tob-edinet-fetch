# EDINET TOB 一覧・案件取得

金融庁 EDINET API から公開買付（TOB）関連書類（docTypeCode 240〜320）を取得し、CSV にまとめるリポジトリです。

**実行場所:** あなたの PC ではなく **GitHub Actions**（GitHub のサーバ）  
**普段見るファイル:** `output/current/tob_cases.csv`（他社株の案件一覧）

---

## 初回セットアップ（管理者）

1. リポジトリ **Settings → Secrets and variables → Actions**
2. **New repository secret** → Name: `EDINET_API_KEY`
3. [EDINET API キー](https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1) を登録

---

## アクション（GitHub Actions）

Actions タブ → 左のワークフロー名 → **Run workflow** → ブランチ `master` を選んで実行します。  
完了すると `output/` 以下が更新され、変更があれば自動 commit されます。

### 実行の順番（推奨）

```
1. Fetch TOB        … 書類一覧の取得・更新（必須・最初に実行）
2. Enrich TOB       … 他社株 TOB の XBRL 詳細抽出
3. Enrich Self TOB  … 自社株 TOB の XBRL 詳細抽出（必要な場合のみ）
```

Fetch を実行しないと Enrich は `fetch_meta.json` が無くて失敗します。

---

### 1. Fetch TOB — 書類一覧の取得

**役割:** EDINET から TOB 関連書類のメタデータ（提出日・書類種別・DocID など）を取得し、CSV に upsert する。案件 CSV も再生成する。

| トリガー | 内容 |
|----------|------|
| **手動 Run workflow** | 開始年・終了年を指定してその期間を取得 |
| **平日スケジュール**（自動） | 直近 35 日だけ再取得してマージ |

**手動実行の入力**

| 入力 | 意味 |
|------|------|
| 開始年 / 終了年 | 取得する暦年。終了年が今年なら **実行日まで** |

**出力ファイル**

| ファイル | 内容 |
|----------|------|
| `output/current/tob_list.csv` | 他社株・書類 1 件 1 行 |
| `output/current/tob_cases.csv` | 他社株・案件 1 件 1 行 |
| `output/current/self_tob_list.csv` | 自社株 TOB・書類 |
| `output/current/self_tob_cases.csv` | 自社株 TOB・案件 |
| `output/current/fetch_meta.json` | 取得範囲（Enrich が参照） |
| `output/snapshots/tob_list_YYYYMM-YYYYMM_0001.csv` など | 上記と同内容の履歴（範囲ごと最大 20 件） |

**ポイント**

- 既存行の **詳細列（Enrich で埋めた列）は消さない**。DocID 単位で upsert。
- 同じ取得範囲で同日に再実行するとスナップショット連番が `_0002`, `_0003` … と増える。
- **API 間隔:** 未キャッシュの日だけ `--sleep` 秒待機（既定 **0.5 秒**）。8 年分の初回取得では日数 × 0.5 秒が下限。429 等が出たら Actions 入力で 1.0〜2.0 に増やす。キャッシュ済みの日は待機しない。

---

### 2. Enrich TOB — 他社株 TOB の詳細抽出

**役割:** `tob_list.csv` の各行について EDINET から XBRL（type=5）を取得し、価格・期間・スポンサー候補などを列に書く。完了後 `tob_cases.csv` を再生成する。

**入力（Run workflow 時）**

| 入力 | 既定 | 意味 |
|------|------|------|
| `doc_limit` | `0` | 処理する書類数の上限。`0` = 全件 |
| `only_pending` | **ON** | `done` / `partial` / `skipped` 済みの書類をスキップ |
| `force_refresh` | OFF | ON にするとキャッシュ済み XBRL も再ダウンロード |
| `fields` | `all` | 更新する列グループ（下表）。例: `valuation,fund` |
| `recompute_only` | OFF | ON なら **API 不使用**。既存 Raw 列から再計算のみ |

**`fields` で選べるグループ（他社株）**

| グループ | 主な列 |
|----------|--------|
| `all` | すべて |
| `basic` | 価格・期間・名称・成否・Taxonomy など |
| `valuation` | 評価レンジ（市場株価法・DCF 等）、PurposesRaw |
| `planned_shares` | 買付予定株数 |
| `fund` | 買付代金 |
| `sponsor` | SponsorHint、IsMBO |
| `agent` | TenderOfferAgent |
| `holdings` | 既保有・買付後割合 |
| `opinion` | OpinionStance |
| `result` | FinalResultNote、報告書関連 Raw（書類 CSV 用） |

**出力:** Fetch と同じ 4 CSV + スナップショット。Enrich 済みの列が `tob_list.csv` に入り、案件は `tob_cases.csv` に集約される。

**所要時間の目安:** 未処理が数百〜千件あると **数十分〜数時間**（1 書類あたり API + 待機時間）。2 回目以降は `only_pending: ON` のままがおすすめ。

---

### 3. Enrich Self TOB — 自社株 TOB の詳細抽出

**役割:** `self_tob_list.csv` だけを対象に、自社株向けタクソノミ（`jptoi_cor`）から詳細を抽出する。

**入力:** Enrich TOB と同様（`fields` のグループ名だけ異なる）。

**`fields` グループ（自社株）:** `all` / `basic` / `planned_shares` / `fund` / `agent` / `result`

| 書類 | 抽出する主な項目 |
|------|------------------|
| 届出 240/250 | 買付期間・価格・買付予定数・代理人・買付代金 |
| 報告 270/280 | 買付期間・按分の有無（`ProrataUsed`、書類 CSV のみ） |
| 撤回 260 | 撤回理由・期間 |

自社株の案件 CSV には他社株向け列（保有比率・SponsorHint・FinalResultNote 等）は **載せません**。

**出力:** 4 CSV すべて更新（他社株 CSV は中身はほぼ変更なし）。

---

### 4. IDリスト作成フロー — 届出書から書類IDを確定

**役割:** 保存済みCSVは読まず、EDINETの一覧APIから、指定した月に出た公開買付届出書（240）と、そこから `ParentDocID` でつながる書類のIDリストをJSONで作る。XBRL本文は取らない。

**入力（Run workflow 時）**

| 入力 | 既定 | 意味 |
|------|------|------|
| 開始月 | 空欄 | `YYYY-MM`。空欄なら **183日の窓が閉じた直近の月**（2026年10月5日なら2026年3月） |
| 終了月 | 空欄 | `YYYY-MM`。空欄なら開始月と同じ（その1ヶ月だけ） |
| 結果をリポジトリに保存する | **ON** | OFF のときは実行ログと artifact だけ。`output/id_lists/` は更新しない |

届出日から183日後までを関連書類の範囲にする。その日がまだ来ていなければ実行日まで取り、JSONの `window_closed` は `false` になる。183日を過ぎていて失敗日がなければ `true`。保存済みの案件では、届出から報告書まで中央値44日、90%は61日以内、最長182日だったので、183日で足りています。月末に出て182日かかった案件まで揃うのは、その月末から183日後です。

**出力:** `output/id_lists/YYYY-MM.json`（届出月ごと）

---

### 5. 案件JSON — 抽出結果の保管

IDリストの次に、書類ごとのXBRLから読み取った値を **1案件1ファイル** にします。CSVやIDリストとは別のフォルダです。

```
output/cases/YYYY/MM/{届出書DocID}.json
```

例: `output/cases/2026/03/S100AAAA.json`

このJSONをローカルへコピーすれば、リポジトリの外で一覧・価格・プレミアムの分析用アプリを作れます。中身は次のとおりです。

| 場所 | 内容 |
|------|------|
| `core` | 最終の買付価格・期間・保有比率・意見・結果。不明は `null`、本当の0は `0`。比率は `0.3538` のような小数。議決権が無くても「所有しておりません」と書いてあれば保有比率は `0` |
| `core.IsMBO` | この取引がMBOだと書かれているときだけ `Yes`。`該当しません`、定義の注、`ＭＢＯ等`、他案件の事例は `No` |
| `core.TargetListingStatus` | 対象会社の今の上場区分。例: `東証プライム`、`東証スタンダード`、`札証本則`、`株主コミュニティ`、`非上場` |
| `core.TargetDelistingNote` | 今回のTOBで上場廃止になる見込か。もともと非上場・株主コミュニティの会社は `null` |
| `referencePrices` / `premiums` | 取引所の公表日前営業日の終値と1・3・6か月平均。プレミアムは `(買付価格-基準)/基準`。株主コミュニティの売買価格はここには入れない |
| `agreedTender` | 応募契約で合意した株数と所有割合。`parties` は株主ごとの内訳 |
| `fairnessMeasures` | 特別委員会、第三者算定、リーガルアドバイザー、対抗買付の機会、マジョリティ・オブ・マイノリティ。書いてない項目は `null` |
| `buyerStructure` | 買付者、その株式を所有するファンドまたは親会社、運営者、その親会社。概要の段落に書いてある名前だけ |
| `financing` | 出資枠、借入枠、貸付人、取得株式を担保にする予定か、自己資金で賄うか。金額は書かれた上限であり、実行額ではない。上限が無く銀行名だけのときは貸付人だけを入れ、金額は `null`。新たな資金調達をしないと書いてあるとき借入枠は `0`。書いてなければ `null` |
| `sources` | `core` の値がどの書類から来たか。`docId`、`docTypeCode`（240 届出書、250 訂正届出書、270 報告書、290 意見表明など）、`docTypeName`。値が無い項目は `null` |
| `valuations` | 算定機関ごとの市場株価法・類似会社比較法・DCF。買付者側と対象会社側は別レコード。レンジは足し合わせない。各レコードに `sourceDocId` と `sourceDocTypeCode` |
| `changes` | 価格・期間・意見などの変更。同じ訂正書類の変更は同じ `changeNo`。各行に `sourceDocId` と `sourceDocTypeCode` |
| `timeline` | 届出・意見・訂正・報告・撤回 |
| `documents` | 各書類のタクソノミ本文。EDINETのCSVは長いテキストブロックを約3万字で切るので、XBRLインスタンスの全文を使う |

市場株価法とDCFに専用の数値要素はありません。価格・目的・意見のテキストブロックの中のレンジを読みます。株価は `PriceOfPurchaseEtcTextBlock` に加え、`最近の株価及び株式売買高` と `株価の状況` の要素も見ます。

`sources` は、買付価格・期間・予定株数・買付代金・代理人・保有比率・意見・結果・スポンサー候補・基準株価が、届出書・訂正届出書・意見表明報告書・公開買付報告書のどれから読んだ値かを示します。訂正で価格が変わっていれば、価格の出典は訂正届出書（250）になります。

`IsHostileInitial` は最初の意見表明だけを見ます。あとから賛同に変わっても書き換えません。`ExistingHoldingRatio` は公開買付者自身の議決権割合で、特別関係者分は足しません。議決権の数値が無く、届出書が公開買付者の対象者株式の未保有を書いているときだけ `0` にします。`いずれも` と書いて関係者も未保有のときだけ、特別関係者の比率も `0` にします。`AfterPurchaseRatio` は書類に書いてある割合だけを使い、議決権から再計算しません。

生成AIの要約や、スポンサー名の外部推定はこのJSONに入れません。

各案件の `pdfLinks` に、公開買付届出書・意見表明報告書・公開買付報告書などの PDF 直リンクを入れます。XBRLが取れなくても、DocID からリンクは残します。形式は `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{DocID}.pdf` です。

同じ実行で、検索用のサマリCSVを書きます。1行が1案件で、価格・期間・保有比率・予定株数・買付代金・代理人・結果・基準株価・プレミアム・買付者側と対象者側の算定レンジだけです。本文は入れません。比率はJSONと同じ小数です。買付前の保有比率は買付者自身だけで、特別関係者は別の列です。`OfferorDcfMin` などは買付者側が依頼した、対象会社株式の算定です。

- `output/case_summaries/YYYY/MM.csv` … その月
- `output/case_summaries/YYYY/YYYY.csv` … 12月をまとめたときだけ、その年の1月〜12月をこの順で結合
- `output/case_summaries/all.csv` … それまでに書いた月次CSVの全部

検索用の静的ページは `site/` です。`all.csv` と同じ内容を `site/data/all.csv` にも書き、次の画面を用意しています。

- `index.html` … 名称・届出月・結果で絞り込む案件検索
- `years.html` … 暦年ごとの一覧（対象会社・買収者・プレミアム・MBO・敵対的・買付期間の日数）

ローカルでは次で開けます。

```bash
python -m http.server 8765 --directory site
```

ブラウザで `http://localhost:8765`（検索）または `http://localhost:8765/years.html`（暦年一覧）を開いてください。`file://` ではCSVを読めないことがあります。

**月次更新との連動:** 「案件JSON作成フロー」で結果を保存すると、`site/data/all.csv` も同じコミットに入ります。ページ本体を直さなくても、次回サイトを開けば新しい案件が出ます。

**GitHub Pages（任意・ネット公開）:** `site/` を公開する workflow は `.github/workflows/pages.yml` です。`master` の `site/**` が変わるとデプロイします。初回だけ自分で有効化してください。

1. リポジトリ → **Settings** → **Pages**
2. Source を **GitHub Actions** にする
3. リポジトリが **private** のままなら、Pages は Free では使えません（public にするか、有料プラン）。公開後のサイトURLは誰でも見られます

有効化後、Actions の「Deploy site to GitHub Pages」が通ると  
`https://<user>.github.io/tob-edinet-fetch/` のような URL になります。

**Actions:** 「案件JSON作成フロー」。開始月・終了月の入力は IDリスト作成フローと同じです。空欄の開始月は、183日の窓が閉じた直近の月です。対象月の `output/id_lists/YYYY-MM.json` が先にないと止まります。このフローは書類ごとにCSV（type=5）とXBRLインスタンス（type=1）を取り、本文は長い方を保存します。

```bash
python -m tob.case_json --from-month 2026-03
```

---

## 出力フォルダの構造

```
output/
  current/          … 常に最新（ここを見る）
    tob_list.csv
    tob_cases.csv
    self_tob_list.csv
    self_tob_cases.csv
    fetch_meta.json
  id_lists/         … 届出月ごとの書類IDリスト（YYYY-MM.json）
  cases/YYYY/MM/    … 抽出済みの案件JSON（届出書DocID.json）
  case_summaries/YYYY/MM.csv … 月次サマリ
  case_summaries/YYYY/YYYY.csv … 12月処理時の年次サマリ
  case_summaries/all.csv … 取得済み全案件のサマリ
site/               … all.csv を読む検索・暦年一覧（data/all.csv を同梱）
  snapshots/        … 履歴（tob_list_202001-202012_0001.csv 形式）
  snapshots/trash/  … 古い履歴
```

---

## どの CSV を見るか

| 目的 | ファイル |
|------|----------|
| 案件単位で一覧確認（**メイン**） | `tob_cases.csv` |
| 1 書類ずつ詳細・Raw テキスト | `tob_list.csv` |
| 自社株 TOB の案件 | `self_tob_cases.csv` |
| 自社株 TOB の書類 | `self_tob_list.csv` |

意見表明報告書（290/300）だけのグループは **案件行を作りません**。同じ買付者・対象会社の届出案件に `OpinionStance` を載せます。

---

## 案件 CSV（`tob_cases.csv`）の主な列

左から人が読む項目、右端付近が ID 類です。

| 列 | 意味 |
|----|------|
| OfferorName | 買付者名 |
| **SponsorHint** | スポンサー候補（2 列目） |
| TargetSecCode / TargetName | 対象会社 |
| Status | 届出中 / 訂正あり / 報告書提出 / 撤回 など |
| OfferPrice / OfferPeriodStart / End | 価格・期間 |
| ExistingHoldingRatio など | 既保有・買付後割合 |
| IsMBO / Valuation* / PlannedShares* | MBO フラグ・評価レンジ・買付予定株数 |
| PurchaseConsideration / TenderOfferAgent | 買付代金・公開買付代理人（会社名のみ） |
| OpinionStance | 賛同 / 反対 など |
| **FinalResultNote** | `成立` / `成立（按分）` / `不成立` / `撤回` |
| TargetDelistingNote | 今回のTOBで上場廃止になる見込み。`上場を維持するためのコスト` は維持決定にしない。もともと非上場の会社は空欄 |
| **LatestFilingUrl** | 届出書（240/250 の最新・訂正含む）の EDINET PDF URL |
| **LatestOutcomeUrl** | 報告書（270/280）または撤回書（260）の最新の EDINET PDF URL |
| FirstFilingDate / LastUpdateDate | 最初の届出日 / 最終更新日 |
| CaseID / LatestFilingDocID など | 内部 ID |

**案件 CSV に載せないもの:** `ProrataUsed`  
按分の有無は **`FinalResultNote` が `成立（按分）` かどうか** で判断します。

報告書から取れた応募株数・買付株数は `ApplicationCount` / `PurchaseCount` です。買付株数は、報告書が「全部の買付け等を行います」と書いているときだけ応募株数と同じ値を入れます。按分のときは空欄です。

価格や買付代金が訂正で変わったときだけ `PriceChangeHistory` / `ConsiderationChangeHistory` に日付付きで残します。算定機関が2社以上、名前つきでレンジを書いているときだけ `ValuationAdvisors` に分けます。

`ReferencePricePriorClose` は「公表日の前営業日」の終値、`ReferencePrice1M` はその同じ文の1か月平均です。プレミアムはその書類の買付価格から計算します。事例のプレミアム率や、提出日の前営業日の株価は使いません。候補が複数で食い違うときは空欄です。

**URL 形式:** `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{DocID}.pdf`（API キー不要。提出から約 10 年以内が目安）

既存 CSV のリンクを PDF 形式に揃える場合:

```bash
python -m tob.refresh_edinet_urls
```

---

## 書類 CSV（`tob_list.csv` / `self_tob_list.csv`）の主な列

| 列 | 意味 |
|----|------|
| DocTypeName | 書類種別名 |
| **EdinetDocUrl** | その行の書類への EDINET PDF URL |
| OfferorName / TargetName など | 抽出済みの値 |
| FinalResultNote / ApplicationCount など | その **書類** から取れた値（報告書行のみ数値あり） |
| DocID / CaseID | 書類 ID |

`self_tob_list.csv` にも **EdinetDocUrl** があります。自社株案件 CSV にも **LatestFilingUrl / LatestOutcomeUrl** があります。

---

## ローカル実行（任意）

```bash
export EDINET_API_KEY=あなたのキー
python -m tob.fetch_tob --from-year 2024 --to-year 2026
python -m tob.fetch_tob --from-year 2017 --to-year 2020 --sleep 0.5
python -m tob.enrich_tob --only-pending
python -m tob.enrich_tob --fields valuation,fund
python -m tob.enrich_tob --recompute-only
python -m tob.enrich_self_tob --only-pending
python -m unittest discover -s tests -v

# GPT 抽出実験（要 OPENAI_API_KEY / pip install pypdf）
python experiments/gpt-extract/scripts/run_one_case.py --case-id S100M232
python experiments/gpt-extract/scripts/run_one_case.py --seed-queue 5
python experiments/gpt-extract/scripts/run_one_case.py --from-queue

# SponsorHint LLM（要 GEMINI_API_KEY、CSV テキストから推論）
python experiments/sponsor-hint-llm/scripts/run_sponsor_hint_llm.py --dry-run --limit 5
python experiments/sponsor-hint-llm/scripts/run_sponsor_hint_llm.py --only-blank --apply-cases
```

---

## リポジトリ構成

| パス | 内容 |
|------|------|
| [`tob/`](tob/) | TOB パイプライン（Fetch / Enrich / IDリスト / 案件JSON / タクソノミ） |
| [`edinet/`](edinet/) | EDINET 提出者リスト等の共有ユーティリティ |
| [`stock_swap/`](stock_swap/) | 株式交換パイプライン（将来追加予定） |
| [`experiments/`](experiments/) | **試作・検証用**（本番 `output/` に影響しない） |
| [`experiments/gpt-extract/`](experiments/gpt-extract/) | ChatGPT で TOB PDF → CSV 抽出する実験場 |
| [`experiments/sponsor-hint-llm/`](experiments/sponsor-hint-llm/) | Gemini で CSV テキストから SponsorHint を推論 |
| `output/` | CSV 出力（`current/` と `snapshots/`） |
| `cache/` | 日次 API レスポンス・XBRL ZIP のキャッシュ |

---

## 技術メモ（メンテ向け）

- XBRL 取得: 書類 API `type=5`（ZIP 内 CSV）
- タクソノミ: [`tob/taxonomy/`](tob/taxonomy/)（2013 / 2014 / 2021 / 2026 年版）
- Fetch: DocID upsert。Enrich 列は保持
- `OfferPriceRaw` は先頭 5000 文字のみ CSV 保存（抽出時は全文使用）。古い CSV を `--recompute-only` だけでは再抽出しきれない場合あり

**主なモジュール:** `tob/fetch_tob.py` / `tob/enrich_tob.py` / `tob/enrich_self_tob.py` / `tob/tob_common.py` / `tob/output_store.py`
