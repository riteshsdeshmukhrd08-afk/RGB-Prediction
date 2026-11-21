// Why the Run button is disabled ("" means it can be clicked).
export function runBlockReason({ fileCount, jobStatus, sending }) {
  if (sending) return "Uploading…";
  if (jobStatus === "queued" || jobStatus === "processing") return "A job is running";
  if (fileCount === 0) return "Select at least one file";
  return "";
}
