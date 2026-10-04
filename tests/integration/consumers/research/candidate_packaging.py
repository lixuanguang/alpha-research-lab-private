"""Package a completed study of installed extension components through the library API."""

from __future__ import annotations

# standard library imports
import sys
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
from engineering_candidates import FoldNetChart, FoldNetMetric, ImbalanceTarget, SmoothedImbalance
from msgspec.structs import replace

# project library imports
from applications.explore import StudyComponents, evaluate_study
from configuration import (
    CandidateDeployment,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    UniverseSelection,
)
from financial_units import ExactRatio
from reference_data.instruments import InstrumentId
from research.experiments import (
    AttemptStore,
    CandidateBundle,
    CandidateDefinition,
    CandidateMetricContract,
    CandidateStateContract,
    Fingerprint,
)
from research.features import FeatureSchema
from research.observations import (
    DecisionInputs,
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from research.studies import DecisionStudy, PublicationPolicy, StudyArtifact
from runtime import (
    CandidateLoader,
    CandidatePackager,
    ComponentSelection,
    InstalledExtensions,
    LocalCandidateExecutor,
)
from serialization import DomainCodec

_EXTENSION = "engineering-candidates"


class _PackagingAcceptance:
    """Run one study with installed components and package it, then refuse altered requests."""

    def __init__(self, output: Path) -> None:
        """Bind the output root, the authored scenario and the installed extension."""
        # third party library imports
        from research_workflows.scenario import _Scenario

        self.output = output
        self.scenario = _Scenario()
        self.extensions = InstalledExtensions()
        self.requirement = InputRequirement(
            name="authored-imbalance",
            family="non-book",
            clock="authored",
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=0,
        )
        self.schema = FeatureSchema(
            implementation="smoothed-imbalance",
            inputs=(self.requirement,),
            outputs=(NumericField(name="smoothed_imbalance", units="dimensionless"),),
            parameters=(("weight", "1/2"),),
            mode="incremental",
            ttl_us=30_000_000,
        )
        self.policy_parameters = DomainCodec().encode_json(
            {
                "instrument": self.scenario.entity,
                "quantity": "1",
                "threshold": {"numerator": "1", "denominator": "10"},
            }
        )

    def study(self, *, retain_extension: bool = True) -> tuple[DecisionStudy, StudyComponents]:
        """Freeze the study of installed components over authored imbalance values."""
        # third party library imports
        from research_workflows.scenario import _Market, _TargetPolicy

        scenario = self.scenario
        placeholder = _TargetPolicy(scenario.dimension, threshold=0)
        rows = tuple(
            NamedObservation(
                input=self.requirement,
                entity=scenario.entity,
                event_at=scenario.at(second),
                available_at=scenario.at(second),
                value=ExactRatio.from_fraction(Fraction(value)),
                reason="authored",
                lineage=f"imbalance:{second}",
            )
            for second, value in ((5, "1/2"), (10, "1/2"), (30, "-1/2"), (40, "1/2"))
        )
        feature = SmoothedImbalance.create(self.schema, b"{}")
        policy = ImbalanceTarget.create(self.policy_parameters)
        metric, chart = FoldNetMetric.create(b"{}"), FoldNetChart.create(b"{}")
        record = self.extensions.artifact(_EXTENSION)
        artifacts: tuple[StudyArtifact, ...] = (
            (scenario.artifact, record) if retain_extension else (scenario.artifact,)
        )
        fingerprints: tuple[Fingerprint, ...] = (
            (scenario.artifact.fingerprint, record.fingerprint)
            if retain_extension
            else (scenario.artifact.fingerprint,)
        )
        base = scenario.study(placeholder, fitted=False)
        study = replace(
            base,
            family="packaged-engineering-study",
            source_identity=NumericHistorySource(rows, (self.requirement,)).identity,
            feature_identity=feature.schema.identity,
            policy_identity=policy.identity,
            output="target",
            metrics=(metric.identity,),
            charts=(chart.identity,),
            extensions=fingerprints,
            economics=replace(base.economics, source_identity=_Market(scenario).identity),
        )
        components = dataclass_replace(
            scenario.components(placeholder, fitted=False),
            source=NumericHistorySource(rows, (self.requirement,)),
            feature=feature,
            policy=policy,
            capabilities=(
                "product:spot",
                "calendar:continuous-utc",
                "intent:target",
                "feature:incremental",
                "input:non-book",
            ),
            metrics=(metric,),
            charts=(chart,),
            artifacts=artifacts,
        )
        return study, components

    def run(self) -> dict[str, object]:
        """Package, reopen and step the candidate, then refuse three altered requests."""
        attempts = self.output / "attempts"
        study, components = self.study()
        history = evaluate_study(
            study,
            components=components,
            attempts=attempts,
            publication=PublicationPolicy(mode="local"),
        )
        assert history.status == "completed", history.status
        store = AttemptStore(attempts)
        packager = CandidatePackager(self.extensions)
        manifest = packager.publish(
            self.output / "candidate",
            store=store,
            attempt_id=history.start.attempt_id,
            extension=_EXTENSION,
            selections=self.selections(self.policy_parameters),
            name="packaged-engineering",
            version="1",
            venue="okx",
            cadence_us=10_000_000,
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
            limitations=("Authored engineering study; no market evidence.",),
        )
        loaded = CandidateLoader(
            self.extensions.components(_EXTENSION), self.registry(manifest.definition.requirements)
        ).load(CandidateBundle(self.output / "candidate"), self.deployment(manifest.definition))
        executor = LocalCandidateExecutor(loaded)
        start = loaded.deployment.starts_at
        warm = executor.step(self.inputs(start, "1/2"), None)
        decided = executor.step(self.inputs(start + timedelta(seconds=10), "1/2"), warm.checkpoint)
        refusals = {
            "changed_parameters": self.refused(
                store,
                history.start.attempt_id,
                self.selections(
                    self.policy_parameters.replace(b'"quantity":"1"', b'"quantity":"2"')
                ),
            ),
            "missing_chart": self.refused(
                store,
                history.start.attempt_id,
                self.selections(self.policy_parameters)[:-1],
            ),
        }
        unretained, unretained_components = self.study(retain_extension=False)
        bare = evaluate_study(
            replace(unretained, family="packaged-engineering-bare"),
            components=unretained_components,
            attempts=attempts,
            publication=PublicationPolicy(mode="local"),
        )
        refusals["unretained_extension"] = self.refused(
            store, bare.start.attempt_id, self.selections(self.policy_parameters)
        )
        return {
            "candidate": manifest.definition.identity,
            "components": [item.factory_key for item in manifest.definition.components],
            "requirements": [item.name for item in manifest.definition.requirements],
            "warm_status": warm.status,
            "decided_status": decided.status,
            "refusals": refusals,
        }

    def refused(
        self, store: AttemptStore, attempt_id: str, selections: tuple[ComponentSelection, ...]
    ) -> str:
        """Return the refusal of one altered packaging request, or fail if it was accepted."""
        try:
            CandidatePackager(self.extensions).publish(
                self.output / f"refused-{len(list(self.output.glob('refused-*')))}",
                store=store,
                attempt_id=attempt_id,
                extension=_EXTENSION,
                selections=selections,
                name="refused",
                version="1",
                venue="okx",
                cadence_us=10_000_000,
                state=CandidateStateContract(
                    feature_mode="incremental",
                    warmup_observations=1,
                    checkpoint_schema="candidate-checkpoint",
                    on_gap="reset",
                    on_restart="restore",
                    policy_state_schema="none",
                ),
                metrics=(),
                limitations=("refused",),
            )
        except ValueError as error:
            return str(error)
        raise AssertionError("altered packaging request was accepted")

    @staticmethod
    def selections(policy: bytes) -> tuple[ComponentSelection, ...]:
        """Select the installed factories the study used, chart last."""
        return (
            ComponentSelection(role="feature", factory_key="smoothed-imbalance", parameters=b"{}"),
            ComponentSelection(role="policy", factory_key="imbalance-target", parameters=policy),
            ComponentSelection(role="metric", factory_key="fold-net", parameters=b"{}"),
            ComponentSelection(role="chart", factory_key="fold-net-path", parameters=b"{}"),
        )

    def deployment(self, definition: CandidateDefinition) -> CandidateDeployment:
        """Place the packaged candidate as an unauthorized runtime instance."""
        identity, requirements = definition.identity, definition.requirements
        instrument = InstrumentId.from_canonical_text(self.scenario.entity)
        return CandidateDeployment(
            name="packaged-engineering-runtime",
            candidate_identity=identity,
            instance="packaged",
            entity=self.scenario.entity,
            mode="runtime",
            input_mode="source",
            source_identity="authored-imbalance",
            starts_at=datetime(2026, 10, 4, tzinfo=UTC),
            selections=tuple(
                CapabilitySelection(name=item.name, profile=f"fixture-{item.name}")
                for item in requirements
            ),
            universes=UniverseSelection(
                collection=(instrument,), research=(), strategy=(instrument,), authorized_trading=()
            ),
        )

    @staticmethod
    def registry(requirements: tuple[CapabilityRequirement, ...]) -> CapabilityRegistry:
        """Declare fixture profiles that satisfy exactly the derived requirements."""
        return CapabilityRegistry(
            tuple(
                CapabilityProfile(
                    name=f"fixture-{item.name}",
                    kind=item.kind,
                    implementation_identity=f"fixture-{item.kind}",
                    version="1",
                    products=(item.product,),
                    venues=(item.venue,),
                    calendars=(item.calendar,),
                    modes=("runtime",),
                    channels=() if item.channel is None else (item.channel,),
                    clocks=() if item.clock is None else (item.clock,),
                    max_freshness_us=item.max_freshness_us,
                    fields=item.fields,
                    operations=item.operations,
                    order_types=item.order_types,
                    qualification="fixture",
                )
                for item in requirements
            )
        )

    def inputs(self, at: datetime, value: str) -> DecisionInputs:
        """Supply one authored imbalance at a decision instant."""
        return DecisionInputs(
            entity=self.scenario.entity,
            decision_at=at,
            observations=(
                NamedObservation(
                    input=self.requirement,
                    entity=self.scenario.entity,
                    event_at=at,
                    available_at=at,
                    value=ExactRatio.from_fraction(Fraction(value)),
                    reason="authored",
                    lineage=f"runtime:{at.isoformat()}",
                ),
            ),
        )


def main() -> None:
    """Run the packaging acceptance and retain its summary."""
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True)
    summary = _PackagingAcceptance(output).run()
    (output / "summary.json").write_bytes(DomainCodec().encode_json(summary))


if __name__ == "__main__":
    main()
