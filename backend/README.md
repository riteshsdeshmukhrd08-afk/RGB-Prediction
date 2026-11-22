# RGB Measurement and Concentration – Backend (FastAPI)

Upload photos or PDFs of vials. For each photo the server measures R, G and B (with `RGB_PREDICTION.py`) and predicts the
COD in mg/L with the fixed model `models/cod_ann_model_bundle.joblib`. Results go to MongoDB, pictures to
Cloudinary, and you can download CSV / XLSX. There is no training in the web app.

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
`CLOUDINARY_API_SECRET`), `FRONTEND_ORIGIN` (comma-separated), `MAX_FILE_MB` (20),
`MAX_FILES` (200), `WORKERS` (2). Keys live only in `.env`, which is git-ignored. Leave Cloudinary empty to skip
image storage.

## Endpoints

| Method and path | Result |
|---|---|
| `GET /api/health` | `{status, mongo, cloudinary, model}`; `model` is `loaded` or `missing`; always 200 |
| `GET /api/formats` | the image extensions this server can open (from Pillow, after HEIC/AVIF plugins load) |
| `POST /api/jobs` | multipart, repeated field `files` → 202 `{job_id, status, accepted, skipped}` |
| `GET /api/jobs?limit=50` | jobs, newest first |
| `GET /api/jobs/{id}` | `{job_id, status, total, processed, error, skipped, idempotency_key}` |
| `GET /api/jobs/{id}/results` | `{job_id, status, results:[{file_name, page, status, error, R, G, B, cod_mg_l, flags, warning, image_url}]}` |
| `GET /api/jobs/{id}/download?format=csv\|xlsx` | the results as a file (same columns) |
| `DELETE /api/jobs/{id}` | 204; removes job, results and the Cloudinary folder |

`R`, `G`, `B` are the trimmed means of the valid liquid pixels, rounded to 2 decimals. They are always returned and are
never changed by the model. `cod_mg_l` is the predicted COD in mg/L, from the raw trimmed means in the order `[R, G]`.
`status` is `ok`, `outside_range` or `failed`. `outside_range` means R, G is outside the model's applicability domain
(Mahalanobis distance above the bundle's `d2_threshold`, or outside the R/G range it was fitted on) or the prediction is
outside the calibrated 100-1250 mg/L; `cod_mg_l` is then `null`, and `warning` says why. `flags` can hold `low_pixels`,
`clipped`, `high_std`, `roi_size` or `failed`.

Errors: 400 too many files · 404 unknown job · 413 file too big ·
422 nothing usable / bad `format` · 503 database unreachable.

## The COD model

`models/cod_ann_model_bundle.joblib` is the only model file the server loads, once, at startup (`cod_model.py`). A joblib
file runs code when it is loaded, so the loader only allows numpy, scikit-learn, scipy and joblib classes. The pipeline
(StandardScaler, MLPRegressor, target standardised) already returns mg/L. Without the file the server still runs, rows
get no COD and `/api/health` says `model: missing`. The bundle was built with scikit-learn 1.9.1 (Python 3.13.7,
numpy 2.1.3, scipy 1.18.1, joblib 1.6.0) and must be read by the same version. To change the model, rebuild it offline
(see `../model_build/README.md`) and replace the file.

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
  ├ db.py              MongoDB (jobs, results)
  ├ storage.py         Cloudinary upload / delete
  ├ pdf_utils.py       count PDF pages, render one page
  ├ imaging.py         open any format, clean PNG for non-JPEG files
  ├ cod_model.py       load the fixed COD model once, predict(R, G), applicability check
  ├ measure_service.py analyze_image(path) -> R, G, B, COD, flags
  │    └ RGB_PREDICTION.py   measure_photo, qc_flags (the measuring code, unchanged)
  └ exports.py         CSV / XLSX (escapes text that starts with = + - @)
```

`RGB_PREDICTION.py` can still be run by hand to build an RGB table from a folder of photos (`python RGB_PREDICTION.py
"C:\photos" "C:\rgb_out"`); the server does not use that mode.
