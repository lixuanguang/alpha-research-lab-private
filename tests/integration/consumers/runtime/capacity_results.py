"""Collect per-source bounded runtime capacity facts without widening their claims."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

# third party library imports
import msgspec

# project library imports
from configuration import PaperServiceConfiguration
from market_data.adapters.sources import BookAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureCursor, CaptureRequest
from market_data.storage import CaptureJournal
from runtime import SharedBookDelivery
from serialization import DomainCodec


class _ServiceRun(msgspec.Struct, frozen=True):
    """Select the current run from a replaceable service liveness view."""

    run_id: str


class _ReadRun(msgspec.Struct, frozen=True):
    """Read the declared length of the independent four-reader interval."""

    steady_duration_seconds: int
    started_at_utc: str | None = None
    steady_ended_at_utc: str | None = None
    started_monotonic_ns: int | None = None
    steady_ended_monotonic_ns: int | None = None


class _FixtureReceipts(msgspec.Struct, frozen=True):
    """Bind authored slots to emitted native bytes and the actual first-open clock."""

    fixture_identity: str
    active_identity: str
    epoch: int
    anchor_ns: int
    closed_ns: int
    emitted: tuple[tuple[int, int, str], ...]


class _TrialContext(msgspec.Struct, frozen=True):
    """Bind each recording to a fixture or observed public transport."""

    public_venue: str | None
    variant: str


class _MeasurementKind(msgspec.Struct, frozen=True):
    """Select a stable opt-in probe schema before decoding its typed row."""

    schema_version: str
    kind: str


class _CaptureBoundary(msgspec.Struct, frozen=True):
    """Describe one received native message through its durable and derived clocks."""

    schema_version: str
    kind: str
    cursor: int
    record_kind: str
    outcome: str
    raw_bytes: int
    receipt_ns: int
    append_started_ns: int
    durable_ns: int
    reconstructed_ns: int
    receipt_to_durable_ns: int
    append_to_durable_ns: int
    record_fsync_ns: int
    cursor_checkpoint_ns: int
    durable_to_reconstructed_ns: int


class _QueueObservation(msgspec.Struct, frozen=True):
    """Describe actual outstanding capture work at a queue transition."""

    schema_version: str
    kind: str
    phase: str
    at_ns: int
    pending_records: int
    in_flight_records: int
    queued_bytes: int
    oldest_age_ns: int


class _PaperBook(msgspec.Struct, frozen=True):
    """Describe one selected account's native book and checkpoint observation."""

    schema_version: str
    kind: str
    position: int
    outcome: str
    market_eligible: bool
    market_selected: bool
    policy_selected: bool
    checkpoint_acknowledged: bool
    checkpoint_status: str | None
    book_started_ns: int
    bbo_observed_ns: int
    checkpoint_acknowledged_ns: int | None
    book_to_checkpoint_ns: int | None


class _ReadSample(msgspec.Struct, frozen=True):
    """Select one successful or failed read from the individual observer trace."""

    boundary: str
    target: str
    phase: str
    seconds: float
    status: str


class _LatencySeries:
    """Keep individual nanosecond durations and gate only qualified percentiles."""

    def __init__(self, budgets_ms: tuple[int, int, int] | None) -> None:
        """Bind the predeclared p50/p95/p99 targets, if this boundary has them."""
        self.budgets_ms = budgets_ms
        self.values_ns: list[int] = []

    def add(self, value_ns: int) -> None:
        """Retain a nonnegative actual monotonic duration without clipping failures."""
        if type(value_ns) is not int or value_ns < 0:
            raise ValueError("capacity duration must be a nonnegative integer nanosecond value")
        self.values_ns.append(value_ns)

    def summarize(self) -> dict[str, object]:
        """Use empirical nearest rank only after 1,000 observations in this group."""
        ordered = sorted(self.values_ns)
        result: dict[str, object] = {
            "count": len(ordered),
            "minimum_ns": ordered[0] if ordered else None,
            "maximum_ns": ordered[-1] if ordered else None,
            "budget_ms": self.budgets_ms,
            "percentile_method": "empirical_nearest_rank",
        }
        if len(ordered) < 1000:
            result["status"] = "unmeasured"
            result["reason"] = "fewer_than_1000_samples_in_this_group"
            return result
        ranks = tuple(
            ordered[math.ceil(portion * len(ordered)) - 1] for portion in (0.5, 0.95, 0.99)
        )
        result.update(zip(("p50_ns", "p95_ns", "p99_ns"), ranks, strict=True))
        if self.budgets_ms is None:
            result["status"] = "measured_no_predeclared_budget"
        else:
            result["status"] = (
                "pass"
                if all(value <= limit * 1_000_000 for value, limit in zip(ranks, self.budgets_ms))
                else "fail"
            )
        return result


class CapacityResultsCollector:
    """Join actual signed-service captures, opt-in probes and concurrent read evidence."""

    def __init__(
        self,
        service_root: Path,
        measurement_root: Path,
        read_root: Path | None = None,
    ) -> None:
        """Bind existing evidence roots; collection never starts a service or mutates inputs."""
        self.service_root = service_root
        self.measurement_root = measurement_root
        self.read_root = read_root
        self.codec = DomainCodec()

    @staticmethod
    def _read_lines(path: Path) -> tuple[bytes, ...]:
        """Reject a partial terminal JSONL row instead of silently dropping it."""
        if not path.is_file():
            return ()
        payload = path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            raise ValueError(f"incomplete capacity measurement row: {path}")
        return tuple(payload.splitlines())

    def _capture_probe(self, path: Path) -> tuple[dict[str, object], dict[int, _CaptureBoundary]]:
        """Summarize one source's unpooled receipt, fsync, cursor and queue trace."""
        receipt = _LatencySeries((50, 250, 1000))
        append = _LatencySeries(None)
        fsync = _LatencySeries(None)
        checkpoint = _LatencySeries(None)
        reconstruction = _LatencySeries(None)
        cursors: dict[int, _CaptureBoundary] = {}
        queue_count = 0
        queue_peak = 0
        queue_bytes_peak = 0
        queue_age_peak_ns = 0
        for line in self._read_lines(path):
            kind = msgspec.json.decode(line, type=_MeasurementKind)
            if kind.schema_version != "runtime-measurement-v1":
                raise ValueError(f"unsupported capacity measurement schema: {path}")
            if kind.kind == "capture_boundary":
                row = msgspec.json.decode(line, type=_CaptureBoundary)
                if (
                    row.cursor <= 0
                    or row.record_kind not in ("frame", "snapshot")
                    or row.cursor in cursors
                    or row.raw_bytes < 0
                    or not row.receipt_ns
                    <= row.append_started_ns
                    <= row.durable_ns
                    <= row.reconstructed_ns
                    or row.receipt_to_durable_ns != row.durable_ns - row.receipt_ns
                    or row.append_to_durable_ns != row.durable_ns - row.append_started_ns
                    or row.durable_to_reconstructed_ns != row.reconstructed_ns - row.durable_ns
                ):
                    raise ValueError(f"invalid capture probe clocks or cursor: {path}")
                cursors[row.cursor] = row
                receipt.add(row.receipt_to_durable_ns)
                append.add(row.append_to_durable_ns)
                fsync.add(row.record_fsync_ns)
                checkpoint.add(row.cursor_checkpoint_ns)
                reconstruction.add(row.durable_to_reconstructed_ns)
            elif kind.kind == "queue":
                queue_row = msgspec.json.decode(line, type=_QueueObservation)
                if (
                    queue_row.phase not in ("accepted", "durable_ready", "acknowledged")
                    or min(
                        queue_row.at_ns,
                        queue_row.pending_records,
                        queue_row.in_flight_records,
                        queue_row.queued_bytes,
                        queue_row.oldest_age_ns,
                    )
                    < 0
                ):
                    raise ValueError(f"invalid capture queue observation: {path}")
                queue_count += 1
                queue_peak = max(
                    queue_peak, queue_row.pending_records + queue_row.in_flight_records
                )
                queue_bytes_peak = max(queue_bytes_peak, queue_row.queued_bytes)
                queue_age_peak_ns = max(queue_age_peak_ns, queue_row.oldest_age_ns)
            else:
                raise ValueError(f"unknown capture measurement kind: {kind.kind}")
        queue_status = (
            "unmeasured"
            if queue_count == 0
            else "fail"
            if queue_peak > 1024 or queue_age_peak_ns > 2_000_000_000
            else "pass"
        )
        return (
            {
                "measurement_path": str(path),
                "measurement_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else None,
                "receipt_to_durable": receipt.summarize(),
                "append_to_durable": append.summarize(),
                "record_fsync": fsync.summarize(),
                "cursor_checkpoint": checkpoint.summarize(),
                "durable_to_reconstructed": reconstruction.summarize(),
                "queue": {
                    "status": queue_status,
                    "observations": queue_count,
                    "peak_occupied_records": queue_peak if queue_count else None,
                    "peak_queued_bytes": queue_bytes_peak if queue_count else None,
                    "oldest_age_peak_ns": queue_age_peak_ns if queue_count else None,
                },
            },
            cursors,
        )

    def _paper_probe(self, path: Path, cursors: dict[int, _CaptureBoundary]) -> dict[str, object]:
        """Keep source/account BBO and selected-book checkpoint clocks separate."""
        bbo = _LatencySeries((20, 100, 500))
        checkpoint = _LatencySeries((250, 750, 2000))
        total = eligible = market_selected = policy_selected = acknowledged = 0
        checkpoint_statuses: dict[str, int] = {}
        for line in self._read_lines(path):
            row = msgspec.json.decode(line, type=_PaperBook)
            if (
                row.schema_version != "runtime-measurement-v1"
                or row.kind != "paper_book"
                or row.position < 0
                or row.book_started_ns < 0
                or row.bbo_observed_ns < row.book_started_ns
            ):
                raise ValueError(f"invalid paper-book measurement: {path}")
            total += 1
            eligible += row.market_eligible
            market_selected += row.market_selected
            policy_selected += row.policy_selected
            acknowledged += row.checkpoint_acknowledged
            if row.market_eligible:
                capture = cursors.get(row.position + 1)
                if capture is None or row.bbo_observed_ns < capture.durable_ns:
                    raise ValueError(f"eligible BBO lacks a causal capture boundary: {path}")
                bbo.add(row.bbo_observed_ns - capture.durable_ns)
            if row.checkpoint_acknowledged:
                if (
                    row.book_to_checkpoint_ns is None
                    or row.checkpoint_acknowledged_ns is None
                    or row.checkpoint_status is None
                    or row.book_to_checkpoint_ns
                    != row.checkpoint_acknowledged_ns - row.book_started_ns
                ):
                    raise ValueError(f"acknowledged checkpoint lacks exact timing: {path}")
                if row.checkpoint_status == "committed":
                    checkpoint.add(row.book_to_checkpoint_ns)
                checkpoint_statuses[row.checkpoint_status] = (
                    checkpoint_statuses.get(row.checkpoint_status, 0) + 1
                )
            elif (
                row.book_to_checkpoint_ns is not None or row.checkpoint_acknowledged_ns is not None
            ):
                raise ValueError(f"unacknowledged checkpoint has a duration: {path}")
        return {
            "measurement_path": str(path),
            "measurement_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else None,
            "deliveries": total,
            "market_eligible": eligible,
            "market_selected": market_selected,
            "policy_selected": policy_selected,
            "checkpoint_acknowledged": acknowledged,
            "checkpoint_committed": checkpoint_statuses.get("committed", 0),
            "checkpoint_rejected": checkpoint_statuses.get("rejected", 0),
            "checkpoint_statuses": checkpoint_statuses,
            "durable_to_bbo": bbo.summarize(),
            "selected_book_to_checkpoint": checkpoint.summarize(),
        }

    @staticmethod
    def _authored_slot_ns(index: int) -> int:
        """Return the fixed native fixture's exact offset without a float clock."""
        if not 0 <= index < 3250:
            raise ValueError("authored capacity slot outside finite fixture")
        if index < 1000:
            return index * 40_000_000
        if index < 2000:
            return 40_000_000_000 + (index - 1000) * 10_000_000
        return 50_000_000_000 + (index - 2000) * 40_000_000

    @classmethod
    def _arrival_facts(
        cls,
        receipts: tuple[int, ...],
        steady_window_ns: tuple[int, int] | None,
        origin: Literal["base_fixture", "live_public", "other_fixture"] = "base_fixture",
    ) -> dict[str, object]:
        """Count actual socket receipts, comparing only base fixtures to authored slots.

        The fixture's first-open monotonic anchor is unavailable outside its
        transport process. First receipt is an explicitly optimistic proxy, so
        this comparison can reveal a shortfall but cannot certify full delivery.
        """
        if not receipts:
            return {"status": "unmeasured", "reason": "no_native_socket_receipts"}
        anchor = receipts[0]
        last = max(receipts)
        clock_regressions = sum(after < before for before, after in pairwise(receipts))
        one_second_bins: dict[int, int] = {}
        for receipt in receipts:
            second = (receipt - anchor) // 1_000_000_000
            one_second_bins[second] = one_second_bins.get(second, 0) + 1
        steady: dict[str, object] | None = None
        if steady_window_ns is not None:
            start, end = steady_window_ns
            if end <= start:
                raise ValueError("capacity steady receipt window is not positive")
            observed = sum(start <= receipt < end for receipt in receipts)
            steady = {
                "start_unix_ns": start,
                "end_unix_ns": end,
                "observed_receipts": observed,
                "observed_rate_hz": observed * 1_000_000_000 / (end - start),
            }
        if origin != "base_fixture":
            return {
                "status": "observed_live_public_no_authored_schedule"
                if origin == "live_public"
                else "observed_other_fixture_no_base_comparison",
                "origin": origin,
                "first_receipt_unix_ns": anchor,
                "last_receipt_unix_ns": last,
                "observed_elapsed_seconds": (last - anchor) / 1_000_000_000,
                "observed_native_receipts": len(receipts),
                "receipt_clock_regressions": clock_regressions,
                "maximum_observed_one_second_receipts": max(one_second_bins.values()),
                "steady_window": steady,
            }
        phase_bounds = (0, 40_000_000_000, 50_000_000_000, 100_000_000_000)
        observed_phases = tuple(
            sum(start <= receipt - anchor < end for receipt in receipts)
            for start, end in pairwise(phase_bounds)
        )
        expected_phases = tuple(
            sum(
                start <= cls._authored_slot_ns(index) < end
                and cls._authored_slot_ns(index) <= last - anchor
                for index in range(3250)
            )
            for start, end in pairwise(phase_bounds)
        )
        if steady is not None and steady_window_ns is not None:
            start, end = steady_window_ns
            expected = sum(
                start <= anchor + cls._authored_slot_ns(index) < end for index in range(3250)
            )
            steady["authored_due_slots_from_first_receipt_proxy"] = expected
            steady["apparent_shortfall"] = max(0, expected - cast(int, steady["observed_receipts"]))
        return {
            "status": "observed_not_qualified",
            "origin": origin,
            "schedule": "3250_slots_25hz_40s_100hz_10s_25hz_50s",
            "anchor": "first_observed_socket_receipt_not_fixture_first_open",
            "first_receipt_unix_ns": anchor,
            "last_receipt_unix_ns": last,
            "observed_elapsed_seconds": (last - anchor) / 1_000_000_000,
            "observed_native_receipts": len(receipts),
            "receipt_clock_regressions": clock_regressions,
            "observed_receipts_by_anchored_phase": observed_phases,
            "authored_due_slots_by_anchored_phase": expected_phases,
            "apparent_shortfall_by_phase": tuple(
                max(0, expected - observed)
                for expected, observed in zip(expected_phases, observed_phases)
            ),
            "maximum_observed_one_second_receipts": max(one_second_bins.values()),
            "steady_window": steady,
        }

    @staticmethod
    def _steady_window_ns(read_root: Path | None) -> tuple[int, int] | None:
        """Use only the observer's actual UTC interval for steady arrival counts."""
        if read_root is None or not (read_root / "summary.json").is_file():
            return None
        run = msgspec.json.decode((read_root / "summary.json").read_bytes(), type=_ReadRun)
        if run.started_at_utc is None or run.steady_ended_at_utc is None:
            return None
        start, end = (
            datetime.fromisoformat(run.started_at_utc),
            datetime.fromisoformat(run.steady_ended_at_utc),
        )
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("capacity read interval has no UTC offset")
        epoch = datetime(1970, 1, 1, tzinfo=UTC)

        def unix_ns(value: datetime) -> int:
            """Convert an aware UTC read clock exactly to its microsecond resolution."""
            delta = value.astimezone(UTC) - epoch
            return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000

        return unix_ns(start), unix_ns(end)

    def _capture_facts(
        self,
        root: Path,
        request: CaptureRequest,
        steady_window_ns: tuple[int, int] | None = None,
        origin: Literal["base_fixture", "live_public", "other_fixture"] = "base_fixture",
    ) -> dict[str, object]:
        """Verify the acknowledged raw journal before counting messages and encoded bytes."""
        completed = (root / "manifest.json").is_file()
        cursor = self.codec.decode_json((root / "cursor.json").read_bytes(), CaptureCursor)
        if cursor.request_identity != request.identity:
            raise ValueError(f"capture cursor differs from request: {root}")
        records = tuple(CaptureJournal(root, request).records(completed=completed))
        if (
            not completed
            and records
            and records[-1].reason == "interrupted_persistence_unknown_tail"
        ):
            records = records[:-1]
        encoded_bytes = sum(len(self.codec.encode_json(record)) + 1 for record in records)
        if encoded_bytes != cursor.offset or len(records) != cursor.records:
            raise ValueError(f"capture records differ from acknowledged cursor: {root}")
        frames = tuple(record for record in records if record.kind in ("frame", "snapshot"))
        record_sizes = sorted(len(self.codec.encode_json(record)) + 1 for record in records)
        raw_sizes = sorted(len(record.raw) for record in frames)
        encoded_sizes = sorted(len(self.codec.encode_json(record)) + 1 for record in frames)
        count = len(frames)
        record_count = len(records)
        record_mean = sum(record_sizes) / record_count if record_count else None
        record_p99 = (
            record_sizes[math.ceil(0.99 * record_count) - 1] if record_count >= 1000 else None
        )
        raw_mean = sum(raw_sizes) / count if count else None
        encoded_mean = sum(encoded_sizes) / count if count else None
        raw_p99 = raw_sizes[math.ceil(0.99 * count) - 1] if count >= 1000 else None
        encoded_p99 = encoded_sizes[math.ceil(0.99 * count) - 1] if count >= 1000 else None
        raw_max = raw_sizes[-1] if count else None
        size_status = (
            "fail"
            if (record_mean is not None and record_mean > 4096)
            or (raw_max is not None and raw_max > 8_000_000)
            or (raw_p99 is not None and raw_p99 > 32_768)
            else "pass"
            if raw_p99 is not None
            else "unmeasured"
        )
        end_reason = next(
            (record.reason for record in reversed(records) if record.kind == "end"), None
        )
        return {
            "request_identity": request.identity,
            "recording_id": request.recording_id,
            "capture_root": str(root),
            "completed_manifest": completed,
            "durable_cursor_records": cursor.records,
            "durable_cursor_bytes": cursor.offset,
            "durable_cursor_sha256": cursor.sha256,
            "native_messages": count,
            "raw_frame_mean_bytes": raw_mean,
            "raw_frame_p99_bytes": raw_p99,
            "raw_frame_max_bytes": raw_max,
            "encoded_durable_record_mean_bytes": record_mean,
            "encoded_durable_record_p99_bytes": record_p99,
            "encoded_durable_frame_mean_bytes": encoded_mean,
            "encoded_durable_frame_p99_bytes": encoded_p99,
            "size_budget_status": size_status,
            "size_p99_unavailable_reason": None
            if raw_p99 is not None
            else "fewer_than_1000_native_messages",
            "first_receipt_ns": min((record.received_ns for record in frames), default=None),
            "last_receipt_ns": max((record.received_ns for record in frames), default=None),
            "arrival_schedule": self._arrival_facts(
                tuple(record.received_ns for record in frames), steady_window_ns, origin
            ),
            "stop_reason": end_reason,
            "stop_status": "pass"
            if completed and end_reason in ("duration_limit", "supervisor_stop")
            else "fail"
            if end_reason
            in ("message_limit", "storage_limit_unknown_tail", "overload_unknown_loss")
            else "unmeasured",
        }

    def _delivery_facts(
        self, path: Path, capture_root: Path, request: CaptureRequest
    ) -> dict[str, object]:
        """Prove every available retained delivery against its raw native cursor."""
        completed = (capture_root / "manifest.json").is_file()
        raw = tuple(CaptureJournal(capture_root, request).records(completed=completed))
        if raw and raw[-1].reason == "interrupted_persistence_unknown_tail":
            raw = raw[:-1]
        replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
        matched = 0
        for line in self._read_lines(path):
            if matched >= len(raw):
                raise ValueError(f"delivery extends beyond acknowledged raw capture: {path}")
            delivery = self.codec.decode_json(line, SharedBookDelivery)
            delivery.__post_init__()
            record = raw[matched]
            if delivery.source.record != record:
                raise ValueError(f"delivery differs from raw capture at {matched}: {path}")
            outcome = replay.apply(record)
            projected = BookProjection.capture(matched, record, outcome, replay)
            if delivery.source.book != projected:
                raise ValueError(
                    f"delivery differs from native reconstruction at {matched}: {path}"
                )
            matched += 1
        remaining_kinds: dict[str, int] = {}
        for record in raw[matched:]:
            remaining_kinds[record.kind] = remaining_kinds.get(record.kind, 0) + 1
        return {
            "delivery_path": str(path),
            "delivery_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "matched_deliveries": matched,
            "available_durable_raw_records": len(raw),
            "unmatched_durable_raw_records": len(raw) - matched,
            "unmatched_raw_record_kinds": remaining_kinds,
            "status": "pass_complete_native_stream"
            if matched == len(raw) and completed
            else "pass_available_cursor_prefix"
            if matched == len(raw)
            else "unmeasured_unattributed_delivery_tail",
            "capture_finalization": "completed" if completed else "interrupted_prefix_only",
            "trace_identity": replay.summary()["trace_identity"],
        }

    def _fixture_schedule(
        self, source_name: str, capture_root: Path, request: CaptureRequest
    ) -> dict[str, object]:
        """Compare every emitted byte and required steady slot with the finalized capture."""
        trace_path = (
            self.service_root.parent / "fixture-epochs" / f"{source_name}.epoch-1-receipts.json"
        )
        if not trace_path.exists() or self.read_root is None:
            return {"status": "unmeasured", "reason": "no_closed_fixture_schedule_trace"}
        trace = self.codec.decode_json(trace_path.read_bytes(), _FixtureReceipts)
        interval = self.codec.decode_json((self.read_root / "summary.json").read_bytes(), _ReadRun)
        start, end = interval.started_monotonic_ns, interval.steady_ended_monotonic_ns
        if start is None or end is None:
            return {"status": "unmeasured", "reason": "no_monotonic_steady_interval"}
        if trace.epoch != 1 or trace.closed_ns <= trace.anchor_ns or end <= start:
            raise ValueError("invalid finite fixture schedule clocks")
        frames = tuple(
            record
            for record in CaptureJournal(capture_root, request).records(completed=True)
            if record.kind in ("frame", "snapshot")
        )
        indices = tuple(row[0] for row in trace.emitted)
        exact_bytes = tuple(hashlib.sha256(row.raw).hexdigest() for row in frames) == tuple(
            row[2] for row in trace.emitted
        )
        contiguous = indices == tuple(range(len(indices)))
        required = {
            index
            for index in range(3250)
            if start <= trace.anchor_ns + self._authored_slot_ns(index) < end
        }
        received_in_interval = {
            index for index, received_ns, _ in trace.emitted if start <= received_ns < end
        }
        # Completion can be late by the unchanged two-second queue-age bound,
        # but every authored slot due in the required interval must be retained.
        missing = required - set(indices)
        late = tuple(
            index
            for index, received_ns, _ in trace.emitted
            if index in required
            and received_ns - trace.anchor_ns - self._authored_slot_ns(index) > 2_000_000_000
        )
        burst = set(range(1000, 2000))
        complete = (
            exact_bytes
            and contiguous
            and not missing
            and not late
            and burst.issubset(required)
            and end - start >= 60_000_000_000
        )
        return {
            "status": "pass" if complete else "fail",
            "trace_path": str(trace_path),
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "fixture_identity": trace.fixture_identity,
            "emitted_frames": len(indices),
            "durable_frames": len(frames),
            "exact_native_bytes": exact_bytes,
            "contiguous_slots": contiguous,
            "required_steady_slots": len(required),
            "received_within_steady_interval": len(received_in_interval),
            "missing_required_slots": tuple(sorted(missing)),
            "slots_later_than_two_seconds": late,
            "complete_declared_burst_in_steady_interval": burst.issubset(required),
        }

    def _reads(self) -> dict[str, object]:
        """Preserve individual reader groups and label the four-reader pool explicitly."""
        if self.read_root is None:
            return {"status": "unmeasured", "reason": "no_read_observer_root"}
        samples_path = self.read_root / "samples.jsonl"
        summary_path = self.read_root / "summary.json"
        duration: int | None = None
        if summary_path.is_file():
            duration = msgspec.json.decode(
                summary_path.read_bytes(), type=_ReadRun
            ).steady_duration_seconds
        budgets = {"depth_bbo": (50, 200, 500), "dashboard": (100, 400, 1000)}
        grouped: dict[tuple[str, str], _LatencySeries] = {}
        pooled = {name: _LatencySeries(target) for name, target in budgets.items()}
        attempts: dict[tuple[str, str], int] = {}
        failures: dict[tuple[str, str], int] = {}
        for line in self._read_lines(samples_path):
            row = msgspec.json.decode(line, type=_ReadSample)
            if row.boundary not in budgets or row.phase != "steady" or row.seconds < 0:
                raise ValueError(f"invalid steady read measurement: {samples_path}")
            key = row.boundary, row.target
            group = grouped.setdefault(key, _LatencySeries(budgets[row.boundary]))
            attempts[key] = attempts.get(key, 0) + 1
            if row.status == "ok":
                elapsed_ns = round(row.seconds * 1_000_000_000)
                group.add(elapsed_ns)
                pooled[row.boundary].add(elapsed_ns)
            elif row.status == "failed":
                failures[key] = failures.get(key, 0) + 1
            else:
                raise ValueError(f"unknown read sample status: {samples_path}")
        groups: dict[str, dict[str, object]] = {}
        workloads: dict[str, dict[str, object]] = {}
        for boundary in budgets:
            targets = sorted(target for name, target in grouped if name == boundary)
            groups[boundary] = {
                target: {
                    **grouped[(boundary, target)].summarize(),
                    "attempts": attempts[(boundary, target)],
                    "failures": failures.get((boundary, target), 0),
                }
                for target in targets
            }
            pooled_result = pooled[boundary].summarize()
            expected = duration * 5 if duration is not None else None
            schedule_complete = (
                expected is not None
                and len(targets) == 4
                and all(attempts[(boundary, target)] >= expected for target in targets)
            )
            if pooled_result["status"] == "pass" and not schedule_complete:
                pooled_result["status"] = "unmeasured"
                pooled_result["reason"] = "four_reader_schedule_incomplete"
            workloads[boundary] = {
                **pooled_result,
                "scope": "pooled_four_concurrent_readers",
                "reader_targets": targets,
                "expected_attempts_per_reader": expected,
                "schedule_status": "pass"
                if schedule_complete
                else "fail"
                if expected is not None
                else "unmeasured",
            }
        return {
            "samples_path": str(samples_path),
            "samples_sha256": hashlib.sha256(samples_path.read_bytes()).hexdigest()
            if samples_path.is_file()
            else None,
            "per_target": groups,
            "four_reader_workload": workloads,
            "feature": {
                "status": "unmeasured",
                "reason": "no_integrated_versioned_feature_materialization_or_serving_path",
            },
        }

    def collect(self) -> dict[str, object]:
        """Return a bounded finite-trial characterization with exact evidence paths."""
        trial_path = self.service_root.parent / "summary.json"
        trial = self.codec.decode_json(trial_path.read_bytes(), _TrialContext)
        if trial.public_venue not in (None, "okx", "bitfinex") or trial.variant not in (
            "base",
            "quiet",
            "oversize",
            "backpressure",
            "reconnect",
        ):
            raise ValueError(f"invalid capacity transport provenance: {trial_path}")
        config = self.codec.decode_json(
            (self.service_root / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        run = self.codec.decode_json((self.service_root / "status.json").read_bytes(), _ServiceRun)
        run_root = self.service_root / "runs" / run.run_id
        probe_root = self.measurement_root / run.run_id
        steady_window = self._steady_window_ns(self.read_root)
        sources: dict[str, object] = {}
        for definition in config.sources:
            origin: Literal["base_fixture", "live_public", "other_fixture"] = (
                "live_public"
                if definition.capture.venue == trial.public_venue
                else "base_fixture"
                if trial.variant == "base"
                else "other_fixture"
            )
            recordings: dict[str, object] = {}
            for request_path in sorted((run_root / definition.name).glob("*/*/request.json")):
                request = self.codec.decode_json(request_path.read_bytes(), CaptureRequest)
                if (
                    request.config != definition.capture
                    or request_path.parent.name != request.recording_id
                    or request_path.parent.parent.name != request.recording_id
                ):
                    raise ValueError(f"capture differs from selected source: {request_path}")
                capture = self._capture_facts(request_path.parent, request, steady_window, origin)
                if origin == "base_fixture" and capture["completed_manifest"] is True:
                    capture["fixture_schedule_proof"] = self._fixture_schedule(
                        definition.name, request_path.parent, request
                    )
                measurement_directory = probe_root / definition.name
                source_probe, cursors = self._capture_probe(
                    measurement_directory / f"{request.recording_id}.capture.jsonl"
                )
                captured_native_messages = capture["native_messages"]
                if type(captured_native_messages) is not int:
                    raise ValueError(f"capture has no native message count: {request_path}")
                actual_frame_cursors = {
                    position
                    for position, record in enumerate(
                        CaptureJournal(request_path.parent, request).records(completed=False),
                        start=1,
                    )
                    if record.kind in ("frame", "snapshot")
                }
                probe_complete = set(cursors) == actual_frame_cursors
                source_probe["coverage"] = {
                    "status": "pass" if probe_complete else "fail",
                    "captured_native_messages": captured_native_messages,
                    "measured_native_messages": len(cursors),
                }
                if not probe_complete:
                    for name in (
                        "receipt_to_durable",
                        "append_to_durable",
                        "record_fsync",
                        "cursor_checkpoint",
                        "durable_to_reconstructed",
                    ):
                        latency = cast(dict[str, object], source_probe[name])
                        if latency.get("status") == "pass":
                            latency["status"] = "unmeasured"
                            latency["reason"] = "probe_does_not_cover_every_native_message"
                expected_accounts = {
                    item.account_id for item in config.instances if item.source == definition.name
                }
                paper: dict[str, object] = {}
                for path in sorted(
                    measurement_directory.glob(f"{request.recording_id}.*.paper.jsonl")
                ):
                    account_id = path.name.removeprefix(f"{request.recording_id}.").removesuffix(
                        ".paper.jsonl"
                    )
                    if account_id not in expected_accounts:
                        raise ValueError(f"paper probe has unknown account: {path}")
                    paper[account_id] = self._paper_probe(path, cursors)
                delivery_parity: dict[str, object] = {}
                for account_id in sorted(expected_accounts):
                    path = run_root / definition.name / f"{request.recording_id}-{account_id}.jsonl"
                    delivery_parity[account_id] = (
                        self._delivery_facts(path, request_path.parent, request)
                        if path.is_file()
                        else {"status": "unmeasured_missing_delivery", "delivery_path": str(path)}
                    )
                    account_probe_raw = paper.get(account_id)
                    if account_probe_raw is None:
                        paper[account_id] = {
                            "status": "unmeasured_missing_probe",
                            "measurement_path": str(
                                measurement_directory
                                / f"{request.recording_id}.{account_id}.paper.jsonl"
                            ),
                        }
                        continue
                    account_probe = cast(dict[str, object], account_probe_raw)
                    delivery_count = cast(dict[str, object], delivery_parity[account_id]).get(
                        "matched_deliveries"
                    )
                    matched_probe = account_probe["deliveries"] == delivery_count
                    account_probe["coverage"] = {
                        "status": "pass" if matched_probe else "fail",
                        "measured_deliveries": account_probe["deliveries"],
                        "retained_deliveries": delivery_count,
                    }
                    if not matched_probe:
                        for name in ("durable_to_bbo", "selected_book_to_checkpoint"):
                            latency = cast(dict[str, object], account_probe[name])
                            if latency.get("status") == "pass":
                                latency["status"] = "unmeasured"
                                latency["reason"] = "probe_does_not_cover_every_retained_delivery"
                recordings[request.recording_id] = {
                    "capture": capture,
                    "source_probe": source_probe,
                    "account_probes": paper,
                    "delivery_parity": delivery_parity,
                }
            sources[definition.name] = {
                "venue": definition.capture.venue,
                "transport_origin": origin,
                "instrument_id": str(definition.capture.instrument_id),
                "recordings": recordings,
                "status": "measured" if recordings else "unmeasured_no_recording",
            }
        return {
            "schema_version": "runtime-capacity-result-v1",
            "evidence_class": "bounded_local_stage_1",
            "run_id": run.run_id,
            "public_venue": trial.public_venue,
            "variant": trial.variant,
            "service_configuration_identity": config.identity,
            "sources": sources,
            "reads": self._reads(),
            "sustained_24_hour_status": "unmeasured",
            "sustained_24_hour_reason": "finite_service_life_and_no_capture_rollover",
        }

    def write(self, output: Path) -> dict[str, object]:
        """Exclusively retain the exact collected result without replacing an attempt."""
        result = self.collect()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(self.codec.encode_json(result))
        return result
