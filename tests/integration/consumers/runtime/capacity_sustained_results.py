"""Collect one sustained phase's rolling latencies, commits, reconciliations and inputs.

The stage-1 collector keeps its 60-second gates. This collector reads the same retained
probes, read samples, feature samples, capture chains and driver observations, and
reports every latency class over fixed windows so a late tail cannot be averaged away.
"""

from __future__ import annotations

# standard library imports
import hashlib
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# third party library imports
import msgspec
from capacity_host import HostGate
from capacity_sustained import SustainedNativeFixture

# project library imports
from market_data.storage import CaptureRecording


@dataclass(frozen=True, slots=True)
class WindowBudget:
    """Declare one latency class's per-window percentile budget and minimum population."""

    p50_ns: int
    p95_ns: int
    p99_ns: int
    minimum: int = 1000


class RollingPercentiles:
    """Summarize ``(clock_ns, value_ns)`` samples over fixed windows of an interval."""

    @staticmethod
    def _rank(ordered: list[int], quantile: float) -> int:
        """Return the nearest-rank percentile of a nonempty ordered population."""
        return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]

    @classmethod
    def summarize(
        cls,
        samples: Iterable[tuple[int, int]],
        *,
        start_ns: int,
        end_ns: int,
        window_ns: int,
        budget: WindowBudget | None = None,
    ) -> dict[str, object]:
        """Report every window inside ``[start_ns, end_ns)`` and the whole interval.

        A window fails when its p95 or p99 exceeds the budget. A window below the
        minimum population is unmeasured, and the class passes only if every
        window is measured and passes.
        """
        if end_ns <= start_ns or window_ns <= 0:
            raise ValueError("rolling percentiles require a positive interval and window")
        count = math.ceil((end_ns - start_ns) / window_ns)
        buckets: list[list[int]] = [[] for _ in range(count)]
        population: list[int] = []
        for clock_ns, value_ns in samples:
            if start_ns <= clock_ns < end_ns:
                buckets[(clock_ns - start_ns) // window_ns].append(value_ns)
                population.append(value_ns)
        windows: list[dict[str, object]] = []
        for index, values in enumerate(buckets):
            values.sort()
            window: dict[str, object] = {
                "offset_seconds": index * window_ns / 1_000_000_000,
                "count": len(values),
            }
            if values:
                window.update(
                    p50_ns=cls._rank(values, 0.50),
                    p95_ns=cls._rank(values, 0.95),
                    p99_ns=cls._rank(values, 0.99),
                    max_ns=values[-1],
                )
            if budget is None:
                window["status"] = "reported"
            elif len(values) < budget.minimum:
                window["status"] = "unmeasured"
            else:
                passed = (
                    cast_int(window["p50_ns"]) <= budget.p50_ns
                    and cast_int(window["p95_ns"]) <= budget.p95_ns
                    and cast_int(window["p99_ns"]) <= budget.p99_ns
                )
                window["status"] = "pass" if passed else "fail"
            windows.append(window)
        population.sort()
        statuses = {str(window["status"]) for window in windows}
        return {
            "count": len(population),
            "p95_ns": cls._rank(population, 0.95) if population else None,
            "p99_ns": cls._rank(population, 0.99) if population else None,
            "max_ns": population[-1] if population else None,
            "window_seconds": window_ns / 1_000_000_000,
            "budget": None
            if budget is None
            else {"p50_ns": budget.p50_ns, "p95_ns": budget.p95_ns, "p99_ns": budget.p99_ns},
            "windows": windows,
            "status": "reported"
            if budget is None
            else "fail"
            if "fail" in statuses
            else "unmeasured"
            if "unmeasured" in statuses
            else "pass",
        }


def cast_int(value: object) -> int:
    """Narrow one retained integer clock or duration."""
    if type(value) is not int:
        raise ValueError("retained latency is not an integer")
    return value


class _Row(msgspec.Struct, frozen=True):
    """Select a measurement row's kind before decoding its typed fields."""

    kind: str


class _Capture(msgspec.Struct, frozen=True):
    """Select capture boundary clocks."""

    cursor: int
    receipt_ns: int
    durable_ns: int
    receipt_to_durable_ns: int


class _Paper(msgspec.Struct, frozen=True, kw_only=True):
    """Select paper book clocks and checkpoint outcome."""

    position: int
    policy_selected: bool
    checkpoint_acknowledged: bool
    checkpoint_status: str | None
    book_started_ns: int
    checkpoint_reason: str | None = None
    bbo_observed_ns: int
    book_to_checkpoint_ns: int | None


class _Read(msgspec.Struct, frozen=True):
    """Select one scheduled read request."""

    boundary: str
    status: str
    scheduled_monotonic_ns: int
    response_seconds: float | None


class _Retrieval(msgspec.Struct, frozen=True):
    """Select one feature retrieval request."""

    status: str
    due_ns: int
    completed_ns: int


class _Materialization(msgspec.Struct, frozen=True):
    """Select one feature materialization's durable-to-available clock."""

    durable_ns: int | None
    durable_to_available_ns: int | None


class _Observation(msgspec.Struct, frozen=True):
    """Select one driver observation's kind and values."""

    kind: str
    values: object


class _Receipts(msgspec.Struct, frozen=True):
    """Decode one fixture epoch's emitted slots, clocks and byte digests."""

    fixture_identity: str
    epoch: int
    anchor_ns: int
    closed_ns: int
    emitted: tuple[tuple[int, int, str], ...]


class _Interval(msgspec.Struct, frozen=True):
    """Decode the read observer's actual measured interval clocks."""

    started_monotonic_ns: int | None
    scheduled_stop_monotonic_ns: int | None


class SustainedResults:
    """Join one sustained phase's retained evidence into rolling, countable facts."""

    def __init__(
        self,
        trial: Path,
        *,
        window_seconds: int = 300,
        budgets: dict[str, WindowBudget] | None = None,
    ) -> None:
        """Bind a completed phase directory and the declared window budgets by class."""
        self.trial, self.window_ns = trial, window_seconds * 1_000_000_000
        self.budgets = {} if budgets is None else budgets

    def interval(self) -> tuple[int, int]:
        """Return the read observer's declared measured interval in monotonic ns."""
        run = msgspec.json.decode((self.trial / "reads/summary.json").read_bytes(), type=_Interval)
        if run.started_monotonic_ns is None or run.scheduled_stop_monotonic_ns is None:
            raise ValueError("sustained phase lacks a measured interval")
        return run.started_monotonic_ns, run.scheduled_stop_monotonic_ns

    @staticmethod
    def _lines(path: Path) -> Iterator[bytes]:
        """Yield complete retained rows, refusing a truncated last row."""
        payload = path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            raise ValueError(f"incomplete sustained evidence row: {path}")
        yield from payload.splitlines()

    def _rolling(self, name: str, samples: Iterable[tuple[int, int]]) -> dict[str, object]:
        """Summarize one class over the measured interval with its declared budget."""
        start, end = self.interval()
        return RollingPercentiles.summarize(
            samples,
            start_ns=start,
            end_ns=end,
            window_ns=self.window_ns,
            budget=self.budgets.get(name),
        )

    def latencies(self) -> dict[str, object]:
        """Report capture, paper, read and feature latency classes over rolling windows."""
        measurements = self.trial / "measurements"
        receipt: dict[str, list[tuple[int, int]]] = {}
        durable: dict[tuple[str, int], int] = {}
        for path in sorted(measurements.glob("*/*/*.capture.jsonl")):
            key = path.name.removesuffix(".capture.jsonl")
            source_receipts = receipt.setdefault(path.parent.name, [])
            for line in self._lines(path):
                if msgspec.json.decode(line, type=_Row).kind != "capture_boundary":
                    continue
                row = msgspec.json.decode(line, type=_Capture)
                source_receipts.append((row.receipt_ns, row.receipt_to_durable_ns))
                durable[(key, row.cursor)] = row.durable_ns
        bbo: dict[str, list[tuple[int, int]]] = {}
        checkpoint: list[tuple[int, int]] = []
        for path in sorted(measurements.glob("*/*/*.paper.jsonl")):
            key, account = path.name.split(".")[:2]
            account_bbo = bbo.setdefault(account, [])
            for line in self._lines(path):
                if msgspec.json.decode(line, type=_Row).kind != "paper_book":
                    continue
                book = msgspec.json.decode(line, type=_Paper)
                durable_ns = durable.get((key, book.position + 1))
                if durable_ns is not None:
                    account_bbo.append((durable_ns, book.bbo_observed_ns - durable_ns))
                if book.book_to_checkpoint_ns is not None:
                    checkpoint.append((book.book_started_ns, book.book_to_checkpoint_ns))
        reads: dict[str, list[tuple[int, int]]] = {}
        failed_reads: dict[str, int] = {}
        samples_path = self.trial / "reads/samples.jsonl"
        for line in self._lines(samples_path) if samples_path.is_file() else iter(()):
            read = msgspec.json.decode(line, type=_Read)
            if read.status == "ok" and read.response_seconds is not None:
                reads.setdefault(read.boundary, []).append(
                    (read.scheduled_monotonic_ns, round(read.response_seconds * 1_000_000_000))
                )
            else:
                failed_reads[read.boundary] = failed_reads.get(read.boundary, 0) + 1
        features = self.trial / "reads/features"
        retrievals: list[tuple[int, int]] = []
        retrieval_path = features / "retrieval-samples.jsonl"
        for line in self._lines(retrieval_path) if retrieval_path.is_file() else iter(()):
            retrieval = msgspec.json.decode(line, type=_Retrieval)
            if retrieval.status == "ok":
                retrievals.append((retrieval.due_ns, retrieval.completed_ns - retrieval.due_ns))
        materialized: list[tuple[int, int]] = []
        materialization_path = features / "materialization-samples.jsonl"
        for line in (
            self._lines(materialization_path) if materialization_path.is_file() else iter(())
        ):
            materialization = msgspec.json.decode(line, type=_Materialization)
            if (
                materialization.durable_ns is not None
                and materialization.durable_to_available_ns is not None
            ):
                materialized.append(
                    (materialization.durable_ns, materialization.durable_to_available_ns)
                )
        return {
            "receipt_to_durable": {
                name: self._rolling("receipt_to_durable", values)
                for name, values in sorted(receipt.items())
            },
            "durable_to_bbo": {
                name: self._rolling("durable_to_bbo", values)
                for name, values in sorted(bbo.items())
            },
            "selected_book_to_checkpoint": self._rolling("selected_book_to_checkpoint", checkpoint),
            **{
                f"read_{name}": self._rolling(f"read_{name}", values)
                for name, values in sorted(reads.items())
            },
            "failed_or_missed_reads": failed_reads,
            "feature_retrieval": self._rolling("feature_retrieval", retrievals),
            "feature_durable_to_available": self._rolling(
                "feature_durable_to_available", materialized
            ),
        }

    def commits(self) -> dict[str, dict[str, int]]:
        """Count each account's selected checkpoints by status and reason inside the interval."""
        start, end = self.interval()
        accounts: dict[str, dict[str, int]] = {}
        for path in sorted((self.trial / "measurements").glob("*/*/*.paper.jsonl")):
            account = path.name.split(".")[1]
            counts = accounts.setdefault(account, {})
            for line in self._lines(path):
                if msgspec.json.decode(line, type=_Row).kind != "paper_book":
                    continue
                book = msgspec.json.decode(line, type=_Paper)
                if not book.policy_selected or not start <= book.book_started_ns < end:
                    continue
                outcome = (
                    f"{book.checkpoint_status}:{book.checkpoint_reason}"
                    if book.checkpoint_acknowledged
                    else "unacknowledged"
                )
                counts[outcome] = counts.get(outcome, 0) + 1
        return accounts

    def reconciliations(self) -> dict[str, object]:
        """Count each account's retained reconciliations and every mismatch."""
        result: dict[str, dict[str, object]] = {}
        for line in self._lines(self.trial / "observations.jsonl"):
            row = msgspec.json.decode(line, type=_Observation)
            if row.kind != "account_reconciled" or not isinstance(row.values, dict):
                continue
            values = row.values
            account = str(values.get("account"))
            entry = result.setdefault(account, {"attempts": 0, "matched": 0, "max_seconds": 0.0})
            entry["attempts"] = cast_int(entry["attempts"]) + 1
            entry["matched"] = cast_int(entry["matched"]) + (values.get("matched") is True)
            seconds = values.get("seconds")
            if isinstance(seconds, float) and seconds > float(str(entry["max_seconds"])):
                entry["max_seconds"] = seconds
        return dict(result)

    def recordings(self) -> dict[str, object]:
        """Report every source's recordings, segments and the source child's replay parity."""
        result: dict[str, object] = {}
        for run in sorted((self.trial / "operating/runs").iterdir()):
            for source in sorted(path for path in run.iterdir() if path.is_dir()):
                entries: list[dict[str, object]] = []
                for recording in CaptureRecording.discover(source):
                    summary_path = recording.root.parent / "source-result.json"
                    summary = (
                        msgspec.json.decode(summary_path.read_bytes(), type=dict[str, object])
                        if summary_path.is_file()
                        else {}
                    )
                    entries.append(
                        {
                            "key": recording.key,
                            "completed": recording.completed,
                            "segments": len(recording.cursor().segments),
                            "durable_records": recording.cursor().records,
                            "replay_parity": summary.get("replay_parity") is True,
                            "stop_reason": summary.get("stop_reason"),
                        }
                    )
                result[source.name] = entries
        return result

    def fixture_proof(self, source: str) -> dict[str, object]:
        """Prove every emitted slot is retained exactly, in order and on time.

        Each fixture epoch's emitted bytes must equal its recording's frames in order;
        every slot due inside the measured interval must have been emitted and
        retained no later than the unchanged two-second queue-age bound.
        """
        start, end = self.interval()
        traces = sorted((self.trial / "fixture-epochs").glob(f"{source}.epoch-*-receipts.json"))
        runs = sorted((self.trial / "operating/runs").iterdir())
        recordings = CaptureRecording.discover(runs[0] / source) if len(runs) == 1 else ()
        if len(traces) != 1 or len(recordings) != 1:
            return {
                "status": "fail",
                "reason": "proof requires one fixture epoch and one recording",
                "epochs": len(traces),
                "recordings": len(recordings),
            }
        trace = msgspec.json.decode(traces[0].read_bytes(), type=_Receipts)
        frames = tuple(
            record
            for record in recordings[0].records(completed=recordings[0].completed)
            if record.kind in ("frame", "snapshot")
        )
        indices = tuple(row[0] for row in trace.emitted)
        exact = tuple(hashlib.sha256(frame.raw).hexdigest() for frame in frames) == tuple(
            row[2] for row in trace.emitted
        )
        required = {
            index
            for index in range(SustainedNativeFixture.frame_count)
            if start <= trace.anchor_ns + SustainedNativeFixture.slot_ns(index) < end
        }
        late = sum(
            1
            for index, received_ns, _ in trace.emitted
            if index in required
            and received_ns - trace.anchor_ns - SustainedNativeFixture.slot_ns(index)
            > 2_000_000_000
        )
        missing = len(required - set(indices))
        complete = exact and indices == tuple(range(len(indices))) and not missing and not late
        return {
            "status": "pass" if complete else "fail",
            "fixture_identity": trace.fixture_identity,
            "emitted": len(indices),
            "retained_frames": len(frames),
            "exact_bytes_in_order": exact,
            "required_slots": len(required),
            "missing_required_slots": missing,
            "late_required_slots": late,
        }

    def collect(
        self, *, host_rows: Path | None = None, host_gate: HostGate | None = None
    ) -> dict[str, object]:
        """Join every sustained fact for one phase, with the host gate when sampled."""
        recordings = self.recordings()
        return {
            "schema_version": "runtime-capacity-sustained-phase",
            "interval_monotonic_ns": self.interval(),
            "latencies": self.latencies(),
            "commits": self.commits(),
            "reconciliations": self.reconciliations(),
            "recordings": recordings,
            "fixture_proofs": {source: self.fixture_proof(source) for source in sorted(recordings)},
            "host": None
            if host_rows is None or host_gate is None
            else host_gate.assess(self._lines(host_rows)),
        }
