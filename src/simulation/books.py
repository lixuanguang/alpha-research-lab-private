"""Schedule separate exchange and strategy books for bounded offline IOC economics."""

from __future__ import annotations

# standard library imports
import hashlib
from collections import deque
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from configuration import BookInstance, BookRun
from financial_units import Money, Price, Quantity
from market_data.contracts import BookObservation
from research.observations import BookFeatures
from serialization import DomainCodec
from simulation.book_execution import BookExecution
from simulation.book_state import BookCheckpoint, BookDecision, BookOrder, BookState, BookValuation
from strategies import BookRule


class BookSimulation:
    """Advance source, feed, arrival, response, decision and valuation phases in that order."""

    def __init__(self, run: BookRun, instance: BookInstance, rule: BookRule) -> None:
        """Bind an immutable scenario and one fresh, stateless book rule.

        Args:
            run: Complete scenario with explicit clocks and bounded source/window selection.
            instance: One selected independent account and rule definition.
            rule: Explicit strategy collaborator; receives only delivered features.

        Raises:
            ValueError: The instance is absent from the run.
        """
        run.__post_init__()
        if instance not in run.instances:
            raise ValueError("book instance is not selected")
        self.run = run
        self.instance = instance
        self.rule = rule
        self.codec = DomainCodec()

    def execute(
        self,
        rows: Iterable[BookObservation],
        *,
        identity: str,
        checkpoint: BookCheckpoint | None = None,
        stop_at: datetime | None = None,
    ) -> BookCheckpoint:
        """Run or resume through a complete clock boundary, with bounded in-flight book state.

        Args:
            rows: Verified native observations in original order, including the restart prefix.
            identity: Immutable source/configuration/implementation fingerprint for this instance.
            checkpoint: Complete prior state, never just a source cursor.
            stop_at: Inclusive UTC interruption boundary; retains pending orders.

        Returns:
            Exact checkpoint, including final reconciled valuation when terminal is reached.

        Raises:
            ValueError: Input clocks, source identity, restart state or terminal marking is invalid.
        """
        identity = hashlib.sha256(
            self.codec.encode_json((identity, self.run.identity, self.instance.instance))
        ).hexdigest()
        terminal = self.run.end if stop_at is None else stop_at
        BookCheckpoint._require_utc(terminal, field_name="stop_at")
        if not self.run.start <= terminal <= self.run.end:
            raise ValueError("book stop outside configured window")
        initial = LedgerState(
            initial_cash=self.instance.initial_cash, dimension=self.instance.quantity.dimension
        )
        if checkpoint is not None:
            checkpoint.__post_init__()
            if checkpoint.identity != identity or terminal < checkpoint.state.clock:
                raise ValueError("book checkpoint identity or stop clock mismatch")
            state = checkpoint.state
        else:
            state = BookState(
                clock=self.run.start,
                input_count=0,
                input_digest="0" * 64,
                exchange=None,
                local=None,
                deliveries=(),
                consumed=(),
                next_decision=self.run.start + timedelta(microseconds=self.run.timing.cadence_us),
                pending=None,
                known_holding=Quantity(value=Decimal(0), dimension=initial.dimension),
                ledger=initial,
                orders=(),
                decisions=(),
                valuations=(),
            )
        if (
            state.ledger.initial_cash != initial.initial_cash
            or state.ledger.dimension != initial.dimension
        ):
            raise ValueError("checkpoint account differs from configured instance")
        ledger = Ledger(state.ledger)
        execution = BookExecution(self.instance, state.consumed)
        rows_iter = iter(rows)
        previous_at: datetime | None = None
        digest = "0" * 64
        last: BookObservation | None = None
        for position in range(state.input_count):
            last = next(rows_iter, None)
            if last is None:
                raise ValueError("checkpoint source prefix is missing")
            previous_at = self._validate_row(last, position, previous_at)
            digest = self._digest(digest, last)
        if digest != state.input_digest or last != state.exchange:
            raise ValueError("checkpoint source prefix changed")
        exchange, local = state.exchange, state.local
        deliveries = deque(state.deliveries)
        orders, decisions, valuations = (
            list(state.orders),
            list(state.decisions),
            list(state.valuations),
        )
        pending, known_holding = state.pending, state.known_holding
        next_decision, count = state.next_decision, state.input_count
        next_row = next(rows_iter, None)
        next_source = None if next_row is None else self._validate_row(next_row, count, previous_at)
        clock = state.clock
        while clock < terminal or (next_source is not None and next_source == clock):
            clocks = [terminal, next_decision]
            if next_source is not None:
                clocks.append(next_source)
            if deliveries:
                clocks.append(self._delivery_at(deliveries[0]))
            if pending is not None:
                order = orders[pending]
                clocks.append(order.arrival_at if order.status == "pending" else order.response_at)
            at = min(clocks)
            if at < clock:
                raise ValueError("book scheduler regressed")
            clock = at
            while next_row is not None and next_source == at:
                exchange = next_row
                execution.update(exchange)
                deliveries.append(exchange)
                digest = self._digest(digest, exchange)
                count += 1
                previous_at = next_source
                next_row = next(rows_iter, None)
                next_source = (
                    None if next_row is None else self._validate_row(next_row, count, previous_at)
                )
            while deliveries and self._delivery_at(deliveries[0]) <= at:
                local = deliveries.popleft()
            if pending is not None:
                order = orders[pending]
                if order.status == "pending" and order.arrival_at == at:
                    reason = self._book_reason(exchange, at)
                    if reason is not None or exchange is None:
                        orders[pending] = self._cancel(order, reason or "missing_book")
                    else:
                        orders[pending] = execution.execute(order, exchange, ledger)
                order = orders[pending]
                if order.status != "pending" and order.response_at <= at:
                    known_holding = ledger.balance.holding
                    pending = None
            if at == next_decision:
                if at < self.run.end:
                    decision, submitted = self._decide(
                        local, at, ledger, known_holding, pending is not None, len(orders)
                    )
                    decisions.append(decision)
                    if submitted is not None:
                        pending = len(orders)
                        orders.append(submitted)
                next_decision += timedelta(microseconds=self.run.timing.cadence_us)
            if at == self.run.end and pending is not None and orders[pending].status == "pending":
                orders[pending] = self._cancel(orders[pending], "terminal_cancellation")
                pending = None
            if at == self.run.end or (decisions and decisions[-1].at == at):
                valuation = self._mark(exchange, at, ledger)
                valuations.append(valuation)
                if at == self.run.end and valuation.mark is None:
                    raise ValueError(f"terminal valuation unavailable: {valuation.reason}")
            if at == terminal:
                break
        result = BookState(
            clock=clock,
            input_count=count,
            input_digest=digest,
            exchange=exchange,
            local=local,
            deliveries=tuple(deliveries),
            consumed=execution.consumed,
            next_decision=next_decision,
            pending=pending,
            known_holding=known_holding,
            ledger=ledger.state,
            orders=tuple(orders),
            decisions=tuple(decisions),
            valuations=tuple(valuations),
        )
        return BookCheckpoint.create(identity, result)

    def _validate_row(
        self, row: BookObservation, position: int, previous: datetime | None
    ) -> datetime:
        """Require unchanged native L2 boundaries and ordered source milliseconds."""
        row.__post_init__()
        at = BookFeatures.source_at(row)
        if (
            row.position != position
            or row.orders
            or at < self.run.start
            or (previous is not None and at < previous)
        ):
            raise ValueError("unsupported L2 position, representation or source-clock regression")
        return at

    def _digest(self, previous: str, row: BookObservation) -> str:
        """Chain original observations without replacing their unknown receipt/sequence fields."""
        return hashlib.sha256(bytes.fromhex(previous) + self.codec.encode_json(row)).hexdigest()

    def _delivery_at(self, row: BookObservation) -> datetime:
        """Assign scenario delivery without mutating original receipt evidence."""
        return BookFeatures.source_at(row) + timedelta(microseconds=self.run.timing.feed_us)

    def _book_reason(self, row: BookObservation | None, at: datetime) -> str | None:
        """Apply stale/invalid and tick checks consistently to decision and execution states."""
        reason = BookFeatures.reason(row, at, self.run.timing.stale_us)
        if reason is not None or row is None:
            return reason
        tick = self.instance.limits.tick
        for price, _ in row.bids + row.asks:
            if (
                self.instance.limits.price_reason(
                    Price(value=price, currency=tick.currency, per=tick.per)
                )
                is not None
            ):
                return "off_tick_book"
        return None

    def _decide(
        self,
        row: BookObservation | None,
        at: datetime,
        ledger: Ledger,
        known_holding: Quantity,
        pending: bool,
        order_count: int,
    ) -> tuple[BookDecision, BookOrder | None]:
        """Issue at most one reserved target delta from the delivered information set."""
        reason = self._book_reason(row, at)
        target: Quantity | None = None
        order: BookOrder | None = None
        if reason is None and row is not None:
            feature = BookFeatures.inspect(row, self.instance.depth)
            target = self.rule.target(
                feature, self.instance.quantity, self.instance.imbalance_threshold
            )
            reason = self.instance.limits.target_reason(
                target, ledger.balance.holding, pending=pending
            )
            if reason is None:
                delta = target - ledger.balance.holding
                if delta.value == 0:
                    reason = "target_unchanged"
                else:
                    tick = self.instance.limits.tick
                    price = (
                        min(price for price, _ in row.asks)
                        if delta.value > 0
                        else max(price for price, _ in row.bids)
                    )
                    reference = Price(value=price, currency=tick.currency, per=tick.per)
                    arrival = at + timedelta(
                        microseconds=self.run.timing.processing_us + self.run.timing.entry_us
                    )
                    estimate = BookExecution(self.instance).costs.fill(
                        "reservation",
                        decision_at=at,
                        filled_at=arrival,
                        quantity=delta,
                        reference=reference,
                    )
                    reserved = (
                        reference.amount(delta) + estimate.fee
                        if delta.value > 0
                        else Money(value=Decimal(0), currency=tick.currency)
                    )
                    # Reserve available cash; actual IOC affordability is rechecked.
                    if reserved.value > ledger.balance.cash.value:
                        reserved = ledger.balance.cash
                    order = BookOrder(
                        identity=f"{self.instance.instance}:{order_count}",
                        decision_at=at,
                        sent_at=at + timedelta(microseconds=self.run.timing.processing_us),
                        arrival_at=arrival,
                        response_at=arrival + timedelta(microseconds=self.run.timing.response_us),
                        requested=delta,
                        reserved_cash=reserved,
                        source_position=row.position,
                    )
                    reason = "submitted"
        return BookDecision(
            at=at,
            source_position=None if row is None else row.position,
            delivered_at=None if row is None else self._delivery_at(row),
            known_holding=known_holding,
            target=target,
            reason=reason or "missing_book",
        ), order

    @staticmethod
    def _cancel(order: BookOrder, reason: str) -> BookOrder:
        """Cancel all unfilled IOC quantity without creating a fill or posting."""
        return replace(
            order,
            status="canceled",
            reason=reason,
            canceled=Quantity(
                value=order.requested.value.copy_abs(), dimension=order.requested.dimension
            ),
        )

    def _mark(self, row: BookObservation | None, at: datetime, ledger: Ledger) -> BookValuation:
        """Value long inventory at fresh exchange best bid without assuming liquidation depth."""
        reason = self._book_reason(row, at)
        price: Price | None = None
        if reason is None and row is not None:
            tick = self.instance.limits.tick
            price = Price(value=max(p for p, _ in row.bids), currency=tick.currency, per=tick.per)
        mark = (
            ledger.mark(price) if price is not None or ledger.balance.holding.value == 0 else None
        )
        return BookValuation(
            at=at, balance=ledger.balance, mark=mark, reason=reason or "best_bid_mark"
        )
