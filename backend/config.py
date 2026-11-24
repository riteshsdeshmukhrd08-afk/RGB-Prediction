"""
config.py - settings read from the environment (.env file).

Other files do `import config` and use e.g. `config.MAX_FILES`.
Secrets (Mongo password, Cloudinary keys) live only in .env and are never printed.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # the backend folder
load_dotenv(BASE_DIR / ".env")                       # does nothing if .env is missing


def _int_env(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "rgb_measure")

# Cloudinary: either CLOUDINARY_URL, or the three separate values (read in storage.py)
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

# CORS: comma-separated list of allowed website addresses
FRONTEND_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
                    if o.strip()]

# Limits
MAX_FILE_MB = _int_env("MAX_FILE_MB", 20)
MAX_FILES = _int_env("MAX_FILES", 200)
WORKERS = _int_env("WORKERS", 2)                  # photos measured at the same time
MAX_PDF_PAGES = _int_env("MAX_PDF_PAGES", 50)

# Folder that holds concentration_model.json (a relative path is relative to the backend folder)
MODEL_DIR = (BASE_DIR / os.getenv("MODEL_DIR", "model")).resolve()

# Which concentration model gives the predictions: "ann" (default; the fixed ANN, no model file, cannot be trained)
# or "linear" (the model trained in the app from a CSV or XLSX). Read when a request is handled.
MODEL_TYPES = ("ann", "linear")
MODEL_TYPE = os.getenv("MODEL_TYPE", "ann").strip().lower() or "ann"
if MODEL_TYPE not in MODEL_TYPES:
    raise ValueError(f"MODEL_TYPE must be 'ann' or 'linear', got {MODEL_TYPE!r} (check backend/.env)")
