import csv
import io

import openpyxl
import pytest

import config
import measure_service
import storage
from conftest import make_pdf, make_photo_png, make_small_png, upload
from RGB_PREDICTION import measure_photo

EXPORT_COLUMNS = ["file_name", "page", "status", "R", "G", "B", "cod_mg_L", "flags", "warning", "error", "image_url"]
# a photo that was measured: "ok", or "outside_range" when R, G are outside what the fixed COD model covers
MEASURED = ("ok", "outside_range")
ROW_KEYS = {"file_name", "page", "status", "error", "R", "G", "B", "cod_mg_l", "flags", "warning", "image_url"}


def finished_job(client, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    return job_id, client.get(f"/api/jobs/{job_id}").json()     # background work is finished when post() returns


def results_of(client, job_id):
    return client.get(f"/api/jobs/{job_id}/results").json()["results"]


# ---------------------------------------------------------------- health
def test_health_reports_mongo_cloudinary_and_model(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mongo": "ok", "cloudinary": "ok", "model": "loaded"}


def test_prediction_completes_and_a_point_outside_the_model_range_has_no_cod(client, tmp_path):
    png = make_photo_png()                               # orange tube: G is about 140, below the model's 146-175
    job_id, job = finished_job(client, upload(client, [("tube.png", png)]))
    assert job["status"] == "done" and job["total"] == 1 and job["processed"] == 1
    assert set(job) == {"job_id", "status", "total", "processed", "error", "skipped", "idempotency_key"}

    body = client.get(f"/api/jobs/{job_id}/results").json()
    assert set(body) == {"job_id", "status", "results"}
    row = body["results"][0]
    assert set(row) == ROW_KEYS and row["page"] is None and row["error"] == ""
    assert row["status"] == "outside_range" and row["cod_mg_l"] is None        # no number outside the model's range
    assert "calibration range" in row["warning"]

    # the same file measured straight with the script: R, G, B are its trimmed means, rounded to 2 decimals
    path = tmp_path / "direct.png"
    path.write_bytes(png)
    m, _ = measure_photo(path)
    assert (row["R"], row["G"], row["B"]) == (round(m["trim_R"], 2), round(m["trim_G"], 2), round(m["trim_B"], 2))
    assert row["image_url"].startswith("https://res.example.com/rgb-measure/" + job_id)


def test_in_range_photo_gets_a_cod_in_mg_per_l(client, monkeypatch):
    real = measure_service.measure_photo

    def in_range(path):
        m, arr = real(path)
        m["trim_R"], m["trim_G"] = 185.853, 163.778      # the measured values of a 449 ppm sample photo
        return m, arr

    monkeypatch.setattr(measure_service, "measure_photo", in_range)
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    row = results_of(client, job_id)[0]
    assert row["status"] == "ok" and isinstance(row["cod_mg_l"], float) and 100 <= row["cod_mg_l"] <= 1250
    assert (row["R"], row["G"]) == (185.85, 163.78)


def test_low_pixels_row_has_a_warning(client, monkeypatch):
    real = measure_service.measure_photo

    def few_pixels(path):
        m, arr = real(path)
        m["status"], m["valid_pixels"] = "low_pixels", 120
        return m, arr

    monkeypatch.setattr(measure_service, "measure_photo", few_pixels)
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    row = results_of(client, job_id)[0]
    assert job["status"] == "done" and row["status"] in ("ok", "outside_range")
    assert "low_pixels" in row["flags"] and "120 valid liquid pixels" in row["warning"]


def test_one_bad_photo_does_not_stop_the_job(client):
    from PIL import Image
    blank = io.BytesIO()
    Image.new("RGB", (300, 300), (128, 128, 128)).save(blank, "PNG")      # no tube in it -> fails
    job_id, job = finished_job(client, upload(client, [("bad.png", blank.getvalue()),
                                                       ("good.png", make_photo_png())]))
    assert job["status"] == "done" and job["total"] == 2 and job["processed"] == 2
    rows = {r["file_name"]: r for r in results_of(client, job_id)}
    assert rows["bad.png"]["status"] == "failed" and rows["bad.png"]["error"] and rows["bad.png"]["flags"] == "failed"
    assert rows["bad.png"]["R"] is None
    assert rows["good.png"]["status"] in MEASURED


def test_all_photos_failing_makes_the_job_failed(client):
    from PIL import Image
    blank = io.BytesIO()
    Image.new("RGB", (300, 300), (128, 128, 128)).save(blank, "PNG")
    job_id, job = finished_job(client, upload(client, [("bad.png", blank.getvalue())]))
    assert job["status"] == "failed" and job["error"]


def test_roi_size_flag_is_added_after_all_photos_finish(client):
    files = [(f"normal_{i}.png", make_small_png((220, 140, 40), seed=i)) for i in range(3)]
    files.append(("wide.png", make_small_png((220, 140, 40), seed=9, width=90)))
    job_id, job = finished_job(client, upload(client, files))
    flags = {r["file_name"]: r["flags"] for r in results_of(client, job_id)}
    assert "roi_size" in flags["wide.png"]
    assert all("roi_size" not in flags[f"normal_{i}.png"] for i in range(3))


# ---------------------------------------------------------------- PDF / folders / validation
def test_multipage_pdf_gives_one_row_per_page(client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    make_pdf(pdf, pages=3)
    r = upload(client, [("scan.pdf", pdf.read_bytes())])
    assert r.json()["accepted"] == 1
    job_id, job = finished_job(client, r)
    assert job["total"] == 3 and job["processed"] == 3 and job["status"] == "done"
    rows = results_of(client, job_id)
    assert [x["page"] for x in rows] == [1, 2, 3]
    assert {x["file_name"] for x in rows} == {"scan.pdf"}
    assert all(x["status"] in MEASURED for x in rows)


def test_folder_upload_with_thumbs_db(client):
    png = make_photo_png()
    r = upload(client, [("folder/a.png", png), ("folder/Thumbs.db", b"junk"), ("folder/b.png", png)])
    assert [x["name"] for x in r.json()["skipped"]] == ["Thumbs.db"] and r.json()["accepted"] == 2
    assert r.json()["skipped"][0]["reason"]
    job_id, job = finished_job(client, r)
    assert job["total"] == 2 and [x["name"] for x in job["skipped"]] == ["Thumbs.db"]
    assert [x["file_name"] for x in results_of(client, job_id)] == ["a.png", "b.png"]


def test_non_image_renamed_to_jpg_is_skipped_with_reason(client):
    r = upload(client, [("fake.jpg", b"this is text, not a jpeg"), ("a.png", make_photo_png())])
    assert [x["name"] for x in r.json()["skipped"]] == ["fake.jpg"]
    assert "not an image" in r.json()["skipped"][0]["reason"]


def test_nothing_usable_gives_422(client):
    r = upload(client, [("Thumbs.db", b"junk"), ("notes.txt", b"hello")])
    assert r.status_code == 422
    assert client.get("/api/jobs").json() == []


def test_file_too_big_gives_413(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_FILE_MB", 0)
    assert upload(client, [("a.png", make_photo_png())]).status_code == 413


def test_too_many_files_gives_400(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_FILES", 1)
    assert upload(client, [("a.png", b"x"), ("b.png", b"x")]).status_code == 400


def test_unknown_job_gives_404(client):
    for url in ("/api/jobs/nope", "/api/jobs/nope/results", "/api/jobs/nope/download"):
        assert client.get(url).status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 404


# ---------------------------------------------------------------- Cloudinary
def test_cloudinary_failure_keeps_job_going(client, monkeypatch):
    def boom(path, job_id):
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr(storage, "upload_file", boom)
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    assert job["status"] == "done"
    row = results_of(client, job_id)[0]
    assert row["status"] in MEASURED and row["image_url"] is None
    assert "image not stored: quota exceeded" in row["warning"]


def test_cloudinary_not_configured_skips_uploads(client, monkeypatch, cloud):
    monkeypatch.setattr(storage, "is_configured", lambda: False)
    monkeypatch.setattr(storage, "check", lambda: "not_configured")
    assert client.get("/api/health").json()["cloudinary"] == "not_configured"
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    row = results_of(client, job_id)[0]
    assert job["status"] == "done" and row["image_url"] is None and "image not stored" not in row["warning"]
    assert cloud["uploads"] == []


# ---------------------------------------------------------------- download
def test_download_csv_and_xlsx_with_escaping_and_new_columns(client):
    r = upload(client, [("=cmd.jpg", make_photo_png()), ("-minus.png", make_photo_png(1))])
    job_id, _ = finished_job(client, r)

    res = client.get(f"/api/jobs/{job_id}/download?format=csv")
    assert res.status_code == 200 and res.headers["content-disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == EXPORT_COLUMNS
    assert [r_[0] for r_ in rows[1:]] == ["'=cmd.jpg", "'-minus.png"]      # escaped: Excel will not run them

    res = client.get(f"/api/jobs/{job_id}/download?format=xlsx")
    assert res.status_code == 200 and res.headers["content-disposition"].startswith("attachment")
    ws = openpyxl.load_workbook(io.BytesIO(res.content)).active
    assert [c.value for c in ws[1]] == EXPORT_COLUMNS
    assert ws["A2"].value == "'=cmd.jpg" and ws["A2"].data_type != "f"      # text, not a formula


def test_download_rejects_other_formats(client):
    job_id, _ = finished_job(client, upload(client, [("a.png", make_photo_png())]))
    assert client.get(f"/api/jobs/{job_id}/download?format=pdf").status_code == 422


# ---------------------------------------------------------------- list / delete
def test_list_newest_first_and_delete(client, cloud):
    first, _ = finished_job(client, upload(client, [("a.png", make_photo_png())]))
    second, _ = finished_job(client, upload(client, [("b.png", make_photo_png())]))
    assert [j["job_id"] for j in client.get("/api/jobs?limit=50").json()] == [second, first]
    assert len(client.get("/api/jobs?limit=1").json()) == 1

    assert client.delete(f"/api/jobs/{first}").status_code == 204
    assert cloud["deleted"] == [first]
    assert client.get(f"/api/jobs/{first}").status_code == 404
    assert [j["job_id"] for j in client.get("/api/jobs").json()] == [second]
    import db
    assert db.results().count_documents({"job_id": first}) == 0


def test_temp_files_are_removed(client):
    import glob
    import tempfile
    before = set(glob.glob(f"{tempfile.gettempdir()}/rgbjob_*"))
    finished_job(client, upload(client, [("a.png", make_photo_png())]))
    assert set(glob.glob(f"{tempfile.gettempdir()}/rgbjob_*")) == before


# ---- Idempotency-Key: a retried POST must not create a second job -------------------------------
KEY = "3f2b8c1e-5a47-4d0e-9b6a-1c2d3e4f5a6b"


def post_with_key(client, key, name="a.png"):
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post("/api/jobs", files=[("files", (name, make_photo_png(), "application/octet-stream"))], headers=headers)


def test_repeated_key_returns_the_same_job_without_a_second_one(client, cloud):
    first = post_with_key(client, KEY)
    assert first.status_code == 202
    again = post_with_key(client, KEY)
    assert again.status_code == 200
    assert again.json()["job_id"] == first.json()["job_id"]
    assert again.json()["accepted"] == 1
    assert len(client.get("/api/jobs").json()) == 1
    assert len(cloud["uploads"]) == 1                    # the photo was not measured or stored again
    assert len(client.get(f"/api/jobs/{first.json()['job_id']}/results").json()["results"]) == 1
    assert client.get(f"/api/jobs/{first.json()['job_id']}").json()["idempotency_key"] == KEY


def test_key_comparison_ignores_case(client):
    a = post_with_key(client, KEY.upper())
    b = post_with_key(client, KEY)
    assert b.status_code == 200 and b.json()["job_id"] == a.json()["job_id"]


def test_different_keys_make_different_jobs(client):
    a = post_with_key(client, KEY)
    b = post_with_key(client, "3f2b8c1e-5a47-4d0e-9b6a-1c2d3e4f5a6c")
    assert a.json()["job_id"] != b.json()["job_id"]
    assert len(client.get("/api/jobs").json()) == 2


def test_missing_key_still_creates_a_job_every_time(client):
    a, b = post_with_key(client, None), post_with_key(client, None)
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] != b.json()["job_id"]
    assert client.get(f"/api/jobs/{a.json()['job_id']}").json()["idempotency_key"] is None


@pytest.mark.parametrize("bad", ["abc", "not-a-uuid-at-all-not-a-uuid-at-all-xx", KEY + "0", "a" * 65, "3f2b8c1e5a474d0e9b6a1c2d3e4f5a6b",
                                 "zzzzzzzz-5a47-4d0e-9b6a-1c2d3e4f5a6b"])
def test_invalid_key_gives_400_and_creates_nothing(client, bad):
    res = post_with_key(client, bad)
    assert res.status_code == 400, res.text
    assert "Idempotency-Key" in res.json()["detail"]
    assert client.get("/api/jobs").json() == []


def test_concurrent_duplicate_insert_returns_the_existing_job(client, monkeypatch):
    """Both requests passed the lookup before either inserted: the second insert hits the unique index."""
    import main
    first = post_with_key(client, KEY).json()["job_id"]
    real = main.existing_job_response
    calls = []

    def blind_first_lookup(key):
        calls.append(key)
        return None if len(calls) == 1 else real(key)    # the "race": the first lookup finds nothing

    monkeypatch.setattr(main, "existing_job_response", blind_first_lookup)
    res = post_with_key(client, KEY)
    assert res.status_code == 200 and res.json()["job_id"] == first
    assert len(client.get("/api/jobs").json()) == 1


def test_unique_partial_index_exists_and_old_jobs_without_a_key_coexist(client):
    import db
    client.get("/api/health")
    info = db.jobs().index_information()
    idx = info["idempotency_key_unique"]
    assert idx["unique"] is True
    assert idx["partialFilterExpression"] == {"idempotency_key": {"$exists": True}}
    db.jobs().insert_one({"_id": "old1", "status": "done", "total": 1, "processed": 1, "skipped": []})   # no key field
    db.jobs().insert_one({"_id": "old2", "status": "done", "total": 1, "processed": 1, "skipped": []})
    assert client.get("/api/jobs/old1").json()["idempotency_key"] is None


def test_cors_preflight_allows_the_idempotency_key_header(client):
    origin = config.FRONTEND_ORIGINS[0]
    res = client.options("/api/jobs", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "idempotency-key"})
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == origin
    assert "idempotency-key" in res.headers["access-control-allow-headers"].lower()
    blocked = client.options("/api/jobs", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "idempotency-key"})
    assert "access-control-allow-origin" not in blocked.headers or blocked.status_code == 400
