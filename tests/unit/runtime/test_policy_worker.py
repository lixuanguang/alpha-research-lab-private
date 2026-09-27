"""Verify exact reference book policies and isolated bounded decision calls."""

from __future__ import annotations

# standard library imports
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# third party library imports
import pytest

# project library imports
from financial_units import Currency, Dimension, ExactRatio, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.features import FeatureVector
from research.observations import NumericField
from runtime import PolicyProcessFailure, ProcessDecisionPolicy
from strategies import (
    DecisionContext,
    DecisionTransition,
    LiquidityClipPolicy,
    OrderIntent,
    ReferenceClipPolicy,
)
from telemetry import HealthMetric


class _BlockingClip(ReferenceClipPolicy):
    """Keep the child occupied long enough to test its independent heartbeat."""

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Block well beyond the caller's reply budget."""
        time.sleep(5)
        return super().decide(context, state)


class TestPolicyWorker:
    """Exercise the public policy interface without account or order capability."""

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
    def _context(cls, *, ask_size: str = "2") -> DecisionContext:
        """Supply one causal uncrossed public-book feature vector."""
        return DecisionContext(
            features=FeatureVector(
                entity=str(cls.dimension.instrument_id),
                decision_at=cls.at,
                event_at=cls.at,
                information_start=cls.at,
                available_at=cls.at,
                expires_at=cls.at + timedelta(seconds=1),
                definition="reference-book-v1",
                fields=ReferenceClipPolicy.fields,
                values=(
                    ExactRatio(numerator="101", denominator="1"),
                    ExactRatio(numerator="100", denominator="1"),
                    ExactRatio(numerator=ask_size, denominator="1"),
                ),
                reasons=("observed", "observed", "observed"),
                input_identity="public-book-source",
            ),
            prediction=None,
        )

    @classmethod
    def _policy(cls, kind: str = "fixed") -> ReferenceClipPolicy:
        """Bind one complete policy formula to the same installed digest."""
        policy = LiquidityClipPolicy if kind == "liquidity" else ReferenceClipPolicy
        return policy(
            cls._quantity("2"),
            cls.currency,
            cls._quantity("1"),
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
        assert first.intent.limit == Price(
            value=Decimal("103"), currency=self.currency, per=self.dimension
        )
        assert first.state == b"1"
        second = policy.decide(self._context(), first.state)
        assert type(second.intent) is OrderIntent
        assert second.intent.limit.value == Decimal("99")
        assert second.state == b"2"
        assert policy.identity != self._policy("liquidity" if kind == "fixed" else "fixed").identity

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
                implementation="a" * 64,
            )
        with pytest.raises(ValueError, match="positive visible size"):
            self._policy("liquidity").decide(self._context(ask_size="0"), b"0")

    def test_spawned_policy_returns_typed_transition_and_keeps_parent_state(self) -> None:
        """One child decision matches the pure formula and leaves state with its caller."""
        policy = self._policy()
        worker = ProcessDecisionPolicy(policy)
        try:
            assert worker.pid is not None and worker.pid > 0
            assert worker.is_alive
            assert worker.identity == policy.identity
            assert worker.output == policy.output
            worker.admit(ReferenceClipPolicy.fields, None)
            first = worker.decide(self._context(), worker.initial_state())
            assert first == policy.decide(self._context(), b"0")
            assert worker.decide(self._context(), first.state) == policy.decide(
                self._context(), b"1"
            )
        finally:
            worker.close()
        assert not worker.is_alive
        assert worker.pid is not None
        worker.validate_state(b"2")
        with pytest.raises(PolicyProcessFailure) as failure:
            worker.decide(self._context(), b"2")
        assert failure.value.pid == worker.pid

    def test_blocked_decision_times_out_while_child_heartbeat_advances(self) -> None:
        """A blocked formula cannot exceed its deadline or stop independent liveness."""
        worker = ProcessDecisionPolicy(
            _BlockingClip(
                self._quantity("2"),
                self.currency,
                self._quantity("1"),
                implementation="a" * 64,
            ),
            timeout_seconds=1,
        )
        try:
            deadline = time.monotonic() + 3
            while worker.health.snapshot()[HealthMetric.HEARTBEAT] == 0:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            before = worker.health.snapshot()[HealthMetric.HEARTBEAT]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(worker.decide, self._context(), b"0")
                time.sleep(0.3)
                after = worker.health.snapshot()[HealthMetric.HEARTBEAT]
                assert after > before
                with pytest.raises(PolicyProcessFailure, match="timed out"):
                    pending.result(timeout=2)
            assert not worker.is_alive
        finally:
            worker.close()
