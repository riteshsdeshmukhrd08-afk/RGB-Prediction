// Sends the files one at a time: resize -> upload -> next. A failed file never stops the others.
// Nothing is reported after `signal` is aborted (Clear), and no new request is started.
export const uploadPath = (item, file) => (file === item.file ? item.path : item.path.replace(/\.[^./\\]+$/, "") + ".jpg");

export async function uploadFiles({ items, prepare, send, signal, onUpdate }) {
  for (const it of items) {
    if (signal.aborted) return;
    onUpdate(it.id, { status: "resizing" });
    let file;
    try {
      file = await prepare(it.file);
    } catch (e) {
      if (signal.aborted) return;
      onUpdate(it.id, { status: "failed", error: e.message });
      continue;
    }
    if (signal.aborted) return;
    onUpdate(it.id, { status: "uploading" });
    try {
      const res = await send([{ file, path: uploadPath(it, file) }], signal, it.key);
      if (signal.aborted) return;
      onUpdate(it.id, { status: "processing", jobId: res.job_id, accepted: res.accepted, skipped: res.skipped || [] });
    } catch (e) {
      if (signal.aborted || e.name === "AbortError") return;
      onUpdate(it.id, { status: "failed", error: e.message });
    }
  }
}
