"""Seal every stored Kraken key again under the active master key.

Run by hand on the host, after the new key was added to CREDENTIAL_KEYS, made active with
CREDENTIAL_KEY_VERSION, and the platform restarted (runbook: docs/operations.md):

    /opt/coinpilot/compose.sh run --rm platform python scripts/rotate_master_key.py
    /opt/coinpilot/compose.sh run --rm platform python scripts/rotate_master_key.py --check

`--check` changes nothing. Both exit 0 when every record is under the active key, and 1
otherwise. Only user ids and counts are printed.
"""

from __future__ import annotations

import os
import sys

import core.database as db
from core.config import load_config
from core.crypto import CredentialCipher
from core.rotation import rotate


def main(argv: list[str]) -> int:
    config = load_config(os.environ)
    db.configure(config.database_url)
    cipher = CredentialCipher(config.credential_keys, config.credential_key_version)
    print(f"active version: {cipher.active_version}")

    if argv == ["--check"]:
        with db.session_scope() as session:
            left = db.credential_owners_not_at(session, cipher.active_version)
        print(f"not under it  : {len(left)}")
        return 0 if not left else 1
    if argv:
        print("usage: rotate_master_key.py [--check]", file=sys.stderr)
        return 2

    report = rotate(db.session_scope, cipher)
    print(f"resealed      : {len(report.resealed)}")
    print(f"unreadable    : {len(report.unreadable)}")
    for user_id in report.unreadable:
        print(f"  {user_id}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
