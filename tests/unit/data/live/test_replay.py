"""Verify epoch-scoped invalidity and resynchronization through the replay consumer."""

# standard library imports
from pathlib import Path

# project library imports
from alpha_research.data.live.config import CaptureConfig
from alpha_research.data.live.journal import CaptureRecord
from alpha_research.data.live.replay import CaptureReplay

_ROOT = Path(__file__).parents[4]


class TestCaptureReplay:
    """Keep gaps visible when a later native snapshot restores usable state."""

    def test_replay_requires_fresh_snapshot_after_gap(self) -> None:
        """Invalid data stays unusable until a new epoch is acknowledged and snapshotted."""
        config = CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json")
        replay = CaptureReplay(config)
        for epoch in (0, 1):
            replay.apply(CaptureRecord(kind="session", epoch=epoch, received_ns=1 + epoch * 10))
            for raw in (
                b'{"event":"conf","status":"OK","flags":65536}',
                (
                    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCU'
                    b'SD","prec":"R0","freq":"F0","len":"25"}'
                ),
                b"[7,[[1,3,2]],1]",
            ):
                replay.apply(
                    CaptureRecord(kind="frame", epoch=epoch, received_ns=2 + epoch * 10, raw=raw)
                )
            assert replay.book.ready
            if epoch == 0:
                replay.apply(CaptureRecord(kind="frame", epoch=0, received_ns=3, raw=b'[7,"hb",9]'))
                assert not replay.book.ready
        assert len(replay.gaps) == 1
