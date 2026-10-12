const DATA_URL = "./data/all.csv";

const els = {
  query: document.getElementById("query"),
  fromMonth: document.getElementById("from-month"),
  toMonth: document.getElementById("to-month"),
  status: document.getElementById("status"),
  meta: document.getElementById("meta"),
  list: document.getElementById("result-list"),
  detail: document.getElementById("detail"),
};

let cases = [];
let selectedId = "";

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];
    if (inQuotes) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  if (!rows.length) return [];
  const headers = rows[0];
  return rows.slice(1).filter((values) => values.some(Boolean)).map((values) => {
    const item = {};
    headers.forEach((header, index) => {
      item[header] = values[index] ?? "";
    });
    return item;
  });
}

function yen(value) {
  if (!value) return "—";
  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number)) return value;
  return `${number.toLocaleString("ja-JP")}円`;
}

function shares(value) {
  if (!value) return "—";
  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number)) return value;
  return `${number.toLocaleString("ja-JP")}株`;
}

function ratio(value) {
  if (value === "" || value == null) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${(number * 100).toFixed(2)}%`;
}

function premium(value) {
  if (value === "" || value == null) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const signed = number >= 0 ? "+" : "";
  return `${signed}${(number * 100).toFixed(1)}%`;
}

function range(min, max) {
  if (!min && !max) return "—";
  if (min && max) return `${Number(min).toLocaleString("ja-JP")}〜${Number(max).toLocaleString("ja-JP")}円`;
  return yen(min || max);
}

function text(value) {
  return value ? String(value) : "—";
}

function matches(item) {
  const query = els.query.value.trim().toLowerCase();
  if (query) {
    const haystack = [
      item.TargetName,
      item.OfferorName,
      item.SponsorHint,
      item.TenderOfferAgent,
      item.caseId,
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(query)) return false;
  }
  if (els.fromMonth.value && item.filingMonth < els.fromMonth.value) return false;
  if (els.toMonth.value && item.filingMonth > els.toMonth.value) return false;
  if (els.status.value && item.Status !== els.status.value) return false;
  return true;
}

function filtered() {
  return cases.filter(matches);
}

function renderList() {
  const rows = filtered();
  els.meta.textContent = `${rows.length}件 / 全${cases.length}件`;
  els.list.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.style.cssText = "padding:1.5rem;color:var(--muted);";
    empty.textContent = "条件に合う案件がありません。";
    els.list.append(empty);
    if (!rows.some((item) => item.caseId === selectedId)) {
      selectedId = "";
      renderDetail(null);
    }
    return;
  }
  if (!rows.some((item) => item.caseId === selectedId)) {
    selectedId = rows[0].caseId;
  }
  for (const item of rows) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "result-item";
    button.setAttribute("aria-selected", item.caseId === selectedId ? "true" : "false");
    button.innerHTML = `
      <span class="name">${escapeHtml(item.TargetName || item.caseId)}</span>
      <span class="sub">${escapeHtml(item.filingMonth)} · ${escapeHtml(item.OfferorName || "買付者不明")} · ${escapeHtml(item.Status || "—")}</span>
    `;
    button.addEventListener("click", () => {
      selectedId = item.caseId;
      renderList();
      renderDetail(item);
    });
    li.append(button);
    els.list.append(li);
  }
  renderDetail(rows.find((item) => item.caseId === selectedId) || null);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function field(label, value, wide = false) {
  return `
    <div class="item${wide ? " wide" : ""}">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value">${escapeHtml(value)}</span>
    </div>
  `;
}

function renderDetail(item) {
  if (!item) {
    els.detail.innerHTML = `<p class="empty">左の一覧から案件を選ぶと、ここにサマリが出ます。</p>`;
    return;
  }
  const links = [];
  if (item.FirstFilingPdf) {
    links.push(`<a href="${escapeHtml(item.FirstFilingPdf)}" target="_blank" rel="noreferrer">届出書PDF</a>`);
  }
  if (item.LatestReportPdf) {
    links.push(`<a href="${escapeHtml(item.LatestReportPdf)}" target="_blank" rel="noreferrer">報告書PDF</a>`);
  }
  els.detail.innerHTML = `
    <div class="detail-head">
      <h2>${escapeHtml(item.TargetName || item.caseId)}</h2>
      <span class="badge">${escapeHtml(item.Status || "—")}</span>
    </div>
    <div class="grid">
      ${field("届出月", text(item.filingMonth))}
      ${field("案件ID", text(item.caseId))}
      ${field("買付者", text(item.OfferorName))}
      ${field("スポンサー候補", text(item.SponsorHint))}
      ${field("買付価格", yen(item.OfferPrice))}
      ${field("公開買付代理人", text(item.TenderOfferAgent))}
      ${field("買付期間", `${text(item.OfferPeriodStart)} 〜 ${text(item.OfferPeriodEnd)}`, true)}
      ${field("買付予定株数", shares(item.PlannedSharesPlanned))}
      ${field("下限 / 上限", `${shares(item.PlannedSharesMin)} / ${shares(item.PlannedSharesMax)}`)}
      ${field("買付代金", yen(item.PurchaseConsideration))}
      ${field("意見", text(item.OpinionStance))}
      ${field("買付前保有（買付者）", ratio(item.ExistingHoldingRatio))}
      ${field("特別関係者", ratio(item.SpecialRelatedHoldingRatio))}
      ${field("買付後保有", ratio(item.AfterPurchaseRatio))}
      ${field("応募 / 買付", `${shares(item.ApplicationCount)} / ${shares(item.PurchaseCount)}`)}
      ${field("前営業日終値", yen(item.PriorClose))}
      ${field("プレミアム（終値）", premium(item.PremiumVsPriorClose))}
      ${field("買付者側 DCF", range(item.OfferorDcfMin, item.OfferorDcfMax))}
      ${field("対象会社側 DCF", range(item.TargetDcfMin, item.TargetDcfMax))}
      ${field("買付者側 市場株価法", range(item.OfferorMarketMin, item.OfferorMarketMax))}
      ${field("対象会社側 市場株価法", range(item.TargetMarketMin, item.TargetMarketMax))}
      ${field("上場区分 / 廃止注記", `${text(item.TargetListingStatus)} / ${text(item.TargetDelistingNote)}`, true)}
    </div>
    <div class="links">${links.join("") || "<span class='value'>—</span>"}</div>
  `;
}

function fillStatusOptions() {
  const values = [...new Set(cases.map((item) => item.Status).filter(Boolean))].sort();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    els.status.append(option);
  }
}

function bind() {
  for (const el of [els.query, els.fromMonth, els.toMonth, els.status]) {
    el.addEventListener("input", renderList);
    el.addEventListener("change", renderList);
  }
}

async function boot() {
  bind();
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    cases = parseCsv(await response.text());
    fillStatusOptions();
    renderList();
  } catch (error) {
    els.meta.textContent = "データを読めませんでした。ローカルサーバ経由で開いてください。";
    els.detail.innerHTML = `<p class="empty">${escapeHtml(String(error))}</p>`;
  }
}

boot();
