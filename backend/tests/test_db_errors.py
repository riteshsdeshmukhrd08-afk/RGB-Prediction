"""A database that is down or refuses us must give 503 with a clear message, never a bare 500."""

import pytest
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError

import db
from conftest import make_photo_png, upload

NO_DB = "Database unreachable: check MONGODB_URI and the MongoDB Atlas IP allowlist"


class Broken:
    """Stands in for a MongoClient / database / collection where every operation raises `error`."""

    def __init__(self, error):
        self._error = error
        self.admin = self

    def close(self):
        pass

    def __getitem__(self, name):
        return self

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise self._error
        return fail


def break_db(error):
    db.client = Broken(error)
    db._indexed = False


TIMEOUT = ServerSelectionTimeoutError("SSL handshake failed: shard-00-00.example.net:27017")
ROUTES = [
    ("get", "/api/jobs"),
    ("get", "/api/jobs/abc"),
    ("get", "/api/jobs/abc/results"),
    ("get", "/api/jobs/abc/download?format=csv"),
    ("delete", "/api/jobs/abc"),
]


@pytest.mark.parametrize("method,url", ROUTES)
def test_unreachable_database_gives_503(client, method, url):
    break_db(TIMEOUT)
    r = getattr(client, method)(url)
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": NO_DB}


@pytest.mark.parametrize("error", [TIMEOUT, ConnectionFailure("connection lost")])
def test_run_with_unreachable_database_gives_503(client, error):
    break_db(error)
    r = upload(client, [("a.png", make_photo_png())])
    assert r.status_code == 503 and r.json() == {"detail": NO_DB}


def test_operation_failure_gives_database_error_with_message(client):
    break_db(OperationFailure("bad auth : authentication failed"))
    r = client.get("/api/jobs")
    assert r.status_code == 503
    assert r.json() == {"detail": "Database error: bad auth : authentication failed"}


def test_health_still_200_and_gives_the_reason(client):
    break_db(TIMEOUT)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["mongo"] == "error" and body["model"] == "loaded"
    assert body["mongo_error"].startswith("ServerSelectionTimeoutError")
