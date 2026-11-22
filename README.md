# RGB Prediction

Measure the colour (R, G, B) of the liquid in vial photos and predict the COD (mg/L) with a fixed, pre-built model.

- **Frontend** (`frontend/`): React + Vite, one page. Upload photos, a folder or a PDF; see R, G, B and the
  predicted COD per photo (or "outside range"); download CSV / XLSX. The web app does not train anything.
- **Backend** (`backend/`): FastAPI. Measures each photo (`RGB_PREDICTION.py`), stores results in MongoDB Atlas, keeps the
  pictures on Cloudinary (optional), and predicts COD with `backend/models/cod_ann_model_bundle.joblib`.

```
RGB-Prediction/
├─ backend/    FastAPI app, RGB_PREDICTION.py (the measuring code), tests, README with the API
└─ frontend/   React + Vite page, tests
```

## What you need

- Python 3.11 – 3.13
- Node.js 20 or newer
- A MongoDB Atlas cluster (and your IP on its Network Access list)
- Optional: a Cloudinary account (without it, results are still produced, just without stored images)

## 1. Backend

```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then open .env and fill in your own values
uvicorn main:app --reload
```

The API runs at <http://localhost:8000> (interactive docs at `/docs`). Check the database connection with
`python scripts/check_mongo.py`.

`.env` holds your secrets (`MONGODB_URI`, Cloudinary keys). It is git-ignored: **never commit it**.
All settings are listed in `backend/.env.example`.

## 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. In development, calls to `/api` are forwarded to the backend on port 8000.
Optional settings are in `frontend/.env.example`.

## 3. The COD model (fixed, no training)

The app only runs `backend/models/cod_ann_model_bundle.joblib` (a neural network on the trimmed-mean R and G, built with
scikit-learn 1.9.1, which is pinned in `backend/requirements.txt`). It is loaded once at startup. A photo whose R, G is
outside the range the model was fitted on gets the status **outside range** and no number. The offline recipe that built
the bundle is in [`model_build/`](model_build/README.md); the web app never runs it.

## 4. Uploads and the browser resize (known limitation)

Vercel rejects request bodies over about 4.5 MB, so the page shrinks big photos in the browser before upload
(longest side 1600 px, JPEG quality 0.92; see `frontend/src/resizeImage.js`). A photo that is at most 1600 px and
under 4 MB is sent unchanged.

**Browser resizing changes the measurement for some photos.** The backend measures at 1200 px and the training data
was measured on original files, but the browser's resampling is not identical and the liquid-region detection is
sensitive to small pixel differences. In a test of 9 real photos, 6 stayed within about 1 level of the original.
The others did not:

| Photo | Measured on the original | Measured after the browser resize |
|---|---|---|
| IMG_2506, IMG_2507 | large region (about 485 x 395 px), B about 205 | **a different region**: a tube-like one, B about 7 |
| IMG_3463 | R 185.9, G 163.8, B 16.4 (region 119 x 100) | R 192.3, G 168.2, B 6.9 (region 82 x 175) |

Which result is correct has not been decided. Uploading the original photos (so nothing is resized) needs a change
to how files reach the backend; it is a proposal only and is not implemented yet.

## Tests

```powershell
# backend (from backend/, venv active)
pip install -r requirements-dev.txt
pytest

# frontend (from frontend/)
npm test
npm run build
```

More detail (endpoints, image formats) is in [`backend/README.md`](backend/README.md).
