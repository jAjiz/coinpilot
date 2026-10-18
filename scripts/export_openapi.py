"""Write the API's OpenAPI document to `web/openapi.json`.

The application generates its client types from that file, so it is committed. Run it after
any change to a route or a model; a test fails while the file is stale:

    PYTHONPATH=. python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from api.app import openapi_document

OPENAPI_FILE = Path(__file__).resolve().parent.parent / "web" / "openapi.json"


def main() -> None:
    document = json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n"
    OPENAPI_FILE.parent.mkdir(exist_ok=True)
    # Newline fixed: the file is committed, and a CRLF checkout would differ on every run.
    with OPENAPI_FILE.open("w", encoding="utf-8", newline="\n") as file:
        file.write(document)


if __name__ == "__main__":
    main()
