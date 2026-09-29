"""Keep stage-1 summaries causal, source-scoped and sample-count qualified."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch
from uuid import uuid4

# third party library imports
import pytest
from capacity_inputs import CapacityWorkload
from capacity_results import CapacityResultsCollector, _LatencySeries

# project library imports
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.storage import CaptureJournal
from serialization import DomainCodec


class TestCapacityResults:
    """Verify that retained probe evidence cannot inflate a latency claim."""

    def test_nearest_rank_requires_one_thousand_in_one_group(self) -> None:
        """Leave sparse groups unmeasured and count an adverse p99 without interpolation."""
        series = _LatencySeries((50, 250, 1000))
        for _ in range(999):
            series.add(10_000_000)
        assert series.summarize()["status"] == "unmeasured"
        series.add(1_100_000_000)
        summary = series.summarize()
        assert summary["p99_ns"] == 10_000_000
        assert summary["maximum_ns"] == 1_100_000_000
        assert summary["status"] == "pass"
        for _ in range(11):
            series.add(1_100_000_000)
        assert series.summarize()["status"] == "fail"

    def test_exact_fixture_schedule_rejects_missing_or_changed_native_bytes(
        self, tmp_path: Path
    ) -> None:
        """Require the whole declared burst and every emitted frame, including the tail."""
        source = (
            CapacityWorkload(
                opening_at=datetime(2026, 9, 27, tzinfo=UTC),
                socket_root=Path("/private/tmp/capacity-schedule-test"),
            )
            .service_configuration()
            .sources[0]
        )
        request = CaptureRequest(
            config=source.capture,
            recording_id=str(uuid4()),
            implementation_identity="a" * 64,
        )
        trace_root = tmp_path / "fixture-epochs"
        trace_root.mkdir()
        reads = tmp_path / "reads"
        reads.mkdir()
        anchor = 10_000_000_000
        codec = DomainCodec()
        (reads / "summary.json").write_bytes(
            codec.encode_json(
                {
                    "steady_duration_seconds": 60,
                    "started_monotonic_ns": anchor + 1_000_000_000,
                    "steady_ended_monotonic_ns": anchor + 61_000_000_000,
                }
            )
        )
        records = tuple(
            CaptureRecord(
                kind="frame", epoch=0, received_ns=anchor + index, raw=str(index).encode()
            )
            for index in range(2300)
        )
        trace = {
            "fixture_identity": "b" * 64,
            "active_identity": "b" * 64,
            "epoch": 1,
            "anchor_ns": anchor,
            "closed_ns": anchor + 62_000_000_000,
            "emitted": tuple(
                (
                    index,
                    anchor + CapacityResultsCollector._authored_slot_ns(index),
                    hashlib.sha256(record.raw).hexdigest(),
                )
                for index, record in enumerate(records)
            ),
        }
        (trace_root / f"{source.name}.epoch-1-receipts.json").write_bytes(codec.encode_json(trace))
        collector = CapacityResultsCollector(tmp_path / "operating", tmp_path, reads)
        with patch.object(CaptureJournal, "records", return_value=iter(records)):
            result = collector._fixture_schedule(source.name, tmp_path, request)
        assert result["status"] == "pass"
        assert result["complete_declared_burst_in_steady_interval"] is True
        with patch.object(CaptureJournal, "records", return_value=iter(records[:-1])):
            result = collector._fixture_schedule(source.name, tmp_path, request)
        assert result["status"] == "fail"
        assert result["exact_native_bytes"] is False
        changed = (
            *records[:-1],
            CaptureRecord(kind="frame", epoch=0, received_ns=anchor, raw=b"x"),
        )
        with patch.object(CaptureJournal, "records", return_value=iter(changed)):
            result = collector._fixture_schedule(source.name, tmp_path, request)
        assert result["status"] == "fail"

    def test_actual_receipts_expose_burst_shortfall_without_a_false_pass(self) -> None:
        """Count observed socket receipts against each fixed authored phase."""
        anchor = 1_000_000_000_000
        receipts = tuple(
            anchor + CapacityResultsCollector._authored_slot_ns(index) for index in range(1000)
        ) + tuple(
            anchor + CapacityResultsCollector._authored_slot_ns(index)
            for index in range(1000, 1500)
        )
        profile = CapacityResultsCollector._arrival_facts(
            receipts,
            (anchor + 40_000_000_000, anchor + 45_000_000_000),
        )
        assert profile["status"] == "observed_not_qualified"
        assert profile["observed_receipts_by_anchored_phase"] == (1000, 500, 0)
        assert profile["authored_due_slots_by_anchored_phase"] == (1000, 500, 0)
        steady = cast(dict[str, object], profile["steady_window"])
        assert steady["observed_receipts"] == 500
        assert steady["authored_due_slots_from_first_receipt_proxy"] == 500
        missing = CapacityResultsCollector._arrival_facts(
            receipts[:-50], (anchor + 40_000_000_000, anchor + 45_000_000_000)
        )
        missing_window = cast(dict[str, object], missing["steady_window"])
        assert missing_window["observed_receipts"] == 450
        assert missing_window["apparent_shortfall"] == 50
        live = CapacityResultsCollector._arrival_facts(
            receipts[:100],
            (anchor, anchor + 5_000_000_000),
            origin="live_public",
        )
        live_window = cast(dict[str, object], live["steady_window"])
        assert live["status"] == "observed_live_public_no_authored_schedule"
        assert live_window["observed_receipts"] == 100
        assert "authored_due_slots_from_first_receipt_proxy" not in live_window
        assert "apparent_shortfall" not in live_window

    @staticmethod
    def _write_rows(path: Path, rows: tuple[dict[str, object], ...]) -> None:
        """Retain complete versioned opt-in probe lines for a bounded fixture."""
        codec = DomainCodec()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(codec.encode_json(row) + b"\n" for row in rows))

    def test_probe_join_preserves_source_account_and_queue_age(self, tmp_path: Path) -> None:
        """Join eligible BBO to the same durable cursor and keep checkpoint flags."""
        root = tmp_path / "probes"
        capture_path = root / "recording.capture.jsonl"
        paper_path = root / "recording.account.paper.jsonl"
        receipt = 1_000_000_000
        durable = receipt + 10_000_000
        capture = {
            "schema_version": "runtime-measurement",
            "kind": "capture_boundary",
            "cursor": 3,
            "record_kind": "frame",
            "outcome": "snapshot",
            "raw_bytes": 512,
            "receipt_ns": receipt,
            "append_started_ns": receipt + 1_000_000,
            "durable_ns": durable,
            "reconstructed_ns": durable + 2_000_000,
            "receipt_to_durable_ns": 10_000_000,
            "append_to_durable_ns": 9_000_000,
            "record_fsync_ns": 2_000_000,
            "cursor_checkpoint_ns": 3_000_000,
            "durable_to_reconstructed_ns": 2_000_000,
        }
        queue = {
            "schema_version": "runtime-measurement",
            "kind": "queue",
            "phase": "durable_ready",
            "at_ns": durable,
            "pending_records": 5,
            "in_flight_records": 1,
            "queued_bytes": 1024,
            "oldest_age_ns": 1_900_000_000,
        }
        self._write_rows(capture_path, (capture, queue))
        paper = {
            "schema_version": "runtime-measurement",
            "kind": "paper_book",
            "position": 2,
            "outcome": "snapshot",
            "market_eligible": True,
            "market_selected": True,
            "policy_selected": True,
            "checkpoint_acknowledged": True,
            "checkpoint_status": "committed",
            "book_started_ns": durable + 1_000_000,
            "bbo_observed_ns": durable + 15_000_000,
            "checkpoint_acknowledged_ns": durable + 201_000_000,
            "book_to_checkpoint_ns": 200_000_000,
        }
        self._write_rows(paper_path, (paper,))
        collector = CapacityResultsCollector(tmp_path, root)
        source_summary, cursors = collector._capture_probe(capture_path)
        account_summary = collector._paper_probe(paper_path, cursors)
        queue_summary = cast(dict[str, object], source_summary["queue"])
        receipt_summary = cast(dict[str, object], source_summary["receipt_to_durable"])
        bbo_summary = cast(dict[str, object], account_summary["durable_to_bbo"])
        checkpoint_summary = cast(dict[str, object], account_summary["selected_book_to_checkpoint"])
        assert queue_summary["status"] == "pass"
        assert queue_summary["oldest_age_peak_ns"] == 1_900_000_000
        assert receipt_summary["status"] == "unmeasured"
        assert account_summary["market_eligible"] == 1
        assert account_summary["policy_selected"] == 1
        assert account_summary["checkpoint_acknowledged"] == 1
        assert bbo_summary["count"] == 1
        assert checkpoint_summary["count"] == 1
        paper["book_started_ns"] = durable - 1_000_000
        paper["bbo_observed_ns"] = durable - 1
        paper["book_to_checkpoint_ns"] = 202_000_000
        self._write_rows(paper_path, (paper,))
        with pytest.raises(ValueError, match="causal capture boundary"):
            collector._paper_probe(paper_path, cursors)

    def test_historical_reader_trace_without_clocks_remains_unqualified(
        self, tmp_path: Path
    ) -> None:
        """Keep old successful durations without inventing timed request completions."""
        read_root = tmp_path / "reads"
        read_root.mkdir()
        (read_root / "summary.json").write_bytes(
            DomainCodec().encode_json({"steady_duration_seconds": 60})
        )
        rows: tuple[dict[str, object], ...] = tuple(
            {
                "boundary": boundary,
                "target": f"{boundary}-{reader}",
                "phase": "steady",
                "seconds": 0.01,
                "status": "ok",
            }
            for boundary in ("depth_bbo", "dashboard")
            for reader in range(4)
            for _ in range(300)
        )
        self._write_rows(read_root / "samples.jsonl", rows)
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        per_target = cast(dict[str, dict[str, dict[str, object]]], result["per_target"])
        assert workload["depth_bbo"]["status"] == "unmeasured"
        assert workload["depth_bbo"]["schedule_status"] == "unmeasured"
        retained = cast(dict[str, object], workload["dashboard"]["all_retained_successful_reads"])
        assert retained["count"] == 1200
        assert all(group["status"] == "unmeasured" for group in per_target["depth_bbo"].values())

    @staticmethod
    def _write_query_interval(root: Path) -> None:
        """Declare the shared actual sixty-second measurement and request deadline."""
        root.mkdir()
        (root / "summary.json").write_bytes(
            DomainCodec().encode_json(
                {
                    "steady_duration_seconds": 60,
                    "started_monotonic_ns": 1_000_000_000,
                    "scheduled_stop_monotonic_ns": 61_000_000_000,
                    "steady_ended_monotonic_ns": 61_010_000_000,
                }
            )
        )

    @staticmethod
    def _query_rows() -> tuple[dict[str, object], ...]:
        """Supply actual request clocks for every slot of each of the eight readers."""
        return tuple(
            {
                "boundary": boundary,
                "target": f"{boundary}-{reader}",
                "reader_id": f"{boundary}-{reader}",
                "phase": "steady",
                "request_index": slot,
                "slot": slot,
                "scheduled_monotonic_ns": 1_000_000_000 + slot * 200_000_000,
                "started_monotonic_ns": 1_000_000_000 + slot * 200_000_000 + reader * 1000,
                "completed_monotonic_ns": 1_010_000_000 + slot * 200_000_000 + reader * 1000,
                "seconds": 0.01,
                "status": "ok",
            }
            for boundary in ("depth_bbo", "dashboard")
            for reader in range(4)
            for slot in range(300)
        )

    def test_pooled_four_reader_workload_requires_actual_completed_slots(
        self, tmp_path: Path
    ) -> None:
        """Qualify 1,200 completions while leaving each 300-sample percentile unmeasured."""
        read_root = tmp_path / "reads"
        self._write_query_interval(read_root)
        self._write_rows(read_root / "samples.jsonl", self._query_rows())
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        per_target = cast(dict[str, dict[str, dict[str, object]]], result["per_target"])
        assert workload["depth_bbo"]["status"] == "pass"
        assert workload["depth_bbo"]["schedule_status"] == "pass"
        assert workload["dashboard"]["count"] == 1200
        service = cast(dict[str, object], workload["depth_bbo"]["service_latency"])
        response = cast(dict[str, object], workload["depth_bbo"]["response_latency"])
        queue = cast(dict[str, object], workload["depth_bbo"]["queue_delay"])
        assert service["status"] == response["status"] == "pass"
        assert service["count"] == response["count"] == queue["count"] == 1200
        assert queue["status"] == "measured_no_predeclared_budget"
        assert all(group["status"] == "unmeasured" for group in per_target["depth_bbo"].values())
        assert all(group["schedule_status"] == "pass" for group in per_target["depth_bbo"].values())
        assert all(
            cast(dict[str, object], group["response_latency"])["status"] == "unmeasured"
            and cast(dict[str, object], group["queue_delay"])["status"] == "unmeasured"
            for group in per_target["depth_bbo"].values()
        )

    def test_late_catch_up_cannot_hide_scheduled_response_latency(self, tmp_path: Path) -> None:
        """Refuse slow due-to-completion responses despite fast service and complete slots."""
        read_root = tmp_path / "reads"
        self._write_query_interval(read_root)
        rows = self._query_rows()
        for row in rows:
            slot = cast(int, row["slot"])
            queue_ns = (
                2_000_000_000 if slot < 250 else max(0, 2_000_000_000 - (slot - 250) * 190_000_000)
            )
            began = cast(int, row["scheduled_monotonic_ns"]) + queue_ns
            row["started_monotonic_ns"] = began
            row["completed_monotonic_ns"] = began + 10_000_000
        self._write_rows(read_root / "samples.jsonl", rows)
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        service = cast(dict[str, object], workload["depth_bbo"]["service_latency"])
        response = cast(dict[str, object], workload["depth_bbo"]["response_latency"])
        queue = cast(dict[str, object], workload["depth_bbo"]["queue_delay"])
        assert workload["depth_bbo"]["schedule_status"] == "pass"
        assert workload["depth_bbo"]["count"] == 1200
        assert service["status"] == "pass"
        assert response["status"] == workload["depth_bbo"]["status"] == "fail"
        assert response["p50_ns"] == 2_010_000_000
        assert queue["p50_ns"] == 2_000_000_000

    def test_failed_requests_cannot_complete_the_reader_workload(self, tmp_path: Path) -> None:
        """Preserve 1,000 successful samples while refusing 200 failed scheduled requests."""
        read_root = tmp_path / "reads"
        self._write_query_interval(read_root)
        rows = self._query_rows()
        for row in rows:
            if cast(int, row["slot"]) >= 250:
                row["status"] = "failed"
        self._write_rows(read_root / "samples.jsonl", rows)
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        assert workload["depth_bbo"]["count"] == 1000
        assert workload["depth_bbo"]["schedule_status"] == "fail"
        assert workload["depth_bbo"]["status"] == "unmeasured"

    @pytest.mark.parametrize("defect", ("duplicate_slot", "late_completion", "missed_slot"))
    def test_reader_identity_and_completion_deadline_are_required(
        self, tmp_path: Path, defect: str
    ) -> None:
        """Reject duplicate, missed or post-deadline requests without discarding their trace."""
        read_root = tmp_path / "reads"
        self._write_query_interval(read_root)
        rows = self._query_rows()
        for row in rows:
            if row["slot"] != 299:
                continue
            if defect == "duplicate_slot":
                row["slot"] = row["request_index"] = 298
                row["scheduled_monotonic_ns"] = 60_600_000_000
            elif defect == "late_completion":
                row["seconds"] = 0.3
                row["completed_monotonic_ns"] = cast(int, row["started_monotonic_ns"]) + 300_000_000
            else:
                row["status"] = "missed"
                row["seconds"] = 0
                row["started_monotonic_ns"] = row["completed_monotonic_ns"] = None
        self._write_rows(read_root / "samples.jsonl", rows)
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        assert workload["depth_bbo"]["schedule_status"] == "fail"
        assert workload["depth_bbo"]["status"] != "pass"
        assert workload["depth_bbo"]["count"] == 1196

    def test_declared_duration_cannot_replace_an_actual_sixty_second_interval(
        self, tmp_path: Path
    ) -> None:
        """Refuse a truncated actual interval even when all retained requests are successful."""
        read_root = tmp_path / "reads"
        self._write_query_interval(read_root)
        (read_root / "summary.json").write_bytes(
            DomainCodec().encode_json(
                {
                    "steady_duration_seconds": 60,
                    "started_monotonic_ns": 1_000_000_000,
                    "scheduled_stop_monotonic_ns": 61_000_000_000,
                    "steady_ended_monotonic_ns": 60_000_000_000,
                }
            )
        )
        self._write_rows(read_root / "samples.jsonl", self._query_rows())
        result = CapacityResultsCollector(tmp_path, tmp_path, read_root)._reads()
        workload = cast(dict[str, dict[str, object]], result["four_reader_workload"])
        assert workload["depth_bbo"]["schedule_status"] == "unmeasured"
        assert workload["depth_bbo"]["status"] == "unmeasured"

    @staticmethod
    def _boundary_rows(
        receipts: tuple[int, ...],
    ) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
        """Create paired native-boundary witnesses at exact causal monotonic clocks."""
        captures: list[dict[str, object]] = []
        books: list[dict[str, object]] = []
        for position, receipt in enumerate(receipts):
            durable = receipt + 10_000
            captures.append(
                {
                    "schema_version": "runtime-measurement",
                    "kind": "capture_boundary",
                    "cursor": position + 1,
                    "record_kind": "frame",
                    "outcome": "update",
                    "raw_bytes": 100,
                    "receipt_ns": receipt,
                    "append_started_ns": receipt + 1000,
                    "durable_ns": durable,
                    "reconstructed_ns": durable + 1000,
                    "receipt_to_durable_ns": 10_000,
                    "append_to_durable_ns": 9000,
                    "record_fsync_ns": 1000,
                    "cursor_checkpoint_ns": 1000,
                    "durable_to_reconstructed_ns": 1000,
                }
            )
            books.append(
                {
                    "schema_version": "runtime-measurement",
                    "kind": "paper_book",
                    "position": position,
                    "outcome": "update",
                    "market_eligible": True,
                    "market_selected": False,
                    "policy_selected": False,
                    "checkpoint_acknowledged": False,
                    "checkpoint_status": None,
                    "book_started_ns": durable + 1000,
                    "bbo_observed_ns": durable + 10_000,
                    "checkpoint_acknowledged_ns": None,
                    "book_to_checkpoint_ns": None,
                }
            )
        return tuple(captures), tuple(books)

    def test_recording_sample_count_cannot_qualify_a_sparse_steady_cohort(
        self, tmp_path: Path
    ) -> None:
        """Keep startup samples while requiring 1,000 observations inside the steady cohort."""
        captures, books = self._boundary_rows(
            tuple(100_000_000 + index * 100_000 for index in range(1000))
            + tuple(1_000_000_000 + index * 1_000_000 for index in range(999))
        )
        capture_path, book_path = tmp_path / "capture.jsonl", tmp_path / "book.jsonl"
        self._write_rows(capture_path, captures)
        self._write_rows(book_path, books)
        collector = CapacityResultsCollector(tmp_path, tmp_path)
        window = (1_000_000_000, 61_000_000_000)
        source, cursors = collector._capture_probe(capture_path, window)
        paper = collector._paper_probe(book_path, cursors, window)
        full_receipt = cast(dict[str, object], source["receipt_to_durable"])
        steady_receipt = cast(dict[str, object], source["steady_receipt_to_durable"])
        full_bbo = cast(dict[str, object], paper["durable_to_bbo"])
        steady_bbo = cast(dict[str, object], paper["steady_durable_to_bbo"])
        assert full_receipt["status"] == full_bbo["status"] == "pass"
        assert steady_receipt["count"] == steady_bbo["count"] == 999
        assert steady_receipt["status"] == steady_bbo["status"] == "unmeasured"
        assert paper["complete_position_prefix"] is True

    def test_ineligible_native_revision_remains_in_the_steady_bbo_population(
        self, tmp_path: Path
    ) -> None:
        """Refuse BBO qualification after an ineligible update while retaining its delay."""
        captures, books = self._boundary_rows(
            tuple(1_000_000_000 + index * 1_000_000 for index in range(1000))
        )
        books[-1]["market_eligible"] = False
        capture_path, book_path = tmp_path / "capture.jsonl", tmp_path / "book.jsonl"
        self._write_rows(capture_path, captures)
        self._write_rows(book_path, books)
        collector = CapacityResultsCollector(tmp_path, tmp_path)
        window = (1_000_000_000, 61_000_000_000)
        _, cursors = collector._capture_probe(capture_path, window)
        paper = collector._paper_probe(book_path, cursors, window)
        steady_bbo = cast(dict[str, object], paper["steady_durable_to_bbo"])
        assert steady_bbo["count"] == 1000
        assert steady_bbo["latency_budget_status"] == "pass"
        assert steady_bbo["status"] == "fail"
        assert paper["steady_ineligible_native_books"] == 1

    def test_duplicate_paper_positions_cannot_substitute_for_missing_deliveries(
        self, tmp_path: Path
    ) -> None:
        """Reject a repeated fast position before it can inflate a boundary population."""
        captures, books = self._boundary_rows((1_000_000_000,))
        capture_path, book_path = tmp_path / "capture.jsonl", tmp_path / "book.jsonl"
        self._write_rows(capture_path, captures)
        self._write_rows(book_path, (books[0], books[0]))
        collector = CapacityResultsCollector(tmp_path, tmp_path)
        _, cursors = collector._capture_probe(capture_path)
        with pytest.raises(ValueError, match="invalid paper-book measurement"):
            collector._paper_probe(book_path, cursors)
