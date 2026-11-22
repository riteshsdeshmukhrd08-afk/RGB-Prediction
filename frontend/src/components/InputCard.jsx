import { useEffect, useRef, useState } from "react";
import { canPreview, formatSize, itemFromFile, itemsFromDrop } from "../files.js";
import { MAX_FILE_MB } from "../api.js";
import CameraModal from "./CameraModal.jsx";
import ErrorLine from "./ErrorLine.jsx";
import { CloseIcon, UploadIcon } from "./Icons.jsx";

const PREVIEW_LIMIT = 48; // thumbnails are made for the first photos only, to keep memory low

const STATUS_LABEL = { queued: "Queued", resizing: "Resizing", uploading: "Uploading", processing: "Measuring", done: "Done", failed: "Failed" };

export default function InputCard({ items, setItems, onRun, onClear, blockReason, phase = "idle", statuses = {}, done = 0, total = 0,
  percent = 0, skipped, tooBig, error }) {
  const running = phase === "running";
  const filesRef = useRef(null);
  const folderRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [camera, setCamera] = useState(false);
  const [urls, setUrls] = useState({});

  // thumbnails: create object URLs, and release them when the list changes or the page closes
  useEffect(() => {
    const made = [];
    const map = {};
    items.slice(0, PREVIEW_LIMIT).forEach((it, i) => {
      if (canPreview(it.file)) {
        const u = URL.createObjectURL(it.file);
        made.push(u);
        map[i] = u;
      }
    });
    setUrls(map);
    return () => made.forEach((u) => URL.revokeObjectURL(u));
  }, [items]);

  const add = (picked) => setItems((old) => [...old, ...picked]);
  const remove = (index) => setItems((old) => old.filter((_, i) => i !== index));

  async function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    add(await itemsFromDrop(e.dataTransfer));
  }

  function pick(e) {
    add([...e.target.files].map(itemFromFile));
    e.target.value = ""; // allows picking the same files again
  }

  return (
    <section className="card input-card">
      <h2>Input</h2>
      <div
        className={"drop" + (dragging ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <UploadIcon className="drop-icon" />
        <p>Drop images, PDFs or a folder here</p>
        <div className="row">
          <button onClick={() => filesRef.current.click()}>Choose images</button>
          <button onClick={() => folderRef.current.click()}>Choose folder</button>
          <button onClick={() => setCamera(true)}>Take photo</button>
        </div>
        <input ref={filesRef} type="file" multiple hidden onChange={pick} />
        <input ref={folderRef} type="file" multiple hidden webkitdirectory="" directory="" onChange={pick} />
      </div>

      {camera && (
        <CameraModal
          onCapture={(file) => { add([itemFromFile(file)]); setCamera(false); }}
          onClose={() => setCamera(false)}
        />
      )}

      {items.length > 0 && (
        <div className="file-area">
          <div className="row spread">
            <strong>{items.length} file(s) selected</strong>
            <button className="link" onClick={onClear || (() => setItems([]))}>Clear</button>
          </div>
          <ul className="files">
            {items.slice(0, 200).map((it, i) => (
              <li key={i + it.path}>
                {urls[i] ? <img src={urls[i]} alt="" /> : <span className="thumb-label">{(it.file.name.split(".").pop() || "file").slice(0, 5)}</span>}
                <span className="name mono" title={it.path}>{it.path}</span>
                {statuses[it.id] && (
                  <span className={"fstatus fs-" + statuses[it.id].status} title={statuses[it.id].error || undefined}>
                    {STATUS_LABEL[statuses[it.id].status]}
                  </span>
                )}
                <span className="size mono">{formatSize(it.file.size)}</span>
                <button className="remove" onClick={() => remove(i)} aria-label={`Remove ${it.file.name}`} title="Remove">
                  <CloseIcon />
                </button>
              </li>
            ))}
          </ul>
          {items.length > 200 && <p className="muted">…and {items.length - 200} more</p>}
        </div>
      )}

      <div className="notes">
      {tooBig.length > 0 && (
        <p className="warn">Not sent (over {MAX_FILE_MB} MB): {tooBig.slice(0, 5).join(", ")}{tooBig.length > 5 ? ` and ${tooBig.length - 5} more` : ""}</p>
      )}
      {skipped.length > 0 && (
        <details open className="warn">
          <summary>{skipped.length} file(s) skipped by the server</summary>
          <ul>{skipped.map((s, i) => <li key={i}>{s.name}: {s.reason}</li>)}</ul>
        </details>
      )}
      <ErrorLine error={error} />
      </div>

      <div className="run-area">
        <div className="progress-slot">
          {running && (
            <div className="bar thin" role="progressbar" aria-label="Progress" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${percent}%` }} />
            </div>
          )}
        </div>
        <button className="primary run block" onClick={onRun} disabled={!!blockReason} aria-busy={running}>
          {running ? `Running ${done} / ${total}` : "Run"}
        </button>
        {blockReason && !running && <p className="muted reason" data-testid="run-reason">{blockReason}</p>}
      </div>
    </section>
  );
}
