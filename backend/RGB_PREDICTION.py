#!/usr/bin/env python3
r"""
RGB_PREDICTION.py - measures the R, G and B of the liquid in vial photos and builds the RGB dataset.

Setup this script expects: white LED behind a grey paper diffuser, vial standing vertically in a
dark foam holder, camera fixed 12-15 cm in front.

Folder layout: one folder per concentration, with the ppm value in its name. Folders can be
nested, and one concentration can be split over folders. A "0 ppm" folder is allowed but not required.

    photos        0 ppm\         photos ...
        150 ppm\       ...
        300 ppm\       ...

Per photo:
  1. Liquid ROI: the central ~55% of the liquid width and ~58% of the liquid height. The meniscus,
     the holder edge and the glass walls are excluded.
  2. Pixel statistics over the ROI, for R, G and B (floats, never truncated):
     mean, median, trimmed mean (darkest and brightest 10% of pixels by brightness removed),
     and the ROI standard deviation (std).
  3. QC flags: clipped (R or G at or above 250 in more than 2% of the ROI), high_std (ROI std above
     15), roi_size (ROI width more than 20% away from the batch median, a sign of a wrong detection),
     low_pixels, failed.

Per concentration: the average of its photos.

Usage (Windows, cmd or PowerShell):
    py RGB_PREDICTION.py "photos" "rgb_out"                          measure every photo, build the tables
    py RGB_PREDICTION.py "photos" "rgb_out" --workers 4              fewer parallel workers (less memory)
    py RGB_PREDICTION.py "photos" "rgb_out" --fresh                  measure every photo again
    py RGB_PREDICTION.py "photos" "rgb_out" --only "150 ppm"         only the folders under this name
    py RGB_PREDICTION.py "photos" "rgb_out" --manual-roi roi.csv     manual ROI overrides (folder,image,x,y,w,h)

Outputs in the output folder:
  batch_features.csv/.xlsx   one row per photo: label, raw float RGB (mean, median, trimmed, std) and QC flags
  rgb_dataset.csv/.xlsx      one row per concentration: the average R, G, B (and more) of its photos
  roi_contact_sheet_NN.png   every photo with its ROI box, for checking by eye
  photo_cache_v2.csv         saved measurements, reused by re-runs

Notes:
  - Changing any setting in this file invalidates the saved photo results automatically.
  - ROI coordinates refer to the shrunk analysis image (longest side MAX_SIDE). The contact sheets show it.
  - Any image format PIL can open is accepted. HEIC/HEIF needs pillow-heif, JPEG XL needs pillow-jxl-plugin.
"""

import argparse
import csv
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from skimage import measure, morphology
from skimage.color import rgb2lab

# Optional decoders for formats Pillow does not read on its own.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()      # HEIC / HEIF
except ImportError:
    pass
try:
    import pillow_jxl                       # JPEG XL (pip install pillow-jxl-plugin)
except ImportError:
    pass

# ---- Settings (change here) -------------------------------------------------------
# Liquid ROI
SIDE_INSET = 0.225         # cut 22.5% of the tube width from each side -> central 55% of the width
TOP_SKIP = 0.20            # skip 20% of the liquid height below the meniscus
BOTTOM_SKIP = 0.22         # skip 22% of the liquid height above the holder -> middle ~58% of the height
MENISCUS_MIN_MAX_ROWS = 6  # the meniscus is a dark band at the top of the liquid, up to this many rows...
MENISCUS_MAX_FRAC = 0.20   # ...or up to this fraction of the tube width, whichever is larger
MENISCUS_MARGIN = 3        # extra rows skipped below the meniscus
BG_STRIP_FRAC = 0.08       # width of the left and right strips used to estimate the background
TUBE_DELTA_E = 30.0        # CIE76 difference from the background that counts as tube or liquid
TUBE_WIDTH_FACTOR = 1.25   # rows wider than this x the tube width reference are not the tube
HOLDER_DARK_MAX = 60       # a pixel is holder-dark if max(R, G, B) is below this
HOLDER_WIDTH_FRAC = 0.6    # the holder test looks at the central 60% of the width
HOLDER_MIN_ROWS = 8        # the holder must be dark for at least this many rows in a row
MIN_ROI_SIZE = 20          # ROI width and height must be at least this many pixels
LIQUID_CHROMA_MIN = 40     # colour fallback: liquid pixels have max - min channel at or above this
# Pixel exclusions
SATURATED_MIN = 250        # exclude pixels with any channel at or above this
NEAR_BLACK_MAX = 10        # exclude pixels with all channels at or below this
GLARE_MIN = 230            # glare: max(R, G, B) at or above this ...
GLARE_MAX_CHROMA = 25      # ... and max - min at or below this
MIN_VALID_PIXELS = 400     # fewer valid pixels -> status low_pixels
INCLUDE_LOW_PIXELS = True  # photos flagged low_pixels are still used
EXCLUDE_FLAGGED = False    # True: photos with clipped, high_std or roi_size flags are left out of the model
# Statistics and QC
TRIM_FRAC = 0.10           # trimmed mean drops the darkest and brightest 10% of pixels (by brightness)
CLIP_LEVEL = 250           # R or G at or above this counts as clipped
CLIP_FLAG_FRAC = 0.02      # flag a photo if more than 2% of its ROI pixels clip
ROI_STD_FLAG = 15.0        # flag a photo if the ROI std of R, G or B is above this (0-255 scale)
ROI_SIZE_FLAG = 0.2        # flag a photo if its ROI width differs from the batch median by more than 20% (fixed camera: expect a few %)
HARD_FLAGS = {"clipped", "high_std", "roi_size"}
# Files and output
IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".gif", ".webp", ".avif", ".jxl",
              ".heif", ".heic", ".hif", ".tif", ".tiff", ".bmp", ".dib", ".jp2", ".j2k"}
NON_IMAGE_EXTS = {".txt", ".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".json", ".xml", ".py", ".pdf",
                  ".doc", ".docx", ".md", ".ini", ".log", ".db", ".sqlite", ".zip", ".rar", ".7z",
                  ".gz", ".tar", ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"}
TILE_W, TILE_H = 170, 210
TILE_COLS, TILES_PER_SHEET = 10, 60
MAX_SIDE = 1200                  # photos are shrunk so the longest side is this many pixels; 0 = no shrinking
CACHE_FILE = "photo_cache_v2.csv"
PPM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ppm", re.IGNORECASE)
DANGEROUS_START = ("=", "+", "-", "@", "\t", "\r")

MEASURE_STATS = [f"{s}_{c}" for s in ("mean", "median", "trim", "std") for c in "RGB"]
ROI_KEYS = ["roi_x", "roi_y", "roi_w", "roi_h"]
CACHE_RESULT_KEYS = ["status", "error"] + ROI_KEYS + ["roi_source", "valid_pixels", "clip_frac"] + MEASURE_STATS
CACHE_KEY_COLUMNS = ["folder", "image", "file_size", "file_mtime_ns", "settings", "manual_roi"]
CACHE_COLUMNS = CACHE_KEY_COLUMNS + ["measure_json"]
SETTINGS_TAG = f"{SIDE_INSET}-{TOP_SKIP}-{BOTTOM_SKIP}-{MENISCUS_MAX_FRAC}-{LIQUID_CHROMA_MIN}-{TRIM_FRAC}-{SATURATED_MIN}"
BATCH_COLUMNS = (["concentration_ppm", "folder", "image", "status", "error", "flags", "roi_source",
                  "roi_x", "roi_y", "roi_w", "roi_h", "valid_pixels", "clip_frac"] + MEASURE_STATS)


class PhotoError(Exception):
    """A photo that cannot be measured. It is recorded in the audit file, and the run continues."""


# ---- Image helpers -----------------------------------------------------------------
@lru_cache(maxsize=None)
def is_photo(path):
    """True for any image file: a known image extension, or a file that PIL can open (checked by content)."""
    p = Path(path)
    if p.name.startswith("."):                   # skips '._' files from Macs and other hidden files
        return False
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        return True
    if ext in NON_IMAGE_EXTS:
        return False
    try:
        with Image.open(p):                      # reads only the header
            return True
    except Exception:
        return False


def load_rgb(path, max_side=MAX_SIDE):
    try:
        img = Image.open(path)
    except UnidentifiedImageError:
        raise PhotoError("cannot read this file as an image: the format is not supported or the file is damaged "
                         "(HEIC/HEIF needs pillow-heif; JPEG XL needs pillow-jxl-plugin)") from None
    if max_side:
        img.draft("RGB", (max_side, max_side))   # JPEG only: decodes at a reduced size
    img = ImageOps.exif_transpose(img)           # orientation only, colours untouched
    if "A" in img.getbands() or "transparency" in img.info:
        rgba = img.convert("RGBA")               # transparent pixels become white, not a random colour
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        img = bg
    else:
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


# ---- Liquid ROI --------------------------------------------------------------------
def find_holder_top(arr):
    """First row of the black holder, or None if there is no holder."""
    H, W = arr.shape[:2]
    x0 = int(W * (1 - HOLDER_WIDTH_FRAC) / 2)
    x1 = int(W * (1 + HOLDER_WIDTH_FRAC) / 2)
    dark_row = (arr[:, x0:x1].max(axis=2) < HOLDER_DARK_MAX).mean(axis=1) > 0.5
    run = 0
    for y in range(H):
        run = run + 1 if dark_row[y] else 0
        if run >= HOLDER_MIN_ROWS:
            start = y - run + 1
            if start > 0.2 * H:          # dark bands at the very top of the image are not the holder
                return start
    return None


def find_tube_column(arr, limit):
    """Left, right, top, bottom of the tube, searched only above row `limit` (background difference)."""
    H, W = arr.shape[:2]
    strip = max(1, int(W * BG_STRIP_FRAC))
    edges = np.concatenate([arr[:, :strip].reshape(-1, 3), arr[:, W - strip:].reshape(-1, 3)])
    bg = np.median(edges.astype(float), axis=0)

    lab = rgb2lab(arr[:limit].astype(float) / 255.0)
    bg_lab = rgb2lab((bg / 255.0).reshape(1, 1, 3))[0, 0]
    delta_e = np.sqrt(((lab - bg_lab) ** 2).sum(axis=2))
    mask = morphology.opening(delta_e > TUBE_DELTA_E, morphology.disk(2))
    regions = measure.regionprops(measure.label(mask))
    if not regions:
        raise PhotoError("no test tube detected against the background")
    main = max(regions, key=lambda r: r.area)
    if main.area < 0.005 * H * W:
        raise PhotoError("detected region is too small to be the test tube")

    comp = main.image
    rows = np.where(comp.any(axis=1))[0]
    lefts = {r: int(np.where(comp[r])[0].min()) for r in rows}
    rights = {r: int(np.where(comp[r])[0].max()) for r in rows}
    widths = {r: rights[r] - lefts[r] + 1 for r in rows}
    ref_width = float(np.percentile(list(widths.values()), 25))   # lower quartile: the holder is wider
    run = []
    for r in rows:
        if widths[r] <= TUBE_WIDTH_FACTOR * ref_width:
            run.append(r)
        elif run:
            break
    if not run:
        raise PhotoError("could not find a tube-shaped region")
    good = np.array(run)
    oy, ox = main.bbox[0], main.bbox[1]
    left = int(round(np.median([lefts[r] for r in good]))) + ox
    right = int(round(np.median([rights[r] for r in good]))) + ox + 1
    top = int(good.min()) + oy
    bottom = int(good.max()) + oy + 1
    if (bottom - top) < (right - left):
        raise PhotoError("detected region is wider than tall, so it is not a tube")
    return left, right, top, bottom


def find_liquid_top(arr, left, right, top, bottom):
    """Row just below the dark meniscus line at the top of the liquid."""
    w = right - left
    max_rows = max(MENISCUS_MIN_MAX_ROWS, int(round(MENISCUS_MAX_FRAC * w)))
    x0, x1 = left + int(w * 0.25), right - int(w * 0.25)   # inner band, away from the glass walls
    dark = (arr[top:bottom, x0:x1].max(axis=2) < 70).mean(axis=1) > 0.5
    run = 0
    for i, is_dark in enumerate(dark):
        if is_dark:
            run += 1
        else:
            if 1 <= run <= max_rows:
                return top + i + MENISCUS_MARGIN
            run = 0
    raise PhotoError("no meniscus line found at the top of the liquid")


def _inner_roi(left, right, liquid_top, liquid_bottom):
    """The central part of the liquid: inner width and middle height, as set above."""
    w = right - left
    inset = int(round(w * SIDE_INSET))
    x, rw = left + inset, w - 2 * inset
    liquid_h = liquid_bottom - liquid_top
    y = liquid_top + int(round(liquid_h * TOP_SKIP))
    y_end = liquid_bottom - int(round(liquid_h * BOTTOM_SKIP))
    rh = y_end - y
    if rw < MIN_ROI_SIZE or rh < MIN_ROI_SIZE:
        raise PhotoError(f"ROI too small ({rw} x {rh} pixels)")
    return int(x), int(y), int(rw), int(rh)


def liquid_roi(arr):
    """Central ROI inside the liquid, found from the background difference. Never below the holder."""
    H = arr.shape[0]
    holder = find_holder_top(arr)
    limit = holder if holder is not None else H
    left, right, top, bottom = find_tube_column(arr, limit)
    liquid_top = find_liquid_top(arr, left, right, top, bottom)
    liquid_bottom = min(bottom, limit)
    if liquid_bottom - liquid_top <= 0:
        raise PhotoError("liquid column has no height above the holder")
    x, y, rw, rh = _inner_roi(left, right, liquid_top, liquid_bottom)
    if y + rh > limit:
        raise PhotoError("ROI would reach the holder")
    return x, y, rw, rh


def liquid_roi_by_colour(arr):
    """Fallback for coloured liquid on a grey or white background. The liquid is found by its colour
    (max - min channel), so a bright window or grey wall behind the tube does not confuse it.
    The meniscus is dark and not coloured, so the liquid top is the top of the coloured region."""
    H, W = arr.shape[:2]
    holder = find_holder_top(arr)
    limit = holder if holder is not None else H
    a = arr[:limit].astype(np.int16)
    chroma = a.max(axis=2) - a.min(axis=2)
    mask = morphology.opening(chroma >= LIQUID_CHROMA_MIN, morphology.disk(2))
    regions = measure.regionprops(measure.label(mask))
    if not regions:
        raise PhotoError("no coloured liquid found (colour fallback)")
    main = max(regions, key=lambda r: r.area)
    if main.area < 0.002 * H * W:
        raise PhotoError("coloured region is too small to be the liquid (colour fallback)")
    comp = main.image
    oy, ox = main.bbox[0], main.bbox[1]
    rows = np.where(comp.any(axis=1))[0]
    lefts = [int(np.where(comp[r])[0].min()) for r in rows]
    rights = [int(np.where(comp[r])[0].max()) for r in rows]
    left = int(round(np.median(lefts))) + ox
    right = int(round(np.median(rights))) + ox + 1
    liquid_top = int(rows.min()) + oy + MENISCUS_MARGIN
    liquid_bottom = min(int(rows.max()) + oy + 1, limit)
    if liquid_bottom - liquid_top <= 0:
        raise PhotoError("liquid column has no height (colour fallback)")
    return _inner_roi(left, right, liquid_top, liquid_bottom)


# ---- Measurement -------------------------------------------------------------------
def measure_roi(arr, roi):
    """Statistics of the valid liquid pixels in the ROI: mean, median, trimmed mean and std for R, G, B,
    plus the number of valid pixels and the fraction of clipped pixels (before exclusions)."""
    x, y, w, h = roi
    H, W = arr.shape[:2]
    if x < 0 or y < 0 or x + w > W or y + h > H or w < 1 or h < 1:
        raise PhotoError(f"ROI {roi} is outside the image")
    patch = arr[y:y + h, x:x + w]
    clip_frac = float(((patch[..., 0] >= CLIP_LEVEL) | (patch[..., 1] >= CLIP_LEVEL)).mean())
    mx = patch.max(axis=2).astype(np.int16)
    mn = patch.min(axis=2).astype(np.int16)
    excluded = (
        (patch >= SATURATED_MIN).any(axis=2)
        | (patch <= NEAR_BLACK_MAX).all(axis=2)
        | ((mx >= GLARE_MIN) & ((mx - mn) <= GLARE_MAX_CHROMA))
    )
    px = patch[~excluded].astype(float)
    n = int(px.shape[0])
    if n == 0:
        raise PhotoError("no valid liquid pixels in the ROI")
    bright = px.mean(axis=1)
    lo, hi = np.percentile(bright, [100 * TRIM_FRAC, 100 * (1 - TRIM_FRAC)])
    keep = (bright >= lo) & (bright <= hi)
    out = {"valid_pixels": n, "clip_frac": clip_frac}
    stats = (("mean", px.mean(axis=0)), ("median", np.median(px, axis=0)),
             ("trim", px[keep].mean(axis=0)),
             ("std", px.std(axis=0, ddof=1) if n > 1 else np.zeros(3)))
    for name, vals in stats:
        for c, v in zip("RGB", vals):
            out[f"{name}_{c}"] = float(v)
    return out


def measure_photo(path, manual_roi=None, max_side=MAX_SIDE):
    """Returns (measurement dict, analysis image). The dict holds the ROI, its source and the statistics."""
    arr = load_rgb(path, max_side)
    if manual_roi is None:
        try:
            roi, source = liquid_roi(arr), "auto"
        except PhotoError:
            roi, source = liquid_roi_by_colour(arr), "auto-colour"
    else:
        roi, source = tuple(int(v) for v in manual_roi), "manual"
    m = measure_roi(arr, roi)
    m.update(roi_x=roi[0], roi_y=roi[1], roi_w=roi[2], roi_h=roi[3], roi_source=source)
    m["status"] = "low_pixels" if m["valid_pixels"] < MIN_VALID_PIXELS else "ok"
    m["error"] = ""
    return m, arr


# ---- QC flags ----------------------------------------------------------------------
def qc_flags(row, roi_w_median):
    """Semicolon-separated QC flags for one photo. Empty means no problem found."""
    if row["status"] == "failed":
        return "failed"
    f = []
    if row["status"] == "low_pixels":
        f.append("low_pixels")
    if row["clip_frac"] > CLIP_FLAG_FRAC:
        f.append("clipped")
    if max(row["std_R"], row["std_G"], row["std_B"]) > ROI_STD_FLAG:
        f.append("high_std")
    if roi_w_median and abs(row["roi_w"] / roi_w_median - 1) > ROI_SIZE_FLAG:
        f.append("roi_size")
    return ";".join(f)


# ---- Per-photo work (runs in worker processes) ---------------------------------------
def make_thumb(arr, roi=None):
    """Small copy of a photo for the contact sheet, and the ROI rescaled to match that copy."""
    H, W = arr.shape[:2]
    f = min((TILE_W - 6) / W, (TILE_H - 34) / H)
    tw, th = max(1, int(W * f)), max(1, int(H * f))
    thumb = np.asarray(Image.fromarray(arr).resize((tw, th), Image.LANCZOS))
    roi_t = None if roi is None else tuple(int(round(v * f)) for v in roi)
    return thumb, roi_t


def cache_payload(row):
    out = {}
    for k in CACHE_RESULT_KEYS:
        v = row.get(k)
        if isinstance(v, np.floating):
            v = float(v)
        elif isinstance(v, np.integer):
            v = int(v)
        out[k] = v
    return out


def process_photo(job):
    """Runs in a worker process. Returns (measurement row, contact-sheet tile) for one photo."""
    path_str, label, ppm, manual_roi, cached, max_side = job
    path = Path(path_str)
    row = {"concentration_ppm": ppm, "folder": label, "image": path.name}
    arr, roi = None, None
    try:
        if cached is not None:                       # measured in an earlier run: reuse it
            row.update(cached)
            arr = load_rgb(path, max_side)           # only needed for the contact sheet
            roi = (row["roi_x"], row["roi_y"], row["roi_w"], row["roi_h"])
        else:
            m, arr = measure_photo(path, manual_roi, max_side)
            row.update(m)
            roi = (m["roi_x"], m["roi_y"], m["roi_w"], m["roi_h"])
    except Exception as e:
        msg = str(e) if isinstance(e, PhotoError) else f"{type(e).__name__}: {e}"
        row.update(status="failed", error=msg)
        roi = None
        try:
            arr = load_rgb(path, max_side)           # still show the photo on the contact sheet
        except Exception:
            arr = None
    thumb, roi_t = (None, None) if arr is None else make_thumb(arr, roi)
    return row, (ppm, f"{label} / {path.name}", thumb, roi_t, row["status"])


# ---- Input and output helpers --------------------------------------------------------
def collect_folders(root):
    """(ppm, folder, label) for every folder that holds photos and has a ppm value in its name, at any depth."""
    found, bad = [], []
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        rel = d.relative_to(root)
        if any(part.startswith(("__MACOSX", ".")) for part in rel.parts):
            continue
        if not any(is_photo(f) for f in d.iterdir() if f.is_file()):
            continue
        label = str(rel)
        m = PPM_RE.search(d.name)
        if m:
            found.append((float(m.group(1)), d, label))
        else:
            bad.append(label)
    if bad:
        raise SystemExit("These folders hold photos but have no ppm value in their name: "
                         + "; ".join(bad) + ". Rename them, e.g. '255 ppm'.")
    if not found:
        raise SystemExit(f"No concentration folders with photos found in '{root}'.")
    return sorted(found, key=lambda t: (t[0], t[2]))


def load_manual_rois(path):
    if path is None:
        return {}
    df = pd.read_csv(path, dtype={"folder": str, "image": str})
    return {(r.folder, r.image): (int(r.x), int(r.y), int(r.w), int(r.h)) for r in df.itertuples()}


def safe_text(value):
    """Stop spreadsheet formula injection: text starting with = + - @ tab or CR is prefixed with a quote."""
    if isinstance(value, str) and value.startswith(DANGEROUS_START):
        return "'" + value
    return value


def write_table(df, base, sheet):
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(safe_text)
    df.to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8")
    df.to_excel(base.with_suffix(".xlsx"), sheet_name=sheet, index=False)


def draw_contact_sheets(tiles, out_dir):
    """tiles: list of (ppm, label, thumbnail array or None, ROI in thumbnail pixels or None, status). Writes PNG pages."""
    pages = []
    for start in range(0, len(tiles), TILES_PER_SHEET):
        chunk = tiles[start:start + TILES_PER_SHEET]
        rows = (len(chunk) + TILE_COLS - 1) // TILE_COLS
        sheet = Image.new("RGB", (TILE_COLS * TILE_W, rows * TILE_H), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (_, label, thumb, roi, status) in enumerate(chunk):
            cx, cy = (i % TILE_COLS) * TILE_W, (i // TILE_COLS) * TILE_H
            draw.text((cx + 3, cy + 2), label[:32], fill="black")
            if thumb is None:
                draw.text((cx + 3, cy + 16), "could not open", fill="red")
                continue
            ox, oy = cx + 3, cy + 30
            sheet.paste(Image.fromarray(thumb), (ox, oy))
            if roi is not None:
                x, y, w, h = roi
                draw.rectangle([ox + x, oy + y, ox + x + w, oy + y + h], outline=(255, 0, 255), width=2)
            if status == "failed":
                draw.text((cx + 3, cy + 16), "FAILED", fill="red")
        path = out_dir / f"roi_contact_sheet_{len(pages) + 1:02d}.png"
        sheet.save(path)
        pages.append(path)
    return pages


def load_cache(path):
    """Saved measurements from earlier runs, keyed by photo and settings. Failed and damaged lines are ignored."""
    cache = {}
    if not path.exists():
        return cache
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                key = tuple(r[k] for k in CACHE_KEY_COLUMNS)
                info = json.loads(r["measure_json"])
                if info.get("status") in (None, "failed"):
                    continue
                cache[key] = info
            except (KeyError, TypeError, ValueError):
                continue
    return cache


# ---- Main --------------------------------------------------------------------------
def _to_numeric(audit, cols):
    for c in cols:
        if c in audit.columns:
            audit[c] = pd.to_numeric(audit[c], errors="coerce")
    return audit


def run(root, out_dir, manual_csv=None, workers=None, fresh=False, max_side=MAX_SIDE, only=None):
    t0 = time.perf_counter()
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / CACHE_FILE
    if fresh and cache_path.exists():
        cache_path.unlink()
    cache = load_cache(cache_path)
    manual = load_manual_rois(manual_csv)
    folders = collect_folders(root)
    if only:
        folders = [f for f in folders if only.lower() in [p.lower() for p in Path(f[2]).parts]]
        if not folders:
            raise SystemExit(f"No concentration folders under '{only}' in '{root}'. Check the folder name.")
        print(f"Partial run: {len(folders)} concentration folders under '{only}'. The tables cover only these folders.")

    by_ppm = {}
    for ppm, folder, label in folders:
        by_ppm.setdefault(ppm, []).append((folder, label))
    for ppm, items in by_ppm.items():
        if len(items) > 1:
            names = "; ".join(label for _, label in items)
            print(f"NOTE: {ppm:g} ppm is in {len(items)} folders ({names}). Their photos are combined.")

    settings_tag = f"{max_side}|{SETTINGS_TAG}"
    jobs, few_photos = [], []
    for ppm in sorted(by_ppm):
        n = 0
        for folder, label in by_ppm[ppm]:
            for img in sorted(f for f in folder.iterdir() if f.is_file() and is_photo(f)):
                n += 1
                st = img.stat()
                manual_roi = manual.get((label, img.name))
                roi_txt = "" if manual_roi is None else ",".join(str(v) for v in manual_roi)
                key = (label, img.name, str(st.st_size), str(st.st_mtime_ns), settings_tag, roi_txt)
                jobs.append((str(img), label, ppm, manual_roi, cache.get(key), key))
        if n < 5:
            few_photos.append(f"{ppm:g} ppm ({n} photos)")
    if not jobs:
        raise SystemExit("No photos found in the concentration folders.")

    workers = workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    n_cached = sum(j[4] is not None for j in jobs)
    print(f"Photos: {len(jobs)}  |  reused from earlier runs: {n_cached}  |  "
          f"measured now: {len(jobs) - n_cached}  |  workers: {workers}", flush=True)

    audit_rows, tiles = [], []
    new_file = not cache_path.exists()
    with open(cache_path, "a", newline="", encoding="utf-8") as cf, \
            ProcessPoolExecutor(max_workers=workers) as ex:
        writer = csv.DictWriter(cf, fieldnames=CACHE_COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        futures = {}
        for path_str, label, ppm, manual_roi, cached, key in jobs:
            fut = ex.submit(process_photo, (path_str, label, ppm, manual_roi, cached, max_side))
            futures[fut] = (key, cached is not None)
        done = 0
        for fut in as_completed(futures):
            key, was_cached = futures[fut]
            row, tile = fut.result()
            audit_rows.append(row)
            tiles.append(tile)
            if not was_cached:                       # save right away, so a crash loses only unfinished photos
                rec = dict(zip(CACHE_KEY_COLUMNS, key))
                rec["measure_json"] = json.dumps(cache_payload(row))
                writer.writerow(rec)
                cf.flush()
            done += 1
            if done % 25 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} photos done", flush=True)

    audit = _to_numeric(pd.DataFrame(audit_rows), ["roi_x", "roi_y", "roi_w", "roi_h", "valid_pixels", "clip_frac"]
                        + MEASURE_STATS)
    use = audit["status"].isin(["ok", "low_pixels"]) if INCLUDE_LOW_PIXELS else audit["status"].eq("ok")
    usable = audit[use].copy()
    if usable.empty:
        write_table(audit.reindex(columns=BATCH_COLUMNS), out_dir / "batch_features", "Batch_features")
        print("No usable photos: every photo failed. See batch_features.csv for the reasons.")
        return None, audit

    roi_w_med = float(usable["roi_w"].median())
    audit["flags"] = [qc_flags(r, roi_w_med) for r in audit.to_dict("records")]
    usable["flags"] = audit.loc[usable.index, "flags"]
    flag_counts = {}
    for s in audit["flags"]:
        for f in (s.split(";") if s else []):
            flag_counts[f] = flag_counts.get(f, 0) + 1

    batch = audit.sort_values(["concentration_ppm", "folder", "image"]).reindex(columns=BATCH_COLUMNS)
    write_table(batch.round(4), out_dir / "batch_features", "Batch_features")

    model_rows = usable
    if EXCLUDE_FLAGGED:
        model_rows = usable[~usable["flags"].apply(lambda s: bool(set(s.split(";")) & HARD_FLAGS))]

    grp = model_rows.groupby("concentration_ppm")
    dataset = pd.DataFrame({
        "n_photos": grp.size(),
        "R": grp["trim_R"].mean(), "G": grp["trim_G"].mean(), "B": grp["trim_B"].mean(),
        "R_median": grp["median_R"].mean(), "G_median": grp["median_G"].mean(), "B_median": grp["median_B"].mean(),
        "std_R": grp["std_R"].mean(), "std_G": grp["std_G"].mean(), "std_B": grp["std_B"].mean(),
        "sd_R_between_photos": grp["trim_R"].std(ddof=1), "sd_G_between_photos": grp["trim_G"].std(ddof=1),
        "sd_B_between_photos": grp["trim_B"].std(ddof=1),
    }).reset_index().round(4)
    write_table(dataset, out_dir / "rgb_dataset", "RGB_dataset")

    pages = draw_contact_sheets(sorted(tiles, key=lambda t: (t[0], t[1])), out_dir)

    print(f"Concentrations in dataset: {len(dataset)}   |   photos used: {len(model_rows)}")
    print(f"Photos processed: {len(audit)}  |  failed: {int((audit.status == 'failed').sum())}  |  "
          f"low_pixels: {int((audit.status == 'low_pixels').sum())}")
    if flag_counts:
        print("QC flags: " + "  ".join(f"{k}={v}" for k, v in sorted(flag_counts.items())))
    print(f"Time: {time.perf_counter() - t0:.0f} s")
    if few_photos:
        print("Concentrations with fewer than 5 photos:", "; ".join(few_photos))
    if EXCLUDE_FLAGGED:
        print("EXCLUDE_FLAGGED is on: photos with clipped, high_std or roi_size flags were left out of the dataset.")
    print("Wrote batch_features.csv/.xlsx and rgb_dataset.csv/.xlsx")
    print("Contact sheets to review by eye:", ", ".join(p.name for p in pages))
    return dataset, audit


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Measure the R, G, B of vial photos and build the RGB dataset (backlit setup).")
    ap.add_argument("root", help="folder that holds the concentration folders (e.g. '150 ppm'), at any depth")
    ap.add_argument("out", help="output folder (keep it outside the root folder)")
    ap.add_argument("--manual-roi", default=None, help="CSV with columns folder,image,x,y,w,h")
    ap.add_argument("--workers", type=int, default=None,
                    help="photos processed in parallel (default: 4, or fewer on small machines)")
    ap.add_argument("--fresh", action="store_true", help="ignore saved results and measure every photo again")
    ap.add_argument("--max-side", type=int, default=MAX_SIDE,
                    help="shrink photos so the longest side is this many pixels; 0 = no shrinking (default 1200)")
    ap.add_argument("--only", default=None, help="process only the folders under this folder name")
    args = ap.parse_args()
    run(args.root, args.out, args.manual_roi, args.workers, args.fresh, args.max_side, args.only)
