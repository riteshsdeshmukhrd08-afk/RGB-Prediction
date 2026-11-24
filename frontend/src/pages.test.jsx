import { describe, expect, it } from "vitest";
import { renderToStaticMarkup as html } from "react-dom/server";
import ResultsCard, { rowTooltip, statusPill } from "./components/ResultsCard.jsx";
import TopBar from "./components/TopBar.jsx";
import Banner from "./components/Banner.jsx";
import ModelCards from "./components/ModelCards.jsx";
import { CompareResult, COMPARE_NOTE } from "./components/CompareCard.jsx";
import { MODEL_DISPLAY_NAME, modelLabel } from "./modelInfo.js";
import { csvFromResults } from "./csvExport.js";

const job = { status: "done", processed: 2, total: 2 };
const results = [
  { file_name: "a.jpg", page: null, status: "ok", error: "", R: 220.02, G: 140, B: 40, predicted_concentration_mg_L: 199.6, expected_error_mg_L: 12.5, model_status: "OK", model_status_text: "OK", flags: "", warning: "", image_url: null },
  { file_name: "b.pdf", page: 2, status: "failed", error: "no tube", R: null, G: null, B: null, predicted_concentration_mg_L: null, expected_error_mg_L: null, model_status: null, model_status_text: "", flags: "failed", warning: "", image_url: null },
];

const ANN = { model_type: "ann", model_name: "ANN v1.1", features: ["R", "G"], expected_error_mg_L: 33.93783767886789, trainable: false };
const LINEAR = { model_type: "linear", model_version: "abc123def456", features: ["R", "G"], expected_error_mg_L: 12.5, trainable: true };
const UNTRAINED = { model_type: "linear", model_version: null, features: [], expected_error_mg_L: null, trainable: true };

describe("Banner", () => {
  it("says so when the ANN model could not be loaded, with the reason", () => {
    const m = html(<Banner health={{ mongo: "ok", model: "unavailable", model_error: "Model file not found: ann_v1_1.joblib" }} healthError={null} onRecheck={() => {}} />);
    expect(m).toContain("The ANN model is not loaded on the server");
    expect(m).toContain("Model file not found: ann_v1_1.joblib");
  });
  it("shows nothing when the model is loaded (or the linear model is simply not trained)", () => {
    expect(html(<Banner health={{ mongo: "ok", model: "loaded" }} healthError={null} onRecheck={() => {}} />)).toBe("");
    expect(html(<Banner health={{ mongo: "ok", model: "missing" }} healthError={null} onRecheck={() => {}} />)).toBe("");
  });
});

describe("Top bar", () => {
  it("shows the model name from one constant, with no error value", () => {
    const m = html(<TopBar dbDown={false} backendError={null} model={ANN} />);
    expect(m).toContain("RGB measurement");
    expect(m).toContain("Model: RGB prediction model");
    expect(MODEL_DISPLAY_NAME).toBe("RGB prediction model");
    expect(m).not.toMatch(/±|33\.9|mg\/L/);
    expect(modelLabel(ANN)).toBe(`Model: ${MODEL_DISPLAY_NAME}`);
  });
  it("shows the linear model's details, or that it is not trained yet", () => {
    expect(html(<TopBar dbDown={false} backendError={null} model={LINEAR} />)).toContain("Model: linear (R, G)");
    expect(html(<TopBar dbDown={false} backendError={null} model={UNTRAINED} />)).toContain("Model: linear · not trained yet");
    expect(modelLabel(null)).toBe("");
  });
  it("shows no model chip until the model is known", () => {
    const m = html(<TopBar dbDown={false} backendError={null} />);
    expect(m).not.toContain("Model:");
    expect(m).not.toMatch(/class="chip /);                   // no chip at all when everything is fine
  });
  it("shows a red chip when the database or the backend is down", () => {
    expect(html(<TopBar dbDown backendError={null} />)).toMatch(/class="chip bad"[^>]*>.*Database not reachable/);
    expect(html(<TopBar dbDown={false} backendError={{ message: "The backend is not reachable. Is it running?" }} />)).toContain("The backend is not reachable");
  });
});

describe("Model cards", () => {
  it("shows the Train card only for the linear model", () => {
    const linear = html(<ModelCards model={LINEAR} onTrained={() => {}} />);
    expect(linear).toContain("Train the concentration model");
    expect(linear).not.toContain("fixed and cannot be trained");
    expect(html(<ModelCards model={UNTRAINED} onTrained={() => {}} />)).toContain("Train the concentration model");
  });
  it("shows a short notice instead when the model is the ANN", () => {
    const m = html(<ModelCards model={ANN} onTrained={() => {}} />);
    expect(m).not.toContain("Train the concentration model");
    expect(m).toContain("ANN v1.1");
    expect(m).toContain("fixed and cannot be trained here");
    expect(m).toContain("MODEL_TYPE=linear");
  });
  it("shows neither before the model is known, and always the Compare card with its note", () => {
    for (const model of [null, ANN, LINEAR]) {
      const m = html(<ModelCards model={model} onTrained={() => {}} />);
      expect(m).toContain("Compare the models");
      expect(m).toContain(COMPARE_NOTE.replace(/'/g, "&#x27;"));
      expect(m).toContain(">Compare<");
    }
    const none = html(<ModelCards model={null} onTrained={() => {}} />);
    expect(none).not.toContain("Train the concentration model");
    expect(none).not.toContain("fixed and cannot be trained");
  });
});

describe("Compare card", () => {
  const result = {
    n_rows: 3, rejected_rows: [], warnings: ["Using trim_R as R"],
    models: {
      ann: { model_name: "ANN v1.1", available: true, features: ["R", "G"], n_rows: 3, n_valid: 2, mae: 15, rmse: 15.8114, n_unpredicted: 1, n_review: 1 },
      linear: { model_version: null, features: [], available: false, n_rows: 3, n_valid: 0, mae: null, rmse: null, n_unpredicted: 3 },
    },
    rows: [
      { row: 2, known_concentration: 100, ann_predicted: 110, ann_status: "OK", ann_note: "", ann_abs_error: 10, linear_predicted: null, linear_note: "", linear_abs_error: null },
      { row: 3, known_concentration: 200, ann_predicted: 220, ann_status: "REVIEW", ann_note: "", ann_abs_error: 20, linear_predicted: null, linear_note: "", linear_abs_error: null },
      { row: 4, known_concentration: 300, ann_predicted: null, ann_status: "NOT_VALID_OUTSIDE_CALIBRATED_RANGE", ann_note: "Predicted value is outside the calibrated range 0-1255 mg/L", ann_abs_error: null, linear_predicted: null, linear_note: "", linear_abs_error: null },
    ],
  };
  it("shows the summary numbers of both models", () => {
    const m = html(<CompareResult result={result} />);
    expect(m).toContain("ANN (ANN v1.1)");
    expect(m).toMatch(/Valid rows<\/span><span class="value mono">2</);
    expect(m).toMatch(/MAE \(mg\/L\)<\/span><span class="value mono">15\.0</);
    expect(m).toMatch(/RMSE \(mg\/L\)<\/span><span class="value mono">15\.8</);
    expect(m).toMatch(/Not predicted<\/span><span class="value mono">1</);
    expect(m).toContain("No linear model is trained, so it could not predict any row.");
    expect(m).toMatch(/MAE \(mg\/L\)<\/span><span class="value mono">—</);                  // a model that predicted nothing: a dash, not 0
  });
  it("shows the comparison table with the known value, both predictions and both errors", () => {
    const m = html(<CompareResult result={result} />);
    const heads = [...m.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((x) => x[1]);
    expect(heads).toEqual(["Row", "Known (mg/L)", "ANN", "ANN abs. error", "Linear", "Linear abs. error"]);
    expect(m.match(/<tbody>.*<\/tbody>/s)[0].match(/<tr>/g)).toHaveLength(3);
    expect(m).toMatch(/<td class="num mono">100\.0<\/td><td class="num mono"[^>]*>110\.0<\/td><td class="num mono">10\.00<\/td><td class="num mono">—<\/td>/);
    expect(m).toContain('title="Predicted value is outside the calibrated range 0-1255 mg/L"');   // why the ANN value is empty
    expect(m).toContain('1 row(s) are "Review"'.replace(/"/g, "&quot;"));
  });
});

describe("Results table", () => {
  it("has exactly five columns: R, G, B, Concentration (mg/L), Image", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    const heads = [...m.matchAll(/<th class="[^"]*">([^<]*)<\/th>/g)].map((x) => x[1]);
    expect(heads).toEqual(["R", "G", "B", "Concentration (mg/L)", "Image"]);
    expect(m.match(/<tbody>.*?<\/tr>/s)[0].match(/<td class="/g)).toHaveLength(5);       // one cell per heading
    expect([...m.matchAll(/<th class="([^"]+)"/g)].map((x) => x[1])).toEqual(["c-rgb num", "c-rgb num", "c-rgb num", "c-conc num", "c-image"]);
    for (const gone of ["Page", "Colour", "± error", "Status", "swatch", "(ppm)", "COD"]) expect(m).not.toContain(gone);
  });
  it("shows R, G, B with two decimals and the concentration with one", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[{ ...results[0], predicted_concentration_mg_L: 200 }]} />);
    expect(m).toMatch(/<td class="c-rgb num">220\.02<\/td><td class="c-rgb num">140\.00<\/td><td class="c-rgb num">40\.00<\/td><td class="c-conc num"[^>]*>200\.0<\/td>/);
    expect(html(<ResultsCard jobId="j" job={job} results={[{ ...results[0], predicted_concentration_mg_L: 387.55 }]} />)).toMatch(/>387\.[56]<\/td>/);
  });
  it("shows a dash when there is no value, R, G or B", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[results[1]]} />);
    expect(m.match(/<tbody>.*<\/tbody>/s)[0].match(/>—</g)).toHaveLength(5);              // R, G, B, concentration, image
  });
  it("shows Open as a link to the image in a new tab, and a dash without an image URL", () => {
    const withImage = html(<ResultsCard jobId="j" job={job} results={[{ ...results[0], image_url: "https://x.example/a.jpg" }]} />);
    expect(withImage).toContain('<td class="c-image"><a href="https://x.example/a.jpg" target="_blank" rel="noreferrer">Open</a></td>');
    expect(html(<ResultsCard jobId="j" job={job} results={[results[0]]} />)).toContain('<td class="c-image">—</td>');
  });
  it("shows the status in the concentration tooltip, without the expected error", () => {
    const review = { ...results[0], predicted_concentration_mg_L: 387.6, expected_error_mg_L: 33.93783767886789, model_status: "REVIEW" };
    expect(rowTooltip(review).split(String.fromCharCode(10))[0]).toBe("Review");
    expect(html(<ResultsCard jobId="j" job={job} results={[review]} />)).toMatch(/<td class="c-conc num" title="Review[^"]*"[^>]*>387\.6<\/td>/);
    expect(rowTooltip(results[0]).split(String.fromCharCode(10))[0]).toBe("OK");
  });
  it("shows the expected error of a single result nowhere on screen", () => {
    const row = { ...results[0], predicted_concentration_mg_L: 387.6, expected_error_mg_L: 33.93783767886789, model_status: "REVIEW", warning: "w", flags: "clipped", image_url: "https://x.example/a.jpg" };
    const screens = [html(<TopBar dbDown={false} backendError={null} model={ANN} />),
      html(<ResultsCard jobId="j" job={job} results={[row, results[1]]} />),
      html(<ModelCards model={ANN} onTrained={() => {}} />)];
    for (const m of screens) expect(m).not.toMatch(/±|33\.9|33\.94|12\.5/);
    expect(rowTooltip(row)).not.toMatch(/±|33\.9|mg\/L/);
  });
  it("shows the failure reason in the tooltip of a failed row", () => {
    const t = rowTooltip(results[1]);
    expect(t.split(String.fromCharCode(10))[0]).toBe("Failed");
    expect(t).toContain("Error: no tube");
    expect(t).toContain("The photo could not be measured, so there is no value");
  });
  it("explains an empty value in the tooltip (no model, or Not valid)", () => {
    const none = { ...results[0], predicted_concentration_mg_L: null, expected_error_mg_L: null, model_status: null };
    expect(rowTooltip(none).split(String.fromCharCode(10))[0]).toBe("OK");
    expect(rowTooltip(none)).toContain("No model loaded: nothing to predict with (train the linear model first)");
    const bad = { ...results[0], predicted_concentration_mg_L: null, expected_error_mg_L: 33.94, model_status: "NOT_VALID_OUTSIDE_CALIBRATED_RANGE" };
    expect(rowTooltip(bad).split(String.fromCharCode(10))[0]).toBe("Not valid: outside calibrated range");
    expect(rowTooltip(bad)).toContain("Not valid: the predicted value is outside the calibrated range, so no value is given");
  });
  it("derives the status label: OK green, Review amber, Not valid red, Failed red, Low pixels amber", () => {
    expect(statusPill(results[0])).toEqual(["ok", "OK"]);
    expect(statusPill({ ...results[0], model_status: "REVIEW" })).toEqual(["warn", "Review"]);
    expect(statusPill({ ...results[0], model_status: "NOT_VALID_OUTSIDE_CALIBRATED_RANGE" })).toEqual(["bad", "Not valid: outside calibrated range"]);
    expect(statusPill(results[1])).toEqual(["bad", "Failed"]);
    expect(statusPill({ ...results[0], status: "low_pixels" })).toEqual(["warn", "Low pixels"]);
  });
  it("puts the notes and flags in the tooltip, and counts flagged rows in the summary line", () => {
    const long = "Outside the calibrated region. Confirm with a standard.";
    const r = { ...results[0], model_status: "REVIEW", warning: long, flags: "clipped;high_std" };
    expect(rowTooltip(r)).toBe(["Review", "a.jpg", "Notes: " + long, "Flags: clipped, high_std"].join(String.fromCharCode(10)));
    const m = html(<ResultsCard jobId="j" job={job} results={[r, results[1]]} />);
    expect(m).toContain('<span class="figure"><b class="mono">1</b><span>flagged</span></span>');
  });
  it("shows the status pill and the three figures in one summary row, with their labels apart", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    const row = m.match(/<div class="summary">.*?<\/div>/s)[0];
    expect(row).toContain('<span class="pill ok">done</span>');
    expect(row).toContain('<span class="figure"><b class="mono">2</b><span>rows</span></span>');
    expect(row).toContain('<span class="figure"><b class="mono">1</b><span>failed</span></span>');
    expect(row).toContain('<span class="figure"><b class="mono">0</b><span>flagged</span></span>');
    expect(row.indexOf("pill")).toBeLessThan(row.indexOf("rows"));
    expect(m).not.toContain('class="stats"');
  });
  it("uses the singular for exactly one row", () => {
    const one = html(<ResultsCard jobId="j" job={job} results={[results[0]]} />);
    expect(one).toContain('<b class="mono">1</b><span>row</span>');
    expect(one).not.toContain("<span>rows</span>");
    expect(html(<ResultsCard jobId="j" job={job} results={[]} />)).toContain('<b class="mono">0</b><span>rows</span>');
  });
  it("colours the pill by state: done green, processing amber, failed red", () => {
    const pill = (status) => html(<ResultsCard jobId="j" job={{ status, processed: 3, total: 15 }} results={results} />).match(/<span class="(pill [a-z]+)">([a-z]+)<\/span>/)[0];
    expect(pill("done")).toBe('<span class="pill ok">done</span>');
    expect(pill("processing")).toBe('<span class="pill warn">processing</span>');
    expect(pill("failed")).toBe('<span class="pill bad">failed</span>');
  });
  it("shows the progress count in the row while processing", () => {
    const m = html(<ResultsCard jobId="j" job={{ status: "processing", processed: 3, total: 15 }} results={results} />);
    expect(m).toContain("3/15 processed");
    expect(html(<ResultsCard jobId="j" job={job} results={results} />)).not.toContain("processed");
  });
  it("shows a centred empty state before any job", () => {
    const m = html(<ResultsCard jobId={null} job={null} results={[]} />);
    expect(m).toContain('class="empty"');
    expect(m).toContain("Results appear here after you press Run.");
  });
  it("puts the download buttons after the table, at the bottom of the panel", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    expect(m.indexOf("</table>")).toBeLessThan(m.indexOf('class="downloads"'));
    expect(html(<ResultsCard jobId="j" job={{ status: "processing", processed: 1, total: 2 }} results={results} />)).not.toContain("Download CSV");
  });
  it("keeps the CSV and XLSX download buttons", () => {
    const m = html(<ResultsCard jobId="job1" job={job} results={results} />);
    expect(m).toContain("Download CSV");
    expect(m).toContain("Download XLSX");
    expect(m).toContain("/api/jobs/job1/download?format=csv");
  });
});

describe("Combined CSV", () => {
  it("has the new columns and shows the model status as text, like the server export", () => {
    const bad = { ...results[0], file_name: "n.jpg", predicted_concentration_mg_L: null, expected_error_mg_L: 33.94, model_status: "NOT_VALID_OUTSIDE_CALIBRATED_RANGE", model_status_text: "Not valid: outside calibrated range" };
    const lines = csvFromResults([results[0], bad]).trim().split(String.fromCharCode(10));
    expect(lines[0]).toBe("file_name,page,status,R,G,B,predicted_concentration_mg_L,expected_error_mg_L,model_status,flags,warning,error,image_url");
    for (const col of ["page", "R", "G", "B", "error", "expected_error_mg_L"]) expect(lines[0].split(",")).toContain(col);   // the table hides them, the file keeps them
    expect(lines[1]).toBe("a.jpg,,ok,220.02,140,40,199.6,12.5,OK,,,,");
    expect(lines[2]).toBe("n.jpg,,ok,220.02,140,40,,33.94,Not valid: outside calibrated range,,,,");
  });
});
