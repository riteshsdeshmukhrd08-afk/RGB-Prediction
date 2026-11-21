import csv
import io

import openpyxl

import measure_service
import storage
from conftest import make_pdf, make_photo_png, make_small_png, upload
from RGB_PREDICTION import measure_photo

EXPORT_COLUMNS = ["file_name", "page", "status", "R", "G", "B", "predicted_concentration_ppm", "typical_error_ppm",
                  "flags", "warning", "error", "image_url"]
ROW_KEYS = {"file_name", "page", "status", "error", "R", "G", "B", "predicted_concentration_ppm", "typical_error_ppm",
            "flags", "warning", "image_url"}


def finished_job(client, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    return job_id, client.get(f"/api/jobs/{job_id}").json()     # background work is finished when post() returns


def results_of(client, job_id):
    return client.get(f"/api/jobs/{job_id}/results").json()["results"]


# ---------------------------------------------------------------- health / no model needed
def test_health_reports_mongo_cloudinary_and_model(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mongo": "ok", "cloudinary": "ok", "model": "missing"}


def test_prediction_completes_without_a_model_and_leaves_concentration_empty(client, tmp_path):
    import config
    assert not config.MODEL_DIR.exists()                         # no model file anywhere
    png = make_photo_png()
    job_id, job = finished_job(client, upload(client, [("tube.png", png)]))
    assert job["status"] == "done" and job["total"] == 1 and job["processed"] == 1
    assert set(job) == {"job_id", "status", "total", "processed", "error", "skipped"}

    body = client.get(f"/api/jobs/{job_id}/results").json()
    assert set(body) == {"job_id", "status", "results"}
    row = body["results"][0]
    assert set(row) == ROW_KEYS and row["status"] == "ok" and row["page"] is None and row["error"] == ""
    assert row["predicted_concentration_ppm"] is None and row["typical_error_ppm"] is None   # no model: empty

    # the same file measured straight with the script: R, G, B are its trimmed means, rounded to 2 decimals
    path = tmp_path / "direct.png"
    path.write_bytes(png)
    m, _ = measure_photo(path)
    assert (row["R"], row["G"], row["B"]) == (round(m["trim_R"], 2), round(m["trim_G"], 2), round(m["trim_B"], 2))
    assert row["image_url"].startswith("https://res.example.com/rgb-measure/" + job_id)


def test_low_pixels_row_has_a_warning(client, monkeypatch):
    real = measure_service.measure_photo

    def few_pixels(path):
        m, arr = real(path)
        m["status"], m["valid_pixels"] = "low_pixels", 120
        return m, arr

    monkeypatch.setattr(measure_service, "measure_photo", few_pixels)
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    row = results_of(client, job_id)[0]
    assert job["status"] == "done" and row["status"] == "low_pixels"
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
    assert rows["good.png"]["status"] == "ok"


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
    assert all(x["status"] == "ok" for x in rows)


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
    assert row["status"] == "ok" and row["image_url"] is None
    assert "image not stored: quota exceeded" in row["warning"]


def test_cloudinary_not_configured_skips_uploads(client, monkeypatch, cloud):
    monkeypatch.setattr(storage, "is_configured", lambda: False)
    monkeypatch.setattr(storage, "check", lambda: "not_configured")
    assert client.get("/api/health").json()["cloudinary"] == "not_configured"
    job_id, job = finished_job(client, upload(client, [("tube.png", make_photo_png())]))
    row = results_of(client, job_id)[0]
    assert job["status"] == "done" and row["image_url"] is None and row["warning"] == ""
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
