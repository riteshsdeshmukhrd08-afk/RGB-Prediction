// Helpers for picking files and folders. Nothing is filtered by type: the backend decides.

let nextId = 1;
export const newId = () => nextId++;       // a stable id per selected file; run state is kept by id
export const itemFromFile = (file) => ({ id: newId(), file, path: file.webkitRelativePath || file.name });

// Browsers can only preview some image types; for the others we show a plain label.
export const canPreview = (file) => /^image\/(png|jpe?g|webp|gif|bmp|avif|svg\+xml)$/i.test(file.type);

export function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

// Files and folders dropped on the page. Folders are read recursively so their paths are kept.
export async function itemsFromDrop(dataTransfer) {
  const entries = [...(dataTransfer.items || [])]
    .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) return [...dataTransfer.files].map(itemFromFile);

  const out = [];
  async function walk(entry, prefix) {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      out.push({ id: newId(), file, path: prefix + entry.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        for (const child of batch) await walk(child, prefix + entry.name + "/");
      } while (batch.length);
    }
  }
  for (const e of entries) await walk(e, "");
  return out;
}
