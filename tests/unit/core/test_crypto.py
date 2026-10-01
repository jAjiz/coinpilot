import uuid
from dataclasses import replace

import pytest

from core.crypto import NONCE_BYTES, CredentialCipher, CredentialsUnreadable
from exchange.types import Credentials

KEY_1 = bytes(range(32))
KEY_2 = bytes(range(32, 64))
ALICE = uuid.UUID("00000000-0000-4000-8000-00000000000a")
BOB = uuid.UUID("00000000-0000-4000-8000-00000000000b")
CREDENTIALS = Credentials(api_key="THE-PUBLIC-KEY", api_secret="THE-SECRET-VALUE")


def _cipher(keys=None, active=1):
    return CredentialCipher(keys or {1: KEY_1}, active)


def test_what_is_sealed_opens_again():
    cipher = _cipher()

    assert cipher.unseal(ALICE, cipher.seal(ALICE, CREDENTIALS)) == CREDENTIALS


def test_the_ciphertext_contains_neither_the_key_nor_the_secret():
    sealed = _cipher().seal(ALICE, CREDENTIALS)

    assert b"THE-PUBLIC-KEY" not in sealed.ciphertext
    assert b"THE-SECRET-VALUE" not in sealed.ciphertext


def test_every_seal_uses_a_fresh_nonce():
    """A nonce reused under one key breaks AES-GCM completely."""
    cipher = _cipher()

    first = cipher.seal(ALICE, CREDENTIALS)
    second = cipher.seal(ALICE, CREDENTIALS)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert len(first.nonce) == NONCE_BYTES


def test_a_record_copied_to_another_user_does_not_open():
    """The user id is the associated data, so a row moved between users is useless."""
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable):
        cipher.unseal(BOB, sealed)


def test_one_changed_byte_is_detected():
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)
    tampered = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]

    with pytest.raises(CredentialsUnreadable):
        cipher.unseal(ALICE, replace(sealed, ciphertext=tampered))


def test_a_version_with_no_key_is_unreadable_not_a_crash():
    sealed = _cipher().seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable, match="version 7"):
        _cipher().unseal(ALICE, replace(sealed, key_version=7))


def test_after_rotation_old_records_open_and_new_ones_use_the_new_key():
    old = _cipher({1: KEY_1}, 1).seal(ALICE, CREDENTIALS)
    rotated = _cipher({1: KEY_1, 2: KEY_2}, 2)

    assert rotated.unseal(ALICE, old) == CREDENTIALS
    assert rotated.seal(ALICE, CREDENTIALS).key_version == 2


def test_the_active_version_must_have_a_key():
    with pytest.raises(ValueError, match="active"):
        CredentialCipher({1: KEY_1}, 2)


def test_a_key_that_is_not_256_bits_is_refused():
    with pytest.raises(ValueError, match="32 bytes"):
        CredentialCipher({1: bytes(16)}, 1)


def test_a_failure_message_carries_no_part_of_the_credential():
    cipher = _cipher()
    sealed = cipher.seal(ALICE, CREDENTIALS)

    with pytest.raises(CredentialsUnreadable) as caught:
        cipher.unseal(BOB, sealed)

    assert "THE-SECRET-VALUE" not in str(caught.value)
    assert "THE-PUBLIC-KEY" not in str(caught.value)
