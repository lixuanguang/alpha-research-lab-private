"""Verify offline, Feast, paper, shadow, and restart candidate runtime behavior."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from applications.paper import PaperRunResult, PaperTimer, run_paper
from configuration import (
    CandidateDeployment,
    CapabilityRegistry,
    PaperConfiguration,
    PaperExecutionScenario,
)
from execution import PaperMarket, PaperOrderJournal
from financial_units import Money
from research.experiments import CandidateBundle, CandidateManifest
from research.features import (
    FeastOfflineWorker,
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureStoreDefinition,
    StoredFeature,
    VersionedFeatureStore,
)
from risk import SpotLimits
from runtime import (
    CandidateComponents,
    CandidateFeatureFeed,
    CandidateLoader,
    CandidateSession,
    CandidateStep,
    PaperCandidateRuntime,
    PaperCheckpoint,
)
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent

# project library imports
from .candidate_bundle import _CandidateAcceptance, _ScenarioView


class _FeatureCandidateAcceptance:
    """Prove packaged candidates consume pinned offline and optional real Feast values."""

    def __init__(self, root: Path, worker_python: Path | None) -> None:
        """Open an authoritative store and optionally bind an isolated Feast worker."""
        self.root = root
        self.root.mkdir()
        self.bridge: FeastServingBridge | None = None
        if worker_python is not None:
            spec = find_spec("applications.explore.command")
            if spec is None or spec.origin is None:
                raise ValueError("installed Feast worker command is missing")
            command = (
                str(worker_python.absolute()),
                "-I",
                "-c",
                "from runpy import run_path; "
                f"raise SystemExit(run_path({spec.origin!r})['main'](['feast-serving-worker']))",
            )
            self.bridge = FeastServingBridge(FeastOfflineWorker(command, timeout_seconds=120))
        self.store = VersionedFeatureStore.open(root / "features.sqlite3")
        self.serving_root = root / "serving"

    def exercise(
        self,
        *,
        name: str,
        bundle: CandidateBundle,
        manifest: CandidateManifest,
        components: CandidateComponents,
        scenario: _ScenarioView,
        source_deployment: CandidateDeployment,
        source_step: CandidateStep,
        decision_second: int,
    ) -> dict[str, object]:
        """Pin a real snapshot and compare source, offline and optional Feast intents."""
        assert manifest.feature_store is not None and source_step.feature is not None
        definition = DomainCodec().decode_json(
            bundle.artifact(manifest.feature_store), FeatureStoreDefinition
        )
        vector = source_step.feature
        self.store.register(definition)
        self.store.append(
            definition,
            StoredFeature(
                definition_identity=definition.identity,
                vector=vector,
                source_version=scenario.source.identity,
                source_sha256=_CandidateAcceptance._sha(
                    DomainCodec().encode_json((scenario.source.identity, vector.input_identity))
                ),
                dataset_version=manifest.dataset.sha256,
                dataset_sha256=manifest.dataset.sha256,
                revision_identity=_CandidateAcceptance._sha(DomainCodec().encode_json(vector)),
            ),
        )
        version = f"{name}-selected"
        snapshot = self.store.materialize(definition, version, vector.decision_at, (vector.entity,))
        self.store.activate(definition, version)
        offline = replace(
            source_deployment,
            name=f"{name}-offline",
            input_mode="offline_features",
            source_identity=snapshot.identity,
            feature_version=version,
        )
        registry = _CandidateAcceptance._registry(manifest.requirements)
        loader = CandidateLoader(components, registry)
        offline_session = CandidateSession(loader.load(bundle, offline))
        offline_step = CandidateFeatureFeed(self.store).evaluate(
            offline_session, vector.decision_at
        )
        assert source_step.status == offline_step.status == "decided"
        assert source_step.feature == offline_step.feature
        assert source_step.prediction == offline_step.prediction
        assert source_step.decision is not None and offline_step.decision is not None
        assert source_step.decision.intent == offline_step.decision.intent
        proof: dict[str, object] = {
            "snapshot": snapshot.identity,
            "source_offline_equal": True,
        }
        if self.bridge is None:
            return proof
        serving = FeastServingSnapshot.from_materialization(snapshot)
        self.bridge.materialize(serving, self.serving_root)
        online = replace(
            source_deployment,
            name=f"{name}-online",
            mode="runtime",
            input_mode="online_features",
            source_identity=snapshot.identity,
            feature_version=version,
        )
        online_session = CandidateSession(loader.load(bundle, online))
        online_feed = CandidateFeatureFeed(
            self.store, bridge=self.bridge, serving_root=self.serving_root
        )
        online_step = online_feed.evaluate(online_session, vector.decision_at)
        assert online_step.status == "decided"
        assert source_step.feature == online_step.feature
        assert source_step.prediction == online_step.prediction
        assert online_step.decision is not None
        assert source_step.decision.intent == online_step.decision.intent
        market_events = _PaperCandidateAcceptance._events(name, scenario, decision_second)
        paper, paper_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="online",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=online_feed,
            decision_second=decision_second,
            events=market_events,
        )
        assert paper_step.status == "decided" and paper_step.decision is not None
        assert paper_step.feature == source_step.feature
        assert paper_step.prediction == source_step.prediction
        assert paper_step.decision.intent == source_step.decision.intent
        assert len(paper.orders) == len(paper.ledger.fills) == 1
        assert paper.checkpoint.candidate.policy.last_at == vector.decision_at
        assert paper.submission_attempted is False
        checkpoint = online_session.checkpoint()
        stale = online_feed.evaluate(online_session, vector.decision_at + timedelta(seconds=10))
        assert stale.status == "paused" and stale.checkpoint == checkpoint
        lost_session = CandidateSession(loader.load(bundle, online))
        unavailable = CandidateFeatureFeed(
            self.store, bridge=self.bridge, serving_root=self.root / "missing-serving"
        ).evaluate(lost_session, vector.decision_at)
        assert (
            unavailable.status == "paused" and unavailable.checkpoint == lost_session.checkpoint()
        )
        lost_paper, lost_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="service-loss",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=CandidateFeatureFeed(
                self.store, bridge=self.bridge, serving_root=self.root / "missing-serving"
            ),
            decision_second=decision_second,
            events=market_events[:2],
        )
        assert lost_step.status == "paused" and lost_step.reason == "feature-service-unavailable"
        assert lost_paper.orders == () and lost_paper.ledger.fills == ()
        assert lost_paper.checkpoint.candidate.policy.last_at is None
        changed_version = f"{name}-changed"
        self.store.materialize(definition, changed_version, vector.decision_at, (vector.entity,))
        self.store.activate(definition, changed_version)
        changed_session = CandidateSession(loader.load(bundle, online))
        changed = online_feed.evaluate(changed_session, vector.decision_at)
        assert changed.status == "paused" and changed.reason == "feature-version-changed"
        assert changed.checkpoint == changed_session.checkpoint()
        changed_paper, changed_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="version-change",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=online_feed,
            decision_second=decision_second,
            events=market_events[:2],
        )
        assert changed_step.status == "paused" and changed_step.reason == "feature-version-changed"
        assert changed_paper.orders == () and changed_paper.ledger.fills == ()
        assert changed_paper.checkpoint.candidate.policy.last_at is None
        self.store.activate(definition, version)
        proof.update(
            source_offline_online_equal=True,
            online_paper_intent_equal=True,
            online_paper_fill_count=len(paper.ledger.fills),
            online_paper_service_loss_paused=True,
            online_paper_version_change_paused=True,
            stale_paused=True,
            service_loss_paused=True,
            version_change_paused=True,
        )
        return proof


class _PaperCandidateAcceptance:
    """Exercise packaged source candidates in dedicated paper and shadow accounts."""

    @staticmethod
    def _config(
        name: str, mode: Literal["paper", "shadow"], scenario: _ScenarioView
    ) -> PaperConfiguration:
        """Declare a finite, cash-backed local spot scenario for one candidate."""
        return PaperConfiguration(
            account=f"{name}-{mode}-account",
            mode=mode,
            initial_cash=Money(value=Decimal("1000"), currency=scenario.currency),
            maximum=scenario.quantity("10"),
            lot=scenario.quantity("1"),
            tick=scenario.price("0.01"),
            maximum_fee=Money(value=Decimal("1"), currency=scenario.currency),
            fee_rate=Decimal("0.002"),
            market_max_age_us=5_000_000,
            execution=PaperExecutionScenario(
                venue="okx",
                instrument_id=scenario.quantity("1").dimension.instrument_id,
                entry_delay_us=0,
                cancel_delay_us=0,
                adverse=scenario.price("0"),
                fee_rate=Decimal("0.002"),
                take_fraction=Decimal("1"),
                gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
            ),
        )

    @staticmethod
    def _events(
        name: str, scenario: _ScenarioView, decision_second: int
    ) -> tuple[PaperMarket | PaperTimer, ...]:
        """Place one authored timer between an eligible quote and later finite touches."""
        return (
            PaperMarket(
                identity=f"{name}-before",
                at=scenario.at(decision_second - 1),
                bid=scenario.price("98"),
                ask=scenario.price("100"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("5"),
            ),
            PaperTimer(identity=f"{name}-decision", at=scenario.at(decision_second)),
            PaperMarket(
                identity=f"{name}-entry",
                at=scenario.at(decision_second + 1),
                bid=scenario.price("98"),
                ask=scenario.price("100"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("1"),
            ),
            PaperMarket(
                identity=f"{name}-cross",
                at=scenario.at(decision_second + 2),
                bid=scenario.price("98"),
                ask=scenario.price("99"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("1"),
            ),
        )

    @staticmethod
    def _saved_step(
        *,
        journal_path: Path,
        name: str,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        config: PaperConfiguration,
    ) -> CandidateStep:
        """Reopen the actual timer step from the account's durable paper journal."""
        loaded = CandidateLoader(components, registry).load(bundle, deployment)
        journal = PaperOrderJournal(
            journal_path,
            account=config.account,
            instance=deployment.instance,
            binding_identity=PaperCandidateRuntime.binding(loaded, config),
            mode=config.mode,
            limits=SpotLimits(
                maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"
            ),
            ledger_state=LedgerState(
                initial_cash=config.initial_cash, dimension=config.maximum.dimension
            ),
            fee_rate=Decimal("0.002"),
        )
        saved = journal.step(f"timer:{name}-decision")
        assert saved is not None
        return DomainCodec().decode_json(saved.result_bytes, CandidateStep)

    @classmethod
    def run_online(
        cls,
        *,
        root: Path,
        name: str,
        case: str,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        scenario: _ScenarioView,
        feed: CandidateFeatureFeed,
        decision_second: int,
        events: tuple[PaperMarket | PaperTimer, ...],
    ) -> tuple[PaperRunResult, CandidateStep]:
        """Run a pinned online candidate and reopen its durable timer decision."""
        config = cls._config(f"{name}-feast-{case}", "paper", scenario)
        journal_path = root / f"{name}-feast-{case}.sqlite3"
        result = run_paper(
            bundle,
            deployment,
            config,
            components=components,
            registry=registry,
            journal_path=journal_path,
            events=events,
            opened_at=scenario.at(decision_second - 1),
            owner=f"{name}-feast-{case}-owner",
            source=None,
            features=feed,
        )
        return result, cls._saved_step(
            journal_path=journal_path,
            name=name,
            bundle=bundle,
            deployment=deployment,
            components=components,
            registry=registry,
            config=config,
        )

    @classmethod
    def exercise(
        cls,
        *,
        root: Path,
        name: str,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        scenario: _ScenarioView,
        source_step: CandidateStep,
        decision_second: int,
    ) -> tuple[dict[str, object], PaperCheckpoint, CandidateStep]:
        """Compare pure decisions, exact fills and reopened journal economics."""
        events = cls._events(name, scenario, decision_second)
        opened_at = scenario.at(decision_second - 1)
        paper_config = cls._config(name, "paper", scenario)
        paper_path = root / f"{name}-paper.sqlite3"
        paper = run_paper(
            bundle,
            deployment,
            paper_config,
            components=components,
            registry=registry,
            journal_path=paper_path,
            events=events,
            opened_at=opened_at,
            owner=f"{name}-paper-first",
            source=scenario.source,
        )
        shadow = run_paper(
            bundle,
            deployment,
            cls._config(name, "shadow", scenario),
            components=components,
            registry=registry,
            journal_path=root / f"{name}-shadow.sqlite3",
            events=events,
            opened_at=opened_at,
            owner=f"{name}-shadow-first",
            source=scenario.source,
        )
        assert len(paper.orders) == len(shadow.orders) == 1
        paper_order, shadow_order = paper.orders[0], shadow.orders[0]
        assert paper_order.intent == shadow_order.intent
        assert paper_order.status == "filled" and shadow_order.status == "intent"
        assert source_step.decision is not None
        if isinstance(source_step.decision.intent, OrderIntent):
            assert source_step.decision.intent == paper_order.intent
        else:
            assert isinstance(source_step.decision.intent, TargetIntent)
            assert source_step.decision.intent.quantity == paper_order.intent.quantity
            assert paper_order.intent.time_in_force == "ioc"
        assert shadow.ledger.fills == ()
        (fill,) = paper.ledger.fills
        expected_price = Decimal("100" if name == "learned" else "99")
        expected_cash = Decimal("899.80" if name == "learned" else "900.80")
        assert fill.quantity.value == Decimal("1")
        assert fill.effective.value == expected_price
        assert fill.reference == fill.effective
        assert fill.fee.value == Decimal("0.20")
        balance = Ledger(paper.ledger).balance
        assert balance.cash.value == expected_cash
        assert balance.holding.value == Decimal("1")
        assert balance.fees.value == Decimal("0.20")
        assert paper.submission_attempted is False and shadow.submission_attempted is False
        restarted = run_paper(
            bundle,
            deployment,
            paper_config,
            components=components,
            registry=registry,
            journal_path=paper_path,
            events=events,
            opened_at=scenario.at(decision_second + 2),
            owner=f"{name}-paper-restarted",
            source=scenario.source,
        )
        assert restarted.ledger == paper.ledger
        assert restarted.orders == paper.orders
        assert restarted.checkpoint.order_sequence == paper.checkpoint.order_sequence
        proof: dict[str, object] = {
            "paper_shadow_intent_equal": True,
            "paper_status": paper_order.status,
            "shadow_status": shadow_order.status,
            "paper_fill_quantity": str(fill.quantity.value),
            "paper_fill_price": str(fill.effective.value),
            "paper_fee": str(fill.fee.value),
            "paper_cash": str(balance.cash.value),
            "shadow_zero_fills": True,
            "restart_no_duplicate_effects": True,
            "submission_attempted": False,
        }
        step = cls._saved_step(
            journal_path=paper_path,
            name=name,
            bundle=bundle,
            deployment=deployment,
            components=components,
            registry=registry,
            config=paper_config,
        )
        assert step.prediction == source_step.prediction
        return proof, paper.checkpoint, step
