import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { MAX_FILE_MB, createJob, getHealth, getJob, getModelInfo, getResults } from "./api.js";
import { initialRun, keysFor, pendingIds, progressOf, runBlockReason, runReducer } from "./runState.js";
import { uploadFiles } from "./uploader.js";
import { prepareImage } from "./resizeImage.js";
import { mergeJobs } from "./mergeJobs.js";
import { usePoll } from "./usePoll.js";
import Banner from "./components/Banner.jsx";
import TopBar from "./components/TopBar.jsx";
import InputCard from "./components/InputCard.jsx";
import ResultsCard from "./components/ResultsCard.jsx";
import ModelCards from "./components/ModelCards.jsx";

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [model, setModel] = useState(null);

  const [items, setItems] = useState([]);
  const [run, dispatch] = useReducer(runReducer, initialRun);   // idle -> running -> done | error, plus one status per file
  const [tooBig, setTooBig] = useState([]);
  const [skipped, setSkipped] = useState([]);
  const [error, setError] = useState(null);                     // problems of the polling (not of single files)
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const sendCtl = useRef(null);
  const runningRef = useRef(false);                             // closes the gap between a click and the next render
  const healthCtl = useRef(null);
  const modelCtl = useRef(null);

  // one backend job per uploaded file (each request must stay small)
  const jobIds = useMemo(() => [...new Set(Object.values(run.files).map((f) => f.jobId).filter(Boolean))], [run.files]);
  const jobId = jobIds.length ? jobIds.join(",") : null;

  // Is the backend (and its database) working? Checked when the page opens, and on "Check again".
  const refreshHealth = useCallback(async () => {
    healthCtl.current?.abort();
    const ctl = new AbortController();
    healthCtl.current = ctl;
    try {
      setHealth(await getHealth(ctl.signal));
      setHealthError(null);
    } catch (e) {
      if (e.name !== "AbortError") { setHealth(null); setHealthError(e); }
    }
  }, []);

  // The active model ({ model_type, model_name, features, expected_error_mg_L, trainable }), shown in the header.
  // The Train card is only shown for the linear model. Also called after a training.
  const refreshModel = useCallback(async () => {
    modelCtl.current?.abort();
    const ctl = new AbortController();
    modelCtl.current = ctl;
    try {
      setModel(await getModelInfo(ctl.signal));
    } catch (e) {
      if (e.name !== "AbortError") setModel(null);     // a network problem shows in the health banner
    }
  }, []);

  const refreshAll = useCallback(() => { refreshHealth(); refreshModel(); }, [refreshHealth, refreshModel]);

  useEffect(() => {
    refreshAll();
    return () => { healthCtl.current?.abort(); modelCtl.current?.abort(); sendCtl.current?.abort(); };
  }, [refreshAll]);

  useEffect(() => { if (run.phase !== "running") runningRef.current = false; }, [run.phase]);

  // progress and rows of the backend jobs
  usePoll(jobId, {
    fetcher: async (ids, signal) => {
      const parts = await Promise.all(ids.split(",").map(async (id) => {
        const [j, r] = await Promise.all([getJob(id, signal), getResults(id, signal)]);
        return { id, job: j, results: r.results };
      }));
      return mergeJobs(parts);
    },
    isDone: (d) => d.job.status === "done" || d.job.status === "failed",
    onData: (d) => {
      setJob(d.job); setResults(d.results); setSkipped(d.job.skipped || []); setError(null);
      dispatch({ type: "JOBS", jobs: d.jobs });
    },
    onError: (e) => setError(e),
  });

  function startRun() {
    if (runningRef.current) return;                              // extra clicks while running do nothing
    const maxBytes = MAX_FILE_MB * 1024 * 1024;
    const sendable = items.filter((it) => it.file.size <= maxBytes);
    setTooBig(items.filter((it) => it.file.size > maxBytes).map((it) => it.path));
    if (!sendable.length) { setError({ message: `Every file is over ${MAX_FILE_MB} MB.` }); return; }
    const ids = pendingIds(sendable, run.files);                 // files already sent or done are not sent again
    if (!ids.length) return;
    runningRef.current = true;
    setError(null);
    const keys = keysFor(ids, run.files);                        // a new file gets a new key, the others keep theirs
    dispatch({ type: "START", ids, keys });
    const ctl = new AbortController();
    sendCtl.current = ctl;
    uploadFiles({
      items: sendable.filter((it) => ids.includes(it.id)).map((it) => ({ ...it, key: keys[it.id] })),
      prepare: prepareImage,
      send: createJob,
      signal: ctl.signal,
      onUpdate: (id, patch) => dispatch({ type: "FILE", id, patch }),
    }).finally(() => { if (!ctl.signal.aborted) dispatch({ type: "UPLOADS_DONE" }); });
  }

  // Clear: stop every request in flight, forget every status and result
  function clear() {
    sendCtl.current?.abort();
    sendCtl.current = null;
    runningRef.current = false;
    dispatch({ type: "RESET" });
    setItems([]); setTooBig([]); setSkipped([]); setError(null); setJob(null); setResults([]);
  }

  const { done, total } = progressOf(items, run.files);
  const pending = pendingIds(items, run.files).length;
  const blockReason = runBlockReason({ fileCount: items.length, phase: run.phase, pending });
  const percent = total ? (100 * done) / total : 0;
  // while files are still being sent, the jobs made so far are not "the" job: keep the Results card on "processing"
  const shownJob = job && run.phase === "running" ? { ...job, status: "processing", total, processed: done } : job;

  const failedFiles = items.filter((it) => run.files[it.id]?.status === "failed");
  const fileError = failedFiles.length
    ? { message: `${failedFiles.length} file(s) failed: ` + failedFiles.slice(0, 3).map((it) => `${it.path}: ${run.files[it.id].error}`).join(" · ") + (failedFiles.length > 3 ? " …" : "") }
    : null;

  const names = new Map(items.map((it) => [it.id, it.path]));
  const files = Object.entries(run.files).filter(([, f]) => f.jobId)
    .map(([id, f]) => ({ id: f.jobId, name: names.get(Number(id)) || "(removed file)", status: f.status }));

  return (
    <div className="app">
      <div className="stage">
        <TopBar dbDown={health?.mongo === "error"} backendError={healthError} model={model} />
        <Banner health={health} healthError={healthError} onRecheck={refreshAll} />
        <main className="columns">
        <InputCard items={items} setItems={setItems} onRun={startRun} onClear={clear} blockReason={blockReason}
          phase={run.phase} statuses={run.files} done={done} total={total} percent={percent}
          skipped={skipped} tooBig={tooBig} error={error || fileError} />
        <ResultsCard jobId={jobId} job={shownJob} results={results} files={files} />
        </main>
      </div>
      <ModelCards model={model} onTrained={refreshModel} />
    </div>
  );
}
