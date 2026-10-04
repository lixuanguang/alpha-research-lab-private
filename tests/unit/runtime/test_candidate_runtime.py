"""Exercise candidate state, temporal admission and persisted feature consumption."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import replace as replace_dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import UUID

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from accounting import Ledger, LedgerState
from applications.paper import run_live_paper
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
    CandidateDeployment,
    CapabilityField,
    CapabilityKind,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    CaptureConfig,
    PaperConfiguration,
    PaperExecutionScenario,
    UniverseSelection,
)
from execution import OrderEvent, PaperMarket, PaperOrderJournal
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.collection import CaptureRunner, CaptureRunResult
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from reference_data.instruments import InstrumentId
from research.experiments import (
    CandidateArtifact,
    CandidateBundle,
    CandidateComponent,
    CandidateDefinition,
    CandidateMetricContract,
    CandidateStateContract,
)
from research.features import (
    FeatureSchema,
    FeatureSession,
    FeatureStoreDefinition,
    ProjectionFeature,
    RunningMeanFeature,
    StoredFeature,
    VersionedFeatureStore,
)
from research.features.serving import FeastServingBridge
from research.observations import (
    DecisionInputs,
    InputRequirement,
    LiveBookDecisionSource,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from risk import SpotLimits
from runtime import (
    CandidateComponents,
    CandidateFeatureFeed,
    CandidateLoader,
    CandidateSession,
    LoadedCandidate,
    PaperCandidateRuntime,
    PaperCaptureObserver,
    PaperCheckpoint,
)
from runtime.paper import PaperFaultEvidence
from runtime.shared_paper import ObservedLiveBookDelivery
from serialization import DomainCodec, WireRecord
from strategies import (
    DecisionContext,
    DecisionIntent,
    DecisionTransition,
    ExposureIntent,
    OrderIntent,
    StrategyEvent,
    TargetIntent,
)

_AT = datetime(2025, 6, 1, 12, tzinfo=UTC)
_ENTITY = "00000000-0000-4000-8000-000000000021"
_INSTRUMENT = InstrumentId(UUID(_ENTITY))
_FIELD = NumericField(name="level", units="ratio")
_INPUT = InputRequirement(
    name="signal", family="non-book", clock="authored", field=_FIELD, max_age_us=10_000_000
)
_CODE = "a" * 64


class _MalformedCaptureRunner(CaptureRunner):
    """Fail one live capture after the dedicated runtime has opened."""

    async def run(
        self,
        request: CaptureRequest,
        output: Path,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> CaptureRunResult:
        """Expose the original protocol failure to workflow fault handling."""
        raise ValueError("malformed capture frame")


class _DisconnectedCaptureRunner(CaptureRunner):
    """Return a completed recording with an unavailable terminal book."""

    async def run(
        self,
        request: CaptureRequest,
        output: Path,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> CaptureRunResult:
        """Expose finite connection loss through the capture result contract."""
        return CaptureRunResult(
            request=request,
            root=output,
            summary={"stop_reason": "connect_failed_unknown_loss", "synchronized": False},
        )


class _RegressingUTCClock(datetime):
    """Expose a scheduler wall clock that moves backward between two reads."""

    reads = 0

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _RegressingUTCClock:
        """Return two UTC instants in descending order."""
        cls.reads += 1
        instant = _AT + timedelta(seconds=3 if cls.reads == 1 else 2)
        return cls(
            instant.year,
            instant.month,
            instant.day,
            instant.hour,
            instant.minute,
            instant.second,
            tzinfo=UTC,
        )


class _ReferencePolicy:
    """Return pure typed intents while exposing controlled failure cases."""

    def __init__(self, output: Literal["target", "order"] = "target") -> None:
        """Bind the declared intent family and one editable test fault."""
        self._output = output
        self.wrong_output = False
        self.wrong_tif = False

    @property
    def identity(self) -> str:
        """Identify this fixed test decision rule."""
        return f"reference-{self._output}"

    @property
    def output(self) -> Literal["target", "order"]:
        """Expose the one selected intent family."""
        return self._output

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the exact feature signature before a decision."""
        if fields != (_FIELD,) or prediction is not None:
            raise ValueError("reference policy requires one level feature")

    def initial_state(self) -> bytes:
        """Start each instance at zero committed decisions."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject malformed portable count state."""
        if type(state) is not bytes or not state.isdigit():
            raise ValueError("invalid reference policy state")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Advance only the staged state supplied by the session."""
        context.__post_init__()
        self.validate_state(state)
        intent: DecisionIntent
        if self.wrong_output:
            intent = ExposureIntent(
                exposure=Money(value=Decimal("1"), currency=Currency.from_code("USD"))
            )
        elif self._output == "order":
            intent = OrderIntent(
                side="buy",
                quantity=Quantity(
                    value=Decimal("1"),
                    dimension=Dimension(instrument_id=_INSTRUMENT, kind=QuantityKind.BASE_UNIT),
                ),
                limit=Price(
                    value=Decimal("100"),
                    currency=Currency.from_code("USD"),
                    per=Dimension(instrument_id=_INSTRUMENT, kind=QuantityKind.BASE_UNIT),
                ),
                time_in_force="ioc" if self.wrong_tif else "gtc",
            )
        else:
            intent = TargetIntent(
                quantity=Quantity(
                    value=Decimal("1"),
                    dimension=Dimension(instrument_id=_INSTRUMENT, kind=QuantityKind.BASE_UNIT),
                )
            )
        return DecisionTransition(intent=intent, state=str(int(state) + 1).encode("ascii"))


class _NoCallWorker:
    """Detect accidental serving I/O for statuses that must pause locally."""

    def __init__(self) -> None:
        """Start with no requests."""
        self.calls = 0

    def __call__(self, request: bytes) -> bytes:
        """Fail if an unavailable feature escapes before status admission."""
        self.calls += 1
        raise AssertionError("unavailable feature must not call the Feast worker")


class TestCandidateSession:
    """Use complete immutable candidate records and installed fixture profiles."""

    @staticmethod
    def _schema(*, incremental: bool = True, ttl_us: int = 10_000_000) -> FeatureSchema:
        """Choose the installed exact mean or projection reference kernel."""
        return FeatureSchema(
            implementation="running-mean" if incremental else "named-projection",
            inputs=(_INPUT,),
            outputs=(_FIELD,),
            parameters=(),
            mode="incremental" if incremental else "batch",
            ttl_us=ttl_us,
        )

    @staticmethod
    def _inputs(at: datetime, value: int | None) -> DecisionInputs:
        """Author an exact observation with independent event and knowledge clocks."""
        return DecisionInputs(
            entity=_ENTITY,
            decision_at=at,
            observations=(
                NamedObservation(
                    input=_INPUT,
                    entity=_ENTITY,
                    event_at=at,
                    available_at=at if value is not None else None,
                    value=None if value is None else ExactRatio.from_fraction(Fraction(value)),
                    reason="observed" if value is not None else "missing",
                    lineage=f"authored-at-{at.isoformat()}",
                ),
            ),
        )

    @staticmethod
    def _requirements(
        output: Literal["target", "order"], *, freshness_us: int
    ) -> tuple[CapabilityRequirement, ...]:
        """Declare all six independent fixture boundaries for the session."""
        result: list[CapabilityRequirement] = []
        domains: tuple[tuple[str, CapabilityKind], ...] = (
            ("signal", "market_data"),
            ("reference", "reference_data"),
            ("calendar", "calendar"),
            ("valuation", "valuation"),
            ("account", "account"),
            ("execution", "execution"),
        )
        for name, kind in domains:
            result.append(
                CapabilityRequirement(
                    name=name,
                    kind=kind,
                    product="spot",
                    venue="synthetic",
                    calendar="continuous-utc",
                    channel="non-book" if name == "signal" else None,
                    clock="authored" if name == "signal" else None,
                    max_freshness_us=freshness_us if name == "signal" else None,
                    fields=(CapabilityField(name="level", units="ratio"),)
                    if name == "signal"
                    else (),
                    operations=(f"intent:{output}",) if name == "execution" else (),
                    order_types=("gtc",) if output == "order" and name == "execution" else (),
                    qualification="fixture",
                )
            )
        return tuple(result)

    @staticmethod
    def _artifacts() -> tuple[CandidateArtifact, ...]:
        """Create valid local references; session tests perform no bundle I/O."""
        return tuple(
            CandidateArtifact(name=name, sha256=hashlib.sha256(name.encode()).hexdigest())
            for name in (
                "schema",
                "feature-parameters",
                "policy-parameters",
                "metric-parameters",
                "chart-parameters",
            )
        )

    @classmethod
    def _definition(
        cls,
        *,
        output: Literal["target", "order"] = "target",
        on_gap: Literal["pause", "reset", "continue"] = "pause",
        warmup: int = 0,
        on_restart: Literal["restore", "reset"] = "restore",
        incremental: bool = True,
        freshness_us: int = 1_000_000,
    ) -> CandidateDefinition:
        """Build a complete executable definition with no research provenance."""
        artifacts = {item.name: item for item in cls._artifacts()}
        components = tuple(
            CandidateComponent(
                role=role,
                factory_key=f"reference-{role}",
                identity=f"reference-{role}",
                implementation_sha256=_CODE,
                parameters=artifacts[f"{role}-parameters"],
            )
            for role in ("feature", "policy", "metric", "chart")
        )
        return CandidateDefinition(
            name="runtime-reference",
            version="1",
            code_sha256=_CODE,
            environment_sha256=_CODE,
            feature_schema=artifacts["schema"],
            feature_store=None,
            transform=None,
            estimator=None,
            components=components,
            inputs=(_INPUT,),
            requirements=cls._requirements(output, freshness_us=freshness_us),
            product="spot",
            calendar="continuous-utc",
            entities=(_ENTITY,),
            cadence_us=1_000_000,
            available_at=_AT - timedelta(seconds=1),
            output=output,
            state=CandidateStateContract(
                feature_mode="incremental" if incremental else "batch",
                warmup_observations=warmup,
                checkpoint_schema="candidate-checkpoint" if on_restart == "restore" else None,
                on_gap=on_gap,
                on_restart=on_restart,
                policy_state_schema="reference-policy-state",
            ),
            metrics=(
                CandidateMetricContract(
                    name="count",
                    kind="metric",
                    component_key="reference-metric",
                    version="1",
                    units="count",
                    applies_to=("research", "runtime"),
                ),
                CandidateMetricContract(
                    name="signal-chart",
                    kind="chart",
                    component_key="reference-chart",
                    version="1",
                    units="ratio",
                    applies_to=("research", "runtime"),
                ),
            ),
            artifacts=tuple(artifacts.values()),
        )

    @staticmethod
    def _bindings(
        requirements: tuple[CapabilityRequirement, ...],
    ) -> tuple[CapabilitySelection, ...]:
        """Name every selected installed fixture profile."""
        return tuple(
            CapabilitySelection(name=r.name, profile=f"fixture-{r.name}") for r in requirements
        )

    @classmethod
    def _loaded(
        cls,
        policy: _ReferencePolicy,
        *,
        on_gap: Literal["pause", "reset", "continue"] = "pause",
        warmup: int = 0,
        on_restart: Literal["restore", "reset"] = "restore",
        incremental: bool = True,
        ttl_us: int = 10_000_000,
        freshness_us: int = 1_000_000,
        input_mode: Literal["source", "offline_features", "online_features"] = "source",
        source_identity: str = "authored-source",
        feature_version: str | None = None,
        starts_at: datetime = _AT,
    ) -> LoadedCandidate:
        """Compose the actual session objects and resolved fixture signatures."""
        executable = cls._definition(
            output=policy.output,
            on_gap=on_gap,
            warmup=warmup,
            on_restart=on_restart,
            incremental=incremental,
            freshness_us=freshness_us,
        )
        mode: Literal["replay", "runtime"] = (
            "runtime" if input_mode == "online_features" else "replay"
        )
        deployment = CandidateDeployment(
            name="runtime-reference",
            candidate_identity=executable.identity,
            instance="instance-one",
            entity=_ENTITY,
            mode=mode,
            input_mode=input_mode,
            source_identity=source_identity,
            starts_at=starts_at,
            selections=cls._bindings(executable.requirements),
            universes=UniverseSelection(
                collection=(),
                research=(_INSTRUMENT,),
                strategy=(_INSTRUMENT,),
                authorized_trading=(),
            ),
            feature_version=feature_version,
        )
        profiles = tuple(
            CapabilityProfile(
                name=f"fixture-{r.name}",
                kind=r.kind,
                implementation_identity=f"installed-{r.kind}",
                version="1",
                products=("spot",),
                venues=("synthetic",),
                calendars=("continuous-utc",),
                modes=("replay", "runtime"),
                channels=("non-book",) if r.name == "signal" else (),
                clocks=("authored",) if r.name == "signal" else (),
                max_freshness_us=freshness_us if r.name == "signal" else None,
                fields=(CapabilityField(name="level", units="ratio"),)
                if r.name == "signal"
                else (),
                operations=(f"intent:{policy.output}",) if r.name == "execution" else (),
                order_types=("gtc",) if policy.output == "order" and r.name == "execution" else (),
            )
            for r in executable.requirements
        )
        schema = cls._schema(incremental=incremental, ttl_us=ttl_us)
        kernel = RunningMeanFeature(schema) if incremental else ProjectionFeature(schema)
        definition = (
            FeatureStoreDefinition(
                name="runtime-reference",
                entity_type="instrument",
                schema=schema,
                instance="instance-one" if incremental else None,
            )
            if input_mode != "source"
            else None
        )
        return LoadedCandidate(
            definition=executable,
            deployment=deployment,
            capabilities=CapabilityRegistry(profiles).resolve(
                executable.requirements, deployment.selections, mode=mode
            ),
            feature=kernel,
            policy=policy,
            transform=None,
            transform_version=None,
            estimator=None,
            estimator_version=None,
            store_definition=definition,
            metrics=(),
            charts=(),
        )

    def test_failed_policy_transition_rolls_back_feature_and_decision_state(self) -> None:
        """A failed second intent cannot change the mean or policy continuation."""
        policy = _ReferencePolicy()
        session = CandidateSession(self._loaded(policy))
        first = session.evaluate_inputs(self._inputs(_AT, 2))
        assert first.status == "decided"
        committed = session.checkpoint()
        policy.wrong_output = True
        with pytest.raises(ValueError, match="undeclared output"):
            session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=1), 8))
        assert session.checkpoint() == committed
        policy.wrong_output = False
        resumed = session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=1), 4))
        assert resumed.status == "decided"
        assert resumed.feature is not None
        assert resumed.feature.values == (ExactRatio.from_fraction(Fraction(3)),)
        assert resumed.checkpoint.observations == 2
        assert resumed.checkpoint.policy.state == b"2"

    def test_undeclared_order_tif_does_not_commit(self) -> None:
        """A policy may emit only the declared order semantics after state validation."""
        policy = _ReferencePolicy(output="order")
        session = CandidateSession(self._loaded(policy))
        before = session.checkpoint()
        policy.wrong_tif = True
        with pytest.raises(ValueError, match="undeclared order type"):
            session.evaluate_inputs(self._inputs(_AT, 1))
        assert session.checkpoint() == before
        policy.wrong_tif = False
        accepted = session.evaluate_inputs(self._inputs(_AT, 1))
        assert accepted.decision is not None
        assert isinstance(accepted.decision.intent, OrderIntent)
        assert accepted.decision.intent.time_in_force == "gtc"

    def test_cadence_pause_warmup_and_restore(self) -> None:
        """A skipped cadence pauses until missing cutoffs arrive; restore keeps warm-up state."""
        loaded = self._loaded(_ReferencePolicy(), warmup=1)
        session = CandidateSession(loaded)
        first = session.evaluate_inputs(self._inputs(_AT, 2))
        assert first.status == "warming" and first.decision is None
        paused = session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=2), 9))
        assert paused.status == "paused" and paused.reason == "input-gap"
        assert session.checkpoint() == first.checkpoint
        restored = CandidateSession(loaded, first.checkpoint)
        second = restored.evaluate_inputs(self._inputs(_AT + timedelta(seconds=1), 4))
        assert second.status == "decided"
        assert second.feature is not None
        assert second.feature.values == (ExactRatio.from_fraction(Fraction(3)),)
        with pytest.raises(ValueError, match="monotonic cadence"):
            restored.evaluate_inputs(self._inputs(_AT + timedelta(seconds=1), 4))

    def test_gap_reset_restarts_warmup_and_state(self) -> None:
        """A gap reset discards both prior feature and policy history."""
        session = CandidateSession(self._loaded(_ReferencePolicy(), on_gap="reset", warmup=1))
        assert session.evaluate_inputs(self._inputs(_AT, 2)).status == "warming"
        assert (
            session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=1), 4)).status == "decided"
        )
        reset = session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=3), 9))
        assert reset.status == "warming"
        assert reset.checkpoint.observations == 1
        assert reset.checkpoint.policy.state == b"1"
        assert reset.feature is not None
        assert reset.feature.values == (ExactRatio.from_fraction(Fraction(9)),)
        assert (
            session.evaluate_inputs(self._inputs(_AT + timedelta(seconds=4), 7)).status == "decided"
        )

    def test_checkpoint_rejects_corruption_foreign_instance_and_reset_restore(self) -> None:
        """Retained bytes, counts and placement must match before continuation."""
        loaded = self._loaded(_ReferencePolicy())
        checkpoint = CandidateSession(loaded).evaluate_inputs(self._inputs(_AT, 1)).checkpoint
        with pytest.raises(ValueError, match=r"digest|checkpoint"):
            CandidateSession(
                loaded, replace(checkpoint, policy=replace(checkpoint.policy, state=b"9"))
            )
        with pytest.raises(ValueError, match=r"digest|count"):
            CandidateSession(loaded, replace(checkpoint, observations=10))
        foreign = replace_dataclass(
            loaded, deployment=replace(loaded.deployment, instance="instance-two")
        )
        with pytest.raises(ValueError, match="another binding"):
            CandidateSession(foreign, checkpoint)
        reset_only = self._loaded(_ReferencePolicy(), on_restart="reset")
        reset_checkpoint = (
            CandidateSession(reset_only).evaluate_inputs(self._inputs(_AT, 1)).checkpoint
        )
        with pytest.raises(ValueError, match="explicit reset"):
            CandidateSession(reset_only, reset_checkpoint)

    @classmethod
    def _store(
        cls, root: Path, *, has_feature: bool, ttl_us: int = 10_000_000
    ) -> tuple[VersionedFeatureStore, FeatureStoreDefinition, str]:
        """Retain an actual SQLite snapshot and immutable source lineage."""
        schema = cls._schema(incremental=False, ttl_us=ttl_us)
        definition = FeatureStoreDefinition(
            name="runtime-reference", entity_type="instrument", schema=schema
        )
        store = VersionedFeatureStore.open(root / "features.sqlite")
        store.register(definition)
        if has_feature:
            features = FeatureSession(
                ProjectionFeature(schema), instance="instance-one", entity=_ENTITY
            )
            vector = features.evaluate(cls._inputs(_AT, 2))
            store.append(
                definition,
                StoredFeature(
                    definition_identity=definition.identity,
                    vector=vector,
                    source_version="authored-1",
                    source_sha256="a" * 64,
                    dataset_version="dataset-1",
                    dataset_sha256="b" * 64,
                    revision_identity="c" * 64,
                ),
            )
        snapshot = store.materialize(definition, "version-one", _AT, (_ENTITY,))
        store.activate(definition, snapshot.version)
        return store, definition, snapshot.identity

    def test_offline_pinned_store_value_and_missing_pause(self, tmp_path: Path) -> None:
        """Consume actual PIT bytes and pause when the pinned materialization lacks a field."""
        store, definition, identity = self._store(tmp_path / "ready", has_feature=True)
        loaded = self._loaded(
            _ReferencePolicy(),
            incremental=False,
            input_mode="offline_features",
            source_identity=identity,
            feature_version="version-one",
        )
        assert loaded.store_definition == definition
        step = CandidateFeatureFeed(store).evaluate(CandidateSession(loaded), _AT)
        assert step.status == "decided"
        assert step.feature is not None
        assert step.feature.values == (ExactRatio.from_fraction(Fraction(2)),)
        absent, _, missing_identity = self._store(tmp_path / "missing", has_feature=False)
        missing = self._loaded(
            _ReferencePolicy(),
            incremental=False,
            input_mode="offline_features",
            source_identity=missing_identity,
            feature_version="version-one",
        )
        paused = CandidateFeatureFeed(absent).evaluate(CandidateSession(missing), _AT)
        assert paused.status == "paused" and paused.reason == "missing"
        assert paused.checkpoint == CandidateSession(missing).checkpoint()

    def test_feature_feed_rejects_unbound_or_changed_deployment(self, tmp_path: Path) -> None:
        """Reject source mode, missing online access and a mismatched pinned snapshot."""
        store, _, identity = self._store(tmp_path, has_feature=True)
        feed = CandidateFeatureFeed(store)
        source = CandidateSession(self._loaded(_ReferencePolicy()))
        with pytest.raises(ValueError, match="no feature-store binding"):
            feed.evaluate(source, _AT)
        online = CandidateSession(
            self._loaded(
                _ReferencePolicy(),
                incremental=False,
                input_mode="online_features",
                source_identity=identity,
                feature_version="version-one",
            )
        )
        with pytest.raises(ValueError, match="isolated Feast bridge"):
            feed.evaluate(online, _AT)
        changed = CandidateSession(
            self._loaded(
                _ReferencePolicy(),
                incremental=False,
                input_mode="offline_features",
                source_identity="0" * 64,
                feature_version="version-one",
            )
        )
        checkpoint = changed.checkpoint()
        with pytest.raises(ValueError, match="materialization differs from pinned deployment"):
            feed.evaluate(changed, _AT)
        assert changed.checkpoint() == checkpoint

    def test_online_future_and_expired_pause_before_serving_io(self, tmp_path: Path) -> None:
        """The pinned store itself rejects a future snapshot and expired value."""
        store, _, identity = self._store(tmp_path, has_feature=True, ttl_us=1_000_000)
        worker = _NoCallWorker()
        bridge = FeastServingBridge(worker)
        future = self._loaded(
            _ReferencePolicy(),
            incremental=False,
            ttl_us=1_000_000,
            freshness_us=10_000_000,
            input_mode="online_features",
            source_identity=identity,
            feature_version="version-one",
            starts_at=_AT - timedelta(seconds=1),
        )
        feed = CandidateFeatureFeed(store, bridge=bridge, serving_root=tmp_path)
        future_step = feed.evaluate(
            CandidateSession(future),
            _AT - timedelta(seconds=1),
        )
        assert future_step.status == "paused" and future_step.reason == "future"
        expired = self._loaded(
            _ReferencePolicy(),
            incremental=False,
            ttl_us=1_000_000,
            freshness_us=10_000_000,
            input_mode="online_features",
            source_identity=identity,
            feature_version="version-one",
        )
        expired_step = feed.evaluate(CandidateSession(expired), _AT + timedelta(seconds=2))
        assert expired_step.status == "paused" and expired_step.reason == "expired"
        assert worker.calls == 0

    def test_online_materialization_age_pauses_even_when_vector_ttl_is_long(
        self, tmp_path: Path
    ) -> None:
        """The source freshness contract also bounds an otherwise ready online vector."""
        store, _, identity = self._store(tmp_path, has_feature=True, ttl_us=60_000_000)
        worker = _NoCallWorker()
        loaded = self._loaded(
            _ReferencePolicy(),
            incremental=False,
            ttl_us=60_000_000,
            input_mode="online_features",
            source_identity=identity,
            feature_version="version-one",
        )
        stale_step = CandidateFeatureFeed(
            store, bridge=FeastServingBridge(worker), serving_root=tmp_path
        ).evaluate(CandidateSession(loaded), _AT + timedelta(seconds=2))
        assert stale_step.status == "paused" and stale_step.reason == "stale"
        assert worker.calls == 0


class _LifecycleHistory(WireRecord, frozen=True):
    """Retain validated immutable callback evidence for the authored policy."""

    events: tuple[StrategyEvent, ...] = ()


class _LifecyclePolicy(_ReferencePolicy):
    """Retain callback observations in pure state so restart delivery can be asserted."""

    def __init__(
        self,
        *,
        target: Decimal = Decimal("1"),
        output: Literal["target", "order"] = "target",
    ) -> None:
        """Start with callbacks enabled, an explicit failure switch and intent."""
        super().__init__(output=output)
        self.fail_kind: str | None = None
        self.target = target

    def initial_state(self) -> bytes:
        """Start with an empty lifecycle event history."""
        return b'{"events":[]}'

    def validate_state(self, state: bytes) -> None:
        """Require strictly decoded immutable lifecycle observations."""
        DomainCodec().decode_json(state, _LifecycleHistory)

    def on_event(self, event: StrategyEvent, state: bytes) -> bytes:
        """Append the supplied immutable event without keeping hidden economic state."""
        if event.kind == self.fail_kind:
            raise ValueError("authored callback failure")
        events = DomainCodec().decode_json(state, _LifecycleHistory).events
        return DomainCodec().encode_json(_LifecycleHistory(events=(*events, event)))

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Request the configured target regardless of callback history."""
        context.__post_init__()
        self.validate_state(state)
        quantity = Quantity(
            value=self.target,
            dimension=Dimension(instrument_id=_INSTRUMENT, kind=QuantityKind.BASE_UNIT),
        )
        intent: DecisionIntent
        if self.output == "order":
            intent = OrderIntent(
                side="buy",
                quantity=quantity,
                limit=Price(
                    value=Decimal("100"),
                    currency=Currency.from_code("USD"),
                    per=quantity.dimension,
                ),
                time_in_force="gtc",
            )
        else:
            intent = TargetIntent(quantity=quantity)
        return DecisionTransition(
            intent=intent,
            state=state,
        )


class TestPaperCandidateRuntime:
    """Check the connected candidate, paper matching, account and durable callback boundaries."""

    @staticmethod
    def _runtime(
        path: Path,
        *,
        mode: Literal["paper", "shadow"] = "paper",
        policy: _LifecyclePolicy | None = None,
    ) -> PaperCandidateRuntime:
        """Bind independent source inputs and a funded single-instrument account."""
        source = NumericHistorySource(
            tuple(
                TestCandidateSession._inputs(_AT + timedelta(seconds=i), 1).observations[0]
                for i in range(4)
            ),
            (_INPUT,),
        )
        loaded = TestCandidateSession._loaded(
            policy or _LifecyclePolicy(),
            source_identity=source.identity,
            on_gap="reset",
        )
        dimension = Dimension(instrument_id=_INSTRUMENT, kind=QuantityKind.BASE_UNIT)
        currency = Currency.from_code("USD")
        config = PaperConfiguration(
            account="dedicated",
            mode=mode,
            initial_cash=Money(value=Decimal("1000"), currency=currency),
            maximum=Quantity(value=Decimal("10"), dimension=dimension),
            lot=Quantity(value=Decimal("1"), dimension=dimension),
            tick=Price(value=Decimal("1"), currency=currency, per=dimension),
            maximum_fee=Money(value=Decimal("0"), currency=currency),
            fee_rate=Decimal("0"),
            market_max_age_us=1_000_000,
            execution=PaperExecutionScenario(
                venue="bitfinex",
                instrument_id=_INSTRUMENT,
                entry_delay_us=0,
                cancel_delay_us=0,
                adverse=Price(value=Decimal("0"), currency=currency, per=dimension),
                fee_rate=Decimal("0"),
                take_fraction=Decimal("1"),
                gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
            ),
        )
        journal = PaperOrderJournal(
            path,
            account=config.account,
            instance=loaded.deployment.instance,
            binding_identity=PaperCandidateRuntime.binding(loaded, config),
            mode=mode,
            limits=SpotLimits(
                maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"
            ),
            ledger_state=LedgerState(initial_cash=config.initial_cash, dimension=dimension),
            fee_rate=Decimal(0),
        )
        return PaperCandidateRuntime(loaded, config, journal, source=source)

    @staticmethod
    def _market(runtime: PaperCandidateRuntime, second: int) -> PaperMarket:
        """Author one-unit touch liquidity at 99/100 with original availability."""
        return PaperMarket(
            identity=f"quote-{second}",
            at=_AT + timedelta(seconds=second),
            bid=Price(
                value=Decimal("99"),
                currency=runtime.config.tick.currency,
                per=runtime.config.maximum.dimension,
            ),
            ask=Price(
                value=Decimal("100"),
                currency=runtime.config.tick.currency,
                per=runtime.config.maximum.dimension,
            ),
            bid_quantity=runtime.config.lot,
            ask_quantity=runtime.config.lot,
        )

    def _live_fixture(
        self, tmp_path: Path
    ) -> tuple[LoadedCandidate, CaptureRequest, PaperConfiguration]:
        """Bind a native book request to a fixture candidate without network I/O."""
        config = self._runtime(tmp_path / "template.sqlite3").config
        capture = replace(
            CaptureConfig.read(Path(__file__).parents[3] / "configs/live/bitfinex-btc-usd.json"),
            instrument_id=_INSTRUMENT,
        )
        request = CaptureRequest(
            config=capture, recording_id="a" * 36, implementation_identity="b" * 64
        )
        book_input = InputRequirement(
            name="book",
            family="book",
            clock="receipt",
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=1_000_000,
        )
        source_identity = LiveBookDecisionSource(
            request, (book_input,), history_capacity=8
        ).identity
        loaded = TestCandidateSession._loaded(_LifecyclePolicy(), source_identity=source_identity)
        requirement: CapabilityRequirement = replace(
            loaded.definition.requirements[0],
            name="book",
            channel=capture.channel,
            clock="receipt",
            fields=(CapabilityField(name="imbalance", units="dimensionless"),),
        )
        requirements: list[CapabilityRequirement] = [requirement]
        requirements.extend(loaded.definition.requirements[1:])
        selected_requirements: tuple[CapabilityRequirement, ...] = tuple(requirements)
        executable = replace(
            loaded.definition,
            inputs=(book_input,),
            requirements=selected_requirements,
        )
        deployment = replace(
            loaded.deployment,
            mode="runtime",
            candidate_identity=executable.identity,
            source_identity=source_identity,
        )
        return (
            replace_dataclass(loaded, definition=executable, deployment=deployment),
            request,
            config,
        )

    def test_paper_observer_rejects_misbound_registry_reference(self, tmp_path: Path) -> None:
        """Matching source IDs cannot conceal a different product or native listing."""
        runtime = self._runtime(tmp_path / "reference.sqlite3")
        capture = replace(
            CaptureConfig.read(Path(__file__).parents[3] / "configs/live/bitfinex-btc-usd.json"),
            instrument_id=_INSTRUMENT,
        )
        request = CaptureRequest(
            config=capture, recording_id="a" * 36, implementation_identity="b" * 64
        )
        source = LiveBookDecisionSource(
            request,
            (
                InputRequirement(
                    name="book",
                    family="book",
                    clock="receipt",
                    field=NumericField(name="imbalance", units="dimensionless"),
                    max_age_us=1_000_000,
                ),
            ),
            history_capacity=8,
        )
        selected = BookSelection.from_capture(
            capture,
            source_id=request.identity,
            capability=BookAdapters.capability(capture),
            max_age_ns=1_000_000_000,
            allow_degraded=True,
        )
        books = BookRegistry(
            BookRegistryConfiguration(selections=(selected,), equivalences=(), history_capacity=8)
        )
        PaperCaptureObserver(source, runtime, books=books)
        invalid_selections = (
            replace(selected, instrument=replace(selected.instrument, symbol="tETHUSD")),
            replace(
                selected,
                instrument=replace(selected.instrument, product="future"),
                capability=replace(selected.capability, product="future"),
            ),
        )
        for invalid in invalid_selections:
            misbound = BookRegistry(
                BookRegistryConfiguration(
                    selections=(invalid,), equivalences=(), history_capacity=8
                )
            )
            with pytest.raises(ValueError, match="selected native venue and units"):
                PaperCaptureObserver(source, runtime, books=misbound)

    def test_scheduler_rejects_regressed_utc_clock(self, tmp_path: Path) -> None:
        """A backward wall clock exits visibly before a cadence decision."""
        loaded, request, _ = self._live_fixture(tmp_path)
        runtime = self._runtime(tmp_path / "clock.sqlite3")
        source = LiveBookDecisionSource(request, loaded.definition.inputs, history_capacity=8)
        selected = BookSelection.from_capture(
            request.config,
            source_id=request.identity,
            capability=BookAdapters.capability(request.config),
            max_age_ns=1_000_000_000,
            allow_degraded=True,
        )
        books = BookRegistry(
            BookRegistryConfiguration(selections=(selected,), equivalences=(), history_capacity=8)
        )
        observer = PaperCaptureObserver(source, runtime, books=books)
        _RegressingUTCClock.reads = 0
        with (
            patch("runtime.live_paper.datetime", _RegressingUTCClock),
            pytest.raises(ValueError, match="UTC clock regressed"),
        ):
            asyncio.run(observer.timers(asyncio.Event()))

    def test_paper_observer_revalidates_private_wire_before_input_retention(
        self, tmp_path: Path
    ) -> None:
        """Unsafe nested books cannot enter the dedicated runtime's durable input journal."""
        loaded, request, _ = self._live_fixture(tmp_path)
        runtime = self._runtime(tmp_path / "untrusted.sqlite3")
        source = LiveBookDecisionSource(request, loaded.definition.inputs, history_capacity=8)
        selected = BookSelection.from_capture(
            request.config,
            source_id=request.identity,
            capability=BookAdapters.capability(request.config),
            max_age_ns=1_000_000_000,
            allow_degraded=True,
        )
        books = BookRegistry(
            BookRegistryConfiguration(selections=(selected,), equivalences=(), history_capacity=8)
        )
        observer = PaperCaptureObserver(source, runtime, books=books)
        received_ns = int(_AT.timestamp()) * 1_000_000_000
        delivery = ObservedLiveBookDelivery(
            record=CaptureRecord(kind="session", epoch=0, received_ns=received_ns),
            book=BookObservation(
                position=0,
                epoch=0,
                received_ns=received_ns,
                source_time=None,
                sequence=None,
                outcome="session",
                status="recovering",
                reason="new",
                state_identity="1" * 64,
            ),
            available_at=_AT + timedelta(seconds=1),
        )
        runtime.open(owner="first", at=_AT)
        try:
            prior_steps, prior_checkpoint = runtime.journal.steps(), runtime.checkpoint()
            force_setattr(delivery.book, "state_identity", "bad")
            with pytest.raises(ValueError, match="book state or quality"):
                observer.deliver(delivery)
            assert runtime.journal.steps() == prior_steps
            assert runtime.checkpoint() == prior_checkpoint
            assert source.latest_book is None
        finally:
            runtime.release()

    def test_paper_shadow_parity_and_restart(self, tmp_path: Path) -> None:
        """Keep decisions identical while only paper posts a single exact modeled fill."""
        intents: list[DecisionIntent] = []
        for mode in ("paper", "shadow"):
            runtime = self._runtime(tmp_path / f"{mode}.sqlite3", mode=mode)
            runtime.open(owner="first", at=_AT)
            runtime.market(self._market(runtime, 0))
            step, admitted = runtime.timer(identity="first", at=_AT)
            assert step.decision is not None and admitted.status == "committed"
            intents.append(step.decision.intent)
            assert runtime.timer(identity="first", at=_AT) == (step, admitted)
            assert len(runtime.journal.orders()) == 1
            runtime.market(self._market(runtime, 1))
            runtime.release()
            restored = self._runtime(tmp_path / f"{mode}.sqlite3", mode=mode)
            restored.open(owner="restarted", at=_AT + timedelta(seconds=1))
            restored.market(self._market(restored, 1))
            balance = Ledger(restored.journal.ledger_state()).balance
            assert balance.cash.value == (Decimal("900") if mode == "paper" else Decimal("1000"))
            assert balance.holding.value == (Decimal("1") if mode == "paper" else Decimal("0"))
            callbacks = (
                DomainCodec()
                .decode_json(restored.checkpoint().candidate.policy.state, _LifecycleHistory)
                .events
            )
            assert sum(e.kind == "timer" for e in callbacks) == 1
            assert sum(e.kind == "recovery" for e in callbacks) == 1
            assert sum(e.kind == "account" for e in callbacks) == (1 if mode == "paper" else 0)
            restored.release()
        assert intents[0] == intents[1]

    def test_stale_clock_account_break_and_callback_failure(self, tmp_path: Path) -> None:
        """Keep hard safety state effective even when strategy callbacks fail."""
        policy = _LifecyclePolicy()
        runtime = self._runtime(tmp_path / "runtime.sqlite3", policy=policy)
        runtime.open(owner="test", at=_AT)
        runtime.market(self._market(runtime, 0))
        paused, _ = runtime.timer(identity="stale", at=_AT + timedelta(seconds=2))
        assert paused.reason == "market-unavailable"
        assert not runtime.journal.orders()
        with pytest.raises(ValueError, match="clock regressed"):
            runtime.market(self._market(runtime, 1))
        balance = Ledger(runtime.journal.ledger_state()).balance
        assert not runtime.reconcile(
            identity="break",
            at=_AT + timedelta(seconds=2),
            cash=Money(value=Decimal("999"), currency=balance.cash.currency),
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.journal.blocked_reason() == "account_break"
        assert runtime.reconcile(
            identity="correct",
            at=_AT + timedelta(seconds=2),
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.journal.blocked_reason() is None
        policy.fail_kind = "fault"
        with pytest.raises(ValueError, match="callback failure"):
            runtime.block(
                identity="independent", at=_AT + timedelta(seconds=2), reason="operator-block"
            )
        assert runtime.checkpoint().blocked == "operator-block"
        runtime.release()

    @pytest.mark.performance
    def test_restart_adds_one_step_read_per_retained_quote(self, tmp_path: Path) -> None:
        """Each retained quote adds about one step decode to a restart, not a lookup of its own."""
        restarts: list[float] = []
        reads: list[float] = []
        for count in (50, 200):
            path = tmp_path / f"{count}.sqlite3"
            runtime = self._runtime(path)
            runtime.open(owner="first", at=_AT)
            for second in range(count):
                runtime.market(self._market(runtime, second))
            runtime.release()
            restart_samples: list[float] = []
            read_samples: list[float] = []
            for attempt in range(5):
                restored = self._runtime(path)
                started = time.perf_counter()
                restored.open(owner=f"restart-{attempt}", at=_AT + timedelta(seconds=count))
                restart_samples.append(time.perf_counter() - started)
                started = time.perf_counter()
                restored.journal.steps()
                read_samples.append(time.perf_counter() - started)
                restored.release()
            restarts.append(sorted(restart_samples)[2])
            reads.append(sorted(read_samples)[2])
        print(
            f"restart at 50/200 quotes: {restarts[0]:.6f}s/{restarts[1]:.6f}s; "
            f"reading every step: {reads[0]:.6f}s/{reads[1]:.6f}s"
        )
        # A connection and query per retained quote made this about 5.6 here.
        assert restarts[1] - restarts[0] < 2.5 * (reads[1] - reads[0])

    def test_interrupted_market_finishes_before_recovery_advances_clock(
        self, tmp_path: Path
    ) -> None:
        """Restore a quote with posted fills but no completed callbacks without double effects."""
        policy = _LifecyclePolicy()
        path = tmp_path / "interrupted.sqlite3"
        runtime = self._runtime(path, policy=policy)
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.timer(identity="intent", at=_AT)
        policy.fail_kind = "order"
        with pytest.raises(ValueError, match="callback failure"):
            runtime.market(self._market(runtime, 1))
        assert len(runtime.journal.ledger_state().fills) == 1
        assert runtime.journal.step("market:quote-1") is None
        runtime.release()

        restored = self._runtime(path)
        restored.open(owner="recovered", at=_AT + timedelta(seconds=3))
        assert restored.journal.step("market:quote-1") is not None
        assert len(restored.journal.ledger_state().fills) == 1
        balance = Ledger(restored.journal.ledger_state()).balance
        assert balance.cash.value == Decimal("900")
        assert balance.holding.value == Decimal("1")
        callbacks = (
            DomainCodec()
            .decode_json(restored.checkpoint().candidate.policy.state, _LifecycleHistory)
            .events
        )
        assert sum(event.kind == "account" for event in callbacks) == 1
        account = next(event for event in callbacks if event.kind == "account")
        assert account.at == _AT + timedelta(seconds=1)
        assert callbacks[-1].kind == "recovery"
        assert callbacks[-1].at == _AT + timedelta(seconds=3)
        restored.market(self._market(restored, 1))
        assert len(restored.journal.ledger_state().fills) == 1
        restored.release()

    def test_reconciliation_cannot_clear_operator_stop(self, tmp_path: Path) -> None:
        """Both mismatching and matching account observations preserve an independent stop."""
        runtime = self._runtime(tmp_path / "stopped.sqlite3")
        runtime.open(owner="operator", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.stop(identity="stop", at=_AT)
        balance = Ledger(runtime.journal.ledger_state()).balance
        assert not runtime.reconcile(
            identity="mismatch",
            at=_AT,
            cash=Money(value=Decimal("999"), currency=balance.cash.currency),
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.checkpoint().blocked == "operator-stop"
        assert runtime.reconcile(
            identity="matched",
            at=_AT,
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.checkpoint().blocked == "operator-stop"
        step, _ = runtime.timer(identity="still-stopped", at=_AT)
        assert step.reason == "operator-stop"
        assert not runtime.journal.orders()
        runtime.release()

    def test_fault_clamps_callback_clock_and_survives_reopen(self, tmp_path: Path) -> None:
        """A delayed fault blocks durably without delivering a regressed policy event."""
        path = tmp_path / "fault.sqlite3"
        runtime = self._runtime(path)
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.timer(identity="later", at=_AT + timedelta(seconds=2))
        runtime.fault(
            identity="capture", at=_AT + timedelta(seconds=1), reason="capture-disconnected"
        )
        assert runtime.checkpoint().blocked == "capture-disconnected"
        events = (
            DomainCodec()
            .decode_json(runtime.checkpoint().candidate.policy.state, _LifecycleHistory)
            .events
        )
        assert events[-1].kind == "fault"
        assert events[-1].at == _AT + timedelta(seconds=2)
        guard = runtime.journal.step("guard:fault:capture")
        assert guard is not None
        evidence = DomainCodec().decode_json(guard.input_bytes, PaperFaultEvidence)
        assert evidence.event == events[-1]
        assert evidence.observed_at == _AT + timedelta(seconds=1)
        runtime.release()

        restored = self._runtime(path)
        restored.open(owner="second", at=_AT + timedelta(seconds=2))
        assert restored.checkpoint().blocked == "capture-disconnected"
        paused, _ = restored.timer(identity="blocked", at=_AT + timedelta(seconds=3))
        assert paused.reason == "capture-disconnected"
        assert not restored.journal.orders()
        restored.release()

    def test_fault_guard_does_not_replay_callback_against_later_state(self, tmp_path: Path) -> None:
        """A failing fault callback leaves a hard block and an idempotent old fault."""
        policy = _LifecyclePolicy()
        runtime = self._runtime(tmp_path / "fault-callback.sqlite3", policy=policy)
        runtime.open(owner="first", at=_AT)
        policy.fail_kind = "fault"
        with pytest.raises(ValueError, match="callback failure"):
            runtime.fault(identity="failure", at=_AT, reason="feed-failed")
        assert runtime.checkpoint().blocked == "feed-failed"
        runtime.timer(identity="later", at=_AT + timedelta(seconds=1))
        policy.fail_kind = None
        runtime.fault(identity="failure", at=_AT, reason="feed-failed")
        events = (
            DomainCodec()
            .decode_json(runtime.checkpoint().candidate.policy.state, _LifecycleHistory)
            .events
        )
        assert all(event.kind != "fault" for event in events)
        with pytest.raises(ValueError, match="another reason"):
            runtime.fault(identity="failure", at=_AT, reason="different-failure")
        runtime.release()

    def test_fault_keeps_interrupted_quote_replayable(self, tmp_path: Path) -> None:
        """Hard fault persistence does not advance past a claimed quote and its fill."""
        policy = _LifecyclePolicy()
        path = tmp_path / "interrupted-fault.sqlite3"
        runtime = self._runtime(path, policy=policy)
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.timer(identity="intent", at=_AT)
        policy.fail_kind = "order"
        with pytest.raises(ValueError, match="callback failure"):
            runtime.market(self._market(runtime, 1))
        policy.fail_kind = None
        runtime.fault(
            identity="capture",
            at=_AT + timedelta(seconds=3),
            reason="capture-interrupted",
        )
        assert runtime.checkpoint().last_at == _AT
        assert runtime.checkpoint().blocked == "capture-interrupted"
        runtime.release()

        restored = self._runtime(path)
        restored.open(owner="second", at=_AT + timedelta(seconds=3))
        assert restored.journal.step("market:quote-1") is not None
        assert len(restored.journal.ledger_state().fills) == 1
        assert restored.checkpoint().blocked == "capture-interrupted"
        restored.release()

    def test_resume_requires_exact_block_fresh_reconciliation_and_known_orders(
        self, tmp_path: Path
    ) -> None:
        """Resume accepts a matched account and retains identified open reservations."""
        path = tmp_path / "resume.sqlite3"
        runtime = self._runtime(path)
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        step, _ = runtime.timer(identity="intent", at=_AT)
        assert step.decision is not None
        order = runtime.journal.orders()[0]
        runtime.stop(identity="operator", at=_AT)
        stopped = runtime.checkpoint()
        balance = Ledger(runtime.journal.ledger_state()).balance
        with pytest.raises(ValueError, match="unresolved order outcome"):
            runtime.resume(
                identity="too-early",
                at=_AT + timedelta(seconds=1),
                expected_checkpoint=stopped,
                cash=balance.cash,
                holding=balance.holding,
                open_order_ids=(order.identity,),
            )
        assert runtime.checkpoint() == stopped
        runtime.order(
            OrderEvent(identity="accepted", order_id=order.identity, at=_AT, kind="accepted")
        )
        observed = runtime.checkpoint()
        with pytest.raises(ValueError, match="expected checkpoint differs"):
            runtime.resume(
                identity="stale",
                at=_AT + timedelta(seconds=1),
                expected_checkpoint=stopped,
                cash=balance.cash,
                holding=balance.holding,
                open_order_ids=(order.identity,),
            )
        with pytest.raises(ValueError, match="fresh reconciliation clock"):
            runtime.resume(
                identity="old-observation",
                at=observed.last_at,
                expected_checkpoint=observed,
                cash=balance.cash,
                holding=balance.holding,
                open_order_ids=(order.identity,),
            )
        assert not runtime.resume(
            identity="wrong-account",
            at=_AT + timedelta(seconds=1),
            expected_checkpoint=observed,
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.checkpoint().blocked == "operator-stop"
        mismatched = runtime.checkpoint()
        assert runtime.journal.blocked_reason() == "account_break"
        assert runtime.resume(
            identity="matched-account",
            at=_AT + timedelta(seconds=2),
            expected_checkpoint=mismatched,
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(order.identity,),
        )
        assert runtime.checkpoint().blocked is None
        assert runtime.journal.blocked_reason() is None
        runtime.release()

        restored = self._runtime(path)
        restored.open(owner="second", at=_AT + timedelta(seconds=2))
        assert restored.checkpoint().blocked is None
        assert restored.journal.orders()[0].identity == order.identity
        restored.release()

    def test_fault_persistence_failure_is_visible(self, tmp_path: Path) -> None:
        """A failed checkpoint write cannot be reported as a successful hard stop."""
        runtime = self._runtime(tmp_path / "unwritable-fault.sqlite3")
        runtime.open(owner="first", at=_AT)
        before = runtime.checkpoint()
        with patch.object(runtime.journal, "commit_step", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                runtime.fault(identity="disk", at=_AT, reason="capture-failed")
        assert runtime.checkpoint() == before
        runtime.release()

    def test_resume_waits_for_unknown_order_reconciliation(self, tmp_path: Path) -> None:
        """An unknown outcome must be resolved by an identified order fact first."""
        runtime = self._runtime(tmp_path / "unknown-resume.sqlite3")
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.timer(identity="intent", at=_AT)
        order = runtime.journal.orders()[0]
        runtime.stop(identity="operator", at=_AT)
        runtime.order(
            OrderEvent(identity="unknown", order_id=order.identity, at=_AT, kind="unknown")
        )
        balance = Ledger(runtime.journal.ledger_state()).balance
        with pytest.raises(ValueError, match="unresolved order outcome"):
            runtime.resume(
                identity="uncertain",
                at=_AT + timedelta(seconds=1),
                expected_checkpoint=runtime.checkpoint(),
                cash=balance.cash,
                holding=balance.holding,
                open_order_ids=(order.identity,),
            )
        runtime.order(
            OrderEvent(
                identity="reconciled-open", order_id=order.identity, at=_AT, kind="reconcile_open"
            )
        )
        assert runtime.resume(
            identity="resolved",
            at=_AT + timedelta(seconds=1),
            expected_checkpoint=runtime.checkpoint(),
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(order.identity,),
        )
        assert runtime.checkpoint().blocked is None
        runtime.release()

    def test_resume_waits_for_cancel_fill_race_resolution(self, tmp_path: Path) -> None:
        """A partial fill cannot hide a pending cancel behind an open status."""
        runtime = self._runtime(
            tmp_path / "cancel-race.sqlite3",
            policy=_LifecyclePolicy(target=Decimal("2"), output="order"),
        )
        runtime.open(owner="first", at=_AT)
        runtime.market(self._market(runtime, 0))
        runtime.timer(identity="order", at=_AT)
        runtime.market(self._market(runtime, 1))
        partially_filled = runtime.journal.orders()[0]
        assert partially_filled.status == "partial"
        assert partially_filled.filled.value == Decimal("1")
        runtime.stop(identity="operator", at=_AT + timedelta(seconds=1))
        runtime.cancel(
            identity="cancel",
            order_id=partially_filled.identity,
            at=_AT + timedelta(seconds=1),
        )
        pending = runtime.journal.orders()[0]
        assert pending.cancel_requested and not pending.is_terminal
        balance = Ledger(runtime.journal.ledger_state()).balance
        with (
            patch.object(
                runtime.journal, "orders", return_value=(replace(pending, status="partial"),)
            ),
            pytest.raises(ValueError, match="unresolved order outcome"),
        ):
            runtime.resume(
                identity="masked-cancel",
                at=_AT + timedelta(seconds=2),
                expected_checkpoint=runtime.checkpoint(),
                cash=balance.cash,
                holding=balance.holding,
                open_order_ids=(pending.identity,),
            )
        runtime.order(
            OrderEvent(
                identity="cancelled",
                order_id=pending.identity,
                at=_AT + timedelta(seconds=1),
                kind="cancelled",
            )
        )
        assert runtime.resume(
            identity="resolved-cancel",
            at=_AT + timedelta(seconds=2),
            expected_checkpoint=runtime.checkpoint(),
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.checkpoint().blocked is None
        runtime.release()

    def test_live_capture_faults_block_before_fence_release(self, tmp_path: Path) -> None:
        """Raised protocol faults and completed disconnects survive a new owner."""
        loaded, request, config = self._live_fixture(tmp_path)
        for runner_type in (_MalformedCaptureRunner, _DisconnectedCaptureRunner):
            path = tmp_path / f"{runner_type.__name__}.sqlite3"
            with (
                patch.object(CandidateLoader, "load", return_value=loaded),
                patch("applications.paper.workflow.CaptureRunner", runner_type),
                pytest.raises(BaseException) as raised,
            ):
                asyncio.run(
                    run_live_paper(
                        CandidateBundle(tmp_path / "unused"),
                        loaded.deployment,
                        config,
                        components=CandidateComponents(features={}, policies={}),
                        registry=CapabilityRegistry(()),
                        request=request,
                        capture_output=tmp_path / "capture",
                        journal_path=path,
                        owner="capture-owner",
                        history_capacity=8,
                    )
                )
            if runner_type is _MalformedCaptureRunner:
                assert isinstance(raised.value, ExceptionGroup)
                assert "malformed capture frame" in str(raised.value.exceptions[0])
            else:
                assert isinstance(raised.value, ValueError)
                assert "without a healthy book" in str(raised.value)
            journal = PaperOrderJournal(
                path,
                account=config.account,
                instance=loaded.deployment.instance,
                binding_identity=PaperCandidateRuntime.binding(loaded, config),
                mode=config.mode,
                limits=SpotLimits(
                    maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"
                ),
                ledger_state=LedgerState(
                    initial_cash=config.initial_cash, dimension=config.maximum.dimension
                ),
                fee_rate=Decimal(0),
            )
            source = LiveBookDecisionSource(request, loaded.definition.inputs, history_capacity=8)
            restored = PaperCandidateRuntime(loaded, config, journal, source=source)
            restored.open(owner="inspector", at=datetime.now(UTC) + timedelta(seconds=1))
            assert restored.checkpoint().blocked == "live-paper-failure:ValueError"
            restored.release()

    def test_live_fault_persistence_failure_preserves_capture_cause(self, tmp_path: Path) -> None:
        """A failed hard-block write annotates rather than replaces the protocol fault."""
        loaded, request, config = self._live_fixture(tmp_path)
        with (
            patch.object(CandidateLoader, "load", return_value=loaded),
            patch("applications.paper.workflow.CaptureRunner", _MalformedCaptureRunner),
            patch.object(PaperCandidateRuntime, "fault", side_effect=OSError("disk full")),
            pytest.raises(ExceptionGroup) as raised,
        ):
            asyncio.run(
                run_live_paper(
                    CandidateBundle(tmp_path / "unused"),
                    loaded.deployment,
                    config,
                    components=CandidateComponents(features={}, policies={}),
                    registry=CapabilityRegistry(()),
                    request=request,
                    capture_output=tmp_path / "capture",
                    journal_path=tmp_path / "persistence.sqlite3",
                    owner="capture-owner",
                    history_capacity=8,
                )
            )
        assert "malformed capture frame" in str(raised.value.exceptions[0])
        assert any("paper fault handling also failed" in note for note in raised.value.__notes__)

    def test_second_live_failure_after_resume_records_a_new_fault(self, tmp_path: Path) -> None:
        """The same capture request cannot reuse a cleared prior run's fault guard."""
        loaded, request, config = self._live_fixture(tmp_path)
        path = tmp_path / "repeated-live.sqlite3"
        bundle = CandidateBundle(tmp_path / "unused")
        components = CandidateComponents(features={}, policies={})
        registry = CapabilityRegistry(())
        with (
            patch.object(CandidateLoader, "load", return_value=loaded),
            patch("applications.paper.workflow.CaptureRunner", _MalformedCaptureRunner),
            pytest.raises(ExceptionGroup, match="unhandled errors") as first,
        ):
            asyncio.run(
                run_live_paper(
                    bundle,
                    loaded.deployment,
                    config,
                    components=components,
                    registry=registry,
                    request=request,
                    capture_output=tmp_path / "capture",
                    journal_path=path,
                    owner="same-owner",
                    history_capacity=8,
                )
            )
        assert "malformed capture frame" in str(first.value.exceptions[0])
        journal = PaperOrderJournal(
            path,
            account=config.account,
            instance=loaded.deployment.instance,
            binding_identity=PaperCandidateRuntime.binding(loaded, config),
            mode=config.mode,
            limits=SpotLimits(
                maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"
            ),
            ledger_state=LedgerState(
                initial_cash=config.initial_cash, dimension=config.maximum.dimension
            ),
            fee_rate=Decimal(0),
        )
        source = LiveBookDecisionSource(request, loaded.definition.inputs, history_capacity=8)
        runtime = PaperCandidateRuntime(loaded, config, journal, source=source)
        runtime.open(owner="operator", at=datetime.now(UTC))
        blocked = runtime.checkpoint()
        assert blocked.blocked == "live-paper-failure:ValueError"
        balance = Ledger(journal.ledger_state()).balance
        assert runtime.resume(
            identity="operator-resume",
            at=max(datetime.now(UTC), blocked.last_at + timedelta(microseconds=1)),
            expected_checkpoint=blocked,
            cash=balance.cash,
            holding=balance.holding,
            open_order_ids=(),
        )
        assert runtime.checkpoint().blocked is None
        runtime.release()
        with (
            patch.object(CandidateLoader, "load", return_value=loaded),
            patch("applications.paper.workflow.CaptureRunner", _MalformedCaptureRunner),
            pytest.raises(ExceptionGroup, match="unhandled errors") as second,
        ):
            asyncio.run(
                run_live_paper(
                    bundle,
                    loaded.deployment,
                    config,
                    components=components,
                    registry=registry,
                    request=request,
                    capture_output=tmp_path / "capture",
                    journal_path=path,
                    owner="same-owner",
                    history_capacity=8,
                )
            )
        assert "malformed capture frame" in str(second.value.exceptions[0])
        saved = journal.checkpoint()
        assert saved is not None
        assert DomainCodec().decode_json(saved, PaperCheckpoint).blocked == (
            "live-paper-failure:ValueError"
        )
        guards = [
            step.step_id for step in journal.steps() if step.step_id.startswith("guard:fault:")
        ]
        assert len(guards) == 2 and len(set(guards)) == 2
