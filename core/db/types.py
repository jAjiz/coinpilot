"""Column types, and the enumerations that are stored as short strings.

An enumeration is a string with a check constraint, not a PostgreSQL `ENUM` type. Adding
a value to a native enum is a migration with awkward transaction rules; a check
constraint is one `ALTER` and it reads plainly in `psql`.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, Numeric

# Twelve decimal places cover the largest lot precision Kraken publishes, with room to
# spare. Twelve integer digits cover any portfolio this system will hold.
AMOUNT = Numeric(24, 12)

# A target weight, 0.00 to 100.00.
PERCENT = Numeric(5, 2)

# Both pinned by the spec.
DRIFT_PCT = Numeric(4, 1)
ORDER_FIAT = Numeric(10, 1)


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CadenceMode(StrEnum):
    """`MIN` is the system minimum cadence. `INTERVAL` uses the days, months and anchor."""

    MIN = "MIN"
    INTERVAL = "INTERVAL"


class OrderReason(StrEnum):
    """Which operation asked for the order. Approval is per operation, not per order."""

    INVEST = "INVEST"
    REBALANCE = "REBALANCE"


class OrderStatus(StrEnum):
    """`PENDING` is written before `AddOrder` is called and means the outcome is unknown."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    FAILED = "FAILED"


class ProposalStatus(StrEnum):
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    LIVE = "LIVE"
    WITHDRAWN = "WITHDRAWN"


class ProposalTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


def enum_check(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    """A check constraint listing exactly the members of `values`.

    Building the constraint from the enumeration is what keeps the two from drifting: a
    member added in Python changes the generated DDL, and the migration that follows
    carries it.
    """
    listed = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({listed})", name=name)
