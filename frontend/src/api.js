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

// bodySize: bytes of the request body, if known. A 413 produced by the host itself carries no CORS headers,
// so the browser hides it and fetch() throws; a body over the limit is then reported as "too large".
async function request(path, { signal, bodySize = 0, imageUpload = false, ...options } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, { signal, ...options });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    if (imageUpload && bodySize >= HOST_BODY_LIMIT) throw new ApiError(TOO_LARGE_MESSAGE, 413);
    throw new ApiError("The backend is not reachable. Is it running?", 0);
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
  return res.status === 204 ? null : res.json();
}

// items: [{ file, path }]  (path keeps the folder structure of a folder upload)
function formWith(items) {
  const form = new FormData();
  for (const it of items) form.append("files", it.file, it.path || it.file.name);
  return form;
}

function oneFile(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  return form;
}

export const getHealth = (signal) => request("/api/health", { signal });

// Prediction
export const createJob = (items, signal) =>
  request("/api/jobs", {
    method: "POST", body: formWith(items), signal, imageUpload: true, bodySize: items.reduce((n, it) => n + it.file.size, 0),
  });
export const getJob = (id, signal) => request(`/api/jobs/${id}`, { signal });
export const getResults = (id, signal) => request(`/api/jobs/${id}/results`, { signal });
export const downloadUrl = (id, format) => `${BASE}/api/jobs/${id}/download?format=${format}`;

// Training from a CSV or XLSX of known values
export const previewTrainingFile = (file, signal) =>
  request("/api/train/preview", { method: "POST", body: oneFile(file), signal });
export const startTraining = (file, signal) =>
  request("/api/train", { method: "POST", body: oneFile(file), signal });
export const getTraining = (id, signal) => request(`/api/train/${id}`, { signal });
export const getCurrentModel = (signal) => request("/api/train/current", { signal });
export const getCurrentReport = (signal) => request("/api/train/current/report", { signal });
