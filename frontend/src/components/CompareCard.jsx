import { useEffect, useRef, useState } from "react";
import { compareFile } from "../api.js";
import ErrorLine from "./ErrorLine.jsx";
import { UploadIcon } from "./Icons.jsx";

export const COMPARE_NOTE = "Use concentrations that were not used to build either model. Otherwise the comparison favours the models that saw them.";

const mg = (v) => (v == null ? "—" : Number(v).toFixed(1));
const err4 = (v) => (v == null ? "—" : Number(v).toFixed(2));

// The summary numbers of one model. A model that predicted nothing shows "—", never 0.
function ModelSummary({ title, m, note }) {
  return (
    <div className="compare-model">
      <h3>{title}</h3>
      <div className="stats cards">
        <div className="stat"><span className="label">Valid rows</span><span className="value mono">{m.n_valid}</span></div>
        <div className="stat"><span className="label">MAE (mg/L)</span><span className="value mono">{mg(m.mae)}</span></div>
        <div className="stat"><span className="label">RMSE (mg/L)</span><span className="value mono">{mg(m.rmse)}</span></div>
        <div className="stat"><span className="label">Not predicted</span><span className="value mono">{m.n_unpredicted}</span></div>
      </div>
      {note && <p className="muted">{note}</p>}
    </div>
  );
}

// The result of one comparison: both summaries and the table. Pure, so it can be tested without a server.
export function CompareResult({ result }) {
  const { ann, linear } = result.models;
  return (
    <div className="compare-result">
      <div className="compare-models">
        <ModelSummary title={ann.available === false ? "ANN" : `ANN (${ann.model_name})`} m={ann}
          note={ann.n_review ? `${ann.n_review} row(s) are "Review": a value is given, but R, G are unusual.` : ""} />
        <ModelSummary title={linear.available ? `Linear (${linear.features.join(", ")})` : "Linear"} m={linear}
          note={linear.available ? "" : "No linear model is trained, so it could not predict any row."} />
      </div>
      {result.warnings.filter((w) => !w.startsWith("No linear model")).map((w, i) => <p key={i} className="muted">{w}</p>)}
      <div className="table-wrap short compare-table">
        <table>
          <thead>
            <tr>
              <th>Row</th>
              {result.rows.some((r) => r.file_name) && <th>File</th>}
              <th className="num">Known (mg/L)</th>
              <th className="num">ANN</th><th className="num">ANN abs. error</th>
              <th className="num">Linear</th><th className="num">Linear abs. error</th>
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r) => (
              <tr key={r.row}>
                <td className="mono">{r.row}</td>
                {result.rows.some((x) => x.file_name) && <td className="mono">{r.file_name}</td>}
                <td className="num mono">{mg(r.known_concentration)}</td>
                <td className="num mono" title={r.ann_predicted == null ? r.ann_note : undefined}>{mg(r.ann_predicted)}</td>
                <td className="num mono">{err4(r.ann_abs_error)}</td>
                <td className="num mono">{mg(r.linear_predicted)}</td>
                <td className="num mono">{err4(r.linear_abs_error)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CompareCard() {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const input = useRef(null);
  const ctl = useRef(null);
  useEffect(() => () => ctl.current?.abort(), []);

  function pick(e) {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    ctl.current?.abort();
    setFile(f); setResult(null); setError(null); setBusy(false);
  }

  async function compare() {
    if (!file || busy) return;
    ctl.current?.abort();
    ctl.current = new AbortController();
    setBusy(true); setError(null);
    try {
      setResult(await compareFile(file, ctl.current.signal));
    } catch (e) {
      if (e.name !== "AbortError") { setError(e); setResult(null); }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card compare-card">
      <h2>Compare the models</h2>
      <p className="muted">Upload a CSV or XLSX with the columns concentration_ppm, R and G (and optionally file_name). Both models predict every row; nothing is trained or saved.</p>
      <p className="warn" role="note">{COMPARE_NOTE}</p>
      <div className="row">
        <button onClick={() => input.current.click()} disabled={busy}><UploadIcon width={16} height={16} /> Choose file</button>
        <input ref={input} type="file" accept=".csv,.xlsx" hidden onChange={pick} />
        {file && <span className="file-name mono muted" title={file.name}>{file.name}</span>}
        <button className="primary" onClick={compare} disabled={!file || busy}>{busy ? "Comparing…" : "Compare"}</button>
      </div>
      <ErrorLine error={error} />
      {result && <CompareResult result={result} />}
    </section>
  );
}
