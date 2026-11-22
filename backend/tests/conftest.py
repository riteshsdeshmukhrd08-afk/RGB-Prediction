"""
Shared test setup.
 - MongoDB is replaced by mongomock (an in-memory fake). Cloudinary is replaced by small fakes.
 - Real credentials from backend/.env are blanked BEFORE the app is imported, so a test can never
   touch your real database or Cloudinary account.
"""

import io
import os
import sys
from pathlib import Path

for _name in ("MONGODB_URI", "CLOUDINARY_URL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
              "CLOUDINARY_API_SECRET"):
    os.environ[_name] = ""          # load_dotenv does not override variables that already exist

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import storage  # noqa: E402
from main import app  # noqa: E402

def make_photo_png(seed=0):
    """A synthetic photo: grey wall with an orange 'liquid' column. Returns PNG bytes."""
    rng = np.random.default_rng(seed)
    arr = np.full((800, 600, 3), 200, np.uint8)
    arr[100:600, 250:350] = (220, 140, 40)
    arr = np.clip(arr.astype(int) + rng.integers(-4, 5, arr.shape), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def make_small_png(color, seed=0, width=50):
    """A small synthetic photo (300x400) with a tube of the given colour and width."""
    rng = np.random.default_rng(seed)
    arr = np.full((400, 300, 3), 200, np.uint8)
    arr[40:260, 130:130 + width] = color
    arr = np.clip(arr.astype(int) + rng.integers(-3, 4, arr.shape), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def make_pdf(path, pages=3):
    import fitz
    png = make_photo_png()
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(fitz.Rect(40, 40, 40 + 450, 40 + 600), stream=png)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def cloud(monkeypatch):
    """Fake Cloudinary. `calls` records what the app did."""
    calls = {"uploads": [], "deleted": []}

    def fake_upload(path, job_id):
        calls["uploads"].append(job_id)
        return f"https://res.example.com/rgb-measure/{job_id}/{Path(path).name}"

    monkeypatch.setattr(storage, "is_configured", lambda: True)
    monkeypatch.setattr(storage, "check", lambda: "ok")
    monkeypatch.setattr(storage, "upload_file", fake_upload)
    monkeypatch.setattr(storage, "delete_job_folder", lambda job_id: calls["deleted"].append(job_id))
    return calls


def _start(monkeypatch, tmp_path):
    db.client = mongomock.MongoClient()
    db._indexed = False
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, tmp_path, cloud):
    """The app, with the fixed COD model loaded at startup (the real file in backend/models)."""
    with _start(monkeypatch, tmp_path) as c:
        yield c


def upload(client, files):
    """files: list of (name, bytes). Sends them in the repeated multipart field 'files'."""
    return client.post("/api/jobs", files=[("files", (n, b, "application/octet-stream")) for n, b in files])


