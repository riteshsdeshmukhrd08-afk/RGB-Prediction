"""
exports.py - builds the CSV / XLSX download for a prediction job.
"""

from pathlib import Path

import pandas as pd

from RGB_PREDICTION import safe_text, write_table

COLUMNS = ["file_name", "page", "status", "R", "G", "B", "predicted_concentration_mg_L", "expected_error_mg_L",
           "model_status", "flags", "warning", "error", "image_url"]
SOURCE = {"model_status": "model_status_text"}                 # the file shows the text, e.g. "Not valid: outside calibrated range"


def build_export(results, fmt, out_dir):
    """Write the results into out_dir and return the Path of the file ("csv" or "xlsx")."""
    df = pd.DataFrame({c: [r.get(SOURCE.get(c, c)) for r in results] for c in COLUMNS}, columns=COLUMNS)
    df["page"] = pd.array(df["page"], dtype="Int64")          # whole numbers, blank for images

    # Stop spreadsheet formula injection. Done here for EVERY text cell, because pandas string
    # columns are not always caught by the check inside write_table.
    for col in df.columns:
        df[col] = [safe_text(v) if isinstance(v, str) else v for v in df[col]]

    base = Path(out_dir) / "results"
    write_table(df, base, "RGB_results")                      # writes results.csv and results.xlsx
    return base.with_suffix("." + fmt)
