import { useRef, useState } from "react";
import { formatSize } from "../files.js";
import { CheckIcon, CloseIcon, UploadIcon } from "./Icons.jsx";

// Small presentational pieces of the Train card (they only show what they are given).

const fmt = (v, digits = 4) => (v == null ? "–" : Number(v).toFixed(digits).replace(/\.?0+$/, "") || "0");
const cell = (v) => (v == null ? "" : String(v));

export function ValidationMessages({ errors = [], warnings = [], passed = [] }) {
  return (
    <div className="messages">
      {errors.map((e, i) => <p className="error" key={"e" + i} role="alert">{e}</p>)}
      {warnings.map((w, i) => <p className="warn" key={"w" + i}>{w}</p>)}
      {passed.map((m, i) => <p className="passed" key={"p" + i}><CheckIcon /> {m}</p>)}
    </div>
  );
}

export function Steps({ steps }) {
  return (
    <ol className="steps" aria-label="Training steps">
      {steps.map((s) => (
        <li key={s.n} className={"step " + s.state} aria-current={s.state === "active" ? "step" : undefined}>
          <span className="num mono">{s.state === "done" ? <CheckIcon /> : s.n}</span>
          <span className="step-label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

export const HELP_TEXT = "Use the Download CSV from the Results panel, after adding a concentration_ppm column. Also accepted: the batch_features export.";

// The drop zone of the Train card. It stays visible after a file is chosen, so a new file can be dropped on it.
export function TrainFile({ file, running, onChoose, onRemove }) {
  const picker = useRef(null);
  const [dragging, setDragging] = useState(false);
  return (
    <>
      <div
        className={"drop" + (dragging ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (!running) onChoose(e.dataTransfer.files[0]); }}
      >
        <UploadIcon className="drop-icon" />
        {file ? (
          <div className="file-chip">
            <span className="mono file-name" title={file.name}>{file.name}</span>
            <span className="mono muted">{formatSize(file.size)}</span>
            <button className="remove always" onClick={onRemove} disabled={running} aria-label={`Remove ${file.name}`} title="Remove">
              <CloseIcon />
            </button>
          </div>
        ) : (
          <p>Drop a .csv or .xlsx file here</p>
        )}
        <button onClick={() => picker.current.click()} disabled={running}>{file ? "Choose a different file" : "Choose file"}</button>
        <input ref={picker} type="file" accept=".csv,.xlsx" hidden
          onChange={(e) => { onChoose(e.target.files[0]); e.target.value = ""; }} />
      </div>
      <p className="muted help">{HELP_TEXT}</p>
    </>
  );
}

export function PreviewPanel({ preview }) {
  if (!preview) return null;
  return (
    <div className="preview">
      {preview.mappings?.length > 0 && (
        <>
          <h3>Column mapping</h3>
          <ul className="mappings">{preview.mappings.map((m) => <li key={m} className="mono">{m}</li>)}</ul>
        </>
      )}
      <h3>First {preview.preview.length} of {preview.n_rows} rows</h3>
      <div className="table-wrap short">
        <table>
          <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {preview.preview.map((row, i) => (
              <tr key={i}>{preview.columns.map((c) => <td key={c}>{cell(row[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.concentrations.length > 0 && (
        <>
          <h3>Concentrations found</h3>
          <div className="table-wrap short">
            <table className="small">
              <thead><tr><th>Concentration (ppm)</th><th>Rows</th></tr></thead>
              <tbody>
                {preview.concentrations.map((c) => <tr key={c.ppm}><td>{fmt(c.ppm)}</td><td>{c.rows}</td></tr>)}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export function TrainButton({ reason, running, onClick }) {
  return (
    <div className="row">
      <button className="primary" onClick={onClick} disabled={!!reason}>{running ? "Training…" : "Train"}</button>
      {reason && <span className="muted">{reason}</span>}
    </div>
  );
}

export function ReportPanel({ report }) {
  if (!report) return null;
  return (
    <div className="report">
      <div className="stats cards">
        <div className="stat">
          <span className="label">Validation</span>
          <span><span className={"pill " + (report.validated ? "ok" : "warn")}>{report.validated ? "Validated" : "In-sample only"}</span></span>
          <span className="muted">{report.validation}</span>
        </div>
        <div className="stat">
          <span className="label">Typical error</span>
          <span className="value mono">±{fmt(report.typical_error_ppm, 2)} ppm</span>
        </div>
        <div className="stat">
          <span className="label">Features</span>
          <span className="value mono">{report.features.join(", ")}</span>
        </div>
        <div className="stat">
          <span className="label">Data</span>
          <span className="value mono">{report.n_rows} rows</span>
          <span className="muted mono">{report.n_concentrations} concentrations</span>
        </div>
      </div>
      <h3>Model: concentration = intercept + coefficient × feature</h3>
      <table className="small">
        <thead><tr><th>Term</th><th>Coefficient</th></tr></thead>
        <tbody>
          <tr><td>intercept</td><td>{fmt(report.intercept)}</td></tr>
          {report.features.map((f, i) => <tr key={f}><td>{f}</td><td>{fmt(report.coefficients[i])}</td></tr>)}
        </tbody>
      </table>
      <h3>Error by concentration range</h3>
      <table className="small">
        <thead><tr><th>Range (ppm)</th><th>Rows</th><th>Typical error (ppm)</th></tr></thead>
        <tbody>
          {report.error_by_range.map((r) => <tr key={r.range_ppm}><td>{r.range_ppm}</td><td>{r.n_rows}</td><td>±{fmt(r.RMSE_ppm, 2)}</td></tr>)}
        </tbody>
      </table>
      {report.candidates && (
        <>
          <h3>Feature sets tried</h3>
          <table className="small">
            <thead><tr><th>Features</th><th>Error (ppm)</th></tr></thead>
            <tbody>
              {report.candidates.map((c) => (
                <tr key={c.features.join()} className={c.features.join() === report.features.join() ? "chosen" : ""}>
                  <td>{c.features.join(", ")}{c.features.join() === report.features.join() ? " ✓" : ""}</td>
                  <td>{c.skipped ? `skipped (${c.skipped})` : fmt(c.RMSE_ppm, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
