"""
One-off check of the MongoDB connection. Run from backend/ inside the venv:
    python scripts/check_mongo.py
Prints only the host name and database name, never the password.
"""

import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # loads backend/.env  # noqa: E402

uri = config.MONGODB_URI
if not uri:
    print("MONGODB_URI is empty: it is not set in backend/.env (or the file is not being read).")
    sys.exit(2)

parsed = urlparse(uri)
host = parsed.hostname or "?"
print(f"scheme   : {parsed.scheme}")
print(f"host     : {host}")
print(f"database : {config.MONGODB_DB}")
print(f"user set : {bool(parsed.username)}   password set: {bool(parsed.password)}")

# DNS: an +srv URI needs a working SRV lookup of _mongodb._tcp.<host>
try:
    if parsed.scheme == "mongodb+srv":
        import dns.resolver  # installed with pymongo's srv support
        answers = dns.resolver.resolve(f"_mongodb._tcp.{host}", "SRV")
        print(f"DNS SRV  : ok ({len(answers)} server records)")
    else:
        print(f"DNS A    : ok ({socket.gethostbyname(host)})")
except Exception as e:
    print(f"DNS      : FAILED  {type(e).__name__}: {e}")

from pymongo import MongoClient  # noqa: E402

client = MongoClient(uri, serverSelectionTimeoutMS=8000)
try:
    print("ping     :", client.admin.command("ping"))
    print("RESULT   : ok")
except Exception as e:
    msg = str(e)
    for secret in (parsed.password or "",):      # never echo the password, even inside an error text
        if secret:
            msg = msg.replace(secret, "***")
    print(f"ping     : FAILED  {type(e).__name__}: {msg[:600]}")
    print("RESULT   :", "authentication failed" if "auth" in type(e).__name__.lower() or "Authentication failed" in msg
          else "timeout / unreachable")
    sys.exit(1)
