// Combines the per-file backend jobs into the single job + rows the Results card shows.
const ACTIVE = new Set(["queued", "processing"]);

// One entry per photo: parts that carry the same idempotency key (or are the same job) count once.
function unique(parts) {
  const seen = new Set();
  return parts.filter((p) => {
    const k = p.job.idempotency_key || `job:${p.id}`;
    if (seen.has(k) || seen.has(`job:${p.id}`)) return false;
    seen.add(k);
    seen.add(`job:${p.id}`);
    return true;
  });
}

export function mergeJobs(all) {
  const parts = unique(all);
  const jobs = parts.map((p) => p.job);
  const active = jobs.filter((j) => ACTIVE.has(j.status));
  let status;
  if (active.length) status = active.every((j) => j.status === "queued") ? "queued" : "processing";
  else status = jobs.some((j) => j.status === "done") ? "done" : "failed";
  return {
    job: {
      status,
      total: jobs.reduce((n, j) => n + j.total, 0),
      processed: jobs.reduce((n, j) => n + j.processed, 0),
      error: jobs.find((j) => j.error)?.error || null,
      skipped: jobs.flatMap((j) => j.skipped || []),
    },
    results: parts.flatMap((p) => p.results),
    jobs: parts.map((p) => ({ id: p.id, status: p.job.status, error: p.job.error || null })),   // one per file
  };
}
