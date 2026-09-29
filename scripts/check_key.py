"""Check a real Kraken key against the permission contract.

Run by hand. It reads the key from the environment, calls `GetApiKeyInfo`, and prints
what the key is allowed to do. It places no order and changes nothing.

    KRAKEN_API_KEY=... KRAKEN_API_SECRET=... PYTHONPATH=. python scripts/check_key.py
"""

from __future__ import annotations

import os
import sys

from exchange.client import KrakenClient, build_http_client
from exchange.keys import validate_key
from exchange.limits import KeyLimiter
from exchange.types import Credentials


def main() -> int:
    key = os.environ.get("KRAKEN_API_KEY", "")
    secret = os.environ.get("KRAKEN_API_SECRET", "")
    if not key or not secret:
        print("set KRAKEN_API_KEY and KRAKEN_API_SECRET", file=sys.stderr)
        return 2

    http = build_http_client()
    try:
        client = KrakenClient(http, KeyLimiter(1.0), Credentials(key, secret))
        result = validate_key(client)
    finally:
        http.close()

    print(f"accepted   : {result.accepted}")
    print(f"rejection  : {result.rejection or '-'}")
    print(f"permissions: {', '.join(result.permissions) or '-'}")
    print(f"missing    : {', '.join(result.missing) or '-'}")
    print(f"forbidden  : {', '.join(result.forbidden) or '-'}")
    print(f"ip allowed : {', '.join(result.ip_allowlist) or 'any address'}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
