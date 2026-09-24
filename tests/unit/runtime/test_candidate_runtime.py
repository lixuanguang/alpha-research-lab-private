"""Exercise candidate state, temporal admission and persisted feature consumption."""

from __future__ import annotations

# standard library imports
import hashlib
from dataclasses import replace as replace_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import UUID

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.explore import run_candidate_feature
from configuration import (
    CandidateDeployment,
    CapabilityField,
    CapabilityKind,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    UniverseSelection,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import (
    CandidateArtifact,
    CandidateComponent,
    CandidateManifest,
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
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from runtime import CandidateSession, LoadedCandidate
from strategies import (
    DecisionContext,
    DecisionIntent,
    DecisionTransition,
    ExposureIntent,
    OrderIntent,
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
        return f"reference-{self._output}-v1"

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
            implementation="running-mean-v1" if incremental else "named-projection-v1",
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
                "dataset",
                "experiment",
                "attempt",
                "report",
                "schema",
                "feature-parameters",
                "policy-parameters",
                "metric-parameters",
                "chart-parameters",
            )
        )

    @classmethod
    def _manifest(
        cls,
        *,
        output: Literal["target", "order"] = "target",
        on_gap: Literal["pause", "reset"] = "pause",
        warmup: int = 0,
        on_restart: Literal["restore", "reset"] = "restore",
        incremental: bool = True,
        freshness_us: int = 1_000_000,
    ) -> CandidateManifest:
        """Build a complete engineering manifest with no empirical authority."""
        artifacts = {item.name: item for item in cls._artifacts()}
        components = tuple(
            CandidateComponent(
                role=role,
                factory_key=f"reference-{role}",
                identity=f"reference-{role}-v1",
                implementation_sha256=_CODE,
                parameters=artifacts[f"{role}-parameters"],
            )
            for role in ("feature", "policy", "metric", "chart")
        )
        return CandidateManifest(
            name="runtime-reference",
            version="1",
            qualification="engineering",
            code_sha256=_CODE,
            environment_sha256=_CODE,
            dataset=artifacts["dataset"],
            experiment=artifacts["experiment"],
            attempt=artifacts["attempt"],
            report=artifacts["report"],
            feature_schema=artifacts["schema"],
            feature_store=None,
            transform=None,
            estimator=None,
            assessment=None,
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
                checkpoint_schema="candidate-checkpoint-v1" if on_restart == "restore" else None,
                on_gap=on_gap,
                on_restart=on_restart,
                policy_state_schema="reference-policy-state-v1",
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
            limitations=("Synthetic software session; no venue evidence.",),
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
        on_gap: Literal["pause", "reset"] = "pause",
        warmup: int = 0,
        on_restart: Literal["restore", "reset"] = "restore",
        incremental: bool = True,
        ttl_us: int = 10_000_000,
        freshness_us: int = 1_000_000,
        input_mode: Literal["source", "offline_features", "online_features"] = "source",
        source_identity: str = "authored-source-v1",
        feature_version: str | None = None,
        starts_at: datetime = _AT,
    ) -> LoadedCandidate:
        """Compose the actual session objects and resolved fixture signatures."""
        manifest = cls._manifest(
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
            candidate_identity=manifest.identity,
            instance="instance-one",
            entity=_ENTITY,
            mode=mode,
            input_mode=input_mode,
            source_identity=source_identity,
            starts_at=starts_at,
            selections=cls._bindings(manifest.requirements),
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
                implementation_identity=f"installed-{r.kind}-v1",
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
            for r in manifest.requirements
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
            manifest=manifest,
            deployment=deployment,
            capabilities=CapabilityRegistry(profiles).resolve(
                manifest.requirements, deployment.selections, mode=mode
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
        step = run_candidate_feature(CandidateSession(loaded), store, at=_AT)
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
        paused = run_candidate_feature(CandidateSession(missing), absent, at=_AT)
        assert paused.status == "paused" and paused.reason == "missing"
        assert paused.checkpoint == CandidateSession(missing).checkpoint()

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
        future_step = run_candidate_feature(
            CandidateSession(future),
            store,
            at=_AT - timedelta(seconds=1),
            bridge=bridge,
            serving_root=tmp_path,
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
        expired_step = run_candidate_feature(
            CandidateSession(expired),
            store,
            at=_AT + timedelta(seconds=2),
            bridge=bridge,
            serving_root=tmp_path,
        )
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
        stale_step = run_candidate_feature(
            CandidateSession(loaded),
            store,
            at=_AT + timedelta(seconds=2),
            bridge=FeastServingBridge(worker),
            serving_root=tmp_path,
        )
        assert stale_step.status == "paused" and stale_step.reason == "stale"
        assert worker.calls == 0
