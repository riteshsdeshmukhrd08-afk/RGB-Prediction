"""
storage.py - Cloudinary helpers. Everything is skipped if Cloudinary is not configured.

Credentials come from CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME / _API_KEY / _API_SECRET in .env.
They are never logged or returned.
"""

import logging

import cloudinary
import cloudinary.api
import cloudinary.uploader

import config

log = logging.getLogger("storage")
ROOT_FOLDER = "rgb-measure"


def setup():
    """Called once at startup. (The SDK itself reads CLOUDINARY_URL from the environment.)"""
    if config.CLOUDINARY_CLOUD_NAME and config.CLOUDINARY_API_KEY and config.CLOUDINARY_API_SECRET:
        cloudinary.config(cloud_name=config.CLOUDINARY_CLOUD_NAME, api_key=config.CLOUDINARY_API_KEY,
                          api_secret=config.CLOUDINARY_API_SECRET, secure=True)


def is_configured():
    c = cloudinary.config()
    return bool(c.cloud_name and c.api_key and c.api_secret)


def check():
    """For /api/health: 'ok', 'not_configured' or 'error'."""
    if not is_configured():
        return "not_configured"
    try:
        cloudinary.api.ping(timeout=5)
        return "ok"
    except Exception:
        return "error"


def upload_file(path, job_id):
    """Upload one image file to rgb-measure/<job_id>. Returns its secure_url."""
    res = cloudinary.uploader.upload(str(path), folder=f"{ROOT_FOLDER}/{job_id}",
                                     resource_type="image", unique_filename=True)
    return res["secure_url"]


def delete_job_folder(job_id):
    """Delete every image of the job, then the (empty) folder."""
    if not is_configured():
        return
    prefix = f"{ROOT_FOLDER}/{job_id}"
    cloudinary.api.delete_resources_by_prefix(prefix, resource_type="image")
    try:
        cloudinary.api.delete_folder(prefix)
    except Exception as e:                     # folder removal is cosmetic; the images are already gone
        log.info("Could not remove empty folder %s: %s", prefix, type(e).__name__)
