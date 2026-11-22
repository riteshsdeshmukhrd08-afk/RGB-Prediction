import { downloadUrl } from "../api.js";
import { downloadCsv } from "../csvExport.js";
import { DownloadIcon, TableIcon } from "./Icons.jsx";

const fmt = (v) => (v == null ? "–" : Number(v).toFixed(2));
const cod = (v) => (v == null ? "–" : Number(v).toFixed(1));

// A photo whose R, G is outside the model's range is shown as text instead of a number.
export const OUTSIDE_RANGE = "outside range";
const STATUS = { ok: ["ok", "OK"], outside_range: ["warn", OUTSIDE_RANGE], failed: ["bad", "Failed"] };

const fileLabel = (r) => (r.page ? `${r.file_name} (p. ${r.page})` : r.file_name);

// One entry per column: its heading, a class (the styles key on the class, not on the column's position),
// and how to draw its cell. `num` columns are right-aligned monospace, in the heading too.
const COLUMNS = [
  { cls: "c-file", label: "File", title: fileLabel, cell: (r) => <span className="ellipsis mono">{fileLabel(r)}</span> },
  { cls: "c-rgb num", label: "R", cell: (r) => fmt(r.R) },
  { cls: "c-rgb num", label: "G", cell: (r) => fmt(r.G) },
  { cls: "c-rgb num", label: "B", cell: (r) => fmt(r.B) },
  { cls: "c-cod num", label: "COD (mg/L)", cell: (r) => (r.status === "outside_range" ? OUTSIDE_RANGE : cod(r.cod_mg_l)) },
  { cls: "c-status", label: "Status", cell: (r) => { const [tone, label] = STATUS[r.status] || ["", r.status]; return <span className={"pill " + tone}>{label}</span>; } },
];

export default function ResultsCard({ jobId, job, results, files = [] }) {
  const many = files.length > 1;                       // one backend job per uploaded file
  const failed = results.filter((r) => r.status === "failed").length;
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
                  {COLUMNS.map((c) => <td key={c.label} className={c.cls} title={c.title?.(r)}>{c.cell(r)}</td>)}
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
