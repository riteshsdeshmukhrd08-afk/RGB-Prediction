import { downloadUrl } from "../api.js";
import { DownloadIcon, TableIcon } from "./Icons.jsx";

const fmt = (v) => (v == null ? "–" : Number(v).toFixed(2));
const ppm = (v) => (v == null ? "—" : Number(v).toFixed(1));
const channel = (v) => Math.max(0, Math.min(255, Math.round(Number(v))));      // clamp to 0-255

const STATUS = { ok: ["ok", "OK"], low_pixels: ["warn", "Low pixels"], failed: ["bad", "Failed"] };

function Swatch({ r, g, b }) {
  if (r == null || g == null || b == null) return null;
  return <span className="swatch" style={{ background: `rgb(${channel(r)}, ${channel(g)}, ${channel(b)})` }} title={`rgb(${channel(r)}, ${channel(g)}, ${channel(b)})`} />;
}

// One entry per column: its heading, a class (the styles key on the class, not on the column's position),
// and how to draw its cell. `num` columns are right-aligned monospace, in the heading too.
const COLUMNS = [
  { cls: "c-index num", label: "#", cell: (r, i) => i + 1 },
  { cls: "c-file", label: "File", title: (r) => r.file_name, cell: (r) => <span className="ellipsis mono">{r.file_name}</span> },
  { cls: "c-page num", label: "Page", cell: (r) => r.page ?? "" },
  { cls: "c-rgb num", label: "R", cell: (r) => fmt(r.R) },
  { cls: "c-rgb num", label: "G", cell: (r) => fmt(r.G) },
  { cls: "c-rgb num", label: "B", cell: (r) => fmt(r.B) },
  { cls: "c-colour", label: "Colour", cell: (r) => <Swatch r={r.R} g={r.G} b={r.B} /> },
  { cls: "c-ppm num", label: "Predicted concentration (ppm)", title: (r, i, m) => (m ? undefined : "No model loaded"),
    cell: (r, i, m) => (m ? ppm(r.predicted_concentration_ppm) : "—") },
  { cls: "c-err num", label: "± error (ppm)", title: (r, i, m) => (m ? undefined : "No model loaded"),
    cell: (r, i, m) => (m ? ppm(r.typical_error_ppm) : "—") },
  { cls: "c-status", label: "Status", cell: (r) => { const [tone, label] = STATUS[r.status] || ["", r.status]; return <span className={"pill " + tone}>{label}</span>; } },
  { cls: "c-flags", label: "Flags", cell: (r) => (r.flags ? r.flags.split(";").map((f) => <span className="tag" key={f}>{f}</span>) : null) },
  { cls: "c-notes", label: "Notes", cell: (r) => [r.warning, r.error].filter(Boolean).join(" · ") },
  { cls: "c-image", label: "Image", cell: (r) => (r.image_url ? <a href={r.image_url} target="_blank" rel="noreferrer">Open</a> : "") },
];

export default function ResultsCard({ jobId, job, results, hasModel }) {
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
          {jobId && <span className="muted mono job-id" title={jobId}>job {jobId.slice(0, 8)}{jobId.includes(",") ? ` +${jobId.split(",").length - 1}` : ""}</span>}
        </div>
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
                  {COLUMNS.map((c) => <td key={c.label} className={c.cls} title={c.title?.(r, i, hasModel)}>{c.cell(r, i, hasModel)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {finished && results.length > 0 && (
        <div className="downloads">
          {jobId.split(",").map((id, n, all) => {
            const part = all.length > 1 ? ` (file ${n + 1})` : "";   // one backend job per uploaded file
            return [
              <a className="button" key={id + "c"} href={downloadUrl(id, "csv")}><DownloadIcon width={16} height={16} /> Download CSV{part}</a>,
              <a className="button" key={id + "x"} href={downloadUrl(id, "xlsx")}><DownloadIcon width={16} height={16} /> Download XLSX{part}</a>,
            ];
          })}
        </div>
      )}
    </section>
  );
}
