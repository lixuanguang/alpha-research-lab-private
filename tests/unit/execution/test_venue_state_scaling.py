"""Measure venue transport state costs as retained receipts grow."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime
from pathlib import Path

# third party library imports
import pytest

# project library imports
from execution.venue_state import VenueStateStore


class TestVenueStateScaling:
    """Bound per-frame costs by the frame, not by the retained history."""

    @pytest.mark.performance
    def test_private_frame_receipt_ignores_retained_receipts(self, tmp_path: Path) -> None:
        """Retaining one heartbeat stays near flat while retained receipts grow tenfold."""
        store = VenueStateStore(tmp_path / "account.sqlite3", "account", b"scope")
        at = datetime(2026, 10, 1, tzinfo=UTC)
        retained = 0

        def frame() -> float:
            """Retain one new heartbeat frame and return how long it took."""
            nonlocal retained
            payload = b'[0,"hb",%d]' % retained
            started = time.perf_counter()
            store.receipt("private-frame", payload, at)
            retained += 1
            return time.perf_counter() - started

        medians: list[float] = []
        with store.claim():
            for size in (500, 5000):
                while retained < size:
                    frame()
                medians.append(sorted(frame() for _ in range(21))[10])
        print(f"frame receipt at 500/5000 receipts: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Decoding, re-encoding and fsyncing the whole state document grew with every receipt.
        assert medians[1] < 2 * medians[0]
