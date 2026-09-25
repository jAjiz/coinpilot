from exchange.keys import FORBIDDEN_PERMISSIONS, REQUIRED_PERMISSIONS, validate_key
from exchange.types import KeyRejection

ENOUGH = [
    "query-funds",
    "modify-trades",
    "query-open-trades",
    "query-closed-trades",
]


class FakeClient:
    """Returns whatever `GetApiKeyInfo` is supposed to have said. `None` means the call
    could not be made at all."""

    def __init__(self, info):
        self._info = info

    def api_key_info(self):
        return self._info


def _info(permissions, ip_allowlist=()):
    return {"permissions": list(permissions), "ipAllowlist": list(ip_allowlist)}


def test_a_key_with_exactly_what_is_needed_is_accepted():
    result = validate_key(FakeClient(_info(ENOUGH)))

    assert result.accepted is True
    assert result.rejection is None
    assert result.missing == ()
    assert result.forbidden == ()


def test_a_harmless_extra_permission_does_not_matter():
    """Only the forbidden list is refused. Everything else is the user's business."""
    result = validate_key(FakeClient(_info([*ENOUGH, "query-ledger", "export-data"])))

    assert result.accepted is True


def test_a_key_missing_a_required_permission_is_refused_and_says_which():
    result = validate_key(FakeClient(_info(["query-funds", "modify-trades"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.MISSING_PERMISSIONS
    assert set(result.missing) == {"query-open-trades", "query-closed-trades"}


def test_a_key_that_can_withdraw_is_refused():
    """The whole point of the contract. A stolen key can trade; it cannot drain."""
    result = validate_key(FakeClient(_info([*ENOUGH, "withdraw-funds"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS
    assert result.forbidden == ("withdraw-funds",)


def test_a_key_that_can_add_a_withdrawal_address_is_refused():
    """It cannot move funds on its own. It is the step before something that can."""
    result = validate_key(FakeClient(_info([*ENOUGH, "add-withdraw-address"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS


def test_a_key_that_can_change_a_withdrawal_address_is_refused():
    result = validate_key(FakeClient(_info([*ENOUGH, "update-withdraw-address"])))

    assert result.accepted is False
    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS


def test_a_key_that_is_both_short_and_dangerous_reports_the_danger():
    """Both facts are returned, and the one named as the reason is the security one."""
    result = validate_key(FakeClient(_info(["query-funds", "withdraw-funds"])))

    assert result.rejection is KeyRejection.FORBIDDEN_PERMISSIONS
    assert result.forbidden == ("withdraw-funds",)
    assert "modify-trades" in result.missing


def test_a_kraken_that_cannot_be_reached_is_a_rejection_not_an_acceptance():
    """Storing a key that was never validated is exactly what this contract prevents."""
    result = validate_key(FakeClient(None))

    assert result.accepted is False
    assert result.rejection is KeyRejection.UNREACHABLE
    assert result.permissions == ()


def test_a_response_with_no_permissions_field_is_refused():
    result = validate_key(FakeClient({}))

    assert result.accepted is False
    assert result.rejection is KeyRejection.MISSING_PERMISSIONS


def test_the_address_allowlist_is_surfaced():
    """So the user can see whether their key is already restricted to one address."""
    result = validate_key(FakeClient(_info(ENOUGH, ip_allowlist=["203.0.113.7"])))

    assert result.ip_allowlist == ("203.0.113.7",)


def test_the_two_lists_do_not_overlap():
    """A permission that was both required and forbidden would make every key fail."""
    assert REQUIRED_PERMISSIONS.isdisjoint(FORBIDDEN_PERMISSIONS)


def test_the_result_carries_no_part_of_the_key():
    """Nothing about validation may become a way to read a credential back."""
    result = validate_key(FakeClient(_info(ENOUGH)))

    assert "api_key" not in repr(result)
    assert "secret" not in repr(result).lower()
