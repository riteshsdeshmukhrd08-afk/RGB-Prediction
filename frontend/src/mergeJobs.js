// Combines the per-file backend jobs into the single job + rows the Results card shows.
const ACTIVE = new Set(["queued", "processing"]);

export function mergeJobs(parts) {
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
  };
}
