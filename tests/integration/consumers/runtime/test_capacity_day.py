"""Prove the day-run declarations, day gates, resource gate, receipts and retention classes."""

from __future__ import annotations

# standard library imports
import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_host import ResourceGate
from capacity_inputs import FixtureReceipts
from capacity_retention import DayRetention
from capacity_sustained import (
    DayNativeFixture,
    DayRehearsalFixture,
    DayRehearsalWorkload,
    DayWorkload,
)
from capacity_sustained_cohort import SustainedDeclaration, SustainedGates, _Observation
from test_capacity_sustained_cohort import SustainedCohortFixture

_MS = 1_000_000
_ACCOUNTS = ("okx-shared", "okx-isolated", "bitfinex-shared", "bitfinex-isolated")
type _Evidence = tuple[dict[str, object], dict[str, object], dict[str, object], list[_Observation]]


class DayFixture:
    """Author a passing day from sustained phase-A evidence."""

    @staticmethod
    def day(
        declaration: SustainedDeclaration, *, messages: int = 2_400_000, segments: int = 49
    ) -> _Evidence:
        """Scale phase-A evidence to the declared day and add per-account checkpoints."""
        summary, results, sustained, observations = SustainedCohortFixture.evidence("a")
        # An ordinary day's supervisor verdict is complete; only phase A excepts a death.
        sustained["supervisor_delivery"] = SustainedCohortFixture.delivery("b")
        assert declaration.day is not None
        interval = declaration.day.interval_seconds
        recordings = cast(dict[str, list[dict[str, object]]], sustained["recordings"])
        for entries in recordings.values():
            entries[0].update(segments=segments, durable_records=messages)
        checkpoints = interval // 3
        sustained["commits"] = {
            account: {"committed:reserved": 2, "committed:target_matched": checkpoints - 2}
            for account in _ACCOUNTS
        }
        sustained["reconciliations"] = {
            account: {"attempts": interval // 60, "matched": interval // 60, "max_seconds": 0.1}
            for account in _ACCOUNTS
        }
        latencies = cast(dict[str, object], sustained["latencies"])
        latencies["selected_book_to_checkpoint_by_account"] = {
            account: {
                "count": checkpoints,
                "p50_ns": 50 * _MS,
                "p95_ns": 60 * _MS,
                "p99_ns": 80 * _MS,
                "max_ns": 90 * _MS,
            }
            for account in _ACCOUNTS
        }
        observations = [item for item in observations if item.kind == "account_facts"]
        return summary, results, sustained, observations

    @staticmethod
    def failed(
        declaration: SustainedDeclaration,
        evidence: tuple[
            dict[str, object], dict[str, object], dict[str, object], list[_Observation]
        ],
    ) -> list[str]:
        """Return every failed day gate."""
        summary, results, sustained, observations = evidence
        gates = SustainedGates.phase(
            "day", summary, results, sustained, tuple(observations), declaration
        )
        return [gate.name for gate in gates if not gate.passed]


class TestDayDeclaration:
    """The counted day and its rehearsal keep the approved authority and shape."""

    def test_presets_fit_the_approved_cap_and_grant(self) -> None:
        """Owners outlive supervisors, which outlive whole-window intervals, inside 26 hours."""
        for declaration, workload in (
            (SustainedDeclaration.counted_day(), DayWorkload),
            (SustainedDeclaration.day_rehearsal(), DayRehearsalWorkload),
        ):
            day = declaration.day
            assert day is not None
            assert day.interval_seconds % 300 == 0
            assert day.interval_seconds < day.supervisor_seconds < day.service_seconds
            assert day.service_seconds <= workload.service_life_seconds == 90_000
            assert workload.grant_seconds == 26 * 3600
            assert day.service_seconds + 3600 <= workload.grant_seconds

    def test_fixtures_cover_each_declared_day(self) -> None:
        """The counted fixture supplies the profile's day and the rehearsal two hours."""
        assert DayNativeFixture.frame_count == 2_400_750
        assert 4 * DayNativeFixture.frame_count >= 9_504_000
        assert DayRehearsalFixture.frame_count == 214_500
        assert DayNativeFixture.elapsed_seconds(DayNativeFixture.frame_count - 1) > 87_000

    def test_counted_workload_declares_seven_day_telemetry(self) -> None:
        """The counted selection bounds its monitoring store at eight million events."""
        workload = DayWorkload(
            opening_at=datetime(2026, 10, 7, tzinfo=UTC), socket_root=Path("/private/tmp/s2b")
        )
        telemetry = workload.service_configuration().telemetry
        assert not isinstance(telemetry, msgspec.UnsetType)
        assert (telemetry.max_events, telemetry.retention_days) == (8_000_000, 7)


class TestDayDayGates:
    """Every day gate passes on complete evidence and names each defect."""

    def test_complete_day_passes(self) -> None:
        """A complete counted day passes every gate."""
        declaration = SustainedDeclaration.counted_day()
        assert DayFixture.failed(declaration, DayFixture.day(declaration)) == []

    @pytest.mark.parametrize(
        ("change", "gate"),
        (
            ("volume", "native_receipt_volume"),
            ("share", "native_receipt_volume"),
            ("percentile", "checkpoint_percentiles_per_account"),
            ("orders", "orders_within_daily_target"),
            ("segments", "segments_rolled_over"),
        ),
    )
    def test_each_day_defect_is_named(self, change: str, gate: str) -> None:
        """One authored defect fails exactly its gate."""
        declaration = SustainedDeclaration.counted_day()
        evidence = copy.deepcopy(DayFixture.day(declaration))
        sustained = evidence[2]
        recordings = cast(dict[str, list[dict[str, object]]], sustained["recordings"])
        if change == "volume":
            for entries in recordings.values():
                entries[0]["durable_records"] = 1_000_000
        elif change == "share":
            recordings["okx-btc-book"][0]["durable_records"] = 100_000
        elif change == "percentile":
            accounts = cast(
                dict[str, dict[str, object]],
                cast(dict[str, object], sustained["latencies"])[
                    "selected_book_to_checkpoint_by_account"
                ],
            )
            accounts["okx-shared"]["p99_ns"] = 2001 * _MS
        elif change == "orders":
            evidence[3][0] = _Observation(
                kind="account_facts",
                values={"label": "post_shutdown", "account": "okx-shared", "child_orders": 41},
            )
        else:
            recordings["okx-btc-book"][0]["segments"] = 47
        assert gate in DayFixture.failed(declaration, evidence)

    def test_a_fenced_prefix_verdict_fails_a_day(self) -> None:
        """The injected-death exception never applies to a day phase."""
        declaration = SustainedDeclaration.counted_day()
        summary, results, sustained, observations = DayFixture.day(declaration)
        sustained["supervisor_delivery"] = SustainedCohortFixture.delivery("a")
        assert DayFixture.failed(declaration, (summary, results, sustained, observations)) == [
            "supervisor_source_delivery_complete"
        ]

    def test_rehearsal_reports_checkpoint_percentiles_without_grading(self) -> None:
        """A rehearsal's percentiles are retained but never fail it."""
        declaration = SustainedDeclaration.day_rehearsal()
        evidence = DayFixture.day(declaration, messages=200_000, segments=5)
        accounts = cast(
            dict[str, dict[str, object]],
            cast(dict[str, object], evidence[2]["latencies"])[
                "selected_book_to_checkpoint_by_account"
            ],
        )
        accounts["okx-shared"]["p99_ns"] = 3000 * _MS
        assert DayFixture.failed(declaration, evidence) == []


class TestDayResources:
    """The resource gate grades the trial tree's peak RSS, mean and p95 cores."""

    @staticmethod
    def rows(cores: tuple[float, ...], rss: int) -> list[bytes]:
        """Author one-second sampler rows."""
        rows: list[bytes] = []
        for index, value in enumerate(cores):
            row: dict[str, object] = {
                "elapsed_seconds": 1.0,
                "trial_cores": value,
                "trial_rss_bytes": rss,
                "host_disk_written_bytes": index * 1000,
            }
            rows.append(msgspec.json.encode(row))
        return rows

    def test_within_and_beyond_each_limit(self) -> None:
        """Peak RSS, mean and p95 cores each fail independently."""
        gate = ResourceGate(24 * 1024**3, 7.0, 9.0)
        passed = gate.assess(self.rows((4.0,) * 100, 8 * 1024**3))
        assert passed["status"] == "pass" and passed["host_disk_written_bytes"] == 99_000
        assert gate.assess(self.rows((4.0,) * 100, 25 * 1024**3))["status"] == "fail"
        assert gate.assess(self.rows((8.0,) * 100, 1024**3))["status"] == "fail"
        bursty = tuple(1.0 if index < 90 else 10.0 for index in range(100))
        assert gate.assess(self.rows(bursty, 1024**3))["status"] == "fail"


class TestFixtureReceipts:
    """Streamed receipts round-trip, and an unclosed epoch is visible as unclosed."""

    def test_written_epoch_reads_back_in_order(self, tmp_path: Path) -> None:
        """Header, rows and footer survive without holding rows in memory."""
        path = tmp_path / "source.epoch-1-receipts.jsonl"
        rows = tuple((index, 1_000 + index, f"{index:064x}") for index in range(5))
        FixtureReceipts.write(
            path,
            fixture_identity="a" * 64,
            active_identity="b" * 64,
            epoch=1,
            anchor_ns=10,
            closed_ns=99,
            emitted=rows,
        )
        receipts = FixtureReceipts(path)
        assert (receipts.epoch, receipts.anchor_ns, receipts.closed_ns) == (1, 10, 99)
        assert receipts.active_identity == "b" * 64
        assert tuple(receipts.rows()) == rows
        path.write_bytes(path.read_bytes().rsplit(b"\n", 2)[0] + b"\n")
        assert FixtureReceipts(path).closed_ns is None


class TestDayRetention:
    """Retained files fall into the profile's occupied-space classes."""

    def test_occupied_space_classes(self) -> None:
        """Recordings are raw capture, delivery logs canonical, reads features and telemetry."""
        assert DayRetention._class(Path("operating/runs/r/src/key/key/journal.jsonl")) == (
            "raw_capture"
        )
        assert DayRetention._class(Path("operating/runs/r/src/key-okx-shared.jsonl")) == (
            "canonical"
        )
        assert DayRetention._class(Path("final-okx-shared.json")) == "canonical"
        assert DayRetention._class(Path("reads/samples.jsonl")) == "features_telemetry"
        assert DayRetention._class(Path("operating/monitoring/telemetry.sqlite3")) == (
            "features_telemetry"
        )
        assert DayRetention._class(Path("observations.jsonl")) == "scratch"

    def test_sibling_account_journals_are_reported_separately_and_ungraded(
        self, tmp_path: Path
    ) -> None:
        """Account state beside the day is its own class; the day's classes exclude it."""
        day = tmp_path / "candidate" / "day"
        (day / "reads").mkdir(parents=True)
        (day / "summary.json").write_bytes(b"{}")
        (day / "reads" / "samples.jsonl").write_bytes(b"x" * 10_000)
        for account, size in (("okx-shared", 20_000), ("bitfinex-isolated", 30_000)):
            state = tmp_path / "candidate" / f"target-{account}" / "state"
            (state / "service-requests").mkdir(parents=True)
            (state / "accounts.sqlite3").write_bytes(b"j" * size)
            (state / "service-requests" / "life.jsonl").write_bytes(b"{}\n")
        (tmp_path / "candidate" / "target-okx-shared" / "release.json").write_bytes(b"{}")
        retention = DayRetention(day, 72)
        journals = retention.account_journals()
        accounts = cast(dict[str, dict[str, int]], journals["accounts"])
        assert set(accounts) == {"okx-shared", "bitfinex-isolated"}
        assert {name: item["files"] for name, item in accounts.items()} == {
            "okx-shared": 2,
            "bitfinex-isolated": 2,
        }
        assert all(item["occupied_bytes"] > 0 for item in accounts.values())
        assert journals["occupied_bytes"] == sum(
            item["occupied_bytes"] for item in accounts.values()
        )
        assert journals["status"] == "reported_ungraded"
        occupied = cast(dict[str, int], retention.occupied()["occupied_bytes"])
        assert sum(occupied.values()) < 20_000
        # The economic replay's rebuilt journals sit beside the day: reported, ungraded.
        assert retention.replay_journals()["occupied_bytes"] == 0
        replays = tmp_path / "candidate" / "economic-replay-journals"
        replays.mkdir()
        (replays / "okx-shared.sqlite3").write_bytes(b"r" * 40_000)
        replayed = retention.replay_journals()
        assert (replayed["files"], replayed["status"]) == (1, "reported_ungraded")
        assert cast(int, replayed["occupied_bytes"]) >= 40_000
        regraded = cast(dict[str, int], retention.occupied()["occupied_bytes"])
        assert regraded == occupied
