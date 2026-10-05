"""Verify exact reference formulas, built-in candidates and isolated bounded steps."""

from __future__ import annotations

# standard library imports
import dataclasses
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal, cast

# third party library imports
import msgspec
import pytest

# project library imports
from configuration import ReferenceCandidate
from financial_units import Currency, Dimension, ExactRatio, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.features import FeatureVector
from research.observations import DecisionInputs, NamedObservation, NumericField
from runtime import (
    CandidateProcessFailure,
    CandidateSession,
    LoadedCandidate,
    LocalCandidateExecutor,
    ProcessCandidateExecutor,
    ReferenceCandidates,
)
from strategies import (
    DecisionContext,
    DecisionSession,
    DecisionTransition,
    LiquidityClipPolicy,
    OrderIntent,
    ReferenceClipPolicy,
    ReferencePolicies,
    TargetClipPolicy,
    TargetIntent,
)
from telemetry import HealthMetric


class _BlockingClip(ReferenceClipPolicy):
    """Keep the child occupied long enough to test its independent heartbeat."""

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Block well beyond the caller's reply budget."""
        time.sleep(5)
        return super().decide(context, state)


class TestReferenceCandidates:
    """Exercise reference formulas and built-in candidates without account capability."""

    at = datetime(2026, 9, 27, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact configured base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _context(
        cls, *, ask: str = "101", bid: str = "100", ask_size: str = "2"
    ) -> DecisionContext:
        """Supply one causal uncrossed public-book feature vector of exact ratios."""
        ask_ratio, bid_ratio = Fraction(ask), Fraction(bid)
        return DecisionContext(
            features=FeatureVector(
                entity=str(cls.dimension.instrument_id),
                decision_at=cls.at,
                event_at=cls.at,
                information_start=cls.at,
                available_at=cls.at,
                expires_at=cls.at + timedelta(seconds=1),
                definition="reference-book",
                fields=ReferenceClipPolicy.fields,
                values=(
                    ExactRatio.from_fraction(ask_ratio),
                    ExactRatio.from_fraction(bid_ratio),
                    ExactRatio(numerator=ask_size, denominator="1"),
                ),
                reasons=("observed", "observed", "observed"),
                input_identity="public-book-source",
            ),
            prediction=None,
        )

    @classmethod
    def _price(cls, value: str) -> Price:
        """Create an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _policy(cls, kind: str = "fixed", *, tick: str = "0.01") -> ReferenceClipPolicy:
        """Bind one complete policy formula to the same installed digest."""
        policy = LiquidityClipPolicy if kind == "liquidity" else ReferenceClipPolicy
        return policy(
            cls._quantity("2"),
            cls.currency,
            cls._quantity("1"),
            tick=cls._price(tick),
            implementation="a" * 64,
        )

    @pytest.mark.parametrize(("kind", "expected_quantity"), (("fixed", "2"), ("liquidity", "1")))
    def test_reference_policies_preserve_exact_order_and_state(
        self, kind: str, expected_quantity: str
    ) -> None:
        """The two formulas share an opening price but differ in visible-size clipping."""
        policy = self._policy(kind)
        policy.admit(ReferenceClipPolicy.fields, None)
        first = policy.decide(self._context(), policy.initial_state())
        assert type(first.intent) is OrderIntent
        assert first.intent.quantity == self._quantity(expected_quantity)
        # 200 bps through the 101 ask, then one tick below the 100 bid.
        assert first.intent.limit == self._price("103.02")
        assert first.state == b"1"
        second = policy.decide(self._context(), first.state)
        assert type(second.intent) is OrderIntent
        assert second.intent.limit.value == Decimal("99.99")
        assert second.state == b"2"
        assert policy.identity != self._policy("liquidity" if kind == "fixed" else "fixed").identity

    def test_target_clip_holds_one_constant_target_through_a_session(self) -> None:
        """Every eligible book requests the same absolute target, under its own identity."""
        policy = ReferencePolicies.create(
            "target_clip",
            self._quantity("1"),
            self.currency,
            self._quantity("1"),
            tick=self._price("0.01"),
            implementation="a" * 64,
        )
        assert type(policy) is TargetClipPolicy and policy.output == "target"
        assert policy.identity != self._policy().identity
        session = DecisionSession(
            policy,
            run_identity="sustained",
            instance="hold-a",
            entity=str(self.dimension.instrument_id),
        )
        for offset in range(3):
            context = self._context(ask=str(101 + offset), bid=str(100 + offset))
            at = self.at + timedelta(milliseconds=100 * offset)
            record = session.evaluate(
                DecisionContext(features=context.features, prediction=None, evaluated_at=at)
            )
            assert record.intent == TargetIntent(quantity=self._quantity("1"))
        assert policy.decide(self._context(), b"7").state == b"8"
        with pytest.raises(ValueError, match="unknown reference policy"):
            ReferencePolicies.create(
                cast(Literal["target_clip"], "maker_clip"),
                self._quantity("1"),
                self.currency,
                self._quantity("1"),
                tick=self._price("0.01"),
                implementation="a" * 64,
            )

    def test_clip_prices_scale_with_a_low_priced_book(self) -> None:
        """Relative and tick offsets keep prices positive and near the touch below one unit."""
        policy = self._policy(tick="0.0001")
        context = self._context(ask="0.05", bid="0.04")
        first = policy.decide(context, policy.initial_state())
        assert type(first.intent) is OrderIntent
        assert first.intent.limit == self._price("0.0510")
        resting = policy.decide(context, first.state)
        assert type(resting.intent) is OrderIntent
        assert resting.intent.limit == self._price("0.0399")
        # A one-tick bid cannot rest a tick lower, so the interest joins the bid.
        joined = policy.decide(self._context(ask="0.0003", bid="0.0001"), b"1")
        assert type(joined.intent) is OrderIntent
        assert joined.intent.limit == self._price("0.0001")
        assert policy.identity != self._policy(tick="0.001").identity

    @pytest.mark.parametrize(
        ("ask", "tick", "expected"),
        (("100", "0.01", "102.00"), ("100.01", "0.01", "102.02"), ("0.0003", "0.0001", "0.0004")),
    )
    def test_opening_clip_covers_modeled_cost_inside_deviation_limit(
        self, ask: str, tick: str, expected: str
    ) -> None:
        """The opening limit rounds up onto the grid, past a 50 bps cost and inside 500 bps."""
        policy = self._policy(tick=tick)
        bid = str(Decimal(ask) - Decimal(tick))
        first = policy.decide(self._context(ask=ask, bid=bid), policy.initial_state())
        assert type(first.intent) is OrderIntent
        limit = first.intent.limit.value
        assert limit == Decimal(expected)
        assert limit % Decimal(tick) == 0
        # The capacity fixture models a 0.50 adverse cost on a 100 touch.
        assert limit >= Decimal(ask) * Decimal("1.005")
        assert limit - Decimal(ask) <= max(Decimal(ask) * Decimal("0.05"), Decimal(tick))

    def test_reference_policy_rejects_foreign_signature_state_and_parameters(self) -> None:
        """Malformed book inputs cannot silently become an executable order."""
        policy = self._policy()
        with pytest.raises(ValueError, match="named book signature"):
            policy.admit((NumericField(name="ask", units="wrong"),), None)
        with pytest.raises(ValueError, match="state"):
            policy.validate_state(b"01")
        with pytest.raises(ValueError, match="parameters"):
            ReferenceClipPolicy(
                self._quantity("2"),
                self.currency,
                self._quantity("3"),
                tick=self._price("0.01"),
                implementation="a" * 64,
            )
        with pytest.raises(ValueError, match="parameters"):
            ReferenceClipPolicy(
                self._quantity("2"),
                self.currency,
                self._quantity("1"),
                tick=self._price("0"),
                implementation="a" * 64,
            )
        with pytest.raises(ValueError, match="positive visible size"):
            self._policy("liquidity").decide(self._context(ask_size="0"), b"0")

    @classmethod
    def _candidate(
        cls, formula: Literal["fixed_clip", "liquidity_clip", "target_clip"] = "fixed_clip"
    ) -> LoadedCandidate:
        """Load one installed reference formula as a runtime candidate."""
        return ReferenceCandidates(venue="okx", freshness_us=5_000_000, clock="receipt").load(
            ReferenceCandidate(formula=formula, cadence_us=1_000_000, starts_at=cls.at),
            instance="clip-a",
            entity=str(cls.dimension.instrument_id),
            quantity=cls._quantity("2"),
            lot=cls._quantity("1"),
            currency=cls.currency,
            tick=cls._price("0.01"),
            source_identity="native-touch",
        )

    @classmethod
    def _inputs(
        cls, loaded: LoadedCandidate, at: datetime, *, ask: str = "101", bid: str = "100"
    ) -> DecisionInputs:
        """Supply the native touch fields the reference candidate reads at one instant."""
        values = {"ask": ask, "bid": bid, "ask_size": "2"}
        return DecisionInputs(
            entity=str(cls.dimension.instrument_id),
            decision_at=at,
            observations=tuple(
                NamedObservation(
                    input=item,
                    entity=str(cls.dimension.instrument_id),
                    event_at=at,
                    available_at=at,
                    value=ExactRatio.from_fraction(Fraction(values[item.field.name])),
                    reason="observed",
                    lineage="native-touch",
                )
                for item in loaded.definition.inputs
            ),
        )

    def test_reference_candidate_reproduces_its_formula_on_the_grid(self) -> None:
        """A packaged formula decides exactly as the pure policy and keeps state across gaps."""
        loaded = self._candidate()
        policy = self._policy()
        assert loaded.definition.state.on_gap == "continue"
        assert loaded.definition.output == "order"
        executor = LocalCandidateExecutor(loaded)
        first = executor.step(self._inputs(loaded, self.at), None)
        assert first.decision is not None
        assert first.decision.intent == policy.decide(self._context(), b"0").intent
        # Skipping one instant keeps the clip counter: the next order rests below the bid.
        later = self.at + timedelta(seconds=2)
        second = executor.step(self._inputs(loaded, later), first.checkpoint)
        assert second.decision is not None
        assert second.decision.intent == policy.decide(self._context(), b"1").intent
        with pytest.raises(ValueError, match="cadence"):
            executor.step(self._inputs(loaded, later + timedelta(milliseconds=1)), None)
        assert loaded.identity != self._candidate("liquidity_clip").identity
        with pytest.raises(ValueError, match="explicit reset"):
            CandidateSession(
                dataclasses.replace(
                    loaded,
                    definition=msgspec.structs.replace(
                        loaded.definition,
                        state=msgspec.structs.replace(loaded.definition.state, on_restart="reset"),
                    ),
                ),
                first.checkpoint,
            )

    def test_spawned_candidate_returns_typed_step_and_keeps_parent_state(self) -> None:
        """One child step matches the in-process step and leaves state with its caller."""
        loaded = self._candidate()
        local = LocalCandidateExecutor(loaded)
        worker = ProcessCandidateExecutor(loaded)
        try:
            assert worker.pid is not None and worker.pid > 0
            assert worker.is_alive
            first = worker.step(self._inputs(loaded, self.at), None)
            assert first == local.step(self._inputs(loaded, self.at), None)
            later = self.at + timedelta(seconds=1)
            assert worker.step(self._inputs(loaded, later), first.checkpoint) == local.step(
                self._inputs(loaded, later), first.checkpoint
            )
            with pytest.raises(ValueError, match="candidate rejected input"):
                worker.step(self._inputs(loaded, later, ask="99", bid="100"), first.checkpoint)
        finally:
            worker.close()
        assert not worker.is_alive
        assert worker.pid is not None
        with pytest.raises(CandidateProcessFailure) as failure:
            worker.step(self._inputs(loaded, self.at), None)
        assert failure.value.pid == worker.pid

    def test_blocked_step_times_out_while_child_heartbeat_advances(self) -> None:
        """A blocked formula cannot exceed its deadline or stop independent liveness."""
        loaded = self._candidate()
        blocking = dataclasses.replace(
            loaded,
            policy=_BlockingClip(
                self._quantity("2"),
                self.currency,
                self._quantity("1"),
                tick=self._price("0.01"),
                implementation="a" * 64,
            ),
        )
        worker = ProcessCandidateExecutor(blocking, timeout_seconds=1)
        try:
            deadline = time.monotonic() + 3
            while worker.health.snapshot()[HealthMetric.HEARTBEAT] == 0:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            before = worker.health.snapshot()[HealthMetric.HEARTBEAT]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(worker.step, self._inputs(loaded, self.at), None)
                time.sleep(0.3)
                after = worker.health.snapshot()[HealthMetric.HEARTBEAT]
                assert after > before
                with pytest.raises(CandidateProcessFailure, match="timed out"):
                    pending.result(timeout=2)
            assert not worker.is_alive
        finally:
            worker.close()
