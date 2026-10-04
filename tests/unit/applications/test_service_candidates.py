"""Verify packaged candidates load from signed bundles and installed extensions only."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from engineering_candidates import FoldNetChart, FoldNetMetric, ImbalanceTarget
from msgspec.structs import replace

# project library imports
from applications.execute.service_candidates import PaperServiceCandidates
from configuration import (
    AccountConfiguration,
    CapabilityField,
    CapabilityKind,
    CapabilityRequirement,
    CaptureConfig,
    OpeningAccount,
    PackagedCandidate,
    PaperExecutionScenario,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    ReferenceCandidate,
)
from configuration.accounts import InstrumentFeeRate
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
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
from research.features import FeatureSchema
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from research.studies import ResultManifest
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import ImplementationIdentity, InstalledExtensions, LocalCandidateExecutor
from serialization import DomainCodec

_ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


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
    def _configuration(cls, packaged: PackagedCandidate) -> PaperServiceConfiguration:
        """Provision a reference formula and a packaged candidate on one shared account."""
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
                    for name in ("reference", "packaged")
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=30_000_000,
                max_price_deviation_bps=100,
                max_order_notional=money,
            ),
        )
        source = PaperServiceSource(
            name="book",
            capture=capture,
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
                for name, candidate in (("reference", reference), ("packaged", packaged))
            ),
            active=("reference", "packaged"),
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
    def _requirements(cls) -> tuple[CapabilityRequirement, ...]:
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
    def _publish(cls, root: Path) -> CandidateDefinition:
        """Publish one packaged candidate with authored completed-study provenance."""
        codec = DomainCodec()
        instrument = str(cls._capture().instrument_id)
        extension = InstalledExtensions().identity(cls.extension)
        schema = FeatureSchema(
            implementation="smoothed-imbalance",
            inputs=(cls._input(),),
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
            feature_schema=artifacts["feature-schema"],
            feature_store=None,
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
            inputs=(cls._input(),),
            requirements=cls._requirements(),
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
                    applies_to=("research",),
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
