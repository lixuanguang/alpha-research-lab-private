"""Order lifecycle models for the execution layer.

Defines:

- :class:`RejectReasonCode` — structured, machine-readable reject codes.
- :class:`OrderLifecycleStatus` — states an order passes through from creation
  to settlement.
- :class:`ValidatedOrder` — wraps an :class:`~alpha_core.strategy_framework.models.OrderIntent`
  with the result of pre-trade validation (pass or reject + reason).
- :class:`ExecutionReport` — fill report produced by a venue adapter or fill
  simulator after an order is submitted.

Design notes:

- ``OrderIntent`` lives in ``alpha_core.strategy_framework.models`` and is the
  *input* to the execution layer.  This module only adds models that are produced
  *by* the execution layer — no duplication of the intent schema.
- All models use ``extra="forbid"`` for strict validation.  Serialisation via
  ``model.model_dump(mode="json")`` produces pure-JSON-compatible dicts whose
  schema is tested in the unit-test suite (acceptance criterion: "Execution
  report schema is stable and serialized in tests").
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.strategy_framework.models as strategy_models


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RejectReasonCode(StrEnum):
    """Structured, machine-readable reason codes for pre-trade rejection.

    All codes are stable — removing or renaming a code is a breaking change
    that requires a schema-version bump.
    """

    LIMIT_ORDER_NO_PRICE = "limit_order_no_price"
    """LIMIT order submitted without a ``price_limit`` value."""

    MARKET_ORDER_NOT_ALLOWED = "market_order_not_allowed"
    """MARKET orders are disabled by the validator configuration."""

    PRICE_OUT_OF_RANGE = "price_out_of_range"
    """``price_limit`` falls outside the configured [min_price, max_price] range."""

    SIZE_TOO_LARGE = "size_too_large"
    """Order size exceeds ``max_size_per_order``."""

    NOTIONAL_TOO_LARGE = "notional_too_large"
    """Implied notional (``size * price_limit``) exceeds ``max_notional_per_order``."""

    INSTRUMENT_NOT_ALLOWED = "instrument_not_allowed"
    """Instrument not in the validator's ``allowed_instruments`` allow-list."""

    CANCEL_ORDER_NO_SIZE = "cancel_order_no_size"
    """CANCEL-type order intents are routed directly; size checks are skipped."""

    UNKNOWN = "unknown"
    """Catch-all for errors not covered above; always accompanied by a detail note."""


class OrderLifecycleStatus(StrEnum):
    """States an order passes through from creation to settlement."""

    NEW = "new"
    """Order intent created but not yet validated."""

    VALIDATED = "validated"
    """Pre-trade checks passed; order is eligible for submission."""

    REJECTED = "rejected"
    """Pre-trade checks failed; order must not be submitted."""

    SUBMITTED = "submitted"
    """Order forwarded to a venue adapter; awaiting acknowledgement."""

    FILLED = "filled"
    """Order fully filled by the venue or fill simulator."""

    PARTIAL_FILL = "partial_fill"
    """Order partially filled; remainder may be cancelled or re-queued."""

    CANCELLED = "cancelled"
    """Order cancelled by the system or venue before full fill."""

    EXPIRED = "expired"
    """Order expired (e.g. day-order past session end) without fill."""


# ---------------------------------------------------------------------------
# ValidatedOrder
# ---------------------------------------------------------------------------


class ValidatedOrder(BaseModel):
    """An :class:`~alpha_core.strategy_framework.models.OrderIntent` decorated
    with the result of pre-trade validation.

    ``status`` is always either :attr:`OrderLifecycleStatus.VALIDATED` or
    :attr:`OrderLifecycleStatus.REJECTED`.  When rejected, ``reject_reason_code``
    and ``reject_reason_detail`` are populated.

    Example (accepted)::

        validated = ValidatedOrder(
            intent=order_intent,
            status=OrderLifecycleStatus.VALIDATED,
        )
        assert validated.is_valid

    Example (rejected)::

        validated = ValidatedOrder(
            intent=order_intent,
            status=OrderLifecycleStatus.REJECTED,
            reject_reason_code=RejectReasonCode.SIZE_TOO_LARGE,
            reject_reason_detail="size=50.0 exceeds max_size_per_order=10.0",
        )
        assert not validated.is_valid
    """

    model_config = ConfigDict(extra="forbid")

    intent: strategy_models.OrderIntent
    """The original order intent passed through pre-trade validation."""

    status: OrderLifecycleStatus
    """Must be VALIDATED or REJECTED at this stage of the lifecycle."""

    reject_reason_code: RejectReasonCode | None = None
    """Structured reject code; ``None`` when ``status == VALIDATED``."""

    reject_reason_detail: str | None = None
    """Human-readable elaboration of the reject reason; ``None`` when accepted."""

    validated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    """UTC timestamp when validation completed."""

    @property
    def is_valid(self) -> bool:
        """``True`` iff the order passed all pre-trade checks."""
        return self.status == OrderLifecycleStatus.VALIDATED


# ---------------------------------------------------------------------------
# ExecutionReport
# ---------------------------------------------------------------------------


class ExecutionReport(BaseModel):
    """Fill report produced after an order is submitted to a venue or fill simulator.

    For prediction-market venues prices are in ``[0, 1]`` (probability space).
    ``fill_price`` and ``fee`` use :class:`~decimal.Decimal` for exact arithmetic.

    Schema stability contract: all fields present today must remain in future
    versions.  New optional fields may be added; existing fields may not be
    removed or renamed without a schema-version increment.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1)
    """Venue-assigned order identifier."""

    instrument_id: str = Field(min_length=1)
    """Canonical instrument ID ``venue:market_id:outcome_id``."""

    status: OrderLifecycleStatus
    """Terminal status for this report (FILLED, PARTIAL_FILL, CANCELLED, etc.)."""

    fill_price: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Average fill price in probability space [0, 1].",
    )
    fill_size: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        description="Number of contracts filled.",
    )
    fill_ts: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    """UTC timestamp of fill (or partial-fill start)."""

    fee: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Total fee charged for this fill in dollars.",
    )
    slippage: Decimal = Field(
        default=Decimal("0"),
        description="fill_price minus intent price limit (positive = adverse).",
    )
    realized_pnl: Decimal | None = Field(
        default=None,
        description="Realized P&L for closing trades; None for opening positions.",
    )
    notes: str | None = None
    """Optional free-text diagnostic note from the adapter or simulator."""

    source_intent: strategy_models.OrderIntent
    """The :class:`~alpha_core.strategy_framework.models.OrderIntent` that
    originated this fill."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Adapter-specific or simulator-specific supplementary data."""


__all__ = [
    "ExecutionReport",
    "OrderLifecycleStatus",
    "RejectReasonCode",
    "ValidatedOrder",
]
