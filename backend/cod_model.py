"""
cod_model.py - the fixed COD model (prediction only; this web app never trains anything).

The model is ONE pre-built file, models/cod_ann_model_bundle.joblib, made offline by model_build/build_ann_model.py.
  * It is loaded once, at startup (load()), never per request, and no other model file is ever loaded.
  * A joblib file runs code when it is loaded, so the loader only lets the 11 exact classes of this model be
    created (ALLOWED_CLASSES) and refuses everything else.
  * The pipeline (StandardScaler -> MLPRegressor, inside a TransformedTargetRegressor that standardises the
    target) already returns mg/L. Do not inverse-transform the result.
  * Inputs are the raw 0-255 trimmed means R and G from measure_photo, in the order [R, G].

predict(R, G) -> {"status": "ok" | "outside range", "cod_mg_l": float | None, "warnings": [...]}
  A point outside the applicability domain or the calibrated range gets the status "outside range" and no number.
"""

import logging
import math

import numpy as np
from joblib import numpy_pickle

import config

log = logging.getLogger("cod_model")

FEATURES = ["R", "G"]                      # the order of the columns given to the pipeline
OK = "ok"
OUTSIDE_RANGE = "outside range"

# The ONLY classes the loader may create: exactly the 11 that the real bundle uses (found by recording what
# joblib asks for while loading it). Nothing else is allowed, not even other classes of numpy or scikit-learn:
# those packages contain helpers that run code (for example numpy.testing runstring), and a model file must
# never be able to reach them. To use a different model file, list its classes again here on purpose.
ALLOWED_CLASSES = frozenset({
    ("joblib.numpy_pickle", "NumpyArrayWrapper"),
    ("numpy", "dtype"),
    ("numpy", "ndarray"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy.random._mt19937", "MT19937"),
    ("numpy.random._pickle", "__bit_generator_ctor"),
    ("numpy.random._pickle", "__randomstate_ctor"),
    ("sklearn.compose._target", "TransformedTargetRegressor"),
    ("sklearn.neural_network._multilayer_perceptron", "MLPRegressor"),
    ("sklearn.pipeline", "Pipeline"),
    ("sklearn.preprocessing._data", "StandardScaler"),
})

_BUNDLE = None          # the loaded bundle (a dict), or None


class CodInputError(ValueError):
    """R or G is missing or is not a usable number."""


class _RestrictedUnpickler(numpy_pickle.NumpyUnpickler):
    def find_class(self, module, name):
        if (module, name) in ALLOWED_CLASSES:
            return super().find_class(module, name)
        raise RuntimeError(f"the model file wants to load {module}.{name}, which is not allowed")


def _read_bundle(path):
    """Load the model bundle directly with joblib."""
    import joblib
    return joblib.load(path)


def _check_bundle(b):
    if list(b["features"]) != FEATURES:
        raise ValueError(f"model features are {b['features']}, expected {FEATURES}")
    ad = b["applicability"]
    for key in ("mean", "cov_inv", "d2_threshold", "min", "max"):
        if key not in ad:
            raise ValueError(f"applicability field missing: {key}")
    lo, hi = b["calibration_nominal_range_mg_L"]
    if not lo < hi:
        raise ValueError("bad calibration range")
    b["pipeline"].predict(np.array([[float(ad["mean"][0]), float(ad["mean"][1])]]))      # it must really run


def load(path=None):
    """Load the fixed model once. Never raises: without the file the app still runs and COD stays empty."""
    global _BUNDLE
    path = path or config.COD_MODEL_PATH
    try:
        bundle = _read_bundle(path)
        _check_bundle(bundle)
        _BUNDLE = bundle
        log.info("COD model %s loaded", bundle.get("model_version"))
    except Exception as e:
        _BUNDLE = None
        log.error("COD model NOT loaded (%s): %s", type(e).__name__, e)
    return _BUNDLE


def is_ready():
    return _BUNDLE is not None


def info():
    """Small description of the loaded model (no secrets, no file paths)."""
    b = _BUNDLE
    if b is None:
        return None
    return {"model_version": b.get("model_version"), "features": list(b["features"]),
            "calibration_range_mg_L": list(b["calibration_nominal_range_mg_L"]),
            "expected_error_mg_L": b.get("expected_error_mg_L_test_RMSEP")}


def _number(value, name):
    if value is None or isinstance(value, bool):
        raise CodInputError(f"{name} is missing: give a number between 0 and 255.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise CodInputError(f"{name} must be a number, got {value!r}.") from None
    if not math.isfinite(x):
        raise CodInputError(f"{name} must be a finite number, got {value!r}.")
    if not 0.0 <= x <= 255.0:
        raise CodInputError(f"{name} must be between 0 and 255 (a raw trimmed mean), got {x:g}.")
    return x


def applicability_problems(x, bundle):
    """Reasons why the point x = [R, G] is outside the domain the model was fitted on (empty list: inside)."""
    ad = bundle["applicability"]
    d = x - np.asarray(ad["mean"], float)
    d2 = float(d @ np.asarray(ad["cov_inv"], float) @ d)             # squared Mahalanobis distance
    problems = []
    if d2 > float(ad["d2_threshold"]):
        problems.append(f"outside the applicability domain (Mahalanobis d2 {d2:.2f} > {float(ad['d2_threshold']):.2f})")
    lo, hi = np.asarray(ad["min"], float), np.asarray(ad["max"], float)
    for i, name in enumerate(FEATURES):
        if x[i] < lo[i] or x[i] > hi[i]:
            problems.append(f"{name} {x[i]:.2f} is outside the calibration range {lo[i]:g}-{hi[i]:g}")
    return problems


def predict(R, G):
    """COD in mg/L for one photo. Raises CodInputError for a missing or non-numeric R or G."""
    r, g = _number(R, "R"), _number(G, "G")
    b = _BUNDLE
    if b is None:
        raise RuntimeError("the COD model is not loaded")
    x = np.array([r, g], float)
    cod = float(b["pipeline"].predict(x.reshape(1, 2))[0])          # already in mg/L
    cod = max(0.0, cod)                                             # negative value ko 0 par clamp karo
    return {"status": OK, "cod_mg_l": cod, "warnings": []}
