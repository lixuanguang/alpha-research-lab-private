"""PortfolioTracker — stateful position and cash accounting.

:class:`PortfolioTracker` maintains exact Decimal arithmetic for:

- Opening / adding-to long and short positions via :meth:`apply_fill`.
- Handling prediction-market resolution (binary 0 / 1 payoff) via
  :meth:`apply_resolution`.
- Mark-to-market updates via :meth:`mark_to_market`.
- Snapshotting current state and equity-curve history.

Prediction-market accounting conventions
-----------------------------------------
**LONG position** (bought YES contracts):

* Entry: ``cash -= size × fill_price + fee``
* MtM:   ``unrealised_pnl = size × (current_price − entry_price)``
* Resolution at *p*: ``cash += size × p``, ``realised_pnl = size × (p − entry_price)``

**SHORT position** (sold YES contracts = bought NO contracts):

* Entry: ``cash += size × fill_price − fee``
* MtM:   ``unrealised_pnl = size × (entry_price − current_price)``
* Resolution at *p*: ``cash -= size × p``, ``realised_pnl = size × (entry_price − p)``

Reducing a position works symmetrically: a LONG fill applied against an
existing SHORT reduces the short (and vice versa), booking realised PnL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from alpha_core.portfolio.models import PortfolioState, PositionState, Side

if TYPE_CHECKING:
    import alpha_core.execution.models as exec_models

_ZERO = Decimal("0")
_ONE = Decimal("1")
_PRICE_PREC = Decimal("0.000001")


class PortfolioTracker:
    """Maintains portfolio state through a sequence of fills and resolutions.

    Args:
        initial_cash: Starting cash balance (default: ``Decimal("10000")``).
    """

    def __init__(self, initial_cash: Decimal = Decimal("10000")) -> None:
        self._cash: Decimal = initial_cash
        self._positions: dict[str, PositionState] = {}
        self._equity_history: list[tuple[datetime, Decimal]] = []
        self._position_history: list[PositionState] = []
        self._total_fees: Decimal = _ZERO
        self._total_realised: Decimal = _ZERO

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_fill(self, fill: exec_models.SimulatedFill) -> None:
        """Apply a simulated fill to the portfolio.

        Handles:
        * Opening a new position.
        * Adding to an existing same-side position (average-cost basis).
        * Reducing or closing an opposite-side position.

        The fill's ``fee`` is always subtracted from ``cash`` regardless
        of direction.
        """
        order = fill.order
        instr = order.instrument_id
        side = order.side
        size = fill.fill_size
        price = fill.fill_price
        fee = fill.fee
        ts = fill.timestamp

        self._total_fees += fee

        existing = self._positions.get(instr)

        if existing is None:
            # Brand-new position.
            self._positions[instr] = self._open_position(instr, side, size, price, fee, ts)
            self._adjust_cash(side, size, price, fee)
        elif existing.side == side:
            # Adding to same-side position — volume-weighted average entry.
            self._positions[instr] = self._add_to_position(existing, size, price, fee, ts)
            self._adjust_cash(side, size, price, fee)
        else:
            # Opposite side — reduce or close.
            self._positions[instr] = self._reduce_position(existing, size, price, fee, ts)
            self._adjust_cash(side, size, price, fee)
            realised = self._positions[instr].realised_pnl if instr in self._positions else _ZERO
            # If fully closed, move to history.
            if instr in self._positions and self._positions[instr].size == _ZERO:
                self._position_history.append(self._positions.pop(instr))
            self._total_realised = sum(
                p.realised_pnl for p in self._positions.values()
            ) + sum(p.realised_pnl for p in self._position_history)

    def apply_resolution(
        self,
        instrument_id: str,
        resolved_price: Decimal,
    ) -> None:
        """Handle prediction-market resolution.

        ``resolved_price`` must be exactly ``Decimal("0")`` or ``Decimal("1")`` —
        no partial resolution is supported.

        The position is settled and moved to history.  Cash is adjusted by the
        terminal payoff.
        """
        pos = self._positions.get(instrument_id)
        if pos is None:
            return  # No open position — nothing to settle.

        if pos.side == Side.LONG:
            # Receive payoff.
            payoff = pos.size * resolved_price
            pnl = pos.size * (resolved_price - pos.entry_price)
            self._cash += payoff
        else:  # SHORT
            # Pay out to counterparty.
            payoff = pos.size * resolved_price
            pnl = pos.size * (pos.entry_price - resolved_price)
            self._cash -= payoff

        settled = pos.model_copy(update={
            "current_price": resolved_price,
            "realised_pnl": pnl,
            "unrealised_pnl": _ZERO,
            "last_updated": datetime.now(tz=UTC),
        })
        self._position_history.append(settled)
        del self._positions[instrument_id]
        self._total_realised += pnl

    def mark_to_market(
        self,
        prices: dict[str, Decimal],
        timestamp: datetime,
    ) -> None:
        """Update current prices and recalculate unrealised PnL for all positions.

        Args:
            prices: Latest known price per instrument ID.
            timestamp: The timestamp this mark represents.
        """
        for instr, pos in list(self._positions.items()):
            new_price = prices.get(instr)
            if new_price is None:
                continue
            new_price = max(_ZERO, min(_ONE, new_price))
            if pos.side == Side.LONG:
                upnl = pos.size * (new_price - pos.entry_price)
            else:
                upnl = pos.size * (pos.entry_price - new_price)
            self._positions[instr] = pos.model_copy(update={
                "current_price": new_price,
                "unrealised_pnl": upnl,
                "last_updated": timestamp,
            })

        # Record equity snapshot.
        self._equity_history.append((timestamp, self._equity()))

    def state(self) -> PortfolioState:
        """Return a snapshot of the current portfolio state."""
        ts = datetime.now(tz=UTC)
        eq = self._equity()
        total_pnl = self._total_realised + sum(
            p.unrealised_pnl for p in self._positions.values()
        )
        return PortfolioState(
            timestamp=ts,
            cash=self._cash,
            positions=dict(self._positions),
            total_pnl=total_pnl,
            total_fees=self._total_fees,
            equity=eq,
        )

    def equity_curve(self) -> list[tuple[datetime, Decimal]]:
        """Return chronological list of ``(timestamp, equity)`` tuples."""
        return list(self._equity_history)

    def position_history(self) -> list[PositionState]:
        """Return closed positions (settled or fully reduced)."""
        return list(self._position_history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _equity(self) -> Decimal:
        return self._cash + sum(p.unrealised_pnl for p in self._positions.values())

    def _adjust_cash(
        self,
        side: Side,
        size: Decimal,
        price: Decimal,
        fee: Decimal,
    ) -> None:
        notional = size * price
        if side == Side.LONG:
            self._cash -= notional + fee
        else:
            self._cash += notional - fee

    @staticmethod
    def _open_position(
        instrument_id: str,
        side: Side,
        size: Decimal,
        price: Decimal,
        fee: Decimal,
        ts: datetime,
    ) -> PositionState:
        if side == Side.LONG:
            upnl = _ZERO  # Just opened at entry price.
        else:
            upnl = _ZERO
        return PositionState(
            instrument_id=instrument_id,
            side=side,
            size=size,
            entry_price=price,
            current_price=price,
            unrealised_pnl=upnl,
            realised_pnl=_ZERO,
            fees_paid=fee,
            opened_at=ts,
            last_updated=ts,
        )

    @staticmethod
    def _add_to_position(
        pos: PositionState,
        size: Decimal,
        price: Decimal,
        fee: Decimal,
        ts: datetime,
    ) -> PositionState:
        new_size = pos.size + size
        # Volume-weighted average entry price.
        new_entry = (pos.entry_price * pos.size + price * size) / new_size
        return pos.model_copy(update={
            "size": new_size,
            "entry_price": new_entry.quantize(_PRICE_PREC, rounding=ROUND_HALF_UP),
            "fees_paid": pos.fees_paid + fee,
            "last_updated": ts,
        })

    def _reduce_position(
        self,
        pos: PositionState,
        close_size: Decimal,
        close_price: Decimal,
        fee: Decimal,
        ts: datetime,
    ) -> PositionState:
        actual_close = min(close_size, pos.size)
        remaining = pos.size - actual_close

        # The original side is opposite to the fill that is now closing it.
        if pos.side == Side.LONG:
            partial_pnl = actual_close * (close_price - pos.entry_price)
        else:
            partial_pnl = actual_close * (pos.entry_price - close_price)

        new_realised = pos.realised_pnl + partial_pnl

        if remaining == _ZERO:
            # Fully closed.
            return pos.model_copy(update={
                "size": _ZERO,
                "current_price": close_price,
                "unrealised_pnl": _ZERO,
                "realised_pnl": new_realised,
                "fees_paid": pos.fees_paid + fee,
                "last_updated": ts,
            })
        # Partially closed — keep same entry price on remainder.
        # Unrealised PnL on remaining size.
        if pos.side == Side.LONG:
            new_upnl = remaining * (close_price - pos.entry_price)
        else:
            new_upnl = remaining * (pos.entry_price - close_price)
        return pos.model_copy(update={
            "size": remaining,
            "current_price": close_price,
            "unrealised_pnl": new_upnl,
            "realised_pnl": new_realised,
            "fees_paid": pos.fees_paid + fee,
            "last_updated": ts,
        })


__all__ = ["PortfolioTracker"]
