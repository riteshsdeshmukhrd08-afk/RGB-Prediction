"""
compare_resize.py - does shrinking a photo in the browser change the measured R, G, B?

For each photo it measures
  A) the original file, and
  B) the client-resized JPEG (longest side 1600 px, JPEG quality 0.92, like frontend/src/resizeImage.js),
with the SAME code path the server uses (imaging.measurable -> RGB_PREDICTION.measure_photo).
It prints the trim_R/G/B difference per photo and the maximum absolute difference per channel.

Usage (from the backend folder):
    python scripts/compare_resize.py photo1.jpg photo2.jpg ... [--limit 2]
    python scripts/compare_resize.py photos/*.jpg --resized-dir browser_out/

  --resized-dir  use JPEGs exported by the real browser code (same file names as the originals, any
                 extension) instead of the Pillow simulation. Use this for the final check: Pillow's
                 resampler is not identical to the browser canvas.
"""

import argparse
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageOps  # noqa: E402

import imaging  # noqa: E402
from RGB_PREDICTION import measure_photo  # noqa: E402

UPLOAD_SIDE, QUALITY = 1600, 92


def simulate_client_resize(src, dst):
    """Pillow stand-in for resizeImage.js: orientation applied, longest side 1600, JPEG q0.92, no EXIF/ICC."""
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if max(img.size) > UPLOAD_SIDE:
            s = UPLOAD_SIDE / max(img.size)
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=QUALITY)


def measure(path):
    with imaging.measurable(path) as p:
        m, _ = measure_photo(p)
    return [m["trim_R"], m["trim_G"], m["trim_B"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--resized-dir", help="folder with browser-exported JPEGs (same base names)")
    ap.add_argument("--limit", type=float, default=2.0, help="flag differences above this many levels (default 2)")
    args = ap.parse_args()

    imaging.register_plugins()
    diffs, failed = [], 0
    print(f"{'photo':36s} {'orig R,G,B':>24s} {'resized R,G,B':>24s} {'dR':>7s} {'dG':>7s} {'dB':>7s}  bytes")
    with tempfile.TemporaryDirectory() as tmp:
        for name in args.photos:
            src = Path(name)
            try:
                if args.resized_dir:
                    cand = [f for f in Path(args.resized_dir).iterdir() if f.stem == src.stem]
                    if not cand:
                        raise FileNotFoundError(f"no resized file for {src.stem} in {args.resized_dir}")
                    resized = cand[0]
                else:
                    resized = Path(tmp) / (src.stem + "_1600.jpg")
                    simulate_client_resize(src, resized)
                a, b = measure(src), measure(resized)
            except Exception as e:
                failed += 1
                print(f"{src.name[:36]:36s} FAILED: {type(e).__name__}: {e}")
                continue
            d = [y - x for x, y in zip(a, b)]
            diffs.append(d)
            fmt = lambda v: ",".join(f"{x:6.2f}" for x in v)  # noqa: E731
            print(f"{src.name[:36]:36s} {fmt(a):>24s} {fmt(b):>24s} {d[0]:+7.2f} {d[1]:+7.2f} {d[2]:+7.2f}  "
                  f"{src.stat().st_size:,} -> {resized.stat().st_size:,}")

    if not diffs:
        print("\nNo photo could be measured.")
        return 1
    worst = [max(abs(d[i]) for d in diffs) for i in range(3)]
    print(f"\nMax |difference| over {len(diffs)} photo(s) (0-255 scale):  "
          f"R {worst[0]:.2f}   G {worst[1]:.2f}   B {worst[2]:.2f}")
    over = [c for c, w in zip("RGB", worst) if w > args.limit]
    print(f"FLAG: {', '.join(over)} above {args.limit:g} levels" if over else f"OK: all channels within {args.limit:g} levels")
    if failed:
        print(f"WARNING: {failed} photo(s) failed to measure and are not in the maximum.")
    return 1 if over or failed else 0


if __name__ == "__main__":
    sys.exit(main())
