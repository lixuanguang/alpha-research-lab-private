"""Project verified completed observations into a deliberately bounded vectorbt research run."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from importlib.metadata import version
from typing import ClassVar

# project library imports
from financial_units import Money, Price, Quantity
from research.observations import TradePoint
from serialization import DomainCodec, WireRecord
from simulation.economics import EconomicResult
from strategies import RuleRegistry


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
    nav_error_bound: float
    scope: str
    schema_version: str = "vectorbt-comparison"

    def __post_init__(self) -> None:
        """Reject unsupported engine claims, malformed sequences and nonfinite projections."""
        if (
            self.schema_version != "vectorbt-comparison"
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
        if (
            type(self.nav_error_bound) is not float
            or not math.isfinite(self.nav_error_bound)
            or self.nav_error_bound <= 0
        ):
            raise ValueError("unsupported vectorbt comparison error bound")
        for order in self.orders:
            order.__post_init__()
        self.exact_terminal_nav.model_copy()
        if not abs(self.nav[-1] - float(self.exact_terminal_nav.value)) <= self.nav_error_bound:
            raise ValueError("vectorbt terminal NAV differs beyond its float error bound")


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
    def run(
        cls, reference: EconomicResult, *, registry: RuleRegistry | None = None
    ) -> VectorbtResult:
        """Compare a supported simple rule against the independent exact economic result.

        Args:
            reference: Complete result of verified chronological replay, including frozen
                observations and original source revisions. This boundary revalidates bytes.
            registry: Optional target-rule registry used to regenerate the configured rule.

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
        resolved_registry = RuleRegistry() if registry is None else registry
        if not resolved_registry.supports(spec.rule):
            raise ValueError("unsupported vectorbt target rule")
        rule = resolved_registry.resolve(spec.rule)
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

    @classmethod
    def _execute(
        cls, reference: EconomicResult, orders: tuple[VectorbtOrder, ...], terminal: Price
    ) -> VectorbtResult:
        """Run the pinned engine and retain its NAV only within the derived float error bound."""
        versions = tuple(
            (name, version(name))
            for name in ("vectorbt", "numba", "llvmlite", "numpy", "pandas", "plotly")
        )
        initial = reference.spec.initial_cash.value
        cash, holdings, nav = cls.project(initial, orders, terminal)
        return VectorbtResult(
            reference_sha256=hashlib.sha256(DomainCodec().encode_json(reference)).hexdigest(),
            engine="vectorbt/numba",
            versions=versions,
            orders=orders,
            cash=cash,
            holdings=holdings,
            nav=nav,
            exact_terminal_nav=reference.terminal.nav,
            nav_error_bound=cls.nav_error_bound(initial, orders, terminal),
            scope=(
                "single isolated cash-funded spot; completed-window signals; "
                "explicit positive-delay prints; full long-only targets; "
                "exact rounded fees projected to float; no shared capital, gaps, "
                "corrections, queue, liquidity or impact"
            ),
        )

    @staticmethod
    def project(
        initial: Decimal, orders: tuple[VectorbtOrder, ...], terminal: Price
    ) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
        """Call the pinned real Numba engine with every relevant execution default explicit.

        Args:
            initial: Exact initial cash.
            orders: Exact delayed long-only target orders in execution order.
            terminal: Exact terminal valuation price.

        Returns:
            Float cash, holdings and NAV after each order and at the terminal mark.

        Raises:
            ValueError: The engine version differs or rejects an order.
        """
        # third party library imports
        import vectorbt

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
            init_cash=float(initial),
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
        return (
            tuple(portfolio.cash().tolist()),
            tuple(portfolio.assets().tolist()),
            tuple(portfolio.value().tolist()),
        )

    # vectorbt 1.1.0 ``add_nb`` returns exactly zero for a sum within these of zero.
    _SNAP_RELATIVE: ClassVar[Fraction] = Fraction(1, 10**9)
    _SNAP_ABSOLUTE: ClassVar[Fraction] = Fraction(1, 10**12)
    _UNIT: ClassVar[Fraction] = Fraction(1, 2**53)

    @classmethod
    def nav_error_bound(
        cls, initial: Decimal, orders: tuple[VectorbtOrder, ...], terminal: Price
    ) -> float:
        """Bound the engine's terminal NAV error against the exact replay of the same orders.

        The engine converts each exact input to float64 (relative error ``u = 2**-53``),
        computes ``size = target - position``, ``cash -= size * price + fee`` on a
        buy, ``cash += size * price - fee`` on a sell, ``position += size``, and
        finally ``cash + position * terminal``. Each operation rounds once, adding
        ``u`` times its exact result, and errors carried into an operation pass
        through unchanged to first order, except that ``position + size`` returns
        to the target, so the carried position error cancels there. vectorbt's
        ``add_nb`` also snaps a sum within ``max(1e-9 * max(|a|, |b|), 1e-12)`` of
        zero to exactly zero. Where the exact sum, widened by the error already
        carried, could fall in that window, the whole exact sum is added to the
        bound. Orders the engine could ignore as zero-sized add their entire
        effect. The sum is doubled as margin for second-order terms and the final
        conversions.

        Args:
            initial: Exact initial cash.
            orders: Exact delayed long-only target orders in execution order.
            terminal: Exact terminal valuation price.

        Returns:
            A positive absolute bound in quote units.
        """
        unit = cls._UNIT
        cash, position = Fraction(initial), Fraction(0)
        cash_error, position_error = unit * abs(cash), Fraction(0)
        for order in orders:
            target = Fraction(order.target.value)
            price = Fraction(order.effective.value)
            fee = Fraction(order.fee.value)
            delta = target - position
            size_error = position_error + unit * (abs(target) + abs(delta))
            # position + (target - position) re-targets: the carried position error
            # cancels to first order, leaving the target's conversion and rounding.
            retarget_error = unit * (abs(target) + abs(delta) + position_error)
            notional = abs(delta) * price
            notional_error = price * (size_error + 2 * unit * abs(delta))
            if abs(delta) <= cls._SNAP_ABSOLUTE + size_error:
                # The engine may ignore a near-zero order that the exact replay executes.
                cash_error += notional + fee + notional_error
                position_error += abs(delta) + size_error
            elif delta > 0:
                total = notional + fee
                total_error = notional_error + unit * (fee + total)
                cash_error = cls._sum_error(cash, -total, cash_error + total_error)
                cash -= total
                position_error = cls._sum_error(position, delta, retarget_error)
            else:
                proceeds_error = cls._sum_error(notional, -fee, notional_error + unit * fee)
                cash += notional - fee
                cash_error += proceeds_error + unit * abs(cash)
                position_error = cls._sum_error(position, delta, retarget_error)
            position = target
        price = Fraction(terminal.value)
        holding = abs(position) * price
        nav = cash + position * price
        error = (
            cash_error
            + price * position_error
            + 2 * unit * holding
            + unit * (abs(cash) + holding)
            + 2 * unit * abs(nav)
        )
        return float(2 * error) + math.ulp(float(2 * error))

    @classmethod
    def _sum_error(cls, left: Fraction, right: Fraction, carried: Fraction) -> Fraction:
        """Return the error of an ``add_nb`` sum: carried, rounding, and a possible snap."""
        result = abs(left + right)
        window = max(cls._SNAP_RELATIVE * max(abs(left), abs(right)), cls._SNAP_ABSOLUTE)
        snapped = result if result <= window + carried else Fraction(0)
        return carried + cls._UNIT * result + snapped
