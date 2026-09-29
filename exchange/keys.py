"""Whether a Kraken key may be stored at all.

`GetApiKeyInfo` needs no permission to call, so this is a read and not a probe: nothing
is attempted in order to find out whether it is allowed.

The check runs once, when the key is registered. Permissions can be widened afterwards
and this system cannot observe that, so it does not pretend to. What the contract buys is
that a key the platform holds never started out able to withdraw.
"""

from __future__ import annotations

from exchange.types import KeyRejection, KeyValidation

# `query-open-trades` and `query-closed-trades` are here because resolving a lost order
# response calls both OpenOrders and ClosedOrders.
REQUIRED_PERMISSIONS = frozenset({"query-funds", "modify-trades", "query-open-trades", "query-closed-trades"})

# The two address permissions cannot move funds on their own. Staging an address is the
# step before a withdrawal, if the withdrawal permission is ever enabled.
FORBIDDEN_PERMISSIONS = frozenset({"withdraw-funds", "add-withdraw-address", "update-withdraw-address"})

_UNREACHABLE = KeyValidation(
    accepted=False,
    rejection=KeyRejection.UNREACHABLE,
    permissions=(),
    missing=(),
    forbidden=(),
    ip_allowlist=(),
)


def validate_key(client) -> KeyValidation:
    """Read the key's permissions and decide whether it may be stored.

    A key that cannot be read is rejected, not deferred. Storing a key that was never
    validated is the one outcome this contract exists to prevent.
    """
    info = client.api_key_info()
    if info is None:
        return _UNREACHABLE

    granted = frozenset(str(entry) for entry in info.get("permissions", []))
    missing = tuple(sorted(REQUIRED_PERMISSIONS - granted))
    forbidden = tuple(sorted(FORBIDDEN_PERMISSIONS & granted))

    # Both facts are returned; the one named as the reason is the security one. A key that
    # can withdraw is a different kind of problem from a key that is merely incomplete.
    if forbidden:
        rejection = KeyRejection.FORBIDDEN_PERMISSIONS
    elif missing:
        rejection = KeyRejection.MISSING_PERMISSIONS
    else:
        rejection = None

    return KeyValidation(
        accepted=rejection is None,
        rejection=rejection,
        permissions=tuple(sorted(granted)),
        missing=missing,
        forbidden=forbidden,
        ip_allowlist=tuple(str(entry) for entry in info.get("ipAllowlist", [])),
    )
