export const DATA_URL = "./data/all.csv";

export function parseCsv(text) {
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
  return rows
    .slice(1)
    .filter((values) => values.some(Boolean))
    .map((values) => {
      const item = {};
      headers.forEach((header, index) => {
        item[header] = values[index] ?? "";
      });
      return item;
    });
}

export async function loadCases() {
  const response = await fetch(DATA_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseCsv(await response.text());
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function premiumLabel(value, derived = "") {
  if (value === "" || value == null) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  const signed = number >= 0 ? "+" : "";
  const label = `${signed}${(number * 100).toFixed(1)}%`;
  return derived === "Yes" ? `（${label}）` : label;
}

export function isSelfTender(item) {
  return String(item.issuerTender).toLowerCase() === "true";
}

export function yenLabel(value) {
  if (value === "" || value == null) return "—";
  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number)) return String(value);
  return `${number.toLocaleString("ja-JP")}円`;
}

export function considerationOku(value) {
  if (value === "" || value == null) return "—";
  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number) || number <= 0) return "—";
  const oku = number / 100_000_000;
  const digits = oku >= 100 ? 0 : 1;
  return `${oku.toLocaleString("ja-JP", { maximumFractionDigits: digits, minimumFractionDigits: digits })}億円`;
}

export function resultLabel(item) {
  return item.FinalResultNote || item.Status || "—";
}

export function offerorLabel(item) {
  const name = item.OfferorName || "—";
  const sponsor = (item.SponsorHint || "").trim();
  if (!sponsor || sponsor === name) return name;
  return `${name}（${sponsor}）`;
}

export function periodDays(start, end) {
  if (!start || !end) return null;
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return null;
  return Math.round((to - from) / 86_400_000);
}

export function slashDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return "";
  return `${match[1]}/${Number(match[2])}/${Number(match[3])}`;
}
