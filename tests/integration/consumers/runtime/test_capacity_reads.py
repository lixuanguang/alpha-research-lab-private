"""Verify retained read cutoffs, native parity and honest percentile reporting."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityWorkload
from capacity_reads import CapacityReadObserver, _RetainedBookIndex, _SourceIndex
from capacity_results import CapacityResultsCollector
from paper_services import PaperServiceWorkload

# project library imports
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal
from runtime import LiveBookDelivery, SharedBookDelivery
from serialization import DomainCodec
from telemetry import MonitoringEvent, MonitoringIdentity, TelemetryStore


class TestCapacityReads:
    """Keep reported boundaries attached to retained service facts."""

    @staticmethod
    def _index(tmp_path: Path) -> tuple[_RetainedBookIndex, _SourceIndex, datetime]:
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
        codec = DomainCodec()
        with delivery_path.open("wb") as stream:
            for position, record in enumerate(records):
                journal.append(record)
                outcome = replay.apply(record)
                row = BookProjection.capture(position, record, outcome, replay)
                delivery = SharedBookDelivery(
                    source=LiveBookDelivery(
                        record=record,
                        book=row,
                        available_at=base + timedelta(milliseconds=position + 1),
                    ),
                    inputs=(),
                    coordinated_at=None,
                )
                stream.write(codec.encode_json(delivery) + b"\n")
        selected = _SourceIndex("btc-book", request, capture_root, delivery_path, 10_000)
        return _RetainedBookIndex(config, (selected,)), selected, base

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
            source.capture_root.parent.name == source.request.recording_id
            for source in index.sources.values()
        )

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
        sample = msgspec.json.decode(lines[0], type=dict[str, str | int | float | None])
        assert sample["status"] == "ok"
        assert sample["event_count"] == 1
        returned = sample["returned_bytes"]
        assert type(returned) is int and returned > 0
        assert sample["scan_unavailable_reason"] == "telemetry_store_scan_bytes_not_exposed"
        assert hashlib.sha256(lines[0]).hexdigest() != sample["result_sha256"]

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
        observer = CapacityReadObserver(
            output, tmp_path, process_pids=(os.getpid(),), duration_seconds=1
        )
        monkeypatch.setattr(observer, "_discover", lambda: (config, index))

        def skip_dashboard(
            _account_id: str, _mode: Literal["paper", "shadow"], _started: float, _stop: float
        ) -> None:
            """Keep the temporal regression independent of a monitoring store."""

        monkeypatch.setattr(observer, "_dashboard_worker", skip_dashboard)

        def fail_after_interval() -> None:
            """Exercise the callback failure after the measured boundary."""
            raise RuntimeError("postprocess diagnostic failure")

        with pytest.raises(RuntimeError, match="postprocess diagnostic failure"):
            observer.run(on_interval_complete=fail_after_interval)
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
        observer = CapacityReadObserver(
            output, tmp_path, process_pids=(os.getpid(),), duration_seconds=1
        )
        monkeypatch.setattr(observer, "_discover", lambda: (config, index))
        released = threading.Event()
        callback_at: list[float] = []

        def blocked_depth(
            _index: _RetainedBookIndex, _name: str, _started: float, _stop: float
        ) -> None:
            """Stand in for a query that never completes before the shared deadline."""
            released.wait(20)

        def skip_dashboard(
            _account_id: str, _mode: Literal["paper", "shadow"], _started: float, _stop: float
        ) -> None:
            """Keep the bound independent of monitoring work."""

        monkeypatch.setattr(observer, "_depth_worker", blocked_depth)
        monkeypatch.setattr(observer, "_dashboard_worker", skip_dashboard)
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError, match="did not stop"):
                observer.run(on_interval_complete=lambda: callback_at.append(time.monotonic()))
        finally:
            released.set()
        assert callback_at and callback_at[0] - started >= 1.0
        assert time.monotonic() - started < 9.0
        failure = msgspec.json.decode((output / "failure.json").read_bytes(), type=dict[str, str])
        assert failure["phase"] == "read_worker_join"
