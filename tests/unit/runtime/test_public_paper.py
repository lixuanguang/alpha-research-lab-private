"""Prove public paper source faults and real coordination clocks fail closed."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from accounting import AccountLedger, AccountSnapshot
from applications.paper import run_live_shared_paper
from applications.paper.monitoring import retain_public_paper_monitoring
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    CaptureConfig,
    CaptureRunConfig,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperStrategyIdentity,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
    AccountControlResult,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PortfolioContext,
)
from financial_units import (
    Currency,
    Dimension,
    ExactRatio,
    Money,
    Price,
    Quantity,
    QuantityKind,
)
from market_data.adapters.sources import BookAdapters
from market_data.books import BookAsOfIndex, BookProjection, BookRegistry, CaptureReplay
from market_data.collection.segments import CaptureSegmentWriter
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    Level,
    RecordingRequest,
)
from market_data.replay import SavedCaptureRun
from market_data.storage import CaptureRecording, CaptureRunJournal
from reference_data.instruments import InstrumentId
from research.experiments import CandidateStateContract
from research.features import FeatureSchema, ProjectionFeature
from research.observations import (
    DecisionInputs,
    InputRequirement,
    LiveBookDecisionSource,
    LiveTradeDecisionSource,
    NumericField,
)
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    AuthoredCandidates,
    SharedBookDelivery,
    SharedDecisionGroup,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
    SharedStrategyInput,
)
from runtime.live_paper import LiveBookDelivery
from runtime.shared_paper import (
    ObservedLiveBookDelivery,
    ObservedSharedBookDelivery,
    RetainedLiveBookDelivery,
    RetainedSharedBookDelivery,
)
from serialization import DomainCodec
from strategies import ConfirmedSignal, OrderIntent
from telemetry import RuntimeMeasurementJournal


class _SequenceClock:
    """Return authored actual-clock observations in order for a bounded retry."""

    def __init__(self, times: tuple[datetime, ...]) -> None:
        """Keep the last clock value after the supplied sequence is exhausted."""
        self.times = times
        self.index = 0

    def __call__(self) -> datetime:
        """Read the next scripted UTC clock value."""
        result = self.times[min(self.index, len(self.times) - 1)]
        self.index += 1
        return result


class _UnknownOutcome:
    """Model account outcomes whose commit result is unknown, counting each attempt."""

    def __init__(self) -> None:
        """Start with no attempts."""
        self.calls = 0

    def __call__(self, account_id: str, reason: str) -> None:
        """Count the attempt and raise the unknown-outcome timeout."""
        self.calls += 1
        raise TimeoutError("unknown account outcome")


class _RejectedControl:
    """Return typed refusals without changing account state, counting each request."""

    def __init__(self) -> None:
        """Start with no requests."""
        self.calls = 0

    def __call__(self, request: AccountControl) -> AccountControlResult:
        """Count the request and refuse it."""
        self.calls += 1
        return AccountControlResult(
            request=request,
            status="rejected",
            phase="running",
            recovery_generation=0,
            reason="test refusal",
        )


class TestSharedPublicPaper:
    """Exercise durable invalidation, ordinary control flow and refusal boundaries."""

    at = datetime(2025, 1, 1, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("4476df8e-6342-4417-839e-e41b88f41446"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _money(cls, value: str) -> Money:
        """Create exact USDT account cash."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact selected base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Create exact selected quote per base."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _capture(cls) -> CaptureConfig:
        """Load the maintained public OKX selection without making a connection."""
        root = Path(__file__).parents[3]
        return CaptureConfig.read(root / "configs/live/okx-btc-usdt.json")

    @classmethod
    def _request(cls) -> CaptureRequest:
        """Bind a fixed valid recording identity for saved native boundaries."""
        return CaptureRequest(
            config=cls._capture(),
            recording_id="11111111-1111-4111-8111-111111111111",
            implementation_identity="a" * 64,
        )

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Fund one isolated account under bounded paper risk policy."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("10"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.at - timedelta(seconds=1),
            accounts=(OpeningAccount(account_id="paper", cash=(cls._money("1000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="paper", maximum=cls._money("1000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="paper",
                        maximum=cls._money("900"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=5_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=500,
                max_order_notional=cls._money("900"),
            ),
        )

    @classmethod
    def _binding(
        cls,
        *,
        cadence_us: int = 1_000_000,
        starts_at: datetime | None = None,
        instance: str = "alpha",
        signal: InputRequirement | None = None,
    ) -> SharedStrategyBinding:
        """Select one candidate that targets one unit whenever its signal is positive.

        The signal is the ask unless another input is named; it is read beside the ask.
        The default grid puts an instant half a second before every whole second, so
        each market delivery on a new whole second crosses one instant.
        """
        ask = NumericField(name="ask", units="quote/base")
        inputs = (cls._requirement(),) if signal is None else (cls._requirement(), signal)
        return SharedStrategyBinding(
            instance_id=instance,
            account_id="paper",
            entity=str(cls.dimension.instrument_id),
            candidate=AuthoredCandidates(venue="okx").load(
                name="public-paper-signal",
                feature=ProjectionFeature(
                    FeatureSchema(
                        implementation="named-projection",
                        inputs=inputs,
                        outputs=tuple(item.field for item in inputs),
                        parameters=(),
                        mode="batch",
                        ttl_us=5_000_000,
                    )
                ),
                policy=ConfirmedSignal(
                    field=ask if signal is None else signal.field,
                    quantity=cls._quantity("1"),
                    confirmations=1,
                ),
                instance=instance,
                entity=str(cls.dimension.instrument_id),
                cadence_us=cadence_us,
                starts_at=cls.at - timedelta(milliseconds=500) if starts_at is None else starts_at,
                source_identity="public-paper-source",
                state=CandidateStateContract(
                    feature_mode="batch",
                    warmup_observations=0,
                    checkpoint_schema="candidate-checkpoint",
                    on_gap="continue",
                    on_restart="restore",
                    policy_state_schema="confirmed-signal",
                ),
            ),
            context=PortfolioContext(
                portfolio_id="test-portfolio",
                strategy_id=instance,
                model_revision="rule-only",
                config_revision="test",
                horizon="short",
                reason="public-paper-test",
                venue="okx",
                settlement="spot",
                risk_bucket="cash",
                authority_scope="paper",
            ),
            maximum_fee=cls._money("1"),
        )

    @classmethod
    def _scenario(cls) -> PaperExecutionScenario:
        """Declare off-chain paper costs for the selected instrument."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=1000,
            cancel_delay_us=2000,
            adverse=cls._price("0"),
            fee_rate=Decimal("0"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="public spot paper matching has no blockchain activity",
        )

    @classmethod
    def _requirement(cls) -> InputRequirement:
        """Use receipt freshness so authored rows need no exchange source clock."""
        return InputRequirement(
            name="book",
            family="book",
            field=NumericField(name="ask", units="quote/base"),
            clock="receipt",
            max_age_us=5_000_000,
        )

    @classmethod
    def _opening(cls) -> AccountObservation:
        """Author the independent opening cash and no-order observation."""
        return AccountObservation(
            identity="opening",
            at=cls.at - timedelta(seconds=1),
            snapshot=AccountSnapshot(
                account_id="paper",
                instance_id=None,
                cash=(cls._money("1000"),),
                positions=(),
                fees=(cls._money("0"),),
                rebates=(cls._money("0"),),
                transfers=(cls._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )

    @classmethod
    def _observer(
        cls,
        path: Path,
        *,
        scenario: PaperExecutionScenario | None = None,
        clock: _SequenceClock | None = None,
        cadence_us: int = 1_000_000,
        retain: bool = False,
        deciding: bool = False,
        measurements: RuntimeMeasurementJournal | None = None,
        index: BookAsOfIndex | None = None,
        request: RecordingRequest | None = None,
    ) -> tuple[SharedPaperCaptureObserver, AccountJournal]:
        """Construct the actual source, registry, account and decision owners.

        Unless ``deciding``, the candidate only sets the matching grid and never decides.
        """
        request = cls._request() if request is None else request
        source = LiveBookDecisionSource(request, (cls._requirement(),), history_capacity=20)
        books = BookRegistry(
            BookRegistryConfiguration(
                selections=(
                    BookSelection.from_capture(
                        request.config,
                        source_id=request.identity,
                        capability=BookAdapters.capability(request.config),
                        max_age_ns=5_000_000_000,
                        allow_degraded=True,
                    ),
                ),
                equivalences=(),
                history_capacity=20,
            )
        )
        journal = AccountJournal(path, cls._config())
        runtime = SharedDecisionRuntime(journal, (cls._binding(cadence_us=cadence_us),))
        observer = SharedPaperCaptureObserver(
            source=source,
            books=books,
            journal=journal,
            runtime=runtime,
            account_id="paper",
            scenario=scenario or cls._scenario(),
            delivery_path=path.with_suffix(".jsonl") if retain else None,
            active=("alpha",) if deciding else (),
            clock=clock,
            measurements=measurements,
            index=index,
        )
        return observer, journal

    @classmethod
    def _delivery(
        cls,
        position: int,
        *,
        seconds: int,
        kind: Literal["session", "frame", "gap", "session_end", "end"],
        outcome: str,
        status: str,
        reason: str,
        market: bool = False,
        state_identity: str = "1" * 64,
    ) -> SharedBookDelivery:
        """Author a canonical received control or two-sided market boundary."""
        at = cls.at + timedelta(seconds=seconds)
        received_ns = int(at.timestamp()) * 1_000_000_000
        record = CaptureRecord(
            kind=kind,
            epoch=0,
            received_ns=received_ns,
            raw=b"{}" if kind == "frame" else b"",
            reason=reason if kind not in ("frame", "session") else "",
        )
        level = Level(size=Decimal("4"), order_count=1)
        row = BookObservation(
            position=position,
            epoch=0,
            received_ns=received_ns,
            source_time=str(received_ns // 1_000_000) if market else None,
            sequence=None,
            outcome=outcome,
            status=status,
            reason=reason,
            state_identity=state_identity,
            bids=((Decimal("99"), level),) if market else (),
            asks=((Decimal("100"), level),) if market else (),
        )
        return SharedBookDelivery(
            source=LiveBookDelivery(record=record, book=row, available_at=at),
            decisions=(),
            matched=market,
        )

    @classmethod
    def _okx_frame(
        cls, action: str, sequence: int, bids: list[list[str]], asks: list[list[str]]
    ) -> bytes:
        """Encode one native OKX books message."""
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "books", "instId": "BTC-USDT"},
                "action": action,
                "data": [
                    {
                        "seqId": sequence,
                        "prevSeqId": sequence - 1 if action == "update" else -1,
                        "ts": str(int(cls.at.timestamp()) * 1000 + sequence),
                        "bids": bids,
                        "asks": asks,
                        "checksum": 0,
                    }
                ],
            }
        )

    @classmethod
    def _okx_records(cls, levels: int, updates: int) -> tuple[CaptureRecord, ...]:
        """Author a session, acknowledgement, deep snapshot and single-level updates."""
        base = int(cls.at.timestamp()) * 1_000_000_000
        bids = [[f"{60000 - i}.5", f"{1 + i % 7}.{i % 10}", "0", "1"] for i in range(levels)]
        asks = [[f"{60001 + i}.5", f"{1 + i % 5}.{i % 10}", "0", "1"] for i in range(levels)]
        records = [
            CaptureRecord(kind="session", epoch=0, received_ns=base),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base + 1,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            ),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base + 2,
                raw=cls._okx_frame("snapshot", 1, bids, asks),
            ),
        ]
        for index in range(updates):
            level = [[f"{60000 - index % levels}.5", f"{2 + index % 9}.1", "0", "2"]]
            records.append(
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=base + 1_000_000 * (index + 3),
                    raw=cls._okx_frame(
                        "update", index + 2, level if index % 2 else [], [] if index % 2 else level
                    ),
                )
            )
        return tuple(records)

    def _run_okx(
        self, path: Path, records: tuple[CaptureRecord, ...], *, projected: bool
    ) -> tuple[bytes, list[float]]:
        """Feed native boundaries to a retaining observer; return its log and observe costs."""
        clock = _SequenceClock(
            tuple(self.at + timedelta(seconds=1, milliseconds=i) for i in range(len(records)))
        )
        observer, journal = self._observer(path, retain=True, clock=clock)
        assert journal.reconcile(self._opening())
        target = observer.projected_rows() if projected else observer
        replay = CaptureReplay(self._request().config, book_factory=BookAdapters.create)
        costs: list[float] = []
        for position, record in enumerate(records):
            row = BookProjection.capture(position, record, replay.apply(record), replay)
            started = time.perf_counter()
            target.observe(record, row)
            costs.append(time.perf_counter() - started)
        return path.with_suffix(".jsonl").read_bytes(), costs

    def _chain(
        self, root: Path, records: tuple[CaptureRecord, ...], *, segment_messages: int
    ) -> CaptureRecording:
        """Retain authored records through the collector's qualified rollover writer."""
        request = CaptureRunRequest(
            config=replace(self._capture(), max_messages=segment_messages),
            window=CaptureRunConfig(
                start_at=self.at - timedelta(seconds=1),
                ready_by=self.at,
                stop_at=self.at + timedelta(hours=1),
                max_messages=len(records),
                max_bytes=64 * 1024**2,
                max_segments=16,
                max_reconnects=0,
            ),
            run_id="22222222-2222-4222-8222-222222222222",
            implementation_identity="a" * 64,
        )
        run = CaptureRunJournal(root / request.run_id, request)
        run.open(resume=False)
        try:
            writer = CaptureSegmentWriter(
                run, run.start_segment(None), previous_bytes=0, previous_records=0
            )
            replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
            for record in records:
                asyncio.run(writer.append(record))
                replay.apply(record)
            run.sealed(writer.current, writer.first_received_ns or 1)
            run.finish(
                {
                    **replay.summary(),
                    "run_identity": request.identity,
                    "saved_bytes": writer.total_bytes,
                    "saved_records": writer.total_records,
                }
            )
        finally:
            run.close()
        SavedCaptureRun.read(
            root / request.run_id, book_factory=BookAdapters.create, max_seconds=30
        )
        return CaptureRecording(root / request.run_id, request)

    def test_chain_is_one_delivery_log_and_index_across_rollover(self, tmp_path: Path) -> None:
        """Deliveries, index positions and source identity run on unchanged across segments."""
        authored = self._okx_records(4, 12)
        end = CaptureRecord(
            kind="end", epoch=0, received_ns=authored[-1].received_ns, reason="duration_limit"
        )
        recording = self._chain(tmp_path / "capture", (*authored, end), segment_messages=5)
        records = tuple(recording.records(completed=True))
        cursor = recording.cursor()
        assert recording.completed and len(cursor.segments) == 3
        assert records == (*authored, end) and cursor.records == len(records)

        path = tmp_path / "paper.sqlite3"
        index = BookAsOfIndex.create(path.with_suffix(".index.sqlite3"))
        clock = _SequenceClock(
            tuple(self.at + timedelta(seconds=1, milliseconds=i) for i in range(len(records)))
        )
        observer, journal = self._observer(
            path, retain=True, clock=clock, index=index, request=recording.request
        )
        assert journal.reconcile(self._opening())
        replay = CaptureReplay(recording.request.config, book_factory=BookAdapters.create)
        for position, record in enumerate(records):
            observer.observe(
                record, BookProjection.capture(position, record, replay.apply(record), replay)
            )
        index.close()
        codec = DomainCodec()
        lines = path.with_suffix(".jsonl").read_bytes().splitlines()
        deliveries = [codec.decode_json(line, SharedBookDelivery) for line in lines]
        assert [item.source.record for item in deliveries] == list(records)
        assert [item.source.book.position for item in deliveries] == list(range(len(records)))
        assert index.covered_bytes() == path.with_suffix(".jsonl").stat().st_size

        # The first record of each later segment is still one contiguous, indexed boundary.
        selection = observer.books.lookup(observer._key, cutoff_ns=0).selection
        assert selection.source_id == recording.identity
        first = 0
        for ordinal, segment in enumerate(cursor.segments):
            located = recording.locate(first)
            assert (located.ordinal, located.position) == (ordinal, 0)
            available = deliveries[first].source.available_at
            elapsed = available - datetime(1970, 1, 1, tzinfo=UTC)
            cutoff_ns = (
                elapsed.days * 86_400 + elapsed.seconds
            ) * 1_000_000_000 + elapsed.microseconds * 1000
            lookup, _ = index.lookup(selection, cutoff_ns=cutoff_ns)
            assert lookup.boundary is not None and lookup.boundary.position == first
            assert lookup.boundary.source_id == recording.identity
            first += segment.records
        with pytest.raises(IndexError):
            recording.locate(first)

    def test_retained_deliveries_are_the_full_canonical_encoding(self, tmp_path: Path) -> None:
        """Reused row bytes and trusted runner rows retain exactly the public-path bytes."""
        records = self._okx_records(20, 12)
        public, _ = self._run_okx(tmp_path / "public.sqlite3", records, projected=False)
        projected, _ = self._run_okx(tmp_path / "projected.sqlite3", records, projected=True)
        assert projected == public
        codec = DomainCodec()
        lines = public.splitlines()
        assert len(lines) == len(records)
        decoded = [codec.decode_json(line, SharedBookDelivery) for line in lines]
        assert any(item.source.book.bids for item in decoded)
        assert [codec.encode_json(item) for item in decoded] == lines
        # The retention envelopes must keep exactly the retained schemas' fields.
        assert {field.name for field in msgspec.structs.fields(RetainedSharedBookDelivery)} == {
            field.name for field in msgspec.structs.fields(SharedBookDelivery)
        }
        assert {field.name for field in msgspec.structs.fields(RetainedLiveBookDelivery)} == {
            field.name for field in msgspec.structs.fields(LiveBookDelivery)
        }

    @pytest.mark.performance
    def test_runner_rows_are_validated_and_encoded_once(self, tmp_path: Path) -> None:
        """A 400-level update costs the observer about one row projection, not three."""
        records = self._okx_records(400, 200)
        _, costs = self._run_okx(tmp_path / "paper.sqlite3", records, projected=True)
        replay = CaptureReplay(self._request().config, book_factory=BookAdapters.create)
        projections: list[float] = []
        for position, record in enumerate(records):
            outcome = replay.apply(record)
            started = time.perf_counter()
            BookProjection.capture(position, record, outcome, replay)
            projections.append(time.perf_counter() - started)
        observe = sorted(costs[3:])[len(costs[3:]) // 2]
        projection = sorted(projections[3:])[len(projections[3:]) // 2]
        print(f"observe/projection per 400-level update: {observe:.6f}s/{projection:.6f}s")
        # Validating the row again and encoding it twice made observe about 3x projection.
        assert observe < 2.2 * projection

    @classmethod
    def _markets(cls) -> tuple[SharedBookDelivery, ...]:
        """Author a session and four whole-second two-sided market updates."""
        return (
            cls._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            *(
                cls._delivery(
                    position,
                    seconds=position,
                    kind="frame",
                    outcome="snapshot" if position == 1 else "update",
                    status="degraded",
                    reason="visible_depth_only",
                    market=True,
                )
                for position in range(1, 5)
            ),
        )

    def test_grid_retains_every_book_but_decides_and_matches_on_crossing_books(
        self, tmp_path: Path
    ) -> None:
        """Books between instants advance source state only; a crossing book decides, then matches.

        With a three-second grid at -0.5 s, 2.5 s, ..., the book at 1 s crosses the first
        instant (nothing to decide yet) and the book at 3 s crosses 2.5 s: the candidate
        decides from the 2 s market, then the 3 s book matches its order.
        """
        path = tmp_path / "sampled.sqlite3"
        times = tuple(self.at + timedelta(seconds=seconds) for seconds in range(5))
        clock = _SequenceClock(times)
        measurement_path = tmp_path / "paper-measurements.jsonl"
        measurements = RuntimeMeasurementJournal(measurement_path, sync_every=1)
        as_of = BookAsOfIndex.create(path.with_suffix(".index.sqlite3"))
        observer, journal = self._observer(
            path,
            clock=clock,
            cadence_us=3_000_000,
            retain=True,
            deciding=True,
            measurements=measurements,
            index=as_of,
        )
        assert journal.reconcile(self._opening())
        deliveries = self._markets()
        for index, delivery in enumerate(deliveries):
            observer.observe(delivery.source.record, delivery.source.book)
            if index == 1:
                first_effects = (
                    journal.accounts(),
                    journal.orders(),
                    journal.paper_traces("paper"),
                    journal.checkpoint("alpha"),
                )
                assert first_effects[3] is None
                assert len(first_effects[2]) == 1
            if index == 2:
                assert (
                    journal.accounts(),
                    journal.orders(),
                    journal.paper_traces("paper"),
                    journal.checkpoint("alpha"),
                ) == first_effects
                assert observer.source.latest_book is not None
                assert observer.source.latest_book.position == index
                assert observer.last_market is not None
                assert observer.last_market.at == times[index]
        assert journal.checkpoint("alpha") is not None
        assert observer.delivered_count == len(deliveries)
        measurements.close()
        measured = tuple(
            msgspec.json.decode(line, type=dict[str, object])
            for line in measurement_path.read_bytes().splitlines()
        )
        assert len(measured) == len(deliveries)
        assert tuple(item["position"] for item in measured) == tuple(range(5))
        assert tuple(item["market_selected"] for item in measured) == (
            False,
            True,
            False,
            True,
            False,
        )
        selected_rows = tuple(item for item in measured if item["policy_selected"] is True)
        assert tuple(item["position"] for item in selected_rows) == (3,)
        assert all(item["checkpoint_acknowledged"] is True for item in selected_rows)
        assert all(
            isinstance(item["book_to_checkpoint_ns"], int) and item["book_to_checkpoint_ns"] >= 0
            for item in selected_rows
        )
        # Opt-in phase clocks are ordered; a direct observe has no supervisor pipe receipt.
        for item in measured:
            assert item["pipe_received_ns"] is None
            phases = cast(dict[str, int], item["phase_ns"])
            started, finished = cast(int, item["book_started_ns"]), cast(int, item["finished_ns"])
            assert started <= phases["retained_ns"] <= finished
            if item["policy_selected"]:
                assert phases["retained_ns"] <= phases["evaluated_ns"] <= phases["observed_ns"]
            else:
                assert "evaluated_ns" not in phases
            if item["market_selected"]:
                assert phases["retained_ns"] <= phases["observed_ns"] <= phases["matched_ns"]
                assert phases["matched_ns"] <= finished
        codec = DomainCodec()
        retained_bytes = path.with_suffix(".jsonl").read_bytes().splitlines()
        retained = tuple(codec.decode_json(line, SharedBookDelivery) for line in retained_bytes)
        assert len(retained) == len(deliveries)
        for payload, delivery in zip(retained_bytes, retained, strict=True):
            observed_source = ObservedLiveBookDelivery(
                record=delivery.source.record,
                book=delivery.source.book,
                available_at=delivery.source.available_at,
            )
            observed = ObservedSharedBookDelivery(
                source=observed_source,
                decisions=delivery.decisions,
                matched=delivery.matched,
                schema_version=delivery.schema_version,
            )
            assert codec.encode_json(observed_source) == codec.encode_json(delivery.source)
            assert codec.encode_json(observed) == codec.encode_json(delivery) == payload
        assert tuple(item.source.book.position for item in retained) == tuple(range(5))
        (group,) = retained[3].decisions
        assert group.at == self.at + timedelta(milliseconds=2500)
        assert group.coordinated_at == group.at + timedelta(microseconds=1)
        assert group.quote.at == times[2]
        assert tuple(item.instance_id for item in group.inputs) == ("alpha",)
        as_of.close()
        selection = observer.books.lookup(observer._key, cutoff_ns=0).selection
        offset = 0
        for payload, delivery in zip(retained_bytes, retained, strict=True):
            elapsed = delivery.source.available_at - datetime(1970, 1, 1, tzinfo=UTC)
            cutoff = (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + (
                elapsed.microseconds * 1000
            )
            lookup, selected = BookAsOfIndex(as_of.path).lookup(selection, cutoff_ns=cutoff)
            assert lookup == observer.books.lookup(observer._key, cutoff_ns=cutoff)
            target = lookup.quote if lookup.quote is not None else lookup.boundary
            assert target is not None and selected is not None
            if target.position == delivery.source.book.position:
                assert selected == (offset, len(payload) + 1)
            offset += len(payload) + 1
        assert BookAsOfIndex(as_of.path).covered_bytes() == offset
        assert tuple(item.matched for item in retained) == (False, True, False, True, False)
        assert len(journal.paper_traces("paper")) == 2
        assert AccountLedger(journal.accounts()[0].ledger).snapshot().positions == (
            self._quantity("1"),
        )

        replay, recovered = self._observer(
            tmp_path / "replay.sqlite3", cadence_us=3_000_000, deciding=True
        )
        assert recovered.reconcile(self._opening())
        for delivery in retained:
            replay.deliver(delivery)
        assert recovered.accounts() == journal.accounts()
        assert recovered.orders() == journal.orders()
        assert recovered.paper_traces("paper") == journal.paper_traces("paper")
        assert recovered.paper_report_facts("paper") == journal.paper_report_facts("paper")
        assert recovered.checkpoint("alpha") == journal.checkpoint("alpha")
        unmatched = replace(retained[3], decisions=(), matched=False)
        fresh, opened = self._observer(
            tmp_path / "unmatched.sqlite3", cadence_us=3_000_000, deciding=True
        )
        assert opened.reconcile(self._opening())
        for delivery in retained[:3]:
            fresh.deliver(delivery)
        with pytest.raises(ValueError, match="replayed decision grid"):
            fresh.deliver(unmatched)

    def test_mixed_grids_read_shared_sources_in_instant_order(self, tmp_path: Path) -> None:
        """Two instants crossed by one book decide in instant order, not binding order.

        Alpha's 3 s grid (2.5 s) and beta's 2 s grid (2.25 s) are both crossed by the
        3 s book; both decide from the 2 s market. Reading alpha first would move the
        live source's frozen cutoff backwards.
        """
        observer, journal = self._shared(
            tmp_path / "mixed.sqlite3",
            (
                self._binding(cadence_us=3_000_000),
                self._binding(
                    cadence_us=2_000_000,
                    starts_at=self.at + timedelta(milliseconds=2250),
                    instance="beta",
                ),
            ),
            clock=_SequenceClock(tuple(self.at + timedelta(seconds=item) for item in range(5))),
        )
        assert journal.reconcile(self._opening())
        for delivery in self._markets()[:4]:
            observer.observe(delivery.source.record, delivery.source.book)
        assert len(observer.decisions) == 2
        checkpoints = (journal.checkpoint("beta"), journal.checkpoint("alpha"))
        assert all(item is not None for item in checkpoints)

    def test_trade_fields_join_book_fields_in_decided_inputs(self, tmp_path: Path) -> None:
        """A candidate reading signed trade flow decides from both feeds at its instant."""
        flow = InputRequirement(
            name="trades",
            family="trade",
            clock="event",
            field=NumericField(name="signed_flow", units="BTC"),
            max_age_us=2_000_000,
        )
        trades_config = replace(
            self._capture(), channel="trades", depth=0, max_orders=1, idle_seconds=5
        )
        trades = self._trades(trades_config, flow)
        clock = _SequenceClock(
            (
                self.at - timedelta(seconds=2),
                self.at - timedelta(seconds=2),
                self.at,
                self.at + timedelta(seconds=1),
                self.at + timedelta(milliseconds=1500),
                self.at + timedelta(seconds=2),
                self.at + timedelta(seconds=3),
            )
        )
        observer, journal = self._shared(
            tmp_path / "trades.sqlite3",
            (self._binding(cadence_us=3_000_000, signal=flow),),
            clock=clock,
            trades=trades,
        )
        assert journal.reconcile(self._opening())
        replay = CaptureReplay(trades_config, book_factory=BookAdapters.create)
        ack = b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}'
        event_ms = self._ns(self.at, 1500) // 1_000_000
        push = (
            '{"arg":{"channel":"trades","instId":"BTC-USDT"},"data":[{"instId":"BTC-USDT",'
            f'"tradeId":"5","ts":"{event_ms}","px":"100","sz":"0.5","side":"buy","count":"1"}}]}}'
        ).encode()
        tape = (
            CaptureRecord(kind="session", epoch=0, received_ns=self._ns(self.at, -2000)),
            CaptureRecord(kind="frame", epoch=0, received_ns=self._ns(self.at, -2000), raw=ack),
            CaptureRecord(kind="frame", epoch=0, received_ns=self._ns(self.at, 1500), raw=push),
        )
        books = self._markets()
        for position in range(2):
            record = tape[position]
            observer.observe_trades(
                record, BookProjection.capture(position, record, replay.apply(record), replay)
            )
        for delivery in books[:2]:
            observer.observe(delivery.source.record, delivery.source.book)
        observer.observe_trades(
            tape[2], BookProjection.capture(2, tape[2], replay.apply(tape[2]), replay)
        )
        for delivery in books[2:4]:
            observer.observe(delivery.source.record, delivery.source.book)
        assert observer.trades_delivered == 3
        retained = tuple(
            DomainCodec().decode_json(line, SharedBookDelivery)
            for line in (tmp_path / "trades.jsonl").read_bytes().splitlines()
        )
        (group,) = retained[3].decisions
        assert group.at == self.at + timedelta(milliseconds=2500)
        (decided,) = group.inputs
        assert decided.inputs is not None
        assert [(row.input.name, row.value) for row in decided.inputs.observations] == [
            ("book", ExactRatio.from_fraction(Fraction(100))),
            ("trades", ExactRatio.from_fraction(Fraction(1, 2))),
        ]
        assert journal.checkpoint("alpha") is not None
        replayed, recovered = self._shared(
            tmp_path / "replay.sqlite3",
            (self._binding(cadence_us=3_000_000, signal=flow),),
            trades=self._trades(trades_config, flow),
        )
        assert recovered.reconcile(self._opening())
        codec = DomainCodec()
        retained_trades = tuple(
            codec.decode_json(line, LiveBookDelivery)
            for line in (tmp_path / "trades.trades.jsonl").read_bytes().splitlines()
        )
        merged = sorted(
            [(item.available_at, 0, item) for item in retained_trades]
            + [(item.source.available_at, 1, item) for item in retained],
            key=self._replay_order,
        )
        for _, _, item in merged:
            if isinstance(item, SharedBookDelivery):
                replayed.deliver(item)
            else:
                replayed.deliver_trades(item)
        assert recovered.checkpoint("alpha") == journal.checkpoint("alpha")
        assert recovered.accounts() == journal.accounts()
        with pytest.raises(ValueError, match="native sources"):
            self._shared(
                tmp_path / "unfed.sqlite3", (self._binding(cadence_us=3_000_000, signal=flow),)
            )

    @classmethod
    def _shared(
        cls,
        path: Path,
        bindings: tuple[SharedStrategyBinding, ...],
        *,
        clock: _SequenceClock | None = None,
        trades: LiveTradeDecisionSource | None = None,
    ) -> tuple[SharedPaperCaptureObserver, AccountJournal]:
        """Construct deciding owners for several bindings, each with an instance budget."""
        request = cls._request()
        config = cls._config()
        limits = tuple(
            InstanceLimit(
                instance_id=item.instance_id,
                account_id="paper",
                maximum=cls._money("400"),
                instruments=(cls.dimension.instrument_id,),
            )
            for item in bindings
        )
        config = replace(config, budgets=replace(config.budgets, instances=limits))
        journal = AccountJournal(path, config)
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(request, (cls._requirement(),), history_capacity=20),
            books=BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            request.config,
                            source_id=request.identity,
                            capability=BookAdapters.capability(request.config),
                            max_age_ns=5_000_000_000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=20,
                )
            ),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, bindings),
            account_id="paper",
            scenario=cls._scenario(),
            delivery_path=path.with_suffix(".jsonl"),
            clock=clock,
            trades=trades,
        )
        return observer, journal

    @staticmethod
    def _trades(config: CaptureConfig, flow: InputRequirement) -> LiveTradeDecisionSource:
        """Bind a fresh live trade source to the fixed trades recording."""
        return LiveTradeDecisionSource(
            CaptureRequest(
                config=config,
                recording_id="22222222-2222-4222-8222-222222222222",
                implementation_identity="a" * 64,
            ),
            (flow,),
            tapes=BookAdapters.trades,
            history_capacity=20,
        )

    @staticmethod
    def _replay_order(
        item: tuple[datetime, int, LiveBookDelivery | SharedBookDelivery],
    ) -> tuple[datetime, int]:
        """Order retained deliveries by delivery time, trades before books at ties."""
        return item[0], item[1]

    @staticmethod
    def _ns(at: datetime, milliseconds: int) -> int:
        """Return exact Unix nanoseconds of an offset from a UTC instant."""
        offset = at + timedelta(milliseconds=milliseconds)
        return (offset - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 1000

    def test_grid_never_delays_source_fault(self, tmp_path: Path) -> None:
        """An invalid boundary between instants blocks a previously priced account."""
        observer, journal = self._observer(tmp_path / "invalid.sqlite3", cadence_us=3_000_000)
        assert journal.reconcile(self._opening())
        session, first, second, *_ = self._markets()
        for delivery in (
            session,
            first,
            replace(second, matched=False),
            self._delivery(
                3,
                seconds=3,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            ),
        ):
            observer.deliver(delivery)
        assert journal.accounts()[0].operator_block == "public_input_invalid"
        assert observer.last_market is not None
        assert observer.last_market.at == self.at + timedelta(seconds=2)

    def test_delivery_schema_and_decision_group_order(self, tmp_path: Path) -> None:
        """Deliveries name their schema; decided instants precede delivery and coordination."""
        delivery = self._delivery(
            0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
        )
        codec = DomainCodec()
        encoded = codec.encode_json(delivery)
        assert b'"matched":false' in encoded
        assert b'"schema_version":"shared-candidate-delivery"' in encoded
        assert codec.decode_json(encoded, SharedBookDelivery) == delivery
        with pytest.raises(msgspec.ValidationError):
            codec.decode_json(
                encoded.replace(b"shared-candidate-delivery", b"shared-book-delivery"),
                SharedBookDelivery,
            )
        observer, journal = self._observer(tmp_path / "groups.sqlite3", deciding=True)
        assert journal.reconcile(self._opening())
        session, first, second, *_ = self._markets()
        for item in (session, first):
            observer.deliver(item)
        quote = AccountQuote(price=self._price("100"), at=first.source.available_at)
        instant = self.at + timedelta(milliseconds=1500)
        inputs = observer._instance_inputs(observer.runtime.bindings[0], instant)
        assert isinstance(inputs, DecisionInputs)
        group = SharedDecisionGroup(
            at=instant,
            quote=quote,
            inputs=(SharedStrategyInput(instance_id="alpha", inputs=inputs, quote=quote),),
            coordinated_at=instant + timedelta(microseconds=1),
        )
        with pytest.raises(ValueError, match="also matches"):
            replace(second, decisions=(group,), matched=False)
        with pytest.raises(ValueError, match="out of order"):
            replace(group, coordinated_at=second.source.available_at)
        with pytest.raises(ValueError, match="precede their delivery"):
            replace(first, decisions=(group,))

    def test_managed_invalidations_fault_once_per_observer(self, tmp_path: Path) -> None:
        """The first bad source fact faults its owner without repeated account loads."""
        path = tmp_path / "managed-invalid.sqlite3"
        observer, original = self._observer(path)
        clock = _SequenceClock((self.at - timedelta(seconds=1),))
        admin = AccountJournal(path, original.config, clock=clock)
        deployment = PaperDeployment(
            account_id="paper",
            configuration_sha256=hashlib.sha256(
                DomainCodec().encode_json(original.config)
            ).hexdigest(),
            releases=("a" * 64,),
            strategies=(
                PaperStrategyIdentity(
                    instance_id="alpha",
                    policy_identity="test",
                    candidate_identity="test",
                    model_identity="test",
                    feature_identity="test",
                ),
            ),
            input_identity="test",
            scenario=self._scenario(),
            state_identity="paper-account-state",
        )
        admin.install_paper(deployment)
        admin.authorize_paper(
            PaperAuthorization(
                identity="fault-test",
                deployment_sha256=deployment.identity,
                valid_from=self.at - timedelta(seconds=1),
                expires_at=self.at + timedelta(seconds=20),
                quantities=(self._quantity("10"),),
                maximum_order_notional=self._money("1000"),
                maximum_orders=10,
            )
        )
        observed = self.at - timedelta(microseconds=1)
        admin.observe(AccountQuote(price=self._price("100"), at=observed))
        assert admin.reconcile(replace(self._opening(), at=observed))
        clock.times = (self.at,)
        owner = admin.claim_paper(
            "paper",
            "fault-worker",
            "a" * 64,
            AccountControl(
                identity="fault-claim",
                account_id="paper",
                kind="restart",
                at=self.at,
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        clock.times = (self.at + timedelta(seconds=4),)
        worker = AccountJournal(path, original.config, paper_owner=owner, clock=clock)
        observer.journal = worker
        observer.runtime = SharedDecisionRuntime(worker, (self._binding(),))
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        first = self._delivery(
            2,
            seconds=2,
            kind="gap",
            outcome="gap",
            status="recovering",
            reason="disconnect_unknown_loss",
        )
        second = self._delivery(
            3,
            seconds=3,
            kind="gap",
            outcome="gap",
            status="recovering",
            reason="disconnect_unknown_loss",
        )
        observer.deliver(first)
        observer.deliver(second)
        controls = worker.controls()
        faults = tuple(item for item in controls if item.request.reason == "public_input_invalid")
        assert len(faults) == 1 and faults[0].status == "applied"
        assert faults[0].request.identity == (
            "public-input-fault:"
            + hashlib.sha256(DomainCodec().encode_json(first.source)).hexdigest()
        )
        observer._apply(first, None, replayed=False)
        assert worker.controls() == controls
        assert worker.accounts()[0].phase == "faulted"

    def test_public_fault_unknown_outcome_propagates_without_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An uncertain account write remains visible to the supervisor for fencing."""
        observer, journal = self._observer(tmp_path / "unknown-fault.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        uncertain = _UnknownOutcome()
        monkeypatch.setattr(journal, "block", uncertain)
        with pytest.raises(TimeoutError, match="unknown account outcome"):
            observer.deliver(
                self._delivery(
                    2,
                    seconds=2,
                    kind="gap",
                    outcome="gap",
                    status="recovering",
                    reason="disconnect_unknown_loss",
                )
            )
        assert uncertain.calls == 1
        assert journal.accounts()[0].operator_block is None

    def test_rejected_public_fault_is_not_confirmed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit rejected control fences the source instead of latching success."""
        observer, journal = self._observer(tmp_path / "rejected-fault.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        monkeypatch.setattr(journal, "paper_owner", object())
        reject = _RejectedControl()
        monkeypatch.setattr(journal, "control", reject)
        with pytest.raises(ValueError, match="fault was not applied"):
            observer.deliver(
                self._delivery(
                    2,
                    seconds=2,
                    kind="gap",
                    outcome="gap",
                    status="recovering",
                    reason="disconnect_unknown_loss",
                )
            )
        assert reject.calls == 1
        assert observer._public_faulted is False

    @pytest.mark.parametrize("is_private_wire", (False, True))
    def test_observer_rejects_mutated_nested_book_before_retention(
        self, tmp_path: Path, is_private_wire: bool
    ) -> None:
        """The public entry validates nested rows before either trusted private core."""
        path = tmp_path / "untrusted.sqlite3"
        observer, journal = self._observer(path, retain=True)
        assert journal.reconcile(self._opening())
        delivery = self._delivery(
            0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
        )
        if is_private_wire:
            delivery = ObservedSharedBookDelivery(
                source=ObservedLiveBookDelivery(
                    record=delivery.source.record,
                    book=delivery.source.book,
                    available_at=delivery.source.available_at,
                ),
                decisions=(),
                matched=False,
            )
        force_setattr(delivery.source.book, "state_identity", "bad")
        with pytest.raises(ValueError, match="book state or quality"):
            LiveBookDelivery(
                record=delivery.source.record,
                book=delivery.source.book,
                available_at=delivery.source.available_at,
            )
        with pytest.raises(ValueError, match="book state or quality"):
            SharedBookDelivery(source=delivery.source, decisions=(), matched=False)
        with pytest.raises(ValueError, match="book state or quality"):
            DomainCodec().decode_json(DomainCodec().encode_json(delivery), SharedBookDelivery)
        with pytest.raises(ValueError, match="book state or quality"):
            observer.observe(delivery.source.record, delivery.source.book)
        with pytest.raises(ValueError, match="book state or quality"):
            observer.deliver(delivery)
        assert not path.with_suffix(".jsonl").exists()
        assert observer.source.latest_book is None
        assert observer.delivered_count == 0

    def test_invalid_after_market_blocks_admission_and_preserves_order(
        self, tmp_path: Path
    ) -> None:
        """A gap revokes a known eligible source without releasing outstanding exposure."""
        observer, journal = self._observer(tmp_path / "account.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        assert journal.accounts()[0].operator_block is None
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        assert observer.last_market is not None
        at = self.at + timedelta(seconds=1, microseconds=1)
        order = AccountDecision(
            account_id="paper",
            instance_id="alpha",
            decision=OrderDecision(
                identity="open-order",
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=self._quantity("1"),
                    limit=self._price("100"),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=self._price("100"), at=self.at + timedelta(seconds=1)),
            maximum_fee=self._money("1"),
        )
        assert journal.admit(order).status == "committed"
        open_order = journal.orders()[0].order
        observer.deliver(
            self._delivery(
                2,
                seconds=2,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            )
        )
        assert AccountJournal(journal.path, journal.config).accounts()[0].operator_block == (
            "public_input_invalid"
        )
        assert journal.orders()[0].order == open_order
        later = AccountDecision(
            account_id="paper",
            instance_id="alpha",
            decision=OrderDecision(
                identity="after-gap",
                at=self.at + timedelta(seconds=2),
                intent=order.decision.intent,
            ),
            quote=order.quote,
            maximum_fee=self._money("1"),
        )
        assert journal.admit(later).status == "rejected"

    @classmethod
    def _unpriceable(
        cls, position: int, *, seconds: int, crossed: bool = False
    ) -> SharedBookDelivery:
        """Author a valid per-order boundary that is one-sided or crossed mid-update."""
        delivery = cls._delivery(
            position,
            seconds=seconds,
            kind="frame",
            outcome="update",
            status="degraded",
            reason="visible_depth_only",
            market=True,
        )
        book = delivery.source.book
        level = Level(size=Decimal("4"), order_count=1)
        book = replace(book, asks=((Decimal("98"), level),) if crossed else ())
        return replace(delivery, source=replace(delivery.source, book=book), matched=False)

    def test_transient_unpriceable_book_faults_only_after_freshness(self, tmp_path: Path) -> None:
        """Intermediate per-order states are unpriced; a persistent one still faults."""
        observer, journal = self._observer(tmp_path / "transient.sqlite3")
        assert journal.reconcile(self._opening())
        opening = (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
        )
        for delivery in (
            *opening,
            self._unpriceable(2, seconds=2),
            self._unpriceable(3, seconds=2, crossed=True),
            self._delivery(
                4,
                seconds=3,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            ),
            self._delivery(
                5,
                seconds=4,
                kind="frame",
                outcome="update",
                status="degraded",
                reason="visible_depth_only",
                market=True,
                state_identity="2" * 64,
            ),
        ):
            observer.deliver(delivery)
        assert journal.accounts()[0].operator_block is None
        assert observer.last_market is not None
        assert observer.last_market.at == self.at + timedelta(seconds=4)
        persistent, persistent_journal = self._observer(tmp_path / "persistent.sqlite3")
        assert persistent_journal.reconcile(self._opening())
        for delivery in (*opening, self._unpriceable(2, seconds=2)):
            persistent.deliver(delivery)
        assert persistent_journal.accounts()[0].operator_block is None
        persistent.deliver(
            self._delivery(
                3,
                seconds=7,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            )
        )
        assert persistent_journal.accounts()[0].operator_block == "public_input_invalid"
        lost, lost_journal = self._observer(tmp_path / "lost.sqlite3")
        assert lost_journal.reconcile(self._opening())
        for delivery in (
            *opening,
            self._unpriceable(2, seconds=2),
            self._delivery(
                3,
                seconds=2,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            ),
        ):
            lost.deliver(delivery)
        assert lost_journal.accounts()[0].operator_block == "public_input_invalid"

    def test_healthy_controls_do_not_block_but_stale_progress_does(self, tmp_path: Path) -> None:
        """Heartbeat and normal finite close preserve readiness; stale input revokes it."""
        observer, journal = self._observer(tmp_path / "account.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        before_control = (
            journal.accounts(),
            journal.orders(),
            journal.paper_traces("paper"),
            journal.checkpoint("alpha"),
        )
        observer.deliver(
            self._delivery(
                2,
                seconds=2,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            )
        )
        assert journal.accounts()[0].operator_block is None
        assert (
            journal.accounts(),
            journal.orders(),
            journal.paper_traces("paper"),
            journal.checkpoint("alpha"),
        ) == before_control
        observer.deliver(
            self._delivery(
                3,
                seconds=2,
                kind="session_end",
                outcome="session_end",
                status="unavailable",
                reason="message_limit",
            )
        )
        observer.deliver(
            self._delivery(
                4,
                seconds=2,
                kind="end",
                outcome="end",
                status="unavailable",
                reason="message_limit",
            )
        )
        assert journal.accounts()[0].operator_block is None
        stale, stale_journal = self._observer(tmp_path / "stale.sqlite3")
        assert stale_journal.reconcile(self._opening())
        for delivery in (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            self._delivery(
                2,
                seconds=7,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            ),
        ):
            stale.deliver(delivery)
        assert stale_journal.accounts()[0].operator_block == "public_input_invalid"

    @pytest.mark.parametrize("changed", ("model", "feature"))
    def test_managed_workload_identity_mismatch_precedes_capture(
        self, tmp_path: Path, changed: str
    ) -> None:
        """Refuse changed model or feature bindings before source access or economics."""
        config, binding = self._config(), self._binding()
        request, requirement = self._request(), self._requirement()
        candidate = binding.candidate
        codec = DomainCodec()
        deployment = PaperDeployment(
            account_id="paper",
            configuration_sha256=hashlib.sha256(codec.encode_json(config)).hexdigest(),
            releases=("a" * 64,),
            strategies=(
                PaperStrategyIdentity(
                    instance_id=binding.instance_id,
                    policy_identity=candidate.policy.identity,
                    candidate_identity=candidate.definition.identity,
                    model_identity="changed-model" if changed == "model" else "rule-only",
                    feature_identity="changed-feature"
                    if changed == "feature"
                    else candidate.feature.schema.identity,
                ),
            ),
            input_identity=hashlib.sha256(
                codec.encode_json((request.config, (requirement,)))
            ).hexdigest(),
            scenario=self._scenario(),
            state_identity="paper-account-state",
        )
        path = tmp_path / "managed.sqlite3"
        admin = AccountJournal(path, config)
        admin.install_paper(deployment)
        admin.authorize_paper(
            PaperAuthorization(
                identity="bounded-workload",
                deployment_sha256=deployment.identity,
                valid_from=self.at,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                quantities=(self._quantity("2"),),
                maximum_order_notional=self._money("100"),
                maximum_orders=2,
            )
        )
        assert admin.reconcile(replace(self._opening(), at=datetime.now(UTC)))
        admin.observe(AccountQuote(price=self._price("10"), at=datetime.now(UTC)))
        owner = admin.claim_paper(
            "paper",
            "reference-worker",
            "a" * 64,
            AccountControl(
                identity="claim-reference",
                account_id="paper",
                kind="restart",
                at=datetime.now(UTC),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        before = admin.accounts()
        with pytest.raises(ValueError, match="deployment workload bindings differ"):
            asyncio.run(
                run_live_shared_paper(
                    config,
                    account_id="paper",
                    bindings=(binding,),
                    scenario=self._scenario(),
                    request=request,
                    journal_path=path,
                    output=tmp_path / "capture",
                    paper_account=AccountJournal(path, config, paper_owner=owner),
                )
            )
        assert admin.accounts() == before
        assert admin.orders() == ()
        assert not (tmp_path / "capture").exists()

    def test_binding_and_opening_refusals_leave_visible_account_block(self, tmp_path: Path) -> None:
        """A foreign scenario fails before binding, and a bad opening blocks the journal."""
        with pytest.raises(ValueError, match="binding differs"):
            self._observer(
                tmp_path / "binding.sqlite3",
                scenario=PaperExecutionScenario(
                    venue="bitfinex",
                    instrument_id=self.dimension.instrument_id,
                    entry_delay_us=1000,
                    cancel_delay_us=2000,
                    adverse=self._price("0"),
                    fee_rate=Decimal("0"),
                    take_fraction=Decimal("1"),
                    gas_inapplicable_reason="off-chain",
                ),
            )
        bad = AccountObservation(
            identity="wrong-opening",
            at=self._opening().at,
            snapshot=AccountSnapshot(
                account_id="wrong",
                instance_id=None,
                cash=(self._money("1000"),),
                positions=(),
                fees=(self._money("0"),),
                rebates=(self._money("0"),),
                transfers=(self._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )
        path = tmp_path / "opening.sqlite3"
        with pytest.raises(ValueError, match="opening or recovery reconciliation failed"):
            asyncio.run(
                run_live_shared_paper(
                    self._config(),
                    account_id="paper",
                    bindings=(self._binding(),),
                    scenario=self._scenario(),
                    request=self._request(),
                    journal_path=path,
                    output=tmp_path / "run",
                    observations=(bad,),
                )
            )
        assert AccountJournal(path, self._config()).accounts()[0].operator_block == (
            "public_paper_failure"
        )
        prior_path = tmp_path / "source-invalid.sqlite3"
        AccountJournal(prior_path, self._config()).block("paper", "public_input_invalid")
        with pytest.raises(ValueError, match="opening or recovery reconciliation failed"):
            asyncio.run(
                run_live_shared_paper(
                    self._config(),
                    account_id="paper",
                    bindings=(self._binding(),),
                    scenario=self._scenario(),
                    request=self._request(),
                    journal_path=prior_path,
                    output=tmp_path / "prior-run",
                    observations=(bad,),
                )
            )
        assert AccountJournal(prior_path, self._config()).accounts()[0].operator_block == (
            "public_input_invalid"
        )

    def test_public_monitoring_passes_only_selected_accounts_orders(self, tmp_path: Path) -> None:
        """Ignore other accounts' orders and preserve both ledgers during monitoring."""
        base = self._config()
        account_ids = ("paper", "paper-other")
        budgets = replace(
            base.budgets,
            firm_maximum=self._money("2000"),
            accounts=(
                AccountLimit(account_id="paper", maximum=self._money("1000")),
                AccountLimit(account_id="paper-other", maximum=self._money("1000")),
            ),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="paper",
                    maximum=self._money("900"),
                    instruments=(self.dimension.instrument_id,),
                ),
                InstanceLimit(
                    instance_id="beta",
                    account_id="paper-other",
                    maximum=self._money("900"),
                    instruments=(self.dimension.instrument_id,),
                ),
            ),
        )
        config = replace(
            base,
            accounts=(
                OpeningAccount(account_id="paper", cash=(self._money("1000"),)),
                OpeningAccount(account_id="paper-other", cash=(self._money("1000"),)),
            ),
            budgets=budgets,
        )
        journal = AccountJournal(tmp_path / "accounts.sqlite3", config)
        opening = self._opening()
        for account_id in account_ids:
            account_opening = replace(
                opening,
                identity=f"opening-{account_id}",
                snapshot=replace(
                    opening.snapshot,
                    account_id=account_id,
                ),
            )
            assert journal.reconcile(account_opening)

        scenario = self._scenario()
        journal.bind_paper_scenario("paper", scenario)
        other_order = AccountDecision(
            account_id="paper-other",
            instance_id="beta",
            decision=OrderDecision(
                identity="other-account-order",
                at=self.at,
                intent=OrderIntent(
                    side="buy",
                    quantity=self._quantity("1"),
                    limit=self._price("100"),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=self._price("100"), at=self.at),
            maximum_fee=self._money("1"),
        )
        journal.observe(other_order.quote)
        admitted = journal.admit(other_order)
        assert admitted.status == "committed", admitted.reason
        trace = journal.match_public_market(
            "paper",
            PaperMarket(
                identity="paper-market",
                at=self.at + timedelta(seconds=1),
                bid=self._price("99.99"),
                ask=self._price("100"),
                bid_quantity=self._quantity("1"),
                ask_quantity=self._quantity("1"),
            ),
            scenario,
        )
        assert trace.account_id == "paper"
        assert {item.account_id for item in journal.orders()} == {"paper-other"}
        ledgers_before = {view.ledger.account_id: view.ledger for view in journal.accounts()}
        assert set(ledgers_before) == set(account_ids)
        assert all(
            AccountLedger(ledger).snapshot().cash == (self._money("1000"),)
            for ledger in ledgers_before.values()
        )

        result = retain_public_paper_monitoring(
            journal,
            account_id="paper",
            request=self._request(),
            root=tmp_path,
            observed_at=self.at + timedelta(seconds=2),
            report=None,
            decisions=(),
            prior_trace_ids=frozenset(),
            summary={},
            processing_ns=None,
            delivered_count=0,
            alert_socket=None,
        )

        assert result.errors == ()
        assert result.dashboards
        assert {
            view.ledger.account_id: view.ledger for view in journal.accounts()
        } == ledgers_before
