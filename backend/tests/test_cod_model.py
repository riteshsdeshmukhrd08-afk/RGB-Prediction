"""The fixed COD model: prediction only. The web app has no training."""
import math
import pickle
import os
from pathlib import Path

import numpy as np
import pytest

import cod_model
import config

BACKEND = Path(__file__).resolve().parent.parent

# From the build script: the two sample inputs, as (R, G). Golden values come from the bundle's own pipeline,
# NOT from the colab cell's predict_cod (that file was not available when this test was written).
GOLDEN = {(219.9, 167.0): 233.25143977, (228.0, 165.8): 113.46212259}


@pytest.fixture(scope="module", autouse=True)
def model():
    cod_model.load()
    assert cod_model.is_ready()
    yield cod_model._BUNDLE


def test_the_bundle_is_the_expected_pipeline(model):
    reg = model["pipeline"].regressor_
    assert [n for n, _ in reg.steps] == ["standardscaler", "mlpregressor"]
    assert model["features"] == ["R", "G"] == cod_model.FEATURES
    assert model["calibration_nominal_range_mg_L"] == [100.0, 1250.0]
    sc = reg.named_steps["standardscaler"]
    assert np.allclose(sc.mean_, model["applicability"]["mean"])          # scaler and applicability: same scale


@pytest.mark.parametrize("rg,expected", GOLDEN.items())
def test_sample_inputs_match_the_pipeline_and_the_golden_values(model, rg, expected):
    out = cod_model.predict(*rg)
    direct = float(model["pipeline"].predict(np.array([rg]))[0])          # [R, G] order, already mg/L
    assert out["status"] == "ok" and out["warnings"] == []
    assert abs(out["cod_mg_l"] - direct) < 1e-6
    assert abs(out["cod_mg_l"] - expected) < 1e-6


def test_in_range_pair_gives_cod_in_mg_per_l():
    out = cod_model.predict(185.853, 163.778)
    assert out["status"] == "ok" and 100 <= out["cod_mg_l"] <= 1250


def test_r_and_g_are_not_interchangeable():
    assert cod_model.predict(219.9, 167.0)["cod_mg_l"] != cod_model.predict(167.0, 219.9).get("cod_mg_l")


@pytest.mark.parametrize("rg", [(230, 165), (131, 175), (228, 146), (185, 100), (255, 255), (0, 0)])
def test_out_of_range_or_out_of_domain_is_outside_range_without_a_number(rg):
    out = cod_model.predict(*rg)
    assert out["status"] == "outside range" and out["cod_mg_l"] is None and out["warnings"]


def test_a_prediction_outside_the_calibrated_range_is_outside_range(monkeypatch, model):
    monkeypatch.setitem(model, "calibration_nominal_range_mg_L", [100.0, 120.0])      # 233 mg/L is now outside
    out = cod_model.predict(219.9, 167.0)
    assert out["status"] == "outside range" and out["cod_mg_l"] is None
    assert any("calibrated range" in w for w in out["warnings"])


@pytest.mark.parametrize("r,g,word", [(None, 160, "R"), (190, None, "G"), ("abc", 160, "R"), (190, "", "G"), ("12,5", 160, "R"),
                                      (math.nan, 160, "R"), (190, math.inf, "G"), (-1, 160, "R"), (190, 300, "G"), (True, 160, "R")])
def test_missing_or_bad_input_is_a_clear_error(r, g, word):
    with pytest.raises(cod_model.CodInputError) as e:
        cod_model.predict(r, g)
    assert str(e.value).startswith(word) and len(str(e.value)) > 15


def test_numeric_strings_are_accepted():
    assert cod_model.predict("185.853", "163.778")["status"] == "ok"


def test_the_model_is_loaded_at_startup_and_never_per_request(client, monkeypatch):
    from conftest import make_photo_png, upload
    assert client.get("/api/health").json()["model"] == "loaded"
    calls = []
    monkeypatch.setattr(cod_model, "_read_bundle", lambda p: calls.append(p))
    for _ in range(3):
        assert upload(client, [("a.png", make_photo_png())]).status_code == 202
    assert calls == []


def test_only_the_fixed_file_is_loaded():
    assert config.COD_MODEL_PATH == BACKEND / "models" / "cod_ann_model_bundle.joblib"
    assert config.COD_MODEL_PATH.is_file()


# ---- the loader: exactly the 11 classes of the real bundle, nothing else -----------------------------
def _pickle_calling(func, *args):
    """A joblib file that, if it were ever loaded unrestricted, would call func(*args). The payloads are harmless
    (they only print / exit / evaluate '1'), but a loader that lets them through is broken."""
    class Payload:
        def __reduce__(self):
            return (func, args)
    return {"x": Payload()}


def _dump(tmp_path, obj, name="m.joblib"):
    import joblib
    path = tmp_path / name
    joblib.dump(obj, path)
    return path


def _calls():
    import subprocess
    import joblib
    from numpy.testing._private.utils import runstring
    return {
        "os.system": (os.system, "exit 0"),
        "subprocess.check_output": (subprocess.check_output, ["python", "-c", "pass"]),
        "builtins.eval": (eval, "1"),
        "numpy.testing runstring": (runstring, "x = 1", {}),
        "joblib.Parallel": (joblib.Parallel, 1),
        "numpy.load": (np.load, "nothing.npy"),
    }


@pytest.mark.parametrize("label", list(_calls()))
def test_code_running_pickles_are_refused(tmp_path, label):
    path = _dump(tmp_path, _pickle_calling(*_calls()[label]))
    with pytest.raises(RuntimeError, match="not allowed"):
        cod_model._read_bundle(path)


def test_a_refused_file_never_becomes_the_model(tmp_path):
    keep = cod_model._BUNDLE
    try:
        assert cod_model.load(_dump(tmp_path, _pickle_calling(os.system, "exit 0"))) is None
        assert not cod_model.is_ready()                       # the app keeps running, without COD
    finally:
        cod_model._BUNDLE = keep


def test_other_classes_of_the_same_packages_are_refused_too(tmp_path):
    """Allowing a whole package was the old rule. A harmless sklearn model that is not ours is refused as well."""
    from sklearn.linear_model import LinearRegression
    path = _dump(tmp_path, {"m": LinearRegression().fit([[0.0], [1.0]], [0.0, 1.0])})
    with pytest.raises(RuntimeError, match="LinearRegression"):
        cod_model._read_bundle(path)


def test_the_allowlist_is_exactly_the_eleven_classes_the_real_bundle_uses(monkeypatch):
    assert len(cod_model.ALLOWED_CLASSES) == 11
    asked = []
    original = cod_model._RestrictedUnpickler.find_class

    def record(self, module, name):
        asked.append((module, name))
        return original(self, module, name)

    monkeypatch.setattr(cod_model._RestrictedUnpickler, "find_class", record)
    bundle = cod_model._read_bundle(config.COD_MODEL_PATH)
    assert set(asked) == set(cod_model.ALLOWED_CLASSES)       # nothing allowed that is not needed, nothing missing
    assert bundle["features"] == ["R", "G"]
    assert not any(m.split(".")[0] in ("os", "subprocess", "builtins", "posix", "nt") for m, _ in cod_model.ALLOWED_CLASSES)
    assert ("numpy.testing._private.utils", "runstring") not in cod_model.ALLOWED_CLASSES


def test_the_real_bundle_loads_and_still_passes_the_startup_prediction_check():
    keep = cod_model._BUNDLE
    try:
        loaded = cod_model.load()                              # _check_bundle runs a real prediction inside load()
        assert loaded is not None and cod_model.is_ready()
        assert loaded["model_version"] == "COD-ANN-RG-v1.0"
    finally:
        cod_model._BUNDLE = keep


def test_a_bundle_that_fails_the_startup_prediction_check_is_not_used(tmp_path, monkeypatch):
    keep = cod_model._BUNDLE
    try:
        real = cod_model._read_bundle(config.COD_MODEL_PATH)
        real["features"] = ["G", "R"]                          # wrong feature order must be caught at startup
        monkeypatch.setattr(cod_model, "_read_bundle", lambda p: real)
        assert cod_model.load() is None and not cod_model.is_ready()
    finally:
        cod_model._BUNDLE = keep


def test_the_model_file_is_read_exactly_once_at_startup_and_never_again(monkeypatch, tmp_path):
    from conftest import _start, make_photo_png, upload
    calls = []
    real = cod_model._read_bundle

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(cod_model, "_read_bundle", counting)
    with _start(monkeypatch, tmp_path) as c:
        assert len(calls) == 1 and calls[0] == config.COD_MODEL_PATH       # startup
        for _ in range(3):
            assert upload(c, [("a.png", make_photo_png())]).status_code == 202
        c.get("/api/health")
        assert len(calls) == 1                                              # requests never reload it


def test_an_unreadable_model_leaves_cod_empty_instead_of_crashing_the_job(client, monkeypatch):
    from conftest import make_photo_png, upload
    keep = cod_model._BUNDLE
    monkeypatch.setattr(cod_model, "_BUNDLE", None)
    r = upload(client, [("a.png", make_photo_png())])
    job_id = r.json()["job_id"]
    row = client.get(f"/api/jobs/{job_id}/results").json()["results"][0]
    assert row["status"] == "ok" and row["cod_mg_l"] is None and "not loaded" in row["warning"]
    assert client.get("/api/health").json()["model"] == "missing"
    cod_model._BUNDLE = keep


# ---- there is no training ---------------------------------------------------------------------
@pytest.mark.parametrize("method,url", [("get", "/api/train/current"), ("get", "/api/train/current/report"),
                                        ("get", "/api/train/abc"), ("post", "/api/train"), ("post", "/api/train/preview"),
                                        ("get", "/api/train")])
def test_old_training_routes_are_gone(client, method, url):
    r = getattr(client, method)(url)
    assert r.status_code == 404, (url, r.status_code)


def test_no_training_or_old_model_code_is_part_of_the_server():
    import importlib
    for name in ("training", "concentration"):
        with pytest.raises(ImportError):
            importlib.import_module(name)
    for f in ("main.py", "measure_service.py", "cod_model.py", "db.py", "config.py"):
        text = (BACKEND / f).read_text(encoding="utf8").lower()
        assert "/api/train" not in text and "fit_model" not in text and "train_jobs" not in text, f
