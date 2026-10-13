"""Collect one sustained phase's rolling latencies, commits, reconciliations and inputs.

The baseline collector keeps its 60-second gates. This collector reads the same retained
probes, read samples, feature samples, capture chains and driver observations, and
reports every latency class over fixed windows so a late tail cannot be averaged away.
Each selected checkpoint's strategy decisions are resolved from the stopped account
journal, so a decision admitted or refused at its later arrival is graded as such.
"""

from __future__ import annotations

# standard library imports
import hashlib
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

# third party library imports
import msgspec
from capacity_host import HostGate
from capacity_inputs import FixtureReceipts
from capacity_sustained import SustainedNativeFixture

# project library imports
from applications.execute import SourceVerification
from configuration import AccountConfiguration, PaperServiceConfiguration
from execution import (
    AccountDecision,
    AccountExecutionResult,
    AccountHistory,
    AccountJournal,
    HistoryDigest,
)
from market_data.storage import CaptureRecording
from serialization import DomainCodec


class SustainedValues:
    """Narrow retained sustained-result values."""

    @staticmethod
    def cast_int(value: object) -> int:
        """Narrow one retained integer clock or duration."""
        if type(value) is not int:
            raise ValueError("retained latency is not an integer")
        return value


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
                    SustainedValues.cast_int(window["p50_ns"]) <= budget.p50_ns
                    and SustainedValues.cast_int(window["p95_ns"]) <= budget.p95_ns
                    and SustainedValues.cast_int(window["p99_ns"]) <= budget.p99_ns
                )
                window["status"] = "pass" if passed else "fail"
            windows.append(window)
        population.sort()
        statuses = {str(window["status"]) for window in windows}
        return {
            "count": len(population),
            "p50_ns": cls._rank(population, 0.50) if population else None,
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
    checkpoint_batches: tuple[str, ...] | None = None
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


class _Interval(msgspec.Struct, frozen=True):
    """Decode the read observer's actual measured interval clocks."""

    started_monotonic_ns: int | None
    scheduled_stop_monotonic_ns: int | None


class _RetainedHistory(msgspec.Struct, frozen=True):
    """Decode a stopped journal's committed history digests retained at the cutoff."""

    journal_path: str
    decisions: HistoryDigest
    portfolio_batches: HistoryDigest
    paper_traces: HistoryDigest


class StoppedJournal:
    """Bind a phase's grading to the stopped journal its final state captured.

    The trial retains each account's final state and, read-only beside it, the stopped
    journal's committed history digests. The next phase reuses the same journal, so it
    is graded only while it still holds exactly that history and the trace history the
    final state names; any later commit fails closed.
    """

    @staticmethod
    def path(trial: Path, account_id: str) -> Path:
        """Name the retained digests beside ``final-<account>.json``."""
        return trial / f"final-{account_id}.history.json"

    @classmethod
    def retain(
        cls,
        trial: Path,
        account_id: str,
        journal_path: Path,
        configuration: AccountConfiguration,
    ) -> None:
        """Retain the stopped journal's committed history digests at the cutoff."""
        with AccountJournal.read_history(journal_path, configuration) as history:
            decisions, batches, traces = history.digests()
        retained = _RetainedHistory(
            journal_path=str(journal_path),
            decisions=decisions,
            portfolio_batches=batches,
            paper_traces=traces,
        )
        cls.path(trial, account_id).write_bytes(DomainCodec().encode_json(retained))

    @classmethod
    def require(
        cls,
        trial: Path,
        account_id: str,
        final: AccountExecutionResult,
        history: AccountHistory,
    ) -> dict[str, int]:
        """Return the graded history's row counts, or raise if it is not the cutoff's.

        Raises:
            OSError: No digests were retained.
            ValueError: The journal or its history differs from the retained cutoff.
        """
        retained = DomainCodec().decode_json(
            cls.path(trial, account_id).read_bytes(), _RetainedHistory
        )
        decisions, batches, traces = history.digests()
        if (
            retained.journal_path != final.journal_path
            or (retained.decisions, retained.portfolio_batches, retained.paper_traces)
            != (decisions, batches, traces)
            or final.paper_trace_history != traces
        ):
            raise ValueError("journal advanced past its retained final state")
        return {
            "decisions": decisions.count,
            "portfolio_batches": batches.count,
            "paper_traces": traces.count,
        }


class DecisionAdmissions:
    """Resolve each committed strategy decision to its own admission in the account journal.

    A paper decision with an entry delay commits as ``arrival_pending`` or
    ``replacement_pending`` and is admitted, or refused, at its arrival in a separate row
    saved under the identity the journal derives from the decision's own. Only that row
    resolves it: a pending commit never counts as an admission, and another decision's
    row never resolves it. Outcome keys are the decision-time ``status:reason``, followed
    for a pending decision by ``->status:reason`` of its arrival, or ``->unresolved``
    when the journal holds none.
    """

    PENDING: ClassVar[frozenset[str]] = frozenset(("arrival_pending", "replacement_pending"))
    ADMITTED: ClassVar[frozenset[str]] = frozenset(("reserved", "target_matched"))

    @classmethod
    def admitted(cls) -> frozenset[str]:
        """Return every outcome key that is a successful admission, immediate or at arrival."""
        decided = tuple(f"committed:{reason}" for reason in sorted(cls.ADMITTED))
        return frozenset(
            (
                *decided,
                *(f"committed:{pending}->{item}" for pending in cls.PENDING for item in decided),
            )
        )

    @classmethod
    def reserved(cls, outcomes: dict[str, int]) -> int:
        """Count decisions whose admission reserved orders, at decision time or arrival."""
        return sum(
            count
            for key, count in outcomes.items()
            if key == "committed:reserved" or key.endswith("->committed:reserved")
        )

    @classmethod
    def resolve(
        cls, history: AccountHistory, account_id: str, batches: Iterable[str]
    ) -> dict[str, int]:
        """Count the outcome of every decision in ``batches``, each decision once.

        A batch the journal lacks counts once as ``missing_batch``. An exact batch retry
        names the same decisions, which are not counted again.
        """
        counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for identity in batches:
            batch = history.batch(identity)
            if batch is None:
                counts["missing_batch"] = counts.get("missing_batch", 0) + 1
                continue
            for item in batch.decisions:
                request = item.request
                key = (request.instance_id, request.decision.identity)
                if key in seen:
                    continue
                seen.add(key)
                outcome = cls._outcome(history, account_id, request)
                counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    @classmethod
    def _outcome(cls, history: AccountHistory, account_id: str, request: AccountDecision) -> str:
        """Return one decision's outcome key from its own saved rows."""
        if request.account_id != account_id:
            return "other_account"
        saved = history.decision(request.instance_id, request.decision.identity)
        if saved is None:
            return "missing"
        if saved.request != request:
            return "conflicting"
        decided = f"{saved.result.status}:{saved.result.reason}"
        if saved.result.status != "committed" or saved.result.reason not in cls.PENDING:
            return decided
        arrival = history.decision(
            request.instance_id,
            AccountJournal.arrival_identity(
                account_id, request.instance_id, request.decision.identity
            ),
        )
        if arrival is None:
            return f"{decided}->unresolved"
        if (
            arrival.request.account_id != account_id
            or arrival.request.decision.at < request.decision.at
        ):
            return f"{decided}->conflicting"
        return f"{decided}->{arrival.result.status}:{arrival.result.reason}"


class SustainedResults:
    """Join one sustained phase's retained evidence into rolling, countable facts."""

    def __init__(
        self,
        trial: Path,
        *,
        window_seconds: int = 300,
        budgets: dict[str, WindowBudget] | None = None,
        fixture: type[SustainedNativeFixture] = SustainedNativeFixture,
    ) -> None:
        """Bind a completed phase, its declared window budgets and its authored schedule."""
        self.trial, self.window_ns = trial, window_seconds * 1_000_000_000
        self.budgets = {} if budgets is None else budgets
        self.fixture = fixture

    def interval(self) -> tuple[int, int]:
        """Return the read observer's declared measured interval in monotonic ns."""
        run = msgspec.json.decode((self.trial / "reads/summary.json").read_bytes(), type=_Interval)
        if run.started_monotonic_ns is None or run.scheduled_stop_monotonic_ns is None:
            raise ValueError("sustained phase lacks a measured interval")
        return run.started_monotonic_ns, run.scheduled_stop_monotonic_ns

    @staticmethod
    def _lines(path: Path) -> Iterator[bytes]:
        """Stream complete retained rows, refusing a truncated last row."""
        with path.open("rb") as stream:
            for line in stream:
                if not line.endswith(b"\n"):
                    raise ValueError(f"incomplete sustained evidence row: {path}")
                yield line[:-1]

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
        account_checkpoints: dict[str, list[tuple[int, int]]] = {}
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
                    sample = (book.book_started_ns, book.book_to_checkpoint_ns)
                    checkpoint.append(sample)
                    account_checkpoints.setdefault(account, []).append(sample)
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
            # Whole-run populations per account, for the day-run checkpoint percentiles.
            "selected_book_to_checkpoint_by_account": {
                name: self._rolling("selected_book_to_checkpoint", values)
                for name, values in sorted(account_checkpoints.items())
            },
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

    def _selected(self) -> Iterator[tuple[str, _Paper]]:
        """Yield each account's policy-selected books that started inside the interval."""
        start, end = self.interval()
        for path in sorted((self.trial / "measurements").glob("*/*/*.paper.jsonl")):
            account = path.name.split(".")[1]
            for line in self._lines(path):
                if msgspec.json.decode(line, type=_Row).kind != "paper_book":
                    continue
                book = msgspec.json.decode(line, type=_Paper)
                if book.policy_selected and start <= book.book_started_ns < end:
                    yield account, book

    def commits(self) -> dict[str, dict[str, int]]:
        """Count each account's selected checkpoints by status and reason inside the interval.

        These are decision-time batch commits; a pending one is resolved per decision
        by ``decisions``.
        """
        accounts: dict[str, dict[str, int]] = {}
        for account, book in self._selected():
            counts = accounts.setdefault(account, {})
            outcome = (
                f"{book.checkpoint_status}:{book.checkpoint_reason}"
                if book.checkpoint_acknowledged
                else "unacknowledged"
            )
            counts[outcome] = counts.get(outcome, 0) + 1
        return accounts

    def decisions(self) -> dict[str, dict[str, object]]:
        """Resolve every decision of each account's selected checkpoints in its stopped journal.

        Decisions belong to the checkpoint that committed them inside the interval; their
        outcome is read from the journal the trial stopped and retained in
        ``final-<account>.json``, so an arrival after the interval, or after a later
        checkpoint, still resolves its own decision, and one never resolved by then is
        unresolved. The journal is read only while it holds exactly the history retained
        at that cutoff (``StoppedJournal``): a later phase reusing it fails closed. An
        acknowledged checkpoint naming no batch counts as ``unnamed_batch``. Unreadable
        evidence is reported, never raised.
        """
        batches: dict[str, list[str]] = {}
        unnamed: dict[str, int] = {}
        for account, book in self._selected():
            named = batches.setdefault(account, [])
            if not book.checkpoint_acknowledged:
                continue
            if book.checkpoint_batches:
                named.extend(book.checkpoint_batches)
            else:
                unnamed[account] = unnamed.get(account, 0) + 1
        codec = DomainCodec()
        result: dict[str, dict[str, object]] = {}
        try:
            service = codec.decode_json(
                (self.trial / "configuration.json").read_bytes(), PaperServiceConfiguration
            )
        except (OSError, ValueError, msgspec.DecodeError) as error:
            reason = f"configuration: {type(error).__name__}"
            return {account: {"readable": False, "reason": reason} for account in batches}
        for account, named in sorted(batches.items()):
            try:
                configuration = next(
                    (item.configuration for item in service.accounts if item.account_id == account),
                    None,
                )
                if configuration is None:
                    raise ValueError("account is not configured")
                final = codec.decode_json(
                    (self.trial / f"final-{account}.json").read_bytes(), AccountExecutionResult
                )
                if final.journal_path is None:
                    raise ValueError("final account state names no journal")
                with AccountJournal.read_history(
                    Path(final.journal_path), configuration
                ) as history:
                    journal = StoppedJournal.require(self.trial, account, final, history)
                    outcomes = DecisionAdmissions.resolve(history, account, named)
            except (OSError, ValueError, msgspec.DecodeError) as error:
                result[account] = {"readable": False, "reason": f"{type(error).__name__}: {error}"}
                continue
            if account in unnamed:
                outcomes["unnamed_batch"] = unnamed[account]
            result[account] = {
                "readable": True,
                "batches": len(named),
                "outcomes": outcomes,
                "journal": journal,
            }
        return result

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
            entry["attempts"] = SustainedValues.cast_int(entry["attempts"]) + 1
            entry["matched"] = SustainedValues.cast_int(entry["matched"]) + (
                values.get("matched") is True
            )
            seconds = values.get("seconds")
            if isinstance(seconds, float) and seconds > float(str(entry["max_seconds"])):
                entry["max_seconds"] = seconds
        return dict(result)

    def recordings(self) -> dict[str, object]:
        """Report every source's recordings, segments and explicitly verified replay parity."""
        result: dict[str, object] = {}
        for run in sorted((self.trial / "operating/runs").iterdir()):
            for source in sorted(path for path in run.iterdir() if path.is_dir()):
                entries: list[dict[str, object]] = []
                for recording in CaptureRecording.discover(source):
                    verification = SourceVerification(recording.root.parent)
                    summary_path = verification.root / SourceVerification.RESULT
                    record_path = verification.root / SourceVerification.RECORD
                    summary = (
                        msgspec.json.decode(summary_path.read_bytes(), type=dict[str, object])
                        if summary_path.is_file()
                        else {}
                    )
                    try:
                        record = (
                            msgspec.json.decode(record_path.read_bytes(), type=dict[str, object])
                            if record_path.is_file()
                            else {}
                        )
                    except msgspec.DecodeError:
                        record = {"status": "unreadable"}
                    entries.append(
                        {
                            "key": recording.key,
                            "completed": recording.completed,
                            "segments": len(recording.cursor().segments),
                            "durable_records": recording.cursor().records,
                            # Parity comes only from an explicit verification record
                            # bound to this sealed result, never from the result itself.
                            "replay_parity": verification.verified(),
                            "verification": record.get("status", "missing"),
                            "stop_reason": summary.get("stop_reason"),
                        }
                    )
                result[source.name] = entries
        return result

    @staticmethod
    def _first_slot_at(fixture: type[SustainedNativeFixture], offset_ns: int) -> int:
        """Return the first slot whose authored offset is at least ``offset_ns``."""
        low, high = 0, fixture.frame_count
        while low < high:
            middle = (low + high) // 2
            if fixture.slot_ns(middle) < offset_ns:
                low = middle + 1
            else:
                high = middle
        return low

    def fixture_proof(self, source: str) -> dict[str, object]:
        """Prove every emitted slot is retained exactly, in order and on time.

        Each fixture epoch's emitted bytes must equal its recording's frames in order;
        every slot due inside the measured interval must have been emitted and
        retained no later than the unchanged two-second queue-age bound. Emitted slots
        and retained frames are compared as they stream, so a day's run is never held.
        """
        start, end = self.interval()
        fixture = self.fixture
        traces = sorted((self.trial / "fixture-epochs").glob(f"{source}.epoch-*-receipts.jsonl"))
        runs = sorted((self.trial / "operating/runs").iterdir())
        recordings = CaptureRecording.discover(runs[0] / source) if len(runs) == 1 else ()
        if len(traces) != 1 or len(recordings) != 1:
            return {
                "status": "fail",
                "reason": "proof requires one fixture epoch and one recording",
                "epochs": len(traces),
                "recordings": len(recordings),
            }
        trace = FixtureReceipts(traces[0])
        # Slot clocks increase with the index, so the slots due in the interval are one range.
        low = self._first_slot_at(fixture, start - trace.anchor_ns)
        high = self._first_slot_at(fixture, end - trace.anchor_ns)
        frames = (
            hashlib.sha256(record.raw).hexdigest()
            for record in recordings[0].records(completed=recordings[0].completed)
            if record.kind in ("frame", "snapshot")
        )
        emitted = retained = late = 0
        exact = contiguous = True
        for index, received_ns, digest in trace.rows():
            contiguous = contiguous and index == emitted
            emitted += 1
            frame = next(frames, None)
            retained += frame is not None
            exact = exact and frame == digest
            if (
                low <= index < high
                and received_ns - trace.anchor_ns - fixture.slot_ns(index) > 2_000_000_000
            ):
                late += 1
        unread = sum(1 for _ in frames)
        retained += unread
        exact = exact and not unread
        missing = max(0, high - max(low, emitted))
        complete = exact and contiguous and not missing and not late
        return {
            "status": "pass" if complete else "fail",
            "fixture_identity": trace.fixture_identity,
            "emitted": emitted,
            "retained_frames": retained,
            "exact_bytes_in_order": exact,
            "required_slots": high - low,
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
            "decisions": self.decisions(),
            "reconciliations": self.reconciliations(),
            "recordings": recordings,
            "fixture_proofs": {source: self.fixture_proof(source) for source in sorted(recordings)},
            "host": None
            if host_rows is None or host_gate is None
            else host_gate.assess(self._lines(host_rows)),
        }
