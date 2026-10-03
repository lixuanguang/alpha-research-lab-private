"""Verify bounded health policy, alert failure and independent installed supervision."""

# standard library imports
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from market_data.adapters.wire import Wire
from runtime import ProcessSupervisor
from serialization import DomainCodec
from telemetry import (
    HealthAlert,
    HealthMetric,
    HealthMetrics,
    HealthPolicy,
    HealthRecorder,
    HealthSignals,
    MonitoringQuery,
    TelemetryStore,
)

_ROOT = Path(__file__).parents[4]


class AdvancingWorkload:
    """Advance real watchdog clocks long enough for a periodic observation."""

    def __call__(self, root: Path, health: HealthMetrics) -> None:
        """Keep source, disk and process clocks separate during a bounded child run."""
        for _ in range(15):
            now = time.monotonic_ns()
            for metric in (
                HealthMetric.HEARTBEAT,
                HealthMetric.INGESTION,
                HealthMetric.PERSISTENCE,
                HealthMetric.MARKET,
            ):
                health.set(metric, now)
            time.sleep(0.1)


class LostWorkload:
    """Exit a child without a final event to exercise independent protection."""

    def __call__(self, root: Path, health: HealthMetrics) -> None:
        """Terminate before any capture health or telemetry can claim success."""
        os._exit(17)


class AdvancingLostWorkload:
    """Produce a live monitor sample, then lose the child before normal completion."""

    def __call__(self, root: Path, health: HealthMetrics) -> None:
        """Keep source and process clocks current until a periodic offer occurs."""
        for _ in range(18):
            now = time.monotonic_ns()
            for metric in (
                HealthMetric.HEARTBEAT,
                HealthMetric.INGESTION,
                HealthMetric.PERSISTENCE,
                HealthMetric.MARKET,
            ):
                health.set(metric, now)
            time.sleep(0.1)
        os._exit(17)


class StalledAppend:
    """Hold the monitoring disk writer while the supervisor remains responsive."""

    def __init__(self) -> None:
        """Bind test-only synchronization for one stalled store call."""
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, events: object) -> int:
        """Simulate storage stalled after a periodic snapshot was offered."""
        self.entered.set()
        self.release.wait(10)
        return 0


class DurableStopRecorder:
    """Retain one parent-owned hard response independently of monitoring storage."""

    def __init__(self, path: Path) -> None:
        """Bind a local observed stop marker."""
        self.path = path

    def __call__(self, reason: str) -> None:
        """Persist the supervised stop reason before alert or telemetry emission."""
        self.path.write_text(reason, encoding="utf-8")


class TestHealth:
    """Protect elapsed progress and failure thresholds without transport dependencies."""

    @staticmethod
    def policy() -> HealthPolicy:
        """Use distinct clock budgets to expose heartbeat and economic-progress confusion.

        Returns:
            Validated test policy with a deliberately unavailable local alert address.
        """
        return HealthPolicy(
            heartbeat_seconds=1,
            progress_seconds=2,
            freshness_seconds=3,
            max_queue=4,
            max_reconnects=1,
            max_invalid=0,
            alert_socket="/private/tmp/alpha-missing-test-syslog.sock",
        )

    def test_codec_and_threshold_boundaries(self) -> None:
        """Keep exact boundaries inclusive and fail clocks/counts independently."""
        policy, codec = self.policy(), DomainCodec()
        assert codec.decode_json(codec.encode_json(policy), HealthPolicy) == policy
        now = 10_000_000_000
        limits = (
            (HealthMetric.HEARTBEAT, 1_000_000_000, "heartbeat_stalled"),
            (HealthMetric.INGESTION, 2_000_000_000, "ingestion_stalled"),
            (HealthMetric.PERSISTENCE, 2_000_000_000, "persistence_stalled"),
            (HealthMetric.MARKET, 3_000_000_000, "market_stalled"),
        )
        for metric, age, expected in limits:
            values = [now] * 4 + [0] * 5
            values[metric] = now - age
            assert policy.reason(tuple(values), now_ns=now) == ""
            assert policy.reason(tuple(values), now_ns=now + 1) == expected
        for metric, limit, expected in (
            (HealthMetric.QUEUE, 4, "queue_limit"),
            (HealthMetric.RECONNECTS, 1, "reconnects_limit"),
            (HealthMetric.INVALID, 0, "invalid_limit"),
        ):
            values = [now] * 4 + [0] * 5
            values[metric] = limit
            assert policy.reason(tuple(values), now_ns=now) == ""
            values[metric] += 1
            assert policy.reason(tuple(values), now_ns=now) == expected
        values = [0] * 9
        values[HealthMetric.PERSISTENCE_FAILED] = 1
        assert policy.reason(tuple(values), now_ns=now) == "persistence_failed"

    @pytest.mark.parametrize(
        "encoded",
        [
            b'{"unknown":1}',
            b'{"heartbeat_seconds":true}',
            b'{"heartbeat_seconds":0}',
            b'{"max_reconnects":6}',
            b'{"max_invalid":-1}',
            b'{"alert_socket":"relative.sock"}',
            b'{"response":"restart"}',
        ],
    )
    def test_invalid_policy(self, encoded: bytes) -> None:
        """Reject malformed configuration before starting a collector or sending alerts."""
        codec = DomainCodec()
        original = codec.encode_json(self.policy()).decode()
        override = encoded.decode()[1:-1]
        # Replacing fields through the strict codec also rejects duplicate or unknown keys.
        with pytest.raises(ValueError):
            codec.decode_json((original[:-1] + "," + override + "}").encode(), HealthPolicy)
        with pytest.raises(ValueError, match="threshold"):
            replace(self.policy(), progress_seconds=0)
        with pytest.raises(ValueError, match="syslog"):
            replace(self.policy(), alert_socket="/" + "x" * 101)

    def test_finalization_does_not_require_new_market_input(self) -> None:
        """Finalization has a parent deadline while heartbeat loss remains observable."""
        policy = self.policy()
        values = [10_000_000_000, 0, 0, 0, 0, 0, 0, 1, 0]
        assert policy.reason(tuple(values), now_ns=10_000_000_000) == ""
        assert policy.reason(tuple(values), now_ns=11_000_000_001) == "heartbeat_stalled"

    def test_startup_is_bounded_separately(self) -> None:
        """Slow interpreter initialization gets no unlimited liveness exemption."""
        policy = self.policy()
        values = (0, 1, 1, 1, 0, 0, 0, 0, 0)
        assert policy.reason(values, now_ns=10_000_000_001) == ""
        assert policy.reason(values, now_ns=10_000_000_002) == "startup_stalled"

    def test_input_stall_can_expire_before_its_last_append(self) -> None:
        """Observe receipt expiry before later persistence expiry, then apply precedence."""
        policy = self.policy()
        values = (3_000_000_000, 1_000_000_000, 1_250_000_000, 3_000_000_000, 0, 0, 0, 0, 0)
        assert policy.reason(values, now_ns=3_000_000_001) == "ingestion_stalled"
        assert policy.reason(values, now_ns=3_250_000_001) == "persistence_stalled"

    def test_shared_observation(self) -> None:
        """Keep advancing heartbeat independent of persistence and economic clocks."""
        health = HealthMetrics()
        before = health.snapshot()
        health.set(HealthMetric.HEARTBEAT, before[0] + 1)
        health.set(HealthMetric.QUEUE, 3)
        assert health.snapshot() == (before[0] + 1, *before[1:4], 3, *before[5:])

    def test_retained_health_distinguishes_heartbeat_from_progress(self) -> None:
        """An advancing heartbeat cannot manufacture source or disk freshness."""
        initial = (
            0,
            1_000_000_000,
            1_000_000_000,
            1_000_000_000,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        final = (
            3_000_000_000,
            1_000_000_000,
            1_000_000_000,
            1_000_000_000,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        events = HealthSignals.project(
            scope="capture:fixture",
            release="a" * 64,
            sample="one",
            observed_at=datetime(2026, 9, 26, tzinfo=UTC),
            observed_monotonic_ns=4_000_000_000,
            initial=initial,
            final=final,
            stop_reason="completed",
            alert_delivered=False,
        )
        by_name = {event.name: event for event in events}
        assert by_name["runtime.heartbeat_age_seconds"].value is not None
        assert by_name["data.persistence_age_seconds"].value is None
        assert by_name["data.persistence_age_seconds"].missing_reason == "no_persistence_progress"
        assert by_name["runtime.stopped"].value is not None
        assert by_name["runtime.stopped"].value.numerator == "1"
        assert by_name["runtime.faulted"].value is not None
        assert by_name["runtime.faulted"].value.numerator == "0"

    def test_supervisor_retains_progress_while_child_is_running(self, tmp_path: Path) -> None:
        """A retained time series includes a live sample before terminal completion."""
        root = tmp_path / "capture"
        root.mkdir()
        result = ProcessSupervisor.run(
            root,
            self.policy(),
            AdvancingWorkload(),
            duration_seconds=2,
            label="progress",
            implementation_identity="a" * 64,
        )
        assert result["stop_reason"] == "completed"
        assert result["telemetry_failures"] == 0
        end = datetime.now(UTC) + timedelta(seconds=1)
        events = TelemetryStore(root / "monitor.sqlite3").query(
            MonitoringQuery(
                scope="capture:capture",
                mode="data",
                start=end - timedelta(minutes=1),
                end=end,
                as_of=end,
            )
        )
        samples = {
            event.sample for event in events if event.name == "runtime.heartbeat_age_seconds"
        }
        assert len(samples) >= 2

    def test_monitoring_loss_cannot_disable_supervisor_protection(self, tmp_path: Path) -> None:
        """A bad telemetry path leaves the parent stop and failure evidence intact."""
        root = tmp_path / "capture"
        root.mkdir()
        (root / "monitor.sqlite3").mkdir()
        stop = tmp_path / "stopped.txt"
        result = ProcessSupervisor.run(
            root,
            self.policy(),
            LostWorkload(),
            duration_seconds=1,
            label="loss",
            implementation_identity="a" * 64,
            protect=DurableStopRecorder(stop),
        )
        assert result["stop_reason"] == "collector_lost"
        assert result["protection_applied"] is True
        assert result["telemetry_failures"] == 1
        assert result["telemetry_dropped"] == 20
        assert stop.read_text(encoding="utf-8") == "collector_lost"

    def test_stalled_monitoring_writer_does_not_delay_protection(self, tmp_path: Path) -> None:
        """A blocked telemetry fsync cannot hold the watchdog control path."""
        root = tmp_path / "capture"
        root.mkdir()
        stop = tmp_path / "stopped.txt"
        stalled = StalledAppend()
        started = time.monotonic()
        try:
            with patch.object(TelemetryStore, "append", stalled):
                result = ProcessSupervisor.run(
                    root,
                    self.policy(),
                    AdvancingLostWorkload(),
                    duration_seconds=2,
                    label="stalled-monitoring",
                    implementation_identity="a" * 64,
                    protect=DurableStopRecorder(stop),
                )
            assert stalled.entered.is_set()
            assert result["stop_reason"] == "collector_lost"
            assert result["protection_applied"] is True
            assert stop.read_text(encoding="utf-8") == "collector_lost"
            assert isinstance(result["telemetry_pending"], int)
            assert result["telemetry_pending"] > 0
            assert result["telemetry_worker_alive"] is True
            assert time.monotonic() - started < 5
        finally:
            stalled.release.set()

    def test_monitoring_worker_start_failure_does_not_disable_protection(
        self, tmp_path: Path
    ) -> None:
        """A missing monitor worker cannot prevent the already-started child stop."""
        root = tmp_path / "capture"
        root.mkdir()
        stop = tmp_path / "stopped.txt"
        with patch.object(HealthRecorder, "start", side_effect=OSError("unavailable")):
            result = ProcessSupervisor.run(
                root,
                self.policy(),
                LostWorkload(),
                duration_seconds=1,
                label="worker-unavailable",
                implementation_identity="a" * 64,
                protect=DurableStopRecorder(stop),
            )
        assert result["protection_applied"] is True
        assert result["telemetry_failures"] == 1
        assert result["telemetry_error"] == "OSError"
        assert stop.read_text(encoding="utf-8") == "collector_lost"

    def test_full_alert_socket_never_blocks(self, socket_directory: Path) -> None:
        """Verify real delivery and deterministic kernel backpressure on nonblocking sockets."""
        address = str(socket_directory / "a.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(address)
            receiver.settimeout(2)
            assert HealthAlert.deliver(address, "market_stalled")
            assert b"market_stalled" in receiver.recv(1024)
            started = time.monotonic()
            with patch.object(socket.socket, "send", self._backpressured_send):
                assert not HealthAlert.deliver(address, "market_stalled")
            assert time.monotonic() - started < 2
        assert not HealthAlert.deliver(address, "collector_lost")

    @staticmethod
    def _backpressured_send(connection: socket.socket, payload: bytes) -> int:
        """Require nonblocking mode on the actual initial and reconnected sockets."""
        assert not connection.getblocking()
        assert b"market_stalled" in payload
        raise BlockingIOError("synthetic full Unix datagram queue")

    def test_installed_health_consumer(self, tmp_path: Path) -> None:
        """Exercise real process loss and failure responses through the installed package."""
        script = tmp_path / "health_consumer.py"
        shutil.copyfile(_ROOT / "tests/integration/consumers/capture/health_consumer.py", script)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(script),
                str(_ROOT / "configs/live/bitfinex-btc-usd.json"),
                str(tmp_path / "runs"),
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            pytest.fail(result.stdout + result.stderr, pytrace=False)
        report = Wire.mapping(Wire.decode(result.stdout.encode()))
        package = report["package"]
        assert isinstance(package, str) and "/site-packages/" in package
        assert isinstance(report["observations"], list)
        assert len(report["observations"]) == 10
        run_root = next((tmp_path / "runs/healthy").iterdir())
        summary = Wire.mapping(Wire.decode((run_root / "health-summary.json").read_bytes()))
        assert summary["stop_reason"] == "completed"
        assert isinstance(summary["telemetry_events"], int)
        assert summary["telemetry_events"] >= 19
        end = datetime.now(UTC) + timedelta(seconds=1)
        events = TelemetryStore(run_root / "monitor.sqlite3").query(
            MonitoringQuery(
                scope=f"capture:{run_root.name}",
                mode="data",
                start=end - timedelta(minutes=5),
                end=end,
                as_of=end,
            )
        )
        assert {event.name for event in events} >= {
            "runtime.heartbeat_age_seconds",
            "data.persistence_age_seconds",
            "data.source_clock_drift_seconds",
            "runtime.alert_delivery_failure",
        }

    @pytest.fixture()
    def socket_directory(self) -> Iterator[Path]:
        """Hold Unix sockets under a short path: AF_UNIX paths are limited to about 104 bytes."""
        with tempfile.TemporaryDirectory(prefix="sock-", dir="/tmp") as directory:
            yield Path(directory)
