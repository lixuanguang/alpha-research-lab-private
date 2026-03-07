"""Fill simulator — deterministic execution-report generation for research and testing.

:class:`FillSimulator` converts a
:class:`~alpha_core.execution.order_models.ValidatedOrder` into an
:class:`~alpha_core.execution.order_models.ExecutionReport` without any network
calls.  It models:

- **Market impact / slippage** — configurable basis-point spread applied
  adversely to the fill price.
- **Fees** — configurable basis-point cost applied to the gross notional.
- **Partial fill** — optional fill-ratio in ``(0, 1)`` for partial simulation.

The simulator is used by:

- Research / backtest pipelines (via :mod:`alpha_core.research.backtest_runner`)
  to produce synthetic fills from signal-derived order intents.
- Unit and integration tests for the execution layer.
- Live dry-run mode to preview what fills would look like without submitting.

Usage::

    sim = FillSimulator(FillConfig(slippage_bps=5, fee_bps=2))
    report = sim.simulate(validated_order, market_price=Decimal("0.62"))
    print(report.fill_price, report.fee)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.execution.order_models as order_models_mod
import alpha_core.strategy_framework.models as strategy_models

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ONE = Decimal("1")
_ZERO = Decimal("0")
_PRICE_PREC = Decimal("0.000001")  # 6 dp — sufficient for PM price space


class FillConfig(BaseModel):
    """Configuration for :class:`FillSimulator`."""

    model_config = ConfigDict(extra="forbid")

    slippage_bps: Decimal = Field(
        default=Decimal("5"),
        ge=_ZERO,
        description=(
            "Basis points of adverse price slippage applied to fills.  "
            "1 bps = 0.01%.  Applied as fraction of fill price."
        ),
    )
    fee_bps: Decimal = Field(
        default=Decimal("2"),
        ge=_ZERO,
        description=(
            "Basis points of fee applied to gross notional (size x fill_price).  "
            "1 bps = 0.01%."
        ),
    )
    fill_ratio: Decimal = Field(
        default=_ONE,
        gt=_ZERO,
        le=_ONE,
        description=(
            "Fraction of the requested size that gets filled.  "
            "1.0 = full fill; 0.5 = partial fill of 50%."
        ),
    )


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class FillSimulator:
    """Stateless fill simulator.

    Args:
        config: Fill model parameters.  Defaults to :class:`FillConfig` with
            5 bps slippage and 2 bps fee, full fill.
    """

    _BPS = Decimal("10000")

    def __init__(self, config: FillConfig | None = None) -> None:
        self._config = config or FillConfig()

    @property
    def config(self) -> FillConfig:
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate(
        self,
        validated_order: order_models_mod.ValidatedOrder,
        *,
        market_price: Decimal | None = None,
        order_id: str | None = None,
        fill_ts: datetime | None = None,
    ) -> order_models_mod.ExecutionReport:
        """Simulate order execution and return an :class:`ExecutionReport`.

        Args:
            validated_order: A pre-trade-validated order.  Orders with
                ``status=REJECTED`` are returned as
                :attr:`~alpha_core.execution.order_models.OrderLifecycleStatus.CANCELLED`
                fills with no price.
            market_price: Reference market price at fill time.  For LIMIT orders
                this defaults to ``intent.price_limit``; for MARKET orders it
                must be supplied (otherwise ``Decimal("0.5")`` is used as a
                fallback).
            order_id: Explicit order ID.  If omitted a UUID4 is generated.
            fill_ts: Explicit fill timestamp.  Defaults to ``datetime.now(UTC)``.

        Returns:
            An :class:`ExecutionReport` describing the simulated fill.
        """
        intent = validated_order.intent
        oid = order_id or str(uuid.uuid4())
        ts = fill_ts or datetime.now(tz=UTC)

        # Rejected intents short-circuit — report them as CANCELLED
        if not validated_order.is_valid:
            return order_models_mod.ExecutionReport(
                order_id=oid,
                instrument_id=intent.instrument_id,
                status=order_models_mod.OrderLifecycleStatus.CANCELLED,
                fill_ts=ts,
                notes=(
                    f"pre-trade rejected: {validated_order.reject_reason_code} — "
                    f"{validated_order.reject_reason_detail}"
                ),
                source_intent=intent,
            )

        # Resolve base price
        base_price = self._resolve_base_price(intent, market_price)

        # Apply slippage (adverse — always moves against the order direction)
        fill_price = self._apply_slippage(base_price, intent)

        # Clamp to [0, 1] (probability space)
        fill_price = max(_ZERO, min(_ONE, fill_price)).quantize(_PRICE_PREC)

        # Fill size (respects partial-fill ratio)
        fill_size = (intent.size * self._config.fill_ratio).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Fee = bps x notional
        notional = fill_size * fill_price
        fee = (notional * self._config.fee_bps / self._BPS).quantize(
            _PRICE_PREC, rounding=ROUND_HALF_UP
        )

        # Slippage delta (positive = adverse)
        slippage = fill_price - base_price

        # Determine terminal status
        status = (
            order_models_mod.OrderLifecycleStatus.FILLED
            if self._config.fill_ratio >= _ONE
            else order_models_mod.OrderLifecycleStatus.PARTIAL_FILL
        )

        return order_models_mod.ExecutionReport(
            order_id=oid,
            instrument_id=intent.instrument_id,
            status=status,
            fill_price=fill_price,
            fill_size=fill_size,
            fill_ts=ts,
            fee=fee,
            slippage=slippage,
            source_intent=intent,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_base_price(
        self,
        intent: strategy_models.OrderIntent,
        market_price: Decimal | None,
    ) -> Decimal:
        """Return the reference price before slippage is applied."""
        if intent.price_limit is not None:
            return intent.price_limit
        if market_price is not None:
            return market_price
        # MARKET order without a supplied price — use mid-market fallback
        return Decimal("0.5")

    def _apply_slippage(
        self,
        base_price: Decimal,
        intent: strategy_models.OrderIntent,
    ) -> Decimal:
        """Return the post-slippage fill price.

        Slippage is adverse:
        - LONG / BUY → fill price is *higher* than base price.
        - SHORT / SELL → fill price is *lower* than base price.
        - FLAT (exit) → treated same as SHORT.
        """
        slip_fraction = self._config.slippage_bps / self._BPS
        slip_delta = base_price * slip_fraction

        if intent.direction == strategy_models.SignalDirection.LONG:
            return base_price + slip_delta
        return base_price - slip_delta


__all__ = [
    "FillConfig",
    "FillSimulator",
]
