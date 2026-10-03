"""Exercise installed session recovery with synthetic wire input and real durable storage."""

from __future__ import annotations

# standard library imports
import asyncio
import base64
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import patch

# third party library imports
from msgspec.structs import replace

# project library imports
import market_data
from applications.collect import collect
from configuration import CaptureConfig, SecretValue
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueTransport
from market_data.adapters.venues.coinbase import CoinbaseBook, CoinbaseCredentials
from market_data.books import CaptureReplay
from market_data.contracts import CaptureRecord, CaptureRequest, FeedSocket
from market_data.replay import SavedCapture
from market_data.storage import CaptureJournal
from serialization import DomainCodec

_ACK = b'{"type":"subscriptions","channels":[{"name":"level3","product_ids":["BTC-USD"]}]}'


class RecoveryScenarios:
    """Drive the recovery and duplicate-and-stale capture scenarios."""

    @staticmethod
    def recovery(directory: Path, output: Path, mode: str) -> dict[str, object]:
        """Run one bounded recovery scenario with original clocks and raw lineage.

        Args:
            directory: Copied synthetic configs and source payloads.
            output: New local recording parent.
            mode: Late snapshot, bridge discontinuity or rate-limit failure.

        Returns:
            Compact observed recovery counts and clock evidence.
        """
        config = replace(
            CaptureConfig.read(directory / "coinbase-btc-usd.json"), retries=2, max_messages=100
        )
        transport = _Transport(config, directory, mode)

        class ObservedReplay(CaptureReplay):
            """Release the REST fixture only after the intended durable consumer boundary."""

            def apply(self, record: CaptureRecord) -> str:
                """Observe persisted input without changing decoder behavior.

                Args:
                    record: Durable message or control transition.

                Returns:
                    Actual decoder classification.
                """
                outcome = super().apply(record)
                if record.kind == "gap" or outcome == "buffered":
                    transport.release.set()
                return outcome

        with (
            patch("market_data.collection.runner.CaptureReplay", ObservedReplay),
            patch("market_data.collection.runner.asyncio.sleep", transport.pause),
        ):
            result = asyncio.run(
                collect(
                    config,
                    output,
                    implementation_identity="a" * 64,
                    credentials=CoinbaseCredentials(
                        SecretValue("fixture"),
                        SecretValue(base64.b64encode(b"fixture-secret").decode()),
                        SecretValue("fixture-passphrase"),
                    ),
                    transport=transport,
                )
            )
        assert len(transport.sockets) == transport.requests == 3
        assert transport.delays == [1.0, 2.0]
        assert all(socket.closed and len(socket.sent) == 1 for socket in transport.sockets)
        assert result["synchronized"] is False and result["retry_exhausted"] is True
        assert result["replay_parity"] is True and result["gaps"]
        root = next(output.iterdir())
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        records = list(CaptureJournal(root, request).records())
        snapshots = [record for record in records if record.kind == "snapshot"]
        if mode == "late":
            assert len(snapshots) == 3
            for record in snapshots:
                gap = next(r for r in records if r.kind == "gap" and r.epoch == record.epoch)
                assert record.received_ns > gap.received_ns
                assert records.index(gap) < records.index(record)
            assert result["snapshots"] == 0
        elif mode == "bridge_gap":
            assert len(snapshots) == 3 and result["snapshots"] == 0
        else:
            assert not snapshots
            assert sum(r.reason == "snapshot_failed_unknown_loss" for r in records) >= 3
        return {
            "scenario": mode,
            "connections": len(transport.sockets),
            "snapshot_requests": transport.requests,
            "backoff_seconds": transport.delays,
            "retained_snapshots": len(snapshots),
            "retry_exhausted": result["retry_exhausted"],
            "synchronized": result["synchronized"],
            "replay_parity": result["replay_parity"],
            "later_receipt_preserved": mode == "late",
            "gap_then_snapshot_receipt_ns": [
                [
                    next(
                        r.received_ns
                        for r in records
                        if r.kind == "gap" and r.epoch == record.epoch
                    ),
                    record.received_ns,
                ]
                for record in snapshots
                if mode == "late"
            ],
        }

    @staticmethod
    def duplicate_and_stale(directory: Path, output: Path) -> dict[str, object]:
        """Reconcile one exact match and reject stale responses through saved-input replay.

        Args:
            directory: Copied Coinbase config, schema and exact snapshot.
            output: Exclusive synthetic recording directory.

        Returns:
            Original and duplicate clocks, exact remaining size and stale-response evidence.
        """
        config = CaptureConfig.read(directory / "coinbase-btc-usd.json")
        request = CaptureRequest(
            config=config,
            recording_id="00000000-0000-4000-8000-000000000024",
            implementation_identity="a" * 64,
        )
        journal, replay = (
            CaptureJournal(output, request),
            CaptureReplay(config, book_factory=BookAdapters.create),
        )
        journal.start()
        match = b'["match","BTC-USD","11","maker","taker","100","0.1",null]'
        rows: tuple[tuple[str, bytes], ...] = (
            ("session", b""),
            ("frame", (directory / "coinbase-schema.json").read_bytes()),
            ("frame", _ACK),
            ("snapshot", (directory / "coinbase-snapshot.json").read_bytes()),
            ("frame", match),
            ("frame", match),
        )
        for clock, (kind, raw) in enumerate(rows, 1):
            record = DomainCodec().decode_json(
                DomainCodec().encode_json(dict(kind=kind, epoch=0, received_ns=clock, raw=raw)),
                CaptureRecord,
            )
            journal.append(record)
            replay.apply(record)
        assert isinstance(replay.book, CoinbaseBook)
        size = replay.book.orders["maker"].size
        assert size == Decimal("0.200000000000000001") and replay.duplicates == 1
        conflict = CaptureRecord(
            kind="frame", epoch=0, received_ns=7, raw=match.replace(b'"0.1"', b'"0.2"')
        )
        journal.append(conflict)
        assert replay.apply(conflict) == "invalid_frame" and replay.invalid
        assert replay.book.orders["maker"].size == size
        for record in (
            CaptureRecord(
                kind="session_end",
                epoch=0,
                received_ns=8,
                reason="invalid_stream_requires_snapshot",
            ),
            CaptureRecord(kind="snapshot", epoch=0, received_ns=9, raw=rows[3][1]),
            CaptureRecord(kind="session", epoch=1, received_ns=10),
            CaptureRecord(kind="snapshot", epoch=0, received_ns=11, raw=rows[3][1]),
            CaptureRecord(kind="end", epoch=1, received_ns=12, reason="duration_limit"),
        ):
            journal.append(record)
            replay.apply(record)
        assert replay.stale_snapshots == 2 and not replay.book.ready
        journal.finish(1)
        assert (
            SavedCapture.read(output, book_factory=BookAdapters.create).summary()
            == replay.summary()
        )
        retained = [r for r in journal.records() if r.raw == match]
        assert [r.received_ns for r in retained] == [5, 6]
        return {
            "duplicate_receipt_ns": [r.received_ns for r in retained],
            "economic_matches": replay.updates,
            "remaining_size": str(size),
            "conflicting_duplicate": "invalid_frame",
            "stale_snapshots": replay.stale_snapshots,
            "new_epoch_synchronized": replay.book.ready,
        }


class _Socket:
    """Keep receipt independent of the blocked snapshot's thread."""

    def __init__(self, transport: _Transport, frames: tuple[bytes, ...]) -> None:
        """Bind a finite wire script and its independent REST synchronization barriers."""
        self.transport = transport
        self.frames = iter(frames)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        """Retain outbound subscriptions to check one resubscription per epoch."""
        self.sent.append(message)

    async def recv(self) -> bytes:
        """Disconnect during REST work or wait until recovery cancels receipt."""
        await self.transport.sleep(0)
        raw = next(self.frames, None)
        if raw is not None:
            return raw
        if self.transport.mode == "late":
            assert await asyncio.to_thread(self.transport.started.wait, 5)
            raise OSError("synthetic disconnect during REST acquisition")
        await asyncio.Event().wait()
        raise AssertionError("unreachable receive")

    async def close(self) -> None:
        """Expose owned socket cleanup to the caller's assertions."""
        self.closed = True


class _Transport(VenueTransport):
    """Expose per-endpoint budgets and late REST completion without source access."""

    def __init__(self, config: CaptureConfig, directory: Path, mode: str) -> None:
        """Bind copied source fixtures, bounded configuration and recovery fault mode."""
        super().__init__(config)
        self.directory, self.mode = directory, mode
        self.sockets: list[_Socket] = []
        self.requests = 0
        self.started, self.release, self.finished = Event(), Event(), Event()
        self.sleep = asyncio.sleep
        self.delays: list[float] = []

    async def pause(self, delay: float) -> None:
        """Observe requested backoff without making fixture acceptance wait for wall time."""
        if delay:
            self.delays.append(delay)
        await self.sleep(0)

    async def open(self, timeout: float) -> FeedSocket:
        """Refuse overlapping REST work and supply the next isolated connection."""
        assert timeout > 0
        assert not self.sockets or self.finished.is_set(), "overlapping recovery requests"
        self.started.clear()
        self.release.clear()
        self.finished.clear()
        suffix = b'["noop","BTC-USD","12",null]' if self.mode == "bridge_gap" else _ACK
        socket = _Socket(
            self, ((self.directory / "coinbase-schema.json").read_bytes(), _ACK, suffix)
        )
        self.sockets.append(socket)
        return socket

    def snapshot(self) -> bytes:
        """Release a late response or simulate a rate-limited endpoint failure."""
        self.requests += 1
        self.started.set()
        try:
            if self.mode == "rate_limit":
                raise OSError("market data HTTP status 429")
            assert self.release.wait(5), "collector failed to drain the affected epoch"
            return (self.directory / "coinbase-snapshot.json").read_bytes()
        finally:
            self.finished.set()


def main() -> None:
    """Verify installed imports, run recovery cases and print small synthetic observations."""
    directory, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    installed = Path(market_data.__file__).resolve()
    assert "site-packages" in installed.parts and not installed.is_relative_to(directory)
    output.mkdir()
    results = {
        "installed_package": str(installed),
        "duplicate_and_stale": RecoveryScenarios.duplicate_and_stale(directory, output / "lineage"),
        "recovery": [
            RecoveryScenarios.recovery(directory, output / mode, mode)
            for mode in ("late", "bridge_gap", "rate_limit")
        ],
    }
    capture = output / "lineage"
    replay = subprocess.run(
        [str(Path(sys.executable).parent / "alpha-collect"), "replay", "--capture", str(capture)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    assert replay.stdout.strip() == DomainCodec().encode_json(
        SavedCapture.read(capture, book_factory=BookAdapters.create).summary()
    )
    (output / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
