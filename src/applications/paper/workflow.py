"""Compose admitted candidates, independent limits and durable paper account events."""

from __future__ import annotations

# standard library imports
import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from accounting import LedgerState
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
    CandidateDeployment,
    CapabilityRegistry,
    PaperConfiguration,
)
from execution import OrderEvent, OrderState, PaperMarket, PaperOrderJournal
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.books import BookRegistry
from market_data.collection import CaptureRunner, CaptureRunResult, CaptureTransport
from market_data.contracts import CaptureRequest
from research.experiments import CandidateBundle
from research.observations import DecisionSource, LiveBookDecisionSource
from risk import SpotLimits
from runtime import (
    CandidateComponents,
    CandidateFeatureFeed,
    CandidateLoader,
    PaperCandidateRuntime,
    PaperCaptureObserver,
    PaperCheckpoint,
)
from serialization import WireRecord


class PaperTimer(WireRecord, frozen=True):
    """Identify an explicit UTC scheduler tick, reusable through replay and live input."""

    identity: str
    at: datetime

    def __post_init__(self) -> None:
        """Reject missing timer identity and clocks without UTC semantics."""
        self._require_utc(self.at, field_name="timer")
        if type(self.identity) is not str or not self.identity:
            raise ValueError("paper timer requires stable identity")


class PaperRunResult(WireRecord, frozen=True):
    """Expose a bounded continuation and exact account state; all orders are simulated."""

    checkpoint: PaperCheckpoint
    ledger: LedgerState
    orders: tuple[OrderState, ...]
    submission_attempted: bool = False

    def __post_init__(self) -> None:
        """Keep returned evidence attributable to durable non-executable state."""
        self.checkpoint.__post_init__()
        self.ledger.__post_init__()
        for order in self.orders:
            order.__post_init__()
        if self.submission_attempted is not False:
            raise ValueError("paper application cannot submit executable orders")


def run_paper(
    bundle: CandidateBundle,
    deployment: CandidateDeployment,
    config: PaperConfiguration,
    *,
    components: CandidateComponents,
    registry: CapabilityRegistry,
    journal_path: Path,
    events: Iterable[PaperMarket | PaperTimer | OrderEvent],
    opened_at: datetime,
    owner: str,
    source: DecisionSource | None = None,
    features: CandidateFeatureFeed | None = None,
) -> PaperRunResult:
    """Run a finite event prefix using the installed candidate and existing public owners.

    The candidate loader admits code, environment, capabilities and configuration
    before any input read. A live producer may supply events incrementally; its
    source retains original availability and lineage. Events are processed
    sequentially, with no hidden unbounded queue. A failure propagates after
    releasing the fence; reopening replays persisted order callbacks. Finishing
    a prefix does not cancel orders or reset state.
    """
    loaded = CandidateLoader(components, registry).load(bundle, deployment)
    config.__post_init__()
    limits = SpotLimits(maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot")
    journal = PaperOrderJournal(
        journal_path,
        account=config.account,
        instance=deployment.instance,
        binding_identity=PaperCandidateRuntime.binding(loaded, config),
        mode=config.mode,
        limits=limits,
        ledger_state=LedgerState(
            initial_cash=config.initial_cash, dimension=config.maximum.dimension
        ),
    )
    runtime = PaperCandidateRuntime(loaded, config, journal, source=source, features=features)
    runtime.open(owner=owner, at=opened_at)
    try:
        for event in events:
            if isinstance(event, PaperMarket):
                runtime.market(event)
            elif isinstance(event, PaperTimer):
                event.__post_init__()
                runtime.timer(identity=event.identity, at=event.at)
            else:
                runtime.order(event)
        return PaperRunResult(
            checkpoint=runtime.checkpoint(),
            ledger=journal.ledger_state(),
            orders=journal.orders(),
        )
    finally:
        runtime.release()


@dataclass(frozen=True)
class LivePaperRunResult:
    """Keep live source evidence separate from the modeled paper account result."""

    capture: CaptureRunResult
    paper: PaperRunResult
    book_registry: BookRegistryConfiguration


async def run_live_paper(
    bundle: CandidateBundle,
    deployment: CandidateDeployment,
    config: PaperConfiguration,
    *,
    components: CandidateComponents,
    registry: CapabilityRegistry,
    request: CaptureRequest,
    capture_output: Path,
    journal_path: Path,
    owner: str,
    history_capacity: int = 10_000,
    transport: CaptureTransport | None = None,
    books: BookRegistry | None = None,
) -> LivePaperRunResult:
    """Collect bounded public books while supervising actual cadence and paper state.

    This local development invocation is neither a deployment nor an executable
    venue session. Both native source adapters retain their source-specific
    quality and clocks. A new process opens a new capture recording and waits
    for a fresh synchronized book while preserving the same candidate/account
    journal. Collector and timer failures cancel their peer; durable source and
    order evidence survive. The existing capture config bounds queue, storage,
    retries and receive duration. Other named inputs use ``run_paper``.
    """
    loaded = CandidateLoader(components, registry).load(bundle, deployment)
    if (
        deployment.mode != "runtime"
        or deployment.input_mode != "source"
        or len(loaded.manifest.inputs) != 1
        or deployment.entity != str(request.config.instrument_id)
    ):
        raise ValueError("live paper requires one admitted native book source")
    source = LiveBookDecisionSource(
        request, loaded.manifest.inputs[0], history_capacity=history_capacity
    )
    journal = PaperOrderJournal(
        journal_path,
        account=config.account,
        instance=deployment.instance,
        binding_identity=PaperCandidateRuntime.binding(loaded, config),
        mode=config.mode,
        limits=SpotLimits(maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"),
        ledger_state=LedgerState(
            initial_cash=config.initial_cash, dimension=config.maximum.dimension
        ),
    )
    runtime = PaperCandidateRuntime(loaded, config, journal, source=source)
    if books is None:
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
                history_capacity=history_capacity,
            )
        )
    observer = PaperCaptureObserver(source, runtime, books=books)
    runner = CaptureRunner(
        book_factory=BookAdapters.create,
        transport=VenueTransport(request.config) if transport is None else transport,
        subscriptions=VenueSubscriptions(),
        observer=observer,
    )
    runtime.open(owner=owner, at=datetime.now(UTC))
    stop = asyncio.Event()
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(observer.timers(stop))
            try:
                capture = await runner.run(request, capture_output)
            finally:
                stop.set()
        return LivePaperRunResult(
            capture=capture,
            book_registry=books.config,
            paper=PaperRunResult(
                checkpoint=runtime.checkpoint(),
                ledger=journal.ledger_state(),
                orders=journal.orders(),
            ),
        )
    finally:
        runtime.release()
