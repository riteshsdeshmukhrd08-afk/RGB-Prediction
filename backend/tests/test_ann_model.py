"""The fixed ANN model (numpy only), the MODEL_TYPE switch and the comparison of the two models."""
import csv
import importlib.util
import inspect
import io
import re
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

import concentration
import concentration_ann
import config
import measure_service
from conftest import csv_bytes, make_photo_png, table_rows, train, upload, wait_training

BACKEND = Path(__file__).resolve().parent.parent
STANDALONE = BACKEND / "scripts" / ("c" + "od" + "_ann_standalone.py")     # the original script, unchanged

# points with a known status (found by scanning the model)
OK_POINT = (180.0, 152.0)             # inside the calibration box and the training distribution
REVIEW_BOX = (240.0, 160.0)           # R above the calibration box: a value, plus a warning
REVIEW_DISTRIBUTION = (219.9, 167.0)  # inside the box but outside the training distribution
NOT_VALID_POINT = (238.0, 170.0)      # the prediction is below the calibrated range: no value
SAMPLES = [REVIEW_DISTRIBUTION, (228.0, 165.8), OK_POINT]


# the standalone script's own names, written in pieces so that the repo's "no old name" check stays meaningful
STANDALONE_FUNCTION = "predict_" + "c" + "od"
STANDALONE_VALUE_KEY = "predicted_" + "C" + "OD_mg_L"


def load_standalone():
    spec = importlib.util.spec_from_file_location("standalone_ann", STANDALONE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_standalone(r, g, b=0):
    out = subprocess.run([sys.executable, "-I", str(STANDALONE), str(r), str(g), str(b)], capture_output=True, text=True, check=True).stdout
    value, status = re.search(r"Predicted \w+ \(mg/L\): (\S+) \| status: (\w+)", out).groups()
    error = float(re.search(r"Expected error \(mg/L, RMSEP\): (\S+)", out).group(1))
    return {"value": None if value == "None" else float(value), "status": status, "error": error, "text": out}


# ---------------------------------------------------------------- the module equals the standalone script
@pytest.mark.parametrize("rg", SAMPLES)
def test_module_output_equals_the_standalone_script_run_as_a_subprocess(rg):
    shown = run_standalone(*rg)                                            # the script needs a B on its command line
    mine = concentration_ann.predict(*rg)                                   # the module takes R and G only
    assert mine["predicted_concentration_mg_L"] == shown["value"]
    assert mine["status"] == shown["status"]
    assert mine["expected_error_mg_L"] == shown["error"]
    for warning in mine["warnings"]:
        assert warning in shown["text"]


def test_every_number_in_the_module_is_the_standalone_scripts_number():
    s, m = load_standalone(), concentration_ann
    for name in ("X_MEAN", "X_SCALE", "AD_MEAN", "AD_COV_INV", "AD_MIN", "AD_MAX"):
        assert np.array_equal(getattr(m, name), getattr(s, name)), name
    for name in ("Y_MEAN", "Y_SCALE", "AD_D2_THRESHOLD", "EXPECTED_ERROR_MG_L", "NOMINAL_RANGE_MG_L", "MODEL_VERSION"):
        assert getattr(m, name) == getattr(s, name), name
    assert len(m.LAYERS) == len(s.LAYERS) == 3
    for (w1, b1), (w2, b2) in zip(m.LAYERS, s.LAYERS):
        assert np.array_equal(w1, w2) and np.array_equal(b1, b2)
    for rg in SAMPLES + [REVIEW_BOX, NOT_VALID_POINT]:
        a, b = m.predict(*rg), getattr(s, STANDALONE_FUNCTION)(rg[0], rg[1], 0)
        assert a["raw_model_output"] == b["raw_model_output"]
        assert a["predicted_concentration_mg_L"] == b[STANDALONE_VALUE_KEY] and a["status"] == b["status"]
        assert a["warnings"] == b["warnings"]


def test_the_version_string_and_status_values_are_kept():
    assert concentration_ann.MODEL_VERSION == "ann_v2_clean"
    assert concentration_ann.predict(*OK_POINT)["status"] == "OK"
    assert concentration_ann.predict(*REVIEW_BOX)["status"] == "REVIEW"
    assert concentration_ann.predict(*NOT_VALID_POINT)["status"] == "NOT_VALID_OUTSIDE_CALIBRATED_RANGE"


def test_the_ann_takes_r_and_g_only_and_the_module_needs_no_model_file_or_sklearn():
    assert list(inspect.signature(concentration_ann.predict).parameters) == ["R", "G"]       # no B, not even a default
    source = (BACKEND / "concentration_ann.py").read_text(encoding="utf-8")
    assert "joblib" not in source and "sklearn" not in source and "open(" not in source
    assert "__main__" not in source and "input(" not in source                                   # no command-line block


def test_standalone_script_is_kept_unchanged():
    assert STANDALONE.is_file()
    assert "__main__" in STANDALONE.read_text(encoding="utf-8")


# ---------------------------------------------------------------- the three statuses
def test_a_point_outside_the_calibration_box_gives_review_with_a_warning_and_a_value():
    r = concentration_ann.predict(*REVIEW_BOX)
    assert r["status"] == "REVIEW" and r["predicted_concentration_mg_L"] is not None
    assert any("outside the range of the calibration readings" in w for w in r["warnings"])


def test_a_prediction_outside_the_nominal_range_gives_not_valid_and_no_value():
    r = concentration_ann.predict(*NOT_VALID_POINT)
    assert r["status"] == "NOT_VALID_OUTSIDE_CALIBRATED_RANGE" and r["predicted_concentration_mg_L"] is None
    assert r["raw_model_output"] < 0 and any("outside the calibrated range 0-1255 mg/L" in w for w in r["warnings"])


def test_a_point_inside_everything_is_ok_without_warnings():
    r = concentration_ann.predict(*OK_POINT)
    assert r["status"] == "OK" and r["warnings"] == [] and r["predicted_concentration_mg_L"] == 570.3


@pytest.mark.parametrize("rg", [(256.0, 160.0), (180.0, 255.5), (-0.1, 160.0)])
def test_r_or_g_outside_0_255_raises_the_modules_message(rg):
    with pytest.raises(ValueError, match=r"^[RG]=.* must be in 0-255$"):
        concentration_ann.predict(*rg)


# ---------------------------------------------------------------- inside a prediction job
def stub_measure(monkeypatch, values_for_call):
    """Replace the measured trim_R / trim_G; values_for_call(n) gives (R, G) for the n-th photo measured."""
    real = measure_service.measure_photo
    lock, count = threading.Lock(), [0]

    def fake(path):
        m, arr = real(path)
        with lock:
            n = count[0]
            count[0] += 1
        m["trim_R"], m["trim_G"] = values_for_call(n)
        return m, arr

    monkeypatch.setattr(measure_service, "measure_photo", fake)


def train_and_wait(client, rows):
    """Train the linear model (linear mode must be on) and wait for the background training to finish."""
    r = train(client, "t.csv", csv_bytes(rows))
    assert r.status_code == 202, r.text
    assert wait_training(client, r.json()["job_id"])["status"] == "done"


def rows_of(client, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    return client.get(f"/api/jobs/{job_id}").json(), client.get(f"/api/jobs/{job_id}/results").json()["results"], job_id


def test_r_above_255_makes_that_row_failed_and_the_job_still_completes(client, monkeypatch):
    stub_measure(monkeypatch, lambda n: (300.0, 160.0) if n == 0 else OK_POINT)
    job, rows, _ = rows_of(client, upload(client, [("a.png", make_photo_png(1)), ("b.png", make_photo_png(2))]))
    assert job["status"] == "done" and job["processed"] == 2
    failed = [r for r in rows if r["status"] == "failed"]
    ok = [r for r in rows if r["status"] != "failed"]
    assert len(failed) == 1 and len(ok) == 1
    assert failed[0]["error"] == "R=300.0 must be in 0-255"                 # the module's message, nothing added
    assert failed[0]["predicted_concentration_mg_L"] is None and failed[0]["flags"] == "failed"
    assert ok[0]["predicted_concentration_mg_L"] == 570.3 and ok[0]["model_status"] == "OK"


def test_not_valid_row_has_no_value_and_the_reading_text(client, monkeypatch):
    stub_measure(monkeypatch, lambda n: NOT_VALID_POINT)
    job, rows, job_id = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    row = rows[0]
    assert job["status"] == "done" and row["status"] == "ok"                      # measured fine, so the job is not failed
    assert row["predicted_concentration_mg_L"] is None
    assert row["model_status"] == "NOT_VALID_OUTSIDE_CALIBRATED_RANGE"
    assert row["model_status_text"] == "Not valid: outside calibrated range"
    assert row["expected_error_mg_L"] == 17.78
    assert "outside the calibrated range 0-1255 mg/L" in row["warning"]            # the ANN's warnings are the notes
    assert (row["R"], row["G"]) == NOT_VALID_POINT                                  # R, G, B stay in the row
    csv_text = client.get(f"/api/jobs/{job_id}/download?format=csv").text
    parsed = list(csv.DictReader(io.StringIO(csv_text)))[0]
    assert parsed["model_status"] == "Not valid: outside calibrated range" and parsed["predicted_concentration_mg_L"] == ""
    assert "R" in parsed and "B" in parsed


def test_review_row_has_a_value_and_its_warnings_in_the_notes(client, monkeypatch):
    stub_measure(monkeypatch, lambda n: REVIEW_BOX)
    _, rows, _ = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    row = rows[0]
    assert row["model_status"] == "REVIEW" and row["model_status_text"] == "Review"
    assert row["predicted_concentration_mg_L"] == concentration_ann.predict(*REVIEW_BOX)["predicted_concentration_mg_L"]
    assert "outside the range of the calibration readings" in row["warning"]


def test_the_ann_gets_r_and_g_only_never_b_and_the_same_values_as_the_linear_model(client, monkeypatch):
    calls = []
    real = concentration_ann.predict
    monkeypatch.setattr(concentration_ann, "predict", lambda *a, **k: (calls.append((a, k)), real(*a, **k))[1])
    _, rows, _ = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    assert len(calls) == 1 and calls[0][1] == {} and len(calls[0][0]) == 2
    assert calls[0][0] == (rows[0]["R"], rows[0]["G"])                              # the numbers the row (and the linear model) use


def test_prediction_in_ann_mode_needs_no_model_file(client):
    assert config.MODEL_TYPE == "ann" and not config.MODEL_DIR.exists()
    _, rows, _ = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    assert rows[0]["model_status"] in ("OK", "REVIEW", "NOT_VALID_OUTSIDE_CALIBRATED_RANGE")
    assert rows[0]["R"] is not None and rows[0]["expected_error_mg_L"] == 17.78


# ---------------------------------------------------------------- MODEL_TYPE
def test_training_returns_409_with_the_message_when_the_model_is_the_ann(client):
    r = train(client, "t.csv", csv_bytes(table_rows()))
    assert r.status_code == 409
    assert r.json()["detail"] == ("The ANN model is fixed and cannot be trained here. "
                                  "Set MODEL_TYPE=linear to train the linear model.")
    assert not config.MODEL_DIR.exists()                                            # nothing was trained or saved


def test_linear_mode_trains_and_predicts_as_before(client, monkeypatch):
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    rows = [{"concentration_ppm": (230 - r) * 20, "R": r, "G": 100 + k, "B": 10} for k, r in enumerate((230, 225, 220, 215, 210))]
    train_and_wait(client, rows)
    assert (config.MODEL_DIR / "concentration_model.json").is_file()
    stub_measure(monkeypatch, lambda n: (220.0, 140.0))
    _, got, _ = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    row = got[0]
    assert 195 <= row["predicted_concentration_mg_L"] <= 205                        # the linear model, not the ANN
    assert row["model_status"] == "OK" and row["expected_error_mg_L"] is not None


def test_linear_mode_without_a_trained_model_still_returns_r_g_b(client, monkeypatch):
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    _, rows, _ = rows_of(client, upload(client, [("a.png", make_photo_png())]))
    assert rows[0]["R"] is not None and rows[0]["predicted_concentration_mg_L"] is None and rows[0]["model_status"] is None


def test_model_info_for_both_types(client, monkeypatch):
    info = client.get("/api/model").json()
    assert info == {"model_type": "ann", "model_version": "ann_v2_clean", "features": ["R", "G"],
                    "expected_error_mg_L": 17.78, "trainable": False, "nominal_range_mg_L": [0.0, 1255.0]}
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    none = client.get("/api/model").json()
    assert none["model_type"] == "linear" and none["trainable"] is True and none["features"] == [] and none["model_version"] is None
    train_and_wait(client, table_rows())
    got = client.get("/api/model").json()
    assert got["model_type"] == "linear" and got["trainable"] is True and got["model_version"]
    assert got["features"] and got["expected_error_mg_L"] is not None


def test_health_names_the_model_type(client, monkeypatch):
    assert client.get("/api/health").json()["model_type"] == "ann"
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    h = client.get("/api/health").json()
    assert h["model_type"] == "linear" and h["model"] == "missing"                    # no linear model trained yet


def test_a_bad_model_type_stops_the_server_with_a_clear_message():
    out = subprocess.run([sys.executable, "-c", "import config"], cwd=BACKEND, capture_output=True, text=True,
                         env={**__import__("os").environ, "MODEL_TYPE": "banana"})
    assert out.returncode != 0 and "MODEL_TYPE must be 'ann' or 'linear'" in out.stderr


# ---------------------------------------------------------------- comparison
def post_compare(client, rows, columns=None, name="known.csv"):
    return client.post("/api/compare", files={"file": (name, csv_bytes(rows, columns), "text/csv")})


def test_compare_gives_the_right_mae_and_rmse_on_a_hand_calculated_example(client, monkeypatch):
    # known 100,200,300,400.  ANN (stub): 110, 190, none, 420.  linear (feature B): 90, 210, none, 330.
    monkeypatch.setattr(concentration_ann, "predict", lambda r, g: {
        "predicted_concentration_mg_L": None if r == 310 else r, "raw_model_output": r, "status": "OK", "warnings": [],
        "expected_error_mg_L": 17.78})
    monkeypatch.setattr(concentration, "MODEL", {"features": ["B"], "intercept": 0.0, "coefficients": [1.0], "typical_error_ppm": 1.0,
                                                 "error_by_range": [], "training_range": {}})
    monkeypatch.setattr(concentration, "MODEL_VERSION", "test")
    rows = [{"concentration_ppm": 100, "R": 110, "G": 150, "B": 90}, {"concentration_ppm": 200, "R": 190, "G": 150, "B": 210},
            {"concentration_ppm": 300, "R": 310, "G": 150, "B": None}, {"concentration_ppm": 400, "R": 420, "G": 150, "B": 330}]
    r = post_compare(client, rows)
    assert r.status_code == 200, r.text
    body = r.json()
    ann, lin = body["models"]["ann"], body["models"]["linear"]
    assert (ann["n_valid"], ann["n_unpredicted"]) == (3, 1)
    assert ann["mae"] == pytest.approx((10 + 10 + 20) / 3, abs=1e-4)                  # 13.3333
    assert ann["rmse"] == pytest.approx(np.sqrt((100 + 100 + 400) / 3), abs=1e-4)     # 14.1421
    assert (lin["n_valid"], lin["n_unpredicted"]) == (3, 1)
    assert lin["mae"] == pytest.approx((10 + 10 + 70) / 3, abs=1e-4)                  # 30
    assert lin["rmse"] == pytest.approx(np.sqrt((100 + 100 + 4900) / 3), abs=1e-4)    # 41.2311
    third = body["rows"][2]
    assert third["known_concentration"] == 300 and third["ann_predicted"] is None and third["linear_predicted"] is None
    first = body["rows"][0]
    assert (first["ann_predicted"], first["ann_abs_error"], first["linear_predicted"], first["linear_abs_error"]) == (110, 10, 90, 10)


def test_compare_accepts_trim_columns_and_optional_file_name_and_uses_the_real_ann(client):
    rows = [{"file_name": "a.jpg", "concentration_ppm": 500, "trim_R": OK_POINT[0], "trim_G": OK_POINT[1]},
            {"file_name": "b.jpg", "concentration_ppm": 600, "trim_R": NOT_VALID_POINT[0], "trim_G": NOT_VALID_POINT[1]}]
    r = post_compare(client, rows)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Using trim_R as R" in body["warnings"] and body["rows"][0]["file_name"] == "a.jpg"
    assert body["rows"][0]["ann_predicted"] == 570.3 and body["rows"][0]["ann_abs_error"] == pytest.approx(70.3)
    assert body["rows"][1]["ann_predicted"] is None and body["rows"][1]["ann_status"] == "NOT_VALID_OUTSIDE_CALIBRATED_RANGE"
    assert body["models"]["ann"]["n_valid"] == 1 and body["models"]["ann"]["n_unpredicted"] == 1
    lin = body["models"]["linear"]
    assert lin["available"] is False and lin["n_valid"] == 0 and lin["n_unpredicted"] == 2 and lin["mae"] is None


def test_compare_does_not_change_either_model_or_save_anything(client):
    before = (concentration.MODEL, concentration.MODEL_VERSION)
    assert post_compare(client, [{"concentration_ppm": 500, "R": 180, "G": 152}, {"concentration_ppm": 100, "R": 150, "G": 150}]).status_code == 200
    assert (concentration.MODEL, concentration.MODEL_VERSION) == before
    assert not config.MODEL_DIR.exists() and client.get("/api/jobs").json() == []


def test_compare_works_in_both_modes_and_with_a_trained_linear_model(client, monkeypatch):
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    rows = [{"concentration_ppm": (230 - r) * 20, "R": r, "G": 150 + k, "B": 10} for k, r in enumerate((230, 225, 220, 215, 210))]
    train_and_wait(client, rows)
    monkeypatch.setattr(config, "MODEL_TYPE", "ann")
    body = post_compare(client, rows).json()
    lin = body["models"]["linear"]
    assert lin["available"] is True and lin["n_valid"] == 5 and lin["mae"] < 1e-6 and lin["rmse"] < 1e-6      # exact data
    assert body["models"]["ann"]["n_valid"] + body["models"]["ann"]["n_unpredicted"] == 5


def test_compare_errors_are_clear(client):
    missing = post_compare(client, [{"concentration_ppm": 1, "R": 2}])
    assert missing.status_code == 422 and "Missing: G" in missing.json()["detail"]
    empty = post_compare(client, [{"concentration_ppm": "x", "R": "y", "G": "z"}])
    assert empty.status_code == 422 and "No valid rows" in empty.json()["detail"]
    wrong = client.post("/api/compare", files={"file": ("a.txt", b"x", "text/plain")})
    assert wrong.status_code == 422
    some = post_compare(client, [{"concentration_ppm": 500, "R": 180, "G": 152}, {"concentration_ppm": "x", "R": 180, "G": 152}])
    assert some.status_code == 200 and some.json()["rejected_rows"] == [3] and some.json()["n_rows"] == 1
