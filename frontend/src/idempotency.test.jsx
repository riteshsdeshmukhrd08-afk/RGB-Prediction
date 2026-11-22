import { afterEach, describe, expect, it, vi } from "vitest";
import { createJob } from "./api.js";
import { mergeJobs } from "./mergeJobs.js";
import { initialRun, keysFor, runReducer } from "./runState.js";
import { uploadFiles } from "./uploader.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const blob = Object.assign(new Blob(["x"]), { name: "a.jpg" });
const item = (id) => ({ id, path: `p${id}.jpg`, file: blob });

// What App.startRun does: keys -> START -> uploadFiles with the key on each item
async function doRun(state, ids, send) {
  const keys = keysFor(ids, state.files);
  let s = runReducer(state, { type: "START", ids, keys });
  await uploadFiles({ items: ids.map((id) => ({ ...item(id), key: keys[id] })), prepare: async (f) => f, send, signal: new AbortController().signal,
    onUpdate: (id, patch) => { s = runReducer(s, { type: "FILE", id, patch }); } });
  return runReducer(s, { type: "UPLOADS_DONE" });
}

describe("Idempotency-Key on the client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the key as a header, and the SAME key again on a timeout/network retry", async () => {
    const seen = [];
    vi.stubGlobal("fetch", vi.fn(async (url, opts) => {
      seen.push(opts.headers["Idempotency-Key"]);
      if (seen.length === 1) throw new TypeError("Failed to fetch");           // the response was lost
      return new Response(JSON.stringify({ job_id: "j1" }), { status: 202 });
    }));
    await createJob([{ file: blob, path: "a.jpg" }], undefined, "11111111-1111-4111-8111-111111111111");
    expect(seen).toEqual(["11111111-1111-4111-8111-111111111111", "11111111-1111-4111-8111-111111111111"]);
  });

  it("sends no header when there is no key", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 202 }));
    vi.stubGlobal("fetch", f);
    await createJob([{ file: blob, path: "a.jpg" }]);
    expect(f.mock.calls[0][1].headers).toBeUndefined();
  });

  it("a later Run re-sends a failed file with the same key; a done file is not sent at all", async () => {
    const keysSent = { 1: [], 2: [] };
    let fail = true;
    const send = async ([x], signal, key) => {
      const id = Number(x.path[1]);
      keysSent[id].push(key);
      if (id === 1 && fail) throw Object.assign(new Error("not reachable"), { network: true, status: 0 });
      return { job_id: "j" + id, accepted: 1 };
    };
    let s = await doRun(initialRun, [1, 2], send);
    expect(s.files[1].status).toBe("failed");
    expect(s.files[1].key).toBe(keysSent[1][0]);                     // the key survives the failure
    s = runReducer(s, { type: "JOBS", jobs: [{ id: "j2", status: "done" }] });
    fail = false;
    s = await doRun(s, [1], send);                                   // the next Run only has file 1 to do (2 is done)
    expect(keysSent[1]).toHaveLength(2);
    expect(keysSent[1][1]).toBe(keysSent[1][0]);
    expect(keysSent[2]).toHaveLength(1);
    expect(keysSent[1][0]).toMatch(UUID);
  });

  it("a new file gets a new key, and every file its own", () => {
    const first = keysFor([1, 2], {});
    expect(first[1]).toMatch(UUID);
    expect(first[1]).not.toBe(first[2]);
    const files = { 1: { status: "failed", key: first[1] } };
    const next = keysFor([1, 3], files);
    expect(next[1]).toBe(first[1]);                                   // same file, same key
    expect(next[3]).toMatch(UUID);
    expect([first[1], first[2], next[3]]).toHaveLength(new Set([first[1], first[2], next[3]]).size);
  });

  it("Clear removes the keys; a job that failed on the server gets a new key on the next Run", () => {
    let s = runReducer(initialRun, { type: "START", ids: [1], keys: { 1: "k1" } });
    expect(s.files[1].key).toBe("k1");
    s = runReducer(s, { type: "FILE", id: 1, patch: { status: "processing", jobId: "j1" } });
    expect(s.files[1].key).toBe("k1");
    const failed = runReducer(s, { type: "JOBS", jobs: [{ id: "j1", status: "failed", error: "no tube" }] });
    expect(failed.files[1].key).toBeNull();
    expect(keysFor([1], failed.files)[1]).not.toBe("k1");
    expect(runReducer(s, { type: "RESET" })).toBe(initialRun);
  });
});

describe("a dropped response never makes two jobs (simulated server with the backend's rule)", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("the server creates the job, the response is lost, the retry gets the same job", async () => {
    const jobs = new Map();                                            // key -> job, like the unique index
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url, opts) => {
      calls++;
      const key = opts.headers["Idempotency-Key"];
      const created = !jobs.has(key);
      if (created) jobs.set(key, { job_id: "job" + (jobs.size + 1) });
      if (calls === 1) throw new TypeError("Failed to fetch");         // created, but the answer never arrives
      return new Response(JSON.stringify({ ...jobs.get(key), accepted: 1 }), { status: created ? 202 : 200 });
    }));
    const s = await doRun(initialRun, [1], (items, signal, key) => createJob(items, signal, key));
    expect(calls).toBe(2);
    expect(jobs.size).toBe(1);
    expect(s.files[1]).toMatchObject({ status: "processing", jobId: "job1" });
  });
});

describe("mergeJobs de-duplicates", () => {
  const part = (id, key, name = "a.jpg") => ({ id, job: { status: "done", total: 1, processed: 1, error: null, skipped: [], idempotency_key: key },
    results: [{ file_name: name, status: "ok", R: 1, G: 2, B: 3 }] });

  it("counts a job once when the same job is returned twice", () => {
    const m = mergeJobs([part("j1", "k1"), part("j2", "k2", "b.jpg"), part("j1", "k1")]);
    expect(m.results.map((r) => r.file_name)).toEqual(["a.jpg", "b.jpg"]);
    expect(m.job).toMatchObject({ total: 2, processed: 2 });
    expect(m.jobs.map((j) => j.id)).toEqual(["j1", "j2"]);
  });
  it("counts one photo once when two job ids carry the same key", () => {
    const m = mergeJobs([part("j1", "k1"), part("j9", "k1")]);
    expect(m.results).toHaveLength(1);
    expect(m.jobs).toHaveLength(1);
  });
  it("keeps jobs without a key apart (older jobs)", () => {
    expect(mergeJobs([part("j1", null), part("j2", null)]).results).toHaveLength(2);
    expect(mergeJobs([part("j1", undefined), part("j1", undefined)]).results).toHaveLength(1);
  });
});
