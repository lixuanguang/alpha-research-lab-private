"""Project verified completed observations into a deliberately bounded vectorbt research run."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import datetime, timedelta
from decimal import Decimal
from importlib.metadata import version

# project library imports
from financial_units import Money, Price, Quantity
from research.observations import TradePoint
from serialization import DomainCodec, WireRecord
from simulation.economics import EconomicResult
from strategies import Momentum, NoTrade


class VectorbtOrder(WireRecord, frozen=True):
    """Retain explicit delayed execution assumptions before converting anything to float."""

    decision_at: datetime
    executed_at: datetime
    target: Quantity
    reference: Price
    effective: Price
    fee: Money

    def __post_init__(self) -> None:
        """Refuse same-observation execution or malformed exact inputs."""
        self._require_utc(self.decision_at, field_name="decision_at")
        self._require_utc(self.executed_at, field_name="executed_at")
        if self.executed_at <= self.decision_at:
            raise ValueError("vectorbt requires explicit positive execution delay")
        for item in (self.target, self.reference, self.effective, self.fee):
            item.model_copy()
        if (
            self.target.dimension != self.reference.per
            or self.effective.per != self.reference.per
            or self.fee.currency != self.reference.currency
            or self.effective.currency != self.reference.currency
        ):
            raise ValueError("vectorbt order units differ")
        if (
            self.target.value < 0
            or self.reference.value <= 0
            or self.effective.value <= 0
            or self.fee.value < 0
        ):
            raise ValueError("unsupported vectorbt order")


class VectorbtResult(WireRecord, frozen=True):
    """Keep approximate engine output separate from the authoritative exact ledger."""

    reference_sha256: str
    engine: str
    versions: tuple[tuple[str, str], ...]
    orders: tuple[VectorbtOrder, ...]
    cash: tuple[float, ...]
    holdings: tuple[float, ...]
    nav: tuple[float, ...]
    exact_terminal_nav: Money
    absolute_tolerance: float
    relative_tolerance: float
    scope: str
    schema_version: str = "vectorbt-comparison-v1"

    def __post_init__(self) -> None:
        """Reject unsupported engine claims, malformed sequences and nonfinite projections."""
        if (
            self.schema_version != "vectorbt-comparison-v1"
            or self.engine != "vectorbt/numba"
            or len(self.reference_sha256) != 64
        ):
            raise ValueError("unsupported vectorbt result identity")
        if (
            not self.nav
            or len(self.cash) != len(self.nav)
            or len(self.holdings) != len(self.nav)
            or len(self.nav) != len(self.orders) + 1
        ):
            raise ValueError("vectorbt result shape mismatch")
        if any(
            type(value) is not float or not math.isfinite(value)
            for values in (self.cash, self.holdings, self.nav)
            for value in values
        ):
            raise ValueError("vectorbt produced a nonfinite or untyped projection")
        if self.absolute_tolerance != 1e-10 or self.relative_tolerance != 1e-12:
            raise ValueError("unsupported vectorbt comparison tolerance")
        for order in self.orders:
            order.__post_init__()
        self.exact_terminal_nav.model_copy()


class VectorbtAdapter:
    """Run funded long-only target orders with explicit next-print timing and rounded fixed fees.

    This is a narrow analytical projection. It independently regenerates targets and
    selects future prints; reference accepted fills are never used as its order input.
    Corrections, gaps, missing windows and contingent capital reuse are unsupported.
    """

    @staticmethod
    def _execution_order(point: TradePoint) -> tuple[datetime, int]:
        """Preserve chronological fill clocks and then the admitted source tie order."""
        return max(point.event_at, point.known_at), point.order

    @classmethod
    def run(cls, reference: EconomicResult) -> VectorbtResult:
        """Compare a supported simple rule against the independent exact economic result.

        Args:
            reference: Complete result of verified chronological replay, including frozen
                observations and original source revisions. This boundary revalidates bytes.

        Returns:
            Versioned approximate arrays, exact order assumptions and disclosed execution scope.

        Raises:
            ValueError: Unsupported inputs, mechanics, capital or material engine disagreement.
        """
        codec = DomainCodec()
        reference = codec.decode_json(codec.encode_json(reference), EconomicResult)
        spec, state = reference.spec, reference.checkpoint.state
        points, completed = state.observations.points, state.observations.completed
        if state.observations.gaps or any(item.point is None for item in completed):
            raise ValueError("vectorbt scope excludes gaps and missing completed observations")
        # A replacement removes an earlier head but increments the admitted order.
        # Refuse this boundary rather than turning terminal heads into historical input.
        if state.observations.next_order != len(points):
            raise ValueError("vectorbt scope excludes revision histories")
        rule: Momentum | NoTrade
        if spec.rule == "completed-price-momentum-v1":
            rule = Momentum()
        elif spec.rule == "no-trade-v1":
            rule = NoTrade()
        else:
            raise ValueError("unsupported vectorbt target rule")
        cadence, delay = (
            timedelta(seconds=spec.cadence_seconds),
            timedelta(seconds=spec.delay_seconds),
        )
        holding = Quantity(value=Decimal(0), dimension=spec.quantity.dimension)
        gross_purchases = Money(value=Decimal(0), currency=spec.initial_cash.currency)
        orders: list[VectorbtOrder] = []
        previous = None
        for observation in completed:
            target = rule.target(previous, observation, spec.quantity, cadence)
            previous = observation
            if target is None or target == holding:
                continue
            candidates = sorted(
                (
                    point
                    for point in points
                    if point.event_at >= observation.closed_at + delay
                    and point.known_at >= observation.closed_at + delay
                    and max(point.event_at, point.known_at)
                    < min(observation.closed_at + cadence, spec.end)
                    and max(point.event_at, point.known_at) - point.event_at
                    <= timedelta(seconds=spec.max_age_seconds)
                ),
                key=cls._execution_order,
            )
            if not candidates:
                continue
            point = candidates[0]
            if spec.limits.price_reason(point.price) is not None:
                raise ValueError("vectorbt execution reference is unsupported")
            delta = target - holding
            fill = spec.costs.fill(
                f"analytical-{len(orders)}",
                decision_at=observation.closed_at,
                filled_at=max(point.event_at, point.known_at),
                quantity=delta,
                reference=point.price,
            )
            if delta.value > 0:
                gross_purchases = gross_purchases + fill.effective.amount(delta) + fill.fee
            if gross_purchases.value > spec.initial_cash.value:
                raise ValueError(
                    "vectorbt scope requires capital covering gross purchases without reuse"
                )
            orders.append(
                VectorbtOrder(
                    decision_at=fill.decision_at,
                    executed_at=fill.filled_at,
                    target=target,
                    reference=fill.reference,
                    effective=fill.effective,
                    fee=fill.fee,
                )
            )
            holding = target
        terminal_points = [
            point for point in points if point.event_at < spec.end and point.known_at <= spec.end
        ]
        terminal = max(terminal_points, key=cls._mark_order) if terminal_points else None
        if terminal is None:
            raise ValueError("vectorbt projection requires an explicit terminal reference")
        # The exact result must already contain successful eligibility/valuation at the
        # terminal. Verify the independently selected signals and executions too.
        exact = state.ledger.fills
        if len(exact) != len(orders) or any(
            (fill.decision_at, fill.filled_at, fill.effective, fill.fee)
            != (order.decision_at, order.executed_at, order.effective, order.fee)
            for fill, order in zip(exact, orders, strict=True)
        ):
            raise ValueError("vectorbt scope cannot reproduce the reference intent outcomes")
        return cls._execute(reference, tuple(orders), terminal.price)

    @staticmethod
    def _mark_order(point: TradePoint) -> tuple[datetime, int]:
        """Select the event-time terminal mark without using hash-based tie ordering."""
        return point.event_at, point.order

    @staticmethod
    def _execute(
        reference: EconomicResult, orders: tuple[VectorbtOrder, ...], terminal: Price
    ) -> VectorbtResult:
        """Call the pinned real Numba engine with every relevant execution default explicit."""
        # third party library imports
        import vectorbt

        versions = tuple(
            (name, version(name))
            for name in ("vectorbt", "numba", "llvmlite", "numpy", "pandas", "plotly")
        )
        if version("vectorbt") != "1.1.0":
            raise ValueError("vectorbt adapter requires its exercised engine version 1.1.0")
        prices = [float(order.effective.value) for order in orders] + [float(terminal.value)]
        closes = [float(order.reference.value) for order in orders] + [float(terminal.value)]
        targets = [float(order.target.value) for order in orders] + [math.nan]
        fees = [float(order.fee.value) for order in orders] + [0.0]
        portfolio = vectorbt.Portfolio.from_orders(
            closes,
            size=targets,
            size_type="targetamount",
            direction="longonly",
            price=prices,
            fees=0.0,
            fixed_fees=fees,
            slippage=0.0,
            init_cash=float(reference.spec.initial_cash.value),
            cash_sharing=False,
            allow_partial=False,
            raise_reject=True,
            lock_cash=True,
            ffill_val_price=False,
            update_value=True,
            reject_prob=0.0,
            seed=0,
            engine="numba",
        )
        cash, holdings, nav = (
            tuple(portfolio.cash().tolist()),
            tuple(portfolio.assets().tolist()),
            tuple(portfolio.value().tolist()),
        )
        result = VectorbtResult(
            reference_sha256=hashlib.sha256(DomainCodec().encode_json(reference)).hexdigest(),
            engine="vectorbt/numba",
            versions=versions,
            orders=orders,
            cash=cash,
            holdings=holdings,
            nav=nav,
            exact_terminal_nav=reference.terminal.nav,
            absolute_tolerance=1e-10,
            relative_tolerance=1e-12,
            scope=(
                "single isolated cash-funded spot; completed-window signals; "
                "explicit positive-delay prints; full long-only targets; "
                "exact rounded fees projected to float; no shared capital, gaps, "
                "corrections, queue, liquidity or impact"
            ),
        )
        if not math.isclose(
            result.nav[-1],
            float(reference.terminal.nav.value),
            rel_tol=result.relative_tolerance,
            abs_tol=result.absolute_tolerance,
        ):
            raise ValueError("vectorbt terminal NAV differs beyond analytical float tolerance")
        return result
