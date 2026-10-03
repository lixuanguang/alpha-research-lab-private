"""Keep cache classes and underpowered cold-query samples distinct."""

from __future__ import annotations

# standard library imports
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

# third party library imports
import pytest
from capacity_history_queries import CacheClass, CapacityHistoryQueries
from capacity_page_cache import PageCache
from capacity_reads import _SourceIndex


class TestCapacityHistoryQueries:
    """Require sufficient exact observations for each separately declared cache boundary."""

    def test_cold_percentiles_require_1000_actual_observations(self) -> None:
        """A short pilot supplies a range and cannot claim the cold query target."""
        short = CapacityHistoryQueries._summarize((2_500_000_000,) * 999, (2_000_000_000,) * 3)
        assert short["status"] == "unmeasured"
        assert "p99_ns" not in short
        complete = CapacityHistoryQueries._summarize((2_500_000_000,) * 1000, (2_000_000_000,) * 3)
        assert complete["status"] == "fail"
        assert complete["p99_ns"] == 2_500_000_000
        warm = CapacityHistoryQueries._summarize((1_000_000,) * 1000, (50_000_000,) * 3)
        assert warm["status"] == "pass"
        assert complete["status"] == "fail"

    def test_dashboard_readers_are_joined_by_their_own_schedule(self) -> None:
        """Waiting follows each reader's paced budget, not the depth readers' finish."""
        start = 1_000_000_000
        cold = CapacityHistoryQueries._reader_deadline_ns(start, 250, "application_cold")
        warm = CapacityHistoryQueries._reader_deadline_ns(start, 250, "warm")
        assert cold - start == 250 * 3_000_000_000 + 30_000_000_000
        assert warm - start == 250 * 1_000_000_000 + 30_000_000_000
        # The stopped cohort's slowest cold dashboard request took 0.956 s.
        assert cold - start > 250 * 956_000_000

    def test_missing_identity_and_invented_duration_fail(self) -> None:
        """Neither changed result bytes nor a missing monotonic duration can be counted."""
        with pytest.raises(ValueError, match="exact result identity"):
            CapacityHistoryQueries._identity({"returned_bytes": 100})
        with pytest.raises(ValueError, match="invalid retained query duration"):
            CapacityHistoryQueries._integer({"service_ns": None}, "service_ns")

    def test_limits_are_declared_before_reading_trial(self, tmp_path: Path) -> None:
        """Refuse an excessive authored query fixture without opening unavailable history."""
        with pytest.raises(ValueError, match="query boundary"):
            CapacityHistoryQueries(
                tmp_path / "trial",
                tmp_path / "output",
                samples_per_reader=250,
                dashboard_events_per_account=10_001,
            )

    def test_cache_classes_are_declared_once(self, tmp_path: Path) -> None:
        """An empty or repeated cache-class declaration is refused before reading history."""
        for classes in ((), ("filesystem_cold", "filesystem_cold")):
            with pytest.raises(ValueError, match="distinct declared cache classes"):
                CapacityHistoryQueries(
                    tmp_path / "trial",
                    tmp_path / "output",
                    samples_per_reader=250,
                    dashboard_events_per_account=10_000,
                    cache_classes=classes,
                )

    def test_cold_files_cover_every_reader_file(self, tmp_path: Path) -> None:
        """Each depth group holds its capture and delivery files; the dashboard its store."""
        trial = tmp_path / "trial"
        (trial / "reads").mkdir(parents=True)
        (trial / "reads/summary.json").write_bytes(
            b'{"steady_ended_at_utc": "2026-10-02T00:00:00+00:00"}'
        )
        capture, delivery = tmp_path / "capture", tmp_path / "delivery"
        for path in (
            capture / "segment/records.bin",
            delivery / "deliveries.log",
            delivery / "deliveries.as-of",
            trial / "operating/monitoring/telemetry.sqlite3",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        (delivery / "empty").write_bytes(b"")
        queries = CapacityHistoryQueries(
            trial,
            tmp_path / "output",
            samples_per_reader=250,
            dashboard_events_per_account=0,
            cache_classes=("filesystem_cold",),
        )
        queries.sources = {
            "okx-btc-book": cast(
                _SourceIndex,
                SimpleNamespace(capture_root=capture, delivery_path=delivery / "deliveries.log"),
            )
        }
        assert queries._cold_files() == {
            "okx-btc-book": (
                capture / "segment/records.bin",
                delivery / "deliveries.as-of",
                delivery / "deliveries.log",
            ),
            "dashboard": (trial / "operating/monitoring/telemetry.sqlite3",),
        }

    @pytest.mark.parametrize(
        "classes",
        (("application_cold", "warm"), ("filesystem_cold",), ("warm", "filesystem_cold")),
    )
    def test_each_declared_class_keeps_its_own_label_and_budget(
        self, tmp_path: Path, classes: tuple[CacheClass, ...]
    ) -> None:
        """Cold classes take the cold p99 budget, warm the warm triple, labelled as declared."""
        trial = tmp_path / "trial"
        (trial / "reads").mkdir(parents=True)
        (trial / "reads/summary.json").write_bytes(
            b'{"steady_ended_at_utc": "2026-10-02T00:00:00+00:00"}'
        )
        queries = CapacityHistoryQueries(
            trial,
            tmp_path / "output",
            samples_per_reader=250,
            dashboard_events_per_account=0,
            cache_classes=classes,
        )
        rows: tuple[dict[str, object], ...] = tuple(
            {
                "boundary": boundary,
                "cache_class": cache_class,
                "target": "t",
                "status": "ok",
                "service_ns": 1_000_000,
                "response_ns": 2_000_000,
            }
            for boundary in ("depth_bbo", "dashboard")
            for cache_class in classes
            for _ in range(2)
        )
        results = queries._class_results(rows, {"depth_bbo": ("t",), "dashboard": ("t",)})
        cold = {"depth_bbo": (2_000_000_000,) * 3, "dashboard": (3_000_000_000,) * 3}
        warm = {
            "depth_bbo": (50_000_000, 200_000_000, 500_000_000),
            "dashboard": (100_000_000, 400_000_000, 1_000_000_000),
        }
        assert [(row["boundary"], row["cache_class"]) for row in results] == [
            (boundary, cache_class)
            for boundary in ("depth_bbo", "dashboard")
            for cache_class in classes
        ]
        for row in results:
            boundary, cache_class = cast(str, row["boundary"]), row["cache_class"]
            latency = cast(dict[str, object], row["service_latency"])
            expected = warm[boundary] if cache_class == "warm" else cold[boundary]
            assert latency["budget_ns"] == expected
            assert (row["requests"], row["failures"]) == (2, 0)


class _StubbornCache(PageCache):
    """Leave pages resident for a declared number of eviction calls."""

    def __init__(self, resident_calls: int) -> None:
        """Skip libc binding; only the eviction outcome is simulated."""
        self.remaining = resident_calls
        self.calls = 0

    def evict(self, paths: object) -> dict[str, int]:
        """Report one resident page per file until the stubborn calls are spent."""
        self.calls += 1
        self.remaining -= 1
        pages = 1 if self.remaining >= 0 else 0
        return {str(path): pages for path in cast(tuple[Path, ...], paths)}


class TestFilesystemColdEviction:
    """A round is released only after every reader file is proved non-resident."""

    def test_eviction_retries_until_nothing_is_resident(self) -> None:
        """Residual pages are evicted again, within the declared attempts."""
        cache = _StubbornCache(resident_calls=2)
        attempts, residual = CapacityHistoryQueries._evict_verified(cache, (Path("/a"), Path("/b")))
        assert (attempts, residual, cache.calls) == (3, {}, 3)

    def test_persistent_residency_is_reported_not_released(self) -> None:
        """After the declared attempts the resident files are returned for a failed round."""
        cache = _StubbornCache(resident_calls=10)
        attempts, residual = CapacityHistoryQueries._evict_verified(cache, (Path("/a"),))
        assert (attempts, residual, cache.calls) == (3, {Path("/a"): 1}, 3)

    @pytest.mark.skipif(sys.platform != "darwin", reason="eviction is declared for Darwin")
    def test_eviction_makes_a_cached_file_nonresident(self, tmp_path: Path) -> None:
        """A read file is resident, eviction leaves no page, and the next read reloads it."""
        cache = PageCache()
        path = tmp_path / "history.bin"
        path.write_bytes(b"\x01" * (cache.page * 64))
        path.read_bytes()
        assert cache.resident(path) == cache.pages(path) == 64
        assert cache.evict((path,)) == {str(path): 0}
        assert cache.resident(path) == 0
        assert path.read_bytes() == b"\x01" * (cache.page * 64)
        assert cache.resident(path) == 64
        empty = tmp_path / "empty"
        empty.write_bytes(b"")
        assert cache.evict((empty,)) == {str(empty): 0}

    def test_other_platforms_are_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Eviction semantics differ elsewhere, so the protocol refuses rather than guesses."""
        monkeypatch.setattr(sys, "platform", "linux")
        with pytest.raises(RuntimeError, match="Darwin only"):
            PageCache()
