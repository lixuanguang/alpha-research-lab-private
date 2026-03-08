"""Slippage models for the event-driven backtester.

Defines a pluggable :class:`SlippageModel` protocol with two implementations:

- :class:`FixedSlippage` — constant basis-point spread applied to fill price.
- :class:`BookDepthSlippage` — walks the order book to estimate realistic
  fill price by consuming liquidity depth-by-depth.

Slippage is always *adverse*:

* **LONG / BUY** — fill price is *higher* than the reference price.
* **SHORT / SELL** — fill price is *lower* than the reference price.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models

_ZERO = Decimal("0")
_ONE = Decimal("1")
_BPS = Decimal("10000")


class SlippageModel(ABC):
    """Abstract base for pluggable slippage estimates."""

    @abstractmethod
    def estimate_slippage(
        self,
        order: exec_models.BacktestOrderIntent,
        book: Any | None,  # CanonicalBookSnapshot | None
    ) -> Decimal:
        """Return the price delta (absolute) due to market impact.

        The sign handling (adverse direction) is applied by the caller.
        """


class FixedSlippage(SlippageModel):
    """Constant basis-point slippage applied to fill price.

    Args:
        bps: Adverse slippage in basis points (default: 10 bps = 0.10%).
    """

    def __init__(self, bps: Decimal = Decimal("10")) -> None:
        if bps < _ZERO:
            raise ValueError(f"bps must be >= 0, got {bps}")
        self._bps = bps

    @property
    def bps(self) -> Decimal:
        return self._bps

    def estimate_slippage(
        self,
        order: exec_models.BacktestOrderIntent,
        book: Any | None,
    ) -> Decimal:
        """Return ``bps / 10000 x reference_price``."""
        ref = order.limit_price if order.limit_price is not None else Decimal("0.5")
        return (self._bps * ref / _BPS).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class BookDepthSlippage(SlippageModel):
    """Walks the order book to estimate price impact.

    If order-book data is not provided, falls back to :class:`FixedSlippage`
    with a conservative 15 bps estimate to avoid silent NaN propagation.

    The book is expected to have ``bids`` and ``asks`` fields as lists of
    ``(price, size)`` tuples sorted best-first.
    """

    _FALLBACK_BPS = Decimal("15")

    def __init__(self) -> None:
        self._fallback = FixedSlippage(bps=self._FALLBACK_BPS)

    def estimate_slippage(
        self,
        order: exec_models.BacktestOrderIntent,
        book: Any | None,
    ) -> Decimal:
        """Walk the book to find the volume-weighted average fill price.

        Returns the absolute slippage delta (fill_price - limit_price).
        Falls back to 15 bps fixed slippage when book is unavailable.
        """
        if book is None:
            return self._fallback.estimate_slippage(order, book)

        # Determine which side of the book to walk.
        if order.side == portfolio_models.Side.LONG:
            levels: list[tuple[Decimal, Decimal]] = getattr(book, "asks", []) or []
        else:
            levels = getattr(book, "bids", []) or []

        if not levels:
            return self._fallback.estimate_slippage(order, book)

        # Walk the book consuming depth until filled.
        remaining = order.size
        total_cost = _ZERO
        total_filled = _ZERO

        for level_price, level_size in levels:
            if remaining <= _ZERO:
                break
            take = min(remaining, level_size)
            total_cost += take * level_price
            total_filled += take
            remaining -= take

        if total_filled == _ZERO:
            return self._fallback.estimate_slippage(order, book)

        vwap = total_cost / total_filled

        # Base reference price.
        ref = order.limit_price if order.limit_price is not None else Decimal("0.5")
        slip = abs(vwap - ref)
        return slip.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


__all__ = ["BookDepthSlippage", "FixedSlippage", "SlippageModel"]
