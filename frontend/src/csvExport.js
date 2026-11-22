// Builds the combined CSV in the browser from the merged results. Same columns, order and
// formula-injection protection as backend/exports.py, so it matches a server download.
export const CSV_COLUMNS = ["file_name", "page", "status", "R", "G", "B", "cod_mg_L", "flags", "warning", "error", "image_url"];

const DANGEROUS_START = ["=", "+", "-", "@", "\t", "\r"];

function cell(value) {
  if (value == null) return "";
  let s = typeof value === "string" ? value : String(value);
  if (typeof value === "string" && DANGEROUS_START.some((c) => s.startsWith(c))) s = "'" + s;
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

export function csvFromResults(results) {
  const lines = [CSV_COLUMNS.join(",")];
  for (const r of results) lines.push(CSV_COLUMNS.map((c) => cell(c === "cod_mg_L" ? r.cod_mg_l : r[c])).join(","));
  return lines.join("\n") + "\n";
}

export function downloadCsv(results, filename = "rgb_results_all.csv") {
  const url = URL.createObjectURL(new Blob([csvFromResults(results)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
