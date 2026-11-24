"""
ANN v1.1: the model file, loading, prediction rules, 503 when it is unavailable, compare.
The expected values come from calling the bundle's own pipeline, never from numbers copied out of the code under test.
"""

import hashlib
import io
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import ann_v1_1
import config
import measure_service
from conftest import make_photo_png, train, upload

FOUR = [(219.9, 167), (228, 165.8), (180, 160), (141, 149)]
# what pipeline.predict gives for FOUR with the pinned library versions (reported in the delivery notes)
FOUR_RAW = [137.43396817, 75.78919427, 584.71506529, 846.91506803]


@pytest.fixture
def bundle():
    assert ann_v1_1.load(), ann_v1_1.status()
    return ann_v1_1.get()


class Stub:
    """A pipeline that always predicts one value."""
    def __init__(self, value):
        self.value = value

    def predict(self, x):
        return np.full(len(x), self.value)


def with_value(bundle, value):
    return {**bundle, "pipeline": Stub(value)}


# ------------------------------------------------------------------ the file
def test_sha256_matches_the_pinned_value():
    digest = hashlib.sha256(config.MODEL_BUNDLE_PATH.read_bytes()).hexdigest()
    assert digest == config.MODEL_BUNDLE_SHA256
    pinned_file = (Path(config.BASE_DIR) / "models" / "ann_v1_1.sha256").read_text().split()[0]
    assert pinned_file == config.MODEL_BUNDLE_SHA256
    assert config.MODEL_BUNDLE_PATH.name == "ann_v1_1.joblib"


def test_bundle_loads_with_the_expected_features(bundle):
    assert bundle["features"] == ["R", "G"]
    assert callable(bundle["pipeline"].predict)
    assert ann_v1_1.status() == {"model": "loaded"}
    info = ann_v1_1.info()
    assert info == {"model_type": "ann", "model_name": "ANN v1.1", "features": ["R", "G"],
                    "expected_error_mg_L": bundle["expected_error_mg_L_test_RMSEP"],
                    "nominal_range_mg_L": [100.0, 1250.0], "training_max_mg_L": 1232.0, "trainable": False}
    assert bundle["training_rows"] == 155 and 33.9 < info["expected_error_mg_L"] < 34.0


def test_app_never_shows_the_bundles_own_model_name(bundle):
    shown = repr(ann_v1_1.info()) + repr(ann_v1_1.predict(180, 160, bundle)) + repr(ann_v1_1.status())
    assert str(bundle["model_version"]) not in shown


# ------------------------------------------------------------------ prediction
@pytest.mark.parametrize("rg,raw", zip(FOUR, FOUR_RAW))
def test_prediction_equals_pipeline_predict(bundle, rg, raw):
    direct = float(bundle["pipeline"].predict(np.array([list(rg)]))[0])
    res = ann_v1_1.predict(*rg, bundle)
    assert direct == pytest.approx(raw, abs=1e-6)
    assert res["raw_model_output"] == round(direct, 1)
    assert res["expected_error_mg_L"] == bundle["expected_error_mg_L_test_RMSEP"]
    if 100 <= direct <= 1250:
        assert res["predicted_concentration_mg_L"] == round(direct, 1)
    else:
        assert res["predicted_concentration_mg_L"] is None and res["status"] == ann_v1_1.STATUS_NOT_VALID


def test_predict_has_no_b_argument():
    import inspect
    assert list(inspect.signature(ann_v1_1.predict).parameters) == ["R", "G", "bundle"]


INSIDE = (180.0, 152.0)          # inside the applicability box and the distance limit


@pytest.mark.parametrize("value,status,has_value", [
    (500.0, "OK", True), (1000.0, "OK", True), (1100.0, "OK", True), (1232.0, "OK", True),
    (1232.5, "REVIEW", True), (1240.0, "REVIEW", True), (1250.0, "REVIEW", True), (1300.0, "NOT_VALID_OUTSIDE_CALIBRATED_RANGE", False),
    (99.9, "NOT_VALID_OUTSIDE_CALIBRATED_RANGE", False), (100.0, "OK", True)])
def test_status_from_the_predicted_value(bundle, value, status, has_value):
    res = ann_v1_1.predict(*INSIDE, with_value(bundle, value))
    assert res["status"] == status
    assert (res["predicted_concentration_mg_L"] is not None) == has_value
    if value > 1232 and has_value:
        assert res["warnings"] == ["Above the highest concentration in the training data (1232 mg/L). Confirm with a standard."]
    if status == "OK":
        assert res["warnings"] == []


def test_not_valid_wins_over_review_and_gives_no_value(bundle):
    res = ann_v1_1.predict(100, 100, with_value(bundle, 1300.0))      # also far outside the region
    assert res["status"] == ann_v1_1.STATUS_NOT_VALID and res["predicted_concentration_mg_L"] is None


def test_the_review_limit_is_read_from_the_bundle_not_hard_coded(bundle):
    assert not hasattr(config, "REVIEW_ABOVE_MG_L")
    assert bundle["calibration_observed_range_mg_L"] == [100.0, 1232.0]
    changed = {**with_value(bundle, 1150.0), "calibration_observed_range_mg_L": [100.0, 1100.0]}
    res = ann_v1_1.predict(*INSIDE, changed)
    assert res["status"] == "REVIEW" and "(1100 mg/L)" in res["warnings"][0]


@pytest.mark.parametrize("rg", [(121.0, 152.0), (226.0, 152.0), (180.0, 145.0), (180.0, 164.0)])
def test_outside_the_applicability_box_is_review(bundle, rg):
    ad = bundle["applicability"]
    assert np.any(np.array(rg) < ad["min"]) or np.any(np.array(rg) > ad["max"])      # the premise
    res = ann_v1_1.predict(*rg, with_value(bundle, 500.0))
    assert res["status"] == "REVIEW" and res["warnings"] == ["Outside the calibrated region. Confirm with a standard."]
    assert res["predicted_concentration_mg_L"] == 500.0


def test_distance_check_alone_gives_review(bundle):
    ad = bundle["applicability"]
    mean, cov_inv = np.array(ad["mean"]), np.array(ad["cov_inv"])
    point = np.array([ad["max"][0], ad["min"][1]])                    # a corner of the box: far from the data
    d = point - mean
    assert np.all(point >= ad["min"]) and np.all(point <= ad["max"])
    assert d @ cov_inv @ d > ad["d2_threshold"]                       # the premise: only the distance test fails
    res = ann_v1_1.predict(*point, with_value(bundle, 500.0))
    assert res["status"] == "REVIEW" and res["warnings"] == ["Outside the calibrated region. Confirm with a standard."]
    assert ann_v1_1.predict(*mean, with_value(bundle, 500.0))["status"] == "OK"


def test_both_review_reasons_give_both_warnings(bundle):
    res = ann_v1_1.predict(100, 100, with_value(bundle, 1240.0))
    assert res["status"] == "REVIEW"
    assert res["warnings"] == ["Above the highest concentration in the training data (1232 mg/L). Confirm with a standard.",
                               "Outside the calibrated region. Confirm with a standard."]


REGION = "Outside the calibrated region. Confirm with a standard."


@pytest.mark.parametrize("rg,status,warnings_,value", [
    # G 167 is above the box maximum (163) and the distance test fails too
    ((219.9, 167), "REVIEW", [REGION], 137.4),
    # R 228 and G 165.8 are above the box, but the value 75.8 is below 100: NOT_VALID comes first, no value, no warnings
    ((228, 165.8), "NOT_VALID_OUTSIDE_CALIBRATED_RANGE", [], None),
    # R 180 and G 160 are INSIDE the box (G max is 163): only the distance test (d2 23.07 > 9.21) gives the review
    ((180, 160), "REVIEW", [REGION], 584.7),
    ((141, 149), "OK", [], 846.9),
])
def test_the_four_fixtures_keep_their_status_and_warnings(bundle, rg, status, warnings_, value):
    res = ann_v1_1.predict(*rg, bundle)
    assert (res["status"], res["warnings"], res["predicted_concentration_mg_L"]) == (status, warnings_, value)


def test_the_bundles_applicability_box_is_the_training_range(bundle):
    ad = bundle["applicability"]
    assert (ad["min"], ad["max"], ad["n_train"]) == ([122.0, 146.0], [225.0, 163.0], 155)
    assert ad["d2_threshold"] == pytest.approx(9.21034037197618)


@pytest.mark.parametrize("rg", [(300, 152), (180, 300), (-1, 152), (180, 255.5)])
def test_r_or_g_outside_0_255_raises_value_error(bundle, rg):
    with pytest.raises(ValueError, match="must be in 0-255"):
        ann_v1_1.predict(*rg, bundle)


def test_failed_row_when_r_is_300_and_the_job_goes_on(bundle, tmp_path, monkeypatch):
    path = tmp_path / "p.png"
    path.write_bytes(make_photo_png())
    m = {"trim_R": 300.0, "trim_G": 152.0, "trim_B": 40.0, "valid_pixels": 5000, "status": "ok", "clip_frac": 0.0,
         "std_R": 1.0, "std_G": 1.0, "std_B": 1.0, "roi_w": 90}
    monkeypatch.setattr(measure_service, "measure_photo", lambda p: (m, None))
    row, qc = measure_service.analyze_image(path, None, "ann")
    assert row["status"] == "failed" and row["error"] == "R=300.0 must be in 0-255" and qc is None
    assert row["predicted_concentration_mg_L"] is None


def test_model_not_loaded_raises_model_unavailable(monkeypatch):
    monkeypatch.setitem(ann_v1_1._state, "bundle", None)
    monkeypatch.setitem(ann_v1_1._state, "error", "gone")
    with pytest.raises(ann_v1_1.ModelUnavailable, match="gone"):
        ann_v1_1.predict(180, 152)


# ------------------------------------------------------------------ the model is unavailable
@pytest.fixture(params=["missing", "wrong_hash", "wrong_sklearn_version", "wrong_features"])
def bad_model(request, monkeypatch, tmp_path):
    """Breaks the model BEFORE the app starts (declare it before `client`). Returns the expected reason text."""
    kind = request.param
    if kind == "missing":
        monkeypatch.setattr(config, "MODEL_BUNDLE_PATH", tmp_path / "nothing.joblib")
        return "not found"
    if kind == "wrong_hash":
        other = tmp_path / "other.joblib"
        other.write_bytes(config.MODEL_BUNDLE_PATH.read_bytes() + b"x")
        monkeypatch.setattr(config, "MODEL_BUNDLE_PATH", other)
        return "pinned SHA-256"
    import joblib
    real = joblib.load
    if kind == "wrong_sklearn_version":
        from sklearn.exceptions import InconsistentVersionWarning

        def load(path, *a, **k):
            out = real(path, *a, **k)
            warnings.warn(InconsistentVersionWarning(estimator_name="Pipeline", current_sklearn_version="9.9.9",
                                                     original_sklearn_version="1.9.1"))
            return out
        monkeypatch.setattr(joblib, "load", load)
        return "scikit-learn version"
    monkeypatch.setattr(joblib, "load", lambda path, *a, **k: {**real(path, *a, **k), "features": ["R", "G", "B"]})
    return "features"


def test_unavailable_model_is_reported_and_jobs_get_503(bad_model, client):
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["model"] == "unavailable" and bad_model in body["model_error"] and body["model_type"] == "ann"
    r = upload(client, [("tube.png", make_photo_png())])
    assert r.status_code == 503 and bad_model in r.json()["detail"]
    assert client.get("/api/model-info").status_code == 503
    assert client.get("/api/jobs").status_code == 200                  # the rest of the app works


def test_unavailable_model_makes_compare_report_it_not_crash(bad_model, client):
    df = pd.DataFrame({"concentration_ppm": [500.0], "R": [180.0], "G": [152.0]})
    r = client.post("/api/compare", files={"file": ("k.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["models"]["ann"]["available"] is False and body["models"]["ann"]["n_valid"] == 0
    assert any("not available" in w for w in body["warnings"])


def test_the_loader_reads_no_other_path_than_the_repository_file():
    import inspect
    src = inspect.getsource(ann_v1_1)
    assert "joblib.load(path)" in src and "def load(path=None, expected_sha256=None)" in src
    import main
    assert "ann_v1_1.load()" in inspect.getsource(main.lifespan)       # no route calls load


# ------------------------------------------------------------------ MODEL_TYPE
def test_ann_mode_refuses_training_with_409(client):
    r = train(client, "t.csv", b"concentration_ppm,R,G\n1,2,3\n")
    assert r.status_code == 409
    assert r.json()["detail"] == ("The ANN model is fixed and cannot be trained here. "
                                  "Set MODEL_TYPE=linear to train the linear model.")


def test_model_info_endpoint(client, bundle):
    r = client.get("/api/model-info")
    assert r.status_code == 200 and r.json() == ann_v1_1.info(bundle)
    assert r.json()["model_name"] == "ANN v1.1" and r.json()["trainable"] is False


def test_linear_mode_does_not_need_or_load_the_ann(client, monkeypatch):
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")
    body = client.get("/api/health").json()
    assert body["model_type"] == "linear" and body["model"] == "missing"
    info = client.get("/api/model-info").json()
    assert info["model_type"] == "linear" and info["trainable"] is True


# ------------------------------------------------------------------ compare
def test_compare_hand_calculated(client, bundle):
    # known = the ANN's own value plus a chosen offset, so the errors are exactly 10, 20 and 30 mg/L
    pts = [(219.9, 167), (180, 160), (141, 149)]
    offsets = [10.0, -20.0, 30.0]
    rows = []
    for (r, g), off in zip(pts, offsets):
        rows.append({"file_name": f"f{len(rows)}.jpg", "concentration_ppm": ann_v1_1.predict(r, g, bundle)["predicted_concentration_mg_L"] + off,
                     "R": r, "G": g})
    rows.append({"file_name": "low.jpg", "concentration_ppm": 100.0, "R": 228, "G": 165.8})      # ANN: not valid (75.8)
    data = pd.DataFrame(rows).to_csv(index=False).encode()
    r = client.post("/api/compare", files={"file": ("k.csv", data, "text/csv")})
    assert r.status_code == 200
    ann = r.json()["models"]["ann"]
    assert ann["n_rows"] == 4 and ann["n_valid"] == 3 and ann["n_unpredicted"] == 1
    assert ann["mae"] == pytest.approx(20.0, abs=1e-3)                                  # (10 + 20 + 30) / 3
    assert ann["rmse"] == pytest.approx(((100 + 400 + 900) / 3) ** 0.5, abs=1e-3)       # 21.6025
    assert ann["model_name"] == "ANN v1.1" and r.json()["models"]["linear"]["available"] is False
    assert r.json()["rows"][3]["ann_predicted"] is None and r.json()["rows"][3]["ann_status"] == ann_v1_1.STATUS_NOT_VALID


# ------------------------------------------------------------------ a job in ann mode
def test_job_completes_in_ann_mode_without_a_linear_model(client, tmp_path):
    assert not config.MODEL_DIR.exists()
    r = upload(client, [("tube.png", make_photo_png())])
    assert r.status_code == 202
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done"
    row = client.get(f"/api/jobs/{r.json()['job_id']}/results").json()["results"][0]
    assert row["status"] == "ok" and row["expected_error_mg_L"] == pytest.approx(33.9378, abs=1e-3)
