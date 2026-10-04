from dataclasses import dataclass
from decimal import Decimal

from core.proposal_plan import has_orders, is_material, plan_document
from engine.types import Side

D = Decimal


@dataclass(frozen=True)
class Leg:
    asset: str
    pair: str
    side: Side
    amount: Decimal
    minimum: Decimal | None
    note: str | None = None


def _doc(*legs):
    return plan_document("EUR", legs)


SELL_XBT = Leg("XBT", "XXBTZEUR", Side.SELL, D("200.00000"), D("5"))
BUY_ETH = Leg("ETH", "XETHZEUR", Side.BUY, D("200.00000"), D("0.5"))


def test_every_amount_is_a_plain_string():
    document = _doc(SELL_XBT)

    assert document == {
        "fiat": "EUR",
        "legs": [
            {
                "asset": "XBT",
                "pair": "XXBTZEUR",
                "side": "sell",
                "amount_fiat": "200",
                "minimum_fiat": "5",
                "note": None,
            }
        ],
    }


def test_a_leg_kraken_does_not_trade_has_no_minimum():
    leg = Leg("SOL", "SOLEUR", Side.BUY, D("10"), None, "kraken does not trade SOLEUR now")

    assert _doc(leg)["legs"][0]["minimum_fiat"] is None


def test_a_plan_whose_every_leg_is_skipped_has_no_orders():
    skipped = Leg("ETH", "XETHZEUR", Side.BUY, D("0.1"), D("0.5"), "below the minimum")

    assert has_orders(_doc(SELL_XBT)) is True
    assert has_orders(_doc(skipped)) is False
    assert has_orders(_doc()) is False


def test_the_same_plan_is_not_material():
    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT, BUY_ETH)) is False


def test_a_move_within_the_legs_minimum_is_not_material():
    """XBT moves 5, exactly its minimum: not more than it."""
    moved = Leg("XBT", "XXBTZEUR", Side.SELL, D("205"), D("5"))

    assert is_material(_doc(SELL_XBT), _doc(moved)) is False


def test_a_move_beyond_the_legs_minimum_is_material():
    moved = Leg("ETH", "XETHZEUR", Side.BUY, D("200.6"), D("0.5"))

    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT, moved)) is True


def test_a_leg_that_appears_or_disappears_is_material():
    assert is_material(_doc(SELL_XBT), _doc(SELL_XBT, BUY_ETH)) is True
    assert is_material(_doc(SELL_XBT, BUY_ETH), _doc(SELL_XBT)) is True


def test_a_leg_that_changes_side_is_material():
    bought = Leg("XBT", "XXBTZEUR", Side.BUY, D("200"), D("5"))

    assert is_material(_doc(SELL_XBT), _doc(bought)) is True


def test_a_skipped_leg_that_becomes_sendable_is_material():
    skipped = Leg("ETH", "XETHZEUR", Side.BUY, D("0.4"), D("0.5"), "below the minimum")
    sendable = Leg("ETH", "XETHZEUR", Side.BUY, D("0.6"), D("0.5"))

    assert is_material(_doc(SELL_XBT, skipped), _doc(SELL_XBT, sendable)) is True
