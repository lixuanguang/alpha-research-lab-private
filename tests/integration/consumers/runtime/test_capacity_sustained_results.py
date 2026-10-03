"""Prove sustained results expose window tails, prove slots and count commits exactly."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_sustained import SustainedNativeFixture, SustainedWorkload
from capacity_sustained_results import RollingPercentiles, SustainedResults, WindowBudget

# project library imports
from configuration import CaptureRunConfig
from market_data.collection import CaptureSegmentWriter
from market_data.contracts import CaptureRecord, CaptureRunRequest
from market_data.storage import CaptureRunJournal

_MS = 1_000_000
_S = 1_000_000_000


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    """Retain JSON-lines evidence exactly as the probes do."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(msgspec.json.encode(row) + b"\n" for row in rows))


class TestRollingPercentiles:
    """Expose a late tail that whole-interval percentiles average away."""

    def test_a_late_window_fails_while_the_whole_interval_passes(self) -> None:
        """Twenty slow samples in one 300-second window fail it; the whole p95 stays low."""
        samples = [
            (window * 300 * _S + index * _S, 500 * _MS if window == 7 and index < 20 else 10 * _MS)
            for window in range(10)
            for index in range(100)
        ]
        result = RollingPercentiles.summarize(
            samples,
            start_ns=0,
            end_ns=3000 * _S,
            window_ns=300 * _S,
            budget=WindowBudget(p50_ns=20 * _MS, p95_ns=50 * _MS, p99_ns=1000 * _MS, minimum=50),
        )
        assert result["p95_ns"] == 10 * _MS and result["status"] == "fail"
        windows = cast(list[dict[str, object]], result["windows"])
        assert [window["status"] for window in windows].count("fail") == 1
        assert windows[7]["p95_ns"] == 500 * _MS

    def test_sparse_windows_are_unmeasured_never_passed(self) -> None:
        """A window below its minimum population cannot pass the class."""
        result = RollingPercentiles.summarize(
            [(0, _MS)],
            start_ns=0,
            end_ns=600 * _S,
            window_ns=300 * _S,
            budget=WindowBudget(p50_ns=10 * _MS, p95_ns=10 * _MS, p99_ns=10 * _MS, minimum=1),
        )
        assert result["status"] == "unmeasured"
        with pytest.raises(ValueError):
            RollingPercentiles.summarize([], start_ns=1, end_ns=1, window_ns=1)


def _phase(tmp_path: Path, *, slots: int, drop: int | None = None, late: int | None = None) -> Path:
    """Author one sustained phase: a real chain, its fixture trace, probes and reads."""
    trial = tmp_path / "phase"
    workload = SustainedWorkload(
        opening_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
        socket_root=Path("/private/tmp/capacity-sustained-results"),
    )
    source = workload.service_configuration().sources[0]
    fixture = SustainedNativeFixture(source)
    anchor = 10 * _S
    frames: list[tuple[int, int, bytes]] = []
    for index in range(slots):
        fixture.index = index + 1
        received = anchor + SustainedNativeFixture.slot_ns(index) + _MS
        if index == late:
            received += 3 * _S
        frames.append((index, received, fixture._native_frame(1_700_000_000_000 + index)))
    now = datetime.now(UTC)
    request = CaptureRunRequest(
        config=source.capture,
        window=CaptureRunConfig(
            start_at=now - timedelta(seconds=1),
            ready_by=now,
            stop_at=now + timedelta(hours=1),
            max_messages=100_000,
            max_bytes=1024**3,
            max_segments=4,
            max_reconnects=1,
        ),
        run_id="00000000-0000-4000-8000-0000000005a5",
        implementation_identity="a" * 64,
    )
    source_root = trial / "operating/runs/run" / source.name
    run = CaptureRunJournal(source_root / request.run_id / request.run_id, request)
    run.open(resume=False)
    try:
        writer = CaptureSegmentWriter(
            run, run.start_segment(None), previous_bytes=0, previous_records=0
        )
        asyncio.run(writer.append(CaptureRecord(kind="session", epoch=0, received_ns=1)))
        for index, received, raw in frames:
            asyncio.run(
                writer.append(CaptureRecord(kind="frame", epoch=0, received_ns=received, raw=raw))
            )
        asyncio.run(
            writer.append(
                CaptureRecord(kind="end", epoch=0, received_ns=frames[-1][1], reason="duration")
            )
        )
        run.sealed(writer.current, writer.first_received_ns or 1)
        run.finish({"run_identity": request.identity})
    finally:
        run.close()
    result: dict[str, object] = {"replay_parity": True, "stop_reason": "duration_limit"}
    (source_root / request.run_id / "source-result.json").write_bytes(msgspec.json.encode(result))
    emitted = [
        (index, received, hashlib.sha256(raw).hexdigest())
        for index, received, raw in frames
        if index != drop
    ]
    receipts: dict[str, object] = {
        "fixture_identity": fixture.identity,
        "active_identity": fixture.identity,
        "epoch": 1,
        "anchor_ns": anchor,
        "closed_ns": frames[-1][1] + _S,
        "emitted": emitted,
    }
    (trial / "fixture-epochs").mkdir(parents=True)
    (trial / f"fixture-epochs/{source.name}.epoch-1-receipts.json").write_bytes(
        msgspec.json.encode(receipts)
    )
    # The interval closes just after the last authored receipt and its durable clock.
    start, stop = anchor, anchor + SustainedNativeFixture.slot_ns(slots - 1) + 10 * _MS
    (trial / "reads").mkdir(parents=True)
    interval: dict[str, object] = {
        "started_monotonic_ns": start,
        "scheduled_stop_monotonic_ns": stop,
    }
    (trial / "reads/summary.json").write_bytes(msgspec.json.encode(interval))
    key = request.run_id
    _write(
        trial / f"measurements/run/{source.name}/{key}.capture.jsonl",
        [
            {
                "schema_version": "runtime-measurement",
                "kind": "capture_boundary",
                "cursor": position + 2,
                "receipt_ns": received,
                "durable_ns": received + _MS,
                "receipt_to_durable_ns": _MS,
            }
            for position, (_, received, _) in enumerate(frames)
        ],
    )
    _write(
        trial / f"measurements/run/{source.name}/{key}.okx-shared.paper.jsonl",
        [
            {
                "schema_version": "runtime-measurement",
                "kind": "paper_book",
                "position": position + 1,
                "policy_selected": position % 75 == 0,
                "checkpoint_acknowledged": position % 75 == 0,
                "checkpoint_status": "committed",
                "checkpoint_reason": "reserved" if position == 0 else "target_matched",
                "book_started_ns": received + 2 * _MS,
                "bbo_observed_ns": received + 3 * _MS,
                "book_to_checkpoint_ns": 40 * _MS if position % 75 == 0 else None,
            }
            for position, (_, received, _) in enumerate(frames)
        ],
    )
    _write(
        trial / "observations.jsonl",
        [
            {
                "kind": "account_reconciled",
                "values": {"account": "okx-shared", "matched": True, "seconds": 0.02},
            },
            {
                "kind": "account_reconciled",
                "values": {"account": "okx-shared", "matched": True, "seconds": 0.03},
            },
        ],
    )
    return trial


class TestSustainedResults:
    """Join a phase's chain, fixture trace, probes and observations exactly."""

    def test_complete_phase_proves_slots_and_counts_commits(self, tmp_path: Path) -> None:
        """Every emitted slot is retained in order and on time across the recording."""
        trial = _phase(tmp_path, slots=600)
        results = SustainedResults(
            trial,
            budgets={
                "receipt_to_durable": WindowBudget(
                    p50_ns=50 * _MS, p95_ns=250 * _MS, p99_ns=1000 * _MS, minimum=100
                )
            },
        ).collect()
        proofs = cast(dict[str, dict[str, object]], results["fixture_proofs"])
        (proof,) = proofs.values()
        assert proof["status"] == "pass" and proof["required_slots"] == 600
        assert proof["exact_bytes_in_order"] is True
        latencies = cast(dict[str, dict[str, dict[str, object]]], results["latencies"])
        (receipt,) = latencies["receipt_to_durable"].values()
        assert receipt["status"] == "pass" and receipt["count"] == 600
        assert latencies["durable_to_bbo"]["okx-shared"]["count"] == 600
        assert results["commits"] == {
            "okx-shared": {"committed:reserved": 1, "committed:target_matched": 7}
        }
        assert results["reconciliations"] == {
            "okx-shared": {"attempts": 2, "matched": 2, "max_seconds": 0.03}
        }
        recordings = cast(dict[str, list[dict[str, object]]], results["recordings"])
        (entries,) = recordings.values()
        assert entries[0]["completed"] is True and entries[0]["replay_parity"] is True

    @pytest.mark.parametrize(("drop", "late"), ((17, None), (None, 23)))
    def test_a_missing_or_late_slot_fails_the_proof(
        self, tmp_path: Path, drop: int | None, late: int | None
    ) -> None:
        """An unemitted slot or one retained beyond two seconds is never a complete input."""
        trial = _phase(tmp_path, slots=100, drop=drop, late=late)
        (proof,) = cast(
            dict[str, dict[str, object]], SustainedResults(trial).collect()["fixture_proofs"]
        ).values()
        assert proof["status"] == "fail"
        if drop is not None:
            assert proof["missing_required_slots"] == 1
        else:
            assert proof["late_required_slots"] == 1


def test_slot_clock_matches_the_declared_schedule() -> None:
    """Integer slot offsets equal the schedule's own clock at every period boundary."""
    for index in (0, 1, 7249, 7250, 8249, 8250, 82_499):
        assert SustainedNativeFixture.slot_ns(index) == round(
            SustainedNativeFixture.elapsed_seconds(index) * _S
        )
