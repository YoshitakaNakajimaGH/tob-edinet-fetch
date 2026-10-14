# EDINET TOB アーカイブ

金融庁 EDINET の公開買付書類（docTypeCode 240〜320）から、案件ごとの数値と静的サイトを作るリポジトリです。

サイトが読むのは `docs/data/all.csv` です。機械が書いた修正前の表は `output/case_summaries/all.csv` です。

会社のネットワークで GitHub Pages が開けないときは、`docs/tob-archive.html` を1ファイルだけダウンロードしてダブルクリックします。CSVと検索画面が入っていて、Pythonもローカルサーバも要りません。案件JSON作成フローが CSV を更新するときに、このHTMLも作り直します。

## 毎月の更新

いまは手動です。Actions タブで `master` を選び、次の順に **Run workflow** します。

1. **IDリスト作成フロー** … 届出月ごとの書類 ID。XBRL 本文は取りません。
2. **案件JSON作成フロー** … ID リストにある書類の XBRL を読み、案件 JSON とサマリ CSV、サイト用 CSV を更新して commit します。

開始月を空欄にすると、届出日から 183 日の窓が閉じた直近の月だけを処理します。2026年10月5日なら 2026年3月です。終了月を空欄にすると、その1ヶ月だけです。対象月の `output/id_lists/YYYY-MM.json` が無いと、案件 JSON は止まります。

結果をリポジトリに保存する、を OFF にすると artifact だけで、`output/` は更新しません。

ローカルで同じことをするとき:

```bash
export EDINET_API_KEY=あなたのキー
python -m tob.id_list --from-month 2026-03
python -m tob.case_json --from-month 2026-03
python -m unittest discover -s tests -v
```

サイトの確認:

```bash
python -m http.server 8765 --directory docs
```

`http://localhost:8765` が案件検索、`years.html` が暦年一覧、`self.html` が自社株です。`file://` では CSV を読めないことがあります。

## 初回セットアップ

1. **Settings → Secrets and variables → Actions**
2. **New repository secret** → Name: `EDINET_API_KEY`
3. [EDINET API キー](https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1) を登録する

公開サイトは GitHub Pages の **Deploy from a branch**、Branch `master`、Folder **`/docs`** です。Private のままだと Free では Pages を使えません。Actions での Pages デプロイは使いません。

## 別の GitHub アカウントへ移す

コードと保存済みの `output/`、`docs/` はリポジトリごと移せます。サイトの HTML にアカウント名は入っていません。

移しただけでは動き続けないものは次です。

- **Actions の secret** は移りません。新しいリポジトリに `EDINET_API_KEY` を入れ直します。キーの値そのものは、同じ契約なら再利用できます。
- **GitHub Pages** は移先で再度有効にします。URL は `https://<新しいユーザー>.github.io/<リポジトリ名>/` になります。
- 移先も public にするか、有料プランでないと Free の Pages は出ません。

ID リストと案件 JSON のワークフローは、secret を入れれば移先の `master` でも同じように commit します。

## サイト

| ページ | 内容 |
|--------|------|
| `docs/index.html` | 案件検索。名称・届出月・結果で絞る |
| `docs/years.html` | 他社株の暦年一覧。自社株は除く |
| `docs/self.html` | 自社株 TOB。`issuerTender` が true の行 |

案件検索の詳細は、上から次の順です。

- 対象会社の上に、MBO は青、敵対的は赤。どちらでもなければ箱は出ません。
- 左が対象会社、矢印、右が買付者。スポンサーが買付者と同じ、または空なら「（同上）」。
- 買付総額と結果。成立は緑、不成立と撤回は赤。
- 資本関係者候補。文字は黒。
- 円/株の軸。直前株価、公開買付価格、市場株価法・類似会社・DCF。レンジは緑の実線。
- 買付前の円は左、買付後の円は右。無い側は「記載なし」。
- 買付株数。右端が 0 株。下限・上限・予定は縦線。実際の買付数は右からの棒。
- 下の表。買付期間は `60日　（2021/1/1~2021/2/29）` のように1行。日数は開始日と終了日を両方数えます。プレミアムはプラスが緑、マイナスが赤。括弧付きは、終値が定番の文言で取れず、届出書のプレミアム文から補った値です。
- 一番下の右は借入と出資。書いていない案件も「—」です。金額は届出書の上限で、実行額ではありません。

書類リンクは、届出書・意見表明書・撤回届出書・対質問回答・報告書のうち、あるものだけの最初の PDF と、書類総数です。

暦年一覧の左端は上場区分です。表の上に、その年のプレミアム平均（括弧付きは平均に入れない）、MBO 件数、敵対的件数、期間日数の平均、最多の幹事証券、買収額最大の対象会社を出します。買収者の括弧はスポンサー候補だけです。不成立と撤回は赤字です。幹事証券は右端です。

自社株のページは対象会社だけです。MBO、敵対的、直前株価、プレミアムは出しません。発行済株式数は本文の「発行済株式総数」からです。自社株の保存テキストにはその文がほとんど無く、空欄が多いです。

## 手修正

`corrections/overrides.csv` に、直したい案件の行だけを書きます。`caseId` は必須です。空欄のセルは変えません。同じ `caseId` を二行、または知らない列名があると、その実行は止まります。

案件 JSON 作成フローは、機械の `output/case_summaries/all.csv` を残し、修正を重ねた結果だけを `docs/data/all.csv` と `docs/data/self_tob.csv` に書きます。説明は `corrections/README.md` です。

## 直前株価とプレミアム

1. 「公表日の前営業日」の終値が文書内で一つなら、それを使う。
2. 訂正で終値が複数なら、最初の届出書で最も早い終値を使い、プレミアムは括弧付き。
3. その文言が無いときは、プレミアムまたはディスカウントの％の隣に書かれた終値を使う。類似案件の中央値や、以前の提案価格は使わない。
4. それでも無い案件は空欄のまま。自社株や、終値も％も書いていない届出書がこれにあたります。

プレミアムは `(買付価格 - 直前株価) / 直前株価` です。

## スポンサーと資本関係者

スポンサー候補は、届出書「（１）本公開買付の概要」の冒頭だけを見ます。資本関係者候補は、その同じ冒頭にある会社名とファンド名です。案件検索は資本関係者を全部出し、暦年一覧の括弧はスポンサー候補だけです。

## データの置き場所

```
output/id_lists/YYYY-MM.json     書類 ID
output/cases/YYYY/MM/{DocID}.json  案件 JSON
output/case_summaries/             機械が書いた CSV
docs/data/                         サイトが読む CSV（手修正を重ねたもの）
corrections/overrides.csv          手修正
tob/taxonomy/                      タクソノミ対応表
old/                               休止した Actions と、以前の CSV。2027-10 以降に削除できる
```

案件 JSON の主な中身は次です。

| 場所 | 内容 |
|------|------|
| `core` | 価格、期間、保有比率、意見、結果、MBO、上場区分。不明は `null`、本当の 0 は `0` |
| `referencePrices` / `premiums` | 直前株価とプレミアム。`vsPriorCloseDerived` が true のときサイトは括弧付き |
| `financing` | 出資枠、借入枠、貸付人。金額は上限 |
| `valuations` | 買付者側と対象会社側の市場株価法、類似会社、DCF |
| `pdfLinks` | 書類ごとの PDF。`https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{DocID}.pdf` |
| `documents` | タクソノミ本文。XBRL インスタンスの全文を使い、CSV の約 3 万字で切らない |

`IsHostileInitial` は最初の意見表明だけです。`ExistingHoldingRatio` は買付者自身で、特別関係者は足しません。

## タクソノミの保守

対応表は `tob/taxonomy/manifest.json` と `tob/taxonomy/mappings/` です。2013、2014、2021〜2026 を年で分けています。提出日に合う年の要素名で本文を取ります。

金融庁が新しい年版を出したときは、その年の mapping を足し、古い年のファイルは残します。要素名が変わると、価格や本文が空になります。年に一度、新しい届出書で価格・期間・保有比率が埋まっているかを見る、が今の確認点です。自社株は `issuer_*.json` で、発行済株式総数の要素はありません。

## 休止したもの

Fetch TOB、Enrich、Sponsor Hint LLM、GPT 抽出、書類子孫の試行、Pages の Actions デプロイは `old/workflows/` にあります。GitHub は `.github/workflows/` しか実行しないので、これらは動きません。中身の説明は `old/README.md` です。

いま動く Actions は、IDリスト作成フロー、案件JSON作成フロー、CI です。
