import csv
import io
import json
import re
from pathlib import Path

import numpy as np
import openpyxl
import pytest

import concentration
import config
import training
from conftest import (TRUE_G, TRUE_INTERCEPT, TRUE_R, csv_bytes, levels_rows, make_photo_png, make_small_png,
                      table_rows, train, trained_client_session, true_ppm, upload, wait_training, xlsx_bytes)


@pytest.fixture(autouse=True)
def linear_mode(monkeypatch):
    """The ANN is fixed and cannot be trained: these tests are about the linear model."""
    monkeypatch.setattr(config, "MODEL_TYPE", "linear")

TOLERANCE = 1e-6          # the synthetic data follow the relation exactly


def model_file():
    return json.loads((config.MODEL_DIR / "concentration_model.json").read_text(encoding="utf-8"))


def assert_recovers_known_values(rows):
    model = model_file()
    assert model["features"] == ["R", "G"]
    assert abs(model["intercept"] - TRUE_INTERCEPT) < TOLERANCE
    assert abs(model["coefficients"][0] - TRUE_R) < TOLERANCE and abs(model["coefficients"][1] - TRUE_G) < TOLERANCE
    for r in rows:                                               # every known concentration is recovered
        ppm, _, _ = concentration.predict(model, {"R": r["R"], "G": r["G"], "B": r["B"]})
        assert abs(ppm - r["concentration_ppm"]) < 0.06           # predictions are rounded to 0.1 ppm


# ---------------------------------------------------------------- training from CSV and XLSX
def test_training_from_csv_recovers_known_concentrations(client):
    rows = table_rows()
    r = train(client, "known.csv", csv_bytes(rows))
    assert r.status_code == 202 and set(r.json()) == {"job_id", "status"}
    job = wait_training(client, r.json()["job_id"])
    assert set(job) == {"job_id", "status", "progress", "warnings", "error"}
    assert job["status"] == "done" and job["error"] is None
    assert_recovers_known_values(rows)
    assert client.get("/api/health").json()["model"] == "loaded"


def test_training_from_xlsx_recovers_known_concentrations(client):
    rows = table_rows(seed=7)
    job = wait_training(client, train(client, "known.xlsx", xlsx_bytes(rows)).json()["job_id"])
    assert job["status"] == "done", job
    assert_recovers_known_values(rows)


def test_one_row_per_concentration_is_accepted(client):
    rows = [{"concentration_ppm": p, "R": 230 - p / 10, "G": 200 - p / 5, "B": 20} for p in (0, 100, 200, 300, 400)]
    job = wait_training(client, train(client, "levels.csv", csv_bytes(rows)).json()["job_id"])
    assert job["status"] == "done"
    assert model_file()["validated"] is True and model_file()["n_concentrations"] == 5


def test_the_apps_own_result_csv_is_valid_once_a_concentration_column_is_added(client):
    # a results file as the app downloads it, plus the user's concentration_ppm column; failed rows are ignored
    header = ["file_name", "page", "status", "R", "G", "B", "predicted_concentration_mg_L", "expected_error_mg_L",
              "model_status", "flags", "warning", "error", "image_url", "concentration_ppm"]
    lines = [header]
    for i, p in enumerate((0, 100, 200, 300, 400)):
        lines.append([f"p{i}.jpg", "", "ok", 230 - p / 10, 200 - p / 5, 20, "", "", "", "", "", "", "", p])
    lines.append(["bad.jpg", "", "failed", "", "", "", "", "", "", "failed", "", "no tube found", "", 100])
    buf = io.StringIO()
    csv.writer(buf).writerows(lines)
    r = train(client, "results.csv", buf.getvalue().encode("utf-8"))
    assert r.status_code == 202, r.text
    job = wait_training(client, r.json()["job_id"])
    assert job["status"] == "done" and any("Ignored row(s) 7" in w for w in job["warnings"])


# ---------------------------------------------------------------- rejections
def test_missing_column_is_rejected_with_422(client):
    r = train(client, "t.csv", csv_bytes(table_rows(), columns=["concentration_ppm", "R", "G"]))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Found: concentration_ppm, R, G. Missing: B.")


def test_single_concentration_is_rejected_with_422(client):
    r = train(client, "t.csv", csv_bytes(levels_rows([100], per=5)))
    assert r.status_code == 422
    assert r.json()["detail"] == "Only one concentration (100 ppm) found. Training needs at least 2."
    assert not (config.MODEL_DIR / "concentration_model.json").exists()


def test_non_numeric_rows_are_ignored_and_their_numbers_listed(client):
    rows = table_rows()
    rows[2]["G"] = "n/a"                     # spreadsheet row 4 (row 1 is the header)
    rows[5]["R"] = None                      # spreadsheet row 7
    r = train(client, "t.csv", csv_bytes(rows))
    assert r.status_code == 202
    job = wait_training(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert any("Ignored row(s) 4, 7" in w for w in job["warnings"])
    assert model_file()["n_rows"] == len(rows) - 2


def test_all_rows_invalid_is_rejected_with_422(client):
    rows = [{"concentration_ppm": "x", "R": "a", "G": "b", "B": "c"} for _ in range(3)]
    r = train(client, "t.csv", csv_bytes(rows))
    assert r.status_code == 422 and "No valid rows" in r.json()["detail"]


def test_wrong_file_type_and_unreadable_file_give_422(client):
    assert train(client, "t.txt", b"a,b").status_code == 422
    assert train(client, "t.xlsx", b"this is not a spreadsheet").status_code == 422
    assert train(client, "t.csv", b"").status_code == 422


def test_second_training_request_while_one_runs_gives_409(client):
    assert training.lock.acquire(blocking=False)                 # pretend a training is running
    try:
        assert train(client, "t.csv", csv_bytes(table_rows())).status_code == 409
    finally:
        training.lock.release()


# ---------------------------------------------------------------- the app's own exports are accepted
def batch_export_rows(levels=(0, 100, 200, 300, 400), per=2, channels=("trim_R", "trim_G", "trim_B")):
    """Rows like the older batch_features export: a folder such as '449 ppm', image, and trim_R/G/B."""
    rows = []
    for p in levels:
        for k in range(per):
            rows.append({"folder": f"part1/{p} ppm", "image": f"IMG_{p}_{k}.jpg", "status": "ok",
                         channels[0]: 230 - p / 10 + k, channels[1]: 200 - p / 5 - k, channels[2]: 20.0})
    return rows


def test_batch_export_with_trim_columns_and_a_folder_column_is_accepted(client):
    rows = batch_export_rows()
    body = client.post("/api/train/preview", files={"file": ("batch_features.csv", csv_bytes(rows), "text/csv")}).json()
    assert body["valid"] is True and body["errors"] == []
    assert body["mappings"] == ["Using the number in column folder (such as '449 ppm') as concentration_ppm",
                                "Using trim_R as R", "Using trim_G as G", "Using trim_B as B", "Using image as file_name"]
    assert all(m in body["warnings"] for m in body["mappings"])                   # also in the warnings list
    assert [c["ppm"] for c in body["concentrations"]] == [0, 100, 200, 300, 400]
    r = train(client, "batch_features.csv", csv_bytes(rows))
    assert r.status_code == 202, r.text
    job = wait_training(client, r.json()["job_id"])
    assert job["status"] == "done" and "Using trim_R as R" in job["warnings"]
    assert model_file()["n_concentrations"] == 5


def test_mean_columns_are_used_when_there_are_no_trim_columns(client):
    rows = batch_export_rows(channels=("mean_R", "mean_G", "mean_B"))
    body = client.post("/api/train/preview", files={"file": ("b.csv", csv_bytes(rows), "text/csv")}).json()
    assert body["valid"] is True and "Using mean_R as R" in body["mappings"]


def test_plain_column_names_win_over_alternatives(client):
    rows = [{"concentration_ppm": p, "R": 230 - p / 10, "trim_R": 1, "G": 200 - p / 5, "B": 20, "folder": "9 ppm"}
            for p in (0, 100, 200, 300)]
    body = client.post("/api/train/preview", files={"file": ("b.csv", csv_bytes(rows), "text/csv")}).json()
    assert body["valid"] is True and body["mappings"] == []
    assert [c["ppm"] for c in body["concentrations"]] == [0, 100, 200, 300]


def test_missing_values_are_named_with_the_columns_that_were_found(client):
    rows = [{"image": "a.jpg", "trim_R": 1, "trim_G": 2, "trim_B": 3, "folder": "no number here"}]
    r = train(client, "b.csv", csv_bytes(rows))
    assert r.status_code == 422
    assert r.json()["detail"] == ("Found: image, trim_R, trim_G, trim_B, folder. Missing: concentration_ppm. "
                                  "Add a concentration_ppm column in ppm.")


def test_one_concentration_in_a_batch_export_is_rejected_with_its_value(client):
    rows = batch_export_rows(levels=(449,), per=6)
    preview = client.post("/api/train/preview", files={"file": ("b.csv", csv_bytes(rows), "text/csv")}).json()
    assert preview["valid"] is False
    assert preview["errors"] == ["Only one concentration (449 ppm) found. Training needs at least 2."]
    r = train(client, "b.csv", csv_bytes(rows))
    assert r.status_code == 422
    assert r.json()["detail"] == "Only one concentration (449 ppm) found. Training needs at least 2."


def test_non_numeric_batch_values_are_listed_by_row(client):
    rows = batch_export_rows()
    rows[1]["trim_G"] = "bad"                      # spreadsheet row 3
    body = client.post("/api/train/preview", files={"file": ("b.csv", csv_bytes(rows), "text/csv")}).json()
    assert body["rejected_rows"] == [3] and any("Ignored row(s) 3" in w for w in body["warnings"])


# ---------------------------------------------------------------- validation and report
def test_four_or_more_concentrations_are_validated_leave_one_out(client):
    trained_client_session(client)
    m = model_file()
    assert m["validated"] is True and m["validation"] == "leave-one-concentration-out"
    assert m["typical_error_ppm"] < 1e-6                           # exact data: no error
    assert [c["features"] for c in m["candidates"]] == [["R", "G"], ["R"], ["G"], ["R", "G", "B"]]
    assert all(c["RMSE_ppm"] is not None for c in m["candidates"])


def test_two_or_three_concentrations_are_reported_as_not_validated(client):
    r = train(client, "t.csv", csv_bytes(levels_rows([100, 300, 500])))
    job = wait_training(client, r.json()["job_id"])
    assert job["status"] == "done" and any("not validated" in w for w in job["warnings"])
    m = model_file()
    assert m["validated"] is False and m["validation"] == "in-sample only, not validated"
    assert len(m["features"]) == 1                               # too few concentrations for 2+ features
    assert [c["skipped"] != "" for c in m["candidates"]] == [True, False, False, True]


def test_error_by_concentration_range(client):
    rows = levels_rows([50, 150, 250, 450, 650, 800], per=2)
    for i, r in enumerate(rows):
        r["R"] += (i % 3) * 0.5                                   # a little noise so errors are not zero
    wait_training(client, train(client, "t.csv", csv_bytes(rows)).json()["job_id"])
    ranges = {r["range_ppm"]: r for r in model_file()["error_by_range"]}
    assert set(ranges) == {"0-200", "200-600", "600+"}
    assert ranges["0-200"]["n_rows"] == 4 and ranges["200-600"]["n_rows"] == 4 and ranges["600+"]["n_rows"] == 4
    assert all(r["RMSE_ppm"] > 0 for r in ranges.values())


def test_current_model_and_report_endpoints(client):
    assert client.get("/api/train/current").status_code == 404
    assert client.get("/api/train/current/report").status_code == 404
    trained_client_session(client)
    cur = client.get("/api/train/current").json()
    assert cur["features"] == ["R", "G"] and cur["validated"] is True and cur["n_concentrations"] == 24
    assert cur["model_version"] and cur["trained_at"] and cur["source_file"] == "known.csv"
    assert set(cur) == {"model_version", "features", "intercept", "coefficients", "typical_error_ppm", "validated",
                        "validation", "n_rows", "n_concentrations", "training_range", "source_file", "trained_at"}
    rep = client.get("/api/train/current/report").json()
    assert rep["candidates"] and rep["error_by_range"] and rep["model_version"] == cur["model_version"]


def test_model_is_backed_up_and_written_atomically(client):
    trained_client_session(client)
    trained_client_session(client, table_rows(seed=2))
    files = sorted(p.name for p in config.MODEL_DIR.iterdir())
    assert "concentration_model.json" in files
    assert len([f for f in files if re.fullmatch(r"concentration_model\.\d{8}T\d+\.json", f)]) == 1   # the first, kept
    assert not any(f.endswith(".tmp") for f in files)


def test_preview_endpoint(client):
    rows = table_rows(8)
    body = client.post("/api/train/preview", files={"file": ("t.csv", csv_bytes(rows), "text/csv")}).json()
    assert body["valid"] is True and body["n_rows"] == 8 and len(body["preview"]) == 5
    assert body["columns"] == ["file_name", "concentration_ppm", "R", "G", "B"] and body["mappings"] == []
    assert sum(c["rows"] for c in body["concentrations"]) == 8
    bad = client.post("/api/train/preview", files={"file": ("t.csv", csv_bytes(rows, ["R", "G"]), "text/csv")})
    assert bad.status_code == 200 and bad.json()["valid"] is False and bad.json()["errors"]
    assert client.post("/api/train/preview", files={"file": ("t.txt", b"x", "text/plain")}).status_code == 422


# ---------------------------------------------------------------- prediction with and without a model
def test_prediction_with_a_model_returns_concentration_and_error(client):
    # the model: concentration depends on R only, exactly  ppm = (230 - R) * 20
    rows = [{"concentration_ppm": (230 - r) * 20, "R": r, "G": 100 + k, "B": 10} for k, r in enumerate((230, 225, 220, 215, 210))]
    wait_training(client, train(client, "t.csv", csv_bytes(rows)).json()["job_id"])
    assert model_file()["features"] == ["R"]
    r = upload(client, [("tube.png", make_photo_png())])               # a photo with R about 220
    row = client.get(f"/api/jobs/{r.json()['job_id']}/results").json()["results"][0]
    assert row["status"] == "ok" and 195 <= row["predicted_concentration_mg_L"] <= 205
    assert row["expected_error_mg_L"] is not None and row["warning"] == ""
    csv_text = client.get(f"/api/jobs/{r.json()['job_id']}/download?format=csv").text
    parsed = list(csv.DictReader(io.StringIO(csv_text)))[0]
    assert float(parsed["predicted_concentration_mg_L"]) == row["predicted_concentration_mg_L"]


def test_photo_outside_the_training_range_is_flagged_but_still_predicted(client):
    rows = [{"concentration_ppm": (230 - r) * 20, "R": r, "G": 100 + k, "B": 10} for k, r in enumerate((230, 225, 220, 215, 210))]
    wait_training(client, train(client, "t.csv", csv_bytes(rows)).json()["job_id"])
    far = make_small_png((120, 140, 40), seed=3)                       # R about 120: far outside 210 to 230
    r = upload(client, [("far.png", far), ("near.png", make_photo_png())])
    out = {x["file_name"]: x for x in client.get(f"/api/jobs/{r.json()['job_id']}/results").json()["results"]}
    assert out["far.png"]["warning"] == "outside training range: R"
    assert out["far.png"]["predicted_concentration_mg_L"] is not None
    assert out["near.png"]["warning"] == ""


def test_a_running_job_keeps_the_model_it_started_with(client):
    trained_client_session(client)
    model, version = concentration.current()
    assert model is not None and version
    r = upload(client, [("tube.png", make_photo_png())])
    trained_client_session(client, table_rows(seed=3))                  # a new model after the job started
    assert concentration.current()[1] != version
    assert client.get(f"/api/jobs/{r.json()['job_id']}").json()["status"] == "done"


# ---------------------------------------------------------------- naming
def test_no_old_name_appears_in_the_model_or_the_source(client):
    forbidden = re.compile("(?<![A-Za-z])" + "c" + "od" + "(?![a-z])|" + "c" + "od" + "_|" + "c" + "od" + "-", re.I)
    trained_client_session(client)
    text = (config.MODEL_DIR / "concentration_model.json").read_text(encoding="utf-8")
    assert not forbidden.search(text)
    root = Path(__file__).resolve().parent.parent
    for path in list(root.glob("*.py")) + list(root.glob("tests/*.py")) + [root / "README.md", root / ".env.example"]:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name

    # The frontend may show exactly two texts that contain the old name: the heading and the table label.
    # Everything else in its source (not its test files) must stay free of it. The backend check above has no exception.
    allowed = ("RGB measurement and " + "C" + "OD prediction", "C" + "OD (mg/L)")
    front = root.parent / "frontend"
    for path in [front / "index.html"] + [p for p in (front / "src").rglob("*") if p.suffix in (".js", ".jsx", ".css")
                                          and ".test." not in p.name]:
        text = path.read_text(encoding="utf-8")
        for ok in allowed:
            text = text.replace(ok, "")
        assert not forbidden.search(text), path.name


def test_the_name_check_still_fails_when_the_old_name_is_added(tmp_path):
    forbidden = re.compile("(?<![A-Za-z])" + "c" + "od" + "(?![a-z])|" + "c" + "od" + "_|" + "c" + "od" + "-", re.I)
    for bad in ("x = 'c" + "od_model'", "# c" + "od model", "the C" + "OD value"):
        assert forbidden.search(bad), bad
    for fine in ("decode(x)", "encoder", "code", "recod" + "e"):
        assert not forbidden.search(fine), fine
