"""
training.py - runs one training (fit the concentration model from a validated table) in the background.

The upload is read and checked in the request (see main.py). This module only holds the "one training at a
time" lock, runs the fit in a thread, and records progress in the train_jobs collection.
"""

import logging
import threading

import concentration
import db

log = logging.getLogger("training")

lock = threading.Lock()          # held while a training is running


def update(job_id, **fields):
    db.train_jobs().update_one({"_id": job_id}, {"$set": fields})


def run_training(job_id, valid, source_name):
    """Thread body. The lock was taken by whoever started the thread; it is released here."""
    try:
        update(job_id, status="running", progress="Fitting the model")
        model = concentration.fit_model(valid, source_name)
        update(job_id, progress="Saving the model")
        concentration.save_model(model)
        update(job_id, status="done", progress="Done", error=None)
    except Exception as e:
        log.exception("Training %s failed", job_id)
        update(job_id, status="failed", progress="Failed", error=f"{type(e).__name__}: {e}")
    finally:
        lock.release()


def start(job_id, valid, source_name):
    threading.Thread(target=run_training, args=(job_id, valid, source_name),
                     name=f"train-{job_id[:6]}", daemon=True).start()


def fail_stale_jobs():
    """After a restart, a job still marked queued/running can never finish: mark it failed."""
    db.train_jobs().update_many({"status": {"$in": ["queued", "running"]}},
                                {"$set": {"status": "failed", "progress": "Failed",
                                          "error": "the server restarted while this training was running"}})
