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
  els.body.replaceChildren();
  for (const item of rows) {
    const days = periodDays(item.OfferPeriodStart, item.OfferPeriodEnd);
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.dataset.caseId = item.caseId;
    tr.innerHTML = `
      <td>${escapeHtml(item.TargetName || item.caseId)}</td>
      <td>${escapeHtml(offerorLabel(item))}</td>
      <td>${escapeHtml(yenLabel(item.PriorClose))}</td>
      <td>${escapeHtml(premiumLabel(item.PremiumVsPriorClose))}</td>
      <td>${escapeHtml(considerationOku(item.PurchaseConsideration))}</td>
      <td>${escapeHtml(item.TenderOfferAgent || "—")}</td>
      <td>${escapeHtml(yesNo(item.IsMBO))}</td>
      <td>${escapeHtml(yesNo(item.IsHostileInitial))}</td>
      <td>${escapeHtml(resultLabel(item))}</td>
      <td>${days == null ? "—" : `${days}日`}</td>
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
    els.body.innerHTML = `<tr><td colspan="10">${escapeHtml(String(error))}</td></tr>`;
  }
}

boot();
