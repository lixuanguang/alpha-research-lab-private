"""Exercise bounded continuous quality independently of source transport."""

# third party library imports
import pytest

# project library imports
from alpha_research.data.live.journal import CaptureRecord
from alpha_research.data.live.quality import ContinuousQuality


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
