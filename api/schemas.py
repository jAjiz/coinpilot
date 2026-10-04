"""Every request and response body.

A response model is a whitelist: a field that is not declared here cannot reach a client,
whatever the ORM row carries. No model in this file has a field for a Kraken key or
secret on the way out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator

from core.db.types import CadenceMode


class TokenPairOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class RefreshIn(BaseModel):
    """The body of a refresh or a logout. A browser sends no body and relies on the cookie."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr | None = None


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    provider: str
    status: str
    created_at: datetime


class CredentialsIn(BaseModel):
    # `SecretStr` keeps the values out of a repr. It does not keep them out of a
    # validation error; the handler in `api/app.py` does that.
    api_key: SecretStr = Field(min_length=1, max_length=256)
    api_secret: SecretStr = Field(min_length=1, max_length=512)


class KeyAcceptedOut(BaseModel):
    validated_at: datetime
    permissions: list[str]
    ip_allowlist: list[str]
    # Granted but never used by the platform. Turning them off in Kraken is recommended,
    # not required: the key was stored.
    unnecessary: list[str]


class CredentialStatusOut(BaseModel):
    registered: bool
    validated_at: datetime | None = None
    key_version: int | None = None


# Nullable columns may be cleared with an explicit null. These may not.
_NOT_NULL = (
    "invest_cash_enabled",
    "cash_rebalance_enabled",
    "auto_rebalance_enabled",
    "paused",
    "min_drift_pct",
    "min_order_fiat",
    "invest_cadence_mode",
    "rebalance_cadence_mode",
)


class ConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fiat: str
    invest_cash_enabled: bool
    cash_rebalance_enabled: bool
    auto_rebalance_enabled: bool
    min_drift_pct: Decimal
    min_order_fiat: Decimal
    invest_cadence_mode: CadenceMode
    invest_interval_days: int | None
    invest_interval_months: int | None
    invest_cadence_anchor: datetime | None
    rebalance_cadence_mode: CadenceMode
    rebalance_interval_days: int | None
    rebalance_interval_months: int | None
    rebalance_cadence_anchor: datetime | None
    next_invest_at: datetime | None
    next_rebalance_at: datetime | None
    paused: bool


class ConfigPatch(BaseModel):
    """Every field optional. `next_invest_at` and `next_rebalance_at` are absent on purpose:
    the scheduler owns them, and `extra="forbid"` turns an attempt into a 422."""

    model_config = ConfigDict(extra="forbid")

    fiat: str | None = None
    invest_cash_enabled: bool | None = None
    cash_rebalance_enabled: bool | None = None
    auto_rebalance_enabled: bool | None = None
    paused: bool | None = None
    # Numeric(4,1) and Numeric(10,1): the bounds are the columns'.
    min_drift_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=1)
    min_order_fiat: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999.9"), decimal_places=1)
    invest_cadence_mode: CadenceMode | None = None
    invest_interval_days: int | None = Field(default=None, ge=0, le=3650)
    invest_interval_months: int | None = Field(default=None, ge=0, le=120)
    invest_cadence_anchor: AwareDatetime | None = None
    rebalance_cadence_mode: CadenceMode | None = None
    rebalance_interval_days: int | None = Field(default=None, ge=0, le=3650)
    rebalance_interval_months: int | None = Field(default=None, ge=0, le=120)
    rebalance_cadence_anchor: AwareDatetime | None = None

    @model_validator(mode="after")
    def _no_null_for_required(self) -> ConfigPatch:
        cleared = [
            name for name in _NOT_NULL if name in self.model_fields_set and getattr(self, name) is None
        ]
        if cleared:
            raise ValueError(f"these settings cannot be null: {', '.join(cleared)}")
        return self


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_pct: Decimal = Field(ge=0, le=100, decimal_places=2)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset: str
    pair: str
    target_pct: Decimal
    # Kraken's smallest order on the asset's pair, in fiat, at the current price (§7.3).
    # Absent from `PUT`, and `null` when Kraken could not be read.
    kraken_min_fiat: str | None = None


class AssetsOut(BaseModel):
    assets: list[AssetOut]
    cash_target_pct: Decimal


class PortfolioOut(BaseModel):
    as_of: datetime
    fiat: str
    # Managed assets plus cash: the denominator of every weight. Plain decimal strings,
    # written like the amounts inside `holdings`.
    total_value: str
    cash: str
    holdings: dict[str, object]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cl_ord_id: str
    txid: str | None
    pair: str
    asset: str
    side: str
    reason: str
    status: str
    requested_fiat: Decimal
    executed_volume: Decimal | None
    executed_price: Decimal | None
    fee: Decimal | None
    cost: Decimal | None
    error: str | None
    created_at: datetime


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: str
    log_messages: str | None


class LegOut(BaseModel):
    """One leg of an operation. Every amount is a plain decimal string."""

    asset: str
    pair: str
    side: str
    amount_fiat: str
    minimum_fiat: str | None
    status: str
    cl_ord_id: str | None
    txid: str | None
    cost: str | None
    executed_volume: str | None
    executed_price: str | None
    fee: str | None
    error: str | None
    note: str | None
    # A sell's volume of the asset. A buy is placed in fiat and has none.
    volume: str | None


class InvestOut(BaseModel):
    status: str
    preview: bool
    legs: list[LegOut]
    messages: list[str]


class ProposalLegOut(BaseModel):
    """One leg as it was proposed, the skipped ones too, with why."""

    asset: str
    pair: str
    side: str
    amount_fiat: str
    minimum_fiat: str | None
    note: str | None


class ProposalOut(BaseModel):
    version: int
    status: str
    trigger: str
    fiat: str
    legs: list[ProposalLegOut]
    updated_at: datetime


class ApproveIn(BaseModel):
    """The version read. An approval of any other is refused (spec §8)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class RebalanceOut(BaseModel):
    status: str
    # What was sent. Empty for a proposal, which sends nothing.
    legs: list[LegOut]
    # The live proposal as the evaluation left it. `null` when there is none.
    proposal: ProposalOut | None
    messages: list[str]
