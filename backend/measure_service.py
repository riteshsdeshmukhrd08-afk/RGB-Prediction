"""
measure_service.py - measures the R, G and B of one photo with RGB_PREDICTION.py (used unchanged).

analyze_image(path) never raises: a problem becomes status "failed" with an error message.
The concentration comes from the model chosen by MODEL_TYPE:
  ann     the fixed ANN (concentration_ann.py): needs no model file, uses only R and G
  linear  the linear model trained in the app (optional: without one, only R, G, B are returned)
"""

import concentration
import concentration_ann
import config
import imaging
from RGB_PREDICTION import MIN_VALID_PIXELS, PhotoError, measure_photo, qc_flags, safe_text, write_table  # noqa: F401


def empty_row():
    return {"status": "failed", "error": "", "R": None, "G": None, "B": None,
            "predicted_concentration_mg_L": None, "expected_error_mg_L": None,
            "model_status": None, "model_status_text": "", "flags": "failed", "warning": ""}


def predict_concentration(values, model, model_type):
    """
    values: the row's R, G, B. Returns a dict with predicted_concentration_mg_L, expected_error_mg_L, model_status,
    model_status_text and notes (a list of warnings). May raise ValueError (the ANN's message when R or G is not in 0-255).
    """
    if model_type == "ann":
        res = concentration_ann.predict(values["R"], values["G"])     # R and G only: B is never passed
        return {"predicted_concentration_mg_L": res["predicted_concentration_mg_L"],
                "expected_error_mg_L": res["expected_error_mg_L"], "model_status": res["status"],
                "model_status_text": concentration_ann.STATUS_TEXT[res["status"]], "notes": list(res["warnings"])}
    ppm, error, warning = concentration.predict(model, values)           # linear: exactly as before (1 ppm = 1 mg/L)
    status = None if ppm is None else ("REVIEW" if warning else "OK")
    return {"predicted_concentration_mg_L": ppm, "expected_error_mg_L": error, "model_status": status,
            "model_status_text": {None: "", "OK": "OK", "REVIEW": "Review"}[status], "notes": [warning] if warning else []}


def analyze_image(path, model=None, model_type=None):
    """
    `model` is the linear model (None: none loaded); `model_type` is "ann" or "linear" (default: MODEL_TYPE).
    Returns (row, qc). `row` holds the result fields. `qc` holds what qc_flags needs
    (status, clip_frac, std_R/G/B, roi_w), or None if the photo failed.
    """
    row, qc = empty_row(), None
    model_type = model_type or config.MODEL_TYPE
    try:
        with imaging.measurable(path) as p:                  # JPEG as is; other formats via a clean PNG
            m, _ = measure_photo(p)                          # measurement dict (the image array is ignored)
        values = {"R": round(m["trim_R"], 2), "G": round(m["trim_G"], 2), "B": round(m["trim_B"], 2)}
        try:
            pred = predict_concentration(values, model, model_type)         # uses the numbers the row shows
        except ValueError as e:                                             # R or G not in 0-255: this row fails, the job goes on
            raise PhotoError(str(e)) from None
        low = (f"only {m['valid_pixels']} valid liquid pixels (fewer than {MIN_VALID_PIXELS}); "
               "the measurement is less reliable") if m["status"] == "low_pixels" else ""
        qc = {"status": m["status"], "clip_frac": m["clip_frac"], "std_R": m["std_R"], "std_G": m["std_G"],
              "std_B": m["std_B"], "roi_w": m["roi_w"]}
        row.update(
            status=m["status"],                              # "ok" or "low_pixels"
            **values,
            predicted_concentration_mg_L=pred["predicted_concentration_mg_L"],
            expected_error_mg_L=pred["expected_error_mg_L"],
            model_status=pred["model_status"], model_status_text=pred["model_status_text"],
            flags=qc_flags(qc, None),                        # roi_size is added later, once the batch is known
            warning="; ".join(w for w in (*pred["notes"], low) if w),
        )
    except PhotoError as e:
        row["error"] = str(e)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    if row["error"]:
        row.update(status="failed", flags="failed")
        qc = None
    return row, qc
