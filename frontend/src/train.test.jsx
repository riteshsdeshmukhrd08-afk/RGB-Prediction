import { describe, expect, it } from "vitest";
import { renderToStaticMarkup as html } from "react-dom/server";
import TrainCard from "./components/TrainCard.jsx";
import { HELP_TEXT, PreviewPanel, ReportPanel, Steps, TrainButton, TrainFile, ValidationMessages } from "./components/TrainParts.jsx";
import { initialTrain, isTableFile, isTrainRunning, passedChecks, trainBlockReason, trainReducer, trainSteps } from "./trainState.js";

const file = { name: "known.csv" };
const goodPreview = { valid: true, errors: [], warnings: [] };

const samplePreview = {
  valid: true,
  n_rows: 7,
  columns: ["file_name", "concentration_ppm", "R", "G", "B"],
  preview: [
    { file_name: "a.jpg", concentration_ppm: 0, R: 230, G: 200, B: 20 },
    { file_name: "b.jpg", concentration_ppm: 0, R: 229.5, G: 199, B: 21 },
    { file_name: "c.jpg", concentration_ppm: 100, R: 220, G: 180, B: 20 },
    { file_name: "d.jpg", concentration_ppm: 100, R: 219, G: 181, B: 19 },
    { file_name: "e.jpg", concentration_ppm: 300, R: 200, G: 140, B: 18 },
  ],
  concentrations: [{ ppm: 0, rows: 2 }, { ppm: 100, rows: 3 }, { ppm: 300, rows: 2 }],
  errors: [],
  warnings: [],
};

const sampleReport = (validated) => ({
  validated,
  validation: validated ? "leave-one-concentration-out" : "in-sample only, not validated",
  typical_error_ppm: 12.5,
  n_rows: 24,
  n_concentrations: validated ? 6 : 3,
  intercept: 250,
  features: ["R", "G"],
  coefficients: [3, -2],
  error_by_range: [{ range_ppm: "0-200", n_rows: 8, RMSE_ppm: 9.1 }, { range_ppm: "200-600", n_rows: 10, RMSE_ppm: 12.2 }],
  candidates: [{ features: ["R", "G"], RMSE_ppm: 12.5, skipped: "" }, { features: ["R"], RMSE_ppm: 40, skipped: "" }],
});

describe("Train button state", () => {
  it("is disabled until a valid file is chosen", () => {
    expect(trainBlockReason({ file: null, preview: null, checking: false, running: false })).toBe("Choose a CSV or XLSX file");
    expect(trainBlockReason({ file, preview: null, checking: true, running: false })).toBe("Checking the file…");
    expect(trainBlockReason({ file, preview: { valid: false, errors: ["x"] }, checking: false, running: false })).toBe("Fix the errors above");
    expect(trainBlockReason({ file, preview: goodPreview, checking: false, running: false })).toBe("");
  });
  it("is disabled while a training runs", () => {
    expect(trainBlockReason({ file, preview: goodPreview, checking: false, running: true })).toBe("A training is running");
  });
  it("renders disabled or enabled", () => {
    expect(html(<TrainButton reason="Choose a CSV or XLSX file" onClick={() => {}} />)).toMatch(/<button[^>]*disabled/);
    expect(html(<TrainButton reason="" onClick={() => {}} />)).not.toMatch(/disabled/);
  });
  it("the whole card starts with Train disabled", () => {
    const markup = html(<TrainCard onTrained={() => {}} />);
    expect(markup).toMatch(/<button class="primary"[^>]*disabled/);
    expect(markup).toContain("Choose a CSV or XLSX file");
  });
  it("accepts only .csv and .xlsx", () => {
    expect(isTableFile({ name: "a.CSV" })).toBe(true);
    expect(isTableFile({ name: "a.xlsx" })).toBe(true);
    expect(isTableFile({ name: "a.xls" })).toBe(false);
    expect(isTableFile({ name: "a.txt" })).toBe(false);
  });
});

describe("Steps", () => {
  const states = (o) => trainSteps({ file: null, checking: false, preview: null, running: false, status: null, ...o }).map((s) => s.state);
  it("starts with the first step active", () => {
    expect(states({})).toEqual(["active", "pending", "pending"]);
  });
  it("moves along as the file is chosen, checked and trained", () => {
    expect(states({ file, checking: true })).toEqual(["done", "active", "pending"]);
    expect(states({ file, preview: { valid: false } })).toEqual(["done", "active", "pending"]);
    expect(states({ file, preview: { valid: true } })).toEqual(["done", "done", "active"]);
    expect(states({ file, preview: { valid: true }, running: true })).toEqual(["done", "done", "active"]);
    expect(states({ file, preview: { valid: true }, status: { status: "done" } })).toEqual(["done", "done", "done"]);
  });
  it("renders the three numbered labels", () => {
    const m = html(<Steps steps={trainSteps({ file: null, checking: false, preview: null, running: false, status: null })} />);
    for (const label of ["Choose file", "Check", "Train"]) expect(m).toContain(label);
    expect(m).toContain('class="step active"');
  });
});

describe("Passed checks", () => {
  it("lists what is fine, in green", () => {
    const passed = passedChecks(samplePreview);
    expect(passed).toContain("All required columns found");
    expect(passed).toContain("3 distinct concentrations");
    expect(html(<ValidationMessages passed={passed} />)).toContain('<p class="passed">');
  });
  it("does not claim the columns are fine when one is missing", () => {
    const bad = { ...samplePreview, valid: false, errors: ["Found: a, b. Missing: B. Add B column(s); trim_B or mean_B also work."], n_valid_rows: 0, concentrations: [] };
    expect(passedChecks(bad)).toEqual([]);
  });
});

describe("Preview", () => {
  it("shows the first 5 rows and the concentration table for a sample file", () => {
    const m = html(<PreviewPanel preview={samplePreview} />);
    expect(m).toContain("First 5 of 7 rows");
    for (const name of ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]) expect(m).toContain(name);
    expect((m.match(/<tbody><tr>/g) || []).length).toBe(2);                 // preview table + concentration table
    expect(m).toContain("<td>0</td><td>2</td>");
    expect(m).toContain("<td>100</td><td>3</td>");
    expect(m).toContain("<td>300</td><td>2</td>");
  });
  it("shows errors in red and warnings in amber", () => {
    const m = html(<ValidationMessages errors={["Found: a. Missing: B."]} warnings={["Ignored row(s) 4."]} />);
    expect(m).toContain('<p class="error" role="alert">Found: a. Missing: B.</p>');
    expect(m).toContain('<p class="warn">Ignored row(s) 4.</p>');
  });
});

describe("Report", () => {
  it("renders a validated model", () => {
    const m = html(<ReportPanel report={sampleReport(true)} />);
    expect(m).toContain("Validated");
    expect(m).not.toContain("In-sample only</span>");
    expect(m).toContain("±12.5 ppm");
    expect(m).toContain("<td>intercept</td><td>250</td>");
    expect(m).toContain("<td>R</td><td>3</td>");
    expect(m).toContain("<td>G</td><td>-2</td>");
    expect(m).toContain("<td>0-200</td><td>8</td><td>±9.1</td>");
  });
  it("renders a model that was not validated", () => {
    const m = html(<ReportPanel report={sampleReport(false)} />);
    expect(m).toContain("In-sample only");
    expect(m).toContain("in-sample only, not validated");
    expect(m).not.toMatch(/pill ok/);
  });
  it("renders nothing without a report", () => {
    expect(html(<ReportPanel report={null} />)).toBe("");
  });
});

// ---- replacing, removing and re-choosing a file ----------------------------------------------------
const fileA = { name: "a.csv", size: 2048 };
const fileB = { name: "b.xlsx", size: 4096 };
const stepStates = (state) => trainSteps({ file: state.file, checking: state.checking, preview: state.preview, running: isTrainRunning(state), status: state.status }).map((x) => x.state);
const reasonOf = (state) => trainBlockReason({ file: state.file, preview: state.preview, checking: state.checking, running: isTrainRunning(state) });
const run = (...actions) => actions.reduce((st, a) => trainReducer(st, a), initialTrain);
const finishedTraining = () => run(
  { type: "choose", token: 1, file: fileA }, { type: "previewDone", token: 1, preview: { ...samplePreview, mappings: [] } },
  { type: "startTrain" }, { type: "started", id: "j1" }, { type: "polled", status: { status: "done", progress: "Done", warnings: ["w"] } },
  { type: "reportLoaded", report: sampleReport(true) }, { type: "error", error: { message: "old error" } },
);

describe("Replacing the file", () => {
  it("clears the preview, messages, report and error, and starts again from step 1", () => {
    const before = finishedTraining();
    expect(before.report).not.toBeNull();
    const after = trainReducer(before, { type: "choose", token: 2, file: fileB });
    expect(after).toMatchObject({ file: fileB, preview: null, report: null, error: null, fileError: null, status: null, trainId: null, checking: true });
    expect(stepStates(after)).toEqual(["done", "active", "pending"]);       // the new file is being checked
    expect(reasonOf(after)).toBe("Checking the file…");                      // Train stays disabled until it passes
  });
  it("drops an old file's preview when it arrives after a new file was chosen", () => {
    const s = run({ type: "choose", token: 1, file: fileA }, { type: "choose", token: 2, file: fileB },
      { type: "previewDone", token: 1, preview: samplePreview });             // late answer for A
    expect(s.preview).toBeNull();
    expect(s.checking).toBe(true);
    expect(trainReducer(s, { type: "previewDone", token: 2, preview: samplePreview }).preview).toBe(samplePreview);
  });
  it("clears the error of the old file when a file that is not csv or xlsx is rejected", () => {
    const s = run({ type: "choose", token: 1, file: fileA }, { type: "previewFailed", token: 1, error: { message: "boom" } },
      { type: "reject", token: 2, error: { message: "Only .csv and .xlsx files are accepted." } });
    expect(s.file).toBeNull();
    expect(s.fileError.message).toMatch(/Only \.csv/);
    expect(stepStates(s)).toEqual(["active", "pending", "pending"]);
  });
});

describe("Removing the file", () => {
  it("returns to step 1 and disables Train", () => {
    const s = trainReducer(finishedTraining(), { type: "remove", token: 3 });
    expect(s).toMatchObject({ file: null, preview: null, report: null, error: null, status: null, trainId: null });
    expect(stepStates(s)).toEqual(["active", "pending", "pending"]);
    expect(reasonOf(s)).toBe("Choose a CSV or XLSX file");
  });
  it("also disables Train after a valid file is removed", () => {
    const valid = run({ type: "choose", token: 1, file: fileA }, { type: "previewDone", token: 1, preview: samplePreview });
    expect(reasonOf(valid)).toBe("");
    expect(reasonOf(trainReducer(valid, { type: "remove", token: 2 }))).toBe("Choose a CSV or XLSX file");
  });
  it("cannot be used while a training runs", () => {
    const running = run({ type: "choose", token: 1, file: fileA }, { type: "previewDone", token: 1, preview: samplePreview },
      { type: "startTrain" }, { type: "started", id: "j" });
    expect(isTrainRunning(running)).toBe(true);
    expect(trainReducer(running, { type: "remove", token: 2 })).toBe(running);
    expect(trainReducer(running, { type: "choose", token: 2, file: fileB })).toBe(running);
  });
});

describe("After a finished training", () => {
  it("a new file can be chosen straight away", () => {
    const done = finishedTraining();
    expect(isTrainRunning(done)).toBe(false);
    const next = trainReducer(done, { type: "choose", token: 5, file: fileB });
    expect(next.file).toBe(fileB);
    expect(isTrainRunning(next)).toBe(false);
    const ready = trainReducer(next, { type: "previewDone", token: 5, preview: samplePreview });
    expect(reasonOf(ready)).toBe("");                                        // Train is enabled again
    expect(stepStates(ready)).toEqual(["done", "done", "active"]);
  });
  it("the steps of the finished training are all done", () => {
    expect(stepStates(finishedTraining())).toEqual(["done", "done", "done"]);
  });
  it("a failed start leaves the card usable", () => {
    const s = run({ type: "choose", token: 1, file: fileA }, { type: "previewDone", token: 1, preview: samplePreview },
      { type: "startTrain" }, { type: "startFailed", error: { message: "409" } });
    expect(isTrainRunning(s)).toBe(false);
    expect(reasonOf(s)).toBe("");
  });
});

describe("The chosen file in the drop zone", () => {
  it("shows its name, size, a remove button and 'Choose a different file'", () => {
    const m = html(<TrainFile file={fileA} running={false} onChoose={() => {}} onRemove={() => {}} />);
    expect(m).toContain("a.csv");
    expect(m).toContain("2 KB");
    expect(m).toContain('aria-label="Remove a.csv"');
    expect(m).toContain("Choose a different file");
    expect(m).toContain('class="drop"');                                     // the drop zone stays visible
  });
  it("shows 'Choose file' and the drop text when there is no file", () => {
    const m = html(<TrainFile file={null} running={false} onChoose={() => {}} onRemove={() => {}} />);
    expect(m).toContain("Drop a .csv or .xlsx file here");
    expect(m).toContain(">Choose file<");
    expect(m).not.toContain("Remove");
  });
  it("disables the buttons while a training runs", () => {
    const m = html(<TrainFile file={fileA} running onChoose={() => {}} onRemove={() => {}} />);
    expect((m.match(/<button[^>]*disabled/g) || []).length).toBe(2);
  });
  it("lists the accepted files under the picker", () => {
    expect(HELP_TEXT).toBe("Use the Download CSV from the Results panel, after adding a concentration_ppm column. Also accepted: the batch_features export.");
    expect(html(<TrainFile file={null} running={false} onChoose={() => {}} onRemove={() => {}} />)).toContain(HELP_TEXT);
    expect(html(<TrainCard onTrained={() => {}} />)).toContain("Also accepted: the batch_features export.");
  });
  it("shows the column mapping in the preview", () => {
    const m = html(<PreviewPanel preview={{ ...samplePreview, mappings: ["Using trim_R as R", "Using image as file_name"] }} />);
    expect(m).toContain("Column mapping");
    expect(m).toContain("Using trim_R as R");
    expect(html(<PreviewPanel preview={{ ...samplePreview, mappings: [] }} />)).not.toContain("Column mapping");
  });
});
