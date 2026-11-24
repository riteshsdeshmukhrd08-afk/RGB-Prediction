import { downloadUrl } from "../api.js";
import { downloadCsv } from "../csvExport.js";
import { DownloadIcon, TableIcon } from "./Icons.jsx";

const num = (v) => (v == null ? "—" : Number(v).toFixed(1));

export const NOT_VALID = "NOT_VALID_OUTSIDE_CALIBRATED_RANGE";
export const NOT_VALID_TEXT = "Not valid: outside calibrated range";

// What the Status column shows: a failed photo is red; otherwise the model's verdict (OK green, Review amber,
// Not valid red); a photo with too few liquid pixels is amber ("Low pixels") unless the model already says more.
export function statusPill(r) {
  if (r.status === "failed") return ["bad", "Failed"];
  if (r.model_status === NOT_VALID) return ["bad", NOT_VALID_TEXT];
  if (r.model_status === "REVIEW") return ["warn", "Review"];
  if (r.status === "low_pixels") return ["warn", "Low pixels"];
  return ["ok", "OK"];
}

// Why a value is empty (part of the row tooltip).
function whyEmpty(r, what) {
  if (r.status === "failed") return "The photo could not be measured, so there is no " + what;
  if (r.model_status === NOT_VALID) return what === "value"
    ? "Not valid: the predicted value is outside the calibrated range, so no value is given"
    : "No value is given, so there is no error estimate";
  return "No model loaded: nothing to predict with (train the linear model first)";
}

const noError = (r) => r.expected_error_mg_L == null || r.model_status === NOT_VALID;

// The tooltip of a row (on the concentration and on the status): the file, the ± error, why a value is empty,
// the reason a photo failed, the notes and the flags. The table itself shows only the concentration and the status.
export function rowTooltip(r) {
  const lines = [r.file_name + (r.page ? ` (page ${r.page})` : "")];
  lines.push(`± ${noError(r) ? "—" : num(r.expected_error_mg_L) + " mg/L"}`);
  if (r.predicted_concentration_mg_L == null) lines.push(whyEmpty(r, "value"));
  if (r.error) lines.push("Error: " + r.error);
  if (r.warning) lines.push("Notes: " + r.warning);
  if (r.flags) lines.push("Flags: " + r.flags.split(";").join(", "));
  return lines.join(String.fromCharCode(10));
}

// Two columns. The styles key on the class, not on the column's position.
const COLUMNS = [
  { cls: "c-conc num", label: "Concentration (mg/L)", cell: (r) => num(r.predicted_concentration_mg_L) },
  { cls: "c-status", label: "Status", cell: (r) => { const [tone, label] = statusPill(r); return <span className={"pill " + tone}>{label}</span>; } },
];

export default function ResultsCard({ jobId, job, results, files = [] }) {
  const many = files.length > 1;                       // one backend job per uploaded file
  const failed = results.filter((r) => r.status === "failed").length;
  const flagged = results.filter((r) => r.status !== "failed" && r.flags).length;
  const running = job && (job.status === "queued" || job.status === "processing");
  const finished = job && !running;
  const rowsLabel = results.length === 1 ? "row" : "rows";
  const tone = job?.status === "failed" ? "bad" : job?.status === "done" ? "ok" : "warn";     // done / failed / processing

  return (
    <section className="card results-card">
      <div className="panel-head">
        <div className="title-group">
          <h2>Results</h2>
          {jobId && <span className="muted mono job-id" title={jobId}>{many ? `${files.length} jobs` : `job ${jobId.slice(0, 8)}`}</span>}
        </div>
        {many && finished && results.length > 0 && (
          <button onClick={() => downloadCsv(results)}><DownloadIcon width={16} height={16} /> Download all CSV</button>
        )}
      </div>

      {!job && (
        <div className="empty">
          <TableIcon />
          <p className="muted">Results appear here after you press Run.</p>
        </div>
      )}

      {job && (
        <div className="summary">
          <span className={"pill " + tone}>{job.status}</span>
          <span className="figure"><b className="mono">{results.length}</b><span>{rowsLabel}</span></span>
          <span className="figure"><b className="mono">{failed}</b><span>failed</span></span>
          <span className="figure"><b className="mono">{flagged}</b><span>flagged</span></span>
          {running && <span className="muted mono">{job.processed}/{job.total} processed</span>}
        </div>
      )}
      {running && <div className="bar"><div style={{ width: `${job.total ? (100 * job.processed) / job.total : 0}%` }} /></div>}
      {job?.status === "failed" && job.error && <p className="error">{job.error}</p>}

      {results.length > 0 && (
        <div className="table-wrap">
          <table className="results-table">
            <thead>
              <tr>{COLUMNS.map((c) => <th key={c.label} className={c.cls}>{c.label}</th>)}</tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} className={r.status === "failed" ? "row-failed" : ""}>
                  {COLUMNS.map((c) => <td key={c.label} className={c.cls} title={rowTooltip(r)}>{c.cell(r, i)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {finished && results.length > 0 && !many && (
        <div className="downloads">
          <a className="button" href={downloadUrl(jobId, "csv")}><DownloadIcon width={16} height={16} /> Download CSV</a>
          <a className="button" href={downloadUrl(jobId, "xlsx")}><DownloadIcon width={16} height={16} /> Download XLSX</a>
        </div>
      )}
      {finished && many && (
        <details className="per-file">
          <summary>Downloads per file ({files.length})</summary>
          <ul>
            {files.map((f) => (
              <li key={f.id}>
                <span className="name mono" title={f.name}>{f.name}</span>
                <span className={"fstatus fs-" + f.status}>{f.status}</span>
                <a className="button small" href={downloadUrl(f.id, "csv")} aria-label={`CSV for ${f.name}`}>CSV</a>
                <a className="button small" href={downloadUrl(f.id, "xlsx")} aria-label={`XLSX for ${f.name}`}>XLSX</a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
