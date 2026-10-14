"""One HTML file with the search screens and the site CSV inside it.

Opening the file from disk does not use fetch or ES modules, so a local
web server is unnecessary.
"""

from __future__ import annotations

import json
from pathlib import Path

DOCS_DIR = Path("docs")
DEFAULT_CSV = DOCS_DIR / "data" / "all.csv"
DEFAULT_HTML = DOCS_DIR / "tob-archive.html"


def _strip_module(source: str) -> str:
    lines = []
    skipping_import = False
    for line in source.splitlines():
        if skipping_import:
            if "from " in line and line.rstrip().endswith(";"):
                skipping_import = False
            continue
        if line.startswith("import "):
            if not line.rstrip().endswith(";"):
                skipping_import = True
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        lines.append(line)
    return "\n".join(lines)


def _search_script(source: str) -> str:
    body = _strip_module(source)
    body = body.replace("\nboot();\n", "\n")
    body = body.replace(
        "function bind() {",
        "let searchBound = false;\nfunction bind() {\n  if (searchBound) return;\n  searchBound = true;",
        1,
    )
    opener = """
window.openCase = function (id) {
  selectedId = id;
  const url = new URL(window.location.href);
  url.searchParams.set("case", id);
  history.replaceState(null, "", url);
  if (window.showView) window.showView("search");
  renderList();
};
"""
    return f"window.bootSearch = (function () {{\n{body}\n{opener}\nreturn boot;\n}})();\n"


def _years_script(source: str) -> str:
    body = _strip_module(source)
    body = body.replace(
        'const selfOnly = document.body.dataset.scope === "self";',
        "let selfOnly = false;",
        1,
    )
    body = body.replace(
        """    const open = () => {
      window.location.href = `./index.html?case=${encodeURIComponent(item.caseId)}`;
    };""",
        """    const open = () => {
      if (window.openCase) window.openCase(item.caseId);
    };""",
        1,
    )
    start = body.find("async function boot()")
    if start < 0:
        raise ValueError("years.js: boot() が見つかりません")
    body = body[:start] + """async function boot() {
  window.__allCases = await loadCases();
}
"""
    extra = """
window.setYearScope = function (flag) {
  selfOnly = flag;
  const root = document.getElementById(flag ? "view-self" : "view-years");
  els.tabs = root.querySelector("[data-role=tabs]");
  els.meta = root.querySelector("[data-role=meta]");
  els.summary = root.querySelector("[data-role=summary]");
  els.body = root.querySelector("[data-role=body]");
  selectedYear = "";
  cases = (window.__allCases || []).filter(inScope);
  renderTabs();
  renderTable();
};
"""
    return f"window.bootYears = (function () {{\n{body}\n{extra}\nreturn boot;\n}})();\n"


def build_offline_html(csv_text: str, docs_dir: Path | None = None) -> str:
    docs = Path(docs_dir) if docs_dir is not None else DOCS_DIR
    css = (docs / "styles.css").read_text(encoding="utf-8")
    csv_js = _strip_module((docs / "csv.js").read_text(encoding="utf-8"))
    csv_js = csv_js.replace(
        """export async function loadCases() {
  const response = await fetch(DATA_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseCsv(await response.text());
}""",
        """async function loadCases() {
  if (window.TOB_CSV == null) throw new Error("CSVがありません");
  return parseCsv(window.TOB_CSV);
}""",
    )
    # _strip_module already removed export, so the replacement above may miss.
    if "fetch(DATA_URL)" in csv_js:
        csv_js = csv_js.replace(
            """async function loadCases() {
  const response = await fetch(DATA_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseCsv(await response.text());
}""",
            """async function loadCases() {
  if (window.TOB_CSV == null) throw new Error("CSVがありません");
  return parseCsv(window.TOB_CSV);
}""",
        )
    search_js = _search_script((docs / "app.js").read_text(encoding="utf-8"))
    years_js = _years_script((docs / "years.js").read_text(encoding="utf-8"))
    payload = json.dumps(csv_text, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TOB Archive</title>
  <style>
/*CSS*/
[hidden] { display: none !important; }
  </style>
</head>
<body>
  <div class="atmosphere" aria-hidden="true"></div>
  <header class="masthead">
    <p class="brand">TOB Archive</p>
    <nav class="site-nav" aria-label="サイト内">
      <a href="#search" data-nav="search" aria-current="page">案件検索</a>
      <a href="#years" data-nav="years">暦年一覧</a>
      <a href="#self" data-nav="self">自社株TOB</a>
    </nav>
    <h1 id="page-title">公開買付の案件を、名前と時期で探す</h1>
    <p class="lead" id="page-lead">このファイルだけで検索できます。サーバは不要です。</p>
  </header>
  <main data-view="search" id="view-search">
    <section class="search" aria-label="検索条件">
      <label class="field grow"><span>名称</span>
        <input id="query" type="search" placeholder="対象会社・買付者・スポンサー・代理人" autocomplete="off" />
      </label>
      <label class="field"><span>開始月</span><input id="from-month" type="month" /></label>
      <label class="field"><span>終了月</span><input id="to-month" type="month" /></label>
      <label class="field"><span>結果</span>
        <select id="status"><option value="">すべて</option></select>
      </label>
    </section>
    <p id="meta" class="meta" aria-live="polite"></p>
    <div class="workspace">
      <section class="results" aria-label="検索結果"><ul id="result-list"></ul></section>
      <section class="detail" aria-label="案件サマリ" id="detail">
        <p class="empty">左の一覧から案件を選ぶと、ここにサマリが出ます。</p>
      </section>
    </div>
  </main>
  <main class="wide" data-view="years" id="view-years" hidden>
    <div class="year-bar" data-role="tabs" aria-label="暦年"></div>
    <p class="meta" data-role="meta" aria-live="polite"></p>
    <div class="year-summary" data-role="summary"></div>
    <div class="table-wrap">
      <table class="year-table">
        <thead>
          <tr>
            <th>上場区分</th><th>対象会社</th><th>買収者</th><th>直前株価</th><th>プレミアム</th>
            <th>買付総額</th><th>MBO</th><th>敵対的</th><th>結果</th><th>期間日数</th><th>幹事証券</th>
          </tr>
        </thead>
        <tbody data-role="body"></tbody>
      </table>
    </div>
  </main>
  <main class="wide" data-view="self" id="view-self" hidden>
    <div class="year-bar" data-role="tabs" aria-label="暦年"></div>
    <p class="meta" data-role="meta" aria-live="polite"></p>
    <div class="table-wrap">
      <table class="year-table">
        <thead>
          <tr>
            <th>対象会社</th><th>買付予定株数</th><th>発行済株式数</th><th>予定比率</th>
            <th>買付総額</th><th>結果</th><th>期間日数</th><th>幹事証券</th>
          </tr>
        </thead>
        <tbody data-role="body"></tbody>
      </table>
    </div>
  </main>
  <script>
window.TOB_CSV = /*PAYLOAD*/;
/*CSVJS*/
/*SEARCHJS*/
/*YEARSJS*/
const titles = {
  search: ["公開買付の案件を、名前と時期で探す", "このファイルだけで検索できます。サーバは不要です。"],
  years: ["暦年ごとの案件一覧", "他社株の公開買付です。行を選ぶと案件検索に移ります。"],
  self: ["自社株TOBの暦年一覧", "買収者と対象会社が同じ案件です。"],
};
window.showView = function (view) {
  if (!titles[view]) view = "search";
  document.querySelectorAll("[data-view]").forEach((el) => {
    el.hidden = el.dataset.view !== view;
  });
  document.querySelectorAll("[data-nav]").forEach((el) => {
    if (el.dataset.nav === view) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  document.getElementById("page-title").textContent = titles[view][0];
  document.getElementById("page-lead").textContent = titles[view][1];
  if (view === "years" || view === "self") window.setYearScope(view === "self");
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
};
document.querySelectorAll("[data-nav]").forEach((el) => {
  el.addEventListener("click", (event) => {
    event.preventDefault();
    window.showView(el.dataset.nav);
  });
});
window.bootSearch().then(() => window.bootYears()).then(() => {
  const hash = (location.hash || "#search").slice(1);
  window.showView(hash === "years" || hash === "self" ? hash : "search");
}).catch((error) => {
  document.getElementById("meta").textContent = String(error);
});
  </script>
</body>
</html>
"""
    return (
        page.replace("/*CSS*/", css)
        .replace("/*PAYLOAD*/", payload)
        .replace("/*CSVJS*/", csv_js)
        .replace("/*SEARCHJS*/", search_js)
        .replace("/*YEARSJS*/", years_js)
    )


def write_offline_archive(
    csv_path: Path | None = None,
    dest: Path | None = None,
    docs_dir: Path | None = None,
) -> Path:
    source = Path(csv_path) if csv_path is not None else DEFAULT_CSV
    target = Path(dest) if dest is not None else DEFAULT_HTML
    html = build_offline_html(source.read_text(encoding="utf-8-sig"), docs_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target
