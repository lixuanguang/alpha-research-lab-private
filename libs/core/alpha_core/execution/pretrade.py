"""Pre-trade validator for prediction-market order intents.

Applies a configurable set of guardrails to each
:class:`~alpha_core.strategy_framework.models.OrderIntent` before it reaches
a venue adapter.  Invalid intents are returned as
:class:`~alpha_core.execution.order_models.ValidatedOrder` with
``status=REJECTED`` and a structured :class:`~alpha_core.execution.order_models.RejectReasonCode`.

Design principles:

- **Deterministic reject codes** — same intent + same config always produces
  the same :class:`~alpha_core.execution.order_models.RejectReasonCode`.
- **Check ordering** — checks execute in a fixed, documented sequence; the
  first failing check produces the reject code (no multi-failure accumulation
  in this version).
- **Stateless** — the validator carries no mutable state; it is safe to share
  across threads.
- **MarketState integration** — ``state`` is accepted for future checks
  (e.g. spread sanity vs live mid-price) but is currently optional.

Public API::

    config = PreTradeConfig(
        max_size_per_order=Decimal("10"),
        allow_market_orders=False,
    )
    validator = PreTradeValidator(config)
    validated = validator.validate(order_intent, state=market_state)
    if not validated.is_valid:
        print(validated.reject_reason_code)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.execution.order_models as order_models_mod
import alpha_core.strategy_framework.models as strategy_models

log = logging.getLogger(__name__)

# Default price bounds for prediction-market contracts (probability space).
_DEFAULT_MIN_PRICE = Decimal("0.01")
_DEFAULT_MAX_PRICE = Decimal("0.99")
_DEFAULT_MAX_SIZE = Decimal("1000")
_DEFAULT_MAX_NOTIONAL = Decimal("500")  # dollars


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class PreTradeConfig(BaseModel):
    """Configuration for :class:`PreTradeValidator`.

    All monetary values are in the contract's native currency (USD for most
    PM venues).  Prices are in probability space ``[0, 1]``.
    """

    model_config = ConfigDict(extra="forbid")

    allow_market_orders: bool = Field(
        default=True,
        description="If False, MARKET-type orders are rejected outright.",
    )
    min_price: Decimal = Field(
        default=_DEFAULT_MIN_PRICE,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Minimum allowed price_limit for LIMIT orders.",
    )
    max_price: Decimal = Field(
        default=_DEFAULT_MAX_PRICE,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Maximum allowed price_limit for LIMIT orders.",
    )
    max_size_per_order: Decimal = Field(
        default=_DEFAULT_MAX_SIZE,
        gt=Decimal("0"),
        description="Maximum number of contracts in a single order.",
    )
    max_notional_per_order: Decimal = Field(
        default=_DEFAULT_MAX_NOTIONAL,
        gt=Decimal("0"),
        description="Maximum implied notional (size x price_limit) in dollars.",
    )
    allowed_instruments: frozenset[str] | None = Field(
        default=None,
        description=(
            "Optional allow-list of canonical instrument IDs.  "
            "When set, any order whose instrument_id is not in this set "
            "is rejected with INSTRUMENT_NOT_ALLOWED."
        ),
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class PreTradeValidator:
    """Stateless pre-trade guardrail for PM-style order intents.

    Args:
        config: Validation parameters.  Defaults to :class:`PreTradeConfig`
            with sensible PM-market defaults.

    Check sequence (first failure wins):

    1. Instrument allow-list (if configured).
    2. MARKET order policy.
    3. LIMIT order must have ``price_limit``.
    4. ``price_limit`` within ``[min_price, max_price]``.
    5. ``size`` ≤ ``max_size_per_order``.
    6. Implied notional ≤ ``max_notional_per_order`` (LIMIT orders only).
    """

    def __init__(self, config: PreTradeConfig | None = None) -> None:
        self._config = config or PreTradeConfig()

    @property
    def config(self) -> PreTradeConfig:
        """The active validation configuration (read-only)."""
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        intent: strategy_models.OrderIntent,
        *,
        state: strategy_models.MarketState | None = None,
    ) -> order_models_mod.ValidatedOrder:
        """Validate a single :class:`~alpha_core.strategy_framework.models.OrderIntent`.

        Args:
            intent: The order intent to validate.
            state:  Optional market state snapshot for context-aware checks
                    (reserved for future use; currently unused but accepted
                    for API stability).

        Returns:
            A :class:`~alpha_core.execution.order_models.ValidatedOrder` with
            ``status=VALIDATED`` on success or ``status=REJECTED`` on failure.
        """
        del state  # reserved for future market-state-aware checks
        code, detail = self._run_checks(intent)
        if code is not None:
            log.debug(
                "pre-trade reject instrument=%s code=%s detail=%s",
                intent.instrument_id,
                code,
                detail,
            )
            return order_models_mod.ValidatedOrder(
                intent=intent,
                status=order_models_mod.OrderLifecycleStatus.REJECTED,
                reject_reason_code=code,
                reject_reason_detail=detail,
            )

        log.debug("pre-trade accept instrument=%s", intent.instrument_id)
        return order_models_mod.ValidatedOrder(
            intent=intent,
            status=order_models_mod.OrderLifecycleStatus.VALIDATED,
        )

    def validate_batch(
        self,
        intents: Sequence[strategy_models.OrderIntent],
        *,
        state: strategy_models.MarketState | None = None,
    ) -> list[order_models_mod.ValidatedOrder]:
        """Validate a batch of intents and return one result per intent.

        Processing is sequential; no intent is skipped even if earlier ones fail.
        """
        return [self.validate(intent, state=state) for intent in intents]

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _run_checks(
        self,
        intent: strategy_models.OrderIntent,
    ) -> tuple[order_models_mod.RejectReasonCode | None, str | None]:
        """Return ``(reason_code, detail)`` for the first failing check, or
        ``(None, None)`` if all checks pass."""

        # 1. Instrument allow-list
        if (
            self._config.allowed_instruments is not None
            and intent.instrument_id not in self._config.allowed_instruments
        ):
            return (
                order_models_mod.RejectReasonCode.INSTRUMENT_NOT_ALLOWED,
                f"instrument_id={intent.instrument_id!r} not in allowed_instruments",
            )

        # CANCEL orders bypass size/price checks — they are control signals, not
        # orders that consume liquidity.
        if intent.order_type == strategy_models.OrderType.CANCEL:
            return (None, None)

        # 2. MARKET order policy
        if (
            not self._config.allow_market_orders
            and intent.order_type == strategy_models.OrderType.MARKET
        ):
            return (
                order_models_mod.RejectReasonCode.MARKET_ORDER_NOT_ALLOWED,
                "MARKET orders are disabled by pre-trade config (allow_market_orders=False)",
            )

        # 3. LIMIT order requires price_limit
        if intent.order_type == strategy_models.OrderType.LIMIT and intent.price_limit is None:
            return (
                order_models_mod.RejectReasonCode.LIMIT_ORDER_NO_PRICE,
                "LIMIT order must have price_limit set",
            )

        # 4. price_limit range check (only when price is present)
        if intent.price_limit is not None:
            if (
                intent.price_limit < self._config.min_price
                or intent.price_limit > self._config.max_price
            ):
                return (
                    order_models_mod.RejectReasonCode.PRICE_OUT_OF_RANGE,
                    (
                        f"price_limit={intent.price_limit} outside "
                        f"[{self._config.min_price}, {self._config.max_price}]"
                    ),
                )

        # 5. Size cap
        if intent.size > self._config.max_size_per_order:
            return (
                order_models_mod.RejectReasonCode.SIZE_TOO_LARGE,
                (
                    f"size={intent.size} exceeds "
                    f"max_size_per_order={self._config.max_size_per_order}"
                ),
            )

        # 6. Notional cap (only for LIMIT orders where price is known)
        if intent.price_limit is not None:
            notional = intent.size * intent.price_limit
            if notional > self._config.max_notional_per_order:
                return (
                    order_models_mod.RejectReasonCode.NOTIONAL_TOO_LARGE,
                    (
                        f"notional={notional} (size={intent.size} x "
                        f"price={intent.price_limit}) exceeds "
                        f"max_notional_per_order={self._config.max_notional_per_order}"
                    ),
                )

        return (None, None)


__all__ = [
    "PreTradeConfig",
    "PreTradeValidator",
]
