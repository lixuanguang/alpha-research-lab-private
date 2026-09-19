"""Exercise independent supervision with synthetic feeds and real local syslog delivery."""

from __future__ import annotations

# standard library imports
import asyncio
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
from msgspec.structs import replace

# project library imports
import market_data
from applications.collect import supervise
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueTransport
from market_data.contracts import FeedSocket
from market_data.replay import SavedCapture
from telemetry import HealthPolicy

_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD","prec":"R0","freq":"F0","len":"25"}',
    b"[7,[[1,100,2],[2,101,-1]],1]",
)


class HealthSocket:
    """Inject one named failure after a real reconstructed and persisted snapshot."""

    def __init__(self, mode: str, output: Path) -> None:
        """Bind a finite fault exercise.

        Args:
            mode: Named synthetic failure; no external source is used.
            output: Supervisor output used to locate this child's journal.
        """
        self.mode, self.output, self.index = mode, output, 0

    async def send(self, message: str) -> None:
        """Accept the pipeline's real subscription messages.

        Args:
            message: Non-secret native subscription text.
        """

    async def recv(self) -> bytes:
        """Return exact R0 input or inject one bounded failure.

        Returns:
            Snapshot or advancing heartbeat sequence bytes.

        Raises:
            OSError: A configured disconnect requires recovery.
        """
        if self.mode != "queue":
            await asyncio.sleep(0.02)
        self.index += 1
        if self.index <= len(_FRAMES):
            return _FRAMES[self.index - 1]
        if self.mode == "death":
            os.kill(os.getpid(), signal.SIGKILL)
        if self.mode == "blocked":
            time.sleep(10)
        if self.mode == "ingestion":
            await asyncio.Event().wait()
        if self.mode == "disk":
            for path in self.output.rglob("journal.jsonl"):
                path.chmod(0o400)
        if self.mode == "invalid":
            return b"[7,[1,0,2],2]"
        if self.mode == "reconnect":
            raise OSError("synthetic disconnect")
        return f'[7,"hb",{self.index - 2}]'.encode()

    async def close(self) -> None:
        """Close the local synthetic feed without further input."""


class HealthTransport(VenueTransport):
    """Keep failure injection entirely at the collector's existing transport boundary."""

    def __init__(self, config: CaptureConfig, mode: str, output: Path) -> None:
        """Bind the actual source config and one child-local exercise.

        Args:
            config: Maintained source identity with synthetic resource limits.
            mode: Named deterministic failure or healthy completion.
            output: Parent path for this test's actual committed journals.
        """
        self.config = config
        self.mode, self.output = mode, output

    async def open(self, timeout: float) -> FeedSocket:
        """Supply a new synthetic connection for each real recovery attempt.

        Args:
            timeout: The collector's remaining connection budget.

        Returns:
            Native R0 fixture stream, with the requested failure.
        """
        return HealthSocket(self.mode, self.output)


def main() -> None:
    """Verify completion, protection, interrupted prefixes and local delivery outside Git."""
    config_path, output = Path(sys.argv[1]), Path(sys.argv[2])
    output.mkdir()
    observations: list[dict[str, object]] = []
    with (
        TemporaryDirectory(prefix="health-alert-", dir="/tmp") as socket_root,
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver,
    ):
        address = str(Path(socket_root) / "alerts.sock")
        receiver.bind(address)
        receiver.settimeout(2)
        for mode, expected in (
            ("healthy", "completed"),
            ("market", "market_stalled"),
            ("ingestion", "persistence_stalled"),
            ("blocked", "heartbeat_stalled"),
            ("death", "collector_lost"),
            ("disk", "persistence_failed"),
            ("invalid", "invalid_limit"),
            ("reconnect", "reconnects_limit"),
            ("queue", "queue_limit"),
            ("alert_failure", "market_stalled"),
        ):
            destination = output / mode
            config = replace(
                CaptureConfig.read(config_path),
                duration_seconds=10,
                max_messages=3 if mode == "healthy" else 1000,
                queue_capacity=32,
                retries=2,
            )
            policy = HealthPolicy(
                startup_seconds=60,
                heartbeat_seconds=1 if mode == "blocked" else 5,
                progress_seconds=1 if mode == "ingestion" else 5,
                freshness_seconds=1 if mode in ("market", "alert_failure") else 10,
                max_queue=1 if mode == "queue" else 31,
                max_reconnects=0 if mode == "reconnect" else 2,
                max_invalid=10 if mode == "reconnect" else 0,
                alert_socket=address
                if mode != "alert_failure"
                else str(Path(socket_root) / "missing.sock"),
            )
            result = supervise(
                config,
                destination,
                policy,
                transport=HealthTransport(config, mode, destination),
            )
            expected_reasons = (
                ("ingestion_stalled", "persistence_stalled") if mode == "ingestion" else (expected,)
            )
            actual_reason = result["stop_reason"]
            assert isinstance(actual_reason, str) and actual_reason in expected_reasons, (
                f"{mode}: expected {expected_reasons}, observed {actual_reason}; {result}"
            )
            assert result["collector_stopped"] is True, result
            assert result["alert_delivered"] is (mode not in ("healthy", "alert_failure")), result
            if result["alert_delivered"]:
                assert actual_reason.encode() in receiver.recv(1024)
            journals = list(destination.rglob("journal.jsonl"))
            assert len(journals) == 1
            completed = (journals[0].parent / "manifest.json").exists()
            replay = SavedCapture.read(
                journals[0].parent, book_factory=BookAdapters.create, completed=completed
            )
            if mode == "healthy":
                assert replay.book.ready and not replay.gaps
            elif not completed:
                assert replay.invalid
                assert replay.gaps[-1]["reason"] == "interrupted_persistence_unknown_tail"
            observation: dict[str, object] = {
                "scenario": mode,
                **result,
                "committed_frames": replay.frames,
            }
            observations.append(observation)
    evidence: dict[str, object] = {"package": market_data.__file__, "observations": observations}
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
