import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from core.config import GoogleConfig
from core.google import (
    AUTHORIZE_URL,
    GoogleLoginFailed,
    authorization_url,
    code_challenge,
    exchange_code,
    new_login,
)

CONFIG = GoogleConfig(
    client_id="test-client",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:8000/auth/callback/google",
)


def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _google(userinfo=None, token_status=200, userinfo_status=200, seen=None):
    """Answers the token and userinfo endpoints. `seen` collects the token request form."""

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            if seen is not None:
                seen.update(parse_qs(request.content.decode()))
            return httpx.Response(
                token_status, json={"access_token": "google-access", "token_type": "Bearer"}
            )
        if request.url.host == "openidconnect.googleapis.com":
            assert request.headers["Authorization"] == "Bearer google-access"
            body = userinfo or {"sub": "1234567890", "email": "alice@example.test", "email_verified": True}
            return httpx.Response(userinfo_status, json=body)
        return httpx.Response(404)

    return handler


def test_every_login_gets_its_own_state_and_verifier():
    first, second = new_login(), new_login()

    assert first.state != second.state
    assert first.verifier != second.verifier
    assert 43 <= len(first.verifier) <= 128


def test_the_challenge_is_the_s256_of_the_verifier():
    verifier = new_login().verifier
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    assert code_challenge(verifier) == expected


def test_the_authorization_url_asks_for_a_code_with_pkce():
    login = new_login()
    url = urlparse(authorization_url(CONFIG, login))
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == AUTHORIZE_URL
    assert query["client_id"] == ["test-client"]
    assert query["redirect_uri"] == [CONFIG.redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email"]
    assert query["state"] == [login.state]
    assert query["code_challenge"] == [code_challenge(login.verifier)]
    assert query["code_challenge_method"] == ["S256"]


def test_the_authorization_url_never_carries_the_client_secret():
    assert "test-client-secret" not in authorization_url(CONFIG, new_login())


def test_a_code_becomes_a_verified_identity():
    identity = exchange_code(_http(_google()), CONFIG, "the-code", "the-verifier")

    assert identity.subject == "1234567890"
    assert identity.email == "alice@example.test"


def test_the_exchange_sends_the_verifier_and_the_redirect():
    seen = {}

    exchange_code(_http(_google(seen=seen)), CONFIG, "the-code", "the-verifier")

    assert seen["code"] == ["the-code"]
    assert seen["code_verifier"] == ["the-verifier"]
    assert seen["grant_type"] == ["authorization_code"]
    assert seen["redirect_uri"] == [CONFIG.redirect_uri]


def test_a_refused_code_fails_the_login():
    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(token_status=400)), CONFIG, "used-code", "v")


def test_an_unreadable_userinfo_fails_the_login():
    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(userinfo_status=500)), CONFIG, "c", "v")


def test_an_unverified_email_fails_the_login():
    """An address nobody proved they own is not an identity to hand a portfolio to."""
    userinfo = {"sub": "1", "email": "alice@example.test", "email_verified": False}

    with pytest.raises(GoogleLoginFailed, match="verified"):
        exchange_code(_http(_google(userinfo=userinfo)), CONFIG, "c", "v")


def test_an_answer_with_no_subject_fails_the_login():
    userinfo = {"email": "alice@example.test", "email_verified": True}

    with pytest.raises(GoogleLoginFailed):
        exchange_code(_http(_google(userinfo=userinfo)), CONFIG, "c", "v")


def test_an_unreachable_google_fails_the_login():
    def handler(request):
        raise httpx.ConnectError("connection failed")

    with pytest.raises(GoogleLoginFailed, match="reached"):
        exchange_code(_http(handler), CONFIG, "c", "v")


def test_a_failure_message_carries_no_secret():
    with pytest.raises(GoogleLoginFailed) as caught:
        exchange_code(_http(_google(token_status=400)), CONFIG, "c", "the-verifier")

    assert "test-client-secret" not in str(caught.value)
    assert "the-verifier" not in str(caught.value)
