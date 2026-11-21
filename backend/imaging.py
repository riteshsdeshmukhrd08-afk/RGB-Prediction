"""
imaging.py - opening any image Pillow can read, and preparing it for measure_photo.

Rules (so that predictions match training):
  * JPEG files are given to measure_photo unchanged.
  * Every other format is first written as a clean 8-bit sRGB PNG, and measure_photo reads that PNG:
      - EXIF orientation applied            - transparency composited on white
      - 16-bit / grayscale / CMYK -> 8-bit RGB by SCALING (not clipping)
      - first frame of animations, first page of multi-page TIFF
      - embedded colour profile converted to sRGB, and no metadata kept in the PNG
"""

import contextlib
import io
import os
import tempfile

import numpy as np
from PIL import Image, ImageCms, ImageOps

JPEG_FORMATS = {"JPEG", "MPO"}        # MPO = the multi-picture JPEG some phones write


def register_plugins():
    """Add HEIC/HEIF and AVIF readers if the optional packages are installed."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        if hasattr(pillow_heif, "register_avif_opener"):
            try:
                pillow_heif.register_avif_opener()
            except Exception:
                pass
    except ImportError:
        pass
    try:
        import pillow_avif  # noqa: F401  (registers itself)
    except ImportError:
        pass


def supported_extensions():
    """The extensions this server can really open (asked from Pillow, not hard-coded)."""
    return sorted(ext for ext, fmt in Image.registered_extensions().items() if fmt in Image.OPEN)


def image_format(path):
    """Pillow's name for the file's format, found from its CONTENT. Raises if it is not an image."""
    with Image.open(path) as img:
        return img.format


def _gray_to_uint8(img):
    """16-bit / 32-bit / float grayscale -> uint8 by scaling the range."""
    a = np.asarray(img).astype(np.float64)
    top = float(a.max()) if a.size else 0.0
    if img.mode.startswith("I;16"):
        scale = 255.0 / 65535.0
    elif img.mode == "F":
        scale = 255.0 if top <= 1.0 else (1.0 if top <= 255 else 255.0 / top)
    else:                                        # "I": 32-bit integers, range unknown
        scale = 1.0 if top <= 255 else (255.0 / 65535.0 if top <= 65535 else 255.0 / top)
    return np.clip(np.rint(a * scale), 0, 255).astype(np.uint8)


def _to_rgb8(img):
    """Any Pillow image -> 8-bit RGB Image (transparency on white)."""
    if img.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I", "F"):
        g = _gray_to_uint8(img)
        return Image.fromarray(np.stack([g, g, g], axis=-1), "RGB")
    if img.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        white = Image.new("RGB", rgba.size, (255, 255, 255))
        white.paste(rgba, mask=rgba.getchannel("A"))
        return white
    return img.convert("RGB")                    # L, 1, P, CMYK, YCbCr, ... all handled by Pillow


def normalize_to_png(src, dst):
    """Write src as an 8-bit sRGB PNG without metadata. Raises if src cannot be decoded."""
    with Image.open(src) as img:
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)                          # first frame / first page
        icc = img.info.get("icc_profile")
        try:
            img = ImageOps.exif_transpose(img)   # orientation only
        except Exception:
            pass
        rgb = _to_rgb8(img)
        if icc:
            try:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                if "srgb" not in (ImageCms.getProfileDescription(profile) or "").lower():
                    rgb = ImageCms.profileToProfile(rgb, profile, ImageCms.createProfile("sRGB"),
                                                    outputMode="RGB")
            except Exception:
                pass                             # unusable profile: keep the pixels as they are
        Image.fromarray(np.asarray(rgb, dtype=np.uint8), "RGB").save(dst, "PNG")   # fresh image: no metadata


@contextlib.contextmanager
def measurable(path):
    """Yield a path that measure_photo can read; a temporary PNG is deleted afterwards."""
    if image_format(path) in JPEG_FORMATS:
        yield path
        return
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="rgbimg_")
    os.close(fd)
    try:
        normalize_to_png(path, tmp)
        yield tmp
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
