import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup as html } from "react-dom/server";
import InputCard from "./components/InputCard.jsx";
import ResultsCard from "./components/ResultsCard.jsx";
import { createJob } from "./api.js";
import { csvFromResults } from "./csvExport.js";
import { mergeJobs } from "./mergeJobs.js";
import { initialRun, pendingIds, progressOf, runBlockReason, runReducer } from "./runState.js";
import { uploadFiles } from "./uploader.js";

const mkItems = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1, path: `p${i + 1}.jpg`, file: { name: `p${i + 1}.jpg`, size: 1000, type: "image/jpeg" } }));
const reduce = (state, ...actions) => actions.reduce(runReducer, state);

describe("Run while running", () => {
  it("is disabled, shows one status on the button and no second status below it", () => {
    const items = mkItems(24);
    const m = html(<InputCard items={items} setItems={() => {}} onRun={() => {}} onClear={() => {}} blockReason={runBlockReason({ fileCount: 24, phase: "running" })}
      phase="running" statuses={{ 1: { status: "done" }, 2: { status: "uploading" } }} done={5} total={24} percent={20} skipped={[]} tooBig={[]} error={null} />);
    expect(m).toMatch(/<button[^>]*class="primary run block"[^>]*disabled=""|<button[^>]*disabled=""[^>]*class="primary run block"/);
    expect(m).toContain("Running 5 / 24");
    expect(m).not.toContain("Uploading…");
    expect(m).not.toContain('data-testid="run-reason"');          // nothing repeated under the button
    expect(m).toContain('class="progress-slot"');
    expect(m).toContain("Uploading</span>");                       // the per-file chip, not a second headline
  });
  it("is enabled again when idle", () => {
    const m = html(<InputCard items={mkItems(2)} setItems={() => {}} onRun={() => {}} onClear={() => {}} blockReason="" skipped={[]} tooBig={[]} error={null} />);
    expect(m).not.toMatch(/class="primary run block"[^>]*disabled/);
    expect(m).toContain(">Run<");
  });
  it("ignores a second START while running, and never re-sends done or sent files", () => {
    const items = mkItems(3);
    const s1 = runReducer(initialRun, { type: "START", ids: [1, 2, 3] });
    expect(s1.phase).toBe("running");
    expect(runReducer(s1, { type: "START", ids: [1, 2, 3] })).toBe(s1);
    let s = reduce(s1, { type: "FILE", id: 1, patch: { status: "processing", jobId: "j1" } }, { type: "FILE", id: 2, patch: { status: "failed", error: "x" } },
      { type: "FILE", id: 3, patch: { status: "processing", jobId: "j3" } }, { type: "UPLOADS_DONE" });
    expect(s.phase).toBe("running");                                // jobs still being measured
    s = runReducer(s, { type: "JOBS", jobs: [{ id: "j1", status: "done" }, { id: "j3", status: "done" }] });
    expect(s.phase).toBe("error");                                  // one file failed
    expect(pendingIds(items, s.files)).toEqual([2]);                // only the failed file is tried again
    expect(runBlockReason({ fileCount: 3, phase: s.phase, pending: 1 })).toBe("");
    expect(progressOf(items, s.files)).toEqual({ done: 3, total: 3 });
  });
});

describe("uploadFiles", () => {
  it("a failed file does not stop the others", async () => {
    const items = mkItems(5);
    const updates = [];
    const sent = [];
    await uploadFiles({
      items, signal: new AbortController().signal,
      prepare: async (f) => { if (f.name === "p2.jpg") throw new Error("HEIC"); return f; },
      send: async ([x]) => { if (x.path === "p4.jpg") throw new Error("server said no"); sent.push(x.path); return { job_id: "j" + x.path, accepted: 1 }; },
      onUpdate: (id, patch) => updates.push([id, patch.status]),
    });
    expect(sent).toEqual(["p1.jpg", "p3.jpg", "p5.jpg"]);
    const last = (id) => updates.filter((u) => u[0] === id).pop()[1];
    expect([1, 2, 3, 4, 5].map(last)).toEqual(["processing", "failed", "processing", "failed", "processing"]);
  });

  it("Clear (abort) cancels the request in flight, starts no new one and reports nothing afterwards", async () => {
    const ctl = new AbortController();
    const calls = [];
    const updates = [];
    const send = vi.fn((files, signal) => new Promise((resolve, reject) => {
      calls.push(signal);
      signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
    }));
    const p = uploadFiles({ items: mkItems(4), signal: ctl.signal, prepare: async (f) => f, send, onUpdate: (id, patch) => updates.push([id, patch.status]) });
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const before = updates.length;
    ctl.abort();
    await p;
    expect(calls[0].aborted).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
    expect(updates.length).toBe(before);                            // no "failed" written for the aborted file
    expect(runReducer(runReducer(initialRun, { type: "START", ids: [1] }), { type: "RESET" })).toBe(initialRun);
  });
});

describe("createJob: timeout and retry", () => {
  const file = new Blob(["x"]);
  Object.assign(file, { name: "a.jpg" });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("retries once after a network error, then succeeds", async () => {
    const f = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(new Response(JSON.stringify({ job_id: "j" }), { status: 202 }));
    vi.stubGlobal("fetch", f);
    await expect(createJob([{ file, path: "a.jpg" }])).resolves.toEqual({ job_id: "j" });
    expect(f).toHaveBeenCalledTimes(2);
  });
  it("gives up after one retry", async () => {
    const f = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", f);
    await expect(createJob([{ file, path: "a.jpg" }])).rejects.toMatchObject({ status: 0, message: expect.stringContaining("not reachable") });
    expect(f).toHaveBeenCalledTimes(2);
  });
  it.each([[413], [400], [422], [500]])("never retries an HTTP %i answer", async (status) => {
    const f = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ detail: "no" }), { status }));
    vi.stubGlobal("fetch", f);
    await expect(createJob([{ file, path: "a.jpg" }])).rejects.toMatchObject({ status });
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("shows the fixed message on 413", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Request Entity Too Large", { status: 413 })));
    await expect(createJob([{ file, path: "a.jpg" }])).rejects.toMatchObject({ message: "Image too large for upload (after resizing). Try a smaller image." });
  });
  it("times out a request that never answers, retries once, then fails", async () => {
    vi.useFakeTimers();
    const f = vi.fn((url, { signal }) => new Promise((_, reject) => signal.addEventListener("abort", () => reject(Object.assign(new Error("x"), { name: "AbortError" })))));
    vi.stubGlobal("fetch", f);
    const p = createJob([{ file, path: "a.jpg" }]).catch((e) => e);
    await vi.advanceTimersByTimeAsync(121_000);
    await vi.advanceTimersByTimeAsync(121_000);
    expect(await p).toMatchObject({ status: 0, message: expect.stringContaining("in time") });
    expect(f).toHaveBeenCalledTimes(2);
  });
  it("an abort from the caller is not retried", async () => {
    const ctl = new AbortController();
    const f = vi.fn((url, { signal }) => new Promise((_, reject) => signal.addEventListener("abort", () => reject(Object.assign(new Error("x"), { name: "AbortError" })))));
    vi.stubGlobal("fetch", f);
    const p = createJob([{ file, path: "a.jpg" }], ctl.signal).catch((e) => e);
    await vi.waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    ctl.abort();
    expect((await p).name).toBe("AbortError");
    expect(f).toHaveBeenCalledTimes(1);
  });
});

describe("mergeJobs and the combined results", () => {
  const part = (i, status = "done") => ({ id: "j" + i, job: { status, total: 1, processed: status === "done" ? 1 : 0, error: null, skipped: [] },
    results: [{ file_name: `p${i}.jpg`, page: null, status: "ok", R: 200 + i, G: 100, B: 50, flags: "", warning: "", error: "", image_url: null }] });

  it("merges 24 jobs", () => {
    const parts = Array.from({ length: 24 }, (_, i) => part(i + 1));
    const m = mergeJobs(parts);
    expect(m.job).toMatchObject({ status: "done", total: 24, processed: 24 });
    expect(m.results).toHaveLength(24);
    expect(m.results[0].file_name).toBe("p1.jpg");
    expect(m.results[23].file_name).toBe("p24.jpg");
    expect(m.jobs).toHaveLength(24);
    expect(mergeJobs([...parts.slice(0, 23), part(24, "processing")]).job).toMatchObject({ status: "processing", processed: 23 });
    expect(mergeJobs(parts.map((p) => part(1, "failed"))).job.status).toBe("failed");
  });
  it("builds one CSV with the server's columns and protects against formulas", () => {
    const rows = Array.from({ length: 24 }, (_, i) => part(i + 1).results[0]);
    rows[1] = { ...rows[1], file_name: "=cmd|x", warning: 'a "quoted", note' };
    const lines = csvFromResults(rows).trimEnd().split("\n");
    expect(lines).toHaveLength(25);
    expect(lines[0]).toBe("file_name,page,status,R,G,B,predicted_concentration_ppm,typical_error_ppm,flags,warning,error,image_url");
    expect(lines[1]).toBe("p1.jpg,,ok,201,100,50,,,,,,");
    expect(lines[2]).toContain("'=cmd|x");
    expect(lines[2]).toContain('"a ""quoted"", note"');
  });
  it("shows ONE download-all button and ONE collapsed list instead of 48 buttons", () => {
    const parts = Array.from({ length: 24 }, (_, i) => part(i + 1));
    const m = mergeJobs(parts);
    const files = m.jobs.map((j, i) => ({ id: j.id, name: `p${i + 1}.jpg`, status: "done" }));
    const out = html(<ResultsCard jobId={files.map((f) => f.id).join(",")} job={m.job} results={m.results} hasModel={false} files={files} />);
    expect(out.match(/Download all CSV/g)).toHaveLength(1);
    expect(out).toMatch(/<details class="per-file">/);               // closed by default: no "open" attribute
    expect(out.match(/format=csv/g)).toHaveLength(24);
    expect(out).not.toContain("Download CSV (file");
    expect(out).not.toContain("Download XLSX (file");
  });
});
