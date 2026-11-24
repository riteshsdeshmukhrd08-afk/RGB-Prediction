# RGB Prediction

Measure the colour (R, G, B) of the liquid in vial photos, and optionally estimate a concentration (ppm).

- **Frontend** (`frontend/`): React + Vite, one page. Upload photos, a folder or a PDF; see R, G, B, a colour swatch and the
  predicted concentration per photo; download CSV / XLSX; train a model from a CSV or XLSX of known values.
- **Backend** (`backend/`): FastAPI. Measures each photo (`RGB_PREDICTION.py`), stores results in MongoDB Atlas, keeps the
  pictures on Cloudinary (optional), and fits the concentration model.

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

## 3. Train a concentration model (optional)

Use the Train panel on the page with a CSV or XLSX that has the columns `concentration_ppm`, `R`, `G`, `B`
(one row per photo, or one per concentration, at least 2 concentrations). The app's own results CSV works once you add a
`concentration_ppm` column. Without a model, every photo still gets its R, G, B.

## Tests

```powershell
# backend (from backend/, venv active)
pip install -r requirements-dev.txt
pytest

# frontend (from frontend/)
npm test
npm run build
```

More detail (endpoints, image formats, training file rules) is in [`backend/README.md`](backend/README.md).
