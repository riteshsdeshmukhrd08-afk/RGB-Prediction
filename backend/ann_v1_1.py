"""
ann_v1_1.py - the fixed concentration model "ANN v1.1".

The model is a scikit-learn pipeline stored in ONE file that is part of the repository (models/ann_v1_1.joblib).
It is loaded once, at startup, and only after its SHA-256 matches the value pinned in config.py. A joblib file
is pickled code, so no other file is ever loaded: not an upload, not a path a request can set.

Inputs are the measured trimmed means R and G only. B is never used and never passed, not even as a placeholder.
Nothing is trained or refitted here.

STATUS RULES: written from the specification; not checked against the original colab cell, which was not available.
In this order:
  1. NOT_VALID_OUTSIDE_CALIBRATED_RANGE  predicted value below 100 or above 1250 (calibration_nominal_range_mg_L): no value
  2. REVIEW  predicted value above the highest concentration in the training data (the bundle's
     calibration_observed_range_mg_L, read at load time), with the warning WARN_ABOVE_TRAINING
  3. REVIEW  R or G outside the applicability min/max, or d2 above the bundle's d2_threshold (WARN_OUTSIDE_REGION)
  4. OK
Both REVIEW reasons can apply to one row: then both warnings are given.

Status values:
  OK                                    inside the calibrated region
  REVIEW                                a value is given, but it needs a check (the notes say why)
  NOT_VALID_OUTSIDE_CALIBRATED_RANGE    the prediction is outside the calibrated range: no value is given
"""

import hashlib
import logging
import warnings
from pathlib import Path

import numpy as np

import config

log = logging.getLogger("rgb")

MODEL_NAME = "ANN v1.1"
FEATURES = ["R", "G"]

STATUS_OK = "OK"
STATUS_REVIEW = "REVIEW"
STATUS_NOT_VALID = "NOT_VALID_OUTSIDE_CALIBRATED_RANGE"
STATUS_TEXT = {STATUS_OK: "OK", STATUS_REVIEW: "Review", STATUS_NOT_VALID: "Not valid: outside calibrated range"}

WARN_ABOVE_TRAINING = "Above the highest concentration in the training data ({max:g} mg/L). Confirm with a standard."
WARN_OUTSIDE_REGION = "Outside the calibrated region. Confirm with a standard."


class ModelUnavailable(Exception):
    """The model could not be loaded (the message says why). Predictions cannot be made."""


_state = {"bundle": None, "error": "The model has not been loaded yet."}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _check_bundle(b):
    """Raises ModelUnavailable unless the loaded object has what predict() needs."""
    if not isinstance(b, dict):
        raise ModelUnavailable("The model file does not have the expected content.")
    if b.get("features") != FEATURES:
        raise ModelUnavailable('The model file does not use the features ["R", "G"].')
    pipe = b.get("pipeline")
    if pipe is None or not callable(getattr(pipe, "predict", None)):
        raise ModelUnavailable("The model file has no pipeline that can predict.")
    ad = b.get("applicability")
    need = ("mean", "cov_inv", "d2_threshold", "min", "max")
    if not isinstance(ad, dict) or any(k not in ad for k in need):
        raise ModelUnavailable("The model file has no applicability block.")
    for key in ("calibration_nominal_range_mg_L", "calibration_observed_range_mg_L"):
        rng = b.get(key)
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            raise ModelUnavailable("The model file has no calibrated concentration range.")
    err = b.get("expected_error_mg_L_test_RMSEP")
    if not isinstance(err, (int, float)):
        raise ModelUnavailable("The model file has no expected error.")


def load(path=None, expected_sha256=None):
    """
    Loads the repository's model file into memory. Never raises: on a problem the model is marked unavailable and
    the reason is kept (shown by /api/health). Returns True when the model is loaded.
    """
    path = Path(path or config.MODEL_BUNDLE_PATH)
    expected = (expected_sha256 or config.MODEL_BUNDLE_SHA256).lower()
    _state.update(bundle=None, error=None)
    try:
        if not path.is_file():
            raise ModelUnavailable(f"Model file not found: {path.name}")
        if _sha256(path) != expected:
            raise ModelUnavailable(f"Model file {path.name} does not match its pinned SHA-256; it was not loaded.")
        import joblib                                                   # only needed for the ANN
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bundle = joblib.load(path)
        for w in caught:
            if "InconsistentVersion" in type(w.message).__name__:       # built with another scikit-learn version
                raise ModelUnavailable("The model was built with a different scikit-learn version than the one installed.")
        _check_bundle(bundle)
        _state["bundle"] = bundle
    except ModelUnavailable as e:
        _state["error"] = str(e)
    except Exception as e:                                              # a damaged file, a missing library ...
        _state["error"] = f"The model could not be loaded ({type(e).__name__})."
    if _state["error"]:
        log.warning("ANN model not loaded: %s", _state["error"])
    return _state["bundle"] is not None


def is_loaded():
    return _state["bundle"] is not None


def status():
    """For /api/health: {"model": "loaded"} or {"model": "unavailable", "model_error": reason}."""
    if is_loaded():
        return {"model": "loaded"}
    return {"model": "unavailable", "model_error": _state["error"]}


def get():
    """The loaded bundle, or ModelUnavailable (with the reason)."""
    if _state["bundle"] is None:
        raise ModelUnavailable(_state["error"] or "The ANN model is not loaded.")
    return _state["bundle"]


def info(bundle=None):
    """What /api/model-info and the top bar show."""
    b = bundle or get()
    return {"model_type": "ann", "model_name": MODEL_NAME, "features": list(FEATURES),
            "expected_error_mg_L": float(b["expected_error_mg_L_test_RMSEP"]),
            "nominal_range_mg_L": [float(v) for v in b["calibration_nominal_range_mg_L"]],
            "training_max_mg_L": float(b["calibration_observed_range_mg_L"][1]), "trainable": False}


def predict(R, G, bundle=None):
    """
    Returns a dict: predicted_concentration_mg_L (None when not valid), raw_model_output, status, warnings and
    expected_error_mg_L. Raises ValueError("R=... must be in 0-255") when R or G is outside 0-255, and
    ModelUnavailable when the model is not loaded.
    """
    for name, v in (("R", R), ("G", G)):
        if not (0 <= v <= 255):
            raise ValueError(f"{name}={v} must be in 0-255")
    b = bundle or get()
    x = np.array([[R, G]], dtype=float)
    raw = float(b["pipeline"].predict(x)[0])

    lo, hi = (float(v) for v in b["calibration_nominal_range_mg_L"])
    warnings_ = []
    if raw < lo or raw > hi:
        status_, value = STATUS_NOT_VALID, None
    else:
        value = round(raw, 1)
        status_ = STATUS_OK
        observed_max = float(b["calibration_observed_range_mg_L"][1])     # the training maximum, from the bundle
        if raw > observed_max:
            status_ = STATUS_REVIEW
            warnings_.append(WARN_ABOVE_TRAINING.format(max=observed_max))
        ad = b["applicability"]
        d = x[0] - np.asarray(ad["mean"], dtype=float)
        d2 = float(d @ np.asarray(ad["cov_inv"], dtype=float) @ d)
        if (d2 > float(ad["d2_threshold"]) or np.any(x[0] < np.asarray(ad["min"], dtype=float))
                or np.any(x[0] > np.asarray(ad["max"], dtype=float))):
            status_ = STATUS_REVIEW
            warnings_.append(WARN_OUTSIDE_REGION)
    return {"predicted_concentration_mg_L": value, "raw_model_output": round(raw, 1), "status": status_,
            "warnings": warnings_, "expected_error_mg_L": float(b["expected_error_mg_L_test_RMSEP"])}
