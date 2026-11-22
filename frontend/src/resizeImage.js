// Shrinks big photos in the browser before upload (Vercel rejects request bodies over ~4.5 MB).
//
// KNOWN LIMITATION: resizing in the browser does NOT always give the same measurement as the original file.
// The backend shrinks every photo to 1200 px (MAX_SIDE) before measuring, and training data was measured on
// the original files, but Chrome's canvas resampling differs slightly from the backend's (about 0.7 of a level
// darker, in every channel) and the liquid-region (ROI) detection is sensitive to that. In a test of 9 real
// photos, 6 stayed within about 1 level, but:
//   * IMG_2506 and IMG_2507 find a DIFFERENT REGION once resized: the original gives a large region
//     (B about 205), the resized photo a tube-like region (B about 7).
//   * IMG_3463 also changes (R 185.9 -> 192.3, G 163.8 -> 168.2, B 16.4 -> 6.9; ROI 119x100 -> 82x175).
// Which of the two is "right" is not decided. Photos that need no resizing are sent unchanged and are not
// affected. See README.md ("Uploads and the browser resize"). Rules:
//   * longest side <= MAX_UPLOAD_SIDE and file <= MAX_BODY_BYTES: the original file is sent unchanged
//   * otherwise draw on a canvas (longest side -> 1600 px), export JPEG 0.92, lower quality in steps
//   * EXIF orientation is applied by the decoder ("from-image"); the JPEG has no EXIF, so no double rotation
//   * JPEG sources are decoded WITHOUT colour conversion, because the backend reads raw JPEG values
//     (convert("RGB")). Other formats are decoded with conversion to sRGB, as the backend does for them.

export const MAX_UPLOAD_SIDE = 1600;
export const MAX_BODY_BYTES = 4 * 1024 * 1024;
export const QUALITY_STEPS = [0.92, 0.9, 0.88, 0.85];

export class ImagePrepError extends Error {}

export const isHeic = (file) =>
  /^image\/hei[cf]/i.test(file.type) || /\.(heic|heif|hif)$/i.test(file.name);

const isJpeg = (file) => /^image\/jpe?g$/i.test(file.type) || /\.(jpe?g|jpe|jfif)$/i.test(file.name);

async function decode(file) {
  const options = { imageOrientation: "from-image", colorSpaceConversion: isJpeg(file) ? "none" : "default" };
  try {
    return await createImageBitmap(file, options);
  } catch {
    try {
      return await createImageBitmap(file); // older browsers may reject the options
    } catch {
      return null;
    }
  }
}

function toJpeg(canvas, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

function jpegName(name) {
  return name.replace(/\.[^./\\]+$/, "") + ".jpg";
}

// Returns a File that is safe to upload (the same File when nothing needed to change).
export async function prepareImage(file) {
  if (isHeic(file)) {
    throw new ImagePrepError(
      `${file.name}: HEIC/HEIF photos cannot be read by this browser. Convert it to JPEG first, or set the phone camera to "Most Compatible".`,
    );
  }
  const bitmap = await decode(file);
  if (!bitmap) {
    throw new ImagePrepError(`${file.name}: this browser cannot read the file as an image.`);
  }
  try {
    const longest = Math.max(bitmap.width, bitmap.height);
    if (longest <= MAX_UPLOAD_SIDE && file.size <= MAX_BODY_BYTES) return file;

    const scale = Math.min(1, MAX_UPLOAD_SIDE / longest);
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; // transparent pixels become white (the backend does the same)
    ctx.fillRect(0, 0, w, h);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, w, h);

    for (const q of QUALITY_STEPS) {
      const blob = await toJpeg(canvas, q);
      if (blob && blob.size <= MAX_BODY_BYTES) {
        return new File([blob], jpegName(file.name), { type: "image/jpeg", lastModified: file.lastModified });
      }
    }
    throw new ImagePrepError(
      `${file.name}: still over 4 MB after resizing to ${w}x${h} at JPEG quality 0.85. Try a smaller image.`,
    );
  } finally {
    bitmap.close?.();
  }
}
