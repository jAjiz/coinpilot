import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from core.tokens import (
    AUDIENCE,
    ISSUER,
    LoginState,
    TokenInvalid,
    TokenSigner,
    hash_refresh_token,
    new_refresh_token,
)

SECRET = "s" * 32
USER = uuid.UUID("00000000-0000-4000-8000-00000000000a")


def _signer(secret=SECRET, ttl=timedelta(hours=1), now=None):
    return TokenSigner(secret, ttl, now=now or (lambda: datetime.now(UTC)))


def _claims(sub, now):
    return {
        "sub": sub,
        "typ": "access",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }


def test_a_token_verifies_back_to_its_user():
    signer = _signer()

    assert signer.verify(signer.issue(USER).value) == USER


def test_the_expiry_is_the_lifetime_after_issue():
    issued_at = datetime.now(UTC).replace(microsecond=0)
    token = _signer(now=lambda: issued_at).issue(USER)

    assert token.expires_at == issued_at + timedelta(hours=1)


def test_an_expired_token_is_refused():
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    token = _signer(now=lambda: long_ago).issue(USER)

    with pytest.raises(TokenInvalid):
        _signer().verify(token.value)


def test_a_token_signed_with_another_secret_is_refused():
    token = _signer(secret="o" * 32).issue(USER)

    with pytest.raises(TokenInvalid):
        _signer().verify(token.value)


def test_a_token_with_a_changed_payload_is_refused():
    header, payload, signature = _signer().issue(USER).value.split(".")
    changed = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1]

    with pytest.raises(TokenInvalid):
        _signer().verify(f"{header}.{changed}.{signature}")


def test_an_unsigned_token_is_refused():
    """`alg: none` is the classic JWT bypass. The algorithm is pinned, not read from the token."""
    unsigned = jwt.encode(_claims(str(USER), datetime.now(UTC)), None, algorithm="none")

    with pytest.raises(TokenInvalid):
        _signer().verify(unsigned)


def test_a_login_state_is_not_an_access_token():
    signer = _signer()
    state = signer.issue_login_state(LoginState(state="abc", verifier="xyz"))

    with pytest.raises(TokenInvalid):
        signer.verify(state)


def test_an_access_token_is_not_a_login_state():
    signer = _signer()

    with pytest.raises(TokenInvalid):
        signer.verify_login_state(signer.issue(USER).value)


def test_a_login_state_round_trips():
    signer = _signer()
    login = LoginState(state="abc", verifier="xyz")

    assert signer.verify_login_state(signer.issue_login_state(login)) == login


def test_a_subject_that_is_not_a_user_id_is_refused():
    forged = jwt.encode(_claims("not-a-uuid", datetime.now(UTC)), SECRET, algorithm="HS256")

    with pytest.raises(TokenInvalid):
        _signer().verify(forged)


def test_the_token_carries_the_user_id_and_nothing_personal():
    """A JWT is readable by anyone who holds it. It must not carry the email."""
    claims = jwt.decode(_signer().issue(USER).value, options={"verify_signature": False})

    assert set(claims) == {"sub", "typ", "iss", "aud", "iat", "exp"}


def test_the_repr_of_a_token_hides_its_value():
    token = _signer().issue(USER)

    assert token.value not in repr(token)


def test_refresh_token_values_are_long_and_never_repeat():
    values = {new_refresh_token() for _ in range(100)}

    assert len(values) == 100
    assert all(len(value) >= 43 for value in values)


def test_a_refresh_token_is_stored_as_a_fixed_length_hash():
    value = new_refresh_token()

    assert hash_refresh_token(value) == hashlib.sha256(value.encode()).digest()
    assert len(hash_refresh_token(value)) == 32
    assert value.encode() not in hash_refresh_token(value)
