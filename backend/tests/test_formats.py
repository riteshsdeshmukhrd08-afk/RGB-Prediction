import io

import numpy as np
import pytest
from PIL import Image

from conftest import make_photo_png, upload
from RGB_PREDICTION import measure_photo


def photo_image():
    return Image.open(io.BytesIO(make_photo_png())).convert("RGB")


def encode(fmt):
    """Real encoded bytes of the same synthetic photo, or skip if this install cannot write the format."""
    img = photo_image()
    buf = io.BytesIO()
    try:
        if fmt == "GIF":
            img = img.convert("P", palette=Image.ADAPTIVE)
        img.save(buf, fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    except Exception as e:                      # plugin missing (HEIF / AVIF) or unsupported here
        pytest.skip(f"cannot write {fmt}: {type(e).__name__}")
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF", "HEIF", "AVIF"])
def test_every_format_gives_an_ok_row(client, fmt, tmp_path):
    data = encode(fmt)
    # a name without a useful extension: the format must be found from the content
    r = upload(client, [(f"photo_{fmt.lower()}.bin", data)])
    assert r.status_code == 202, r.text
    assert r.json()["skipped"] == []
    job_id = r.json()["job_id"]
    row = client.get(f"/api/jobs/{job_id}/results").json()["results"][0]
    assert row["status"] in ("ok", "outside_range"), row["error"]
    assert all(row[k] is not None for k in "RGB")

    if fmt == "JPEG":                           # JPEG goes to measure_photo untouched: results must be identical
        original = tmp_path / "original.jpg"
        original.write_bytes(data)
        m, _ = measure_photo(original)
        assert (row["R"], row["G"], row["B"]) == (round(m["trim_R"], 2), round(m["trim_G"], 2), round(m["trim_B"], 2))


def test_formats_endpoint_asks_pillow(client):
    body = client.get("/api/formats").json()
    exts = set(body["extensions"])
    assert {".png", ".jpg", ".jpeg", ".webp", ".tif", ".bmp", ".gif", ".pdf"} <= exts
    opened = {e for e, f in Image.registered_extensions().items() if f in Image.OPEN}
    assert exts == opened | {".pdf"}
    try:
        import pillow_heif  # noqa: F401
        assert body["heif"] is True and ".heic" in exts
    except ImportError:
        assert body["heif"] is False


def test_undecodable_image_becomes_failed_row_not_skip(client):
    data = encode("PNG")
    truncated = data[: len(data) // 3]          # header is fine, pixel data is cut off
    r = upload(client, [("cut.png", truncated), ("ok.png", data)])
    assert r.json()["skipped"] == [] and r.json()["accepted"] == 2
    rows = {x["file_name"]: x for x in client.get(f"/api/jobs/{r.json()['job_id']}/results").json()["results"]}
    assert rows["cut.png"]["status"] == "failed" and rows["cut.png"]["error"]
    assert rows["ok.png"]["status"] in ("ok", "outside_range")
