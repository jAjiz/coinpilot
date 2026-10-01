"""Encryption at rest for a user's Kraken key.

The key and the secret are one payload, sealed once under one nonce (spec §5.3). The
user id is the associated data, so a record copied onto another user's row does not
open.

What this protects is a stolen database dump. It does not protect a compromised server,
which must be able to decrypt in order to trade; the permission contract bounds that.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from exchange.types import Credentials

NONCE_BYTES = 12
KEY_BYTES = 32


class CredentialsUnreadable(Exception):
    """The record does not open: another user's row, a changed byte, or a missing key."""


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class CredentialCipher:
    """Seals with the active master key and opens with any version it holds."""

    def __init__(self, keys: Mapping[int, bytes], active_version: int) -> None:
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"master key version {version} is not {KEY_BYTES} bytes")
        if active_version not in keys:
            raise ValueError(f"the active version {active_version} has no key")
        self._keys = dict(keys)
        self._active = active_version

    def seal(self, user_id: uuid.UUID, credentials: Credentials) -> Sealed:
        payload = json.dumps({"key": credentials.api_key, "secret": credentials.api_secret}).encode("utf-8")
        # Random, never counted. A counter would have to survive restarts and replicas to
        # stay unique, and 96 random bits do not collide at this system's scale.
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self._keys[self._active]).encrypt(nonce, payload, user_id.bytes)
        return Sealed(ciphertext=ciphertext, nonce=nonce, key_version=self._active)

    def unseal(self, user_id: uuid.UUID, sealed: Sealed) -> Credentials:
        key = self._keys.get(sealed.key_version)
        if key is None:
            raise CredentialsUnreadable(f"no master key for version {sealed.key_version}")
        try:
            payload = AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, user_id.bytes)
        except InvalidTag:
            raise CredentialsUnreadable("the record does not open for this user under this key") from None
        data = json.loads(payload.decode("utf-8"))
        return Credentials(api_key=data["key"], api_secret=data["secret"])
