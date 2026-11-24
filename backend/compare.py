"""
compare.py - known concentrations against the two models (the ANN and the linear model).

POST /api/compare reads a CSV or XLSX with the same column rules as training (concentration_ppm, R, G, and
optionally file_name and B; trim_R / trim_G / mean_R ... are accepted too) and, for every row, predicts with
BOTH models. It only reads the models: it trains nothing and saves nothing, so comparing never changes either one.

Per model it reports: n_valid (rows that got a value), mae, rmse and n_unpredicted (rows that could not be
predicted: the ANN says "not valid", R or G is outside 0-255, or the linear model is missing / needs a value
the file does not have).
"""

import math

import numpy as np
import pandas as pd

import concentration
import ann_v1_1

NEEDED = ("concentration_ppm", "R", "G")             # B is optional: only a linear model that uses B needs it


def _summary(abs_errors, n_rows):
    n = len(abs_errors)
    e = np.asarray(abs_errors, float)
    return {"n_rows": n_rows, "n_valid": n,
            "mae": round(float(e.mean()), 4) if n else None,
            "rmse": round(float(np.sqrt((e ** 2).mean())), 4) if n else None,
            "n_unpredicted": n_rows - n}


def compare_table(df):
    """Returns (result, errors). `errors` is a list of messages (then result is None)."""
    columns, mappings, missing = concentration._resolve_columns(df)
    absent = [c for c in NEEDED if c in missing]
    if absent:
        return None, [concentration._missing_message(df, absent)]
    if df.empty:
        return None, ["The file has no data rows."]

    use = list(NEEDED) + (["B"] if "B" in columns else [])
    nums = pd.DataFrame({c: columns[c] for c in use})
    core = nums[list(NEEDED)].to_numpy(float)
    ok = np.isfinite(core).all(axis=1) & (nums["concentration_ppm"].to_numpy(float) >= 0)
    rejected = [int(i) + 2 for i in df.index[~ok]]                 # spreadsheet rows (row 1 is the header)
    if not ok.any():
        return None, ["No valid rows: every row has a missing or non-numeric concentration_ppm, R or G."]

    try:
        bundle = ann_v1_1.get()
    except ann_v1_1.ModelUnavailable as e:
        bundle, ann_problem = None, str(e)
    linear, linear_version = concentration.current()
    rows, ann_err, lin_err = [], [], []
    for idx in df.index[ok]:
        known = float(nums.at[idx, "concentration_ppm"])
        r, g = float(nums.at[idx, "R"]), float(nums.at[idx, "G"])
        b = float(nums.at[idx, "B"]) if "B" in nums and math.isfinite(float(nums.at[idx, "B"])) else None
        row = {"row": int(idx) + 2, "known_concentration": known}
        if "file_name" in columns:
            row["file_name"] = str(columns["file_name"][idx])

        try:                                                         # the ANN uses R and G only
            if bundle is None:
                raise ValueError(f"The ANN model is not available: {ann_problem}")
            res = ann_v1_1.predict(r, g, bundle)
            ann_pred, ann_status, ann_note = res["predicted_concentration_mg_L"], res["status"], "; ".join(res["warnings"])
        except ValueError as e:
            ann_pred, ann_status, ann_note = None, None, str(e)
        row.update(ann_predicted=ann_pred, ann_status=ann_status, ann_note=ann_note,
                   ann_abs_error=None if ann_pred is None else round(abs(ann_pred - known), 4))
        if ann_pred is not None:
            ann_err.append(abs(ann_pred - known))

        lin_pred, _, lin_warning = concentration.predict(linear, {"R": r, "G": g, "B": b})
        row.update(linear_predicted=lin_pred, linear_note=lin_warning,
                   linear_abs_error=None if lin_pred is None else round(abs(lin_pred - known), 4))
        if lin_pred is not None:
            lin_err.append(abs(lin_pred - known))
        rows.append(row)

    n = len(rows)
    ann = {"model_name": ann_v1_1.MODEL_NAME, "features": list(ann_v1_1.FEATURES), "available": bundle is not None,
           **_summary(ann_err, n)}
    ann["n_review"] = sum(1 for r in rows if r["ann_status"] == ann_v1_1.STATUS_REVIEW)
    lin = {"model_version": linear_version, "features": list(linear["features"]) if linear else [],
           "available": linear is not None, **_summary(lin_err, n)}
    warnings = list(mappings)
    if rejected:
        warnings.append(f"Ignored row(s) {concentration._rows_text(rejected)}: a value is missing, not a number, "
                        "or the concentration is negative (row 1 is the header).")
    if bundle is None:
        warnings.append(f"The ANN model is not available, so it could not predict any row: {ann_problem}")
    if linear is None:
        warnings.append("No linear model is trained, so it could not predict any row.")
    return {"n_rows": n, "rejected_rows": rejected, "warnings": warnings,
            "models": {"ann": ann, "linear": lin}, "rows": rows}, []
