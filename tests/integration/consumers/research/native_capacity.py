"""Measure R1's research workflow on a captured OKX BTC/ETH books and trades corpus.

Native publication, digest reopen and audit; completed-return features over captured
books, materialized with Feast, every PIT cell against an independent scan, warm close
latency and bounded offline Feast chunks; four costed trials on two workers with a
killed worker, recovery and an uninterrupted control; report reopen; backup and
restore. Copy this file and ``capacity_workload.py`` (whose measurement it reuses)
outside the checkout, side by side, and run them with the installed research interpreter
(``-E -s`` rather than ``-I``, so the sibling module is importable):

  python -E -s native_capacity.py --runs /abs/corpus/runs --window /abs/corpus/window.json \
    --output /abs/new-attempt --worker-python /abs/research-worker/.venv/bin/python
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import signal
import sys
import time
from bisect import bisect_right
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
from capacity_workload import _OFFLINE_FIXTURE_SOURCE as _AUTHORED_FIXTURE
from capacity_workload import _Measurements, _TrackedFeastWorker, _TrackedProcess

# project library imports
from applications.explore import StudyComponents, StudyJobHandler, evaluate_study, schedule_study
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import (
    BookSnapshot,
    DatasetPublication,
    PublicTradeManifest,
    SnapshotStore,
)
from market_data.query import BookQuery
from market_data.storage import RawStore
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, Fingerprint, TemporalSplit, TimeWindow
from research.exploration import (
    BookSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import (
    CompletedReturnFeature,
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureEntity,
    FeatureMaterializer,
    FeatureObservation,
    FeatureSchema,
    FeatureSession,
    FeatureStoreDefinition,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
    VersionedFeatureStore,
)
from research.observations import DecisionInputs, InputRequirement, NumericField
from research.studies import (
    CapturedStudyMarket,
    DecisionStudy,
    LedgerCurveChart,
    NetReturnMetric,
    PublicationPolicy,
    StudyArtifact,
    StudyFold,
    StudyMarketSource,
    StudyReportReader,
    StudyResult,
)
from risk import SpotLimits
from runtime import (
    ImplementationIdentity,
    JobQueue,
    JobRun,
    JobSpec,
    JobWorkerPool,
    WorkspaceBackup,
)
from serialization import DomainCodec
from simulation import (
    IntentMarket,
    IntentSimulationResult,
    IntentSimulationSpec,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)
from strategies import ConfirmedSignal

_LIMIT = 4_000_000_000
_CADENCE = 60
_CLOSE_LATENCY_CADENCE = 5
_MAX_AGE_US = 15_000_000
# A book batch holds whole 400-level books: the batch, not the corpus, bounds memory, and
# a close that crosses a batch decodes it, so a small batch keeps close latency even.
_BATCH = 32
_FEEDS = ("okx-btc-usdt-books", "okx-btc-usdt-trades", "okx-eth-usdt-books", "okx-eth-usdt-trades")
# Authored (lot, tick, quantity) for the reference trials; not venue-verified.
_GRID = {"BTC": ("0.00001", "0.1", "0.006"), "ETH": ("0.00001", "0.01", "0.1")}
_OFFLINE_FIXTURE_SOURCE = (
    _AUTHORED_FIXTURE.replace("running_mean", "completed_return")
    .replace("capacity_mean_source", "native_return_source")
    .replace("research_capacity_diagnostic", "research_native_capacity")
)


class _Window(msgspec.Struct):
    """The declared fixed collection window."""

    start_at: datetime
    stop_at: datetime


class _Progress(msgspec.Struct):
    """A run's committed raw positions."""

    committed_records: int


class _Segment(msgspec.Struct):
    """A segment's place in its chain."""

    ordinal: int


class _SegmentRequest(msgspec.Struct):
    """A segment request; the first segment of an unchained capture has none."""

    segment: _Segment | None = None


class _Published(msgspec.Struct):
    """The snapshot identities one capture publication produced."""

    books: str
    trades: tuple[str, ...]


class _Corpus:
    """The captured runs, their fixed window and their committed raw positions."""

    def __init__(self, runs: Path, window: Path) -> None:
        """Read the declared window and each run's committed record count."""
        declared = msgspec.json.decode(window.read_bytes(), type=_Window)
        self.runs = runs
        self.start, self.end = declared.start_at, declared.stop_at
        self.records = {
            feed: msgspec.json.decode(
                (runs / feed / "progress.json").read_bytes(), type=_Progress
            ).committed_records
            for feed in _FEEDS
        }

    def last_segments(self) -> tuple[Path, ...]:
        """Select each run's last segment, which carries its whole chain."""
        selected = []
        for feed in _FEEDS:
            found: list[tuple[int, Path]] = []
            for directory in (self.runs / feed / "segments").iterdir():
                request = directory / "request.json"
                if request.is_file():
                    segment = msgspec.json.decode(
                        request.read_bytes(), type=_SegmentRequest
                    ).segment
                    found.append((0 if segment is None else segment.ordinal, directory))
            selected.append(max(found)[1])
        return tuple(selected)

    def decisions(self, cadence: int) -> tuple[datetime, ...]:
        """Return every close strictly inside the window at a fixed cadence."""
        out, at = [], self.start + timedelta(seconds=cadence)
        while at < self.end:
            out.append(at)
            at += timedelta(seconds=cadence)
        return tuple(out)


class _EntitySources:
    """Dispatch one feature definition's reads to each instrument's own saved source."""

    def __init__(self, sources: dict[str, SavedDecisionSource]) -> None:
        """Require one shared requirement signature across instruments."""
        if len({source.requirements for source in sources.values()}) != 1:
            raise ValueError("entity sources differ in requirements")
        self._sources = sources

    @property
    def identity(self) -> str:
        """Pin every instrument's selection."""
        return hashlib.sha256(
            DomainCodec().encode_json(sorted((e, s.identity) for e, s in self._sources.items()))
        ).hexdigest()

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the shared requirement signature."""
        return next(iter(self._sources.values())).requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Read the entity's own captured book at the cutoff."""
        return self._sources[entity].read(entity, at)


class _Accounting:
    """Recompute a trial's fees, cash, holding and NAV from its fills, independently."""

    @staticmethod
    def check(economics: IntentSimulationResult) -> None:
        """Require every taker fee and the terminal mark to equal exact recomputation."""
        state = economics.ledger
        minor = state.initial_cash.currency.minor_unit
        cash = Fraction(state.initial_cash.value)
        holding = Fraction(0)
        for fill in state.fills:
            notional = Fraction(abs(fill.quantity.value)) * Fraction(fill.effective.value)
            fee = Decimal(notional.numerator) / Decimal(notional.denominator) * Decimal("0.001")
            if fill.fee.value != fee.quantize(minor, rounding=ROUND_HALF_UP):
                raise AssertionError(f"fill fee differs from exact recomputation: {fill}")
            cash -= Fraction(fill.quantity.value) * Fraction(fill.effective.value)
            cash -= Fraction(fill.fee.value)
            holding += Fraction(fill.quantity.value)
        if economics.mark is None:
            return
        price = economics.valuation_price
        value = Fraction(0) if price is None else holding * Fraction(price.value)
        if Fraction(economics.mark.nav.value) != cash + value:
            raise AssertionError("terminal NAV differs from exact recomputation")


class _BlockingMarket:
    """Keep a market's identity but never return from a read: the injected fault."""

    def __init__(self, market: StudyMarketSource) -> None:
        """Wrap the real market."""
        self._market = market

    @property
    def identity(self) -> str:
        """Report the wrapped market's identity, so the study binding is unchanged."""
        return self._market.identity

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Block until the parent kills this process."""
        while True:
            time.sleep(60)


class _TimedHandler:
    """Count concurrently active workers around the real study handler."""

    def __init__(self, handler: StudyJobHandler, measurements: _Measurements) -> None:
        """Bind the handler and a thread-safe active-worker counter."""
        # standard library imports
        import threading

        self.handler, self.m = handler, measurements
        self.active = self.peak = 0
        self._lock = threading.Lock()

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Run one trial and record its duration."""
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        started = time.perf_counter()
        try:
            return self.handler.execute(spec, run)
        finally:
            self.m.record("study-worker", started, job=spec.job_id)
            with self._lock:
                self.active -= 1


class _Workflow:
    """R1's combined workflow over the captured corpus."""

    def __init__(
        self,
        measurements: _Measurements,
        corpus: _Corpus,
        worker_python: Path,
        artifact: StudyArtifact,
        bridge: FeastServingBridge,
        runner: _TrackedProcess,
        offline_command: tuple[str, ...],
    ) -> None:
        """Bind the attempt root and shared services."""
        self.m, self.corpus, self.worker_python = measurements, corpus, worker_python
        self.artifact, self.bridge, self.runner = artifact, bridge, runner
        self.offline_command = offline_command
        self.root = measurements.root
        self.snapshots, self.raw = self.root / "snapshots", RawStore(self.root / "raw")
        self.readers = SourceAdapters()
        self.decisions = corpus.decisions(_CADENCE)
        self.requirement = InputRequirement(
            name="book",
            family="book",
            clock="receipt",
            field=NumericField(name="bid", units="quote/base"),
            max_age_us=_MAX_AGE_US,
        )
        self.schema = FeatureSchema(
            implementation="completed-return",
            inputs=(self.requirement,),
            outputs=(NumericField(name="completed_return", units="dimensionless"),),
            parameters=(("cadence_seconds", str(_CADENCE)),),
            mode="incremental",
            ttl_us=_CADENCE * 1_000_000,
        )
        self.definition = FeatureStoreDefinition(
            name="r1b-completed-return",
            entity_type="instrument",
            schema=self.schema,
            instance="r1b-stream",
        )

    # Publication -------------------------------------------------------------------

    def publish(self) -> None:
        """Publish every chain, then reopen by digest and audit by re-derivation."""
        self.snapshots.mkdir()
        (self.root / "raw").mkdir()
        started = time.perf_counter()
        published = DatasetPublication(
            self.readers, ImplementationIdentity.sha256()
        ).publish_captures(
            self.corpus.last_segments(),
            self.raw,
            self.snapshots,
            max_records=1_000_000,
            max_bytes=_LIMIT,
        )
        records = sum(self.corpus.records.values())
        self.m.record(
            "publication",
            started,
            raw_positions=records,
            raw_positions_by_feed=self.corpus.records,
        )
        (self.root / "published.json").write_bytes(DomainCodec().encode_json(published))
        self.m.checkpoint("publication")
        self._components()
        started = time.perf_counter()
        BookSnapshot.read(
            self.snapshots,
            self.raw,
            readers=self.readers,
            identity=published.book,
            max_bytes=_LIMIT,
        )
        for identity in published.trades:
            SnapshotStore(
                self.snapshots, self.raw, readers=self.readers, manifest_type=PublicTradeManifest
            ).read(identity, max_bytes=_LIMIT)
        self.m.record("reopen-digest", started)
        started = time.perf_counter()
        BookSnapshot.read(
            self.snapshots,
            self.raw,
            readers=self.readers,
            identity=published.book,
            max_bytes=_LIMIT,
            rederive=True,
        )
        self.m.record("audit-rederive-books", started)

    def _components(self) -> None:
        """Record stored bytes of raw objects, book partitions and trade snapshots."""
        sizes: dict[str, int] = {}
        for path in (self.root / "raw").rglob("*"):
            if path.is_file():
                sizes["raw"] = sizes.get("raw", 0) + path.stat().st_size
        for path in self.snapshots.rglob("*"):
            if path.is_file():
                sizes["snapshots"] = sizes.get("snapshots", 0) + path.stat().st_size
        (self.root / "stored-bytes.json").write_text(json.dumps(sizes))

    def _published(self) -> tuple[str, tuple[str, ...]]:
        """Return the book and trades snapshot identities."""
        published = msgspec.json.decode(
            (self.root / "published.json").read_bytes(), type=_Published
        )
        return published.books, published.trades

    # Features ------------------------------------------------------------------------

    def _book(self) -> tuple[BookSnapshot, dict[str, str]]:
        """Open the book snapshot and map each instrument to its request identity."""
        book = BookSnapshot.read(
            self.snapshots,
            self.raw,
            readers=self.readers,
            identity=self._published()[0],
            max_bytes=_LIMIT,
        )
        return book, {
            str(book.selection(identity).request.config.instrument_id): identity
            for identity in book.request_identities
        }

    def entities(self) -> dict[str, tuple[str, str, str]]:
        """Map each instrument to (request identity, base currency, quote currency)."""
        book, requests = self._book()
        out = {}
        for entity, identity in sorted(requests.items()):
            config = book.selection(identity).request.config
            out[entity] = (identity, config.base_currency, config.quote_currency)
        return out

    def source(self, entity: str, request: str) -> SavedDecisionSource:
        """One instrument's captured book over the whole window."""
        query = BookQuery(
            snapshot_id=self._published()[0],
            request_identity=request,
            instrument=InstrumentId.from_canonical_text(entity),
            start=self.corpus.start,
            end=self.corpus.end,
            known_at=self.corpus.end,
            columns=("bids", "asks"),
            batch_size=_BATCH,
            max_bytes=_LIMIT,
        )
        return SavedDecisionSource(
            ResearchReader(self.snapshots, self.raw, readers=self.readers),
            ResearchSelection(inputs=(BookSelection(name="book", query=query),)),
            (self.requirement,),
        )

    def features(self) -> None:
        """Initialize, time warm closes, materialize with Feast and check every PIT cell."""
        entities = self.entities()
        sources = {e: self.source(e, request) for e, (request, _, _) in entities.items()}
        for entity, source in sources.items():
            started = time.perf_counter()
            source.read(entity, self.decisions[0])
            self.m.record("feature-source-initialization", started, entity=entity)
        dense = self.corpus.decisions(_CLOSE_LATENCY_CADENCE)
        kernel = CompletedReturnFeature(
            FeatureSchema(
                implementation="completed-return",
                inputs=(self.requirement,),
                outputs=self.schema.outputs,
                parameters=(("cadence_seconds", str(_CLOSE_LATENCY_CADENCE)),),
                mode="incremental",
                ttl_us=_CLOSE_LATENCY_CADENCE * 1_000_000,
            )
        )
        for entity, source in sources.items():
            session = FeatureSession(kernel, instance="close-latency", entity=entity)
            for at in dense:
                started = time.perf_counter()
                session.evaluate(source.read(entity, at))
                self.m.record("warm-close", started)
        composite = _EntitySources(sources)
        store = VersionedFeatureStore.open(self.root / "features" / "history.sqlite3")
        lineage = hashlib.sha256(DomainCodec().encode_json(self._published())).hexdigest()
        started = time.perf_counter()
        result = FeatureMaterializer().materialize(
            store,
            self.definition,
            source=composite,
            kernel=CompletedReturnFeature(self.schema),
            instance="r1b-stream",
            entities=tuple(sources),
            decisions=self.decisions,
            source_version=composite.identity,
            source_sha256=lineage,
            dataset_version="r1b-corpus",
            dataset_sha256=lineage,
            version="complete",
            bridge=self.bridge,
            serving_root=self.root / "serving",
        )
        self.m.record(
            "feature-materialization-with-feast",
            started,
            rows=len(self.decisions) * len(sources),
            identity=result.identity,
        )
        expected = self._independent_returns(entities)
        rows: list[tuple[str, datetime, ExactRatio | None, datetime, datetime]] = []
        mismatches: list[object] = []
        present = 0
        for entity in sources:
            for at in self.decisions:
                started = time.perf_counter()
                value = store.retrieve_offline(self.definition, entity, at)
                self.m.record("pit-retrieval", started)
                if value.feature is None:
                    mismatches.append((entity, at, "no stored row", value.status))
                    continue
                vector = value.feature.vector
                stored = vector.values[0]
                present += stored is not None
                if stored != expected[entity][at]:
                    mismatches.append((entity, at, stored, expected[entity][at]))
                rows.append((entity, at, stored, vector.event_at, vector.available_at))
        (self.root / "pit-check.json").write_bytes(
            DomainCodec().encode_json(
                {"cells": len(rows), "present": present, "mismatches": mismatches[:50]}
            )
        )
        if mismatches:
            raise AssertionError(f"{len(mismatches)} PIT cells differ from the independent scan")
        started = time.perf_counter()
        reopened = VersionedFeatureStore.open(self.root / "features" / "history.sqlite3")
        reopened.retrieve_online(self.definition, next(iter(sources)), self.decisions[-1])
        self.m.record("feature-reopen", started)
        self.m.checkpoint("features")
        self.offline_features(tuple(rows), tuple(sources))

    def _independent_returns(
        self, entities: dict[str, tuple[str, str, str]]
    ) -> dict[str, dict[datetime, ExactRatio | None]]:
        """Recompute each return from stored book rows, not through the query layer."""
        book, _ = self._book()
        out: dict[str, dict[datetime, ExactRatio | None]] = {}
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        started = time.perf_counter()
        for entity, (request, _, _) in entities.items():
            received: list[int] = []
            bids: list[Fraction | None] = []
            for row in book.observations(request):
                if row.outcome == "clock" or row.received_ns is None:
                    continue
                best = None
                if row.bids and row.asks:
                    bid = max(price for price, _ in row.bids)
                    ask = min(price for price, _ in row.asks)
                    if bid < ask:
                        best = Fraction(bid)
                received.append(row.received_ns)
                bids.append(best)
            closes: list[Fraction | None] = []
            for at in self.decisions:
                elapsed = at - epoch
                cutoff = (
                    elapsed.days * 86_400 + elapsed.seconds
                ) * 10**9 + elapsed.microseconds * 1000
                position = bisect_right(received, cutoff) - 1
                close = None
                if position >= 0 and cutoff - received[position] <= _MAX_AGE_US * 1000:
                    close = bids[position]
                closes.append(close)
            out[entity] = {}
            for index, at in enumerate(self.decisions):
                previous = closes[index - 1] if index else None
                current = closes[index]
                out[entity][at] = (
                    None
                    if previous is None or current is None
                    else ExactRatio.from_fraction(current / previous - 1)
                )
        self.m.record("independent-return-scan", started)
        return out

    def offline_features(
        self,
        rows: tuple[tuple[str, datetime, ExactRatio | None, datetime, datetime], ...],
        entities: tuple[str, ...],
    ) -> None:
        """Reconcile every present PIT cell through bounded offline Feast chunks."""
        root = self.root / "offline-feast"
        root.mkdir()
        repository = root / "repository"
        present = tuple(row for row in rows if row[2] is not None)
        source_rows = [
            {
                "instrument": entity,
                "feature_event_timestamp": event_at.isoformat(),
                "created_timestamp": available_at.isoformat(),
                "completed_return": f"{ratio.numerator}/{ratio.denominator}",
            }
            for entity, _, ratio, event_at, available_at in present
            if ratio is not None
        ]
        rows_path = root / "rows.json"
        rows_path.write_text(json.dumps(source_rows, separators=(",", ":")), encoding="utf-8")
        author = root / "author.py"
        author.write_text(_OFFLINE_FIXTURE_SOURCE + "\n", encoding="utf-8")
        started = time.perf_counter()
        self.runner.complete(
            self.runner.start(
                (str(self.worker_python), "-I", str(author), str(repository), str(rows_path)),
                cwd=root,
            ),
            payload=None,
            timeout=300,
        )
        source = repository / "data" / "features.parquet"
        registry = repository / "data" / "registry.db"
        definition_path = repository / "feature_store.yaml"
        self.m.record(
            "feast-offline-fixture-construction", started, source_bytes=source.stat().st_size
        )
        definition = OfflineFeatureDefinition(
            feature_name="completed_return",
            feature_ref="completed_return:completed_return",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=self.schema.ttl_us,
            sdk_version="0.66.0",
            definition_version="r1b-completed-return",
            definition_bytes=definition_path.read_bytes(),
            registry_bytes=registry.read_bytes(),
            source_version="r1b-native-feature",
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            join_key="instrument",
            repository_path=str(repository),
        )
        access = OfflineFeatureAccess(
            OfflineFeatureBridge(
                _TrackedFeastWorker(
                    self.runner,
                    self.offline_command,
                    cwd=repository,
                    timeout=300,
                    operation="offline-retrieval",
                )
            )
        )
        # Every decision whose stored return is present in every entity is reconciled.
        indexed: dict[tuple[str, datetime], tuple[str, datetime, datetime]] = {
            (entity, at): (f"{ratio.numerator}/{ratio.denominator}", ev, av)
            for entity, at, ratio, ev, av in present
            if ratio is not None
        }
        decisions = tuple(at for at in self.decisions if all((e, at) in indexed for e in entities))
        width = max(1, min(2048, len(decisions) // 3))
        chunks = reconciled = 0
        for offset in range(0, len(decisions), width):
            chunk = decisions[offset : offset + width]
            request = OfflineFeatureRequest(
                definition=definition,
                entities=tuple(
                    FeatureEntity(entity_type="instrument", entity_key=e) for e in entities
                ),
                decisions=chunk,
            )
            reference = tuple(
                FeatureObservation(
                    definition_identity=definition.identity,
                    source_version=definition.source_version,
                    source_sha256=definition.source_sha256,
                    feature_name=definition.feature_name,
                    entity_type=definition.entity_type,
                    entity_key=entity,
                    decision_at=at,
                    event_at=indexed[(entity, at)][1],
                    available_at=indexed[(entity, at)][2],
                    ttl_us=definition.ttl_us,
                    units=definition.units,
                    value=indexed[(entity, at)][0],
                )
                for entity in entities
                for at in chunk
            )
            started = time.perf_counter()
            comparison = access.compare(request, reference)
            if comparison.mismatches or len(comparison.matches) != request.expected_rows:
                raise AssertionError("Feast offline chunk differs from the durable PIT cells")
            self.m.record("feast-offline-chunk", started, chunk=chunks, cells=request.expected_rows)
            chunks += 1
            reconciled += request.expected_rows
        if chunks < 3:
            raise AssertionError("offline Feast reconciliation needs at least three chunks")
        self.m.record("feast-offline-reconciled", time.perf_counter(), cells=reconciled)
        self.m.checkpoint("offline-feast")

    # Studies -------------------------------------------------------------------------

    def study_specs(self) -> tuple[tuple[DecisionStudy, ...], dict[str, StudyComponents]]:
        """Two families (one per instrument) of two ConfirmedSignal trials each."""
        metric, chart = NetReturnMetric(), LedgerCurveChart()
        studies: list[DecisionStudy] = []
        bindings: dict[str, StudyComponents] = {}
        published = self._published()[0]
        for index, (entity, (request, base, quote)) in enumerate(self.entities().items()):
            instrument = InstrumentId.from_canonical_text(entity)
            dimension = Dimension(instrument_id=instrument, kind=QuantityKind.BASE_UNIT)
            currency = Currency.from_code(quote)
            lot, tick, size = (Decimal(v) for v in _GRID[base])
            quantity = Quantity(value=size, dimension=dimension)
            source = self.source(entity, request)
            market = CapturedStudyMarket(
                self.snapshots,
                self.raw,
                readers=self.readers,
                snapshot_id=published,
                request_identity=request,
                max_bytes=_LIMIT,
                clock_assumption="receipt-as-matching",
                max_levels=20,
            )
            execution = LimitOrderExecution(
                LimitExecutionConfig(
                    entry_delay_us=1_000,
                    cancel_delay_us=0,
                    lifetime_us=_CADENCE * 1_000_000,
                    max_book_age_us=2_000_000,
                    take_fraction=Decimal(1),
                    queue_ahead_fraction=Decimal(1),
                )
            )
            tick_price = Price(value=tick, currency=currency, per=dimension)
            costs = SpotFeeModel(
                maker=SpotCosts(
                    adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                    fee_rate=Decimal("0.0008"),
                    rounding="half_up",
                ),
                # A target lowers to an IOC at the touch, which no adverse cost could fill
                # (stage 2a, S4), so slippage is declared zero; fees stay exact.
                taker=SpotCosts(
                    adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                    fee_rate=Decimal("0.001"),
                    rounding="half_up",
                ),
            )
            validation = TimeWindow(start=self.corpus.start, end=self.corpus.end)
            split = TemporalSplit(
                training=None,
                validation=validation,
                holdout=TimeWindow(
                    start=self.corpus.end + timedelta(days=1),
                    end=self.corpus.end + timedelta(days=2),
                ),
                samples=(),
                fit_mode="none",
                fit_cutoff=None,
                embargo_us=0,
                rationale="R1b reference trials; holdout not consumed",
            )
            fold = StudyFold(
                name="r1b-validation",
                split=split,
                training_decisions=(),
                decisions=self.decisions,
                evaluated_as_of=self.corpus.end - timedelta(microseconds=1),
            )
            for trial in range(2):
                policy = ConfirmedSignal(
                    field=self.schema.outputs[0], quantity=quantity, confirmations=trial + 1
                )
                components = StudyComponents(
                    source=source,
                    market=market,
                    feature=CompletedReturnFeature(self.schema),
                    policy=policy,
                    execution=execution,
                    costs=costs,
                    capabilities=(
                        "product:spot",
                        "calendar:continuous-utc",
                        "intent:target",
                        "feature:incremental",
                        "input:book",
                    ),
                    metrics=(metric,),
                    charts=(chart,),
                    artifacts=(self.artifact,),
                )
                study = DecisionStudy(
                    family=f"r1b-{index}",
                    source_identity=source.identity,
                    feature_identity=self.schema.identity,
                    policy_identity=policy.identity,
                    model_identity=None,
                    transform_identity=None,
                    label_identity=None,
                    output="target",
                    calendar="continuous-utc",
                    required_capabilities=(),
                    folds=(fold,),
                    partition="validation",
                    economics=IntentSimulationSpec(
                        instance=f"r1b-{index}",
                        entity=entity,
                        source_identity=market.identity,
                        start=self.decisions[0],
                        end=self.corpus.end,
                        initial_cash=Money(value=Decimal(100_000), currency=currency),
                        limits=SpotLimits(
                            maximum=Quantity(value=size * 4, dimension=dimension),
                            lot=Quantity(value=lot, dimension=dimension),
                            tick=tick_price,
                            product="spot",
                            specification_identity=hashlib.sha256(
                                DomainCodec().encode_json(("r1b-authored-grid", base, str(lot)))
                            ).hexdigest(),
                            minimum_order=Quantity(value=lot, dimension=dimension),
                        ),
                        execution_identity=execution.identity,
                        cost_identity=costs.identity,
                    ),
                    metrics=(metric.identity,),
                    charts=(chart.identity,),
                    extensions=(self.artifact.fingerprint,),
                    parameters=(("receipt-clock-assumption", "receipt-as-matching"),),
                )
                studies.append(study)
                bindings[study.identity] = components
        return tuple(studies), bindings

    def _pool(
        self, bindings: dict[str, StudyComponents], workers: int
    ) -> tuple[JobQueue, JobWorkerPool, _TimedHandler]:
        """Open the attempt's job queue and a worker pool over the bound trials."""
        queue = JobQueue(self.root / "jobs")
        handler = _TimedHandler(StudyJobHandler(bindings, self.root / "studies"), self.m)
        pool = JobWorkerPool(
            queue,
            {"decision-study": handler},
            max_workers=workers,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=StudyJobHandler.environment_sha256(),
        )
        return queue, pool, handler

    def interrupted_worker(self) -> None:
        """Run the first queued trial in a child that blocks in its market read until killed.

        The block makes the kill land inside a durable attempt however short the trial.
        """
        _, bindings = self.study_specs()
        blocked = {
            identity: replace(components, market=_BlockingMarket(components.market))
            for identity, components in bindings.items()
        }
        _, pool, _ = self._pool(blocked, 1)
        pool.run_until_idle()

    def _interrupt(self, family: str, arguments: list[str]) -> None:
        """Kill the child once its study attempt is durable."""
        process = self.runner.start(
            (
                sys.executable,
                "-E",
                "-s",
                str(Path(__file__).resolve()),
                *arguments,
                "--action",
                "interrupted-worker",
            ),
            cwd=self.root.parent,
        )
        family_root = self.root / "studies" / hashlib.sha256(family.encode()).hexdigest()
        started = time.perf_counter()
        try:
            while time.perf_counter() - started < 600:
                if tuple(family_root.glob("*/artifact-job-key.bin")):
                    break
                if process.poll() is not None:
                    _, stderr = process.communicate()
                    raise AssertionError(
                        "child exited before its study attempt started: "
                        + stderr[-2_000:].decode(errors="replace")
                    )
                time.sleep(0.05)
            else:
                raise TimeoutError("child did not begin a durable study attempt")
            process.kill()
            process.communicate(timeout=30)
            if process.poll() != -signal.SIGKILL:
                raise AssertionError("child was not terminated by SIGKILL")
            self.m.record("injected-process-kill", started, job="trial-0-0")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=30)
            self.m.untrack(process.pid)

    def studies(self, arguments: list[str]) -> None:
        """Four trials on two workers, a killed worker, recovery, control and reopen."""
        started = time.perf_counter()
        studies, bindings = self.study_specs()
        self.m.record("study-construction", started)
        queue, pool, handler = self._pool(bindings, 2)
        for trial in range(2):
            for index in range(2):
                schedule_study(
                    queue,
                    studies[index * 2 + trial],
                    job_id=f"trial-{index}-{trial}",
                    run_at=self.decisions[0],
                    publication=PublicationPolicy(mode="local"),
                    retry_delay_seconds=0,
                )
            if trial == 0:
                self._interrupt(studies[0].family, arguments)
                assert queue.read("trial-0-0").status == "running"
            started = time.perf_counter()
            pool.run_until_idle()
            if trial == 0:
                self.m.record("process-kill-recovery-wave", started, job="trial-0-0")
            self.m.record("two-worker-wave", started, peak_active_workers=handler.peak)
            for index in range(2):
                state = queue.read(f"trial-{index}-{trial}")
                assert state.status == "completed", state.last_error
        assert handler.peak == 2 and queue.read("trial-0-0").attempts == 2
        family = hashlib.sha256(studies[0].family.encode()).hexdigest()
        store = AttemptStore(self.root / "studies" / family)
        histories = store.histories()
        assert sum(h.status == "abandoned" for h in histories) == 1
        recovered = next(
            h
            for h in histories
            if h.status == "completed"
            and store.artifact(h.start.attempt_id, "job-key") == b"trial-0-0"
        )
        started = time.perf_counter()
        control = evaluate_study(
            studies[0],
            components=bindings[studies[0].identity],
            attempts=self.root / "uninterrupted-control",
            publication=PublicationPolicy(mode="local"),
        )
        self.m.record("uninterrupted-control", started)
        assert StudyResult.read(store, recovered.start.attempt_id) == StudyResult.read(
            AttemptStore(self.root / "uninterrupted-control"), control.start.attempt_id
        )
        outcomes = []
        for index in range(2):
            store = AttemptStore(
                self.root / "studies" / hashlib.sha256(f"r1b-{index}".encode()).hexdigest()
            )
            for history in store.histories():
                if history.status != "completed":
                    continue
                started = time.perf_counter()
                result = StudyResult.read(store, history.start.attempt_id)
                StudyReportReader.read(store, history.start.attempt_id)
                self.m.record("report-and-result-reopen", started)
                economics = result.folds[0].economics
                _Accounting.check(economics)
                outcomes.append(
                    {
                        "family": f"r1b-{index}",
                        "fills": len(economics.ledger.fills),
                        "net": None if economics.mark is None else str(economics.mark.net.value),
                        "unvalued": economics.unvalued_reason,
                    }
                )
        (self.root / "trial-outcomes.json").write_text(json.dumps(outcomes))
        self.m.checkpoint("studies")

    # Backup ---------------------------------------------------------------------------

    def backup(self) -> None:
        """Back up inputs, features and results; restore and compare."""
        components = ("raw", "snapshots", "features", "serving", "offline-feast", "jobs", "studies")
        backup = self.root.parent / (self.root.name + "-backup")
        restored = self.root.parent / (self.root.name + "-restored")
        started = time.perf_counter()
        WorkspaceBackup.create(self.root, backup, components=components)
        self.m.record("backup", started)
        self.m.checkpoint("backup", backup)
        started = time.perf_counter()
        WorkspaceBackup.restore(backup, restored)
        self.m.record("restore", started)
        self.m.checkpoint("restore", restored)
        started = time.perf_counter()
        restored_store = VersionedFeatureStore.open(restored / "features" / "history.sqlite3")
        snapshot = FeastServingSnapshot.from_materialization(
            restored_store.get_materialization(self.definition, "complete")
        )
        generation = self.bridge.open_generation(snapshot, restored / "serving")
        self.m.record("online-generation-reopen", started)
        for entity in self.entities():
            served = self.bridge.retrieve(snapshot, generation, entity, self.decisions[-1])
            assert served.status == "ready", served
        for index in range(2):
            family = hashlib.sha256(f"r1b-{index}".encode()).hexdigest()
            original = AttemptStore(self.root / "studies" / family)
            copy = AttemptStore(restored / "studies" / family)
            assert original.histories() == copy.histories()
            for history in original.histories():
                if history.status == "completed":
                    assert StudyResult.read(original, history.start.attempt_id) == StudyResult.read(
                        copy, history.start.attempt_id
                    )
        BookSnapshot.read(
            restored / "snapshots",
            RawStore(restored / "raw"),
            readers=self.readers,
            identity=self._published()[0],
            max_bytes=_LIMIT,
        )
        self.m.record("backup-restore-equivalence", started)


class _FeastCommand:
    """Run the installed Feast worker commands in the separately locked worker."""

    def __init__(self, worker: str) -> None:
        """Locate the installed command module once."""
        spec = find_spec("applications.explore.command")
        if spec is None or spec.origin is None:
            raise ValueError("installed Feast command missing")
        self._worker, self._origin = worker, spec.origin

    def argv(self, name: str) -> tuple[str, ...]:
        """Return the isolated worker argv for one named command."""
        return (
            self._worker,
            "-I",
            "-c",
            "from runpy import run_path; "
            f"raise SystemExit(run_path({self._origin!r})['main'](['{name}']))",
        )


class _Arguments(argparse.Namespace):
    """Corpus, attempt root, Feast worker and action."""

    runs: Path
    window: Path
    output: Path
    worker_python: Path
    action: Literal["run", "interrupted-worker"]


def main() -> None:
    """Run the workflow; a failure is retained in measurement.json before propagating."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runs", "window", "output", "worker-python"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--action", choices=("run", "interrupted-worker"), default="run")
    args = parser.parse_args(namespace=_Arguments())
    m = (
        _Measurements.create(args.output)
        if args.action == "run"
        else _Measurements(
            args.output.resolve(), ImplementationIdentity.sha256(), sample_resources=False
        )
    )
    m.scope = "native-capture R1b measurement"
    m.consumer = Path(__file__)
    try:
        worker = str(args.worker_python.absolute())
        command = _FeastCommand(worker).argv
        runner = _TrackedProcess(m)
        bridge = FeastServingBridge(
            _TrackedFeastWorker(
                runner,
                command("feast-serving-worker"),
                cwd=m.root,
                timeout=300,
                operation="online-boundary",
            )
        )
        consumer = Path(__file__).read_bytes()
        artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name="r1b-consumer", sha256=hashlib.sha256(consumer).hexdigest()
            ),
            payload=consumer,
        )
        corpus = _Corpus(args.runs.absolute(), args.window.absolute())
        workflow = _Workflow(
            m,
            corpus,
            args.worker_python.absolute(),
            artifact,
            bridge,
            runner,
            command("feast-worker"),
        )
        if args.action == "interrupted-worker":
            workflow.interrupted_worker()
            return
        m.input_configuration = {
            "window": [corpus.start, corpus.end],
            "raw_positions_by_feed": corpus.records,
            "decisions_per_entity": len(workflow.decisions),
            "close_latency_cadence_seconds": _CLOSE_LATENCY_CADENCE,
            "worker_python": worker,
        }
        workflow.publish()
        workflow.features()
        arguments = [
            "--runs",
            str(corpus.runs),
            "--window",
            str(args.window.absolute()),
            "--output",
            str(m.root),
            "--worker-python",
            worker,
        ]
        workflow.studies(arguments)
        workflow.backup()
    except Exception as error:
        if args.action == "run":
            m.finish("failed", f"{type(error).__name__}: {error}")
        raise
    if args.action == "run":
        m.finish("complete")


if __name__ == "__main__":
    main()
