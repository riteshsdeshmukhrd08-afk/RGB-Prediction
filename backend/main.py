"""
main.py - the FastAPI app: CORS + routes + the background job runner.

One upload, step by step:
  POST /api/jobs   save files to a temp folder -> create the job in Mongo -> reply {job_id}
                   then, in the background, WORKERS photos at a time:
                     (PDF page -> image) -> upload to Cloudinary -> measure + predict -> save the result
  GET  /api/jobs/{id}            progress (processed / total)
  GET  /api/jobs/{id}/results    the results as JSON
  GET  /api/jobs/{id}/download   the results as CSV or XLSX
"""

import logging
import re
import shutil
import statistics
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image
from pymongo import DESCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure, ServerSelectionTimeoutError
from starlette.background import BackgroundTask

import config
import db
import exports
import compare
import concentration
import ann_v1_1
import imaging
import measure_service
import pdf_utils
import storage
import training
from RGB_PREDICTION import qc_flags

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

imaging.register_plugins()      # HEIC/HEIF and AVIF readers, if installed

DB_UNREACHABLE = "Database unreachable: check MONGODB_URI and the MongoDB Atlas IP allowlist"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):
    db.init()
    db.ensure_indexes()
    storage.setup()
    concentration.load_model()      # the linear model is read here (it is optional)
    if config.MODEL_TYPE == "ann":
        ann_v1_1.load()             # the ANN file of the repository: checked against its pinned SHA-256, then loaded once
    if db.is_configured():
        try:
            training.fail_stale_jobs()
        except Exception as e:
            log.warning("Could not check old training jobs: %s", type(e).__name__)
    yield
    db.close()


app = FastAPI(title="RGB Measurement API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_methods=["*"],
    # Idempotency-Key is not a CORS-safelisted header, so the browser sends a preflight and needs it listed.
    allow_headers=["Accept", "Accept-Language", "Content-Language", "Content-Type", "Idempotency-Key"],
    expose_headers=["Content-Disposition"],
)


# ---------------------------------------------------------------------------
# Database errors become clear 503 answers instead of a bare "500 Internal Server Error"
# ---------------------------------------------------------------------------
async def database_unreachable(request: Request, exc: Exception):
    log.error("Database unreachable on %s %s", request.method, request.url.path, exc_info=exc)   # logged once
    return JSONResponse({"detail": DB_UNREACHABLE}, status_code=503)


async def database_error(request: Request, exc: OperationFailure):
    log.error("Database error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": f"Database error: {exc}"}, status_code=503)


# ServerSelectionTimeoutError is a kind of ConnectionFailure; both are listed to make the intent clear.
app.add_exception_handler(ServerSelectionTimeoutError, database_unreachable)
app.add_exception_handler(ConnectionFailure, database_unreachable)
app.add_exception_handler(OperationFailure, database_error)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def require_db():
    if not db.is_configured():
        raise HTTPException(503, "database is not configured (set MONGODB_URI in .env)")
    db.ensure_indexes()


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def parse_idempotency_key(value):
    """None when the header is absent; the key in lower case when it is a UUID; otherwise a 400."""
    if value is None:
        return None
    if len(value) > 64 or not UUID_RE.match(value):
        raise HTTPException(400, "Idempotency-Key must be a UUID (at most 64 characters).")
    return value.lower()


def existing_job_response(key):
    """The answer for a repeated request: the job that this key already created (HTTP 200), or None."""
    job = db.jobs().find_one({"idempotency_key": key})
    if job is None:
        return None
    return JSONResponse({"job_id": job["_id"], "status": job["status"],
                         "accepted": job.get("accepted", job["total"]), "skipped": job.get("skipped", []),
                         "duplicate": True}, status_code=200)


def sanitize_filename(name):
    """Keep only the last part of the path and drop control / path characters. Text starting
    with = + - @ is allowed here; it is escaped when the spreadsheet is written."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip()
    return name[:150] or "file"


def unique_name(name, used):
    """Two files with the same name in a folder upload: a.jpg, a_2.jpg, ..."""
    stem, ext = Path(name).stem, Path(name).suffix
    candidate, n = name, 1
    while candidate in used:
        n += 1
        candidate = f"{stem}_{n}{ext}"
    used.add(candidate)
    return candidate


def classify(path):
    """
    Decide what a file is by its CONTENT (never its extension).
    Returns ("image", 1) or ("pdf", page_count), or raises ValueError(reason) to skip it.
    """
    with open(path, "rb") as f:
        head = f.read(5)
    if head == b"%PDF-":
        return "pdf", pdf_utils.page_count(path)         # ValueError for password / too many pages
    try:
        imaging.image_format(path)                       # opens the header only: decoding problems later
    except Exception:                                    # become a failed row, not a skip
        raise ValueError("not an image that this server can open") from None
    return "image", 1


def save_and_classify(files, work_dir):
    """
    Copy uploads to uniquely named temp files (size is checked while copying).
    Returns (items, accepted, skipped). `items` has one entry per image or PDF page.
    """
    max_bytes = config.MAX_FILE_MB * 1024 * 1024
    used, items, skipped, accepted = set(), [], [], 0
    for upload in files:
        name = unique_name(sanitize_filename(upload.filename), used)
        dest = Path(work_dir) / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        size = 0
        with open(dest, "wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"'{name}' is larger than {config.MAX_FILE_MB} MB.")
                out.write(chunk)
        try:
            if size == 0:
                raise ValueError("empty file")
            kind = classify(dest)
        except ValueError as e:
            skipped.append({"name": name, "reason": str(e)})
            dest.unlink(missing_ok=True)
            continue
        accepted += 1
        if kind[0] == "pdf":
            for page in range(1, kind[1] + 1):
                items.append({"path": dest, "name": name, "kind": "pdf", "page": page})
        else:
            items.append({"path": dest, "name": name, "kind": "image", "page": None})
    for seq, item in enumerate(items):
        item["seq"] = seq                         # keeps the upload order in the results
    return items, accepted, skipped


def job_json(job):
    return {
        "job_id": job["_id"], "status": job["status"], "total": job["total"],
        "processed": job["processed"], "error": job.get("error"),
        "skipped": job.get("skipped", []), "idempotency_key": job.get("idempotency_key"),
    }


def get_job_or_404(job_id):
    require_db()
    job = db.jobs().find_one({"_id": job_id})
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------
def process_item(job_id, item, work_dir, model, model_type):
    """Handle ONE photo / PDF page: (render) -> upload -> measure -> save. Returns what the job needs, or None."""
    if db.jobs().count_documents({"_id": job_id}, limit=1) == 0:
        return None                                # the job was deleted meanwhile
    row, qc, url, warnings = None, None, None, []
    image_path = item["path"]
    try:
        if item["kind"] == "pdf":
            image_path = Path(work_dir) / f"{uuid.uuid4().hex}.png"
            pdf_utils.render_page(item["path"], item["page"] - 1, image_path)
        if storage.is_configured():
            try:
                url = storage.upload_file(image_path, job_id)
            except Exception as e:                 # a failed upload never stops the job
                warnings.append(f"image not stored: {str(e)[:200]}")
        row, qc = measure_service.analyze_image(image_path, model, model_type)
    except Exception as e:
        row, qc = measure_service.empty_row(), None
        row["error"] = f"{type(e).__name__}: {e}"
    finally:
        image_path.unlink(missing_ok=True)         # delete the temp image right away
        if item["kind"] == "image":
            item["path"].unlink(missing_ok=True)

    if warnings:
        row["warning"] = "; ".join(x for x in (row["warning"], *warnings) if x)
    doc = {"job_id": job_id, "seq": item["seq"], "file_name": item["name"], "page": item["page"],
           **row, "image_url": url}
    inserted = db.results().insert_one(doc).inserted_id        # saved as soon as it is done
    db.jobs().update_one({"_id": job_id}, {"$inc": {"processed": 1}})
    return {"id": inserted, "seq": item["seq"], "status": row["status"], "error": row["error"], "qc": qc}


def process_job(job_id, items, work_dir, model, model_type):
    """Runs in the background. WORKERS photos at a time (threads, never a process pool).
    `model` is the linear model the job started with (or None) and `model_type` is "ann" or "linear";
    a training that finishes meanwhile does not change them."""
    try:
        db.jobs().update_one({"_id": job_id}, {"$set": {"status": "processing"}})
        done = []
        with ThreadPoolExecutor(max_workers=config.WORKERS) as pool:
            futures = [pool.submit(process_item, job_id, it, work_dir, model, model_type) for it in items]
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception:                  # e.g. the database went away
                    log.exception("Photo failed unexpectedly in job %s", job_id)
                    continue
                if res is not None:
                    done.append(res)
        if db.jobs().count_documents({"_id": job_id}, limit=1) == 0:
            return

        # The roi_size flag compares each photo with the whole batch, so it is added now.
        usable = [d for d in done if d["qc"] is not None]
        widths = [d["qc"]["roi_w"] for d in usable]
        roi_w_median = statistics.median(widths) if len(widths) >= 3 else None
        for d in usable:
            db.results().update_one({"_id": d["id"]},
                                    {"$set": {"flags": qc_flags(d["qc"], roi_w_median)}})

        if any(d["status"] != "failed" for d in done):
            db.jobs().update_one({"_id": job_id}, {"$set": {"status": "done"}})
        else:
            first = min(done, key=lambda d: d["seq"])["error"] if done else "no photo could be processed"
            db.jobs().update_one({"_id": job_id}, {"$set": {"status": "failed", "error": first}})
    except Exception as e:
        log.exception("Job %s crashed", job_id)
        db.jobs().update_one({"_id": job_id}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {e}"}})
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)    # delete every temp file


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """Always answers 200; the fields say what is working."""
    if not db.is_configured():
        ok, reason = False, "MONGODB_URI is not set in backend/.env"
    else:
        ok, reason = db.ping()
    out = {"status": "ok", "mongo": "ok" if ok else "error", "cloudinary": storage.check(),
           "model_type": config.MODEL_TYPE}
    if config.MODEL_TYPE == "ann":
        out.update(ann_v1_1.status())                   # {"model": "loaded"} or {"model": "unavailable", "model_error": reason}
    else:
        out["model"] = "loaded" if concentration.is_ready() else "missing"
    if not ok:
        out["mongo_error"] = reason
    return out


@app.post("/api/jobs", status_code=202)
def create_job(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...),
               idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    key = parse_idempotency_key(idempotency_key)
    require_db()
    if key:                                             # a retry of a request that already created its job
        again = existing_job_response(key)
        if again is not None:
            return again
    model_type = config.MODEL_TYPE                      # the job keeps this choice
    if model_type == "ann" and not ann_v1_1.is_loaded():
        raise HTTPException(503, "The ANN model is not available: " + ann_v1_1.status()["model_error"])
    model, _ = concentration.current()                  # the linear model: none is fine, R, G, B are always returned
    if len(files) > config.MAX_FILES:
        raise HTTPException(400, f"Too many files: {len(files)} (limit is {config.MAX_FILES}).")

    job_id = uuid.uuid4().hex
    work_dir = Path(tempfile.mkdtemp(prefix=f"rgbjob_{job_id}_"))
    try:
        items, accepted, skipped = save_and_classify(files, work_dir)
        if not items:
            raise HTTPException(422, "No supported image or PDF files were found.")
        doc = {
            "_id": job_id, "status": "queued", "total": len(items), "processed": 0, "error": None,
            "accepted": accepted, "skipped": skipped,
            "created_at": datetime.now(timezone.utc),
        }
        if key:
            doc["idempotency_key"] = key                # the field is left out without a key (partial unique index)
        db.jobs().insert_one(doc)
    except DuplicateKeyError:                           # the same request arrived twice at once; the other one won
        shutil.rmtree(work_dir, ignore_errors=True)
        again = existing_job_response(key) if key else None
        if again is None:
            raise
        return again
    except BaseException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    background_tasks.add_task(process_job, job_id, items, work_dir, model, model_type)
    return {"job_id": job_id, "status": "queued", "accepted": accepted, "skipped": skipped}


@app.get("/api/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=200)):
    require_db()
    return [job_json(j) for j in db.jobs().find().sort("created_at", DESCENDING).limit(limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return job_json(get_job_or_404(job_id))


def load_results(job_id):
    rows = db.results().find({"job_id": job_id}, {"_id": 0, "seq": 0, "job_id": 0}).sort("seq", 1)
    return list(rows)


@app.get("/api/jobs/{job_id}/results")
def get_results(job_id: str):
    job = get_job_or_404(job_id)
    return {"job_id": job_id, "status": job["status"], "results": load_results(job_id)}


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, format: str = Query("csv", pattern="^(csv|xlsx)$")):
    get_job_or_404(job_id)
    tmp_dir = tempfile.mkdtemp(prefix="rgbexport_")
    try:
        path = exports.build_export(load_results(job_id), format, tmp_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    media = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, media_type=media, filename=f"rgb_results_{job_id[:8]}.{format}",
                        content_disposition_type="attachment",
                        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True))


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    get_job_or_404(job_id)
    try:
        storage.delete_job_folder(job_id)
    except Exception as e:                      # do not leave the job undeletable because Cloudinary is down
        log.warning("Cloudinary cleanup failed for job %s: %s", job_id, type(e).__name__)
    db.results().delete_many({"job_id": job_id})
    db.jobs().delete_one({"_id": job_id})
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------
@app.get("/api/formats")
def formats():
    """What this server can really open (asked from Pillow after the plugins are loaded)."""
    exts = imaging.supported_extensions()
    return {"extensions": exts + [".pdf"], "pdf": True,
            "heif": ".heic" in exts, "avif": ".avif" in exts}


# ---------------------------------------------------------------------------
# Training: fit the concentration model from a CSV or XLSX of known values
# ---------------------------------------------------------------------------
NO_MODEL = "No model: train one from a CSV or XLSX file."
ANN_FIXED = "The ANN model is fixed and cannot be trained here. Set MODEL_TYPE=linear to train the linear model."


def read_table_upload(upload):
    """Read the single uploaded table (size limit checked) and return (DataFrame, file name). 413 / 422 on problems."""
    max_bytes = config.MAX_FILE_MB * 1024 * 1024
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"The file is larger than {config.MAX_FILE_MB} MB.")
    name = sanitize_filename(upload.filename)
    try:
        return concentration.read_table(data, name), name
    except ValueError as e:
        raise HTTPException(422, str(e))


def train_job_json(job):
    return {"job_id": job["_id"], "status": job["status"], "progress": job.get("progress", ""),
            "warnings": job.get("warnings", []), "error": job.get("error")}


def get_train_job_or_404(job_id):
    require_db()
    job = db.train_jobs().find_one({"_id": job_id})
    if job is None:
        raise HTTPException(404, "Training job not found.")
    return job


@app.post("/api/train/preview")
def preview_training_file(file: UploadFile = File(...)):
    """Checks a training file without training: first rows, detected concentrations, errors and warnings."""
    df, _ = read_table_upload(file)
    summary, _ = concentration.inspect_table(df)
    return summary


@app.post("/api/train", status_code=202)
def start_training(file: UploadFile = File(...)):
    if config.MODEL_TYPE == "ann":
        raise HTTPException(409, ANN_FIXED)
    require_db()
    df, name = read_table_upload(file)
    summary, valid = concentration.inspect_table(df)
    if valid is None:
        raise HTTPException(422, " ".join(summary["errors"]))
    if not training.lock.acquire(blocking=False):
        raise HTTPException(409, "A training is already running. Wait for it to finish.")
    job_id = uuid.uuid4().hex
    try:
        db.train_jobs().insert_one({
            "_id": job_id, "status": "queued", "progress": "Queued", "warnings": summary["warnings"],
            "error": None, "created_at": datetime.now(timezone.utc),
        })
        training.start(job_id, valid, name)               # the thread releases the lock when it ends
    except BaseException:
        training.lock.release()
        raise
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/train/current")
def current_model():
    """Details of the loaded model; 404 if there is none."""
    model, version = concentration.current()
    if model is None:
        raise HTTPException(404, NO_MODEL)
    keys = ("features", "intercept", "coefficients", "typical_error_ppm", "validated", "validation", "n_rows",
            "n_concentrations", "training_range", "source_file", "trained_at")
    return {"model_version": version, **{k: model.get(k) for k in keys}}


@app.get("/api/train/current/report")
def current_model_report():
    """The full report of the loaded model, including the table of validation errors."""
    model, version = concentration.current()
    if model is None:
        raise HTTPException(404, NO_MODEL)
    return {"model_version": version, **model}


@app.get("/api/train/{job_id}")
def get_training(job_id: str):
    return train_job_json(get_train_job_or_404(job_id))


# ---------------------------------------------------------------------------
# Which model is active, and the comparison of the two models (neither is changed by it)
# ---------------------------------------------------------------------------
@app.get("/api/model-info")
def model_info():
    """The active model: model_type, model_name, features, expected_error_mg_L, nominal range, training_max and trainable."""
    if config.MODEL_TYPE == "ann":
        try:
            return ann_v1_1.info()
        except ann_v1_1.ModelUnavailable as e:
            raise HTTPException(503, f"The ANN model is not available: {e}")
    model, version = concentration.current()
    return {"model_type": "linear", "model_name": "Linear model", "model_version": version,
            "features": list(model["features"]) if model else [],
            "expected_error_mg_L": model["typical_error_ppm"] if model else None, "trainable": True,
            "loaded": model is not None}


@app.post("/api/compare")
def compare_models(file: UploadFile = File(...)):
    """Known concentrations (CSV or XLSX with concentration_ppm, R, G) against the ANN and the linear model."""
    df, _ = read_table_upload(file)
    result, errors = compare.compare_table(df)
    if errors:
        raise HTTPException(422, " ".join(errors))
    return result
