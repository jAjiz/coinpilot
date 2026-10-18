"""The OpenAPI document is committed as a file: the application's client types come from it."""

import json
from contextlib import nullcontext

from api.app import create_app, openapi_document
from scripts.export_openapi import OPENAPI_FILE


def test_the_committed_document_is_the_apis():
    committed = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert committed == openapi_document(), "stale: run python scripts/export_openapi.py"


def test_the_document_holds_only_the_api():
    assert all(path.startswith("/api/") for path in openapi_document()["paths"])


def test_the_document_matches_the_running_app(make_context):
    assert openapi_document() == create_app(make_context(nullcontext)).openapi()
