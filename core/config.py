"""The one module that reads the process environment.

Every other module receives what it needs as an argument. That is what lets a test state
its inputs instead of inheriting them from the machine it runs on.
"""

from __future__ import annotations

import os


def database_url() -> str:
    """The database the platform connects to.

    Raises rather than defaulting. A silent default would point a production process at a
    local database, and the failure would look like an empty account.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url
