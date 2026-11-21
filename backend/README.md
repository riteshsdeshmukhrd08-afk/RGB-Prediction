# RGB Measurement and Concentration – Backend (FastAPI)

Upload photos or PDFs of vials. For each photo the server measures R, G and B (with `RGB_PREDICTION.py`) and, if a
concentration model is loaded, also returns a predicted concentration in ppm. Results go to MongoDB, pictures to
Cloudinary, and you can download CSV / XLSX. The model is trained from a CSV or XLSX of known values.

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
`CLOUDINARY_API_SECRET`), `MODEL_DIR` (default `./model`), `FRONTEND_ORIGIN` (comma-separated), `MAX_FILE_MB` (20),
`MAX_FILES` (200), `WORKERS` (2). Keys live only in `.env`, which is git-ignored. Leave Cloudinary empty to skip
image storage.

## Endpoints

| Method and path | Result |
|---|---|
| `GET /api/health` | `{status, mongo, cloudinary, model}`; `model` is `loaded` or `missing`; always 200 |
| `GET /api/formats` | the image extensions this server can open (from Pillow, after HEIC/AVIF plugins load) |
| `POST /api/jobs` | multipart, repeated field `files` → 202 `{job_id, status, accepted, skipped}` |
| `GET /api/jobs?limit=50` | jobs, newest first |
| `GET /api/jobs/{id}` | `{job_id, status, total, processed, error, skipped}` |
| `GET /api/jobs/{id}/results` | `{job_id, status, results:[{file_name, page, status, error, R, G, B, predicted_concentration_ppm, typical_error_ppm, flags, warning, image_url}]}` |
| `GET /api/jobs/{id}/download?format=csv\|xlsx` | the results as a file (same columns) |
| `DELETE /api/jobs/{id}` | 204; removes job, results and the Cloudinary folder |
| `POST /api/train/preview` | multipart, one `file` (.csv/.xlsx) → first rows, detected concentrations, errors, warnings (trains nothing) |
| `POST /api/train` | multipart, one `file` (.csv/.xlsx) → 202 `{job_id, status}`; 422 if invalid; 409 if a training is running |
| `GET /api/train/{job_id}` | `{job_id, status, progress, warnings, error}` |
| `GET /api/train/current` | the loaded model's details, or 404 |
| `GET /api/train/current/report` | the full report: errors by range and the table of feature sets tried, or 404 |

`R`, `G`, `B` are the trimmed means of the valid liquid pixels, rounded to 2 decimals. They are always returned and are
never changed by the model. `predicted_concentration_ppm` and `typical_error_ppm` are empty when no model is loaded.
`warning` says `outside training range: R` when a photo's value for a feature of the model is outside the range seen in
training; the prediction is still returned. `status` is `ok`, `low_pixels` or `failed`; `flags` can hold `low_pixels`,
`clipped`, `high_std`, `roi_size` or `failed`.

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
  ├ concentration.py   read + check the training table, fit, save/load the model, predict
  ├ training.py        one training at a time, in a background thread
  ├ measure_service.py analyze_image(path, model) -> R, G, B, concentration, flags
  │    └ RGB_PREDICTION.py   measure_photo, qc_flags (the measuring code, unchanged)
  └ exports.py         CSV / XLSX (escapes text that starts with = + - @)
```

`RGB_PREDICTION.py` can still be run by hand to build an RGB table from a folder of photos (`python RGB_PREDICTION.py
"C:\photos" "C:\rgb_out"`); the server does not use that mode.
