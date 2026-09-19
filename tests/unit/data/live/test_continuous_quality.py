"""Exercise bounded continuous quality independently of source transport."""

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.books import CaptureReplay
from market_data.contracts import CaptureRecord
from market_data.validation import ContinuousQuality

_ROOT = Path(__file__).parents[4]


class TestContinuousQuality:
    """Check observable admission and refusal without credentials or network access."""

    def test_quality_recovery_watermark_and_stalled_progress(self) -> None:
        """Neither open connections nor heartbeats or repeated messages resume decisions."""
        quality = ContinuousQuality("synthetic", lateness_ns=2, freshness_ns=5)
        for kind, instant, outcome, ready in (
            ("session", 10, "session", False),
            ("frame", 11, "snapshot", True),
        ):
            quality.observe(
                CaptureRecord(
                    kind="session" if kind == "session" else "frame", epoch=0, received_ns=instant
                ),
                outcome,
                ready=ready,
            )
        with pytest.raises(ValueError, match="degraded"):
            quality.require_usable(now_ns=11)
        quality.require_usable(now_ns=16, allow_degraded=True)
        assert quality.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=10), "duplicate", ready=True
        )
        assert quality.last_market_ns == 11 and quality.last_durable_ns == 11
        quality.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=17), "heartbeat", ready=True
        )
        assert quality.status == "stale" and quality.last_market_ns == 11
        with pytest.raises(ValueError, match="stale"):
            quality.require_usable(now_ns=17, allow_degraded=True)
        assert not quality.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=14), "update", ready=True
        )
        assert quality.status == "recovering"
        quality.observe(
            CaptureRecord(kind="session", epoch=1, received_ns=18), "session", ready=False
        )
        assert quality.status == "recovering"
        quality.observe(
            CaptureRecord(kind="frame", epoch=1, received_ns=19), "snapshot", ready=True
        )
        quality.require_usable(now_ns=19, allow_degraded=True)
        assert quality.transition_ns == 19

    def test_source_lateness_and_staleness(self) -> None:
        """Recent receipt cannot freshen an old source timestamp or cross its watermark."""
        quality = ContinuousQuality("synthetic", lateness_ns=2, freshness_ns=5)
        quality.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=100),
            "snapshot",
            ready=True,
            source_ns=80,
        )
        assert quality.status == "stale"
        assert not quality.observe(
            CaptureRecord(kind="frame", epoch=0, received_ns=101),
            "update",
            ready=True,
            source_ns=77,
        )
        assert quality.source_watermark_ns == 78 and quality.status == "recovering"

    def test_coinbase_buffered_source_stays_stale_after_snapshot_receipt(self) -> None:
        """Replay keeps an old buffered market clock instead of freshening from REST receipt."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        replay = CaptureReplay(config, book_factory=BookAdapters.create)
        receipt_ns = 2_000_000_000_000_000_000
        source_time = "2033-05-18T03:33:20.000000001Z"
        replay.apply(CaptureRecord(kind="session", epoch=0, received_ns=receipt_ns))
        replay.apply(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=receipt_ns + 1,
                raw=(
                    _ROOT / "tests/fixtures/market_data/coinbase/coinbase-schema.json"
                ).read_bytes(),
            )
        )
        replay.apply(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=receipt_ns + 2,
                raw=b'{"type":"subscriptions","channels":[{"name":"level3",'
                b'"product_ids":["BTC-USD"]}]}',
            )
        )
        replay.apply(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=receipt_ns + 3,
                raw=(
                    b'["open","BTC-USD","11","other","sell","102","2",'
                    b'"2033-05-18T03:33:20.000000001Z"]'
                ),
            )
        )
        outcome = replay.apply(
            CaptureRecord(
                kind="snapshot",
                epoch=0,
                received_ns=receipt_ns + 105_000_000_000,
                raw=(
                    _ROOT / "tests/fixtures/market_data/coinbase/coinbase-snapshot.json"
                ).read_bytes(),
            )
        )
        assert outcome == "snapshot"
        assert replay.book.source_time == source_time
        assert replay.quality.last_market_ns == receipt_ns + 1
        assert replay.quality.status == "stale"
        with pytest.raises(ValueError, match="stale"):
            replay.quality.require_usable(now_ns=receipt_ns + 105_000_000_000, allow_degraded=True)
