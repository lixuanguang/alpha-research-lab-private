"""Verify packaged candidates load from signed bundles and installed extensions only."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast
from uuid import uuid4

# third party library imports
import pytest
from engineering_candidates import FoldNetChart, FoldNetMetric, ImbalanceTarget
from msgspec.structs import replace

# project library imports
from accounting import Fill
from applications.execute import FeaturePublisher
from applications.execute.candidate_telemetry import CandidateTelemetry
from applications.execute.service_candidates import PaperServiceCandidates
from applications.execute.service_monitor import InspectedPaperAccount
from configuration import (
    AccountConfiguration,
    CapabilityField,
    CapabilityKind,
    CapabilityRequirement,
    CaptureConfig,
    OpeningAccount,
    PackagedCandidate,
    PaperExecutionScenario,
    PaperFeaturePublisher,
    PaperFeatureServing,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    ReferenceCandidate,
)
from configuration.accounts import InstrumentFeeRate
from execution import AccountExecutionResult, AccountPaperFill, PaperMarket, PaperOwner
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.contracts import CaptureRequest
from market_data.storage import CaptureJournal
from research.experiments import AttemptStore, ExperimentSpec, Fingerprint, TimeWindow
from research.experiments.candidates import (
    CandidateArtifact,
    CandidateBundle,
    CandidateComponent,
    CandidateDefinition,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
)
from research.features import FeatureSchema, FeatureStoreDefinition, VersionedFeatureStore
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from research.studies import ResultManifest
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    CandidateEvidence,
    CandidateMonitoringExporter,
    CandidateRuntime,
    ImplementationIdentity,
    InstalledExtensions,
    LocalCandidateExecutor,
)
from serialization import DomainCodec
from telemetry import (
    DashboardBuilder,
    MetricRegistry,
    MetricThreshold,
    MonitoringConfiguration,
    MonitoringDefinitions,
    MonitoringQuery,
    OperationalAlerts,
    TelemetryStore,
)

_ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


# Below the AF_UNIX pathname limit on macOS, where /tmp is a link; Linux has no /private.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class TestPaperServiceCandidates:
    """Resolve a reference and a packaged candidate on one native book source."""

    extension = "engineering-candidates"

    @staticmethod
    def _artifact(name: str, payload: bytes) -> CandidateArtifact:
        """Identify known test bytes independently of the bundle writer."""
        return CandidateArtifact(name=name, sha256=hashlib.sha256(payload).hexdigest())

    @staticmethod
    def _capture() -> CaptureConfig:
        """Load the maintained public OKX selection without connecting."""
        return CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))

    @classmethod
    def _configuration(
        cls,
        packaged: PackagedCandidate,
        *,
        trades: bool = False,
        copies: tuple[str, ...] = ("packaged",),
    ) -> PaperServiceConfiguration:
        """Provision a reference formula and a packaged candidate on one shared account.

        With ``trades`` the source also records its public trades feed; ``copies`` names
        each instance of the packaged candidate.
        """
        capture = cls._capture()
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        money = Money(value=Decimal("1000"), currency=currency)
        quantity = Quantity(value=Decimal("1"), dimension=dimension)
        tick = Price(value=Decimal("0.01"), currency=currency, per=dimension)
        limits: tuple[SpotLimits, ...] = (
            SpotLimits(maximum=quantity, lot=quantity, tick=tick, product="spot"),
        )
        account = AccountConfiguration(
            mode="paper",
            opening_at=_ORIGIN,
            accounts=(OpeningAccount(account_id="shared", cash=(money,)),),
            instruments=limits,
            fee_rates=(InstrumentFeeRate(instrument_id=capture.instrument_id, rate=Decimal(0)),),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=money,
                accounts=(AccountLimit(account_id="shared", maximum=money),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id="shared",
                        maximum=money,
                        instruments=(capture.instrument_id,),
                    )
                    for name in ("reference", *copies)
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=30_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=money,
            ),
        )
        source = PaperServiceSource(
            name="book",
            capture=capture,
            trades=(
                replace(capture, channel="trades", depth=0, max_orders=1, idle_seconds=10)
                if trades
                else None
            ),
            freshness_us=30_000_000,
            scenario=PaperExecutionScenario(
                venue="okx",
                instrument_id=capture.instrument_id,
                entry_delay_us=1000,
                cancel_delay_us=2000,
                adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal("0.5"),
                gas_inapplicable_reason="Off-chain spot without blockchain transfers.",
            ),
        )
        reference = ReferenceCandidate(
            formula="target_clip", cadence_us=3_000_000, starts_at=_ORIGIN
        )
        candidates: tuple[tuple[str, ReferenceCandidate | PackagedCandidate], ...] = (
            ("reference", reference),
            *((copy, packaged) for copy in copies),
        )
        return PaperServiceConfiguration(
            accounts=(
                PaperServiceAccount(
                    account_id="shared",
                    configuration=account,
                    socket_path="/private/tmp/service-candidates.sock",
                ),
            ),
            sources=(source,),
            instances=tuple(
                PaperServiceInstance(
                    instance_id=name,
                    account_id="shared",
                    source="book",
                    candidate=candidate,
                    quantity=quantity,
                    lot=quantity,
                    maximum_fee=Money(value=Decimal("1"), currency=currency),
                )
                for name, candidate in candidates
            ),
            active=("reference", *copies),
            revision=1,
        )

    @classmethod
    def _input(cls) -> InputRequirement:
        """Read book imbalance under the source's shared name, clock and freshness."""
        return InputRequirement(
            name="book",
            family="book",
            clock="receipt",
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=30_000_000,
        )

    @classmethod
    def _flow(cls) -> InputRequirement:
        """Read signed public trade flow over the last ten seconds."""
        return InputRequirement(
            name="trades",
            family="trade",
            clock="event",
            field=NumericField(name="signed_flow", units="BTC"),
            max_age_us=10_000_000,
        )

    @classmethod
    def _requirements(cls, *, trades: bool = False) -> tuple[CapabilityRequirement, ...]:
        """Declare the native book, optional trades and the paper service families needed."""
        flow = CapabilityRequirement(
            name="trades",
            kind="market_data",
            product="spot",
            venue="okx",
            calendar="continuous-utc",
            channel="trade",
            clock="event",
            max_freshness_us=10_000_000,
            fields=(CapabilityField(name="signed_flow", units="BTC"),),
        )
        return (*((flow,) if trades else ()), *cls._base_requirements())

    @classmethod
    def _base_requirements(cls) -> tuple[CapabilityRequirement, ...]:
        """Declare the native book and the four paper service families the candidate needs."""
        return (
            CapabilityRequirement(
                name="book",
                kind="market_data",
                product="spot",
                venue="okx",
                calendar="continuous-utc",
                channel="book",
                clock="receipt",
                max_freshness_us=30_000_000,
                fields=(CapabilityField(name="imbalance", units="dimensionless"),),
            ),
            cls._family("reference", "reference_data"),
            cls._family("calendar", "calendar"),
            cls._family("valuation", "valuation"),
            cls._family("account", "account"),
            CapabilityRequirement(
                name="execution",
                kind="execution",
                product="spot",
                venue="okx",
                calendar="continuous-utc",
                operations=("intent:target",),
                order_types=("ioc",),
            ),
        )

    @staticmethod
    def _family(name: str, kind: CapabilityKind) -> CapabilityRequirement:
        """Require one spot OKX paper service family on the continuous calendar."""
        return CapabilityRequirement(
            name=name, kind=kind, product="spot", venue="okx", calendar="continuous-utc"
        )

    @classmethod
    def _publish(
        cls, root: Path, *, trades: bool = False, served: bool = False, runtime: bool = False
    ) -> CandidateDefinition:
        """Publish one packaged candidate with authored completed-study provenance.

        With ``trades`` its feature also reads signed public trade flow; with ``served``
        the bundle packages its feature-store definition.
        """
        inputs = (cls._input(), cls._flow()) if trades else (cls._input(),)
        codec = DomainCodec()
        instrument = str(cls._capture().instrument_id)
        extension = InstalledExtensions().identity(cls.extension)
        schema = FeatureSchema(
            implementation="smoothed-imbalance",
            inputs=inputs,
            outputs=(NumericField(name="smoothed_imbalance", units="dimensionless"),),
            parameters=(("weight", "1/2"),),
            mode="incremental",
            ttl_us=30_000_000,
        )
        policy_parameters = codec.encode_json(
            {
                "instrument": instrument,
                "quantity": "1",
                "threshold": {"numerator": "1", "denominator": "10"},
            }
        )
        policy = ImbalanceTarget.create(policy_parameters)
        metric, chart = FoldNetMetric.identity, FoldNetChart.identity
        payloads: dict[str, bytes] = {
            "feature-schema": codec.encode_json(schema),
            "feature-parameters": b"{}",
            "policy-parameters": policy_parameters,
            "metric-parameters": b"{}",
            "chart-parameters": b"{}",
        }
        if served:
            payloads["feature-store"] = codec.encode_json(cls._store(schema))
        selection = codec.encode_json(
            {
                "schema_version": "decision-study",
                "family": "engineering-candidates",
                "source_identity": "authored-book",
                "feature_identity": schema.identity,
                "policy_identity": policy.identity,
                "model_identity": None,
                "transform_identity": None,
                "output": "target",
                "calendar": "continuous-utc",
                "economics": {
                    "schema_version": "offline-intent-simulation",
                    "entity": instrument,
                    "source_identity": "authored-market",
                },
                "metrics": (metric,),
                "charts": (chart,),
            }
        )
        spec = ExperimentSpec(
            schema_version="experiment-engineering-sample",
            family="engineering-candidates",
            inputs=(
                Fingerprint(
                    name="resolved-configuration", sha256=hashlib.sha256(selection).hexdigest()
                ),
            ),
            components=(
                Fingerprint(name="implementation", sha256=ImplementationIdentity.sha256()),
                Fingerprint(name="engineering-candidates", sha256=extension),
            ),
            parameters=(),
            seeds=(),
            environment_sha256=ExperimentSpec.installed_environment(),
            split=None,
            engineering_sample=TimeWindow(start=_ORIGIN, end=_ORIGIN + timedelta(hours=1)),
        )
        report = codec.encode_json(
            {
                "schema_version": "study-report",
                "study_identity": spec.identity,
                "selected_metrics": (metric,),
                "selected_charts": (chart,),
            }
        )
        with AttemptStore(root / "attempts") as store:
            started = store.start(
                spec, at=_ORIGIN + timedelta(hours=2), invocation="engineering", request=selection
            )
            result = ResultManifest.retain(
                store,
                started.attempt_id,
                {"study-report": report, "feature-schema": payloads["feature-schema"]},
            )
            history = store.finish(
                started.attempt_id,
                status="completed",
                at=_ORIGIN + timedelta(hours=3),
                reason="Authored engineering candidate study.",
                result=codec.encode_json(result),
            )
        provenance = {
            "dataset-selection": selection,
            "experiment": codec.encode_json(spec),
            "attempt": codec.encode_json(history),
            "study-report": report,
        }
        artifacts = {
            name: cls._artifact(name, payload) for name, payload in (payloads | provenance).items()
        }
        definition = CandidateDefinition(
            name="engineering-imbalance",
            version="1",
            code_sha256=ImplementationIdentity.sha256(),
            environment_sha256=ExperimentSpec.installed_environment(),
            runtime_code_sha256=CandidateRuntime.code_sha256(),
            runtime_environment_sha256=CandidateRuntime.environment_sha256(),
            feature_schema=artifacts["feature-schema"],
            feature_store=artifacts.get("feature-store"),
            transform=None,
            estimator=None,
            components=(
                CandidateComponent(
                    role="feature",
                    factory_key="smoothed-imbalance",
                    identity=schema.identity,
                    implementation_sha256=extension,
                    parameters=artifacts["feature-parameters"],
                ),
                CandidateComponent(
                    role="policy",
                    factory_key="imbalance-target",
                    identity=policy.identity,
                    implementation_sha256=extension,
                    parameters=artifacts["policy-parameters"],
                ),
                CandidateComponent(
                    role="metric",
                    factory_key="fold-net",
                    identity=metric.sha256,
                    implementation_sha256=extension,
                    parameters=artifacts["metric-parameters"],
                ),
                CandidateComponent(
                    role="chart",
                    factory_key="fold-net-path",
                    identity=chart.sha256,
                    implementation_sha256=extension,
                    parameters=artifacts["chart-parameters"],
                ),
            ),
            inputs=inputs,
            requirements=cls._requirements(trades=trades),
            product="spot",
            calendar="continuous-utc",
            entities=(instrument,),
            cadence_us=3_000_000,
            available_at=_ORIGIN,
            output="target",
            state=CandidateStateContract(
                feature_mode="incremental",
                warmup_observations=1,
                checkpoint_schema="candidate-checkpoint",
                on_gap="reset",
                on_restart="restore",
                policy_state_schema="none",
            ),
            metrics=(
                CandidateMetricContract(
                    name="fold-net",
                    kind="metric",
                    component_key="fold-net",
                    version="1",
                    units="USDT",
                    applies_to=("research", "runtime") if runtime else ("research",),
                    warning_below=ExactRatio(numerator="0", denominator="1") if runtime else None,
                ),
                CandidateMetricContract(
                    name="fold-net-path",
                    kind="chart",
                    component_key="fold-net-path",
                    version="1",
                    units="USDT",
                    applies_to=("research",),
                ),
            ),
            artifacts=tuple(artifacts[name] for name in sorted(payloads)),
        )
        manifest = CandidateManifest(
            definition=definition,
            qualification="engineering",
            dataset=artifacts["dataset-selection"],
            experiment=artifacts["experiment"],
            attempt=artifacts["attempt"],
            report=artifacts["study-report"],
            assessment=None,
            artifacts=tuple(artifacts[name] for name in sorted(provenance)),
            limitations=("Authored engineering workload; no market evidence.",),
        )
        CandidateBundle(root / "candidates" / definition.identity).publish(
            manifest, payloads | provenance
        )
        return definition

    @classmethod
    def _inputs(cls, at: datetime, imbalance: str) -> DecisionInputs:
        """Supply one authored book imbalance at a grid instant."""
        instrument = str(cls._capture().instrument_id)
        return DecisionInputs(
            entity=instrument,
            decision_at=at,
            observations=(
                NamedObservation(
                    input=cls._input(),
                    entity=instrument,
                    event_at=at,
                    available_at=at,
                    value=ExactRatio.from_fraction(Fraction(imbalance)),
                    reason="authored",
                    lineage="authored-book",
                ),
            ),
        )

    def test_packaged_candidate_loads_from_bundle_and_extension(self, tmp_path: Path) -> None:
        """A signed bundle and its installed extension yield the exact packaged candidate."""
        definition = self._publish(tmp_path)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        configuration = self._configuration(packaged)
        resolved = PaperServiceCandidates(configuration, tmp_path / "candidates")
        source = configuration.sources[0]
        reference, candidate_instance = configuration.instances
        loaded = resolved.candidate(candidate_instance)
        assert loaded.definition == definition
        assert loaded.deployment.instance == "packaged"
        assert {item.field.name for item in resolved.requirements(source)} == {
            "ask",
            "bid",
            "ask_size",
            "imbalance",
        }
        assert loaded.deployment.source_identity == resolved.source_identity(source)
        report = resolved.report()
        instances = cast(dict[str, dict[str, object]], report["instances"])
        assert instances["packaged"]["candidate_identity"] == definition.identity
        assert instances["packaged"]["model_identity"] == "rule-only"
        assert resolved.candidate(reference).definition.name == "reference-target-clip"
        executor = LocalCandidateExecutor(loaded)
        first = executor.step(self._inputs(_ORIGIN + timedelta(seconds=3), "1/2"), None)
        assert first.status == "warming" and first.decision is None
        second = executor.step(
            self._inputs(_ORIGIN + timedelta(seconds=6), "1/2"), first.checkpoint
        )
        assert second.status == "decided" and second.decision is not None
        assert second.feature is not None
        assert second.feature.values == (ExactRatio(numerator="1", denominator="2"),)

    def test_trade_reading_candidate_needs_its_source_trades_feed(self, tmp_path: Path) -> None:
        """Trade fields resolve only from a recorded trades feed, and confirm the signal."""
        definition = self._publish(tmp_path, trades=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        configuration = self._configuration(packaged, trades=True)
        resolved = PaperServiceCandidates(configuration, tmp_path / "candidates")
        source = configuration.sources[0]
        feeds = resolved.feeds(source)
        assert feeds.trades == (self._flow(),)
        assert self._input() in feeds.book and self._flow() not in feeds.book
        loaded = resolved.candidate(configuration.instances[1])
        assert loaded.definition.inputs == (self._input(), self._flow())
        assert resolved.report()["sources"] == {"book": resolved.source_identity(source)}
        unfed = PaperServiceCandidates(self._configuration(packaged), tmp_path / "candidates")
        assert resolved.source_identity(source) != unfed.source_identity(
            self._configuration(packaged).sources[0]
        )
        executor = LocalCandidateExecutor(loaded)
        at = _ORIGIN + timedelta(seconds=3)
        warm = executor.step(self._both(at, "1/2", "1"), None)
        agreeing = executor.step(self._both(at + timedelta(seconds=3), "1/2", "2"), warm.checkpoint)
        assert agreeing.feature is not None and agreeing.feature.values == (
            ExactRatio(numerator="1", denominator="2"),
        )
        opposed = executor.step(
            self._both(at + timedelta(seconds=6), "1/2", "-1"), agreeing.checkpoint
        )
        assert opposed.feature is not None and opposed.feature.values == (
            ExactRatio(numerator="0", denominator="1"),
        )
        with pytest.raises(ValueError, match="no provisioned feed: trades"):
            unfed.report()

    @classmethod
    def _both(cls, at: datetime, imbalance: str, flow: str) -> DecisionInputs:
        """Supply authored book imbalance and signed trade flow at a grid instant."""
        book = cls._inputs(at, imbalance)
        return DecisionInputs(
            entity=book.entity,
            decision_at=at,
            observations=(
                *book.observations,
                NamedObservation(
                    input=cls._flow(),
                    entity=book.entity,
                    event_at=at,
                    available_at=at,
                    value=ExactRatio.from_fraction(Fraction(flow)),
                    reason="authored",
                    lineage="authored-trades",
                ),
            ),
        )

    @staticmethod
    def _store(schema: FeatureSchema) -> FeatureStoreDefinition:
        """Describe the store definition serving the packaged instance's feature."""
        return FeatureStoreDefinition(
            name="engineering-imbalance",
            entity_type="instrument",
            schema=schema,
            instance="packaged",
        )

    def test_feature_version_serves_the_packaged_candidate_its_stream(self, tmp_path: Path) -> None:
        """A feature version replaces source inputs with the bundle's store stream."""
        definition = self._publish(tmp_path, served=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity,
            extension=self.extension,
            starts_at=_ORIGIN,
            feature_version="stream",
        )
        configuration = self._configuration(packaged)
        resolved = PaperServiceCandidates(configuration, tmp_path / "candidates")
        instance = configuration.instances[1]
        assert resolved.inputs(instance) == ()
        loaded = resolved.candidate(instance)
        assert loaded.store_definition is not None
        stream = VersionedFeatureStore.stream_identity(loaded.store_definition, "stream")
        assert (loaded.deployment.input_mode, loaded.deployment.source_identity) == (
            "online_features",
            stream,
        )
        assert loaded.deployment.feature_version == "stream"
        instances = cast(dict[str, dict[str, object]], resolved.report()["instances"])
        assert instances["packaged"]["feature_stream"] == stream
        assert instances["reference"]["feature_stream"] is None
        unpackaged = self._publish(tmp_path / "plain")
        without = replace(packaged, definition_sha256=unpackaged.identity)
        plain = PaperServiceCandidates(
            self._configuration(without), tmp_path / "plain" / "candidates"
        )
        with pytest.raises(ValueError, match="no feature-store definition"):
            plain.candidate(self._configuration(without).instances[1])

    def test_publisher_inputs_start_the_feeds_a_served_stream_reads(self, tmp_path: Path) -> None:
        """Only a declared publisher adds a served stream's fields, including trades."""
        definition = self._publish(tmp_path, trades=True, served=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity,
            extension=self.extension,
            starts_at=_ORIGIN,
            feature_version="stream",
        )
        serving = PaperFeatureServing(
            store_path="/private/tmp/features.sqlite3",
            serving_root="/private/tmp/feast",
            worker=("/usr/bin/python3", "-m", "worker"),
        )
        unpublished = replace(self._configuration(packaged, trades=True), features=serving)
        resolved = PaperServiceCandidates(unpublished, tmp_path / "candidates")
        assert resolved.published_inputs(unpublished.instances[1]) == ()
        assert resolved.feeds(unpublished.sources[0]).trades == ()
        published = replace(
            unpublished,
            features=replace(serving, publisher=PaperFeaturePublisher(max_lag_seconds=5)),
        )
        resolved = PaperServiceCandidates(published, tmp_path / "candidates")
        assert resolved.published_inputs(published.instances[0]) == ()
        assert resolved.published_inputs(published.instances[1]) == (self._input(), self._flow())
        feeds = resolved.feeds(published.sources[0])
        assert feeds.trades == (self._flow(),) and self._input() in feeds.book

    def test_feature_publisher_binds_its_supervisors_fresh_status(self, tmp_path: Path) -> None:
        """Stale or foreign status binds nothing; a bound run refuses an incremental stream."""
        definition = self._publish(tmp_path, trades=True, served=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity,
            extension=self.extension,
            starts_at=_ORIGIN,
            feature_version="stream",
        )
        configuration = replace(
            self._configuration(packaged, trades=True),
            duration_seconds=1,
            features=PaperFeatureServing(
                store_path=str(tmp_path / "features.sqlite3"),
                serving_root=str(tmp_path / "feast"),
                worker=("/usr/bin/python3", "-m", "worker"),
                publisher=PaperFeaturePublisher(max_lag_seconds=5),
            ),
        )
        root = tmp_path / "service"
        root.mkdir()
        publisher = FeaturePublisher(
            configuration, tmp_path / "candidates", root, poll_seconds=0.01
        )
        assert [item.instance_id for item in publisher.served()] == ["packaged"]
        (tmp_path / "feast").mkdir()
        with (tmp_path / "feast" / "publisher.lock").open("a+b") as fence:
            fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(ValueError, match="already owns this serving root"):
                publisher.run()
        assert publisher.run()["stopped"] == "supervisor_not_found"
        codec = DomainCodec()
        status = root / "status.json"
        status.write_bytes(
            codec.encode_json(
                {"configuration": configuration.identity, "run_id": "old", "observed_at": _ORIGIN}
            )
        )
        assert publisher.run()["run_id"] is None
        fresh = datetime.now(UTC) + timedelta(hours=1)
        status.write_bytes(
            codec.encode_json({"configuration": "b" * 64, "run_id": "run", "observed_at": fresh})
        )
        with pytest.raises(ValueError, match="names another configuration"):
            publisher.run()
        status.write_bytes(
            codec.encode_json(
                {"configuration": configuration.identity, "run_id": "run", "observed_at": fresh}
            )
        )
        with pytest.raises(ValueError, match="started no recording"):
            publisher.run()
        source = configuration.sources[0]
        for feed, capture in (("book", source.capture), ("book.trades", source.trades)):
            assert capture is not None
            request = CaptureRequest(
                config=capture, recording_id=str(uuid4()), implementation_identity="a" * 64
            )
            directory = root / "runs" / "run" / feed / request.recording_id
            CaptureJournal(directory / request.recording_id, request).start()
        with pytest.raises(ValueError, match="batch feature definitions only"):
            publisher.run()
        with pytest.raises(ValueError, match="declares no feature publisher"):
            FeaturePublisher(replace(configuration, features=None), tmp_path / "candidates", root)

    @classmethod
    def _bought(cls) -> tuple[Fill, CandidateEvidence]:
        """Author one bought unit at 100 with a 1/10 fee, marked at a 99 bid."""
        dimension = Dimension(
            instrument_id=cls._capture().instrument_id, kind=QuantityKind.BASE_UNIT
        )
        currency = Currency.from_code("USDT")
        price = Price(value=Decimal("100"), currency=currency, per=dimension)
        fill = Fill(
            identity="bought",
            decision_at=_ORIGIN + timedelta(seconds=5),
            filled_at=_ORIGIN + timedelta(seconds=6),
            quantity=Quantity(value=Decimal("1"), dimension=dimension),
            reference=price,
            effective=price,
            fee=Money(value=Decimal("0.1"), currency=currency),
        )
        return fill, CandidateEvidence(
            fills=(fill,),
            initial_cash=Money(value=Decimal("1000"), currency=currency),
            mark=Price(value=Decimal("99"), currency=currency, per=dimension),
            start=_ORIGIN,
            cutoff=_ORIGIN + timedelta(seconds=10),
        )

    def test_runtime_metrics_delays_and_bands_reach_the_dashboard_alert(
        self, tmp_path: Path
    ) -> None:
        """A runtime metric is the bundle's own over the paper fold; its band alerts."""
        definition = self._publish(tmp_path, runtime=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        configuration = self._configuration(packaged)
        loaded = PaperServiceCandidates(configuration, tmp_path / "candidates").candidate(
            configuration.instances[1]
        )
        exporter = CandidateMonitoringExporter(
            loaded,
            scope="account:shared",
            account="shared",
            mode="paper",
            clock_quality="observed",
            study=loaded.definition.identity,
        )
        assert exporter.thresholds == (
            MetricThreshold(
                name="fold-net", operator="<", threshold=ExactRatio(numerator="0", denominator="1")
            ),
        )
        _, evidence = self._bought()
        (metric,) = exporter.runtime_metrics(evidence, recorded_at=evidence.cutoff)
        assert (metric.name, metric.units, metric.at) == ("fold-net", "USDT", evidence.cutoff)
        assert metric.value == ExactRatio.from_fraction(Fraction(-11, 10))
        delay = exporter.decision_delay(
            _ORIGIN + timedelta(seconds=3),
            _ORIGIN + timedelta(seconds=4, microseconds=500_000),
            recorded_at=evidence.cutoff,
        )
        assert (delay.name, delay.units) == ("runtime.decision-delay", "seconds")
        assert delay.value == ExactRatio.from_fraction(Fraction(3, 2))
        with pytest.raises(ValueError, match="coordination after its instant"):
            exporter.decision_delay(_ORIGIN, _ORIGIN, recorded_at=evidence.cutoff)
        query = MonitoringQuery(
            scope="account:shared",
            mode="paper",
            start=_ORIGIN,
            end=evidence.cutoff + timedelta(seconds=1),
            as_of=evidence.cutoff + timedelta(seconds=1),
        )
        store = TelemetryStore(tmp_path / "telemetry.sqlite3")
        store.append((metric, delay))
        (view,) = MonitoringConfiguration.account(
            query,
            store.query(query),
            alert_socket="/private/tmp/m3e-unbound.sock",
            thresholds=exporter.thresholds,
        )
        (rule,) = view.dashboard.alerts
        assert (rule.identity, rule.operator) == ("threshold:fold-net:<", "<")
        snapshot = DashboardBuilder.build(
            view.dashboard,
            view.query,
            store.select(view.query),
            MetricRegistry(MonitoringDefinitions.resolve(view.metrics)),
            OperationalAlerts(tmp_path / "alerts.sqlite3"),
        )
        (evaluation,) = snapshot.alert_results
        assert evaluation.state == "triggered"
        (attempt,) = OperationalAlerts(tmp_path / "alerts.sqlite3").read()
        assert attempt.status == "failed"

    def test_shadow_accounts_get_the_same_candidate_view(self, tmp_path: Path) -> None:
        """A shadow account's candidate series and band rule form a shadow page."""
        definition = self._publish(tmp_path, runtime=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        configuration = self._configuration(packaged)
        loaded = PaperServiceCandidates(configuration, tmp_path / "candidates").candidate(
            configuration.instances[1]
        )
        exporter = CandidateMonitoringExporter(
            loaded,
            scope="account:shared",
            account="shared",
            mode="shadow",
            clock_quality="observed",
            study=loaded.definition.identity,
        )
        _, evidence = self._bought()
        events = exporter.runtime_metrics(evidence, recorded_at=evidence.cutoff)
        end = evidence.cutoff + timedelta(seconds=1)
        query = MonitoringQuery(
            scope="account:shared", mode="shadow", start=_ORIGIN, end=end, as_of=end
        )
        (view,) = MonitoringConfiguration.account(
            query, events, alert_socket="/private/tmp/m3f.sock", thresholds=exporter.thresholds
        )
        assert view.dashboard.title.startswith("Shadow observations")
        assert [spec.modes for spec in view.metrics] == [("shadow",)]
        assert [rule.identity for rule in view.dashboard.alerts] == ["threshold:fold-net:<"]
        with pytest.raises(ValueError, match="paper or shadow"):
            MonitoringConfiguration.account(replace(query, mode="research"), events)

    def test_candidate_telemetry_exports_and_alerts_from_the_diagnostics(
        self, tmp_path: Path
    ) -> None:
        """An account sample exports the candidate's metric and its band reaches a receiver."""
        definition = self._publish(tmp_path, runtime=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        address = Path(_SOCKET_ROOT) / f"m3e-{uuid4().hex[:8]}.sock"
        configuration = replace(self._configuration(packaged), alert_socket=str(address))
        owner = PaperOwner(
            account_id="shared",
            deployment_sha256="a" * 64,
            authorization_id="authorization",
            release_identity="b" * 64,
            owner_id="owner",
            generation=1,
        )
        root = tmp_path / "monitoring"
        telemetry = CandidateTelemetry(
            configuration,
            (owner,),
            candidates=tmp_path / "candidates",
            runs=tmp_path / "runs",
            root=root,
            started_at=_ORIGIN,
        )
        fill, evidence = self._bought()
        state = AccountExecutionResult(
            accounts=(),
            orders=(),
            paper_fills=(AccountPaperFill(instance_id="packaged", order_id="order", fill=fill),),
        )
        market = PaperMarket(
            identity="market",
            at=evidence.cutoff,
            bid=evidence.mark if evidence.mark is not None else fill.reference,
            ask=fill.reference,
            bid_quantity=fill.quantity,
            ask_quantity=fill.quantity,
        )
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            receiver.bind(str(address))
            receiver.settimeout(2)
            telemetry.sample(
                InspectedPaperAccount(configuration.accounts[0].configuration, owner, state),
                state,
                (market,),
                observed_at=evidence.cutoff,
            )
            assert telemetry.failures == 0, telemetry.last_error
            assert b"account-control" in receiver.recv(4096)
        finally:
            receiver.close()
            address.unlink(missing_ok=True)
        query = MonitoringQuery(
            scope="account:shared:strategy:packaged",
            mode="paper",
            start=_ORIGIN,
            end=evidence.cutoff + timedelta(seconds=1),
            as_of=evidence.cutoff + timedelta(seconds=1),
        )
        events = TelemetryStore(root / "telemetry.sqlite3").query(query)
        assert [(item.name, item.value) for item in events] == [
            ("fold-net", ExactRatio.from_fraction(Fraction(-11, 10)))
        ]
        pages = tuple(
            path
            for path in (root / "dashboards" / "shared").iterdir()
            if not path.name.startswith(".")
        )
        assert len(pages) == 1 and (pages[0] / "dashboard.html").is_file()
        assert [item.status for item in OperationalAlerts(root / "alerts.sqlite3").read()] == [
            "delivered"
        ]

    def test_candidates_sharing_an_account_keep_their_own_series(self, tmp_path: Path) -> None:
        """Two instances of one candidate export the same metric without colliding."""
        definition = self._publish(tmp_path, runtime=True)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        configuration = self._configuration(packaged, copies=("packaged", "packaged-late"))
        owner = PaperOwner(
            account_id="shared",
            deployment_sha256="a" * 64,
            authorization_id="authorization",
            release_identity="b" * 64,
            owner_id="owner",
            generation=1,
        )
        root = tmp_path / "monitoring"
        telemetry = CandidateTelemetry(
            configuration,
            (owner,),
            candidates=tmp_path / "candidates",
            runs=tmp_path / "runs",
            root=root,
            started_at=_ORIGIN,
        )
        fill, evidence = self._bought()
        state = AccountExecutionResult(
            accounts=(),
            orders=(),
            paper_fills=tuple(
                AccountPaperFill(instance_id=name, order_id=f"order-{name}", fill=fill)
                for name in ("packaged", "packaged-late")
            ),
        )
        market = PaperMarket(
            identity="market",
            at=evidence.cutoff,
            bid=evidence.mark if evidence.mark is not None else fill.reference,
            ask=fill.reference,
            bid_quantity=fill.quantity,
            ask_quantity=fill.quantity,
        )
        telemetry.sample(
            InspectedPaperAccount(configuration.accounts[0].configuration, owner, state),
            state,
            (market,),
            observed_at=evidence.cutoff,
        )
        assert telemetry.failures == 0, telemetry.last_error
        end = evidence.cutoff + timedelta(seconds=1)
        for name in ("packaged", "packaged-late"):
            query = MonitoringQuery(
                scope=f"account:shared:strategy:{name}",
                mode="paper",
                start=_ORIGIN,
                end=end,
                as_of=end,
            )
            events = TelemetryStore(root / "telemetry.sqlite3").query(query)
            assert [item.name for item in events] == ["fold-net"]
        labels = sorted(
            path.name.split("-", 1)[1]
            for path in (root / "dashboards" / "shared").iterdir()
            if not path.name.startswith(".")
        )
        assert labels == ["packaged-1", "packaged-late-1"]

    def test_feature_publisher_lag_is_bounded(self) -> None:
        """The publisher's lag is a whole number of seconds from 1 to 300."""
        assert PaperFeaturePublisher(max_lag_seconds=300).max_lag_seconds == 300
        for lag in (0, 301, True):
            with pytest.raises(ValueError, match="lag must be 1 to 300 seconds"):
                PaperFeaturePublisher(max_lag_seconds=lag)

    def test_feature_serving_requires_absolute_paths_and_worker(self) -> None:
        """The served-feature binding refuses relative locations and unbounded timeouts."""
        serving = PaperFeatureServing(
            store_path="/private/tmp/features.sqlite3",
            serving_root="/private/tmp/feast",
            worker=("/usr/bin/python3", "-m", "worker"),
        )
        for changes in (
            {"store_path": "features.sqlite3"},
            {"serving_root": "feast"},
            {"worker": ("python3",)},
            {"worker_timeout_seconds": 61},
        ):
            with pytest.raises(ValueError, match="invalid paper feature serving"):
                replace(serving, **changes)

    def test_packaged_candidate_refuses_unsigned_foreign_or_changed_inputs(
        self, tmp_path: Path
    ) -> None:
        """No signed directory, another extension or changed bundle bytes load nothing."""
        definition = self._publish(tmp_path)
        packaged = PackagedCandidate(
            definition_sha256=definition.identity, extension=self.extension, starts_at=_ORIGIN
        )
        instance = self._configuration(packaged).instances[1]
        with pytest.raises(ValueError, match="signed candidates"):
            PaperServiceCandidates(self._configuration(packaged), None).candidate(instance)
        foreign = self._configuration(replace(packaged, extension="absent-extension"))
        with pytest.raises(ValueError, match="not installed"):
            PaperServiceCandidates(foreign, tmp_path / "candidates").candidate(foreign.instances[1])
        with pytest.raises(ValueError, match="invalid packaged candidate"):
            replace(packaged, extension="alpha-research-execution")
        objects = tmp_path / "candidates" / definition.identity / "objects"
        changed = objects / definition.feature_schema.sha256
        changed.chmod(0o600)
        changed.write_bytes(changed.read_bytes() + b" ")
        with pytest.raises(ValueError, match="artifact bytes differ"):
            PaperServiceCandidates(
                self._configuration(packaged), tmp_path / "candidates"
            ).candidate(instance)
