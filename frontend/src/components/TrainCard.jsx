import { useEffect, useReducer, useRef } from "react";
import { getCurrentReport, getTraining, previewTrainingFile, startTraining } from "../api.js";
import { initialTrain, isTableFile, isTrainRunning, passedChecks, trainBlockReason, trainReducer, trainSteps } from "../trainState.js";
import { usePoll } from "../usePoll.js";
import ErrorLine from "./ErrorLine.jsx";
import { PreviewPanel, ReportPanel, Steps, TrainButton, TrainFile, ValidationMessages } from "./TrainParts.jsx";

export default function TrainCard({ onTrained }) {
  const [s, dispatch] = useReducer(trainReducer, initialTrain);
  const token = useRef(0);          // matches state.token: a late answer for an older file is ignored
  const previewCtl = useRef(null);
  const startCtl = useRef(null);

  const running = isTrainRunning(s);
  const reason = trainBlockReason({ file: s.file, preview: s.preview, checking: s.checking, running });
  const steps = trainSteps({ file: s.file, checking: s.checking, preview: s.preview, running, status: s.status });

  usePoll(s.trainId, {
    fetcher: getTraining,
    isDone: (st) => st.status === "done" || st.status === "failed",
    onData: (st) => dispatch({ type: "polled", status: st }),
    onError: (e) => dispatch({ type: "error", error: e }),
  });

  // when the training succeeds: load its report and tell the page (so the top bar shows the new model)
  const trained = useRef(onTrained);
  trained.current = onTrained;
  useEffect(() => {
    if (s.status?.status !== "done") return undefined;
    const ctl = new AbortController();
    getCurrentReport(ctl.signal)
      .then((report) => dispatch({ type: "reportLoaded", report }))
      .catch((e) => e.name !== "AbortError" && dispatch({ type: "error", error: e }));
    trained.current?.();
    return () => ctl.abort();
  }, [s.status?.status, s.trainId]);

  useEffect(() => () => { previewCtl.current?.abort(); startCtl.current?.abort(); }, []);

  // A new file replaces the old one: everything (preview, messages, report, errors) starts again from step 1.
  async function choose(picked) {
    if (!picked || running) return;
    previewCtl.current?.abort();
    const mine = ++token.current;
    if (!isTableFile(picked)) {
      dispatch({ type: "reject", token: mine, error: { message: "Only .csv and .xlsx files are accepted." } });
      return;
    }
    dispatch({ type: "choose", token: mine, file: picked });
    previewCtl.current = new AbortController();
    try {
      dispatch({ type: "previewDone", token: mine, preview: await previewTrainingFile(picked, previewCtl.current.signal) });
    } catch (e) {
      if (e.name !== "AbortError") dispatch({ type: "previewFailed", token: mine, error: e });
    }
  }

  function remove() {
    if (running) return;
    previewCtl.current?.abort();
    dispatch({ type: "remove", token: ++token.current });
  }

  async function train() {
    dispatch({ type: "startTrain" });
    startCtl.current = new AbortController();
    try {
      const res = await startTraining(s.file, startCtl.current.signal);
      dispatch({ type: "started", id: res.job_id });
    } catch (e) {
      if (e.name !== "AbortError") dispatch({ type: "startFailed", error: e });
    }
  }

  return (
    <section className="card train-card">
      <h2>Train the concentration model</h2>
      <Steps steps={steps} />
      <div className="train-grid">
      <div className="train-left">
      <p className="muted">Upload a CSV or XLSX with the columns concentration_ppm, R, G, B (and optionally file_name), one row per photo or per concentration. At least 2 distinct concentrations are needed; with 4 or more the error is validated.</p>

      <TrainFile file={s.file} running={running} onChoose={choose} onRemove={remove} />

      <ErrorLine error={s.fileError} />
      {s.checking && <p className="muted">Checking the file…</p>}
      {s.preview && <ValidationMessages errors={s.preview.errors} warnings={s.preview.warnings} passed={passedChecks(s.preview)} />}

      <TrainButton reason={reason} running={running} onClick={train} />

      {running && (
        <div>
          <div className="bar indeterminate"><div /></div>
          <p className="muted">Status: {s.status?.status || "uploading"} · {s.status?.progress || "Uploading…"}</p>
        </div>
      )}
      {!s.preview && s.status?.warnings?.length > 0 && <ValidationMessages warnings={s.status.warnings} />}
      {s.status?.status === "failed" && <ErrorLine error={s.status.error} />}
      <ErrorLine error={s.error} />
      </div>
      {(s.report || s.preview) && (
        <div className="train-right">
          {s.report ? <ReportPanel report={s.report} /> : <PreviewPanel preview={s.preview} />}
        </div>
      )}
      </div>
    </section>
  );
}
