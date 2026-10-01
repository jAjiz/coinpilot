"""A user's Kraken key: validated on write (spec §5.2), sealed at rest (§5.3), never read back."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

import core.database as db
from api.deps import Ctx, CurrentUser, Db
from api.schemas import CredentialsIn, CredentialStatusOut, KeyAcceptedOut
from exchange.keys import validate_key
from exchange.types import Credentials, KeyRejection

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post("", status_code=201, response_model=KeyAcceptedOut)
def register(body: CredentialsIn, user: CurrentUser, session: Db, context: Ctx) -> KeyAcceptedOut:
    credentials = Credentials(
        api_key=body.api_key.get_secret_value(),
        api_secret=body.api_secret.get_secret_value(),
    )
    result = validate_key(context.kraken_for(credentials))
    if result.rejection is KeyRejection.UNREACHABLE:
        raise HTTPException(503, "kraken could not be reached; the key was not stored")
    if result.rejection is KeyRejection.LOCKED_OUT:
        raise HTTPException(
            429,
            "kraken has locked the account out after repeated invalid keys; wait a few minutes"
            " before trying again, since every attempt restarts the lockout",
        )
    if not result.accepted:
        raise HTTPException(
            422,
            {
                "rejection": result.rejection.value,
                "missing": list(result.missing),
                "forbidden": list(result.forbidden),
                "unnecessary": list(result.unnecessary),
            },
        )

    sealed = context.cipher.seal(user.id, credentials)
    validated_at = context.now()
    db.save_credentials(session, user.id, sealed.ciphertext, sealed.nonce, sealed.key_version, validated_at)
    return KeyAcceptedOut(
        validated_at=validated_at,
        permissions=list(result.permissions),
        ip_allowlist=list(result.ip_allowlist),
        unnecessary=list(result.unnecessary),
    )


@router.delete("", status_code=204)
def remove(user: CurrentUser, session: Db) -> Response:
    if not db.delete_credentials(session, user.id):
        raise HTTPException(404, "no key is registered")
    return Response(status_code=204)


@router.get("/status", response_model=CredentialStatusOut)
def status(user: CurrentUser, session: Db) -> CredentialStatusOut:
    record = db.get_credentials(session, user.id)
    if record is None:
        return CredentialStatusOut(registered=False)
    return CredentialStatusOut(
        registered=True, validated_at=record.validated_at, key_version=record.key_version
    )
