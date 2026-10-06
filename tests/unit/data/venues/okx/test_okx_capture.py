"""Exercise the OKX public subscription, durable recovery and application heartbeat."""

from __future__ import annotations

# standard library imports
import asyncio
import time
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from applications.collect import collect
from configuration import CaptureConfig
from market_data.adapters.transport import VenueTransport
from market_data.collection import ReceiptClock, ReceiptStream
from market_data.contracts import CaptureRecord, FeedSocket

_ROOT = Path(__file__).parents[5]
_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
_SNAPSHOT = (
    b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"snapshot","data":[{"pre'
    b'vSeqId":-1,"seqId":10,"asks":[["101","1","0","1"]],"bids":[["100","2","0","2"]]}'
    b"]}"
)
_GAP = (
    b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"update","data":[{"prevS'
    b'eqId":9,"seqId":11,"asks":[],"bids":[]}]}'
)


class OKXSocket:
    """Deliver one finite public source script with a checked subscription."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind the finite script.

        Args:
            frames: Synthetic source messages.
        """
        self.frames = iter(frames)
        self.closed = False

    async def send(self, message: str) -> None:
        """Require the intended public channel.

        Args:
            message: Outbound subscription JSON.
        """
        assert '"books"' in message and '"BTC-USDT"' in message

    async def recv(self) -> bytes:
        """End a scripted epoch with visible disconnect.

        Returns:
            Next native frame.

        Raises:
            OSError: The source script ended.
        """
        await asyncio.sleep(0)
        frame = next(self.frames, None)
        if frame is None:
            raise OSError("scripted disconnect")
        return frame

    async def close(self) -> None:
        """Record cleanup after collection."""
        self.closed = True


class OKXTransport(VenueTransport):
    """Use actual storage/replay across a failing epoch and a new snapshot."""

    async def open(self, timeout: float) -> FeedSocket:
        """Supply two sessions for deterministic gap recovery.

        Args:
            timeout: Remaining connection budget.

        Returns:
            Fresh independently synchronized socket.
        """
        return OKXSocket((_ACK, _SNAPSHOT, _GAP))


class PingSocket:
    """Remain quiet until the required OKX application ping arrives."""

    def __init__(self) -> None:
        """Create the liveness trigger."""
        self.ping = asyncio.Event()

    async def send(self, message: str) -> None:
        """Accept only the documented text ping.

        Args:
            message: Heartbeat text.
        """
        assert message == "ping"
        self.ping.set()

    async def recv(self) -> bytes:
        """Respond only after the application has requested liveness.

        Returns:
            Exact OKX text pong bytes.
        """
        await self.ping.wait()
        return b"pong"

    async def close(self) -> None:
        """No external resource exists in the synthetic socket."""


class TestOKXCapture:
    """Verify OKX-specific composition without replacing shared persistence with mocks."""

    def test_recovery_retains_gap_and_replays_new_snapshot(self, tmp_path: Path) -> None:
        """A linked new epoch recovers visible levels while its preceding gap remains visible."""
        config = replace(
            CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"), max_messages=5, retries=1
        )
        result = asyncio.run(
            collect(
                config, tmp_path, implementation_identity="a" * 64, transport=OKXTransport(config)
            )
        )
        assert result["epochs"] == 2 and result["synchronized"] is True
        assert result["levels"] == 2 and result["orders"] is None
        assert result["gaps"] and result["replay_parity"] is True

    def test_application_ping_does_not_consume_message_budget(self) -> None:
        """A quiet feed gets text ping/pong without mistaking a timer for a source frame."""
        config = replace(
            CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"), idle_seconds=1
        )
        queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(4)
        socket = PingSocket()
        asyncio.run(
            ReceiptStream.frames(
                socket, queue, config, 0, time.monotonic() + 4, 1, receipts=ReceiptClock()
            )
        )
        assert socket.ping.is_set()
        assert queue.get_nowait().raw == b"pong"
        assert queue.get_nowait().reason == "message_limit"
