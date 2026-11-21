"""
measure_service.py - measures the R, G and B of one photo with RGB_PREDICTION.py (used unchanged).

analyze_image(path) never raises: a problem becomes status "failed" with an error message.
A concentration model is optional: with one loaded, the row also gets the predicted concentration.
"""

import concentration
import imaging
from RGB_PREDICTION import MIN_VALID_PIXELS, PhotoError, measure_photo, qc_flags, safe_text, write_table  # noqa: F401


def empty_row():
    return {"status": "failed", "error": "", "R": None, "G": None, "B": None,
            "predicted_concentration_ppm": None, "typical_error_ppm": None, "flags": "failed", "warning": ""}


def analyze_image(path, model=None):
    """
    `model` is the concentration model to use (None: only R, G, B are returned).
    Returns (row, qc). `row` holds the result fields. `qc` holds what qc_flags needs
    (status, clip_frac, std_R/G/B, roi_w), or None if the photo failed.
    """
    row, qc = empty_row(), None
    try:
        with imaging.measurable(path) as p:                  # JPEG as is; other formats via a clean PNG
            m, _ = measure_photo(p)                          # measurement dict (the image array is ignored)
        values = {"R": round(m["trim_R"], 2), "G": round(m["trim_G"], 2), "B": round(m["trim_B"], 2)}
        ppm, error, range_warning = concentration.predict(model, values)    # uses the numbers the row shows
        low = (f"only {m['valid_pixels']} valid liquid pixels (fewer than {MIN_VALID_PIXELS}); "
               "the measurement is less reliable") if m["status"] == "low_pixels" else ""
        qc = {"status": m["status"], "clip_frac": m["clip_frac"], "std_R": m["std_R"], "std_G": m["std_G"],
              "std_B": m["std_B"], "roi_w": m["roi_w"]}
        row.update(
            status=m["status"],                              # "ok" or "low_pixels"
            **values,
            predicted_concentration_ppm=ppm, typical_error_ppm=error,
            flags=qc_flags(qc, None),                        # roi_size is added later, once the batch is known
            warning="; ".join(w for w in (range_warning, low) if w),
        )
    except PhotoError as e:
        row["error"] = str(e)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    if row["error"]:
        row.update(status="failed", flags="failed")
        qc = None
    return row, qc
