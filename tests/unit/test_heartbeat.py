"""Unit tests for HeartbeatMonitor."""

from __future__ import annotations

import apps.data_collector.connectors.heartbeat as heartbeat_mod
import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_monitor(timeout: float = 10.0) -> tuple[heartbeat_mod.HeartbeatMonitor, list[float]]:
    """Return a monitor whose clock is controlled by the returned list."""
    clock: list[float] = [0.0]
    monitor = heartbeat_mod.HeartbeatMonitor(timeout_seconds=timeout, time_func=lambda: clock[0])
    return monitor, clock


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_invalid_timeout_raises() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        heartbeat_mod.HeartbeatMonitor(timeout_seconds=0.0)

    with pytest.raises(ValueError, match="timeout_seconds"):
        heartbeat_mod.HeartbeatMonitor(timeout_seconds=-5.0)


# ---------------------------------------------------------------------------
# record_heartbeat / tracked
# ---------------------------------------------------------------------------


def test_record_heartbeat_tracks_connector() -> None:
    monitor, _ = _make_monitor()
    monitor.record_heartbeat("conn-a")
    assert "conn-a" in monitor.tracked()


def test_record_multiple_connectors() -> None:
    monitor, _ = _make_monitor()
    for cid in ["a", "b", "c"]:
        monitor.record_heartbeat(cid)
    assert set(monitor.tracked()) == {"a", "b", "c"}


def test_repeated_heartbeat_updates_timestamp() -> None:
    monitor, clock = _make_monitor(timeout=5.0)
    monitor.record_heartbeat("conn-a")
    clock[0] = 4.0
    monitor.record_heartbeat("conn-a")
    clock[0] = 8.0
    # Last beat at t=4; now t=8 → gap is 4s < timeout 5s → not stale
    assert monitor.check_stale() == []


# ---------------------------------------------------------------------------
# check_stale
# ---------------------------------------------------------------------------


def test_no_stale_when_fresh() -> None:
    monitor, clock = _make_monitor(timeout=30.0)
    monitor.record_heartbeat("conn-a")
    clock[0] = 29.9
    assert monitor.check_stale() == []


def test_stale_detected_after_timeout() -> None:
    monitor, clock = _make_monitor(timeout=10.0)
    monitor.record_heartbeat("conn-a")
    clock[0] = 10.1
    stale = monitor.check_stale()
    assert stale == ["conn-a"]


def test_only_stale_connectors_returned() -> None:
    monitor, clock = _make_monitor(timeout=10.0)
    monitor.record_heartbeat("fresh")
    clock[0] = 5.0
    monitor.record_heartbeat("stale")
    clock[0] = 20.0
    # "fresh" was recorded at t=0, gap = 20s → stale
    # "stale" was recorded at t=5, gap = 15s → stale
    stale = monitor.check_stale()
    assert set(stale) == {"fresh", "stale"}


def test_second_beat_resets_staleness() -> None:
    monitor, clock = _make_monitor(timeout=10.0)
    monitor.record_heartbeat("conn-a")
    clock[0] = 15.0
    # Stale at this point
    assert "conn-a" in monitor.check_stale()
    # Refresh
    monitor.record_heartbeat("conn-a")
    clock[0] = 20.0
    # Gap from last beat (t=15) to now (t=20) = 5s < 10s timeout
    assert monitor.check_stale() == []


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def test_remove_stops_tracking() -> None:
    monitor, _ = _make_monitor()
    monitor.record_heartbeat("conn-a")
    monitor.remove("conn-a")
    assert "conn-a" not in monitor.tracked()
    assert monitor.check_stale() == []


def test_remove_unknown_is_noop() -> None:
    monitor, _ = _make_monitor()
    monitor.remove("never-tracked")  # No exception.
    assert monitor.tracked() == []
