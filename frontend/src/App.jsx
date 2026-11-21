import { useCallback, useEffect, useRef, useState } from "react";
import { MAX_FILE_MB, createJob, getCurrentModel, getHealth, getJob, getResults } from "./api.js";
import { runBlockReason } from "./runState.js";
import { usePoll } from "./usePoll.js";
import Banner from "./components/Banner.jsx";
import TopBar from "./components/TopBar.jsx";
import InputCard from "./components/InputCard.jsx";
import ResultsCard from "./components/ResultsCard.jsx";
import TrainCard from "./components/TrainCard.jsx";

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [model, setModel] = useState(null);

  const [items, setItems] = useState([]);
  const [sending, setSending] = useState(false);
  const [tooBig, setTooBig] = useState([]);
  const [skipped, setSkipped] = useState([]);
  const [error, setError] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const sendCtl = useRef(null);
  const healthCtl = useRef(null);
  const modelCtl = useRef(null);

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

  // The loaded concentration model (null when there is none yet). Also called after a training.
  // It is not shown in the header; the Results table and the Train card use it.
  const refreshModel = useCallback(async () => {
    modelCtl.current?.abort();
    const ctl = new AbortController();
    modelCtl.current = ctl;
    try {
      setModel(await getCurrentModel(ctl.signal));
    } catch (e) {
      if (e.name !== "AbortError") setModel(null);     // 404 = no model; a network problem shows in the health banner
    }
  }, []);

  const refreshAll = useCallback(() => { refreshHealth(); refreshModel(); }, [refreshHealth, refreshModel]);

  useEffect(() => {
    refreshAll();
    return () => { healthCtl.current?.abort(); modelCtl.current?.abort(); sendCtl.current?.abort(); };
  }, [refreshAll]);

  // progress and rows of the running job
  usePoll(jobId, {
    fetcher: async (id, signal) => {
      const [j, r] = await Promise.all([getJob(id, signal), getResults(id, signal)]);
      return { job: j, results: r.results };
    },
    isDone: (d) => d.job.status === "done" || d.job.status === "failed",
    onData: (d) => { setJob(d.job); setResults(d.results); setSkipped(d.job.skipped || []); setError(null); },
    onError: (e) => setError(e),
  });

  async function run() {
    const maxBytes = MAX_FILE_MB * 1024 * 1024;
    const sendable = items.filter((it) => it.file.size <= maxBytes);
    setTooBig(items.filter((it) => it.file.size > maxBytes).map((it) => it.path));
    setError(null); setJob(null); setResults([]); setJobId(null); setSkipped([]);
    if (!sendable.length) { setError({ message: `Every file is over ${MAX_FILE_MB} MB.` }); return; }
    setSending(true);
    sendCtl.current?.abort();
    sendCtl.current = new AbortController();
    try {
      const res = await createJob(sendable, sendCtl.current.signal);
      setSkipped(res.skipped || []);
      setJob({ status: "queued", processed: 0, total: res.accepted });
      setJobId(res.job_id);
    } catch (e) {
      if (e.name !== "AbortError") setError(e);
    } finally {
      setSending(false);
    }
  }

  const blockReason = runBlockReason({ fileCount: items.length, jobStatus: job?.status, sending });
  const processing = job?.status === "queued" || job?.status === "processing";
  const activity = sending ? "Uploading" : processing ? "Processing" : "";
  const percent = processing && job.total ? (100 * job.processed) / job.total : null;

  return (
    <div className="app">
      <div className="stage">
        <TopBar dbDown={health?.mongo === "error"} backendError={healthError} />
        <Banner health={health} healthError={healthError} onRecheck={refreshAll} />
        <main className="columns">
        <InputCard items={items} setItems={setItems} onRun={run} blockReason={blockReason} sending={sending}
          activity={activity} percent={percent} skipped={skipped} tooBig={tooBig} error={error} />
        <ResultsCard jobId={jobId} job={job} results={results} hasModel={!!model} />
        </main>
      </div>
      <TrainCard onTrained={refreshModel} />
    </div>
  );
}
