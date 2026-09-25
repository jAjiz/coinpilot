import pytest

from exchange.orders import map_order_status, new_cl_ord_id
from exchange.types import ExchangeOrderStatus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pending", ExchangeOrderStatus.PENDING),
        ("open", ExchangeOrderStatus.OPEN),
        ("closed", ExchangeOrderStatus.CLOSED),
        ("canceled", ExchangeOrderStatus.CANCELED),
    ],
)
def test_every_status_kraken_publishes_is_translated(raw, expected):
    assert map_order_status(raw) == expected


def test_expired_and_canceled_mean_the_same_thing_here():
    """Both are off the book with nothing more coming, so nothing downstream needs to
    tell them apart."""
    assert map_order_status("expired") == ExchangeOrderStatus.CANCELED


def test_a_status_this_code_does_not_model_is_unknown_not_a_guess():
    """An order the system cannot read must be reported, never assumed."""
    assert map_order_status("partially_filled") == ExchangeOrderStatus.UNKNOWN


def test_a_missing_status_is_unknown():
    assert map_order_status(None) == ExchangeOrderStatus.UNKNOWN
    assert map_order_status("") == ExchangeOrderStatus.UNKNOWN


def test_a_client_id_is_krakens_short_uuid_form():
    """Thirty-two hexadecimal characters, no dashes. Kraken also accepts free text up to
    eighteen characters, which is too narrow to be unique without coordination."""
    minted = new_cl_ord_id()

    assert len(minted) == 32
    assert all(character in "0123456789abcdef" for character in minted)


def test_two_client_ids_never_collide():
    assert new_cl_ord_id() != new_cl_ord_id()


def test_a_client_id_fits_the_ledger_column():
    """`orders.cl_ord_id` is String(64)."""
    assert len(new_cl_ord_id()) <= 64
