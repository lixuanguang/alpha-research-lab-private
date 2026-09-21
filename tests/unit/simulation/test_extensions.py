"""Verify compatible target-rule registration and exact signal direction."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest
from economic_examples import START, ReplayInputs
from msgspec.structs import replace

# project library imports
from applications.backtest import run_backtest
from financial_units import Currency, Dimension, ExactRatio, Price, Quantity, QuantityKind
from market_data.query import InputBinding, QueryBatch
from reference_data.instruments import InstrumentId
from research.features import (
    FeatureDefinition,
    FeatureRegistry,
    FeatureValue,
    TrailingReturn,
    WindowPolicy,
)
from research.models import EstimatorRegistry, LinearDefinition, LinearModel
from research.observations import Observation, TradePoint
from simulation import EconomicCheckpoint, EconomicResult
from strategies import Momentum, Reversal, RuleRegistry, TargetRule

_START = datetime(2024, 6, 1, tzinfo=UTC)


class _InvalidIdentityRule:
    """Provide a structurally valid rule with an invalid registration identity."""

    @property
    def identity(self) -> str:
        """Return the invalid empty identity used by the rejection test."""
        return ""

    def target(
        self,
        previous: Observation | None,
        current: Observation,
        quantity: Quantity,
        cadence: timedelta,
    ) -> Quantity | None:
        """Satisfy the target-rule protocol without contributing behavior."""
        return None


class _DelegatingFeature:
    """Expose one independently constructed evaluator with the trailing contract."""

    def __init__(self, definition: TrailingReturn) -> None:
        """Bind one immutable typed definition for delegated evaluation.

        Args:
            definition: Validated trailing-return settings retained by the evaluator.
        """
        self._definition = definition

    @property
    def schema_version(self) -> str:
        """Return the retained definition schema."""
        return self._definition.schema_version

    @property
    def units(self) -> str:
        """Return the retained feature units."""
        return self._definition.units

    @property
    def policy(self) -> WindowPolicy:
        """Return the retained causal window policy."""
        return self._definition.policy

    @property
    def cadence_us(self) -> int:
        """Return the retained decision cadence."""
        return self._definition.cadence_us

    @property
    def processing_delay_us(self) -> int:
        """Return the retained processing delay."""
        return self._definition.processing_delay_us

    @property
    def identity(self) -> str:
        """Return the retained immutable feature identity."""
        return self._definition.identity

    def __post_init__(self) -> None:
        """Validate the wrapped definition."""
        self._definition.__post_init__()

    def evaluate(
        self, batches: tuple[QueryBatch, ...], *, binding: InputBinding, decision_at: datetime
    ) -> FeatureValue:
        """Delegate exact evaluation to the retained feature definition."""
        return self._definition.evaluate(batches, binding=binding, decision_at=decision_at)


class _DelegatingEstimator(LinearModel):
    """Mark a distinct estimator engine while preserving the linear consumer API."""


def _delegating_feature(definition: TrailingReturn) -> FeatureDefinition:
    """Construct one feature evaluator from typed settings."""
    return _DelegatingFeature(definition)


def _delegating_estimator(definition: LinearDefinition) -> LinearModel:
    """Construct one estimator after observing typed settings."""
    definition.__post_init__()
    return _DelegatingEstimator()


class TestRuleRegistry:
    """Exercise registry invariants and the independent reversal signal."""

    @staticmethod
    def _observation(second: int, price: str, order: int) -> Observation:
        """Build one exact completed trade observation for a direction example."""
        dimension = Dimension(instrument_id=InstrumentId(UUID(int=1)), kind=QuantityKind.BASE_UNIT)
        point = TradePoint(
            trade_id=order,
            revision=f"revision-{order}",
            event_at=_START + timedelta(seconds=second - 1),
            known_at=_START + timedelta(seconds=second - 1),
            order=order,
            price=Price(value=Decimal(price), currency=Currency.from_code("USDT"), per=dimension),
        )
        return Observation(
            closed_at=_START + timedelta(seconds=second), point=point, reason="valid"
        )

    def test_default_registry_resolves_fresh_builtins(self) -> None:
        """Keep built-ins available while making every resolution an isolated instance."""
        registry = RuleRegistry()

        assert registry.identities == (
            "completed-price-momentum-v1",
            "no-trade-v1",
            "completed-price-reversal-v1",
        )
        first = registry.resolve("completed-price-reversal-v1")
        second = registry.resolve("completed-price-reversal-v1")
        assert isinstance(first, Reversal)
        assert isinstance(second, Reversal)
        assert first is not second

    def test_reversal_buys_only_on_strict_fall(self) -> None:
        """Expose fall, equal and rise outcomes through the same exact target contract."""
        dimension = Dimension(instrument_id=InstrumentId(UUID(int=1)), kind=QuantityKind.BASE_UNIT)
        quantity = Quantity(value=Decimal("0.001"), dimension=dimension)
        rule = RuleRegistry().resolve("completed-price-reversal-v1")
        previous = self._observation(60, "110", 0)

        falling = rule.target(
            previous, self._observation(120, "100", 1), quantity, timedelta(minutes=1)
        )
        equal = rule.target(
            previous, self._observation(120, "110", 1), quantity, timedelta(minutes=1)
        )
        rising = rule.target(
            previous, self._observation(120, "120", 1), quantity, timedelta(minutes=1)
        )

        assert falling == quantity
        assert equal is not None and equal.value == Decimal("0")
        assert rising is not None and rising.value == Decimal("0")

    def test_registration_rejects_duplicate_and_invalid_identities(self) -> None:
        """Reject duplicate reviewed IDs and factories that cannot identify a rule."""
        registry = RuleRegistry()
        with pytest.raises(ValueError, match="duplicate"):
            registry.register(Momentum)
        with pytest.raises(ValueError, match="identity"):
            registry.register(_InvalidIdentityRule)

    def test_rule_protocol_remains_the_injected_consumer_contract(self) -> None:
        """Keep registry results typed as the narrow target protocol."""
        rule: TargetRule = RuleRegistry().resolve("completed-price-momentum-v1")
        assert rule.identity == "completed-price-momentum-v1"

    def test_reversal_exact_run_and_checkpoint_isolation(self) -> None:
        """Keep independent momentum/reversal state and a pending reversal checkpoint."""
        reader, momentum_spec = ReplayInputs._inputs(ReplayInputs.rows)
        reversal_spec = replace(
            momentum_spec, instance="synthetic-reversal", rule=Reversal().identity
        )
        registry = RuleRegistry()
        momentum = run_backtest(reader, momentum_spec, registry=registry)
        reversal = run_backtest(reader, reversal_spec, registry=registry)
        assert isinstance(momentum, EconomicResult)
        assert isinstance(reversal, EconomicResult)
        assert tuple(fill.filled_at for fill in momentum.checkpoint.state.ledger.fills) == (
            START + timedelta(seconds=121),
            START + timedelta(seconds=181),
        )
        assert tuple(fill.filled_at for fill in reversal.checkpoint.state.ledger.fills) == (
            START + timedelta(seconds=181),
        )
        assert reversal.checkpoint.state.trace[-1].balance.holding.value == Decimal("0.00100")
        checkpoint = run_backtest(
            reader,
            reversal_spec,
            registry=registry,
            stop_at=START + timedelta(seconds=180),
        )
        assert isinstance(checkpoint, EconomicCheckpoint)
        assert checkpoint.state.pending is not None
        assert (
            run_backtest(reader, reversal_spec, registry=registry, checkpoint=checkpoint)
            == reversal
        )


class TestResearchRegistries:
    """Prove injected research engines preserve the existing typed contracts."""

    @staticmethod
    def _feature() -> TrailingReturn:
        """Build one immutable feature definition for registry resolution."""
        return TrailingReturn(
            policy=WindowPolicy(lookback_us=10_000_000, min_trades=2, max_staleness_us=2_000_000),
            cadence_us=10_000_000,
            processing_delay_us=0,
        )

    def test_compatible_feature_engine_receives_typed_definition(self) -> None:
        """Allow a distinct evaluator while retaining identity, units and timing."""
        definition = self._feature()
        registry = FeatureRegistry()
        registry.register("delegating-trailing-v1", _delegating_feature)

        resolved = registry.resolve("delegating-trailing-v1", definition)

        assert isinstance(resolved, _DelegatingFeature)
        assert id(resolved) != id(definition)
        assert resolved.identity == definition.identity
        assert resolved.units == definition.units
        assert resolved.policy == definition.policy
        assert resolved.cadence_us == definition.cadence_us
        assert resolved.processing_delay_us == definition.processing_delay_us

    def test_compatible_estimator_engine_receives_typed_definition(self) -> None:
        """Allow a distinct estimator while retaining the linear consumer contract."""
        zero = ExactRatio(numerator="0", denominator="1")
        definition = LinearDefinition(
            mode="configured", assumptions="Injected exact estimator", intercept=zero, slope=zero
        )
        registry = EstimatorRegistry()
        registry.register("delegating-linear-v1", _delegating_estimator)

        first = registry.resolve("delegating-linear-v1", definition)
        second = registry.resolve("delegating-linear-v1", definition)

        assert isinstance(first, _DelegatingEstimator)
        assert first is not second
