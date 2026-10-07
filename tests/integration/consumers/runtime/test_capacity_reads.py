"""Verify retained read cutoffs, native parity and honest percentile reporting."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityWorkload
from capacity_reads import (
    CapacityReadObserver,
    _DashboardReader,
    _ResourceSampler,
    _RetainedBookIndex,
    _SourceIndex,
)
from capacity_results import CapacityResultsCollector
from msgspec.structs import replace
from paper_services import PaperServiceWorkload

# project library imports
from configuration import BookRegistryConfiguration, CaptureRunConfig, PaperServiceSource
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import (
    BookAsOfIndex,
    BookDepth,
    BookProjection,
    BookRegistry,
    CaptureReplay,
)
from market_data.collection import CaptureSegmentWriter
from market_data.contracts import CaptureRecord, CaptureRequest, CaptureRunRequest
from market_data.storage import CaptureJournal, CaptureRecording, CaptureRunJournal
from runtime import LiveBookDelivery, SharedBookDelivery
from serialization import DomainCodec
from telemetry import MonitoringEvent, MonitoringIdentity, TelemetryStore


class _Constant[T]:
    """Return one fixed value on every call, standing in for a zero-argument callable."""

    def __init__(self, value: T) -> None:
        """Bind the value to return."""
        self.value = value

    def __call__(self) -> T:
        """Return the bound value."""
        return self.value


class _DeliveryWriter:
    """Append retained deliveries and their durable index rows as the shared service does."""

    def __init__(self, reader: _RetainedBookIndex, source: _SourceIndex) -> None:
        """Create the source's index beside its delivery log."""
        self.reader, self.source = reader, source
        self.registry = BookRegistry(
            BookRegistryConfiguration(
                selections=(reader.selections[source.name],),
                equivalences=(),
                history_capacity=100,
            )
        )
        self.index = BookAsOfIndex.create(source.index.path)
        self.codec = DomainCodec()

    def append(self, delivery: SharedBookDelivery, *, indexed: bool = True) -> tuple[int, int]:
        """Durably append one delivery line and, unless deferred, its index row."""
        payload = self.codec.encode_json(delivery) + b"\n"
        with self.source.delivery_path.open("ab") as stream:
            offset = stream.seek(0, os.SEEK_END)
            stream.write(payload)
        if indexed:
            self.index_line(delivery, offset, len(payload))
        return offset, len(payload)

    def index_line(self, delivery: SharedBookDelivery, offset: int, length: int) -> None:
        """Accept the delivery's boundary and record the registry's carried market."""
        config = self.source.request.config
        self.registry.accept(
            BookDepth._touch_quote_validated(
                delivery.source.book,
                venue=config.venue,
                instrument_id=config.instrument_id,
                source_id=self.source.request.identity,
                channel=config.channel,
                available_ns=self.reader._unix_ns(delivery.source.available_at),
            )
        )
        latest = self.registry.latest(self.source.key)
        assert latest is not None
        self.index.append(*latest, offset=offset, length=length)


class _HeldUntilCommit:
    """Hold the readiness loop after its actual initial schema observation."""

    def __init__(self) -> None:
        """Start before the first attempt and before the commit."""
        self.first_attempt = threading.Event()
        self.committed = threading.Event()

    def __call__(self, _seconds: float) -> None:
        """Signal the first attempt, then wait for the schema commit."""
        self.first_attempt.set()
        assert self.committed.wait(2)


class _SchemaWait:
    """Capture the bounded actual reader result without losing thread errors."""

    def __init__(self, reader: _DashboardReader, output: Path) -> None:
        """Bind the reader and its readiness output with no outcome yet."""
        self._reader = reader
        self._output = output
        self.outcomes: list[dict[str, object]] = []
        self.failures: list[Exception] = []

    def __call__(self) -> None:
        """Wait for the schema and keep the result or failure."""
        try:
            self.outcomes.append(self._reader.wait_for_schema(self._output, time.monotonic() + 2))
        except Exception as error:
            self.failures.append(error)


class _CountedDiscovery:
    """Record each whole-host discovery."""

    def __init__(self, discover: Callable[[], object]) -> None:
        """Bind the original discovery with none recorded."""
        self._discover = discover
        self.discoveries: list[float] = []

    def __call__(self) -> dict[int, object]:
        """Record the discovery time and discover as before."""
        self.discoveries.append(time.monotonic())
        return cast(dict[int, object], self._discover())


class _NativeRead(Protocol):
    """The retained index's native read call shape."""

    def __call__(self, source_name: str, *, cutoff_ns: int) -> dict[str, object]:
        """Read one source's facts at the cutoff."""
        ...


class _DelayedFirstRead:
    """Drive a synthetic monotonic clock and delay only the first native read."""

    def __init__(self, read: _NativeRead, first_service_ns: int) -> None:
        """Start the synthetic clock at ten seconds with no reads."""
        self._read = read
        self._first_service_ns = first_service_ns
        self.now_ns = 10_000_000_000
        self.polls = 0

    def monotonic_ns(self) -> int:
        """Return the synthetic monotonic clock."""
        return self.now_ns

    def advance(self, seconds: float) -> None:
        """Advance the synthetic monotonic clock to the next arrival."""
        self.now_ns += round(seconds * 1_000_000_000)

    def read(self, source_name: str, *, cutoff_ns: int) -> dict[str, object]:
        """Delay only the first native read without changing its retained facts."""
        if self.polls == 0:
            self.now_ns += self._first_service_ns
        self.polls += 1
        return self._read(source_name, cutoff_ns=cutoff_ns)


class TestCapacityReads:
    """Keep reported boundaries attached to retained service facts."""

    @staticmethod
    def _skip_dashboard(
        _account_id: str, _mode: Literal["paper", "shadow"], _started: float, _stop: float
    ) -> None:
        """Keep a reader test independent of monitoring work."""

    @staticmethod
    def _fail_after_interval() -> None:
        """Exercise the callback failure after the measured boundary."""
        raise RuntimeError("postprocess diagnostic failure")

    @staticmethod
    def _blocked_depth(
        released: threading.Event,
        _index: _RetainedBookIndex,
        _name: str,
        _started: float,
        _stop: float,
    ) -> None:
        """Stand in for a query that never completes before the shared deadline."""
        released.wait(20)

    @staticmethod
    def _record_now(times: list[float]) -> None:
        """Record when the interval callback ran."""
        times.append(time.monotonic())

    @pytest.fixture(autouse=True)
    def _close_writers(self) -> Iterator[None]:
        """Release every index writer a test opened."""
        self.writers: list[_DeliveryWriter] = []
        yield
        for writer in self.writers:
            writer.index.close()

    def _index(self, tmp_path: Path) -> tuple[_RetainedBookIndex, _SourceIndex, datetime]:
        """Retain a real native OKX capture and its corresponding delivery stream."""
        workload = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-read-test"),
        )
        config = workload.service_configuration()
        source = config.sources[0]
        request = CaptureRequest(
            config=source.capture,
            recording_id=str(uuid4()),
            implementation_identity="a" * 64,
        )
        capture_root = tmp_path / "capture"
        journal = CaptureJournal(capture_root, request)
        journal.start()
        replay = CaptureReplay(source.capture, book_factory=BookAdapters.create)
        base = datetime(2026, 9, 27, 12, tzinfo=UTC)
        base_ns = int((base - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()) * 1_000_000_000
        records = (
            CaptureRecord(kind="session", epoch=0, received_ns=base_ns),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base_ns + 1_000_000,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            ),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base_ns + 2_000_000,
                raw=(
                    b'{"arg":{"channel":"books","instId":"BTC-USDT"},'
                    b'"action":"snapshot","data":[{"prevSeqId":-1,"seqId":10,'
                    b'"ts":"1790510400002","bids":[["99","4","0","1"]],'
                    b'"asks":[["100","4","0","1"]]}]}'
                ),
            ),
        )
        delivery_path = tmp_path / "delivery.jsonl"
        selected = _SourceIndex("btc-book", request, capture_root, delivery_path, 10_000)
        reader = _RetainedBookIndex(config, (selected,))
        self.writer = _DeliveryWriter(reader, selected)
        self.writers.append(self.writer)
        for position, record in enumerate(records):
            journal.append(record)
            outcome = replay.apply(record)
            row = BookProjection.capture(position, record, outcome, replay)
            self.writer.append(
                SharedBookDelivery(
                    source=LiveBookDelivery(
                        record=record,
                        book=row,
                        available_at=base + timedelta(milliseconds=position + 1),
                    ),
                    decisions=(),
                    matched=False,
                )
            )
        return reader, selected, base

    def test_as_of_depth_and_independent_native_parity(self, tmp_path: Path) -> None:
        """Exclude future delivery and prove the displayed touch against raw replay."""
        index, source, base = self._index(tmp_path)
        assert index.poll() == 3
        before = index.depth("btc-book", cutoff_ns=index._unix_ns(base))
        after = index.depth("btc-book", cutoff_ns=index._unix_ns(base + timedelta(milliseconds=4)))
        assert before["eligible"] is False
        assert before["partial_coverage"] is True
        assert after["eligible"] is True
        assert after["quote_position"] == 2
        assert (after["bid_levels"], after["ask_levels"]) == (1, 1)
        scanned = after["depth_index_scan_bytes"]
        assert type(scanned) is int and scanned > 0
        assert len(str(after["result_sha256"])) == 64
        assert index.replay_parity()["btc-book"]["matched_deliveries"] == 3
        capture_facts = CapacityResultsCollector(tmp_path, tmp_path)._capture_facts(
            source.capture_root, source.request
        )
        assert capture_facts["native_messages"] == 2
        assert capture_facts["durable_cursor_records"] == 3
        assert capture_facts["size_budget_status"] == "unmeasured"
        with source.delivery_path.open("ab") as stream:
            stream.write(b"{" + b"broken" + b"\n")
        with pytest.raises(ValueError):
            index.poll()

    def test_segment_chain_is_read_as_one_recording(self, tmp_path: Path) -> None:
        """Index, depth, replay parity, capture and delivery facts span every segment."""
        config = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-chain-test"),
        ).service_configuration()
        # The signed source selection carries the segment limits it declares.
        source = replace(
            config.sources[0], capture=replace(config.sources[0].capture, max_messages=1)
        )
        sources: tuple[PaperServiceSource, ...] = (source, *config.sources[1:])
        config = replace(config, sources=sources)
        base = datetime(2026, 9, 27, 12, tzinfo=UTC)
        base_ns = int((base - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()) * 1_000_000_000
        request = CaptureRunRequest(
            config=source.capture,
            window=CaptureRunConfig(
                start_at=base - timedelta(seconds=1),
                ready_by=base,
                stop_at=base + timedelta(minutes=1),
                max_messages=10,
                max_bytes=64 * 1024**2,
                max_segments=8,
                max_reconnects=0,
            ),
            run_id=str(uuid4()),
            implementation_identity="a" * 64,
        )
        service_root = tmp_path / "service"
        source_root = service_root / "runs" / "active" / source.name
        capture_root = source_root / request.run_id / request.run_id
        update = (
            b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"update","data":[{'
            b'"prevSeqId":10,"seqId":11,"ts":"1790510400003","bids":[["99","5","0","1"]],'
            b'"asks":[]}]}'
        )
        records = (
            CaptureRecord(kind="session", epoch=0, received_ns=base_ns),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base_ns + 1_000_000,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            ),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=base_ns + 2_000_000,
                raw=(
                    b'{"arg":{"channel":"books","instId":"BTC-USDT"},'
                    b'"action":"snapshot","data":[{"prevSeqId":-1,"seqId":10,'
                    b'"ts":"1790510400002","bids":[["99","4","0","1"]],'
                    b'"asks":[["100","4","0","1"]]}]}'
                ),
            ),
            CaptureRecord(kind="frame", epoch=0, received_ns=base_ns + 3_000_000, raw=update),
            CaptureRecord(
                kind="end", epoch=0, received_ns=base_ns + 4_000_000, reason="duration_limit"
            ),
        )
        run = CaptureRunJournal(capture_root, request)
        run.open(resume=False)
        try:
            chain = CaptureSegmentWriter(
                run, run.start_segment(None), previous_bytes=0, previous_records=0
            )
            for record in records:
                asyncio.run(chain.append(record))
            run.sealed(chain.current, chain.first_received_ns or 1)
            run.finish({"run_identity": request.identity})
        finally:
            run.close()
        recording = CaptureRecording.read(capture_root)
        assert recording.completed and len(recording.cursor().segments) == 3

        delivery_path = source_root / f"{request.run_id}-{config.accounts[0].account_id}.jsonl"
        selected = _SourceIndex(source.name, request, capture_root, delivery_path, 10_000)
        reader = _RetainedBookIndex(config, (selected,))
        writer = _DeliveryWriter(reader, selected)
        self.writers.append(writer)
        replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
        for position, record in enumerate(records):
            row = BookProjection.capture(position, record, replay.apply(record), replay)
            writer.append(
                SharedBookDelivery(
                    source=LiveBookDelivery(
                        record=record,
                        book=row,
                        available_at=base + timedelta(milliseconds=position + 1),
                    ),
                    decisions=(),
                    matched=False,
                )
            )
        assert reader.poll() == len(records)
        # Position 3 opens the third segment and moves the touch to the update.
        depth = reader.depth(
            source.name, cutoff_ns=reader._unix_ns(base + timedelta(milliseconds=4))
        )
        assert depth["eligible"] is True and depth["quote_position"] == 3
        assert recording.locate(3).ordinal == 2
        parity = reader.replay_parity()[source.name]
        assert parity["matched_deliveries"] == len(records)

        collector = CapacityResultsCollector(tmp_path, tmp_path)
        facts = collector._capture_facts(capture_root, request)
        assert facts["recording_id"] == request.run_id
        assert facts["completed_manifest"] is True and facts["stop_reason"] == "duration_limit"
        assert facts["durable_cursor_records"] == len(records)
        assert facts["native_messages"] == 3
        segments = cast(tuple[dict[str, object], ...], facts["capture_segments"])
        assert [segment["durable_cursor_records"] for segment in segments] == [2, 1, 2]
        delivered = collector._delivery_facts(delivery_path, capture_root, request)
        assert delivered["status"] == "pass_complete_native_stream"
        assert delivered["matched_deliveries"] == len(records)

        found = CapacityReadObserver._discover_source(source, source_root)
        assert (found.request, found.capture_root, found.delivery_path) == (
            request,
            capture_root,
            delivery_path,
        )

    def test_service_discovery_resolves_nested_capture_root(self, tmp_path: Path) -> None:
        """Find source/recording/recording/request and sibling account deliveries."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-discovery-test"),
        ).service_configuration()
        service_root = tmp_path / "service"
        service_root.mkdir()
        codec = DomainCodec()
        (service_root / "configuration.json").write_bytes(codec.encode_json(config))
        (service_root / "status.json").write_bytes(codec.encode_json({"run_id": "active"}))
        for source in config.sources:
            request = CaptureRequest(
                config=source.capture,
                recording_id=str(uuid4()),
                implementation_identity="a" * 64,
            )
            source_root = service_root / "runs" / "active" / source.name
            capture_root = source_root / request.recording_id / request.recording_id
            capture_root.mkdir(parents=True)
            (capture_root / "request.json").write_bytes(codec.encode_json(request))
            (source_root / f"{request.recording_id}-{config.accounts[0].account_id}.jsonl").touch()
        observer = CapacityReadObserver(
            tmp_path / "reads", service_root, process_pids=(1,), duration_seconds=1
        )
        discovered, index = observer._discover()
        assert discovered == config
        assert len(index.sources) == 4
        assert all(
            source.capture_root.parent.name == source.request.recording_key
            for source in index.sources.values()
        )

    def test_encoded_history_retains_every_complete_native_boundary(self, tmp_path: Path) -> None:
        """Keep control and full native facts exact while materializing only a causal selection."""
        index, source, base = self._index(tmp_path)
        original_lines = tuple(source.delivery_path.read_bytes().splitlines(keepends=True))
        assert index.poll() == 3
        retained = tuple(source.history)
        assert tuple(quote.position for quote, _, _ in retained) == (0, 1, 2)
        assert tuple(payload for _, payload, _ in retained) == original_lines
        assert tuple(count for _, _, count in retained) == tuple(map(len, original_lines))
        codec = DomainCodec()
        for quote, payload, count in retained:
            delivery = codec.decode_json(payload, SharedBookDelivery)
            assert delivery.source.book.position == quote.position
            assert delivery.source.available_at == base + timedelta(milliseconds=quote.position + 1)
            assert count == len(codec.encode_json(delivery)) + 1
        before = index.depth(source.name, cutoff_ns=index._unix_ns(base))
        selected = index.depth(
            source.name, cutoff_ns=index._unix_ns(base + timedelta(milliseconds=4))
        )
        assert before["quote_position"] is None and before["partial_coverage"] is True
        assert selected["quote_position"] == 2 and selected["partial_coverage"] is False
        assert (selected["bid_levels"], selected["ask_levels"]) == (1, 1)
        assert index.replay_parity()[source.name]["matched_deliveries"] == len(retained)

    @pytest.mark.parametrize(
        ("before", "after"),
        (
            (b'"size":"4"', b'"size":"NaN"'),
            (b'"matched":false', b'"matched":"false"'),
        ),
    )
    def test_index_decode_keeps_native_and_envelope_validation(
        self, tmp_path: Path, before: bytes, after: bytes
    ) -> None:
        """Narrow indexing still rejects malformed full depth and envelope fields."""
        index, source, _ = self._index(tmp_path)
        payload = source.delivery_path.read_bytes()
        assert before in payload
        source.delivery_path.write_bytes(payload.replace(before, after))
        with pytest.raises(ValueError):
            index.poll()

    def _next(
        self, delivery: SharedBookDelivery, position: int, base: datetime
    ) -> SharedBookDelivery:
        """Repeat the latest boundary at the next position and a later delivery clock."""
        return replace(
            delivery,
            source=replace(
                delivery.source,
                book=replace(delivery.source.book, position=position),
                available_at=base + timedelta(milliseconds=position + 2),
            ),
        )

    def test_read_covers_only_the_indexed_prefix_and_keeps_causal_cutoff(
        self, tmp_path: Path
    ) -> None:
        """A durable delivery whose index row is pending is partial coverage, not a new quote."""
        index, source, base = self._index(tmp_path)
        codec = DomainCodec()
        latest = codec.decode_json(
            source.delivery_path.read_bytes().splitlines()[-1], SharedBookDelivery
        )
        fourth = self._next(latest, 3, base)
        self.writer.append(fourth)
        required_end = source.delivery_path.stat().st_size
        result = index.read(source.name, cutoff_ns=index._unix_ns(base + timedelta(milliseconds=4)))
        assert result["quote_position"] == 2
        assert result["delivery_prefix_complete"] is True
        assert result["depth_index_required_prefix_bytes"] == required_end
        assert result["depth_index_indexed_prefix_bytes"] == required_end
        fifth = self._next(fourth, 4, base)
        pending = self.writer.append(fifth, indexed=False)
        cutoff = index._unix_ns(base + timedelta(milliseconds=7))
        lagging = index.read(source.name, cutoff_ns=cutoff)
        assert lagging["delivery_prefix_complete"] is False
        assert lagging["reason"] == "incomplete_retained_delivery_prefix"
        assert lagging["depth_index_indexed_prefix_bytes"] == required_end
        self.writer.index_line(fifth, *pending)
        caught_up = index.read(source.name, cutoff_ns=cutoff)
        assert caught_up["quote_position"] == 4
        assert caught_up["delivery_prefix_complete"] is True

    def test_incomplete_captured_prefix_is_explicit_partial_coverage(self, tmp_path: Path) -> None:
        """A half-written next boundary cannot pass as an eligible current read."""
        index, source, base = self._index(tmp_path)
        codec = DomainCodec()
        latest = codec.decode_json(
            source.delivery_path.read_bytes().splitlines()[-1], SharedBookDelivery
        )
        fourth = self._next(latest, 3, base)
        payload = codec.encode_json(fourth) + b"\n"
        offset = source.delivery_path.stat().st_size
        with source.delivery_path.open("ab") as stream:
            stream.write(payload[: len(payload) // 2])
        cutoff = index._unix_ns(base + timedelta(milliseconds=7))
        result = index.read(source.name, cutoff_ns=cutoff)
        assert result["delivery_prefix_complete"] is False
        assert result["partial_coverage"] is True
        assert result["eligible"] is False
        assert result["reason"] == "incomplete_retained_delivery_prefix"
        with source.delivery_path.open("ab") as stream:
            stream.write(payload[len(payload) // 2 :])
        assert index.read(source.name, cutoff_ns=cutoff)["delivery_prefix_complete"] is False
        self.writer.index_line(fourth, offset, len(payload))
        completed = index.read(source.name, cutoff_ns=cutoff)
        assert completed["delivery_prefix_complete"] is True
        assert completed["quote_position"] == 3
        assert completed["eligible"] is True

    def test_native_parity_reports_unattributed_durable_tail(self, tmp_path: Path) -> None:
        """A verified capture tail without delivery cannot count as complete parity."""
        index, source, _ = self._index(tmp_path)
        assert index.poll() == 3
        full = index.replay_parity()["btc-book"]
        assert full["status"] == "pass_available_cursor_prefix"
        retained = source.delivery_path.read_bytes().splitlines(keepends=True)
        source.delivery_path.write_bytes(b"".join(retained[:-1]))
        config = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-read-test"),
        ).service_configuration()
        fresh_source = _SourceIndex(
            source.name, source.request, source.capture_root, source.delivery_path, 10_000
        )
        fresh_index = _RetainedBookIndex(config, (fresh_source,))
        assert fresh_index.poll() == 2
        interrupted = fresh_index.replay_parity()[source.name]
        assert interrupted["undelivered_durable_raw_records"] == 1
        assert interrupted["status"] == "unmeasured_unattributed_delivery_tail"
        collector = CapacityResultsCollector(tmp_path, tmp_path)
        reduced = collector._delivery_facts(
            source.delivery_path, source.capture_root, source.request
        )
        assert reduced["matched_deliveries"] == 2
        assert reduced["unmatched_durable_raw_records"] == 1
        assert reduced["unmatched_raw_record_kinds"] == {"frame": 1}
        assert reduced["status"] == "unmeasured_unattributed_delivery_tail"

    def test_dashboard_query_uses_retained_events(self, tmp_path: Path) -> None:
        """Read one exact account fact through TelemetryStore and render its snapshot."""
        root = tmp_path / "service"
        journal = root / "monitoring" / "telemetry.sqlite3"
        journal.parent.mkdir(parents=True)
        now = datetime.now(UTC)
        event = MonitoringEvent(
            context=MonitoringIdentity(scope="account:shared", mode="paper"),
            name="risk.blocked",
            version="1",
            sample="sample-1",
            at=now - timedelta(seconds=2),
            available_at=now - timedelta(seconds=1),
            recorded_at=now,
            units="boolean",
            value=ExactRatio(numerator="0", denominator="1"),
        )
        assert TelemetryStore(journal).append((event,)) == 1
        output = tmp_path / "reads"
        output.mkdir()
        observer = CapacityReadObserver(output, root, process_pids=(1,), duration_seconds=1)
        started = time.monotonic()
        observer._dashboard_worker("shared", "paper", started, started + 0.01)
        lines = (output / "samples.jsonl").read_bytes().splitlines()
        assert len(lines) == 1
        sample = msgspec.json.decode(lines[0], type=dict[str, str | int | float | bool | None])
        assert sample["status"] == "ok"
        assert sample["event_count"] == 1
        returned = sample["returned_bytes"]
        assert type(returned) is int and returned > 0
        assert sample["scan_unavailable_reason"] == "telemetry_store_scan_bytes_not_exposed"
        assert hashlib.sha256(lines[0]).hexdigest() != sample["result_sha256"]
        assert sample["reader_id"] == sample["target"] == "shared"
        assert sample["request_index"] == sample["slot"] == 0
        due, began, completed = (
            sample["scheduled_monotonic_ns"],
            sample["started_monotonic_ns"],
            sample["completed_monotonic_ns"],
        )
        assert type(due) is int and type(began) is int and type(completed) is int
        assert due <= began <= completed
        assert sample["seconds"] == (completed - began) / 1_000_000_000

    def test_dashboard_startup_waits_for_committed_schema_before_warmup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An existing empty SQLite file stays unready until its schema transaction commits."""
        journal = tmp_path / "monitoring" / "telemetry.sqlite3"
        journal.parent.mkdir()
        sqlite3.connect(journal).close()
        output = tmp_path / "readiness"
        output.mkdir()
        reader = _DashboardReader.open(tmp_path, "shared", "paper")
        await_commit = _HeldUntilCommit()
        first_attempt, committed = await_commit.first_attempt, await_commit.committed
        wait_for_schema = _SchemaWait(reader, output)
        outcomes, failures = wait_for_schema.outcomes, wait_for_schema.failures
        monkeypatch.setattr(time, "sleep", await_commit)
        with closing(sqlite3.connect(journal)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            TelemetryStore._create(writer)
            worker = threading.Thread(target=wait_for_schema, daemon=True)
            worker.start()
            try:
                assert first_attempt.wait(2)
                with pytest.raises(sqlite3.OperationalError, match="no such table: metadata"):
                    reader.read(datetime.now(UTC))
                writer.commit()
            finally:
                committed.set()
            worker.join(2)
        assert not worker.is_alive() and not failures
        assert len(outcomes) == 1 and outcomes[0]["status"] == "ready"
        attempts = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in (output / "schema-readiness.jsonl").read_bytes().splitlines()
        ]
        assert [item["status"] for item in attempts] == ["schema_not_committed", "ready"]
        assert reader.read(datetime.now(UTC))["event_count"] == 0

    def test_dashboard_schema_readiness_respects_deadline_and_rejects_foreign_schema(
        self, tmp_path: Path
    ) -> None:
        """Startup waiting cannot become an indefinite or broad query retry loop."""
        journal = tmp_path / "monitoring" / "telemetry.sqlite3"
        journal.parent.mkdir()
        sqlite3.connect(journal).close()
        reader = _DashboardReader.open(tmp_path, "shared", "paper")
        output = tmp_path / "readiness"
        output.mkdir()
        began = time.monotonic()
        with pytest.raises(TimeoutError, match="within startup deadline"):
            reader.wait_for_schema(output, began + 0.04)
        assert time.monotonic() - began < 0.5
        with closing(sqlite3.connect(journal)) as writer:
            writer.execute("CREATE TABLE unrelated (value TEXT)")
            writer.commit()
        with pytest.raises(ValueError, match="nontelemetry schema"):
            reader.wait_for_schema(output, time.monotonic() + 1)

    def test_resource_sampler_caches_tree_but_reads_counters_and_disk_each_sample(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whole-host discovery cannot consume a one-second slot on every sample."""
        root, other = tmp_path / "root", tmp_path / "other"
        (root / "nested").mkdir(parents=True)
        other.mkdir()
        (root / "a.bin").write_bytes(b"a" * 5000)
        (root / "nested" / "b.bin").write_bytes(b"b" * 7)
        (other / "c.bin").write_bytes(b"c" * 11)
        (root / "linked").symlink_to(other, target_is_directory=True)
        sampler = _ResourceSampler(
            (os.getpid(),),
            (root, root / "nested", tmp_path / "absent"),
            tmp_path / "resources.jsonl",
            tmp_path / "phases.jsonl",
        )
        counted = _CountedDiscovery(sampler._discover)
        discoveries = counted.discoveries
        monkeypatch.setattr(sampler, "_discover", counted)
        sampler.sample(steady_started=time.monotonic())
        sampler.sample(steady_started=time.monotonic())
        assert len(discoveries) == 1
        assert len(sampler.rss_samples) == 2 and all(value > 0 for value in sampler.rss_samples)
        assert len(sampler.cpu_samples) == 1
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in (tmp_path / "resources.jsonl").read_bytes().splitlines()
        ]
        assert [row["logical_bytes"] for row in rows] == [5007, 5007]
        assert all(row["file_count"] == 2 for row in rows)
        (root / "nested" / "d.bin").write_bytes(b"d")
        sampler._tree = None
        sampler.sample(steady_started=time.monotonic())
        assert len(discoveries) == 2
        last = msgspec.json.decode(
            (tmp_path / "resources.jsonl").read_bytes().splitlines()[-1], type=dict[str, object]
        )
        assert last["logical_bytes"] == 5008
        phases = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in (tmp_path / "phases.jsonl").read_bytes().splitlines()
        ]
        ages = [phase["process_tree_age_seconds"] for phase in phases]
        assert ages[0] == ages[2] == 0.0 and isinstance(ages[1], float) and ages[1] > 0

    def test_insufficient_warm_sample_count_has_no_percentiles(self) -> None:
        """Refuse a p99 claim from a short startup or steady observation."""
        short = CapacityReadObserver._summary([0.01, 0.02], 1)
        assert short["success_count"] == 2
        assert "p99_seconds" not in short
        assert short["percentile_unavailable_reason"] == "fewer_than_1000_successful_steady_samples"
        qualified = CapacityReadObserver._summary([float(value) for value in range(1000)], 0)
        assert qualified["p50_seconds"] == 499.0
        assert qualified["p95_seconds"] == 949.0
        assert qualified["p99_seconds"] == 989.0

    @pytest.mark.parametrize("first_service_ns", (250_000_000, 1_000_000_001))
    def test_due_slots_recover_queue_and_exclude_late_completions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_service_ns: int
    ) -> None:
        """A late reader serves queued due requests and never counts work after the cutoff."""
        index, source, _ = self._index(tmp_path)
        assert index.poll() == 3
        output = tmp_path / "reads"
        output.mkdir()
        observer = CapacityReadObserver(output, tmp_path, process_pids=(1,), duration_seconds=1)
        clock = _DelayedFirstRead(index.read, first_service_ns)
        monkeypatch.setattr(time, "monotonic_ns", clock.monotonic_ns)
        monkeypatch.setattr(time, "sleep", clock.advance)
        monkeypatch.setattr(index, "read", clock.read)
        observer._depth_worker(index, source.name, 10.0, 11.0)
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in (output / "samples.jsonl").read_bytes().splitlines()
        ]
        assert [row["slot"] for row in rows] == list(range(5))
        assert [row["scheduled_monotonic_ns"] for row in rows] == [
            10_000_000_000 + slot * 200_000_000 for slot in range(5)
        ]
        if first_service_ns == 250_000_000:
            assert all(row["status"] == "ok" for row in rows)
            assert rows[1]["queue_delay_seconds"] == 0.05
            assert rows[1]["response_seconds"] == 0.05
            assert len(observer._samples["depth_bbo"]) == 5
            assert observer._failures["depth_bbo"] == 0
        else:
            assert rows[0]["status"] == "ok"
            assert rows[0]["completed_within_interval"] is False
            assert all(row["status"] == "missed" for row in rows[1:])
            assert all(row["started_monotonic_ns"] is None for row in rows[1:])
            assert observer._samples["depth_bbo"] == []
            assert observer._failures["depth_bbo"] == 5

    def test_full_interval_and_callback_failure_keep_steady_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A last 0.8-second slot cannot shorten the declared one-second interval."""
        index, _, _ = self._index(tmp_path)
        config = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-read-test"),
        ).service_configuration()
        output = tmp_path / "reads"
        journal = tmp_path / "monitoring" / "telemetry.sqlite3"
        journal.parent.mkdir()
        TelemetryStore(journal).append(())
        observer = CapacityReadObserver(
            output, tmp_path, process_pids=(os.getpid(),), duration_seconds=1
        )
        monkeypatch.setattr(observer, "_discover", _Constant((config, index)))
        monkeypatch.setattr(observer, "_dashboard_worker", self._skip_dashboard)
        with pytest.raises(RuntimeError, match="postprocess diagnostic failure"):
            observer.run(on_interval_complete=self._fail_after_interval)
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        elapsed = summary["steady_elapsed_seconds"]
        assert isinstance(elapsed, float) and elapsed >= 1.0
        assert summary["steady_duration_seconds"] == 1
        assert summary["postprocess_status"] == "fail"
        assert summary["native_replay_parity"] is None
        resources = cast(dict[str, object], summary["resources"])
        samples = resources["samples"]
        assert isinstance(samples, int) and samples >= 1
        assert resources["pid_roots"] == [os.getpid()]
        phases = (output / "resource-phases.jsonl").read_bytes().splitlines()
        assert len(phases) == samples
        phase = msgspec.json.decode(phases[0], type=dict[str, int | float])
        assert phase["sample_total_seconds"] >= phase["disk_scan_seconds"]
        failure = msgspec.json.decode((output / "failure.json").read_bytes(), type=dict[str, str])
        assert failure["phase"] == "interval_complete_callback"

    def test_stuck_reader_uses_one_join_deadline_after_shutdown_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blocked query cannot multiply the five-second post-interval bound."""
        index, _, _ = self._index(tmp_path)
        config = PaperServiceWorkload(
            "okx",
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-read-test"),
        ).service_configuration()
        output = tmp_path / "reads"
        journal = tmp_path / "monitoring" / "telemetry.sqlite3"
        journal.parent.mkdir()
        TelemetryStore(journal).append(())
        observer = CapacityReadObserver(
            output, tmp_path, process_pids=(os.getpid(),), duration_seconds=1
        )
        monkeypatch.setattr(observer, "_discover", _Constant((config, index)))
        released = threading.Event()
        callback_at: list[float] = []
        monkeypatch.setattr(observer, "_depth_worker", partial(self._blocked_depth, released))
        monkeypatch.setattr(observer, "_dashboard_worker", self._skip_dashboard)
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError, match="did not stop"):
                observer.run(on_interval_complete=partial(self._record_now, callback_at))
        finally:
            released.set()
        assert callback_at and callback_at[0] - started >= 1.0
        assert time.monotonic() - started < 9.0
        failure = msgspec.json.decode((output / "failure.json").read_bytes(), type=dict[str, str])
        assert failure["phase"] == "read_worker_join"
