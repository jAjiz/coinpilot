"""onboarded_at

Revision ID: b4884c7eade8
Revises: c7a4e2d91f3b
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4884c7eade8"
down_revision: str | Sequence[str] | None = "c7a4e2d91f3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable and without a default: the release before this one never writes it.
    op.add_column("user_settings", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_settings", "onboarded_at")
