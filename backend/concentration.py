"""
concentration.py - the concentration model.

  read_table / inspect_table   read a training CSV or XLSX and check it (one function decides what is valid)
  fit_model                    choose the feature set and fit  concentration = intercept + sum(coef * feature)
  save_model / load_model      MODEL_DIR/concentration_model.json (old file backed up, new one written atomically)
  predict                      concentration, typical error and a range warning for one photo's R, G, B

The model only uses R, G and B values; it never changes them.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config

log = logging.getLogger("concentration")

MODEL_FILE = "concentration_model.json"
REQUIRED_COLUMNS = ["concentration_ppm", "R", "G", "B"]
# Other column names accepted for each value (the app's own exports use some of them)
CHANNEL_ALIASES = {c: [c, f"trim_{c}", f"mean_{c}"] for c in "RGB"}
FILE_NAME_ALIASES = ["file_name", "image"]
PPM_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s*ppm", re.IGNORECASE)      # "449 ppm" in a folder column
FEATURE_SETS = [["R", "G"], ["R"], ["G"], ["R", "G", "B"]]      # candidates, tried in this order
RANGES = [(0, 200), (200, 600), (600, None)]                    # ppm; None = no upper limit
MIN_CONCENTRATIONS = 2
VALIDATION_CONCENTRATIONS = 4        # leave-one-concentration-out needs at least this many
NOT_VALIDATED = "in-sample only, not validated"
VALIDATED = "leave-one-concentration-out"

MODEL = None          # the loaded model (a dict), or None
MODEL_VERSION = None  # short fingerprint of the file


# ---------------------------------------------------------------- reading the training table
def read_table(data, filename):
    """Read CSV or XLSX bytes into a DataFrame of text cells. Raises ValueError with a readable message."""
    ext = Path(filename or "").suffix.lower()
    if ext not in (".csv", ".xlsx"):
        raise ValueError("Only .csv and .xlsx files are accepted.")
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig",
                             dtype=object, skip_blank_lines=False)
        else:
            df = pd.read_excel(io.BytesIO(data), dtype=object)
    except pd.errors.EmptyDataError:
        raise ValueError("The file is empty.") from None
    except Exception as e:
        raise ValueError(f"The file could not be read as {ext[1:].upper()} ({type(e).__name__}).") from None
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all")                      # blank lines are ignored; row numbers are kept


def _rows_text(rows, limit=20):
    shown = ", ".join(str(r) for r in rows[:limit])
    return shown + (f" and {len(rows) - limit} more" if len(rows) > limit else "")


def _resolve_columns(df):
    """
    Find the columns that hold the concentration, R, G, B (and the file name), accepting the alternative names.
    Returns (columns, mappings, missing): `columns` maps a value name to a numeric Series (or a text Series for
    file_name), `mappings` are messages like "Using trim_R as R", `missing` lists the values that cannot be read.
    """
    lookup = {c.lower(): c for c in df.columns}
    columns, mappings, missing = {}, [], []

    if "concentration_ppm" in lookup:
        columns["concentration_ppm"] = pd.to_numeric(df[lookup["concentration_ppm"]], errors="coerce")
    elif "folder" in lookup:
        found = df[lookup["folder"]].astype(str).str.extract(PPM_IN_TEXT)[0].astype(float)
        if found.notna().any():
            columns["concentration_ppm"] = found
            mappings.append(f"Using the number in column {lookup['folder']} (such as '449 ppm') as concentration_ppm")
    if "concentration_ppm" not in columns:
        missing.append("concentration_ppm")

    for ch in "RGB":
        for name in CHANNEL_ALIASES[ch]:
            if name.lower() in lookup:
                columns[ch] = pd.to_numeric(df[lookup[name.lower()]], errors="coerce")
                if name != ch:
                    mappings.append(f"Using {lookup[name.lower()]} as {ch}")
                break
        else:
            missing.append(ch)

    for name in FILE_NAME_ALIASES:
        if name in lookup:
            columns["file_name"] = df[lookup[name]].astype(str)
            if name != "file_name":
                mappings.append(f"Using {lookup[name]} as file_name")
            break
    return columns, mappings, missing


def _missing_message(df, missing):
    found = ", ".join(df.columns[:30]) + (", ..." if len(df.columns) > 30 else "")
    hints = []
    if "concentration_ppm" in missing:
        hints.append("Add a concentration_ppm column in ppm.")
    channels = [c for c in "RGB" if c in missing]
    if channels:
        hints.append(f"Add {', '.join(channels)} column(s); trim_{channels[0]} or mean_{channels[0]} also work.")
    return f"Found: {found}. Missing: {', '.join(missing)}. " + " ".join(hints)


def inspect_table(df):
    """
    Check a training table. Returns (summary, valid) where `valid` is a DataFrame with the columns
    concentration_ppm, R, G, B (and file_name if present) or None, and `summary` is JSON-ready:
    {columns, preview, mappings, n_rows, n_valid_rows, rejected_rows, concentrations, errors, warnings, valid}.
    Row numbers are spreadsheet rows: row 1 is the header, the first data row is row 2.
    """
    errors, warnings = [], []
    summary = {"columns": list(df.columns), "preview": json.loads(df.head(5).to_json(orient="records")),
               "mappings": [], "n_rows": int(len(df)), "n_valid_rows": 0, "rejected_rows": [], "concentrations": [],
               "errors": errors, "warnings": warnings, "valid": False}
    columns, mappings, missing = _resolve_columns(df)
    summary["mappings"] = mappings
    warnings.extend(mappings)                       # said in the preview and in the warnings
    if missing:
        errors.append(_missing_message(df, missing))
        return summary, None
    if df.empty:
        errors.append("The file has no data rows.")
        return summary, None

    nums = pd.DataFrame({c: columns[c] for c in REQUIRED_COLUMNS})
    ok = np.isfinite(nums.to_numpy(float)).all(axis=1) & (nums["concentration_ppm"].to_numpy(float) >= 0)
    rejected = [int(i) + 2 for i in df.index[~ok]]
    summary["rejected_rows"] = rejected
    if rejected:
        warnings.append(f"Ignored row(s) {_rows_text(rejected)}: a value is missing, not a number, or the "
                        "concentration is negative (row 1 is the header).")
    valid = nums[ok].copy()
    if "file_name" in columns:
        valid["file_name"] = columns["file_name"][ok].to_numpy()
    summary["n_valid_rows"] = int(len(valid))
    if valid.empty:
        errors.append("No valid rows: every row has a missing or non-numeric value.")
        return summary, None

    counts = valid.groupby(valid["concentration_ppm"].round(6)).size()
    summary["concentrations"] = [{"ppm": float(p), "rows": int(n)} for p, n in counts.items()]
    if len(counts) == 1:
        errors.append(f"Only one concentration ({float(counts.index[0]):g} ppm) found. "
                      f"Training needs at least {MIN_CONCENTRATIONS}.")
    elif len(counts) < VALIDATION_CONCENTRATIONS:
        warnings.append(f"Fewer than {VALIDATION_CONCENTRATIONS} concentrations: the error cannot be validated and "
                        "will be reported as in-sample only, not validated.")
    summary["valid"] = not errors
    return summary, (valid if not errors else None)


# ---------------------------------------------------------------- fitting
def _fit(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


def _predict(coef, X):
    return coef[0] + X @ coef[1:]


def _range_label(lo, hi):
    return f"{lo:g}+" if hi is None else f"{lo:g}-{hi:g}"


def fit_model(valid, source_name=""):
    """
    Fit the linear model on the validated table and choose the feature set with the lowest error.
    With 4 or more concentrations the error is measured by leaving one concentration out at a time.
    With 2 or 3 it is in-sample only, and sets with too many features for so few concentrations are skipped.
    """
    y = valid["concentration_ppm"].to_numpy(float)
    groups = np.round(y, 6)
    n_conc = len(np.unique(groups))
    validated = n_conc >= VALIDATION_CONCENTRATIONS
    max_params = max(2, n_conc - 1)

    candidates, best = [], None
    for feats in FEATURE_SETS:
        entry = {"features": feats, "RMSE_ppm": None, "MAE_ppm": None, "skipped": ""}
        candidates.append(entry)
        if not validated and len(feats) + 1 > max_params:
            entry["skipped"] = f"too many features for {n_conc} concentrations"
            continue
        X = valid[feats].to_numpy(float)
        if validated:
            pred = np.empty(len(y))
            for g in np.unique(groups):
                test = groups == g
                pred[test] = _predict(_fit(X[~test], y[~test]), X[test])
        else:
            pred = _predict(_fit(X, y), X)
        resid = y - pred
        rmse, mae = float(np.sqrt(np.mean(resid ** 2))), float(np.mean(np.abs(resid)))
        entry.update(RMSE_ppm=round(rmse, 2), MAE_ppm=round(mae, 2))
        key = (round(rmse, 9), len(feats))                  # lowest error; on a tie, fewer features
        if best is None or key < best["key"]:
            best = {"key": key, "feats": feats, "resid": resid, "rmse": rmse, "mae": mae}

    X = valid[best["feats"]].to_numpy(float)
    coef = _fit(X, y)
    by_range = []
    for lo, hi in RANGES:
        sel = (y >= lo) & (y < (hi if hi is not None else np.inf))
        if sel.any():
            r = best["resid"][sel]
            by_range.append({"range_ppm": _range_label(lo, hi), "from_ppm": lo, "to_ppm": hi,
                             "n_rows": int(sel.sum()), "RMSE_ppm": round(float(np.sqrt(np.mean(r ** 2))), 2),
                             "MAE_ppm": round(float(np.mean(np.abs(r))), 2)})
    return {
        "model": "concentration_ppm = intercept + sum(coefficients[i] * features[i])",
        "features": best["feats"],
        "intercept": float(coef[0]),
        "coefficients": [float(c) for c in coef[1:]],
        "n_rows": int(len(y)), "n_concentrations": int(n_conc),
        "validated": validated,
        "validation": VALIDATED if validated else NOT_VALIDATED,
        "RMSE_ppm": round(best["rmse"], 2), "MAE_ppm": round(best["mae"], 2),
        "typical_error_ppm": round(best["rmse"], 2),
        "error_by_range": by_range,
        "candidates": candidates,
        "training_range": {f: [float(valid[f].min()), float(valid[f].max())] for f in best["feats"]},
        "source_file": source_name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------- saving and loading
_REQUIRED_KEYS = ("features", "intercept", "coefficients", "typical_error_ppm", "error_by_range")


def read_model_file(path):
    """Read and check a model file. Returns (model, version). Raises on any problem."""
    raw = Path(path).read_bytes()
    model = json.loads(raw)
    missing = [k for k in _REQUIRED_KEYS if k not in model]
    if missing:
        raise ValueError("missing keys: " + ", ".join(missing))
    if len(model["coefficients"]) != len(model["features"]):
        raise ValueError("coefficients and features have different lengths")
    return model, hashlib.sha256(raw).hexdigest()[:12]


def load_model():
    """Load MODEL_DIR/concentration_model.json. Missing or unreadable means no model (the server still runs)."""
    global MODEL, MODEL_VERSION
    path = config.MODEL_DIR / MODEL_FILE
    try:
        MODEL, MODEL_VERSION = read_model_file(path)
    except FileNotFoundError:
        MODEL, MODEL_VERSION = None, None
        log.warning("No concentration model found in %s", config.MODEL_DIR)
        return
    except Exception as e:
        MODEL, MODEL_VERSION = None, None
        log.warning("The concentration model could not be used: %s", e)
        return
    log.info("Concentration model loaded: features %s, version %s", MODEL["features"], MODEL_VERSION)


def save_model(model):
    """Back up the current file, then write the new one atomically (temp file, then rename). Returns the version."""
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = config.MODEL_DIR / MODEL_FILE
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        shutil.copy2(target, config.MODEL_DIR / f"concentration_model.{stamp}.json")
    tmp = config.MODEL_DIR / (MODEL_FILE + ".tmp")
    try:
        tmp.write_text(json.dumps(model, indent=2), encoding="utf-8")
        os.replace(tmp, target)                         # the file is never half-written
    finally:
        tmp.unlink(missing_ok=True)
    load_model()
    return MODEL_VERSION


def current():
    """(model, version) in use now. A prediction job takes this once, when it is created."""
    return MODEL, MODEL_VERSION


def is_ready():
    return MODEL is not None


# ---------------------------------------------------------------- predicting
def error_for(model, ppm):
    """Typical error for the concentration range a predicted value falls in (overall error if that range had no data)."""
    for r in model["error_by_range"]:
        hi = r["to_ppm"]
        if r["from_ppm"] <= ppm and (hi is None or ppm < hi):
            return r["RMSE_ppm"]
    return model["typical_error_ppm"]


def predict(model, values):
    """
    values: {"R": .., "G": .., "B": ..}.  Returns (ppm, typical_error_ppm, warning).
    ppm and error are None when `model` is None or a needed value is missing.
    """
    if model is None:
        return None, None, ""
    x = [values.get(f) for f in model["features"]]
    if any(v is None or not math.isfinite(v) for v in x):
        return None, None, ""
    ppm = max(model["intercept"] + sum(c * v for c, v in zip(model["coefficients"], x)), 0.0)
    outside = [f for f, v in zip(model["features"], x)
               if f in model.get("training_range", {})
               and not (model["training_range"][f][0] <= v <= model["training_range"][f][1])]
    warning = ("outside training range: " + ", ".join(outside)) if outside else ""
    return round(ppm, 1), error_for(model, ppm), warning
