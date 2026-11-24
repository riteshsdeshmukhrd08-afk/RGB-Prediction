# RGB Measurement and Concentration – Backend (FastAPI)

Upload photos or PDFs of vials. For each photo the server measures R, G and B (with `RGB_PREDICTION.py`) and a
predicted concentration in mg/L. Results go to MongoDB, pictures to Cloudinary, and you can download CSV / XLSX.
`MODEL_TYPE` chooses the model: `ann` (the default, ANN v1.1, a fixed neural network from `models/ann_v1_1.joblib`, `ann_v1_1.py`) or `linear` (trained
in the app from a CSV or XLSX of known values). `POST /api/compare` compares the two on known concentrations.

## Run it (Windows PowerShell)

```powershell
cd C:\Users\abhay\Downloads\RGB_PREDICTION\backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                   # then fill in .env (skip if you already have one)
uvicorn main:app --reload
```

Docs and a try-it page: <http://localhost:8000/docs>. Check the database first with `python scripts/check_mongo.py`.

## Settings (`.env`)

`MONGODB_URI`, `MONGODB_DB`, `CLOUDINARY_URL` (or `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` /
`CLOUDINARY_API_SECRET`), `MODEL_DIR` (default `./model`), `MODEL_BUNDLE_PATH` (default `models/ann_v1_1.joblib`), `FRONTEND_ORIGIN` (comma-separated), `MAX_FILE_MB` (20),
`MAX_FILES` (200), `WORKERS` (2), `MODEL_TYPE` (`ann` or `linear`, default `ann`; anything else stops the server at
start). Keys live only in `.env`, which is git-ignored. Leave Cloudinary empty to skip
image storage.

## Endpoints

| Method and path | Result |
|---|---|
| `GET /api/health` | `{status, mongo, cloudinary, model_type, model}`; always 200. `model` is `loaded`; for the ANN also `unavailable` with `model_error` (the reason); for the linear model `missing` |
| `GET /api/model-info` | the active model: `{model_type, model_name, features, expected_error_mg_L, nominal_range_mg_L, training_max_mg_L, trainable}` (ANN: `"ANN v1.1"`, 503 if its file is not loaded) |
| `GET /api/formats` | the image extensions this server can open (from Pillow, after HEIC/AVIF plugins load) |
| `POST /api/jobs` | multipart, repeated field `files` → 202 `{job_id, status, accepted, skipped}`; 503 when `MODEL_TYPE=ann` and the ANN file is not loaded |
| `GET /api/jobs?limit=50` | jobs, newest first |
| `GET /api/jobs/{id}` | `{job_id, status, total, processed, error, skipped}` |
| `GET /api/jobs/{id}/results` | `{job_id, status, results:[{file_name, page, status, error, R, G, B, predicted_concentration_mg_L, expected_error_mg_L, model_status, model_status_text, flags, warning, image_url}]}` |
| `GET /api/jobs/{id}/download?format=csv\|xlsx` | the results as a file (same columns) |
| `DELETE /api/jobs/{id}` | 204; removes job, results and the Cloudinary folder |
| `POST /api/train/preview` | multipart, one `file` (.csv/.xlsx) → first rows, detected concentrations, errors, warnings (trains nothing) |
| `POST /api/train` | multipart, one `file` (.csv/.xlsx) → 202 `{job_id, status}`; 422 if invalid; 409 if a training is running, **or if `MODEL_TYPE=ann`** ("The ANN model is fixed and cannot be trained here. Set MODEL_TYPE=linear to train the linear model.") |
| `GET /api/train/{job_id}` | `{job_id, status, progress, warnings, error}` |
| `GET /api/train/current` | the loaded model's details, or 404 |
| `GET /api/train/current/report` | the full report: errors by range and the table of feature sets tried, or 404 |
| `POST /api/compare` | multipart, one `file` (.csv/.xlsx with `concentration_ppm`, `R`, `G`, optional `file_name`; the same column names as training, so `trim_R` / `trim_G` work) → per row the known concentration, both predictions and both absolute errors; per model `n_valid`, `mae`, `rmse`, `n_unpredicted`. Trains and saves nothing. |

`R`, `G`, `B` are the trimmed means of the valid liquid pixels, rounded to 2 decimals. They are always returned and are
never changed by the model.

**Concentration fields.** `predicted_concentration_mg_L` and `expected_error_mg_L` come from the active model, using
the same `R` and `G` the row shows (the linear model's ppm value is reported in the same field, 1 ppm = 1 mg/L).
`model_status` is `OK`, `REVIEW` or `NOT_VALID_OUTSIDE_CALIBRATED_RANGE` for the ANN (`model_status_text`: "OK", "Review",
"Not valid: outside calibrated range"); for the linear model it is `OK`, or `REVIEW` when a value is outside its training
range, or empty when no model is trained. For `NOT_VALID_OUTSIDE_CALIBRATED_RANGE` (predicted value below 100 or above 1250 mg/L) the value is empty. The ANN gives `REVIEW` for a value above the highest concentration in the training data (read from the model file: 1232 mg/L) and for R, G outside the calibrated region (the model file's min/max box or its distance limit). These status rules were written from the specification; they were not checked against the original colab cell, which was not available. The ANN's
warnings, and the linear model's `outside training range: R`, are in `warning` (the Notes column). The ANN uses only
`R` and `G`; a value outside 0-255 fails that row with the message `R=300.0 must be in 0-255` and the job goes on.
`status` is `ok`, `low_pixels` or `failed`; `flags` can hold `low_pixels`, `clipped`, `high_std`, `roi_size` or `failed`.

Errors: 400 too many files · 404 unknown job / no model · 409 training already running · 413 file too big ·
422 nothing usable / invalid training file / bad `format` · 503 database unreachable.

## Training file

A CSV or XLSX with a concentration in ppm and the R, G, B values, one row per photo (best) or per concentration.
Column names are not case-sensitive, and the app's own exports are accepted:

| Value | Accepted columns (first one found is used) |
|---|---|
| concentration | `concentration_ppm`, or the number in a `folder` column such as `449 ppm` |
| R, G, B | `R`, `G`, `B`; else `trim_R`, `trim_G`, `trim_B` (the batch_features export); else `mean_R`, `mean_G`, `mean_B` |
| file name (optional) | `file_name`, else `image` |

The app's own results CSV is valid once you add a `concentration_ppm` column; its failed rows are simply ignored.
When a column is taken from an alternative name, the preview and the warnings say so (for example `Using trim_R as R`).

- A row with a missing or non-numeric value (or a negative concentration) is ignored, and its row number is listed
  as a warning (row 1 is the header).
- 422 if a value cannot be read at all (the message lists the columns that were found and which values are missing),
  if every row has the same concentration (`Only one concentration (449 ppm) found. Training needs at least 2.`),
  or if no row is valid.

The model is `concentration = intercept + sum(coefficient × feature)`. It tries the feature sets `[R, G]`, `[R]`, `[G]`,
`[R, G, B]` and keeps the one with the lowest error. With 4 or more concentrations the error is measured by leaving one
concentration out at a time ("leave-one-concentration-out"). With 2 or 3 it is "in-sample only, not validated", and only
single-feature sets are considered. The report gives the features, coefficients, typical error and the error for
0–200, 200–600 and 600+ ppm. The model is saved to `MODEL_DIR/concentration_model.json`: the old file is copied to
`concentration_model.<timestamp>.json` first, and the new one is written to a temp file and renamed. Jobs already
running keep the model they started with.

## Image formats

Files are recognised by content, not extension. JPEG goes to `measure_photo` unchanged. Anything else (PNG, WebP, GIF,
BMP, TIFF, HEIC, AVIF, ...) is first written as a clean 8-bit sRGB PNG (EXIF orientation applied, transparency on white,
16-bit/CMYK/gray scaled to 8-bit RGB, first frame/page, no metadata) and that PNG is measured. A file Pillow cannot open
appears in `skipped` with a reason; one that opens but fails to decode becomes a `failed` row.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest                    # all tests (about 30 s)
pytest -m "not slow"      # same here: there are no slow tests any more
```

They use an in-memory fake MongoDB and fake Cloudinary, and blank your real credentials first.

## How it fits together

```
main.py (routes, background job)
  ├ config.py          .env settings
  ├ db.py              MongoDB (jobs, results, train_jobs)
  ├ storage.py         Cloudinary upload / delete
  ├ pdf_utils.py       count PDF pages, render one page
  ├ imaging.py         open any format, clean PNG for non-JPEG files
  ├ concentration.py   (linear model) read + check the training table, fit, save/load the model, predict
  ├ ann_v1_1.py        the fixed ANN: loads models/ann_v1_1.joblib once (SHA-256 checked), predict(R, G, bundle)
  ├ models/            ann_v1_1.joblib and ann_v1_1.sha256 (the only model file the app ever loads)
  ├ compare.py         POST /api/compare: both models against known concentrations
  ├ training.py        one training at a time, in a background thread
  ├ measure_service.py analyze_image(path, model, model_type) -> R, G, B, concentration, flags
  │    └ RGB_PREDICTION.py   measure_photo, qc_flags (the measuring code, unchanged)
  └ exports.py         CSV / XLSX (escapes text that starts with = + - @)
```

`RGB_PREDICTION.py` can still be run by hand to build an RGB table from a folder of photos (`python RGB_PREDICTION.py
"C:\photos" "C:\rgb_out"`); the server does not use that mode.

## The ANN model file

`models/ann_v1_1.joblib` is loaded once at startup, only if its SHA-256 equals `MODEL_BUNDLE_SHA256` in `config.py`
(the same value is in `models/ann_v1_1.sha256`). A joblib file is pickled code, so the app never loads any other file:
not an upload and not a path a request can set. If the file is missing, changed, or was built with another scikit-learn
version than the pinned one (`scikit-learn==1.9.1`), `/api/health` reports `model: unavailable` with the reason and
`POST /api/jobs` answers 503. The model is never trained or refitted here.
