"""The eight tables.

Every one of them carries `user_id`. There are no singleton rows, and no table holds
state that belongs to the system rather than to a tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.db.types import (
    AMOUNT,
    DRIFT_PCT,
    ORDER_FIAT,
    PERCENT,
    CadenceMode,
    OrderReason,
    OrderStatus,
    ProposalStatus,
    ProposalTrigger,
    UserStatus,
    enum_check,
)
from engine.types import Side


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    """An OAuth identity. The key is a UUID so that a row count is not leaked."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # Not unique: two providers can return the same address, and that is one person with
    # two identities until something links them.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE)

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_users_provider_subject"),
        enum_check("status", UserStatus, "ck_users_status"),
    )


class UserCredentials(TimestampMixin, Base):
    """The Kraken key and secret, encrypted together under one nonce.

    One ciphertext, not two, is deliberate. Two payloads under the same master key need
    two nonces, and a reused nonce breaks AES-GCM completely. One payload makes that
    mistake impossible rather than merely discouraged.

    Inside the ciphertext is `{"key": ..., "secret": ...}` encoded UTF-8. This table never
    sees that structure: it stores bytes, and the phase that owns the cipher decides what
    they mean.
    """

    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSettings(TimestampMixin, Base):
    """One row per user. `fiat` is immutable for now."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)

    invest_cash_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # True selects the engine's REDUCE_DRIFT cash policy; false selects PRORATA.
    cash_rebalance_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_rebalance_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    min_drift_pct: Mapped[Decimal] = mapped_column(DRIFT_PCT, nullable=False, default=Decimal("0"))
    min_order_fiat: Mapped[Decimal] = mapped_column(ORDER_FIAT, nullable=False, default=Decimal("0"))

    invest_cadence_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=CadenceMode.MIN)
    invest_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invest_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invest_cadence_anchor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rebalance_cadence_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=CadenceMode.MIN)
    rebalance_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebalance_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rebalance_cadence_anchor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    next_invest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_rebalance_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # One indexed query per tick. The partial predicate keeps a paused user out of the
    # index entirely rather than out of the result.
    __table_args__ = (
        enum_check("invest_cadence_mode", CadenceMode, "ck_user_settings_invest_cadence_mode"),
        enum_check("rebalance_cadence_mode", CadenceMode, "ck_user_settings_rebalance_cadence_mode"),
        Index(
            "ix_user_settings_next_invest_at",
            "next_invest_at",
            postgresql_where=text("paused = false"),
        ),
        Index(
            "ix_user_settings_next_rebalance_at",
            "next_rebalance_at",
            postgresql_where=text("paused = false"),
        ),
    )


class AssetConfig(TimestampMixin, Base):
    """One row per user and asset.

    A row with `target_pct = 0` says *exit this position*. No row at all says *this asset
    is not managed*. Two intentions, told apart by the presence of the row.
    """

    __tablename__ = "asset_config"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    asset: Mapped[str] = mapped_column(String(16), primary_key=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    target_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)

    # A per-row bound, not the sum rule. The spec puts "the weights sum to 100 or less" in
    # the application layer; this only says a single weight is a percentage.
    __table_args__ = (
        CheckConstraint("target_pct >= 0 AND target_pct <= 100", name="ck_asset_config_target_pct"),
    )


class Order(TimestampMixin, Base):
    """Every order attempted, written `PENDING` before `AddOrder` is called."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Unique across the whole table, not per user. Kraken requires uniqueness among open
    # orders, and a global rule is both stronger and simpler to reason about.
    cl_ord_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    txid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OrderStatus.PENDING)
    requested_fiat: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    executed_volume: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    executed_price: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(AMOUNT, nullable=True)

    __table_args__ = (
        enum_check("side", Side, "ck_orders_side"),
        enum_check("reason", OrderReason, "ck_orders_reason"),
        enum_check("status", OrderStatus, "ck_orders_status"),
        Index("ix_orders_user_created_at", "user_id", "created_at"),
        # Every evaluation begins by asking whether this user has an unresolved attempt.
        # A partial index holds only the rows that answer yes, which is almost none.
        Index("ix_orders_user_pending", "user_id", postgresql_where=text("status = 'PENDING'")),
    )


class Proposal(TimestampMixin, Base):
    """At most one per user.

    A later phase owns the transitions between the statuses. This one owns the row and
    the rule that there is only ever one.
    """

    __tablename__ = "proposal"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # JSONB, because the plan is read back as structure: to compare versions and to
    # execute. Text that is only ever fetched whole stays Text.
    plan: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ProposalStatus.LIVE)

    __table_args__ = (
        enum_check("trigger", ProposalTrigger, "ck_proposal_trigger"),
        enum_check("status", ProposalStatus, "ck_proposal_status"),
    )


class PortfolioSnapshot(Base):
    """A point in the value series. Rows are inserted and never updated."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    cash: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    # Holds the unmanaged assets too, each flagged, so the user sees their real account
    # rather than a partial view of it.
    holdings: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_portfolio_snapshots_user_as_of", "user_id", "as_of"),)


class EvaluationSession(Base):
    """One row per user evaluation, not per system tick.

    The class is not called `Session` because SQLAlchemy already owns that name in every
    module that touches the database.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # No check constraint, and that is the one deliberate exception. Telemetry gains
    # values over time, and a constraint here would make each one a migration while
    # protecting nothing that matters.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Text, not JSONB: fetched whole and never queried into.
    log_messages: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_sessions_user_started_at", "user_id", "started_at"),
        # Retention deletes across every user at once, so it needs the date on its own.
        Index("ix_sessions_started_at", "started_at"),
    )
