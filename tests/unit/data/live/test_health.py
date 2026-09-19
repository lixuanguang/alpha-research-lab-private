"""Verify bounded health policy, alert failure and independent installed supervision."""

# standard library imports
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from market_data.adapters.wire import Wire
from serialization import DomainCodec
from telemetry import HealthAlert, HealthMetric, HealthMetrics, HealthPolicy

_ROOT = Path(__file__).parents[4]


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

    def test_full_alert_socket_never_blocks(self, tmp_path: Path) -> None:
        """Verify real delivery and deterministic kernel backpressure on nonblocking sockets."""
        address = str(tmp_path / "a.sock")
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
        summary = Wire.mapping(
            Wire.decode(
                (next((tmp_path / "runs/healthy").iterdir()) / "health-summary.json").read_bytes()
            )
        )
        assert summary["stop_reason"] == "completed"
