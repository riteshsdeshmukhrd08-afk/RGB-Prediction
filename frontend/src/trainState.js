// Training file helpers (no React here, so they are easy to test).

export const isTableFile = (file) => /\.(csv|xlsx)$/i.test(file?.name || "");

// Why the Train button is disabled ("" means it can be clicked).
export function trainBlockReason({ file, preview, checking, running }) {
  if (running) return "A training is running";
  if (!file) return "Choose a CSV or XLSX file";
  if (checking) return "Checking the file…";
  if (!preview) return "The file could not be checked";
  if (!preview.valid) return "Fix the errors above";
  return "";
}

// The three numbered steps above the Train card: "pending", "active" or "done".
export function trainSteps({ file, checking, preview, running, status }) {
  const checked = !!preview && !checking;
  const trained = status?.status === "done";
  return [
    { n: 1, label: "Choose file", state: file ? "done" : "active" },
    { n: 2, label: "Check", state: !file ? "pending" : checked && preview.valid ? "done" : "active" },
    { n: 3, label: "Train", state: trained ? "done" : checked && preview.valid || running ? "active" : "pending" },
  ];
}

// Checks that passed, shown in green next to the errors (red) and warnings (amber).
export function passedChecks(preview) {
  if (!preview) return [];
  const passed = [];
  if (!preview.errors.some((e) => /Missing:/.test(e))) passed.push("All required columns found");
  if (preview.n_valid_rows > 0) passed.push(`${preview.n_valid_rows} valid row(s)`);
  if (preview.concentrations.length >= 2) passed.push(`${preview.concentrations.length} distinct concentrations`);
  if (preview.concentrations.length >= 4) passed.push("4 or more concentrations: the error can be validated");
  return passed;
}

// ---- The state of the Train card ------------------------------------------------------------------
// One reducer, so "replace the file", "remove the file" and "a late answer for an old file" are easy to test.
export const initialTrain = {
  token: 0,            // changes whenever the file changes; answers for an older token are ignored
  file: null, preview: null, checking: false, fileError: null,
  starting: false, trainId: null, status: null, report: null, error: null,
};

export const isTrainRunning = (s) => s.starting || s.status?.status === "queued" || s.status?.status === "running";

export function trainReducer(s, a) {
  switch (a.type) {
    case "choose":        // a new file replaces the old one and everything restarts from step 1
      return isTrainRunning(s) ? s : { ...initialTrain, token: a.token, file: a.file, checking: true };
    case "reject":        // a file that is not .csv or .xlsx
      return isTrainRunning(s) ? s : { ...initialTrain, token: a.token, fileError: a.error };
    case "remove":
      return isTrainRunning(s) ? s : { ...initialTrain, token: a.token };
    case "previewDone":
      return a.token !== s.token ? s : { ...s, checking: false, preview: a.preview };
    case "previewFailed":
      return a.token !== s.token ? s : { ...s, checking: false, fileError: a.error };
    case "startTrain":
      return { ...s, starting: true, report: null, status: null, trainId: null, error: null };
    case "started":
      return { ...s, starting: false, trainId: a.id, status: { status: "queued", progress: "Queued", warnings: [] } };
    case "startFailed":
      return { ...s, starting: false, error: a.error };
    case "polled":
      return { ...s, status: a.status, error: null };
    case "reportLoaded":
      return { ...s, report: a.report };
    case "error":
      return { ...s, error: a.error };
    default:
      return s;
  }
}
