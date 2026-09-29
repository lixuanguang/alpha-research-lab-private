"""Exercise public ingestion, causal selections and recovery with independent source bytes."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from functools import partial
from itertools import pairwise
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_book_datasets import TestBookDatasets as _Books

# project library imports
from configuration import CaptureConfig, PublicDataJob
from financial_units import Currency, Dimension, ExactRatio, Price, Quantity, QuantityKind
from market_data.acquisition import PublicAcquisition, PublicIngestion
from market_data.acquisition.public import PendingResponse
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import (
    CaptureRecord,
    CaptureRequest,
    PublicReceipt,
    PublicRequest,
    RawObject,
    RequestBinding,
)
from market_data.datasets import (
    BookInput,
    DatasetPublication,
    PublicTradeManifest,
    SnapshotCatalog,
    SnapshotStore,
)
from market_data.query import BookQuery, BookQueryReader, PublicTradeQuery, PublicTradeReader
from market_data.storage import CaptureJournal, RawStore
from reference_data.catalogs import ReferenceHistory, VenueSpecification
from research.exploration import (
    BookSelection,
    PublicTradeResearchInput,
    PublicTradeSelection,
    ReferenceResearchInput,
    ReferenceSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import FeatureSchema, FeatureSession, ProjectionFeature
from research.observations import InputRequirement, NumericField
from risk import SpotLimits
from serialization import DomainCodec

_START = datetime(2026, 9, 23, 12, tzinfo=UTC)
_RECEIVED = _START + timedelta(hours=1)
_OKX_REFERENCE = (
    b'{"code":"0","data":[{"instType":"SPOT","instId":"BTC-USDT","baseCcy":"BTC",'
    b'"quoteCcy":"USDT","tickSz":"0.1","lotSz":"0.00000001","minSz":"0.00001",'
    b'"state":"live"}]}'
)
_BITFINEX_REFERENCE = b'[["BTCUSD"],[["BTCUSD",[null,null,null,"0.00004","2000"]]]]'
_OKX_TRADES = (
    b'{"code":"0","data":[{"instId":"BTC-USDT","tradeId":"20","ts":"1790164800200",'
    b'"px":"100.2","sz":"0.3","side":"sell"},{"instId":"BTC-USDT","tradeId":"19",'
    b'"ts":"1790164800100","px":"100.1","sz":"0.2","side":"buy"}]}'
)
_BITFINEX_TRADES = b"[[7,1790164800100,0.25,101.3],[8,1790164800200,-0.15,101.2]]"


class _Clock:
    """Supply independent deterministic receipt and scheduling observations."""

    def __init__(self, at: datetime = _RECEIVED) -> None:
        """Start at an explicitly hypothetical local observation instant."""
        self.at = at

    def now(self) -> datetime:
        """Return a stable instant until the worker explicitly waits."""
        return self.at

    def sleep(self, seconds: float) -> None:
        """Advance the injected wall clock without waiting in a software test."""
        self.at += timedelta(seconds=seconds)


class _Transport:
    """Return independently authored protocol responses and retain requested endpoints."""

    def __init__(self, payloads: tuple[bytes, ...]) -> None:
        """Retain an ordered fixture response sequence."""
        self.payloads = list(payloads)
        self.requests: list[tuple[str, str]] = []

    def get(self, host: str, path: str) -> bytes:
        """Fail on unexpected refetches rather than silently recycling fixture bytes."""
        self.requests.append((host, path))
        if not self.payloads:
            raise AssertionError("unexpected public source request")
        return self.payloads.pop(0)


class _PollingTransport:
    """Answer both references, then distinct capture pages, timing every request."""

    def __init__(self) -> None:
        """Start before the first reference request."""
        self.requested: list[float] = []

    def get(self, host: str, path: str) -> bytes:
        """Return the next response with fresh trade IDs and record when it was asked for."""
        self.requested.append(time.perf_counter())
        count = len(self.requested)
        if count <= 2:
            return (_OKX_REFERENCE, _BITFINEX_REFERENCE)[count - 1]
        if "okx" in host:
            return _OKX_TRADES.replace(b'"20"', f'"{2 * count}"'.encode()).replace(
                b'"19"', f'"{2 * count - 1}"'.encode()
            )
        newer = f"[{2 * count + 1},1790164800200,-0.15,101.2]"
        return f"[{newer},[{2 * count},1790164800100,0.25,101.3]]".encode()


class _LostAcknowledgement(RawStore):
    """Model death after durable raw publication but before checkpoint acknowledgement."""

    def publish(self, source: Path, *, descriptor: RawObject, request: RequestBinding) -> Path:
        """Publish bytes then fail, leaving the original pending receipt for recovery."""
        super().publish(source, descriptor=descriptor, request=request)
        raise OSError("lost raw publication acknowledgement")


class _RegressedPublicationClock(RawStore):
    """Move the observed wall clock backwards across a real raw publication."""

    def __init__(self, root: Path, clock: _Clock) -> None:
        """Bind the temporary store and independently controlled local clock."""
        super().__init__(root)
        self._clock = clock

    def publish(self, source: Path, *, descriptor: RawObject, request: RequestBinding) -> Path:
        """Retain bytes before simulating a backwards wall-clock adjustment."""
        path = super().publish(source, descriptor=descriptor, request=request)
        self._clock.at -= timedelta(seconds=1)
        return path


class TestPublicData:
    """Test real shared APIs with explicit synthetic evidence, not venue qualification claims."""

    @staticmethod
    def _job() -> PublicDataJob:
        """Read the same multi-instrument configuration used by installed applications."""
        return PublicDataJob.read(Path("configs/data-jobs/public-spot-trades.json"))

    @classmethod
    def _acquire(
        cls, root: Path, *, trades: bytes = _OKX_TRADES
    ) -> tuple[PublicAcquisition, RawStore]:
        """Run complete reference and trade ingestion into a fresh raw store."""
        raw_path = root / "raw"
        raw_path.mkdir()
        raw = RawStore(raw_path)
        clock = _Clock()
        state = PublicIngestion(SourceAdapters(), raw).resume(
            cls._job(),
            implementation_identity="a" * 64,
            path=root / "acquisition.json",
            transport=_Transport((_OKX_REFERENCE, _BITFINEX_REFERENCE, trades, _BITFINEX_TRADES)),
            clock=clock.now,
            sleep=clock.sleep,
        )
        return state, raw

    @classmethod
    def _published(
        cls, root: Path, *, trades: bytes = _OKX_TRADES
    ) -> tuple[PublicTradeQuery, RawStore]:
        """Publish through the existing atomic snapshot store with raw re-decoding."""
        state, raw = cls._acquire(root, trades=trades)
        snapshots = root / "snapshots"
        snapshots.mkdir()
        manifest, payload = PublicTradeManifest.assemble(
            state,
            raw,
            readers=SourceAdapters(),
            max_bytes=1_000_000,
            normalization_identity="b" * 64,
        )
        identity = SnapshotStore(
            snapshots, raw, readers=SourceAdapters(), manifest_type=PublicTradeManifest
        ).publish(manifest, (payload,), max_bytes=1_000_000)
        return PublicTradeQuery(
            snapshot_id=identity,
            instruments=state.job.universes.research,
            start=state.job.start,
            end=state.job.end,
            known_at=_RECEIVED + timedelta(minutes=1),
            max_bytes=1_000_000,
        ), raw

    def test_cutoff_discovery_assembly_and_replay(self, tmp_path: Path) -> None:
        """Discover exact IDs, preserve native units and exclude data before local knowledge."""
        query, raw = self._published(tmp_path)
        reader = PublicTradeReader(tmp_path / "snapshots", raw, readers=SourceAdapters())
        result = reader.read(query)
        assert [row.trade.price for row in result.rows] == [
            Decimal("100.2"),
            Decimal("100.1"),
            Decimal("101.3"),
            Decimal("101.2"),
        ]
        assert [row.trade.side for row in result.rows] == ["sell", "buy", "buy", "sell"]
        assert all(row.specification_identity is None for row in result.rows)
        assert (
            reader.read(replace(query, known_at=_RECEIVED - timedelta(microseconds=1))).rows == ()
        )
        assert len(tuple(reader.replay(query))) == 4
        cursor = tuple(reader.replay(query))[1][0]
        assert len(tuple(reader.replay(query, after=cursor))) == 2
        with pytest.raises(ValueError, match="another query"):
            tuple(
                reader.replay(
                    replace(query, known_at=query.known_at + timedelta(seconds=1)), after=cursor
                )
            )
        catalog = SnapshotCatalog(tmp_path / "snapshots").discover(
            max_entries=10, max_bytes=1_000_000
        )
        assert tuple(m.identity for m in catalog) == (query.snapshot_id,)
        selection = ResearchSelection(
            inputs=(
                PublicTradeSelection(name="trades", query=query),
                ReferenceSelection(name="venue_rules", query=query),
            )
        )
        restored = DomainCodec().decode_json(
            DomainCodec().encode_json(selection), ResearchSelection
        )
        dataset = ResearchReader(tmp_path / "snapshots", raw, readers=SourceAdapters()).read(
            restored
        )
        assert isinstance(dataset.inputs[0], PublicTradeResearchInput)
        assert isinstance(dataset.inputs[1], ReferenceResearchInput)
        assert (
            dataset.inputs[1].history.resolve(
                query.instruments[0], valid_at=_START, known_at=query.known_at
            )
            is None
        )
        assert [i.quote_currency for i in result.instruments] == ["USDT", "USD"]

    def test_named_trade_and_reference_features_use_actual_cutoffs(self, tmp_path: Path) -> None:
        """Carry both venues through exact public/reference feature projections."""
        query, raw = self._published(tmp_path)
        reader = ResearchReader(tmp_path / "snapshots", raw, readers=SourceAdapters())
        selection = ResearchSelection(
            inputs=(
                PublicTradeSelection(name="trades", query=query),
                ReferenceSelection(name="rules", query=query),
            )
        )
        for instrument, expected in zip(
            self._job().instruments[:2], (Fraction("0.3"), Fraction("0.15")), strict=True
        ):
            requirements = (
                InputRequirement(
                    name="trades",
                    family="trade",
                    clock="event",
                    field=NumericField(name="quantity", units=instrument.base_currency),
                    max_age_us=7_200_000_000,
                ),
                InputRequirement(
                    name="rules",
                    family="reference",
                    clock="valid",
                    field=NumericField(name="minimum_quantity", units=instrument.base_currency),
                    max_age_us=7_200_000_000,
                ),
            )
            source = SavedDecisionSource(reader, selection, requirements)
            schema = FeatureSchema(
                implementation="named-projection-v1",
                inputs=requirements,
                outputs=(
                    NumericField(name="size", units=instrument.base_currency),
                    NumericField(name="minimum", units=instrument.base_currency),
                ),
                parameters=(),
                mode="batch",
                ttl_us=0,
            )
            session = FeatureSession(
                ProjectionFeature(schema), instance="public", entity=str(instrument.instrument_id)
            )
            missing = session.evaluate(
                source.read(str(instrument.instrument_id), _RECEIVED - timedelta(microseconds=1))
            )
            assert missing.values == (None, None)
            observed = session.evaluate(source.read(str(instrument.instrument_id), query.known_at))
            assert observed.values[0] == ExactRatio.from_fraction(expected)
            assert observed.values[1] is not None
            assert observed.information_start == _START + timedelta(milliseconds=200)
            assert (
                source.read(str(instrument.instrument_id), _RECEIVED - timedelta(microseconds=1))
                .observations[0]
                .value
                is None
            )

    def test_equal_time_public_trades_use_native_position_tie_break(self, tmp_path: Path) -> None:
        """Distinct same-millisecond trades remain valid and use the last retained position."""
        query, raw = self._published(
            tmp_path, trades=_OKX_TRADES.replace(b"1790164800100", b"1790164800200")
        )
        requirement = InputRequirement(
            name="trades",
            family="trade",
            clock="event",
            field=NumericField(name="quantity", units="BTC"),
            max_age_us=7_200_000_000,
        )
        source = SavedDecisionSource(
            ResearchReader(tmp_path / "snapshots", raw, readers=SourceAdapters()),
            ResearchSelection(inputs=(PublicTradeSelection(name="trades", query=query),)),
            (requirement,),
        )
        assert source.read(str(query.instruments[0]), query.known_at).observations[
            0
        ].value == ExactRatio(numerator="1", denominator="5")

    def test_saved_book_features_keep_receipt_clock_and_invalidation(self, tmp_path: Path) -> None:
        """Native L2 depth 3 versus 1 yields exactly 1/2; a later gap removes the value."""
        config = CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))
        request = CaptureRequest(
            config=config,
            recording_id="00000000-0000-0000-0000-000000000099",
            implementation_identity="a" * 64,
        )
        journal = CaptureJournal(tmp_path / "capture", request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        journal.append(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=1000,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            )
        )
        journal.append(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=2000,
                raw=_Books._frame(
                    "snapshot", -1, 10, '[["100","3","0","1"]]', '[["101","1","0","1"]]'
                ),
            )
        )
        journal.append(CaptureRecord(kind="gap", epoch=0, received_ns=4000, reason="unknown_loss"))
        journal.append(CaptureRecord(kind="end", epoch=0, received_ns=5000, reason="message_limit"))
        journal.finish(1)
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        raw = RawStore(tmp_path / "raw")
        snapshot = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (tmp_path / "capture",),
            raw,
            tmp_path / "snapshots",
            max_records=16,
            max_bytes=1_000_000,
        )
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        query = BookQuery(
            snapshot_id=snapshot,
            request_identity=request.identity,
            instrument=config.instrument_id,
            start=epoch,
            end=epoch + timedelta(seconds=1),
            known_at=epoch + timedelta(seconds=1),
            columns=("bids", "asks"),
            batch_size=2,
            max_bytes=1_000_000,
        )
        requirement = InputRequirement(
            name="depth",
            family="book",
            clock="receipt",
            field=NumericField(name="imbalance", units="dimensionless"),
            max_age_us=100,
        )
        source = SavedDecisionSource(
            ResearchReader(tmp_path / "snapshots", raw, readers=SourceAdapters()),
            ResearchSelection(inputs=(BookSelection(name="depth", query=query),)),
            (requirement,),
        )
        assert source.read(
            str(config.instrument_id), epoch + timedelta(microseconds=3)
        ).observations[0].value == ExactRatio(numerator="1", denominator="2")
        gap = source.read(str(config.instrument_id), epoch + timedelta(microseconds=4))
        assert gap.observations[0].value is None
        assert gap.observations[0].reason == "invalid_book_control"

    def test_pending_receipt_resumes_without_refetch(self, tmp_path: Path) -> None:
        """Recover a durable object whose acknowledgement was lost using its original clock."""
        raw_path = tmp_path / "raw"
        raw_path.mkdir()
        clock, job = _Clock(), self._job()
        transport = _Transport((_OKX_REFERENCE, _BITFINEX_REFERENCE, _OKX_TRADES, _BITFINEX_TRADES))
        path = tmp_path / "acquisition.json"
        with pytest.raises(OSError, match="lost raw"):
            PublicIngestion(SourceAdapters(), _LostAcknowledgement(raw_path)).resume(
                job,
                implementation_identity="a" * 64,
                path=path,
                transport=transport,
                clock=clock.now,
                sleep=clock.sleep,
            )
        retained = DomainCodec().decode_json(path.read_bytes(), PublicAcquisition)
        assert retained.pending is not None and retained.pending.received == _RECEIVED
        clock.at += timedelta(minutes=5)
        ingestion = PublicIngestion(SourceAdapters(), RawStore(raw_path))
        completed = ingestion.resume(
            job,
            implementation_identity="a" * 64,
            path=path,
            transport=transport,
            clock=clock.now,
            sleep=clock.sleep,
        )
        assert len(transport.requests) == 4
        assert completed.receipts[0].raw.ts_received == _RECEIVED
        assert (
            ingestion.resume(
                job,
                implementation_identity="a" * 64,
                path=path,
                transport=_Transport(()),
                clock=clock.now,
                sleep=clock.sleep,
            )
            == completed
        )
        with pytest.raises(ValueError, match="identical job"):
            ingestion.resume(
                replace(job, max_pages=99),
                implementation_identity="a" * 64,
                path=path,
                transport=_Transport(()),
                clock=clock.now,
                sleep=clock.sleep,
            )

    def test_checkpoint_steps_refuse_exactly_what_whole_validation_refuses(
        self, tmp_path: Path
    ) -> None:
        """Adding a response or receipt checks only it, with whole-state outcomes and messages."""
        completed, _ = self._acquire(tmp_path)
        state = replace(completed, complete=False, finished_at=None)
        last = state.receipts[-1]
        later = last.raw.ts_ingested + timedelta(seconds=1)
        foreign = replace(last.request, job_identity="f" * 64)
        pendings = (
            PendingResponse(request=last.request, payload=b"[]", received=later),
            PendingResponse(request=last.request, payload=b"[]", received=_START),
            PendingResponse(request=foreign, payload=b"[]", received=later),
            PendingResponse(
                request=last.request, payload=bytes(state.job.max_bytes), received=later
            ),
        )
        for base in (state, completed):
            for pending in pendings:
                self._assert_same_outcome(
                    partial(base._with_pending, pending),
                    partial(self._whole_with_pending, base, pending),
                )
        assert state.pending is None
        raw = replace(last.raw, ts_received=later, ts_ingested=later)
        assert completed.finished_at is not None
        beyond = completed.finished_at + timedelta(seconds=1)
        receipts = (
            PublicReceipt(request=last.request, raw=raw),
            PublicReceipt(request=last.request, raw=replace(raw, ts_received=_START)),
            PublicReceipt(
                request=foreign, raw=replace(raw, request_identity=foreign.binding.identity)
            ),
            PublicReceipt(request=last.request, raw=replace(raw, size_bytes=state.job.max_bytes)),
            PublicReceipt(
                request=last.request, raw=replace(raw, ts_received=beyond, ts_ingested=beyond)
            ),
        )
        unsafe = PublicReceipt(request=last.request, raw=replace(raw))
        force_setattr(unsafe.raw, "sha256", "not-a-digest")
        pending_state = replace(state, pending=pendings[0])
        for base in (pending_state, completed):
            for receipt in (*receipts, unsafe):
                self._assert_same_outcome(
                    partial(base._with_receipt, receipt),
                    partial(self._whole_with_receipt, base, receipt),
                )
        assert pending_state.pending == pendings[0] and pending_state.receipts == state.receipts

    @staticmethod
    def _whole_with_pending(base: PublicAcquisition, pending: PendingResponse) -> PublicAcquisition:
        """Validate the whole successor that holds a new pending response."""
        return replace(base, pending=pending)

    @staticmethod
    def _whole_with_receipt(base: PublicAcquisition, receipt: PublicReceipt) -> PublicAcquisition:
        """Validate the whole successor that commits one more receipt."""
        receipts: tuple[PublicReceipt, ...] = (*base.receipts, receipt)
        return replace(base, receipts=receipts, pending=None)

    @staticmethod
    def _assert_same_outcome(
        step: Callable[[], PublicAcquisition], whole: Callable[[], PublicAcquisition]
    ) -> None:
        """Require an incremental checkpoint step to match validating the whole successor."""
        try:
            expected = whole()
        except ValueError as error:
            with pytest.raises(ValueError) as refused:
                step()
            assert str(refused.value) == str(error)
            return
        actual = step()
        actual.__post_init__()
        assert actual == expected
        assert DomainCodec().encode_json(actual) == DomainCodec().encode_json(expected)

    @pytest.mark.performance
    def test_capture_page_cost_does_not_grow_with_saved_pages(self, tmp_path: Path) -> None:
        """A new capture page costs about the same after 50 or 200 saved pages."""
        medians: list[float] = []
        for pages in (50, 200):
            root = tmp_path / str(pages)
            (root / "raw").mkdir(parents=True)
            job = replace(
                self._job(),
                mode="capture",
                end=_START + timedelta(seconds=5 * pages),
                max_pages=1000,
            )
            transport, clock = _PollingTransport(), _Clock(_START)
            state = PublicIngestion(SourceAdapters(), RawStore(root / "raw")).resume(
                job,
                implementation_identity="a" * 64,
                path=root / "acquisition.json",
                transport=transport,
                clock=clock.now,
                sleep=clock.sleep,
            )
            assert len(state.receipts) == pages + 2
            gaps = sorted(later - earlier for earlier, later in pairwise(transport.requested[-22:]))
            medians.append(gaps[len(gaps) // 2])
        print(f"capture page at 50/200 saved pages: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Re-verifying every saved page and receipt per page grew about fourfold here; the
        # checkpoint rewrite still grows slowly with the saved receipts.
        assert medians[1] < 2.5 * medians[0]

    def test_clock_regression_retains_pending_and_rejects_reordered_knowledge(
        self, tmp_path: Path
    ) -> None:
        """Reject backwards durable clocks without clamping or acknowledging the response."""
        raw_path = tmp_path / "raw"
        raw_path.mkdir()
        clock, path = _Clock(), tmp_path / "acquisition.json"
        with pytest.raises(ValueError, match="clock regressed during publication"):
            PublicIngestion(SourceAdapters(), _RegressedPublicationClock(raw_path, clock)).resume(
                self._job(),
                implementation_identity="a" * 64,
                path=path,
                transport=_Transport((_OKX_REFERENCE,)),
                clock=clock.now,
                sleep=clock.sleep,
            )
        retained = DomainCodec().decode_json(path.read_bytes(), PublicAcquisition)
        assert retained.pending is not None and retained.pending.received == _RECEIVED
        assert retained.receipts == ()
        clock.at = _RECEIVED + timedelta(seconds=2)
        state = PublicIngestion(SourceAdapters(), RawStore(raw_path)).resume(
            self._job(),
            implementation_identity="a" * 64,
            path=path,
            transport=_Transport((_BITFINEX_REFERENCE, _OKX_TRADES, _BITFINEX_TRADES)),
            clock=clock.now,
            sleep=clock.sleep,
        )
        # The second response follows the first receipt but precedes durable ingestion.
        second = replace(
            state.receipts[1],
            raw=replace(
                state.receipts[1].raw,
                ts_received=_RECEIVED + timedelta(seconds=1),
                ts_ingested=_RECEIVED + timedelta(seconds=1),
            ),
        )
        with pytest.raises(ValueError, match="public receipt clock regressed"):
            replace(state, receipts=(state.receipts[0], second))

    def test_universes_and_capabilities_fail_before_source_access(self, tmp_path: Path) -> None:
        """Research selection cannot expand strategy/trading scopes or admit unsupported assets."""
        query, raw = self._published(tmp_path)
        with pytest.raises(ValueError, match="strategy universe"):
            PublicTradeReader(tmp_path / "snapshots", raw, readers=SourceAdapters()).read(
                replace(query, purpose="strategy")
            )
        job = self._job()
        with pytest.raises(ValueError, match="authorized_trading universe"):
            job.universes.require(job.instruments[0].instrument_id, "authorized_trading")
        source = SourceAdapters().public(job.instruments[0])
        for instrument in (
            replace(job.instruments[0], product="future"),
            replace(job.instruments[0], calendar="XNYS"),
        ):
            with pytest.raises(ValueError, match="capabilities"):
                source.capability.admit(instrument, channel="trades", mode="backfill")
        with pytest.raises(ValueError, match="capabilities"):
            source.capability.admit(
                job.instruments[0], channel="trades", mode="backfill", historical_reference=True
            )

    def test_source_pagination_does_not_drop_equal_time_trades(self) -> None:
        """Require timestamp overlap and fail on unpageable saturation instead of skipping."""
        job = replace(self._job(), page_size=2)
        instrument = job.instruments[1]
        request = PublicRequest(
            job_identity=job.identity,
            implementation_identity="a" * 64,
            instrument=instrument,
            kind="trades",
            cursor=None,
            ordinal=0,
        )
        source = SourceAdapters().public(instrument)
        page = source.trades(job, request, _BITFINEX_TRADES)
        assert page.next_cursor == "1790164800200"
        with pytest.raises(ValueError, match="saturated millisecond"):
            source.trades(
                job,
                replace(request, cursor="1790164800200", ordinal=1),
                b"[[8,1790164800200,-0.15,101.2],[9,1790164800200,0.3,101.3]]",
            )
        okx = job.instruments[0]
        request = replace(request, instrument=okx)
        assert SourceAdapters().public(okx).trades(job, request, _OKX_TRADES).next_cursor == "19"
        with pytest.raises(ValueError, match="did not advance"):
            SourceAdapters().public(okx).trades(job, replace(request, cursor="20"), _OKX_TRADES)

    def test_reference_corrections_do_not_change_earlier_decisions(self) -> None:
        """Resolve a late tick correction by valid and known time and reject unknown order rules."""
        instrument = self._job().instruments[0]
        original = VenueSpecification(
            instrument=instrument,
            valid_from=_START,
            valid_to=_START + timedelta(days=1),
            ts_knowledge=_START,
            source_digest="a" * 64,
            basis="source_history",
            price_tick=Decimal("0.1"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.1"),
            status="live",
        )
        corrected = replace(
            original,
            price_tick=Decimal("0.2"),
            ts_knowledge=_RECEIVED,
            source_digest="b" * 64,
            supersedes=original.identity,
        )
        history = ReferenceHistory(specifications=(original, corrected))
        assert (
            history.resolve(instrument.instrument_id, valid_at=_START, known_at=_START) == original
        )
        assert (
            history.resolve(instrument.instrument_id, valid_at=_START, known_at=_RECEIVED)
            == corrected
        )
        dimension = Dimension(instrument_id=instrument.instrument_id, kind=QuantityKind.BASE_UNIT)
        currency = Currency.from_code("USDT")
        limits = SpotLimits.from_reference(
            history,
            maximum=Quantity(value=Decimal("1"), dimension=dimension),
            quote_currency=currency,
            valid_at=_START,
            known_at=_START,
            max_age=timedelta(hours=1),
        )
        assert limits.specification_identity == original.identity
        assert (
            limits.order_reason(
                Quantity(value=Decimal("0.1"), dimension=dimension),
                Price(value=Decimal("100.2"), currency=currency, per=dimension),
            )
            is None
        )
        assert (
            limits.order_reason(
                Quantity(value=Decimal("0.05"), dimension=dimension),
                Price(value=Decimal("100.2"), currency=currency, per=dimension),
            )
            == "minimum_order_quantity"
        )
        assert (
            limits.order_reason(
                Quantity(value=Decimal("0.1"), dimension=dimension),
                Price(value=Decimal("100.25"), currency=currency, per=dimension),
            )
            == "invalid_reference_price"
        )
        assert (
            history.resolve(
                instrument.instrument_id, valid_at=_START - timedelta(seconds=1), known_at=_RECEIVED
            )
            is None
        )
        with pytest.raises(ValueError, match="stale"):
            history.require_order(
                instrument.instrument_id,
                valid_at=_RECEIVED + timedelta(hours=1),
                known_at=_RECEIVED,
                max_age=timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="historical validity"):
            replace(original, basis="current_observation", ts_knowledge=_RECEIVED)

    def test_corruption_and_incomplete_prefixes_cannot_publish(self, tmp_path: Path) -> None:
        """Fail the entire publication on missing or altered source evidence."""
        state, raw = self._acquire(tmp_path)
        with pytest.raises(ValueError, match="completed ingestion"):
            PublicTradeManifest.assemble(
                replace(state, complete=False, finished_at=None),
                raw,
                readers=SourceAdapters(),
                max_bytes=1_000_000,
                normalization_identity="b" * 64,
            )
        path = tmp_path / "raw" / state.receipts[-1].raw.sha256
        path.chmod(0o600)
        path.write_bytes(b"[]")
        with pytest.raises(ValueError):
            PublicTradeManifest.assemble(
                state,
                raw,
                readers=SourceAdapters(),
                max_bytes=1_000_000,
                normalization_identity="b" * 64,
            )

    def test_polling_revisions_remain_causal_and_restartable(self, tmp_path: Path) -> None:
        """A later changed value cannot alter an earlier cutoff or backdate repeated values."""
        job = replace(self._job(), mode="capture", end=_START + timedelta(seconds=15))
        raw_path, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw_path.mkdir()
        snapshots.mkdir()
        raw, clock = RawStore(raw_path), _Clock(_START)
        transport = _Transport(
            (
                _OKX_REFERENCE,
                _BITFINEX_REFERENCE,
                _OKX_TRADES,
                b"[[8,1790164800200,-0.15,101.2],[7,1790164800100,0.25,101.3]]",
                _OKX_TRADES.replace(b'"100.2"', b'"99.9"'),
            )
        )
        state = PublicIngestion(SourceAdapters(), raw).resume(
            job,
            implementation_identity="a" * 64,
            path=tmp_path / "acquisition.json",
            transport=transport,
            clock=clock.now,
            sleep=clock.sleep,
        )
        manifest, payload = PublicTradeManifest.assemble(
            state,
            raw,
            readers=SourceAdapters(),
            max_bytes=1_000_000,
            normalization_identity="b" * 64,
        )
        identity = SnapshotStore(
            snapshots, raw, readers=SourceAdapters(), manifest_type=PublicTradeManifest
        ).publish(manifest, (payload,), max_bytes=1_000_000)
        query = PublicTradeQuery(
            snapshot_id=identity,
            instruments=job.universes.research,
            start=job.start,
            end=job.end,
            known_at=_START + timedelta(seconds=9),
            max_bytes=1_000_000,
        )
        reader = PublicTradeReader(snapshots, raw, readers=SourceAdapters())
        earlier = reader.read(query)
        later = reader.read(replace(query, known_at=_START + timedelta(seconds=15)))
        assert next(r.trade.price for r in earlier.rows if r.trade.trade_id == "20") == Decimal(
            "100.2"
        )
        assert next(r.trade.price for r in later.rows if r.trade.trade_id == "20") == Decimal(
            "99.9"
        )
        assert later.duplicate_observations == 1
        assert next(r.ts_knowledge for r in later.rows if r.trade.trade_id == "19") == _START
        assert reader.read(query) == earlier

    def test_new_compatible_listing_needs_only_configuration(self, tmp_path: Path) -> None:
        """Onboard the authored ETH listing without modifying shared ingestion or source logic."""
        base = self._job()
        instrument = base.instruments[2]
        members = (instrument.instrument_id,)
        job = replace(
            base,
            universes=replace(base.universes, collection=members, research=members, strategy=()),
        )
        raw_path = tmp_path / "raw"
        raw_path.mkdir()
        clock = _Clock()
        reference = _OKX_REFERENCE.replace(b"BTC", b"ETH")
        trades = _OKX_TRADES.replace(b"BTC", b"ETH")
        state = PublicIngestion(SourceAdapters(), RawStore(raw_path)).resume(
            job,
            implementation_identity="a" * 64,
            path=tmp_path / "acquisition.json",
            transport=_Transport((reference, trades)),
            clock=clock.now,
            sleep=clock.sleep,
        )
        assert state.complete and len(state.receipts) == 2
        assert all(r.request.instrument == instrument for r in state.receipts)

    def test_rejected_response_stays_pending_and_cannot_be_refetched(self, tmp_path: Path) -> None:
        """Preserve invalid source bytes for diagnosis and refuse to replace them on retry."""
        raw_path = tmp_path / "raw"
        raw_path.mkdir()
        clock, job = _Clock(), self._job()
        ingestion = PublicIngestion(SourceAdapters(), RawStore(raw_path))
        path = tmp_path / "acquisition.json"
        with pytest.raises(ValueError, match="rejected request"):
            ingestion.resume(
                job,
                implementation_identity="a" * 64,
                path=path,
                transport=_Transport((b'{"code":"500","data":[]}',)),
                clock=clock.now,
                sleep=clock.sleep,
            )
        retained = DomainCodec().decode_json(path.read_bytes(), PublicAcquisition)
        assert (
            retained.pending is not None and retained.pending.payload == b'{"code":"500","data":[]}'
        )
        with pytest.raises(ValueError, match="rejected request"):
            ingestion.resume(
                job,
                implementation_identity="a" * 64,
                path=path,
                transport=_Transport(()),
                clock=clock.now,
                sleep=clock.sleep,
            )

    def test_scoped_book_cannot_inherit_collection_membership_for_research(
        self, tmp_path: Path
    ) -> None:
        """A valid captured book remains unavailable to an excluded research universe."""
        universes = replace(self._job().universes, research=())
        capture = _Books._capture(tmp_path / "capture", universes=universes)
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        raw = RawStore(tmp_path / "raw")
        identity = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (capture,), raw, tmp_path / "snapshots", max_records=16, max_bytes=1_000_000
        )
        selected = BookInput.read(capture, max_records=16)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        query = BookQuery(
            snapshot_id=identity,
            request_identity=selected.request.identity,
            instrument=self._job().instruments[0].instrument_id,
            start=epoch,
            end=epoch + timedelta(seconds=1),
            known_at=_RECEIVED,
            columns=("bids",),
            batch_size=10,
            max_bytes=1_000_000,
        )
        with pytest.raises(ValueError, match="research universe"):
            BookQueryReader.read(tmp_path / "snapshots", raw, readers=SourceAdapters(), query=query)

    @pytest.mark.integration
    def test_installed_commands_and_mixed_input_consumer(self, tmp_path: Path) -> None:
        """Run installed publication, discovery, cutoff reads and assembly outside the checkout."""
        self._acquire(tmp_path)
        capture = _Books._capture(tmp_path / "capture", universes=self._job().universes)
        script = tmp_path / "public_data.py"
        shutil.copyfile(Path("tests/integration/consumers/datasets/public_data.py"), script)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(script),
                "--acquisition",
                str(tmp_path / "acquisition.json"),
                "--raw",
                str(tmp_path / "raw"),
                "--output",
                str(tmp_path / "consumer"),
                "--books",
                str(capture),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert (tmp_path / "consumer/selection.json").is_file()
