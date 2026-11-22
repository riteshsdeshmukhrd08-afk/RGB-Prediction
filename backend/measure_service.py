"""
measure_service.py - measures the R, G and B of one photo with RGB_PREDICTION.py (used unchanged) and
adds the COD from the fixed model (cod_model.py).

analyze_image(path) never raises: a problem becomes status "failed" with an error message.
Row status: "ok", "outside_range" (R, G outside what the COD model covers: no number is given) or "failed".
"""

import cod_model
import imaging
from RGB_PREDICTION import MIN_VALID_PIXELS, PhotoError, measure_photo, qc_flags, safe_text, write_table  # noqa: F401


def empty_row():
    return {"status": "failed", "error": "", "R": None, "G": None, "B": None,
            "cod_mg_l": None, "flags": "failed", "warning": ""}


def analyze_image(path):
    """
    Returns (row, qc). `row` holds the result fields. `qc` holds what qc_flags needs
    (status, clip_frac, std_R/G/B, roi_w), or None if the photo failed.
    """
    row, qc = empty_row(), None
    try:
        with imaging.measurable(path) as p:                  # JPEG as is; other formats via a clean PNG
            m, _ = measure_photo(p)                          # measurement dict (the image array is ignored)
        values = {"R": round(m["trim_R"], 2), "G": round(m["trim_G"], 2), "B": round(m["trim_B"], 2)}
        notes = []
        if m["status"] == "low_pixels":
            notes.append(f"only {m['valid_pixels']} valid liquid pixels (fewer than {MIN_VALID_PIXELS}); "
                         "the measurement is less reliable")
        status, cod = "ok", None
        if cod_model.is_ready():
            res = cod_model.predict(m["trim_R"], m["trim_G"])    # the raw trimmed means, order [R, G]
            cod = res["cod_mg_l"]
            notes += res["warnings"]
            if res["status"] == cod_model.OUTSIDE_RANGE:
                status = "outside_range"
        else:
            notes.append("COD model not loaded")
        qc = {"status": m["status"], "clip_frac": m["clip_frac"], "std_R": m["std_R"], "std_G": m["std_G"],
              "std_B": m["std_B"], "roi_w": m["roi_w"]}
        row.update(status=status, **values, cod_mg_l=cod, flags=qc_flags(qc, None), warning="; ".join(notes))
    except PhotoError as e:
        row["error"] = str(e)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    if row["error"]:
        row.update(status="failed", flags="failed")
        qc = None
    return row, qc
