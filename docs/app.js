import { considerationOku, escapeHtml, isSelfTender, loadCases, premiumLabel } from "./csv.js";

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

function range(min, max) {
  if (!min && !max) return "—";
  if (min && max) {
    return `${Number(min).toLocaleString("ja-JP")}〜${Number(max).toLocaleString("ja-JP")}円`;
  }
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
      const url = new URL(window.location.href);
      url.searchParams.set("case", item.caseId);
      history.replaceState(null, "", url);
      renderList();
    });
    li.append(button);
    els.list.append(li);
  }
  renderDetail(rows.find((item) => item.caseId === selectedId) || null);
}

function field(label, value, wide = false) {
  return `
    <div class="item${wide ? " wide" : ""}">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value">${escapeHtml(value)}</span>
    </div>
  `;
}

function asNumber(value) {
  if (value === "" || value == null) return null;
  const number = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(number) && number > 0 ? number : null;
}

function priceChart(item) {
  const bands = [
    ["買付者・市場株価法", item.OfferorMarketMin, item.OfferorMarketMax],
    ["買付者・類似会社", item.OfferorComparableMin, item.OfferorComparableMax],
    ["買付者・DCF", item.OfferorDcfMin, item.OfferorDcfMax],
    ["対象会社・市場株価法", item.TargetMarketMin, item.TargetMarketMax],
    ["対象会社・類似会社", item.TargetComparableMin, item.TargetComparableMax],
    ["対象会社・DCF", item.TargetDcfMin, item.TargetDcfMax],
  ]
    .map(([label, min, max]) => ({ label, min: asNumber(min), max: asNumber(max) }))
    .filter((band) => band.min != null && band.max != null);
  const prior = asNumber(item.PriorClose);
  const offer = asNumber(item.OfferPrice);
  const values = [prior, offer, ...bands.flatMap((band) => [band.min, band.max])].filter((value) => value != null);
  if (!values.length) return "";
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * 0.08 || high * 0.05 || 1;
  const start = Math.max(0, low - pad);
  const end = high + pad;
  const at = (value) => ((value - start) / (end - start)) * 100;
  const line = (value, kind, label) => value == null
    ? ""
    : `<span class="price-line ${kind}" style="left:${at(value)}%">${label ? `<b>${escapeHtml(yen(value))}</b>` : ""}</span>`;
  const labeled = `${line(prior, "prior", true)}${line(offer, "offer", true)}`;
  const plain = `${line(prior, "prior", false)}${line(offer, "offer", false)}`;
  const rows = bands.map((band) => {
    const left = at(Math.min(band.min, band.max));
    const width = Math.max(at(Math.max(band.min, band.max)) - left, 1.2);
    return `
      <div class="band-row">
        <span class="band-label">${escapeHtml(band.label)}</span>
        <span class="band-track">
          ${plain}
          <i style="left:${left}%;width:${width}%"></i>
        </span>
      </div>`;
  }).join("");
  const axis = `<div class="band-row"><span class="band-label">円/株</span><span class="band-track axis">${labeled}</span></div>`;
  return `<div class="price-chart" aria-label="株価と算定レンジ">${axis}${rows}</div>`;
}

function dealStory(item) {
  const self = isSelfTender(item);
  const sponsor = (item.SponsorHint || "").trim();
  const buyer = item.OfferorName || "—";
  const sponsorSlot = sponsor && sponsor !== buyer ? sponsor : sponsor ? "" : buyer;
  const result = item.FinalResultNote || item.Status || "—";
  const resultClass = /不成立|撤回/.test(result) ? "result-bad" : /成立/.test(result) ? "result-good" : "";
  if (self) {
    return `
      <div class="deal">
        <div class="party">
          <span>対象会社</span>
          <strong>${escapeHtml(item.TargetName || item.caseId)}</strong>
          <em>自社株TOB</em>
        </div>
      </div>
      <p class="deal-line"><b>${escapeHtml(considerationOku(item.PurchaseConsideration))}</b><span class="${resultClass}">${escapeHtml(result)}</span></p>
    `;
  }
  return `
    <div class="deal">
      <div class="party">
        <span>対象会社</span>
        <strong>${escapeHtml(item.TargetName || item.caseId)}</strong>
      </div>
      <div class="deal-arrow" aria-hidden="true">→</div>
      <div class="party party-right">
        <span>買付者</span>
        <strong>${escapeHtml(buyer)}</strong>
        ${sponsorSlot ? `<span>スポンサー</span><strong>${escapeHtml(sponsorSlot)}</strong>` : ""}
      </div>
    </div>
    <p class="deal-line"><b>${escapeHtml(considerationOku(item.PurchaseConsideration))}</b><span class="${resultClass}">${escapeHtml(result)}</span></p>
  `;
}

function renderDetail(item) {
  if (!item) {
    els.detail.innerHTML = `<p class="empty">左の一覧から案件を選ぶと、ここにサマリが出ます。</p>`;
    return;
  }
  const links = [];
  const pdfs = [
    ["届出書", item.FirstFilingPdf],
    ["意見表明書", item.FirstOpinionPdf],
    ["撤回届出書", item.FirstWithdrawalPdf],
    ["対質問回答", item.FirstAnswerPdf],
    ["報告書", item.LatestReportPdf],
  ];
  for (const [label, href] of pdfs) {
    if (href) links.push(`<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${label}</a>`);
  }
  els.detail.innerHTML = `
    ${dealStory(item)}
    ${priceChart(item)}
    <p class="capital-line">資本関係者候補 ${escapeHtml(text(item.CapitalParties))}</p>
    <div class="grid">
      ${field("届出月", text(item.filingMonth))}
      ${field("上場区分", text(item.TargetListingStatus))}
      ${field("公開買付代理人", text(item.TenderOfferAgent))}
      ${field("プレミアム", premiumLabel(item.PremiumVsPriorClose))}
      ${field("買付期間", `${text(item.OfferPeriodStart)} 〜 ${text(item.OfferPeriodEnd)}`, true)}
      ${field("発行済株式数", shares(item.IssuedShares))}
      ${field("買付予定株数", shares(item.PlannedSharesPlanned))}
      ${field("買付前保有（買付者）", ratio(item.ExistingHoldingRatio))}
      ${field("買付後保有", ratio(item.AfterPurchaseRatio))}
      ${field("意見", text(item.OpinionStance))}
      ${field("応募 / 買付", `${shares(item.ApplicationCount)} / ${shares(item.PurchaseCount)}`)}
      ${field("書類総数", text(item.DocCount))}
      ${field("廃止注記", text(item.TargetDelistingNote), true)}
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
    cases = await loadCases();
    const wanted = new URL(window.location.href).searchParams.get("case");
    if (wanted && cases.some((item) => item.caseId === wanted)) {
      selectedId = wanted;
    }
    fillStatusOptions();
    renderList();
  } catch (error) {
    els.meta.textContent = "データを読めませんでした。ローカルサーバ経由で開いてください。";
    els.detail.innerHTML = `<p class="empty">${escapeHtml(String(error))}</p>`;
  }
}

boot();
