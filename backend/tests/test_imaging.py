import io

import numpy as np
from PIL import Image

import imaging


def normalise(img, tmp_path, fmt="PNG", **save_kw):
    src, dst = tmp_path / "src.bin", tmp_path / "out.png"
    img.save(src, fmt, **save_kw)
    imaging.normalize_to_png(src, dst)
    return Image.open(dst)


def test_16_bit_is_scaled_not_clipped(tmp_path):
    ramp = np.tile(np.linspace(0, 65535, 64).astype(np.uint16), (8, 1))
    out = normalise(Image.fromarray(ramp), tmp_path)
    a = np.asarray(out)
    assert out.mode == "RGB" and a.dtype == np.uint8
    assert a[0, 0, 0] == 0 and a[0, -1, 0] == 255
    assert abs(int(a[0, 32, 0]) - 130) <= 3                     # 40000/65535*255 is about 156 at column ~41
    assert (a[0, :, 0] == 255).sum() == 1                       # clipping would give many 255s
    assert (a[:, :, 0] == a[:, :, 1]).all()


def test_transparency_goes_on_white(tmp_path):
    img = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    img.putpixel((0, 0), (10, 20, 30, 255))
    a = np.asarray(normalise(img, tmp_path))
    assert tuple(a[0, 0]) == (10, 20, 30) and tuple(a[3, 3]) == (255, 255, 255)


def test_cmyk_and_gray_become_rgb(tmp_path):
    cmyk = np.asarray(normalise(Image.new("CMYK", (4, 4), (0, 0, 0, 0)), tmp_path, "TIFF"))
    assert cmyk.shape[-1] == 3 and cmyk.min() >= 250
    gray = np.asarray(normalise(Image.new("L", (4, 4), 77), tmp_path))
    assert (gray == 77).all()


def test_first_frame_and_first_page(tmp_path):
    red, blue = Image.new("RGB", (8, 8), (255, 0, 0)), Image.new("RGB", (8, 8), (0, 0, 255))
    gif = normalise(red, tmp_path, "GIF", save_all=True, append_images=[blue])
    assert tuple(np.asarray(gif)[0, 0]) == (255, 0, 0)
    tif = normalise(Image.new("RGB", (8, 8), (10, 200, 30)), tmp_path, "TIFF", save_all=True,
                    append_images=[Image.new("RGB", (8, 8), (1, 1, 1))])
    assert tuple(np.asarray(tif)[0, 0]) == (10, 200, 30)


def test_exif_orientation_applied_and_no_metadata_kept(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6                                            # rotate 90 degrees when displayed
    out = normalise(Image.new("RGB", (40, 20), (5, 5, 5)), tmp_path, exif=exif, dpi=(300, 300))
    assert out.size == (20, 40)
    assert not out.getexif() and "icc_profile" not in out.info and "dpi" not in out.info


def test_measurable_passes_jpeg_unchanged_and_cleans_up_others(tmp_path):
    jpg, png = tmp_path / "a.bin", tmp_path / "b.bin"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(jpg, "JPEG")
    Image.new("RGB", (8, 8), (9, 9, 9)).save(png, "PNG")
    with imaging.measurable(jpg) as p:
        assert p == jpg
    with imaging.measurable(png) as p:
        assert p != png and str(p).endswith(".png") and p.__class__ is str
        temp = p
    import os
    assert not os.path.exists(temp)
