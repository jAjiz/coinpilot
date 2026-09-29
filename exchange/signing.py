"""The Kraken request signature.

Pure: given a path, a nonce, the encoded body and the secret, it returns one header
value. No I/O, no clock and no state, which is why the algorithm is pinned by Kraken's
own published example rather than by whether a request happened to succeed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import urlencode


def encode_body(payload: Mapping[str, object]) -> str:
    """The exact string that is both signed and sent.

    One function serves both on purpose. Signing a different encoding from the one that
    goes out is the failure that looks exactly like a wrong secret.
    """
    return urlencode(payload)


def sign(path: str, nonce: str, body: str, secret: str) -> str:
    """The value of the `API-Sign` header.

    Raises `ValueError` when the secret is not valid base64, because a signature built
    from a mistyped secret is indistinguishable from a rejected one at the far end.
    """
    try:
        decoded = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("the API secret is not valid base64") from exc

    message = path.encode() + hashlib.sha256((nonce + body).encode()).digest()
    signature = hmac.new(decoded, message, hashlib.sha512)
    return base64.b64encode(signature.digest()).decode()
