"""Walk available L2 depth with exact fees, cash checks and persistent simulated depletion."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Fill, Ledger
from configuration import BookInstance
from financial_units import DecimalGrid, Price, Quantity
from market_data.contracts import BookObservation
from simulation.book_state import BookOrder, ConsumedLevel
from simulation.costs import SpotCosts


class BookExecution:
    """Own one instance's no-impact depletion overlay, never the recorded source book."""

    def __init__(self, instance: BookInstance, consumed: tuple[ConsumedLevel, ...] = ()) -> None:
        """Bind independent hard limits and exact costs; restore all consumed levels.

        Args:
            instance: Resolved size, lot/tick, cash and taker-fee assumptions.
            consumed: Validated depletion retained at a complete checkpoint boundary.
        """
        instance.__post_init__()
        self.instance = instance
        self._consumed = {(item.side, item.price): Fraction(item.size) for item in consumed}
        tick = instance.limits.tick
        self.costs = SpotCosts(
            adverse=Price(value=Decimal(0), currency=tick.currency, per=tick.per),
            fee_rate=instance.fee_rate,
            rounding="half_even" if instance.rounding == "half_even" else "half_up",
        )

    @property
    def consumed(self) -> tuple[ConsumedLevel, ...]:
        """Expose deterministically sorted depletion for checkpointing.

        Returns:
            Immutable side/price/quantity records in exact native units.
        """
        return tuple(
            ConsumedLevel(side=side, price=price, size=DecimalGrid.exact_decimal(size))
            for (side, price), size in sorted(self._consumed.items())
        )

    def update(self, row: BookObservation) -> None:
        """Clear depletion only for explicitly absent levels on valid source boundaries.

        Args:
            row: New exchange state. Same-price snapshots and size/count changes retain debt.
        """
        if row.status != "degraded" or row.outcome not in ("snapshot", "update"):
            return
        present = {("bid", price) for price, _ in row.bids} | {
            ("ask", price) for price, _ in row.asks
        }
        self._consumed = {key: size for key, size in self._consumed.items() if key in present}

    def execute(self, order: BookOrder, row: BookObservation, ledger: Ledger) -> BookOrder:
        """Fill best prices first, cap each level, round fees per fill and cancel remainder.

        Args:
            order: Pending IOC arriving now; one reservation per isolated instance.
            row: Valid fresh exchange book at arrival, independent of strategy delivery.
            ledger: Authoritative account; each level rechecks actual affordability and limits.

        Returns:
            Complete IOC outcome with unique price-level fills and explicit canceled size.
        """
        buying = order.requested.value > 0
        levels = sorted(row.asks) if buying else sorted(row.bids, reverse=True)
        side = "ask" if buying else "bid"
        remaining = abs(Fraction(order.requested.value))
        lot = Fraction(self.instance.limits.lot.value)
        fills: list[Fill] = []
        reason = "insufficient_displayed_liquidity"
        touch = self._price(levels[0][0])
        for price, level in levels:
            available = max(
                Fraction(),
                Fraction(level.size) * Fraction(self.instance.take_fraction)
                - self._consumed.get((side, price), Fraction()),
            )
            units = int(min(remaining, available) // lot)
            if not units:
                continue
            effective = self._price(price)
            if self.instance.limits.price_reason(effective) is not None:
                reason = "invalid_reference_price"
                break
            low, high = 0, units
            while low < high:
                trial = (low + high + 1) // 2
                fill = self._fill(order, effective, touch, trial, len(fills))
                rejection = self.instance.limits.fill_reason(
                    fill.quantity, effective, fill.fee, ledger.balance.cash, ledger.balance.holding
                )
                if rejection is None:
                    low = trial
                else:
                    high = trial - 1
            if low:
                fill = self._fill(order, effective, touch, low, len(fills))
                ledger.apply(fill)
                fills.append(fill)
                taken = low * lot
                self._consumed[(side, price)] = (
                    self._consumed.get((side, price), Fraction()) + taken
                )
                remaining -= taken
            if low < units:
                reason = "insufficient_cash_or_risk_limit"
                break
            if not remaining:
                reason = "filled"
                break
        completed_fills: tuple[Fill, ...] = tuple(fills)
        return replace(
            order,
            fills=completed_fills,
            canceled=Quantity(
                value=DecimalGrid.exact_decimal(remaining), dimension=order.requested.dimension
            ),
            status="filled" if not remaining else "partial" if fills else "canceled",
            reason=reason,
        )

    def _price(self, value: Decimal) -> Price:
        """Bind an exact native quote to the declared spot dimensions."""
        tick = self.instance.limits.tick
        return Price(value=value, currency=tick.currency, per=tick.per)

    def _fill(
        self, order: BookOrder, effective: Price, touch: Price, units: int, index: int
    ) -> Fill:
        """Price one whole-lot child fill with arrival touch as depth-slippage reference."""
        quantity = Quantity(
            value=DecimalGrid.exact_decimal(
                units
                * Fraction(self.instance.limits.lot.value)
                * (1 if order.requested.value > 0 else -1)
            ),
            dimension=order.requested.dimension,
        )
        fill = self.costs.fill(
            f"{order.identity}:{index}",
            decision_at=order.decision_at,
            filled_at=order.arrival_at,
            quantity=quantity,
            reference=effective,
        )
        return replace(fill, reference=touch)
