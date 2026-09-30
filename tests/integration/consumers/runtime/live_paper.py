"""Package an engineering candidate before one bounded native public-book paper capture."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import hashlib
import sys
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import LedgerState
from applications.explore import StudyComponents, evaluate_study
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
    CaptureConfig,
    PaperConfiguration,
    PaperExecutionScenario,
)
from execution import PaperOrderJournal, StepRecord
from financial_units import Currency, Dimension, ExactRatio, Money, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import CaptureRequest
from research.experiments import AttemptStore, CandidateBundle, Fingerprint
from research.features import FeatureKernel, FeatureSchema
from research.observations import (
    InputRequirement,
    LiveBookDecisionSource,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from research.studies import (
    ChartDefinition,
    DecisionStudy,
    MetricDefinition,
    PublicationPolicy,
    StudyArtifact,
)
from risk import SpotLimits
from runtime import (
    CandidateComponents,
    CandidateLoader,
    CandidateStep,
    ChartFactory,
    FeatureFactory,
    InstalledIdentity,
    LiveBookDelivery,
    LoadedCandidate,
    MetricFactory,
    PaperCandidateRuntime,
    PaperCaptureObserver,
    PolicyFactory,
)
from serialization import DomainCodec
from simulation import SpotCosts, SpotFeeModel
from strategies import DecisionPolicy, StrategyEvent


class _LiveCandidateConsumer:
    """Package a real installed candidate while keeping authored study rows separate."""

    def __init__(self, config: CaptureConfig, output: Path) -> None:
        """Bind one explicit native venue selection and local evidence directory."""
        config.__post_init__()
        if config.venue not in ("bitfinex", "okx"):
            raise ValueError("live paper consumer requires supported public books")
        self.config = config
        self.output = output

    def _requirements(self) -> tuple[CapabilityRequirement, ...]:
        """Declare the actual book clock alongside fixture-only paper services."""
        config = self.config
        names: tuple[tuple[str, CapabilityKind], ...] = (
            ("book-signal", "market_data"),
            ("reference", "reference_data"),
            ("calendar", "calendar"),
            ("valuation", "valuation"),
            ("account", "account"),
            ("execution", "execution"),
        )
        return tuple(
            CapabilityRequirement(
                name=name,
                kind=kind,
                product="spot",
                venue=config.venue,
                calendar="continuous-utc",
                channel="book" if name == "book-signal" else None,
                clock="receipt" if name == "book-signal" else None,
                max_freshness_us=5_000_000 if name == "book-signal" else None,
                fields=(CapabilityField(name="imbalance", units="dimensionless"),)
                if name == "book-signal"
                else (),
                operations=("intent:order",) if name == "execution" else (),
                order_types=("post-only",) if name == "execution" else (),
                qualification="read_only" if name == "book-signal" else "fixture",
            )
            for name, kind in names
        )

    def _registry(self, requirements: tuple[CapabilityRequirement, ...]) -> CapabilityRegistry:
        """Bind read-only native input and non-executable fixture capabilities."""
        return CapabilityRegistry(
            tuple(
                CapabilityProfile(
                    name=f"fixture-{requirement.name}",
                    kind=requirement.kind,
                    implementation_identity=(
                        f"native-{self.config.venue}-public-book"
                        if requirement.kind == "market_data"
                        else f"installed-fixture-{requirement.kind}"
                    ),
                    version="1",
                    products=("spot",),
                    venues=(self.config.venue,),
                    calendars=("continuous-utc",),
                    modes=("replay", "runtime"),
                    channels=("book",) if requirement.kind == "market_data" else (),
                    clocks=("receipt",) if requirement.kind == "market_data" else (),
                    max_freshness_us=5_000_000 if requirement.kind == "market_data" else None,
                    fields=(CapabilityField(name="imbalance", units="dimensionless"),)
                    if requirement.kind == "market_data"
                    else (),
                    operations=("intent:order",) if requirement.kind == "execution" else (),
                    order_types=("post-only",) if requirement.kind == "execution" else (),
                    qualification="read_only" if requirement.kind == "market_data" else "fixture",
                )
                for requirement in requirements
            )
        )

    @staticmethod
    def _journal(
        path: Path, loaded: LoadedCandidate, paper: PaperConfiguration
    ) -> PaperOrderJournal:
        """Reopen exactly the admitted non-executable account and simulation grids."""
        return PaperOrderJournal(
            path,
            account=paper.account,
            instance=loaded.deployment.instance,
            binding_identity=PaperCandidateRuntime.binding(loaded, paper),
            mode=paper.mode,
            limits=SpotLimits(
                maximum=paper.maximum, lot=paper.lot, tick=paper.tick, product="spot"
            ),
            ledger_state=LedgerState(
                initial_cash=paper.initial_cash, dimension=paper.maximum.dimension
            ),
            fee_rate=Decimal("0.002"),
        )

    @staticmethod
    def _timers(records: tuple[StepRecord, ...]) -> tuple[CandidateStep, ...]:
        """Read the original serialized decision results, never recompute their clocks."""
        codec = DomainCodec()
        return tuple(
            codec.decode_json(record.result_bytes, CandidateStep)
            for record in records
            if record.step_id.startswith("timer:")
        )

    def _play_saved(
        self,
        records: tuple[StepRecord, ...],
        *,
        request: CaptureRequest,
        loaded: LoadedCandidate,
        paper: PaperConfiguration,
        journal_path: Path,
    ) -> PaperOrderJournal:
        """Use retained delivery envelopes and tick IDs through the public runtime."""
        if not records or not records[0].step_id.startswith("start:"):
            raise ValueError("live paper journal lacks its original lifecycle start")
        codec = DomainCodec()
        start = codec.decode_json(records[0].result_bytes, StrategyEvent)
        if start.kind != "start":
            raise ValueError("live paper journal starts with another lifecycle event")
        journal = self._journal(journal_path, loaded, paper)
        source = LiveBookDecisionSource(request, loaded.manifest.inputs[0], history_capacity=10_000)
        runtime = PaperCandidateRuntime(loaded, paper, journal, source=source)
        books = BookRegistry(
            BookRegistryConfiguration(
                selections=(
                    BookSelection.from_capture(
                        request.config,
                        source_id=request.identity,
                        capability=BookAdapters.capability(request.config),
                        max_age_ns=min(
                            loaded.manifest.inputs[0].max_age_us * 1000,
                            request.config.idle_seconds * 1_000_000_000,
                        ),
                        allow_degraded=True,
                    ),
                ),
                equivalences=(),
                history_capacity=10_000,
            )
        )
        observer = PaperCaptureObserver(source, runtime, books=books)
        runtime.open(owner=f"{paper.account}-saved-replay", at=start.at)
        try:
            for record in records[1:]:
                if record.step_id.startswith("input:"):
                    observer.deliver(codec.decode_json(record.input_bytes, LiveBookDelivery))
                elif record.step_id.startswith("timer:"):
                    original = codec.decode_json(record.result_bytes, CandidateStep)
                    runtime.timer(identity=record.step_id.removeprefix("timer:"), at=original.at)
                elif not record.step_id.startswith(("market:", "order:", "account:")):
                    raise ValueError(f"unexpected live paper journal step: {record.step_id}")
        finally:
            runtime.release()
        return journal

    def _prove_saved_replay(
        self,
        *,
        request: CaptureRequest,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        paper: PaperConfiguration,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        journal_path: Path,
    ) -> dict[str, object]:
        """Compare restored paper and shadow effects against actual durable deliveries."""
        loaded = CandidateLoader(components, registry).load(bundle, deployment)
        original = self._journal(journal_path, loaded, paper)
        saved_records = original.steps()
        if not any(record.step_id.startswith("input:") for record in saved_records):
            raise ValueError("live paper capture has no durable book deliveries to replay")
        original_timers = self._timers(saved_records)
        if not original_timers or not any(step.status == "decided" for step in original_timers):
            raise ValueError("live paper capture has no admitted book-driven decision")
        paper_replay_path = self.output / "paper-replay.sqlite3"
        paper_replay = self._play_saved(
            saved_records,
            request=request,
            loaded=loaded,
            paper=paper,
            journal_path=paper_replay_path,
        )
        if (
            paper_replay.steps() != saved_records
            or paper_replay.ledger_state() != original.ledger_state()
            or paper_replay.orders() != original.orders()
        ):
            raise ValueError("saved live delivery replay changed paper trace or account")

        shadow_deployment = replace(
            deployment,
            name=f"{deployment.name}-shadow",
            instance=f"{deployment.instance}-shadow",
        )
        shadow_paper = replace(paper, account=f"{paper.account}-shadow", mode="shadow")
        shadow_loaded = CandidateLoader(components, registry).load(bundle, shadow_deployment)
        shadow_path = self.output / "shadow-replay.sqlite3"
        shadow = self._play_saved(
            saved_records,
            request=request,
            loaded=shadow_loaded,
            paper=shadow_paper,
            journal_path=shadow_path,
        )
        shadow_timers = self._timers(shadow.steps())
        if len(shadow_timers) != len(original_timers):
            raise ValueError("shadow replay lost a live candidate cutoff")
        for actual, simulated in zip(original_timers, shadow_timers, strict=True):
            if (
                (actual.status, actual.reason, actual.at)
                != (simulated.status, simulated.reason, simulated.at)
                or (None if actual.feature is None else actual.feature.values)
                != (None if simulated.feature is None else simulated.feature.values)
                or (None if actual.decision is None else actual.decision.intent)
                != (None if simulated.decision is None else simulated.decision.intent)
            ):
                raise ValueError("shadow replay changed a saved book-driven intent")
        if shadow.ledger_state().fills:
            raise ValueError("shadow replay posted a modeled execution")

        next_request = replace(request, recording_id=str(uuid4()))
        next_source = LiveBookDecisionSource(
            next_request, loaded.manifest.inputs[0], history_capacity=10_000
        )
        if next_source.identity != deployment.source_identity:
            raise ValueError("fresh capture recording changed the admitted source binding")
        before_orders, before_ledger = original.orders(), original.ledger_state()
        last_timer_record = next(
            record for record in reversed(saved_records) if record.step_id.startswith("timer:")
        )
        last_timer = DomainCodec().decode_json(last_timer_record.result_bytes, CandidateStep)
        previous_checkpoint = original.checkpoint()
        if previous_checkpoint is None:
            raise ValueError("live paper journal lacks a durable continuation")
        restored = PaperCandidateRuntime(loaded, paper, original, source=next_source)
        restored.open(owner=f"{paper.account}-fresh-recording", at=datetime.now(UTC))
        try:
            repeated, _ = restored.timer(
                identity=last_timer_record.step_id.removeprefix("timer:"), at=last_timer.at
            )
            if repeated != last_timer:
                raise ValueError("restart changed the saved candidate decision")
        finally:
            restored.release()
        if original.orders() != before_orders or original.ledger_state() != before_ledger:
            raise ValueError("fresh-recording restart duplicated paper account effects")
        return {
            "saved_delivery_count": sum(
                record.step_id.startswith("input:") for record in saved_records
            ),
            "saved_timer_count": len(original_timers),
            "saved_decision_count": sum(step.status == "decided" for step in original_timers),
            "paper_replay_journal": str(paper_replay_path),
            "paper_replay_exact_steps": True,
            "paper_replay_ledger_equal": True,
            "paper_replay_orders_equal": True,
            "shadow_replay_journal": str(shadow_path),
            "shadow_same_intents": True,
            "shadow_zero_fills": True,
            "fresh_recording_source_identity_equal": True,
            "restart_no_duplicate_effects": True,
        }

    async def run(self) -> dict[str, object]:
        """Evaluate a historical synthetic study, load its bundle, then capture live books."""
        # The standalone installed consumer is copied beside its explicit support
        # package. Isolated Python cannot see test files through the checkout.
        consumer_root = str(Path(__file__).resolve().parent)
        if consumer_root not in sys.path:
            sys.path.insert(0, consumer_root)
        # third party library imports
        from research_workflows.candidate_bundle import _CandidateAcceptance
        from research_workflows.scenario import (
            _Feature,
            _FillCountMetric,
            _OrderPolicy,
            _ProfitChart,
            _Scenario,
        )

        config = self.config

        class _LiveScenario(_Scenario):
            """Reuse authored study mechanics under the selected live instrument units."""

            def __init__(self, selected: CaptureConfig) -> None:
                """Keep historical synthetic rows apart from the later native capture."""
                super().__init__()
                self.entity = str(selected.instrument_id)
                self.dimension = Dimension(
                    instrument_id=selected.instrument_id, kind=QuantityKind.BASE_UNIT
                )
                self.currency = Currency(code=selected.quote_currency, minor_unit=Decimal("0.01"))
                self.requirement = InputRequirement(
                    name="book-signal",
                    family="book",
                    clock="receipt",
                    field=NumericField(name="imbalance", units="dimensionless"),
                    max_age_us=5_000_000,
                )
                rows = tuple(
                    NamedObservation(
                        input=self.requirement,
                        entity=self.entity,
                        event_at=self.at(second),
                        available_at=self.at(second),
                        value=ExactRatio.from_fraction(Fraction(value)),
                        reason="authored-historical-study",
                        lineage=f"synthetic-book-imbalance:{second}:{value}",
                    )
                    for second, value in (
                        (1, "1/4"),
                        (2, "1/2"),
                        (10, "3/4"),
                        (20, "1/4"),
                        (21, "1/2"),
                        (30, "3/4"),
                        (40, "1/4"),
                    )
                )
                self.source = NumericHistorySource(rows, (self.requirement,))
                self.feature = _Feature(self.requirement)
                costs = SpotCosts(
                    adverse=self.price("0"), fee_rate=Decimal("0.002"), rounding="half_even"
                )
                self.costs = SpotFeeModel(maker=costs, taker=costs)
                self.limits = SpotLimits(
                    maximum=self.quantity("10"),
                    lot=self.quantity("1"),
                    tick=self.price("0.01"),
                    product="spot",
                    specification_identity="a" * 64,
                    minimum_order=self.quantity("1"),
                )

        class _LiveFactories:
            """Reconstruct the exact reviewed companion types from packaged parameters."""

            def __init__(self, scenario: _LiveScenario) -> None:
                """Bind the study's selected instrument and feature signature."""
                self.scenario = scenario

            def feature(self, schema: FeatureSchema, payload: bytes) -> FeatureKernel:
                """Reload the book-signal square only under its published schema."""
                _CandidateAcceptance._require_parameters(payload, {})
                if schema != self.scenario.feature.schema:
                    raise ValueError("live candidate feature schema differs")
                return _Feature(self.scenario.requirement)

            def policy(self, payload: bytes) -> DecisionPolicy:
                """Reload the authored passive order without selecting an executable adapter."""
                _CandidateAcceptance._require_parameters(payload, {"limit": "99", "quantity": "1"})
                return _OrderPolicy(self.scenario)

            def metric(self, payload: bytes) -> MetricDefinition:
                """Reload the retained synthetic study fill count metric."""
                _CandidateAcceptance._require_parameters(payload, {})
                return _FillCountMetric()

            def chart(self, payload: bytes) -> ChartDefinition:
                """Reload the retained synthetic study profit chart."""
                _CandidateAcceptance._require_parameters(payload, {})
                return _ProfitChart()

            def register(self, implementation_sha256: str) -> CandidateComponents:
                """Pin every reconstructed factory to the copied installed source bytes."""
                return CandidateComponents(
                    features={"fresh-square": FeatureFactory(implementation_sha256, self.feature)},
                    policies={"fresh-policy": PolicyFactory(implementation_sha256, self.policy)},
                    metrics={"fresh-fill-count": MetricFactory(implementation_sha256, self.metric)},
                    charts={"fresh-profit-chart": ChartFactory(implementation_sha256, self.chart)},
                )

        self.output.mkdir(parents=True, exist_ok=True)
        scenario = _LiveScenario(config)
        policy = _OrderPolicy(scenario)
        codec = DomainCodec()
        companion = Path(__file__).parent
        support_sources = tuple(sorted((companion / "research_workflows").glob("*.py")))
        implementation_sources = (
            companion / "decision_study.py",
            companion / "candidate_workflow.py",
            Path(__file__),
            *support_sources,
        )
        implementation_payload = codec.encode_json(
            tuple(source.read_bytes() for source in implementation_sources)
        )
        implementation_sha256 = hashlib.sha256(implementation_payload).hexdigest()
        artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name="installed-live-book-candidate-factories",
                sha256=implementation_sha256,
            ),
            payload=implementation_payload,
        )
        study: DecisionStudy = scenario.study(
            policy,
            fitted=False,
            passive=True,
            family=f"installed-{config.venue}-book-paper-engineering",
        )
        study = replace(study, extensions=(scenario.artifact.fingerprint, artifact.fingerprint))
        study_components: StudyComponents = scenario.components(policy, fitted=False, passive=True)
        study_components = dataclass_replace(
            study_components,
            capabilities=(
                "product:spot",
                "calendar:continuous-utc",
                "intent:order",
                "feature:batch",
                "input:book",
            ),
            artifacts=(*study_components.artifacts, artifact),
        )
        attempts = self.output / "attempts"
        history = evaluate_study(
            study,
            components=study_components,
            attempts=attempts,
            publication=PublicationPolicy(mode="local"),
        )
        if history.status != "completed":
            raise ValueError("live paper candidate requires a completed engineering study")
        bundle_root = self.output / "candidate"
        requirements = self._requirements()
        manifest = _CandidateAcceptance._bundle(
            bundle_root,
            study=study,
            history=history,
            store=AttemptStore(attempts),
            learned=False,
            implementation_sha256=implementation_sha256,
            implementation_payload=implementation_payload,
            requirements=requirements,
            cadence_us=1_000_000,
            on_gap="reset",
            metric_currency=config.quote_currency,
        )
        components = _LiveFactories(scenario).register(implementation_sha256)
        registry = self._registry(requirements)
        request = CaptureRequest(
            config=config,
            recording_id=str(uuid4()),
            implementation_identity=InstalledIdentity.sha256(),
        )
        source_identity = LiveBookDecisionSource(
            request, scenario.requirement, history_capacity=10_000
        ).identity
        starts_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=2)
        deployment: CandidateDeployment = _CandidateAcceptance._deployment(
            manifest,
            mode="runtime",
            instance=f"{config.venue}-book-paper",
            source_identity=source_identity,
            starts_at=starts_at,
        )
        bundle = CandidateBundle(bundle_root)
        CandidateLoader(components, registry).load(bundle, deployment)
        paper = PaperConfiguration(
            account=f"{config.venue}-book-paper",
            mode="paper",
            initial_cash=Money(value=Decimal("1000"), currency=scenario.currency),
            maximum=scenario.quantity("10"),
            lot=scenario.quantity("1"),
            tick=scenario.price("0.01"),
            maximum_fee=Money(value=Decimal("1"), currency=scenario.currency),
            fee_rate=Decimal("0.002"),
            market_max_age_us=5_000_000,
            execution=PaperExecutionScenario(
                venue="okx" if config.venue == "okx" else "bitfinex",
                instrument_id=scenario.quantity("1").dimension.instrument_id,
                entry_delay_us=0,
                cancel_delay_us=0,
                adverse=scenario.price("0"),
                fee_rate=Decimal("0.002"),
                take_fraction=Decimal("1"),
                gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
            ),
        )
        (self.output / "candidate-deployment.json").write_bytes(codec.encode_json(deployment))
        (self.output / "capture-request.json").write_bytes(codec.encode_json(request))
        (self.output / "paper-config.json").write_bytes(codec.encode_json(paper))
        result = await run_live_paper(
            bundle,
            deployment,
            paper,
            components=components,
            registry=registry,
            request=request,
            capture_output=self.output / "capture",
            journal_path=self.output / "paper.sqlite3",
            owner=f"{config.venue}-book-paper-consumer",
            history_capacity=10_000,
        )
        if result.capture.request != request or result.paper.submission_attempted is not False:
            raise ValueError("live paper run differs from its admitted capture or safe mode")
        (self.output / "book-registry.json").write_bytes(codec.encode_json(result.book_registry))
        proof = self._prove_saved_replay(
            request=request,
            bundle=bundle,
            deployment=deployment,
            paper=paper,
            components=components,
            registry=registry,
            journal_path=self.output / "paper.sqlite3",
        )
        summary: dict[str, object] = {
            "venue": config.venue,
            "symbol": config.symbol,
            "candidate": manifest.identity,
            "deployment": deployment.identity,
            "source": source_identity,
            "recording": request.identity,
            "book_registry": result.book_registry.identity,
            "capture_root": str(result.capture.root),
            "capture_summary": result.capture.summary,
            "paper_journal": str(self.output / "paper.sqlite3"),
            "paper_checkpoint": result.paper.checkpoint,
            "paper_orders": len(result.paper.orders),
            "paper_fills": len(result.paper.ledger.fills),
            "submission_attempted": result.paper.submission_attempted,
            "study_qualification": "engineering",
            "saved_replay": proof,
        }
        (self.output / "summary.json").write_bytes(codec.encode_json(summary))
        return summary


class _Arguments(argparse.Namespace):
    """Keep the standalone native selection and evidence path typed."""

    config: Path
    output: Path


def main() -> None:
    """Run one selected public-book paper capture with installed candidate artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    config = CaptureConfig.read(args.config)
    result = asyncio.run(_LiveCandidateConsumer(config, args.output).run())
    print(DomainCodec().encode_json(result).decode(), flush=True)


if __name__ == "__main__":
    main()
