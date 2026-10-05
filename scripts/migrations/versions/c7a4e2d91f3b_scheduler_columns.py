"""scheduler columns

Revision ID: c7a4e2d91f3b
Revises: 8b8c04912293
Create Date: 2026-10-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a4e2d91f3b"
down_revision: str | Sequence[str] | None = "8b8c04912293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_settings",
        sa.Column("failure_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("sessions", sa.Column("operation", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("trigger", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "trigger")
    op.drop_column("sessions", "operation")
    op.drop_column("portfolio_snapshots", "pinned")
    op.drop_column("user_settings", "failure_streak")
