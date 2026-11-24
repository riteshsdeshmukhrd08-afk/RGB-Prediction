// Every call to the backend lives in this file.

const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
export const MAX_FILE_MB = Number(import.meta.env.VITE_MAX_FILE_MB) || 20;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// The backend sends {"detail": "text"} (or a list of validation problems). Turn it into one string.
function detailText(body, fallback) {
  const d = body && body.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  if (d && typeof d === "object") return d.message || JSON.stringify(d);
  return fallback;
}

export const TOO_LARGE_MESSAGE = "Image too large for upload (after resizing). Try a smaller image.";
const HOST_BODY_LIMIT = 4.5 * 1024 * 1024; // Vercel's request body limit

// One attempt. Throws ApiError; `network: true` marks a failure of the connection itself (or a timeout).
// bodySize: bytes of the request body, if known. A 413 produced by the host itself carries no CORS headers,
// so the browser hides it and fetch() throws; a body over the limit is then reported as "too large".
async function attempt(path, { signal, timeoutMs = 0, bodySize = 0, imageUpload = false, ...options }) {
  const ctl = new AbortController();
  let timedOut = false;
  const timer = timeoutMs ? setTimeout(() => { timedOut = true; ctl.abort(); }, timeoutMs) : null;
  const onAbort = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  else signal?.addEventListener("abort", onAbort);
  try {
    let res;
    try {
      res = await fetch(BASE + path, { signal: ctl.signal, ...options });
    } catch (e) {
      if (e.name === "AbortError" && !timedOut) throw e;          // the caller cancelled
      let err;
      if (timedOut) err = new ApiError("The backend did not answer in time.", 0);
      else if (imageUpload && bodySize >= HOST_BODY_LIMIT) throw new ApiError(TOO_LARGE_MESSAGE, 413);
      else err = new ApiError("The backend is not reachable. Is it running?", 0);
      err.network = true;
      throw err;
    }
    if (!res.ok) {
      let text = "";
      let body = null;
      try {
        text = await res.text();
        body = JSON.parse(text);
      } catch {
        /* not JSON */
      }
      let message = detailText(body, "");
      if (!message) {
        // The dev server answers with an empty body when the backend is down; a crashed backend sends plain text.
        message = text.trim()
          ? "The server failed without giving details. Check the backend terminal."
          : "No answer from the backend. Is it running?";
      }
      if (imageUpload && res.status === 413) throw new ApiError(TOO_LARGE_MESSAGE, 413);
      throw new ApiError(message, res.status);
    }
    return res.status === 204 ? null : await res.json();
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

// retries: extra attempts after a NETWORK error or timeout only. Never after an HTTP answer (4xx, 413, 5xx).
async function request(path, { retries = 0, ...options } = {}) {
  for (let n = 0; ; n++) {
    try {
      return await attempt(path, options);
    } catch (e) {
      if (!e.network || n >= retries || options.signal?.aborted) throw e;
    }
  }
}

// items: [{ file, path }]  (path keeps the folder structure of a folder upload)
function formWith(items) {
  const form = new FormData();
  for (const it of items) form.append("files", it.file, it.path || it.file.name);
  return form;
}

const POLL_TIMEOUT_MS = 30_000;
export const UPLOAD_TIMEOUT_MS = 120_000;

export const getHealth = (signal) => request("/api/health", { signal, timeoutMs: POLL_TIMEOUT_MS });

// Prediction
// idempotencyKey: the same key on every attempt of the same file, so the server never makes two jobs for it.
export const createJob = (items, signal, idempotencyKey) =>
  request("/api/jobs", {
    method: "POST", body: formWith(items), signal, headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined, imageUpload: true, timeoutMs: UPLOAD_TIMEOUT_MS, retries: 1, bodySize: items.reduce((n, it) => n + it.file.size, 0),
  });
export const getJob = (id, signal) => request(`/api/jobs/${id}`, { signal, timeoutMs: POLL_TIMEOUT_MS });
export const getResults = (id, signal) => request(`/api/jobs/${id}/results`, { signal, timeoutMs: POLL_TIMEOUT_MS });
export const downloadUrl = (id, format) => `${BASE}/api/jobs/${id}/download?format=${format}`;

// The active concentration model: { model_type, model_name, features, expected_error_mg_L, trainable }
export const getModelInfo = (signal) => request("/api/model-info", { signal, timeoutMs: POLL_TIMEOUT_MS });
