"""
db.py - the MongoDB connection (pymongo, a normal blocking driver).

Collections:
  jobs    one document per upload
  results one document per photo (or PDF page)

The connection is created lazily: if Atlas is unreachable the server still starts and
/api/health reports mongo "error".
"""

import logging
import time

from pymongo import ASCENDING, DESCENDING, MongoClient

import config

log = logging.getLogger("db")

client = None          # tests put a mongomock client here before the app starts
_indexed = False
_last_index_try = 0.0


def init():
    """Create the client from MONGODB_URI unless one is already set."""
    global client
    if client is None and config.MONGODB_URI:
        client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)


def close():
    global client, _indexed, _last_index_try
    if client is not None:
        client.close()
    client, _indexed, _last_index_try = None, False, 0.0


def is_configured():
    return client is not None


def database():
    return client[config.MONGODB_DB]


def jobs():
    return database()["jobs"]


def results():
    return database()["results"]


def ensure_indexes():
    """Create the indexes once. Safe to call again; failures are only logged."""
    global _indexed, _last_index_try
    if _indexed or client is None:
        return
    if time.monotonic() - _last_index_try < 60:        # do not wait for a dead database on every request
        return
    _last_index_try = time.monotonic()
    try:
        results().create_index([("job_id", ASCENDING)])
        jobs().create_index([("created_at", DESCENDING)])
        # One job per Idempotency-Key. Partial: jobs created without a key (older ones too) are not indexed.
        jobs().create_index([("idempotency_key", ASCENDING)], unique=True, name="idempotency_key_unique",
                            partialFilterExpression={"idempotency_key": {"$exists": True}})
        _indexed = True
    except Exception as e:
        log.warning("Could not create indexes yet: %s", type(e).__name__)


def ping():
    """(True, "") if MongoDB answers, else (False, short reason). The reason never contains the URI."""
    try:
        client.admin.command("ping")
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"
