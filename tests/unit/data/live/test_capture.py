"""Exercise durable collection with deterministic disconnect, overload and disk faults."""

from __future__ import annotations

# standard library imports
import asyncio
import os
from pathlib import Path
from threading import Event
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.live.replay import CaptureReplay
from alpha_research.data.live.transport import FeedSocket, VenueTransport
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.venues.coinbase.auth import CoinbaseAccessError, CoinbaseCredentials
from alpha_research.pipelines.live import collect, receive_frames, receive_snapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[4]
_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'[7,"hb",1]',
    (
        b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCU'
        b'SD","prec":"R0","freq":"F0","len":"25"}'
    ),
    b"[7,[[1,100,2],[2,101,-1]],2]",
    b"[7,[1,100,1.5],3]",
)


class ScriptedSocket:
    """Yield independent wire inputs with deterministic async scheduling."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind one connection's finite message script.

        Args:
            frames: Finite exact messages for one synthetic connection.
        """
        self.frames = iter(frames)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        """Retain subscription messages for non-secret transport assertions.

        Args:
            message: One outbound subscription/configuration message; never logged.
        """
        self.sent.append(message)

    async def recv(self) -> bytes:
        """End the scripted connection with an explicit transport fault.

        Returns:
            Next complete source message.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        await asyncio.sleep(0)
        result = next(self.frames, None)
        if result is None:
            raise OSError("synthetic disconnect")
        return result

    async def close(self) -> None:
        """Expose collector shutdown to the test."""
        self.closed = True


class ScriptedTransport(VenueTransport):
    """Replace only the external connection boundary; use actual collector/storage/replay."""

    def __init__(self, config: CaptureConfig, sessions: tuple[tuple[bytes, ...], ...]) -> None:
        """Bind a finite set of permitted recovery attempts.

        Args:
            config: Validated native spot source selection and resource budgets.
            sessions: Finite per-connection scripts for recovery tests.
        """
        super().__init__(config)
        self.sessions = iter(sessions)
        self.sockets: list[ScriptedSocket] = []

    async def open(self, timeout: float) -> FeedSocket:
        """Deliver the next isolated connection, failing when retry budget is exhausted.

        Args:
            timeout: Remaining connection budget in seconds.

        Returns:
            Bounded connection for the selected feed or synthetic session.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        frames = next(self.sessions, None)
        if frames is None:
            raise OSError("synthetic connection failure")
        socket = ScriptedSocket(frames)
        self.sockets.append(socket)
        return socket


class StalledSubscriptionSocket(ScriptedSocket):
    """Hold the second outbound message until the capture deadline cancels it."""

    async def send(self, message: str) -> None:
        """Send the configuration frame, then stall subscription under backpressure.

        Args:
            message: Outbound non-secret configuration or subscription JSON.
        """
        await super().send(message)
        if len(self.sent) == 2:
            await asyncio.Event().wait()


class FailingJournal(CaptureJournal):
    """Fail the first market append after durable session metadata exists."""

    def append(self, record: CaptureRecord) -> None:
        """Represent a disk failure while preserving the last committed prefix.

        Args:
            record: One complete received message or scoped session transition.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        if record.kind == "frame":
            raise OSError("synthetic disk full")
        super().append(record)


class TestCapture:
    """Check observable recording and installed-library contracts on saved inputs."""

    @staticmethod
    def config() -> CaptureConfig:
        """Use the maintained source selection with a finite deterministic fixture budget.

        Returns:
            Validated maintained source config with bounded fixture limits.
        """
        return replace(
            CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
            max_messages=5,
            retries=0,
        )

    def test_durable_capture_parity_and_tamper(self, tmp_path: Path) -> None:
        """Store actual framed inputs and reproduce every message-boundary state offline."""
        config = self.config()
        transport = ScriptedTransport(config, (_FRAMES,))
        result = asyncio.run(
            collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
        )
        assert result["synchronized"] is True
        assert result["orders"] == 2
        assert result["gaps"] == []
        assert result["replay_parity"] is True
        root = next(tmp_path.iterdir())
        replay = CaptureReplay.read(root)
        assert replay.summary()["trace_identity"] == result["trace_identity"]
        assert all(socket.closed for socket in transport.sockets)
        descriptor = DomainCodec().decode_json((root / "manifest.json").read_bytes(), RawObject)
        digest = descriptor.sha256
        assert isinstance(digest, str)
        os.chmod(root / digest, 0o600)
        (root / digest).write_bytes(b"tampered")
        with pytest.raises(ValueError, match="size mismatch"):
            CaptureReplay.read(root)

    def test_subscription_deadline(self, tmp_path: Path) -> None:
        """Cancel blocked subscription sends and retain an unavailable closed session."""
        asyncio.run(self._subscription_deadline(tmp_path))

    async def _subscription_deadline(self, tmp_path: Path) -> None:
        """An outer guard makes a missing subscription timeout fail without hanging tests."""
        config = replace(self.config(), duration_seconds=1)
        socket = StalledSubscriptionSocket(())
        transport = ScriptedTransport(config, ())
        with patch.object(transport, "open", return_value=socket):
            async with asyncio.timeout(5):
                result = await collect(
                    config, tmp_path, implementation_identity="a" * 64, transport=transport
                )
        assert len(socket.sent) == 2 and socket.closed
        assert result["messages"] == 0 and result["synchronized"] is False
        assert result["stop_reason"] == "connect_failed_unknown_loss"
        assert result["gaps"] and result["replay_parity"] is True
        saved = CaptureReplay.read(next(tmp_path.iterdir()))
        assert saved.gaps[0]["reason"] == "connect_failed_unknown_loss"

    @pytest.mark.parametrize(
        "raw",
        [
            b'{"event":"info","version":3,"platform":{"status":1}}',
            b'{"event":"error","code":10300,"msg":"Subscription failed"}',
        ],
    )
    def test_rejected_source_session(self, tmp_path: Path, raw: bytes) -> None:
        """Keep incompatible negotiation visible without admitting a book."""
        config = self.config()
        transport = ScriptedTransport(config, ((raw, *_FRAMES),))
        result = asyncio.run(
            collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
        )
        assert result["messages"] == 1 and result["synchronized"] is False
        assert result["stop_reason"] == "invalid_stream_requires_snapshot"
        assert result["gaps"] and result["replay_parity"] is True
        assert transport.sockets[0].closed

    def test_disconnect_resubscription(self, tmp_path: Path) -> None:
        """A fresh snapshot recovers state while the old session's unknown gap survives."""
        config = replace(self.config(), retries=1, max_messages=8)
        transport = ScriptedTransport(config, (_FRAMES[:3], _FRAMES))
        result = asyncio.run(
            collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
        )
        assert result["epochs"] == 2
        assert result["synchronized"] is True
        assert result["gaps"]
        assert result["replay_parity"] is True
        assert len(transport.sockets) == 2

    def test_retry_exhaustion(self, tmp_path: Path) -> None:
        """Connection failures create finite unavailable epochs and visible terminal status."""
        config = replace(self.config(), retries=1)
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, ()),
            )
        )
        assert result["epochs"] == 2
        assert result["synchronized"] is False
        assert result["messages"] == 0
        assert result["gaps"]

    def test_persistence_failure_preserves_incomplete_prefix(self, tmp_path: Path) -> None:
        """No manifest is published after disk failure; offline inspection reports unknown loss."""
        config = self.config()
        transport = ScriptedTransport(config, (_FRAMES,))
        consumer = CaptureReplay(config)
        with (
            patch("alpha_research.pipelines.live.CaptureJournal", FailingJournal),
            patch("alpha_research.pipelines.live.CaptureReplay", return_value=consumer),
        ):
            with pytest.raises(OSError, match="disk full"):
                asyncio.run(
                    collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
                )
        root = next(tmp_path.iterdir())
        assert consumer.messages == 0
        assert not (root / "manifest.json").exists()
        replay = CaptureReplay.read(root, completed=False)
        assert replay.gaps[0]["reason"] == "interrupted_persistence_unknown_tail"
        assert not replay.book.ready
        assert all(socket.closed for socket in transport.sockets)

    def test_same_day_restart_preserves_prior_segment(self, tmp_path: Path) -> None:
        """Two invocations publish distinct identities without replacing the first input."""
        config = self.config()
        results = []
        for _ in range(2):
            results.append(
                asyncio.run(
                    collect(
                        config,
                        tmp_path,
                        implementation_identity="a" * 64,
                        transport=ScriptedTransport(config, (_FRAMES,)),
                    )
                )
            )
        assert results[0]["request_identity"] != results[1]["request_identity"]
        assert len(list(tmp_path.iterdir())) == 2
        for root in tmp_path.iterdir():
            assert CaptureReplay.read(root).messages == len(_FRAMES)

    @pytest.mark.parametrize("invalid", [b"[7,[[1,-100,2]],2]", b"[7,[[1,100,0]],2]", b"not JSON"])
    def test_invalid_units_and_schema_retain_raw_diagnosis(
        self, tmp_path: Path, invalid: bytes
    ) -> None:
        """Raw invalid inputs survive the durable boundary while downstream state is blocked."""
        config = self.config()
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, ((*_FRAMES[:3], invalid),)),
            )
        )
        root = next(tmp_path.iterdir())
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        records = list(CaptureJournal(root, request).records())
        assert [r.raw for r in records if r.kind == "frame"][-1] == invalid
        assert result["synchronized"] is False and result["gaps"]
        assert result["replay_parity"] is True

    def test_slow_consumer_receipt_remains_bounded(self, tmp_path: Path) -> None:
        """A blocked consumer cannot stall receipt or hide queue overflow behind a good book."""
        applying, overflow = Event(), Event()
        config = replace(self.config(), queue_capacity=1, max_messages=100)

        class PressureSocket(ScriptedSocket):
            """Synchronize a source burst with an actual blocked downstream invocation."""

            delivered = 0

            async def recv(self) -> bytes:
                """Wait for downstream processing, then fill and overflow its bounded queue.

                Returns:
                    One exact frame in the deliberate burst.
                """
                if self.delivered == 1:
                    assert await asyncio.to_thread(applying.wait, 5)
                raw = await super().recv()
                self.delivered += 1
                if self.delivered == 3:
                    overflow.set()
                return raw

        class SlowReplay(CaptureReplay):
            """Inspect persistence before blocking the first downstream message."""

            def apply(self, record: CaptureRecord) -> str:
                """Check the durable prefix before the live consumer can acknowledge a frame.

                Args:
                    record: One message delivered by capture or offline replay.

                Returns:
                    Normal replay classification after the deterministic barrier.
                """
                root = next(tmp_path.iterdir())
                if not (root / "manifest.json").exists():
                    request = DomainCodec().decode_json(
                        (root / "request.json").read_bytes(), CaptureRequest
                    )
                    assert (
                        list(CaptureJournal(root, request).records(completed=False))[-2] == record
                    )
                    if record.kind == "frame" and self.messages == 0:
                        applying.set()
                        assert overflow.wait(5), "consumer blocked receipt event loop"
                return super().apply(record)

        socket = PressureSocket(_FRAMES)
        transport = ScriptedTransport(config, ())
        with (
            patch.object(transport, "open", return_value=socket),
            patch("alpha_research.pipelines.live.CaptureReplay", SlowReplay),
        ):
            result = asyncio.run(
                collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
            )
        assert socket.delivered == 3 and socket.closed
        assert result["messages"] == 2 and result["stop_reason"] == "overload_unknown_loss"
        assert result["gaps"] and result["replay_parity"] is True

    def test_truncated_tail(self, tmp_path: Path) -> None:
        """Process death in an append preserves readable records and explicitly rejects the tail."""
        request = CaptureRequest(
            config=self.config(),
            recording_id="00000000-0000-4000-8000-000000000001",
            implementation_identity="a" * 64,
        )
        root = tmp_path / "attempt"
        journal = CaptureJournal(root, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        with (root / "journal.jsonl").open("ab") as output:
            output.write(b'{"kind":"frame"')
        replay = CaptureReplay.read(root, completed=False)
        assert replay.messages == 0
        assert len(replay.gaps) == 1
        assert not replay.ended

    def test_storage_limit(self, tmp_path: Path) -> None:
        """A bounded journal reserves room for a visible terminal gap, without silent clipping."""
        config = replace(self.config(), max_bytes=8192, max_frame_bytes=2048, max_messages=100)
        frames = _FRAMES + tuple(
            b'{"event":"info","unused":"' + b"x" * 1000 + b'"}' for _ in range(10)
        )
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, (frames,)),
            )
        )
        assert result["stop_reason"] == "storage_limit_unknown_tail"
        root = next(tmp_path.iterdir())
        assert (root / "journal.jsonl").stat().st_size <= config.max_bytes
        assert result["gaps"]

    def test_missing_auth_before_io(self, tmp_path: Path) -> None:
        """Coinbase missing auth neither creates an attempt nor opens a socket."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        with pytest.raises(CoinbaseAccessError):
            asyncio.run(collect(config, tmp_path, implementation_identity="a" * 64))
        assert list(tmp_path.iterdir()) == []

    def test_overload(self) -> None:
        """A full application queue stops receipt and emits unknown-loss metadata."""
        asyncio.run(self._overload())

    async def _overload(self) -> None:
        """Hold the consumer until the bounded producer observes the full queue."""
        config = replace(self.config(), queue_capacity=1)
        queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(1)
        task = asyncio.create_task(
            receive_frames(ScriptedSocket(_FRAMES), queue, config, 0, float("inf"), 5)
        )
        for _ in range(5):
            await asyncio.sleep(0)
        first = await queue.get()
        assert first.kind == "frame"
        ending = await queue.get()
        assert ending.reason == "overload_unknown_loss"
        await task


class SnapshotSocket(ScriptedSocket):
    """Keep the synthetic feed open until the snapshot precedes its final message."""

    def __init__(self, frames: tuple[bytes, ...], snapshot_queued: asyncio.Event) -> None:
        """Bind an explicit ordering barrier rather than relying on worker-thread speed.

        Args:
            frames: Complete finite source script.
            snapshot_queued: Signal that the actual snapshot receiver enqueued its result.
        """
        super().__init__(frames)
        self.remaining = len(frames)
        self.snapshot_queued = snapshot_queued

    async def recv(self) -> bytes:
        """Deliver the final update only after the independent snapshot is queued.

        Returns:
            Next exact source frame.
        """
        if self.remaining == 1:
            await self.snapshot_queued.wait()
        self.remaining -= 1
        return await super().recv()


class CoinbaseScript(VenueTransport):
    """Exercise concurrent snapshot fetching while preserving streamed L3 receipt order."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind the actual config and deterministic snapshot source.

        Args:
            config: Explicit Coinbase selection and bounded capture limits.
        """
        super().__init__(config)
        self.snapshot_queued = asyncio.Event()
        self.socket = SnapshotSocket(
            (
                (_ROOT / "tests/fixtures/l3/coinbase-schema.json").read_bytes(),
                b'{"type":"subscriptions","channels":[{"name":"level3",'
                b'"product_ids":["BTC-USD"]}]}',
                *(b'["noop","BTC-USD","' + str(i).encode() + b'",null]' for i in range(8, 30)),
            ),
            self.snapshot_queued,
        )

    async def enqueue_snapshot(
        self, transport: VenueTransport, queue: asyncio.Queue[CaptureRecord], epoch: int
    ) -> None:
        """Signal the socket only after the real snapshot receiver has queued its input.

        Args:
            transport: The collector's selected synthetic REST source.
            queue: The collector's actual bounded persistence queue.
            epoch: Current connection epoch.
        """
        await receive_snapshot(transport, queue, epoch)
        self.snapshot_queued.set()

    async def open(self, timeout: float) -> FeedSocket:
        """Return the bounded synthetic socket.

        Args:
            timeout: Remaining receive budget; no real network is accessed.

        Returns:
            The scripted L3 connection.
        """
        return self.socket

    def snapshot(self) -> bytes:
        """Supply the independent complete L3 snapshot.

        Returns:
            Exact synthetic REST bytes with snapshot sequence ten.
        """
        return (_ROOT / "tests/fixtures/l3/coinbase-snapshot.json").read_bytes()


class TestCoinbaseCapture:
    """Verify the authenticated pipeline composition independently of live eligibility."""

    def test_snapshot_acquisition_and_replay(self, tmp_path: Path) -> None:
        """A concurrent REST response bridges persisted compact updates with exact parity."""
        from_config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        config = replace(from_config, retries=0, max_messages=24)
        transport = CoinbaseScript(config)
        with patch("alpha_research.pipelines.live.receive_snapshot", transport.enqueue_snapshot):
            result = asyncio.run(
                collect(
                    config,
                    tmp_path,
                    implementation_identity="a" * 64,
                    credentials=CoinbaseCredentials(
                        "fixture", b"fixture-secret", "fixture-passphrase"
                    ),
                    transport=transport,
                )
            )
        assert result["snapshots"] == 1
        assert result["orders"] == 1
        assert result["replay_parity"] is True
        assert result["synchronized"] is True
        assert result["gaps"] == []
        assert result["stop_reason"] == "message_limit"
        assert transport.socket.closed
        root = next(tmp_path.iterdir())
        journal = (root / "journal.jsonl").read_bytes()
        assert b"fixture-secret" not in journal
        assert b"fixture-passphrase" not in journal
