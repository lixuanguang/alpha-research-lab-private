"""Exercise exact offline intent economics and declared L2 lifecycle assumptions."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory, VenueSpecification
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from serialization import DomainCodec
from simulation import (
    IntentMarket,
    IntentSimulation,
    IntentSimulationResult,
    IntentSimulationSpec,
    IntentTrade,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)
from strategies import DecisionRecord, ExposureIntent, OrderIntent, QuoteIntent, TargetIntent


class _Case:
    """Build one spot account and deterministic source facts with exact hand values."""

    def __init__(
        self,
        *,
        queue_ahead: str = "1",
        entry_delay_us: int = 1_000_000,
        cancel_delay_us: int = 0,
    ) -> None:
        """Bind explicit model versions and a ten-second independent sample."""
        self.start = datetime(2026, 9, 23, tzinfo=UTC)
        self.entity = "4476df8e-6342-4417-839e-e41b88f41446"
        self.dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(self.entity),
            kind=QuantityKind.BASE_UNIT,
        )
        self.currency = Currency(code="USDT", minor_unit=Decimal("0.01"))
        self.limits = SpotLimits(
            maximum=self.quantity("10"),
            lot=self.quantity("1"),
            tick=self.price("0.01"),
            product="spot",
            specification_identity="a" * 64,
            minimum_order=self.quantity("1"),
        )
        maker = SpotCosts(adverse=self.price("0"), fee_rate=Decimal("0.001"), rounding="half_even")
        taker = SpotCosts(adverse=self.price("0"), fee_rate=Decimal("0.002"), rounding="half_even")
        self.costs = SpotFeeModel(maker=maker, taker=taker)
        self.execution = LimitOrderExecution(
            LimitExecutionConfig(
                entry_delay_us=entry_delay_us,
                cancel_delay_us=cancel_delay_us,
                lifetime_us=6_000_000,
                max_book_age_us=20_000_000,
                take_fraction=Decimal("1"),
                queue_ahead_fraction=Decimal(queue_ahead),
            )
        )
        self.spec = IntentSimulationSpec(
            instance="alpha",
            entity=self.entity,
            source_identity="saved-fixture",
            start=self.start,
            end=self.at(10),
            initial_cash=self.money("1000"),
            limits=self.limits,
            execution_identity=self.execution.identity,
            cost_identity=self.costs.identity,
        )

    def at(self, seconds: int) -> datetime:
        """Return one explicitly UTC event or decision time."""
        return self.start + timedelta(seconds=seconds)

    def quantity(self, value: str) -> Quantity:
        """Bind native base units."""
        return Quantity(value=Decimal(value), dimension=self.dimension)

    def money(self, value: str) -> Money:
        """Bind exact quote money."""
        return Money(value=Decimal(value), currency=self.currency)

    def price(self, value: str) -> Price:
        """Bind exact quote per base unit."""
        return Price(value=Decimal(value), currency=self.currency, per=self.dimension)

    def decision(
        self, at: int, intent: TargetIntent | ExposureIntent | OrderIntent | QuoteIntent | None
    ) -> DecisionRecord:
        """Retain a typed MR02 output without inventing an executable client ID."""
        return DecisionRecord(
            instance="alpha",
            entity=self.entity,
            at=self.at(at),
            policy="fixture-policy",
            feature_identity="fixture-feature",
            model_identity=None,
            intent=intent,
        )

    def book(
        self,
        at: int,
        *,
        bid: str = "99",
        ask: str = "101",
        bid_size: str = "2",
        ask_size: str = "2",
        known: int | None = None,
    ) -> IntentMarket:
        """Wrap canonical L2 state with distinct source and knowledge clocks."""
        row = BookObservation(
            position=at,
            epoch=None,
            received_ns=None,
            source_time=str(int(self.at(at).timestamp() * 1000)),
            sequence=None,
            outcome="snapshot",
            status="degraded",
            reason="bounded synthetic L2 fixture",
            state_identity=hashlib.sha256(f"{at}:{bid}:{ask}".encode()).hexdigest(),
            bids=((Decimal(bid), Level(Decimal(bid_size), 1)),),
            asks=((Decimal(ask), Level(Decimal(ask_size), 1)),),
        )
        return IntentMarket(
            identity=f"book:{at}:{bid}:{ask}",
            source_identity=self.spec.source_identity,
            instrument=self.entity,
            channel="l2",
            source_at=self.at(at),
            known_at=self.at(at if known is None else known),
            book=row,
        )

    def trade(self, at: int, *, price: str, quantity: str, aggressor: str) -> IntentMarket:
        """Declare a source trade independently from any matching L2 depth update."""
        if aggressor not in ("buy", "sell"):
            raise ValueError("invalid test aggressor")
        return IntentMarket(
            identity=f"trade:{at}:{price}:{quantity}:{aggressor}",
            source_identity=self.spec.source_identity,
            instrument=self.entity,
            channel="l2",
            source_at=self.at(at),
            known_at=self.at(at),
            book=None,
            trades=(
                IntentTrade(
                    price=self.price(price),
                    quantity=self.quantity(quantity),
                    aggressor="buy" if aggressor == "buy" else "sell",
                ),
            ),
        )

    def run(
        self, decisions: tuple[DecisionRecord, ...], market: tuple[IntentMarket, ...]
    ) -> IntentSimulationResult:
        """Start a fresh injected ledger and execute one bounded sample."""
        ledger = Ledger(LedgerState(initial_cash=self.spec.initial_cash, dimension=self.dimension))
        return IntentSimulation(self.spec, self.execution, self.costs, ledger).run(
            decisions, market
        )

    def reference_history(self) -> ReferenceHistory:
        """Retain a valid-time grid change learned two seconds after it takes effect."""
        definition = InstrumentDefinition(
            instrument_id=self.dimension.instrument_id,
            venue="fixture",
            symbol="BASE-USDT",
            product="spot",
            base_currency="BASE",
            quote_currency="USDT",
            calendar="24-7",
        )
        first = VenueSpecification(
            instrument=definition,
            valid_from=self.at(0),
            valid_to=self.at(5),
            ts_knowledge=self.at(0),
            source_digest="1" * 64,
            basis="source_history",
            price_tick=Decimal("0.01"),
            quantity_step=Decimal("1"),
            minimum_quantity=Decimal("1"),
            status="live",
        )
        second = VenueSpecification(
            instrument=definition,
            valid_from=self.at(5),
            valid_to=None,
            ts_knowledge=self.at(7),
            source_digest="2" * 64,
            basis="source_history",
            price_tick=Decimal("0.01"),
            quantity_step=Decimal("2"),
            minimum_quantity=Decimal("2"),
            status="live",
        )
        return ReferenceHistory(specifications=(first, second))


class TestIntentSimulation:
    """Prove exact economics and explicit model limitations."""

    def test_target_loss_reconciles_exact_fees_and_terminal_bid(self) -> None:
        """A delayed buy at 101 marked at 99 loses exactly spread plus taker fee."""
        case = _Case()
        result = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),),
            (case.book(1), case.book(10)),
        )
        assert result.ledger.fills[0].filled_at == case.at(3)
        assert result.ledger.fills[0].effective == case.price("101")
        assert result.ledger.fills[0].fee == case.money("0.20")
        assert result.ledger.fills[0].quantity == case.quantity("1")
        assert result.mark is not None and result.net_return is not None
        assert result.mark.nav == case.money("997.80")
        assert result.mark.net == case.money("-2.20")
        assert Fraction(
            int(result.net_return.numerator), int(result.net_return.denominator)
        ) == Fraction(-11, 5000)
        assert result.orders[0].status == "filled"
        assert (
            DomainCodec().decode_json(DomainCodec().encode_json(result), IntentSimulationResult)
            == result
        )

    def test_no_trade_keeps_capital_and_rejects_future_source_or_knowledge(self) -> None:
        """A flat target has no fill; unavailable future books cannot price earlier arrival."""
        case = _Case()
        flat = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("0"))),),
            (case.book(1), case.book(10)),
        )
        assert flat.ledger.fills == ()
        assert flat.mark is not None
        assert flat.mark.nav == case.money("1000")
        assert flat.decisions[0].reason == "no_change"
        future_source = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),),
            (case.book(5, known=1), case.book(10)),
        )
        assert future_source.ledger.fills == ()
        assert future_source.decisions[0].reason == "no_fresh_book_at_arrival"
        future_knowledge = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),),
            (case.book(1, known=5), case.book(10)),
        )
        assert future_knowledge.ledger.fills == ()

    def test_exposure_resolves_at_then_known_midpoint_with_exact_lots(self) -> None:
        """Currency exposure becomes an absolute long target at arrival-time midpoint."""
        case = _Case()
        result = case.run(
            (case.decision(2, ExposureIntent(exposure=case.money("200"))),),
            (case.book(1), case.book(10)),
        )
        assert result.ledger.fills[0].quantity == case.quantity("2")
        assert result.ledger.fills[0].filled_at == case.at(3)
        assert result.mark is not None
        assert result.mark.net == case.money("-4.40")

    def test_idle_decisions_pay_entry_latency_without_cancel_latency(self) -> None:
        """First and post-fill decisions have no outstanding work to cancel."""
        case = _Case(cancel_delay_us=8_000_000)
        target = TargetIntent(quantity=case.quantity("1"))
        bid = OrderIntent(
            side="buy",
            quantity=case.quantity("1"),
            limit=case.price("99"),
            time_in_force="post-only",
        )
        result = case.run(
            (case.decision(2, target), case.decision(4, bid)),
            (case.book(1), case.book(10)),
        )
        assert tuple(order.placed_at for order in result.orders) == (case.at(3), case.at(5))
        assert result.ledger.fills[0].filled_at == case.at(3)
        assert result.orders[1].reason == "sample_end"

    def test_resting_replacement_waits_for_cancel_then_entry_latency(self) -> None:
        """A resting order closes after cancel latency before its replacement arrives."""
        case = _Case(cancel_delay_us=2_000_000)
        first = OrderIntent(
            side="buy",
            quantity=case.quantity("1"),
            limit=case.price("99"),
            time_in_force="post-only",
        )
        second = replace(first, limit=case.price("98"))
        result = case.run(
            (case.decision(2, first), case.decision(4, second)),
            (case.book(1), case.book(10)),
        )
        assert result.orders[0].placed_at == case.at(3)
        assert result.orders[0].closed_at == case.at(6)
        assert result.orders[0].reason == "replaced"
        assert result.orders[1].placed_at == case.at(7)

    def test_abstention_cancels_the_resting_plan_and_places_nothing(self) -> None:
        """An abstaining decision replaces the plan with none, after cancel latency."""
        case = _Case(cancel_delay_us=2_000_000)
        first = OrderIntent(
            side="buy",
            quantity=case.quantity("1"),
            limit=case.price("99"),
            time_in_force="post-only",
        )
        result = case.run(
            (case.decision(2, first), case.decision(4, None)),
            (case.book(1), case.book(10)),
        )
        assert len(result.orders) == 1
        assert result.orders[0].closed_at == case.at(6)
        assert result.orders[0].reason == "replaced"
        assert result.decisions[1].reason == "abstained"
        assert result.decisions[1].order_identities == ()

    def test_in_flight_replacement_keeps_cancel_before_arrival_priority(self) -> None:
        """Cancellation at an older plan's arrival prevents that plan from submitting."""
        case = _Case(entry_delay_us=3_000_000, cancel_delay_us=2_000_000)
        first = OrderIntent(
            side="buy",
            quantity=case.quantity("1"),
            limit=case.price("99"),
            time_in_force="post-only",
        )
        second = replace(first, limit=case.price("98"))
        result = case.run(
            (case.decision(2, first), case.decision(3, second)),
            (case.book(1), case.book(10)),
        )
        assert result.decisions[0].reason == "replaced_before_arrival"
        assert len(result.orders) == 1
        assert result.orders[0].requested == second
        assert result.orders[0].placed_at == case.at(8)

    def test_passive_queue_sensitivity_and_replacement(self) -> None:
        """Only future same-price sell trades deplete a bid queue; replacement cancels it."""
        conservative = _Case(queue_ahead="1")
        bid = OrderIntent(
            side="buy",
            quantity=conservative.quantity("1"),
            limit=conservative.price("99"),
            time_in_force="post-only",
        )
        inputs = (
            conservative.book(1),
            conservative.trade(4, price="99", quantity="1", aggressor="sell"),
            conservative.trade(5, price="99", quantity="2", aggressor="sell"),
            conservative.book(10, bid="98", ask="100"),
        )
        result = conservative.run((conservative.decision(2, bid),), inputs)
        assert result.orders[0].queue_ahead == conservative.quantity("2")
        assert result.ledger.fills[0].filled_at == conservative.at(5)
        assert result.ledger.fills[0].fee == conservative.money("0.10")
        assert result.mark is not None
        assert result.mark.net == conservative.money("-1.10")

        optimistic = _Case(queue_ahead="0")
        optimistic_result = optimistic.run((optimistic.decision(2, bid),), inputs)
        assert optimistic_result.ledger.fills[0].filled_at == optimistic.at(4)
        assert optimistic_result.spec.execution_identity != result.spec.execution_identity

        replaced = conservative.run(
            (
                conservative.decision(2, bid),
                conservative.decision(4, TargetIntent(quantity=conservative.quantity("0"))),
            ),
            inputs,
        )
        assert replaced.ledger.fills == ()
        assert replaced.orders[0].reason == "replaced"
        assert replaced.orders[0].canceled == conservative.quantity("1")

    def test_ioc_partial_and_post_only_crossing_are_explicit(self) -> None:
        """Displayed capacity bounds IOC fills and a crossing post-only quote is rejected."""
        case = _Case()
        ioc = OrderIntent(
            side="buy", quantity=case.quantity("2"), limit=case.price("101"), time_in_force="ioc"
        )
        partial = case.run(
            (case.decision(2, ioc),),
            (case.book(1, ask_size="1"), case.book(10)),
        )
        assert partial.orders[0].status == "partial"
        assert partial.orders[0].canceled == case.quantity("1")
        assert partial.ledger.fills[0].quantity == case.quantity("1")
        quote = QuoteIntent(
            bid=OrderIntent(
                side="buy",
                quantity=case.quantity("1"),
                limit=case.price("102"),
                time_in_force="post-only",
            ),
            ask=OrderIntent(
                side="sell",
                quantity=case.quantity("1"),
                limit=case.price("103"),
                time_in_force="post-only",
            ),
        )
        quoted = case.run((case.decision(2, quote),), (case.book(1), case.book(10)))
        assert {order.reason for order in quoted.orders} == {
            "post_only_crossing",
            "insufficient_holding",
        }
        assert quoted.ledger.fills == ()

    def test_open_holding_without_a_fresh_terminal_bid_is_unvalued(self) -> None:
        """A gap before the end leaves the holding unvalued, never marked at a stale bid."""
        case = _Case()
        gap = case.book(5)
        assert gap.book is not None
        gap = replace(
            gap,
            identity="gap:5",
            book=replace(
                gap.book, outcome="gap", status="recovering", reason="disconnect", bids=(), asks=()
            ),
        )
        result = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),), (case.book(1), gap)
        )
        assert result.ledger.fills[0].quantity == case.quantity("1")
        assert result.valuation_price is None
        assert result.mark is None and result.net_return is None
        assert result.unvalued_reason == IntentSimulationResult.unvalued_without_fresh_bid
        assert (
            DomainCodec().decode_json(DomainCodec().encode_json(result), IntentSimulationResult)
            == result
        )
        valued = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),),
            (case.book(1), case.book(10)),
        )
        assert valued.mark is not None
        with pytest.raises(ValueError, match="unvalued open holding"):
            replace(result, unvalued_reason=None)
        with pytest.raises(ValueError, match="unvalued open holding"):
            replace(result, mark=valued.mark)
        with pytest.raises(ValueError, match="valued result"):
            replace(valued, unvalued_reason="stale")
        with pytest.raises(ValueError, match="valued result"):
            replace(valued, mark=None, net_return=None)

    def test_identity_and_terminal_mark_cannot_be_silently_substituted(self) -> None:
        """Selected models, source identity and reconstructed accounting remain bound."""
        case = _Case()
        ledger = Ledger(LedgerState(initial_cash=case.spec.initial_cash, dimension=case.dimension))
        with pytest.raises(ValueError, match="collaborator identity"):
            IntentSimulation(
                replace(case.spec, execution_identity="wrong"), case.execution, case.costs, ledger
            )
        with pytest.raises(ValueError, match="market identity"):
            case.run((), (replace(case.book(1), source_identity="foreign"),))
        result = case.run((), (case.book(1), case.book(10)))
        assert result.mark is not None
        with pytest.raises(ValueError, match="terminal mark"):
            replace(result, mark=replace(result.mark, nav=case.money("999"))).__post_init__()

    def test_then_known_reference_change_cancels_old_order_and_admits_new_grid(self) -> None:
        """An unknown interval never falls back to a fixed grid; later known rules apply."""
        case = _Case(queue_ahead="0")
        case.spec = replace(
            case.spec,
            reference_history=case.reference_history(),
            reference_max_age_us=20_000_000,
        )
        one = OrderIntent(
            side="buy",
            quantity=case.quantity("1"),
            limit=case.price("99"),
            time_in_force="post-only",
        )
        early = case.run(
            (case.decision(2, one),),
            (
                case.book(1),
                case.trade(6, price="99", quantity="2", aggressor="sell"),
                case.book(10),
            ),
        )
        assert early.ledger.fills == ()
        assert early.orders[0].reason == "order_reference_unavailable"
        with pytest.raises(ValueError, match="order specification unknown"):
            case.spec.limits_at(case.at(6))
        two = replace(one, quantity=case.quantity("2"))
        late = case.run(
            (case.decision(7, two),),
            (
                case.book(1),
                case.book(8),
                case.trade(9, price="99", quantity="2", aggressor="sell"),
                case.book(10, bid="98", ask="100"),
            ),
        )
        assert late.ledger.fills[0].quantity == case.quantity("2")
        assert late.ledger.fills[0].filled_at == case.at(9)
        assert late.spec.limits_at(case.at(9)).lot == case.quantity("2")

    def test_receipt_matching_preserves_unknown_native_source_clock(self) -> None:
        """Receipt-only source timing is explicit and never rewrites the native book."""
        case = _Case()
        original = case.book(1)
        assert original.book is not None
        elapsed = case.at(1) - datetime(1970, 1, 1, tzinfo=UTC)
        received_ns = (
            (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
        ) * 1000 + 101
        canonical = replace(original.book, source_time=None, received_ns=received_ns)
        receipt_at = case.at(1) + timedelta(microseconds=1)
        receipt = replace(
            original,
            source_at=receipt_at,
            known_at=receipt_at,
            book=canonical,
            clock_assumption="receipt-as-matching",
        )
        result = case.run(
            (case.decision(2, TargetIntent(quantity=case.quantity("1"))),),
            (receipt, case.book(10)),
        )
        assert result.ledger.fills[0].filled_at == case.at(3)
        assert canonical.source_time is None
        assert any("receipt-as-matching" in limit for limit in result.limitations)
        with pytest.raises(ValueError, match="receipt-matching clock"):
            replace(receipt, source_at=case.at(1)).__post_init__()
