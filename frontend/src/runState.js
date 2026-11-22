// The run as one state machine:  idle -> running -> done | error   (Run again: -> running).
// Every selected file has its own status: queued, resizing, uploading, processing, done, failed.
//   queued/resizing/uploading   in this browser
//   processing                  accepted by the server (a backend job exists), being measured
//   done / failed               finished; a done file is never uploaded again

const ACTIVE = ["queued", "resizing", "uploading", "processing"];
const KEEP = ["done", "processing", "uploading", "resizing"];      // Run leaves these alone

// The Idempotency-Key of a file: made once when the file is first queued, reused by every attempt and every
// later Run, so the server can recognise a repeated upload. (Not generated inside the reducer: it must stay pure.)
export function newKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const b = globalThis.crypto.getRandomValues(new Uint8Array(16));      // pages served over plain http
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// The keys for the files a Run sends: a file that has one keeps it, only a new file gets a new one.
export const keysFor = (ids, files) => Object.fromEntries(ids.map((id) => [id, files[id]?.key || newKey()]));

export const initialRun = { phase: "idle", uploading: false, files: {} };

// Why the Run button is disabled ("" means it can be clicked).
export function runBlockReason({ fileCount, jobStatus, sending, phase, pending }) {
  if (phase === "running") return "Running";
  if (sending) return "Uploading…";
  if (jobStatus === "queued" || jobStatus === "processing") return "A job is running";
  if (fileCount === 0) return "Select at least one file";
  if (pending === 0) return "Every file is already processed";
  return "";
}

// Ids of the files a Run would send now.
export const pendingIds = (items, files) => items.filter((it) => !KEEP.includes(files[it.id]?.status)).map((it) => it.id);

function settle(s) {
  if (s.phase !== "running" || s.uploading) return s;
  const all = Object.values(s.files);
  if (all.some((f) => ACTIVE.includes(f.status))) return s;
  return { ...s, phase: all.some((f) => f.status === "failed") ? "error" : "done" };
}

export function runReducer(s, a) {
  switch (a.type) {
    case "START": {
      if (s.phase === "running") return s;                       // extra clicks are ignored
      const files = { ...s.files };
      let n = 0;
      for (const id of a.ids) {
        if (KEEP.includes(files[id]?.status)) continue;
        files[id] = { status: "queued", key: files[id]?.key || a.keys?.[id] };   // failed files are tried again, same key
        n++;
      }
      return n ? { phase: "running", uploading: true, files } : s;
    }
    case "FILE":
      return settle({ ...s, files: { ...s.files, [a.id]: { ...s.files[a.id], ...a.patch } } });
    case "UPLOADS_DONE":
      return settle({ ...s, uploading: false });
    case "JOBS": {                                                // a.jobs: [{ id, status, error }] from polling
      let files = s.files;
      for (const [fid, f] of Object.entries(s.files)) {
        if (f.status !== "processing") continue;
        const j = a.jobs.find((x) => x.id === f.jobId);
        if (!j || (j.status !== "done" && j.status !== "failed")) continue;
        if (files === s.files) files = { ...s.files };
        // A job that FAILED is a finished answer: a new Run must make a new job, so its key is dropped.
        files[fid] = j.status === "done" ? { ...f, status: "done" } : { ...f, status: "failed", key: null, error: j.error || "The server could not measure this file" };
      }
      return files === s.files ? s : settle({ ...s, files });
    }
    case "RESET":
      return initialRun;
    default:
      return s;
  }
}

// { done, total } for the button label, counted over the files that are currently selected
export function progressOf(items, files) {
  let done = 0;
  let total = 0;
  for (const it of items) {
    const st = files[it.id]?.status;
    if (!st) continue;
    total++;
    if (st === "done" || st === "failed") done++;
  }
  return { done, total };
}
