"""Fee calculation helpers for the event-driven backtester.

Thin helpers on top of :class:`~alpha_core.execution.models.FeeSchedule`
that produce Decimal-exact fee amounts for fills and resolutions.

Usage::

    schedule = FeeSchedule(taker_fee_bps=Decimal("20"))
    fee = total_fill_fee(schedule, fill_size=Decimal("5"), fill_price=Decimal("0.6"))
    # fee = 5 × 0.6 × 0.0020 = 0.006000
"""

from __future__ import annotations

from decimal import Decimal

from alpha_core.execution.models import FeeSchedule

_ZERO = Decimal("0")


def total_fill_fee(
    schedule: FeeSchedule,
    fill_size: Decimal,
    fill_price: Decimal,
    *,
    is_maker: bool = False,
) -> Decimal:
    """Compute the total fee for a single fill.

    Combines:
    * Maker or taker fee on notional (``fill_size × fill_price``).
    * Per-contract flat fee (``fill_size × per_contract_fee``).

    Args:
        schedule: Fee schedule to apply.
        fill_size: Number of contracts filled.
        fill_price: Fill price per contract.
        is_maker: If ``True``, apply maker rate; otherwise taker rate.

    Returns:
        Total fee in dollars (Decimal).
    """
    notional = fill_size * fill_price
    rate_fee = schedule.maker_fee(notional) if is_maker else schedule.taker_fee(notional)
    per_contract = (fill_size * schedule.per_contract_fee).quantize(Decimal("0.000001"))
    return rate_fee + per_contract


def total_resolution_fee(
    schedule: FeeSchedule,
    fill_size: Decimal,
    resolved_price: Decimal,
) -> Decimal:
    """Compute the resolution-specific fee on a settled position.

    Args:
        schedule: Fee schedule to apply.
        fill_size: Number of contracts being settled.
        resolved_price: Resolution price (0 or 1 for binary PM).

    Returns:
        Resolution fee in dollars (Decimal).
    """
    payoff = fill_size * resolved_price
    return schedule.resolution_fee(payoff)


__all__ = ["total_fill_fee", "total_resolution_fee"]
