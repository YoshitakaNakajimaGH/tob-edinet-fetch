import {
  considerationOku,
  escapeHtml,
  isSelfTender,
  loadCases,
  offerorLabel,
  periodDays,
  premiumLabel,
  resultLabel,
  yenLabel,
} from "./csv.js";

const els = {
  tabs: document.getElementById("year-tabs"),
  meta: document.getElementById("meta"),
  summary: document.getElementById("year-summary"),
  body: document.getElementById("year-body"),
};

const selfOnly = document.body.dataset.scope === "self";
let cases = [];
let selectedYear = "";

function filingYear(item) {
  return (item.filingMonth || "").slice(0, 4);
}

function inScope(item) {
  return selfOnly ? isSelfTender(item) : !isSelfTender(item);
}

function years() {
  return [...new Set(cases.map(filingYear).filter((year) => /^\d{4}$/.test(year)))].sort(
    (a, b) => Number(b) - Number(a),
  );
}

function yesNo(value) {
  if (value === "Yes" || value === "true") return "Yes";
  if (value === "No" || value === "false") return "No";
  return "—";
}

function renderTabs() {
  const list = years();
  if (!list.length) {
    els.tabs.replaceChildren();
    return;
  }
  if (!list.includes(selectedYear)) {
    selectedYear = list[0];
  }
  els.tabs.replaceChildren();
  for (const year of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "year-tab";
    button.textContent = year;
    button.setAttribute("aria-pressed", year === selectedYear ? "true" : "false");
    button.addEventListener("click", () => {
      selectedYear = year;
      const url = new URL(window.location.href);
      url.searchParams.set("year", year);
      history.replaceState(null, "", url);
      renderTabs();
      renderTable();
    });
    els.tabs.append(button);
  }
}

function sharesLabel(value) {
  if (value === "" || value == null) return "—";
  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number)) return String(value);
  return `${number.toLocaleString("ja-JP")}株`;
}

function resultCell(item) {
  const label = resultLabel(item);
  const bad = /不成立|撤回/.test(label);
  return `<td class="${bad ? "result-bad" : ""}">${escapeHtml(label)}</td>`;
}

function premiumCell(value) {
  const label = premiumLabel(value);
  const number = Number(value);
  const tone = value === "" || value == null || !Number.isFinite(number)
    ? ""
    : number > 0
      ? "premium-up"
      : number < 0
        ? "premium-down"
        : "";
  return `<td class="${tone}">${escapeHtml(label)}</td>`;
}

function average(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function renderSummary(rows) {
  if (!els.summary || selfOnly) return;
  const premiums = rows
    .map((item) => Number(item.PremiumVsPriorClose))
    .filter((value) => Number.isFinite(value));
  const days = rows
    .map((item) => periodDays(item.OfferPeriodStart, item.OfferPeriodEnd))
    .filter((value) => value != null);
  const mbo = rows.filter((item) => item.IsMBO === "Yes").length;
  const hostile = rows.filter((item) => item.IsHostileInitial === "Yes").length;
  const agents = new Map();
  for (const item of rows) {
    const agent = (item.TenderOfferAgent || "").trim();
    if (!agent) continue;
    agents.set(agent, (agents.get(agent) || 0) + 1);
  }
  const topAgent = [...agents.entries()].sort((a, b) => b[1] - a[1])[0];
  const largest = rows.reduce((best, item) => {
    const amount = Number(String(item.PurchaseConsideration || "").replace(/,/g, ""));
    if (!Number.isFinite(amount)) return best;
    if (!best || amount > best.amount) {
      return { amount, name: item.TargetName || item.caseId };
    }
    return best;
  }, null);
  const premiumAvg = average(premiums);
  const dayAvg = average(days);
  const cards = [
    ["プレミアム平均", premiumAvg == null ? "—" : premiumLabel(premiumAvg)],
    ["MBO", `${mbo}件`],
    ["敵対的", `${hostile}件`],
    ["期間日数平均", dayAvg == null ? "—" : `${dayAvg.toFixed(1)}日`],
    ["最多の幹事", topAgent ? `${topAgent[0]}（${topAgent[1]}件）` : "—"],
    ["買収額最大", largest ? `${largest.name}（${considerationOku(largest.amount)}）` : "—"],
  ];
  els.summary.replaceChildren();
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "summary-card";
    card.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    els.summary.append(card);
  }
}

function renderTable() {
  const rows = cases
    .filter((item) => filingYear(item) === selectedYear)
    .sort((a, b) => {
      const left = `${a.OfferPeriodStart || ""}${a.caseId}`;
      const right = `${b.OfferPeriodStart || ""}${b.caseId}`;
      return left < right ? -1 : left > right ? 1 : 0;
    });
  els.meta.textContent = selectedYear
    ? `${selectedYear}年 ${rows.length}件 / 全${cases.length}件`
    : "データがありません";
  renderSummary(rows);
  els.body.replaceChildren();
  for (const item of rows) {
    const days = periodDays(item.OfferPeriodStart, item.OfferPeriodEnd);
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.dataset.caseId = item.caseId;
    const period = days == null ? "—" : `${days}日`;
    const planned = Number(String(item.PlannedSharesPlanned || "").replace(/,/g, ""));
    const issued = Number(String(item.IssuedShares || "").replace(/,/g, ""));
    const issuedRatio = Number.isFinite(planned) && Number.isFinite(issued) && issued > 0
      ? `${((planned / issued) * 100).toFixed(1)}%`
      : "—";
    tr.innerHTML = selfOnly
      ? `
      <td>${escapeHtml(item.TargetName || item.caseId)}</td>
      <td>${escapeHtml(sharesLabel(item.PlannedSharesPlanned))}</td>
      <td>${escapeHtml(sharesLabel(item.IssuedShares))}</td>
      <td>${escapeHtml(issuedRatio)}</td>
      <td>${escapeHtml(considerationOku(item.PurchaseConsideration))}</td>
      ${resultCell(item)}
      <td>${escapeHtml(period)}</td>
      <td>${escapeHtml(item.TenderOfferAgent || "—")}</td>
    `
      : `
      <td>${escapeHtml(item.TargetListingStatus || "—")}</td>
      <td>${escapeHtml(item.TargetName || item.caseId)}</td>
      <td>${escapeHtml(offerorLabel(item))}</td>
      <td>${escapeHtml(yenLabel(item.PriorClose))}</td>
      ${premiumCell(item.PremiumVsPriorClose)}
      <td>${escapeHtml(considerationOku(item.PurchaseConsideration))}</td>
      <td>${escapeHtml(yesNo(item.IsMBO))}</td>
      <td>${escapeHtml(yesNo(item.IsHostileInitial))}</td>
      ${resultCell(item)}
      <td>${escapeHtml(period)}</td>
      <td>${escapeHtml(item.TenderOfferAgent || "—")}</td>
    `;
    const open = () => {
      window.location.href = `./index.html?case=${encodeURIComponent(item.caseId)}`;
    };
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    els.body.append(tr);
  }
}

async function boot() {
  try {
    cases = (await loadCases()).filter(inScope);
    const wanted = new URL(window.location.href).searchParams.get("year");
    if (wanted && years().includes(wanted)) {
      selectedYear = wanted;
    }
    renderTabs();
    renderTable();
  } catch (error) {
    els.meta.textContent = "データを読めませんでした。ローカルサーバ経由で開いてください。";
    const span = selfOnly ? 8 : 11;
    els.body.innerHTML = `<tr><td colspan="${span}">${escapeHtml(String(error))}</td></tr>`;
  }
}

boot();
