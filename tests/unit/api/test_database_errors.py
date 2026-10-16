"""A database that cannot be reached is a 503 the client may retry, not a bare 500."""

import uuid
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from api.app import create_app

UNREACHABLE = OperationalError("SELECT 1", {}, psycopg.errors.ConnectionTimeout("connection timeout expired"))
# A server-side error carries a SQLSTATE: the database answered, so it is not an outage.
LOCK_REFUSED = OperationalError("SELECT 1", {}, psycopg.errors.LockNotAvailable("could not obtain lock"))
POOL_EXHAUSTED = PoolTimeout("QueuePool limit reached")


@pytest.fixture
def api(make_context):
    def build(error: Exception) -> TestClient:
        @contextmanager
        def sessions():
            raise error
            yield

        context = make_context(sessions)
        client = TestClient(create_app(context), raise_server_exceptions=False)
        client.headers["Authorization"] = f"Bearer {context.signer.issue(uuid.uuid4()).value}"
        return client

    return build


@pytest.mark.parametrize("error", [UNREACHABLE, POOL_EXHAUSTED])
def test_an_unreachable_database_is_a_503_the_client_may_retry(api, error):
    response = api(error).get("/api/auth/me")

    assert response.status_code == 503
    assert "database" in response.json()["detail"]


def test_the_503_does_not_carry_the_drivers_message(api):
    response = api(UNREACHABLE).get("/api/auth/me")

    assert "timeout" not in response.text
    assert "5432" not in response.text


def test_an_error_the_database_answered_with_is_still_a_500(api):
    assert api(LOCK_REFUSED).get("/api/auth/me").status_code == 500
