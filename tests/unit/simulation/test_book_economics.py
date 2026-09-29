"""Prove exact L2 IOC mechanics, delayed information and complete isolated recovery."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from configuration import BookRun
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.instruments import InstrumentId
from research.observations import BookFeatures
from serialization import DomainCodec
from simulation import BookCheckpoint, BookOrder, BookSimulation
from simulation.book_execution import BookExecution
from strategies import BookImbalance, BookRules


class _Case:
    """Construct authored spot scenarios without inventing original receipt evidence."""

    def __init__(self) -> None:
        """Bind the maintained configuration to a small independently calculated order envelope."""
        original = BookRun.read(Path("configs/backtests/okx-eth-usdt-book.json"))
        instance = original.instances[0]
        self.dimension = instance.quantity.dimension
        self.currency = Currency(code="USDT", minor_unit=Decimal("0.0001"))
        self.instance = replace(
            instance,
            quantity=self.quantity("3"),
            initial_cash=self.money("1000"),
            limits=replace(
                instance.limits,
                maximum=self.quantity("3"),
                lot=self.quantity("0.1"),
                tick=self.price("0.01"),
            ),
            take_fraction=Decimal("1"),
            depth=2,
        )
        self.run = replace(
            original,
            end=original.start + timedelta(seconds=8),
            timing=replace(
                original.timing,
                feed_us=100_000,
                processing_us=100_000,
                entry_us=200_000,
                response_us=500_000,
                stale_us=10_000_000,
            ),
            instances=(self.instance,),
        )

    def quantity(self, value: str) -> Quantity:
        """Bind exact native base units."""
        return Quantity(value=Decimal(value), dimension=self.dimension)

    def money(self, value: str) -> Money:
        """Bind exact quote units."""
        return Money(value=Decimal(value), currency=self.currency)

    def price(self, value: str) -> Price:
        """Bind an exact native price."""
        return Price(value=Decimal(value), currency=self.currency, per=self.dimension)

    def row(
        self,
        position: int,
        milliseconds: int,
        *,
        bid: str = "100",
        bids: tuple[tuple[str, str], ...] | None = None,
        asks: tuple[tuple[str, str], ...] = (("101", "1"), ("102", "1")),
        outcome: str = "update",
        status: str = "degraded",
    ) -> BookObservation:
        """Author one complete L2 boundary with deliberately unknown receipt and sequence."""
        bid_levels = ((bid, "10"),) if bids is None else bids
        return BookObservation(
            position=position,
            epoch=None,
            received_ns=None,
            source_time=str(self.run.history.start_ms + milliseconds),
            sequence=None,
            outcome=outcome,
            status=status,
            reason="fixture; original receipt and sequence unknown",
            state_identity=hashlib.sha256(
                str((position, milliseconds, bid_levels, asks)).encode()
            ).hexdigest(),
            bids=tuple((Decimal(p), Level(Decimal(q), 1)) for p, q in bid_levels),
            asks=tuple((Decimal(p), Level(Decimal(q), 1)) for p, q in asks),
        )

    def order(self, identity: str, quantity: str) -> BookOrder:
        """Create a positive-delay IOC for an independent ledger oracle."""
        return BookOrder(
            identity=identity,
            decision_at=self.run.start,
            sent_at=self.run.start,
            arrival_at=self.run.start + timedelta(seconds=1),
            response_at=self.run.start + timedelta(seconds=2),
            requested=self.quantity(quantity),
            reserved_cash=self.money("1000"),
            source_position=0,
        )

    def simulate(
        self,
        rows: tuple[BookObservation, ...],
        *,
        run: BookRun | None = None,
        checkpoint: BookCheckpoint | None = None,
        stop_ms: int | None = None,
    ) -> BookCheckpoint:
        """Run the actual scheduler over a bounded native fixture."""
        selected = self.run if run is None else run
        return BookSimulation(
            selected, selected.instances[0], BookRules().resolve(selected.instances[0].rule)
        ).execute(
            rows,
            identity="a" * 64,
            checkpoint=checkpoint,
            stop_at=None if stop_ms is None else selected.start + timedelta(milliseconds=stop_ms),
        )


class TestBookExecution:
    """Reconcile price walking, size/cash boundaries, consumption and quote-unit fees."""

    def test_depth_partial_fees_and_sale_reconcile_exactly(self) -> None:
        """Buy two levels, add one, then partially sell and reconcile rational basis and NAV."""
        case = _Case()
        ledger = Ledger(LedgerState(initial_cash=case.money("1000"), dimension=case.dimension))
        execution = BookExecution(case.instance)
        first = execution.execute(case.order("buy", "3"), case.row(0, 0), ledger)
        assert [fill.effective.value for fill in first.fills] == [Decimal("101"), Decimal("102")]
        assert first.status == "partial" and first.canceled == case.quantity("1")
        assert ledger.balance.cash == case.money("796.7970")
        assert ledger.balance.holding == case.quantity("2")
        assert ledger.balance.fees == case.money("0.2030")
        assert ledger.balance.slippage == case.money("1")
        update = case.row(1, 500, asks=(("101", "1"), ("102", "1"), ("103", "1")))
        execution.update(update)
        second = execution.execute(case.order("add", "1"), update, ledger)
        assert [fill.effective.value for fill in second.fills] == [Decimal("103")]
        sell_book = case.row(2, 600, bids=(("110", "1"), ("109", "0.5")), asks=(("111", "100"),))
        execution.update(sell_book)
        sold = execution.execute(case.order("sell", "-3"), sell_book, ledger)
        assert sold.status == "partial" and sold.canceled == case.quantity("1.5")
        assert ledger.balance.cash == case.money("858.0295")
        assert ledger.balance.holding == case.quantity("1.5")
        assert ledger.balance.basis.value == Fraction(153)
        assert ledger.balance.realized.value == Fraction("11.5")
        assert ledger.balance.fees == case.money("0.4705")
        mark = ledger.mark(case.price("110"))
        assert mark.nav == case.money("1023.0295")
        assert mark.net == case.money("23.0295")
        assert mark.unrealized.value == Fraction(12)
        assert mark.gross.value - Fraction(ledger.balance.slippage.value) - Fraction(
            ledger.balance.fees.value
        ) == Fraction(mark.net.value)

    def test_same_levels_never_replenish_on_snapshots_or_size_decreases(self) -> None:
        """Retain consumption through same-price updates, clearing it only on removal."""
        case = _Case()
        ledger = Ledger(LedgerState(initial_cash=case.money("1000"), dimension=case.dimension))
        execution = BookExecution(case.instance)
        original = case.row(0, 0, asks=(("101", "1"),))
        execution.execute(case.order("first", "1"), original, ledger)
        for i, size in enumerate(("1", "0.5", "1"), 1):
            row = case.row(i, i, asks=(("101", size),), outcome="snapshot")
            execution.update(row)
            order = execution.execute(case.order(f"repeat-{i}", "1"), row, ledger)
            assert order.status == "canceled" and not order.fills
        increased = case.row(4, 4, asks=(("101", "1.5"),))
        execution.update(increased)
        partial = execution.execute(case.order("increase", "1"), increased, ledger)
        assert partial.fills[0].quantity == case.quantity("0.5")
        absent = case.row(5, 5, asks=(("102", "1"),))
        execution.update(absent)
        execution.update(original)
        restored = execution.execute(case.order("reappear", "1"), original, ledger)
        assert restored.status == "filled"

    def test_cash_and_participation_cap_partial_size_on_lot_grid(self) -> None:
        """Affordable quantities include taker fees and cannot borrow or take unlimited depth."""
        case = _Case()
        instance = replace(case.instance, take_fraction=Decimal("0.5"))
        ledger = Ledger(LedgerState(initial_cash=case.money("45"), dimension=case.dimension))
        order = BookExecution(instance).execute(
            case.order("small-cash", "3"), case.row(0, 0), ledger
        )
        assert order.fills[0].quantity == case.quantity("0.4")
        assert order.canceled == case.quantity("2.6")
        assert ledger.balance.cash == case.money("4.5596")
        assert order.reason == "insufficient_cash_or_risk_limit"
        funded = Ledger(LedgerState(initial_cash=case.money("1000"), dimension=case.dimension))
        capped = BookExecution(instance).execute(case.order("cap", "3"), case.row(0, 0), funded)
        assert [fill.quantity.value for fill in capped.fills] == [Decimal("0.5"), Decimal("0.5")]

    def test_decimal_context_does_not_change_accounting(self) -> None:
        """The same depth execution is exact even under a hostile ambient decimal context."""
        case = _Case()
        expected = case.simulate((case.row(0, 0),))
        with localcontext() as context:
            context.prec = 3
            observed = case.simulate((case.row(0, 0),))
        assert observed == expected


class TestBookTiming:
    """Exercise exchange/knowledge separation, ties, staleness and alternate scenarios."""

    def test_feed_delays_do_not_delay_exchange_arrival_book(self) -> None:
        """Execute unseen exchange updates without exposing them to earlier decisions."""
        case = _Case()
        run = replace(case.run, timing=replace(case.run.timing, feed_us=500_000))
        rows = (case.row(0, 0), case.row(1, 900, asks=(("105", "1"), ("106", "1"))))
        result = case.simulate(rows, run=run)
        assert result.state.decisions[0].source_position == 0
        assert result.state.decisions[0].delivered_at == run.start + timedelta(milliseconds=500)
        assert result.state.orders[0].fills[0].effective == case.price("105")
        assert result.state.orders[0].arrival_at == run.start + timedelta(milliseconds=1300)
        assert result.state.local is not None and result.state.local.received_ns is None
        assert result.state.local.sequence is None

    def test_future_changes_cannot_change_prior_decisions_or_fills(self) -> None:
        """Perturb later prices and verify the already completed causal prefix byte for byte."""
        case = _Case()
        original = (case.row(0, 0), case.row(1, 2500))
        changed = (original[0], case.row(1, 2500, bid="90", asks=(("91", "100"),)))
        left = case.simulate(original)
        right = case.simulate(changed)
        assert left.state.decisions[:2] == right.state.decisions[:2]
        assert left.state.orders[:2] == right.state.orders[:2]
        slower = replace(case.run, timing=replace(case.run.timing, feed_us=1_100_000))
        delayed = case.simulate(original, run=slower)
        assert delayed.state.decisions[0].reason == "missing_book"
        assert delayed.state.orders[0].decision_at == slower.start + timedelta(seconds=2)

    def test_source_ties_precede_arrival_and_response_precedes_decision(self) -> None:
        """Use the last raw source boundary at arrival and block until the modeled response."""
        case = _Case()
        run = replace(case.run, timing=replace(case.run.timing, response_us=1_700_000))
        rows = (
            case.row(0, 0),
            case.row(1, 1300, asks=(("104", "1"),)),
            case.row(2, 1300, asks=(("105", "1"),)),
        )
        result = case.simulate(rows, run=run)
        assert result.state.orders[0].fills[0].effective == case.price("105")
        assert result.state.decisions[1].reason == "pending_intent"
        assert result.state.decisions[1].known_holding == case.quantity("0")
        assert result.state.decisions[2].known_holding == case.quantity("1")
        assert result.state.decisions[2].reason == "submitted"

    def test_stale_invalid_and_terminal_missingness_are_explicit(self) -> None:
        """Cancel invalid arrivals and refuse stale terminal marks on open holdings."""
        case = _Case()
        rows = (case.row(0, 0), case.row(1, 1200, status="unavailable", outcome="invalid_frame"))
        invalid = case.simulate(rows)
        assert invalid.state.orders[0].reason == "invalid_book"
        assert not invalid.state.ledger.fills
        assert invalid.state.decisions[1].reason == "invalid_book"
        assert invalid.state.valuations[-1].reason == "invalid_book"
        stale = replace(case.run, timing=replace(case.run.timing, stale_us=500_000))
        flat = case.simulate((case.row(0, 0),), run=stale)
        assert all(d.reason == "stale_book" for d in flat.state.decisions)
        with pytest.raises(ValueError, match="terminal valuation unavailable"):
            case.simulate(
                (case.row(0, 0),),
                run=replace(case.run, timing=replace(case.run.timing, stale_us=2_000_000)),
            )
        crossed = case.simulate((case.row(0, 0, bid="101"),))
        assert crossed.state.decisions[0].reason == "crossed_book"
        with pytest.raises(ValueError, match="regression"):
            case.simulate((case.row(0, 10), case.row(1, 0)))


class TestBookRecoveryAndConfiguration:
    """Prove complete restart state, another spot configuration and independent accounts."""

    @pytest.mark.parametrize("stop_ms", [1000, 1200, 1300, 1500, 1800, 2700, 8000])
    def test_restart_matches_uninterrupted_bytes(self, stop_ms: int) -> None:
        """Resume pending orders, unseen source updates, responses and consumed size exactly."""
        case = _Case()
        rows = (case.row(0, 0), case.row(1, 1250), case.row(2, 2500))
        whole = case.simulate(rows)
        partial = case.simulate(rows, stop_ms=stop_ms)
        codec = DomainCodec()
        restored = codec.decode_json(codec.encode_json(partial), BookCheckpoint)
        assert codec.encode_json(case.simulate(rows, checkpoint=restored)) == codec.encode_json(
            whole
        )
        if stop_ms == 1300:
            assert restored.state.pending is not None and restored.state.consumed
            assert restored.state.deliveries and restored.state.known_holding == case.quantity("0")

    def test_checkpoint_rejects_schema_corruption_identity_and_source_changes(self) -> None:
        """A valid cursor cannot substitute for bound source and complete checkpoint state."""
        case = _Case()
        rows = (case.row(0, 0),)
        partial = case.simulate(rows, stop_ms=1500)
        with pytest.raises(ValueError, match="unsupported book checkpoint"):
            replace(partial, schema_version="l2-ioc-checkpoint-unsupported")
        with pytest.raises(ValueError, match="digest mismatch"):
            replace(partial, state_sha256="0" * 64)
        with pytest.raises(ValueError, match="identity"):
            case.simulate(rows, checkpoint=replace(partial, identity="b" * 64))
        with pytest.raises(ValueError, match="source prefix changed"):
            case.simulate((case.row(0, 0, bid="99"),), checkpoint=partial)

    def test_second_spot_and_isolated_instances(self) -> None:
        """Onboard another spot configuration and keep account state independent."""
        case = _Case()
        other_dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
            kind=QuantityKind.BASE_UNIT,
        )
        other_currency = Currency(code="USD", minor_unit=Decimal("0.01"))
        quantity = Quantity(value=Decimal("3"), dimension=other_dimension)
        instance = replace(
            case.instance,
            instance="other-spot",
            quantity=quantity,
            initial_cash=Money(value=Decimal("1000"), currency=other_currency),
            limits=replace(
                case.instance.limits,
                maximum=quantity,
                lot=Quantity(value=Decimal("0.1"), dimension=other_dimension),
                tick=Price(value=Decimal("0.01"), per=other_dimension, currency=other_currency),
            ),
        )
        history = replace(
            case.run.history,
            symbol="BTC-USD",
            base_currency="BTC",
            quote_currency="USD",
            instrument_id=other_dimension.instrument_id,
        )
        second = replace(case.run, history=history, instances=(instance,))
        result = case.simulate((case.row(0, 0),), run=second)
        assert result.state.valuations[-1].balance.cash.value == Decimal("796.80")
        assert result.state.ledger.dimension == other_dimension
        control = replace(case.instance, instance="control", rule="book-no-trade")
        smaller = replace(case.instance, instance="smaller", quantity=case.quantity("0.5"))
        selected = replace(case.run, instances=(case.instance, control, smaller))
        results = tuple(
            BookSimulation(selected, item, BookRules().resolve(item.rule)).execute(
                (case.row(0, 0),), identity="a" * 64
            )
            for item in selected.instances
        )
        assert [r.state.valuations[-1].balance.holding.value for r in results] == [
            Decimal("2"),
            Decimal("0"),
            Decimal("0.5"),
        ]
        assert results[1].state.valuations[-1].mark is not None
        assert results[1].state.valuations[-1].mark.net.value == 0
        assert results[1].state.consumed == ()
        assert results[0].state.orders[0].identity != results[2].state.orders[0].identity

    def test_configuration_rejects_unsupported_product_grids_and_rules(self) -> None:
        """Fail unsupported mechanics and invalid configured selections before replay."""
        case = _Case()
        with pytest.raises(ValueError, match="spot limits"):
            replace(case.instance.limits, product="perpetual")
        with pytest.raises(ValueError, match="invalid book"):
            replace(case.instance, quantity=case.quantity("3.01"))
        with pytest.raises(ValueError, match="duplicate"):
            replace(case.run, instances=(case.instance, case.instance))
        with pytest.raises(ValueError, match="unsupported book rule"):
            BookRules().resolve("maker")
        with pytest.raises(ValueError, match="timing"):
            replace(case.run.timing, entry_us=0)
        feature = BookFeatures.inspect(case.row(0, 0), 2)
        assert BookImbalance().target(feature, case.quantity("3"), Decimal("0.2")) == case.quantity(
            "3"
        )
