"""Prove the shared public capture callback follows durable native application."""

from __future__ import annotations

# standard library imports
import asyncio
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest, FeedSocket
from market_data.storage import CaptureJournal
from telemetry import RuntimeMeasurementJournal

_ROOT = Path(__file__).parents[4]
_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
_BOOK = (
    b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"snapshot",'
    b'"data":[{"prevSeqId":-1,"seqId":10,'
    b'"asks":[["101","1","0","1"]],"bids":[["100","2","0","2"]]}]}'
)


class _Socket:
    """Deliver a finite native public-book stream without external network access."""

    def __init__(self) -> None:
        """Bind a real acknowledgement followed by one exact book message."""
        self._frames = iter((_ACK, _BOOK))
        self.closed = False

    async def send(self, message: str) -> None:
        """Require the selected public book subscription."""
        assert '"books"' in message and '"BTC-USDT"' in message

    async def recv(self) -> bytes:
        """Return the next whole source frame."""
        frame = next(self._frames, None)
        if frame is None:
            raise OSError("bounded source ended")
        await asyncio.sleep(0)
        return frame

    async def close(self) -> None:
        """Expose cleanup after success or a callback failure."""
        self.closed = True


class _Transport(VenueTransport):
    """Use the public transport contract with a deterministic socket."""

    def __init__(self, config: CaptureConfig, socket: _Socket) -> None:
        """Bind selected source identity and the scripted transport boundary."""
        super().__init__(config)
        self._socket = socket

    async def open(self, timeout: float) -> FeedSocket:
        """Return one bounded native socket for the selected request."""
        assert timeout > 0
        return self._socket


class _Observer:
    """Check committed input at every callback, optionally failing on a market row."""

    def __init__(self, root: Path, request: CaptureRequest, *, fail_market: bool = False) -> None:
        """Bind the exact expected durable journal and failure mode."""
        self.root, self.request, self.fail_market = root, request, fail_market
        self.rows: list[BookObservation] = []

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Require original bytes committed before projection or application effects."""
        committed = tuple(CaptureJournal(self.root, self.request).records(completed=False))
        assert committed[-2] == record
        assert row.position == len(self.rows)
        assert row.received_ns == record.received_ns and row.epoch == record.epoch
        if row.outcome == "snapshot":
            assert row.status == "degraded" and row.bids and row.asks
            if self.fail_market:
                raise RuntimeError("consumer refused market boundary")
        self.rows.append(row)


class TestCaptureObserver:
    """Keep collector continuation tied to every durable callback outcome."""

    @staticmethod
    def _request() -> CaptureRequest:
        """Bind one finite maintained OKX selection with prechosen recording identity."""
        config = replace(
            CaptureConfig.read(_ROOT / "configs" / "live" / "okx-btc-usdt.json"),
            duration_seconds=5,
            max_messages=2,
            retries=0,
        )
        return CaptureRequest(
            config=config,
            recording_id="d" * 36,
            implementation_identity="e" * 64,
        )

    def test_callback_sees_each_durable_canonical_boundary(self, tmp_path: Path) -> None:
        """The caller supplies its capture ID before opening and observes terminal loss."""
        request, socket = self._request(), _Socket()
        observer = _Observer(tmp_path / request.recording_id, request)
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=_Transport(request.config, socket),
            subscriptions=VenueSubscriptions(),
            observer=observer,
        )
        result = asyncio.run(runner.run(request, tmp_path))
        assert result.request == request and result.root == tmp_path / request.recording_id
        assert [row.outcome for row in observer.rows] == [
            "session",
            "acknowledgement",
            "snapshot",
            "session_end",
            "end",
        ]
        assert result.summary["replay_parity"] is True and socket.closed

    def test_callback_failure_propagates_without_publishing_capture(self, tmp_path: Path) -> None:
        """A failed live consumer closes receipt and leaves a verifiable interrupted prefix."""
        request, socket = self._request(), _Socket()
        root = tmp_path / request.recording_id
        observer = _Observer(root, request, fail_market=True)
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=_Transport(request.config, socket),
            subscriptions=VenueSubscriptions(),
            observer=observer,
        )
        with pytest.raises(RuntimeError, match="consumer refused market boundary"):
            asyncio.run(runner.run(request, tmp_path))
        assert socket.closed and not (root / "manifest.json").exists()
        interrupted = tuple(CaptureJournal(root, request).records(completed=False))
        assert interrupted[-2].raw == _BOOK and interrupted[-1].kind == "gap"

    def test_opt_in_measurements_retain_each_fsynced_frame_and_queue_change(
        self, tmp_path: Path
    ) -> None:
        """Tie individual monotonic timings to durable cursors without changing raw input."""
        request, socket = self._request(), _Socket()
        path = tmp_path / "capture-measurements.jsonl"
        with RuntimeMeasurementJournal(path, sync_every=1) as measurements:
            runner = CaptureRunner(
                book_factory=BookAdapters.create,
                transport=_Transport(request.config, socket),
                subscriptions=VenueSubscriptions(),
                measurements=measurements,
            )
            result = asyncio.run(runner.run(request, tmp_path))
        rows = tuple(
            msgspec.json.decode(line, type=dict[str, object])
            for line in path.read_bytes().splitlines()
        )
        boundaries = tuple(row for row in rows if row["kind"] == "capture_boundary")
        queues = tuple(row for row in rows if row["kind"] == "queue")
        assert len(boundaries) == 2
        assert all(row["schema_version"] == "runtime-measurement" for row in rows)
        assert [row["cursor"] for row in boundaries] == [2, 3]
        assert [row["outcome"] for row in boundaries] == ["acknowledgement", "snapshot"]
        for row in boundaries:
            receipt = row["receipt_ns"]
            append_started = row["append_started_ns"]
            durable = row["durable_ns"]
            reconstructed = row["reconstructed_ns"]
            assert all(
                isinstance(value, int)
                for value in (receipt, append_started, durable, reconstructed)
            )
            assert isinstance(receipt, int)
            assert isinstance(append_started, int)
            assert isinstance(durable, int)
            assert isinstance(reconstructed, int)
            assert receipt <= append_started <= durable <= reconstructed
            record_fsync = row["record_fsync_ns"]
            cursor_checkpoint = row["cursor_checkpoint_ns"]
            assert isinstance(record_fsync, int) and record_fsync >= 0
            assert isinstance(cursor_checkpoint, int) and cursor_checkpoint >= 0
        assert [row["phase"] for row in queues].count("accepted") >= 2
        assert [row["phase"] for row in queues].count("acknowledged") >= 2
        assert [row["phase"] for row in queues].count("durable_ready") >= 2
        assert any(
            isinstance(age, int) and age > 0
            for age in (row["oldest_age_ns"] for row in queues if row["phase"] == "durable_ready")
        )
        assert any(
            isinstance(value, int) and value >= 1
            for value in (row["pending_records"] for row in queues)
        )
        assert result.summary["replay_parity"] is True
        assert tuple(
            record.raw
            for record in CaptureJournal(result.root, request).records()
            if record.kind == "frame"
        ) == (_ACK, _BOOK)
