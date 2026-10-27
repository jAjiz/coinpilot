"""order_session

Revision ID: e5b7c1d93a42
Revises: b4884c7eade8
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b7c1d93a42"
down_revision: str | Sequence[str] | None = "b4884c7eade8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable and without a default: the release before this one never writes it, and
    # the orders already there belong to no session. SET NULL because retention deletes
    # old sessions and the ledger keeps its orders.
    op.add_column("orders", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_orders_session_id_sessions", "orders", "sessions", ["session_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_orders_session_id", "orders", ["session_id"])
    # The order the attempts were written in, which is the order a session sent them in.
    # The rows already there are numbered in no particular order; none has a session.
    op.add_column("orders", sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("orders", "seq")
    op.drop_index("ix_orders_session_id", table_name="orders")
    op.drop_constraint("fk_orders_session_id_sessions", "orders", type_="foreignkey")
    op.drop_column("orders", "session_id")
