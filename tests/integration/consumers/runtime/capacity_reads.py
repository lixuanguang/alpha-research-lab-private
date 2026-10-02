"""Observe bounded paper-service reads and process resources from retained facts.

The observer is an independent diagnostic. It has no account socket, policy worker,
or venue transport. A steady sample uses the service's fsynced delivery log and
monitoring store; an interrupted raw capture is checked separately for replay parity.
"""

from __future__ import annotations

# standard library imports
import hashlib
import math
import multiprocessing
import os
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Literal, Protocol, cast

# third party library imports
import msgspec
import psutil  # type: ignore[import-untyped]  # [owner=runtime; rationale=locked diagnostic dependency has no bundled typing stubs; expires=2027-02-01]
from capacity_features import CapacityFeatureObserver

# project library imports
from applications.execute.source_service import _DecodedBookObservation
from configuration import (
    BookKey,
    BookRegistryConfiguration,
    BookSelection,
    PaperServiceConfiguration,
)
from market_data.adapters.sources import BookAdapters
from market_data.books import (
    BookAsOfIndex,
    BookDepth,
    BookProjection,
    BookRegistry,
    CaptureReplay,
)
from market_data.contracts import BookObservation, BookQuote, CaptureRequest
from market_data.storage import CaptureJournal
from runtime import LiveBookDelivery, SharedBookDelivery
from serialization import DomainCodec
from telemetry import (
    DashboardConfig,
    DashboardRenderer,
    MetricRegistry,
    MonitoringConfiguration,
    MonitoringDefinitions,
    MonitoringQuery,
    TelemetryStore,
)

_NO_SUCH_PROCESS = cast(type[Exception], psutil.NoSuchProcess)  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil process-exit exception is handled at sampling boundary; expires=2027-02-01]
_ACCESS_DENIED = cast(type[Exception], psutil.AccessDenied)  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil access exception is recorded at sampling boundary; expires=2027-02-01]
# Descendant discovery walks every host process; counters stay one-second.
_TREE_REFRESH_SECONDS = 5.0


class _ServiceRun(msgspec.Struct, frozen=True):
    """Read only the currently active run identity from the service status."""

    run_id: str


class _IndexedSourceDelivery(LiveBookDelivery, frozen=True):
    """Decode complete typed native records before checking their separate delivery clock."""

    book: _DecodedBookObservation

    def __post_init__(self) -> None:
        """Avoid recursively validating native fields already checked by the typed decoder."""
        self._require_availability()


class _IndexedSharedDelivery(SharedBookDelivery, frozen=True):
    """Decode a strict complete envelope for the read-only retained index."""

    source: _IndexedSourceDelivery

    def __post_init__(self) -> None:
        """Check coordination after the decoder validates every nested source and policy field."""
        self._require_coordination()


class _MemorySample(Protocol):
    """Describe resident bytes returned by the installed OS adapter."""

    rss: int


class _CpuSample(Protocol):
    """Describe cumulative process CPU seconds returned by the OS adapter."""

    user: float
    system: float


class _IoSample(Protocol):
    """Describe supported cumulative physical process I/O counters."""

    read_bytes: int
    write_bytes: int


class _StopSignal(Protocol):
    """Bound the separate diagnostic sampler without sharing read-worker state."""

    def is_set(self) -> bool:
        """Report the parent's end-of-interval signal."""
        ...

    def wait(self, timeout: float | None = None) -> bool:
        """Sleep until either the next one-second slot or the stop signal."""
        ...


class _SampledProcess(Protocol):
    """Narrow the optional psutil process surface to this observer's reads."""

    pid: int

    def memory_info(self) -> _MemorySample:
        """Read current resident bytes."""
        ...

    def cpu_times(self) -> _CpuSample:
        """Read cumulative user and system CPU seconds."""
        ...

    def io_counters(self) -> _IoSample:
        """Read platform-supported physical read and write counters."""
        ...

    def create_time(self) -> float:
        """Disambiguate a reused process ID."""
        ...

    def children(self, *, recursive: bool) -> list[_SampledProcess]:
        """Discover the current descendants of a selected process."""
        ...


class _SourceIndex:
    """Bind a source's delivery log, its durable as-of index and the live polled history."""

    def __init__(
        self,
        name: str,
        request: CaptureRequest,
        capture_root: Path,
        delivery_path: Path,
        history_capacity: int,
    ) -> None:
        """Bind a source's original recording and one account's identical delivery copy."""
        self.name, self.request = name, request
        self.capture_root, self.delivery_path = capture_root, delivery_path
        self.key = BookKey(venue=request.config.venue, instrument_id=request.config.instrument_id)
        self.index = BookAsOfIndex(delivery_path.with_name(delivery_path.stem + ".index.sqlite3"))
        self.offset = 0
        self.deliveries = 0
        self.history: deque[tuple[BookQuote, bytes, int]] = deque(maxlen=history_capacity)


class _RetainedBookIndex:
    """Advance actual causal book projections without reading later delivery clocks."""

    def __init__(
        self, config: PaperServiceConfiguration, sources: tuple[_SourceIndex, ...]
    ) -> None:
        """Use installed registry admission and the exact retained source bindings."""
        self.codec = DomainCodec()
        self.sources = {source.name: source for source in sources}
        self.lock = threading.RLock()
        self.poll_lock = threading.Lock()
        selections = tuple(
            BookSelection.from_capture(
                source.request.config,
                source_id=source.request.identity,
                capability=BookAdapters.capability(source.request.config),
                max_age_ns=next(
                    item.freshness_us for item in config.sources if item.name == source.name
                )
                * 1000,
                allow_degraded=True,
            )
            for source in sources
        )
        self.selections = {
            source.name: selection for source, selection in zip(sources, selections, strict=True)
        }
        self.registry = BookRegistry(
            BookRegistryConfiguration(
                selections=selections, equivalences=(), history_capacity=10_000
            )
        )

    @staticmethod
    def _unix_ns(value: datetime) -> int:
        """Convert an observed UTC microsecond clock without floating-point rounding."""
        delta = value - datetime(1970, 1, 1, tzinfo=UTC)
        return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000

    def poll(self) -> int:
        """Apply a captured finite prefix so later appends cannot extend a poll."""
        retained_ends = self._retained_ends()
        with self.poll_lock:
            return self._poll_serialized(retained_ends)

    def _retained_ends(self) -> dict[str, int]:
        """Capture selected file bounds before waiting for another reader's poll."""
        return {
            name: source.delivery_path.stat().st_size
            for name, source in self.sources.items()
            if source.delivery_path.is_file()
        }

    def read(self, source_name: str, *, cutoff_ns: int) -> dict[str, object]:
        """Answer one as-of query from the durable index and report its covered prefix."""
        source = self.sources[source_name]
        required_end = (
            source.delivery_path.stat().st_size if source.delivery_path.is_file() else None
        )
        indexed_end = source.index.covered_bytes()
        result = self.depth(source_name, cutoff_ns=cutoff_ns)
        covered = required_end is not None and indexed_end >= required_end
        if not covered:
            result.update(
                eligible=False,
                partial_coverage=True,
                reason="incomplete_retained_delivery_prefix",
            )
        result.update(
            delivery_prefix_complete=covered,
            depth_index_required_prefix_bytes=required_end,
            depth_index_indexed_prefix_bytes=indexed_end,
        )
        return result

    def _poll_serialized(self, retained_ends: dict[str, int]) -> int:
        """Coalesce already covered prefixes without scanning a growing EOF."""
        count = 0
        for name, retained_end in retained_ends.items():
            source = self.sources[name]
            if source.offset >= retained_end:
                continue
            with source.delivery_path.open("rb") as stream:
                stream.seek(source.offset)
                while source.offset < retained_end:
                    line = stream.readline(retained_end - source.offset)
                    if not line.endswith(b"\n"):
                        break
                    delivery = self.codec.decode_json(line, _IndexedSharedDelivery)
                    row = delivery.source.book
                    if (
                        row.position != source.deliveries
                        or delivery.source.record.received_ns != row.received_ns
                    ):
                        raise ValueError(f"{source.name} delivery position or receipt differs")
                    quote = BookDepth._touch_quote_validated(
                        row,
                        venue=source.request.config.venue,
                        instrument_id=source.request.config.instrument_id,
                        source_id=source.request.identity,
                        channel=source.request.config.channel,
                        available_ns=self._unix_ns(delivery.source.available_at),
                    )
                    with self.lock:
                        self.registry.accept(quote)
                        source.history.append((quote, line, len(line)))
                        source.deliveries += 1
                        source.offset = stream.tell()
                    count += 1
        return count

    def depth(self, source_name: str, *, cutoff_ns: int) -> dict[str, object]:
        """Look up the causal boundary in the durable index and decode only its delivery."""
        source = self.sources[source_name]
        limit = 25 if source.request.config.venue == "bitfinex" else 100
        lookup, selected = source.index.lookup(self.selections[source_name], cutoff_ns=cutoff_ns)
        selected_row: BookObservation | None = None
        read_bytes = 0
        if selected is not None:
            offset, length = selected
            with source.delivery_path.open("rb") as stream:
                stream.seek(offset)
                encoded_delivery = stream.read(length)
            read_bytes = len(encoded_delivery)
            if read_bytes != length or not encoded_delivery.endswith(b"\n"):
                raise ValueError(f"{source_name} indexed delivery is truncated")
            selected_row = self.codec.decode_json(
                encoded_delivery, _IndexedSharedDelivery
            ).source.book
            target = lookup.quote if lookup.quote is not None else lookup.boundary
            if target is None or selected_row.position != target.position:
                raise ValueError(f"{source_name} indexed delivery differs from its boundary")
        selected_depth = (
            BookDepth((), ()) if selected_row is None else BookDepth.from_observation(selected_row)
        )
        visible = BookDepth(selected_depth.bids[-limit:], selected_depth.asks[:limit])
        result = self.codec.encode_json((lookup, visible))
        return {
            "source": source_name,
            "cutoff_ns": cutoff_ns,
            "reason": lookup.reason,
            "eligible": lookup.eligible,
            "boundary_position": None if lookup.boundary is None else lookup.boundary.position,
            "quote_position": None if lookup.quote is None else lookup.quote.position,
            "market_state": None if lookup.quote is None else lookup.quote.market_state,
            "bid_levels": len(visible.bids),
            "ask_levels": len(visible.asks),
            "depth_index_scan_bytes": read_bytes,
            "returned_bytes": len(result),
            "result_sha256": hashlib.sha256(result).hexdigest(),
            "partial_coverage": not lookup.eligible,
            "consolidation": "not_applicable_no_equivalent_currency_pair",
            "scan_basis": "durable_as_of_index_lookup_and_one_selected_delivery",
        }

    def replay_parity(self) -> dict[str, dict[str, object]]:
        """Compare all available raw records and retained deliveries at one cursor."""
        findings: dict[str, dict[str, object]] = {}
        for source in self.sources.values():
            replay = CaptureReplay(source.request.config, book_factory=BookAdapters.create)
            delivered: list[SharedBookDelivery] = []
            with source.delivery_path.open("rb") as stream:
                for line in stream:
                    if not line.endswith(b"\n"):
                        raise ValueError(f"{source.name} delivery has an incomplete line")
                    delivered.append(self.codec.decode_json(line, SharedBookDelivery))
            if len(delivered) != source.deliveries:
                raise ValueError(f"{source.name} delivery changed after final index poll")
            raw_records = tuple(
                CaptureJournal(source.capture_root, source.request).records(completed=False)
            )
            if raw_records and raw_records[-1].reason == "interrupted_persistence_unknown_tail":
                raw_records = raw_records[:-1]
            matched = 0
            for position, record in enumerate(raw_records):
                if position >= len(delivered):
                    break
                saved = delivered[position].source
                if record != saved.record:
                    raise ValueError(f"{source.name} raw capture differs at {position}")
                outcome = replay.apply(record)
                projected = BookProjection.capture(position, record, outcome, replay)
                if projected != saved.book:
                    raise ValueError(f"{source.name} native book differs at {position}")
                matched += 1
            if matched != len(delivered):
                raise ValueError(f"{source.name} delivery extends beyond verified raw cursor")
            remaining_kinds: dict[str, int] = {}
            for record in raw_records[matched:]:
                remaining_kinds[record.kind] = remaining_kinds.get(record.kind, 0) + 1
            findings[source.name] = {
                "matched_deliveries": matched,
                "available_durable_raw_records": len(raw_records),
                "undelivered_durable_raw_records": len(raw_records) - matched,
                "undelivered_raw_record_kinds": remaining_kinds,
                "status": "pass_available_cursor_prefix"
                if len(raw_records) == matched
                else "unmeasured_unattributed_delivery_tail",
                "request_identity": source.request.identity,
                "raw_capture_root": str(source.capture_root),
                "delivery_path": str(source.delivery_path),
                "trace_identity": replay.summary()["trace_identity"],
            }
        return findings


class _DashboardReader:
    """Reuse bounded query components while selecting current SQLite revisions every time."""

    def __init__(
        self,
        store: TelemetryStore,
        scope: str,
        mode: Literal["paper", "shadow"],
        config: DashboardConfig,
        registry: MetricRegistry,
    ) -> None:
        """Bind immutable metric selection and one process-owned telemetry reader."""
        self.store, self.scope, self.mode = store, scope, mode
        self.config, self.registry = config, registry
        self.renderer = DashboardRenderer(config, registry)
        self.codec = DomainCodec()

    @classmethod
    def open(
        cls, service_root: Path, account_id: str, mode: Literal["paper", "shadow"]
    ) -> _DashboardReader:
        """Resolve installed metric identities before the measured read interval."""
        at = datetime.now(UTC)
        query = MonitoringQuery(
            scope=f"account:{account_id}",
            mode=mode,
            start=at - timedelta(hours=1),
            end=at,
            as_of=at,
            limit=10_000,
        )
        selection = MonitoringConfiguration.defaults(query)
        return cls(
            TelemetryStore(service_root / "monitoring" / "telemetry.sqlite3"),
            query.scope,
            mode,
            selection.dashboard,
            MetricRegistry(MonitoringDefinitions.resolve(selection.metrics)),
        )

    def read(self, at: datetime) -> dict[str, object]:
        """Query and render one exact one-hour snapshot at its current causal cutoff."""
        query = MonitoringQuery(
            scope=self.scope,
            mode=self.mode,
            start=at - timedelta(hours=1),
            end=at,
            as_of=at,
            limit=10_000,
        )
        selection = self.store.select(query)
        rendered, identity = self.renderer.render(query, selection)
        return {
            "scope": query.scope,
            "event_count": len(selection.rows),
            "event_bytes": sum(len(row.payload) for row in selection.rows),
            "returned_bytes": len(rendered),
            "result_sha256": identity,
            "scan_bytes": None,
            "scan_unavailable_reason": "telemetry_store_scan_bytes_not_exposed",
        }

    def wait_for_schema(self, output: Path, deadline: float) -> dict[str, object]:
        """Wait only at startup for a committed telemetry schema within the shared deadline."""
        started = time.monotonic()
        attempt = 0
        while (remaining := deadline - time.monotonic()) > 0:
            status = "not_created"
            detail: str | None = None
            if self.store.path.is_file():
                try:
                    with closing(
                        sqlite3.connect(
                            f"{self.store.path.resolve().as_uri()}?mode=ro",
                            uri=True,
                            timeout=min(0.05, remaining),
                        )
                    ) as connection:
                        connection.execute("BEGIN")
                        tables = cast(
                            list[tuple[str]],
                            connection.execute(
                                "SELECT name FROM sqlite_master WHERE type='table'"
                            ).fetchall(),
                        )
                        names = {row[0] for row in tables}
                        if not names:
                            status = "schema_not_committed"
                        elif names != {"metadata", "events"}:
                            raise ValueError("dashboard startup selected a nontelemetry schema")
                        else:
                            metadata = cast(
                                list[tuple[object, ...]],
                                connection.execute(
                                    "SELECT version, floor FROM metadata"
                                ).fetchall(),
                            )
                            if len(metadata) != 1 or metadata[0][0] != "telemetry-store":
                                raise ValueError(
                                    "dashboard startup has unsupported telemetry metadata"
                                )
                            status = "ready"
                except sqlite3.OperationalError as error:
                    if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        raise
                    status, detail = "sqlite_locked", str(error)
            with (output / "schema-readiness.jsonl").open("ab") as stream:
                stream.write(
                    self.codec.encode_json(
                        {
                            "attempt": attempt,
                            "at": datetime.now(UTC),
                            "monotonic_ns": time.monotonic_ns(),
                            "status": status,
                            "error": detail,
                        }
                    )
                    + b"\n"
                )
            attempt += 1
            if status == "ready" and time.monotonic() < deadline:
                return {
                    "status": status,
                    "attempts": attempt,
                    "seconds": time.monotonic() - started,
                }
            time.sleep(max(0.0, min(0.02, deadline - time.monotonic())))
        raise TimeoutError(
            "dashboard telemetry schema did not become ready within startup deadline"
        )


class _ResourceSampler:
    """Sample selected service process trees and occupied roots every second."""

    def __init__(
        self, pids: tuple[int, ...], roots: tuple[Path, ...], output: Path, phases: Path
    ) -> None:
        """Bind only explicitly owned service roots and process identities."""
        self.pids, self.roots, self.output, self.phases = pids, roots, output, phases
        self.previous_cpu: dict[tuple[int, float], float] = {}
        self.previous_io: dict[tuple[int, float], tuple[int, int]] = {}
        self.previous_at: float | None = None
        self.failures: list[str] = []
        self.count = 0
        self.visible_process_samples = 0
        self.rss_samples: list[int] = []
        self.cpu_samples: list[float] = []
        self.occupied_samples: list[int] = []
        self.sampled_read_bytes = 0
        self.sampled_write_bytes = 0
        self.io_unavailable_samples = 0
        self._tree: dict[int, _SampledProcess] | None = None
        self._tree_at = 0.0

    def _discover(self) -> dict[int, _SampledProcess]:
        """Resolve the selected root processes and all of their current descendants."""
        processes: dict[int, _SampledProcess] = {}
        for pid in self.pids:
            try:
                process = cast(_SampledProcess, psutil.Process(pid))  # type: ignore[misc]  # [owner=runtime; rationale=untyped psutil constructor confined to typed process-tree sampler; expires=2027-02-01]
                processes[pid] = process
                for child in process.children(recursive=True):
                    processes[child.pid] = child
            except _NO_SUCH_PROCESS:
                self.failures.append(f"process_missing:{pid}")
            except OSError, _ACCESS_DENIED:
                self.failures.append(f"process_tree_unavailable:{pid}")
        if not processes:
            self.failures.append("no_visible_processes")
        return processes

    def _scan_disk(self) -> tuple[int, int, int]:
        """Sum logical and allocated bytes of regular files under every selected root."""
        logical_bytes, occupied_bytes, file_count = 0, 0, 0
        seen_paths: set[str] = set()
        pending = [str(root) for root in self.roots]
        while pending:
            try:
                with os.scandir(pending.pop()) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(entry.path)
                            elif entry.path not in seen_paths and entry.is_file():
                                seen_paths.add(entry.path)
                                stat = entry.stat()
                                logical_bytes += stat.st_size
                                occupied_bytes += stat.st_blocks * 512
                                file_count += 1
                        except FileNotFoundError:
                            continue
            except FileNotFoundError, NotADirectoryError:
                continue
        return logical_bytes, occupied_bytes, file_count

    def sample(self, *, steady_started: float) -> None:
        """Retain one process-tree, I/O and allocated-disk observation.

        Whole-host process discovery can exceed the one-second slot under load, so
        tree membership is refreshed every few seconds or after a tracked process
        exits. Counters for every tracked process are still read each second.
        """
        phase_started = time.perf_counter()
        at = time.monotonic()
        refreshed = self._tree is None or at - self._tree_at >= _TREE_REFRESH_SECONDS
        if refreshed:
            self._tree, self._tree_at = self._discover(), at
        processes = cast(dict[int, _SampledProcess], self._tree)
        discovery_finished = time.perf_counter()
        rss = 0
        cpu_delta = 0.0
        io_read = 0
        io_write = 0
        io_delta_read = 0
        io_delta_write = 0
        io_supported = bool(processes)
        current_cpu: dict[tuple[int, float], float] = {}
        current_io: dict[tuple[int, float], tuple[int, int]] = {}
        for process in processes.values():
            try:
                identity = (process.pid, process.create_time())
                rss += process.memory_info().rss
                clocks = process.cpu_times()
                cumulative = clocks.user + clocks.system
                prior = self.previous_cpu.get(identity)
                if prior is not None:
                    cpu_delta += max(0.0, cumulative - prior)
                current_cpu[identity] = cumulative
                try:
                    counters = process.io_counters()
                except OSError, _ACCESS_DENIED, AttributeError, NotImplementedError:
                    io_supported = False
                else:
                    io_read += counters.read_bytes
                    io_write += counters.write_bytes
                    current_io[identity] = counters.read_bytes, counters.write_bytes
                    prior_io = self.previous_io.get(identity)
                    if prior_io is not None:
                        io_delta_read += max(0, counters.read_bytes - prior_io[0])
                        io_delta_write += max(0, counters.write_bytes - prior_io[1])
            except _NO_SUCH_PROCESS:
                self.failures.append(f"process_exited:{process.pid}")
                self._tree = None
            except OSError, _ACCESS_DENIED:
                self.failures.append(f"process_counters_unavailable:{process.pid}")
        counters_finished = time.perf_counter()
        elapsed = None if self.previous_at is None else at - self.previous_at
        logical_cpus = None if elapsed is None or elapsed <= 0 else cpu_delta / elapsed
        self.previous_at, self.previous_cpu, self.previous_io = at, current_cpu, current_io
        if logical_cpus is not None:
            self.cpu_samples.append(logical_cpus)
        self.rss_samples.append(rss)
        if io_supported:
            self.sampled_read_bytes += io_delta_read
            self.sampled_write_bytes += io_delta_write
        else:
            self.io_unavailable_samples += 1
        logical_bytes, occupied_bytes, file_count = self._scan_disk()
        disk_finished = time.perf_counter()
        self.count += 1
        if current_cpu:
            self.visible_process_samples += 1
        self.occupied_samples.append(occupied_bytes)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        write_started = time.perf_counter()
        with self.output.open("ab") as stream:
            stream.write(
                DomainCodec().encode_json(
                    {
                        "steady_offset_seconds": at - steady_started,
                        "sampled_at_utc": datetime.now(UTC).isoformat(),
                        "processes": len(current_cpu),
                        "rss_bytes": rss,
                        "logical_cpus": logical_cpus,
                        "cpu_delta_seconds": cpu_delta,
                        "io_read_bytes_cumulative": io_read if io_supported else None,
                        "io_write_bytes_cumulative": io_write if io_supported else None,
                        "io_read_bytes_sampled_delta": io_delta_read if io_supported else None,
                        "io_write_bytes_sampled_delta": io_delta_write if io_supported else None,
                        "io_unavailable_reason": None
                        if io_supported
                        else "os_process_counter_unavailable",
                        "occupied_bytes": occupied_bytes,
                        "logical_bytes": logical_bytes,
                        "file_count": file_count,
                    }
                )
                + b"\n"
            )
        write_finished = time.perf_counter()
        with self.phases.open("ab") as stream:
            stream.write(
                DomainCodec().encode_json(
                    {
                        "sample": self.count,
                        "steady_offset_seconds": at - steady_started,
                        "process_tree_age_seconds": at - self._tree_at,
                        "process_discovery_seconds": discovery_finished - phase_started,
                        "process_counters_seconds": counters_finished - discovery_finished,
                        "disk_scan_seconds": disk_finished - counters_finished,
                        "sample_write_seconds": write_finished - write_started,
                        "sample_total_seconds": write_finished - phase_started,
                    }
                )
                + b"\n"
            )

    @staticmethod
    def run_process(
        pids: tuple[int, ...],
        roots: tuple[Path, ...],
        output: Path,
        control: Connection[object, object],
        stop_signal: _StopSignal,
        duration_seconds: int,
    ) -> None:
        """Run one-Hz resource observation outside the eight read workers' GIL."""
        codec = DomainCodec()
        sampler = _ResourceSampler(
            pids, roots, output / "resources.jsonl", output / "resource-phases.jsonl"
        )
        try:
            control.send("ready")
            schedule: object = control.recv()
            if (
                not isinstance(schedule, tuple)
                or len(schedule) != 2
                or type(schedule[0]) is not float
                or type(schedule[1]) is not float
                or schedule[1] <= schedule[0]
            ):
                raise ValueError("resource sampler received no valid steady interval")
            started, stop = cast(tuple[float, float], schedule)
            slot = 0
            while (due := started + slot) < stop and not stop_signal.is_set():
                remaining = due - time.monotonic()
                if remaining > 0 and stop_signal.wait(remaining):
                    break
                if stop_signal.is_set() or time.monotonic() >= stop:
                    break
                try:
                    sampler.sample(steady_started=started)
                except (OSError, ValueError, TypeError) as error:
                    sampler.failures.append(f"resource_sampler:{type(error).__name__}:{error}")
                    break
                slot = max(slot + 1, math.floor(time.monotonic() - started) + 1)
            with (output / "resources-summary.json").open("xb") as stream:
                stream.write(
                    codec.encode_json(
                        CapacityReadObserver._resource_summary(sampler, duration_seconds)
                    )
                )
        except Exception as error:
            with (output / "resources-failure.json").open("xb") as stream:
                stream.write(
                    codec.encode_json({"error": type(error).__name__, "reason": str(error)})
                )
            raise
        finally:
            control.close()


class CapacityReadObserver:
    """Measure steady local depth and dashboard reads at the declared reader rate."""

    def __init__(
        self,
        output: Path,
        service_root: Path,
        *,
        process_pids: tuple[int, ...],
        occupied_roots: tuple[Path, ...] = (),
        duration_seconds: int = 60,
        features: bool = False,
        feature_cohort: Literal["initial_steady", "recovery_steady"] = "initial_steady",
    ) -> None:
        """Bind a fresh evidence directory and explicit local process/disk scope.

        The 60-second default yields 1,200 requested samples per query class.
        Resource demand excludes this diagnostic process unless explicitly supplied.
        """
        if duration_seconds < 1 or not 1 <= len(process_pids) <= 16:
            raise ValueError("read observer requires a positive interval and owned process IDs")
        self.output, self.service_root = output, service_root
        self.process_pids = process_pids
        self.occupied_roots = occupied_roots or (service_root,)
        self.duration_seconds = duration_seconds
        self.features = features
        self.feature_cohort = feature_cohort
        self.codec = DomainCodec()
        self._samples: dict[str, list[float]] = {"depth_bbo": [], "dashboard": []}
        self._failures: dict[str, int] = {"depth_bbo": 0, "dashboard": 0}
        self._write_lock = threading.Lock()

    def _discover(self) -> tuple[PaperServiceConfiguration, _RetainedBookIndex]:
        """Resolve the current service run and exact source recordings after startup."""
        config = self.codec.decode_json(
            (self.service_root / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        status = self.codec.decode_json(
            (self.service_root / "status.json").read_bytes(), _ServiceRun
        )
        run_id = status.run_id
        if type(run_id) is not str or not run_id:
            raise ValueError("service status has no current run identity")
        run_root = self.service_root / "runs" / run_id
        sources: list[_SourceIndex] = []
        for definition in config.sources:
            source_root = run_root / definition.name
            request_paths = tuple(source_root.glob("*/*/request.json"))
            if len(request_paths) != 1:
                raise ValueError(f"{definition.name} requires one current capture request")
            request_path = request_paths[0]
            request = self.codec.decode_json(request_path.read_bytes(), CaptureRequest)
            if (
                request.config != definition.capture
                or request_path.parent.name != request.recording_id
                or request_path.parent.parent.name != request.recording_id
            ):
                raise ValueError(f"{definition.name} capture differs from service selection")
            deliveries = tuple(sorted(source_root.glob(f"{request.recording_id}-*.jsonl")))
            if not deliveries:
                raise ValueError(f"{definition.name} has no retained delivery stream")
            sources.append(
                _SourceIndex(
                    definition.name,
                    request,
                    request_path.parent,
                    deliveries[0],
                    10_000,
                )
            )
        if len(sources) != 4 or len(config.accounts) != 4:
            raise ValueError("declared steady read workload requires four sources and accounts")
        return config, _RetainedBookIndex(config, tuple(sources))

    def _record(self, sample: dict[str, object]) -> None:
        """Append one individual duration and result identity without reducing evidence."""
        stage = sample["boundary"]
        if stage not in ("depth_bbo", "dashboard"):
            raise ValueError("unknown read boundary")
        with self._write_lock:
            if sample["status"] == "ok" and sample["completed_within_interval"]:
                self._samples[stage].append(cast(float, sample["seconds"]))
            else:
                self._failures[stage] += 1
            with (self.output / "samples.jsonl").open("ab") as stream:
                stream.write(self.codec.encode_json(sample) + b"\n")

    def _depth_worker(
        self, index: _RetainedBookIndex, source_name: str, started: float, stop: float
    ) -> None:
        """Issue one causal depth/BBO read every 200 ms for a selected source."""
        self._paced_worker("depth_bbo", source_name, started, stop, index)

    def _dashboard_worker(
        self, account_id: str, mode: Literal["paper", "shadow"], started: float, stop: float
    ) -> None:
        """Issue one one-hour telemetry query and exact render every 200 ms."""
        reader = _DashboardReader.open(self.service_root, account_id, mode)
        self._paced_worker("dashboard", account_id, started, stop, reader)

    @staticmethod
    def _dashboard_process(
        output: Path,
        service_root: Path,
        account_id: str,
        mode: Literal["paper", "shadow"],
        control: Connection[object, object],
        duration_seconds: int,
    ) -> None:
        """Warm one independent dashboard reader, then follow the parent's exact interval."""
        output.mkdir(parents=True, exist_ok=False)
        codec = DomainCodec()
        startup_started = time.monotonic_ns()
        try:
            observer = CapacityReadObserver(
                output,
                service_root,
                process_pids=(os.getpid(),),
                duration_seconds=duration_seconds,
            )
            startup_deadline = control.recv()
            if type(startup_deadline) is not float or not math.isfinite(startup_deadline):
                raise ValueError("dashboard reader received no valid startup deadline")
            reader = _DashboardReader.open(service_root, account_id, mode)
            schema_readiness = reader.wait_for_schema(output, startup_deadline)
            warmup = reader.read(datetime.now(UTC))
            (output / "startup.json").write_bytes(
                codec.encode_json(
                    {
                        "reader_id": account_id,
                        "pid": os.getpid(),
                        "seconds": (time.monotonic_ns() - startup_started) / 1_000_000_000,
                        "cache_class": "warm_initialized_components_and_exact_payload_reuse",
                        "warmup": warmup,
                        "schema_readiness": schema_readiness,
                    }
                )
            )
            control.send("ready")
            schedule = control.recv()
            if (
                type(schedule) is not tuple
                or len(schedule) != 2
                or type(schedule[0]) is not float
                or type(schedule[1]) is not float
            ):
                raise ValueError("dashboard reader received no valid steady interval")
            started, stop = cast(tuple[float, float], schedule)
            observer._paced_worker("dashboard", account_id, started, stop, reader)
        except Exception as error:
            (output / "failure.json").write_bytes(
                codec.encode_json({"error": type(error).__name__, "reason": str(error)})
            )
            raise
        finally:
            control.close()

    def _paced_worker(
        self,
        boundary: Literal["depth_bbo", "dashboard"],
        target: str,
        started: float,
        stop: float,
        binding: _RetainedBookIndex | _DashboardReader,
    ) -> None:
        """Retain missed slots instead of concealing an overloaded reader schedule."""
        started_ns = round(started * 1_000_000_000)
        stop_ns = round(stop * 1_000_000_000)
        slots = math.ceil((stop - started) * 5)
        slot = 0
        while slot < slots:
            due_ns = started_ns + slot * 200_000_000
            while (remaining_ns := due_ns - time.monotonic_ns()) > 0:
                time.sleep(remaining_ns / 1_000_000_000)
            measured_ns = time.monotonic_ns()
            if measured_ns >= stop_ns:
                self._missed_slots(boundary, target, slot, slots, started_ns, stop_ns)
                break
            query_at = datetime.now(UTC)
            try:
                if boundary == "depth_bbo":
                    if not isinstance(binding, _RetainedBookIndex):
                        raise TypeError("depth reader requires native retained index")
                    result = binding.read(target, cutoff_ns=binding._unix_ns(query_at))
                else:
                    if not isinstance(binding, _DashboardReader):
                        raise TypeError("dashboard reader requires retained monitoring bindings")
                    result = binding.read(query_at)
                status = "ok"
            except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error) as error:
                result = {"error": type(error).__name__, "reason": str(error)}
                status = "failed"
            completed_ns = time.monotonic_ns()
            self._record(
                {
                    "boundary": boundary,
                    "reader_id": target,
                    "target": target,
                    "phase": "steady",
                    "slot": slot,
                    "request_index": slot,
                    "scheduled_monotonic_ns": due_ns,
                    "started_monotonic_ns": measured_ns,
                    "completed_monotonic_ns": completed_ns,
                    "scheduled_stop_monotonic_ns": stop_ns,
                    "completed_within_interval": completed_ns <= stop_ns,
                    "queue_delay_seconds": (measured_ns - due_ns) / 1_000_000_000,
                    "response_seconds": (completed_ns - due_ns) / 1_000_000_000,
                    "started_offset_seconds": (measured_ns - started_ns) / 1_000_000_000,
                    "at_utc": query_at.isoformat(),
                    "seconds": (completed_ns - measured_ns) / 1_000_000_000,
                    "status": status,
                    **result,
                }
            )
            slot += 1

    def _missed_slots(
        self,
        boundary: Literal["depth_bbo", "dashboard"],
        target: str,
        start: int,
        end: int,
        started_ns: int,
        stop_ns: int,
    ) -> None:
        """Retain every omitted due request without treating it as a latency observation."""
        for slot in range(start, end):
            self._record(
                {
                    "boundary": boundary,
                    "reader_id": target,
                    "target": target,
                    "phase": "steady",
                    "slot": slot,
                    "request_index": slot,
                    "scheduled_monotonic_ns": started_ns + slot * 200_000_000,
                    "started_monotonic_ns": None,
                    "completed_monotonic_ns": None,
                    "scheduled_stop_monotonic_ns": stop_ns,
                    "completed_within_interval": False,
                    "queue_delay_seconds": None,
                    "response_seconds": None,
                    "started_offset_seconds": None,
                    "at_utc": None,
                    "seconds": 0.0,
                    "status": "missed",
                    "reason": "reader_schedule_backlog_or_interval_complete",
                }
            )

    def _poll(self, index: _RetainedBookIndex, stop_event: threading.Event) -> None:
        """Keep read state aligned with fsynced complete delivery records."""
        try:
            while not stop_event.is_set():
                index.poll()
                stop_event.wait(0.05)
        except (OSError, ValueError, TypeError) as error:
            (self.output / "poll-failure.json").write_bytes(
                self.codec.encode_json({"error": type(error).__name__, "reason": str(error)})
            )
            stop_event.set()

    @staticmethod
    def _summary(values: list[float], failures: int) -> dict[str, object]:
        """Report nearest-rank warm percentiles only from at least 1,000 successes."""
        ordered = sorted(values)
        result: dict[str, object] = {
            "success_count": len(ordered),
            "failure_count": failures,
            "min_seconds": ordered[0] if ordered else None,
            "max_seconds": ordered[-1] if ordered else None,
            "percentile_method": "empirical_nearest_rank",
        }
        if len(ordered) >= 1000:
            result["p50_seconds"] = ordered[math.ceil(0.50 * len(ordered)) - 1]
            result["p95_seconds"] = ordered[math.ceil(0.95 * len(ordered)) - 1]
            result["p99_seconds"] = ordered[math.ceil(0.99 * len(ordered)) - 1]
        else:
            result["percentile_unavailable_reason"] = "fewer_than_1000_successful_steady_samples"
        return result

    @staticmethod
    def _resource_summary(sampler: _ResourceSampler, expected_samples: int) -> dict[str, object]:
        """Summarize sampled demand without claiming an underpowered CPU percentile."""
        return {
            "scope": "selected_pid_roots_and_descendants_including_diagnostic_if_selected",
            "pid_roots": sampler.pids,
            "occupied_roots": tuple(str(root) for root in sampler.roots),
            "samples": sampler.count,
            "visible_process_samples": sampler.visible_process_samples,
            "expected_one_hertz_samples": expected_samples,
            "status": "pass"
            if sampler.count >= expected_samples
            and sampler.visible_process_samples == sampler.count
            and not sampler.failures
            else "fail"
            if sampler.count
            else "unmeasured",
            "sampling_failures": sampler.failures,
            "cpu_average_logical_cores": (
                sum(sampler.cpu_samples) / len(sampler.cpu_samples) if sampler.cpu_samples else None
            ),
            "cpu_peak_logical_cores": max(sampler.cpu_samples, default=None),
            "cpu_p95_status": "not_measured_fewer_than_1000_samples",
            "peak_rss_bytes": max(sampler.rss_samples, default=None),
            "peak_occupied_bytes": max(sampler.occupied_samples, default=None),
            "io_read_bytes_sampled": (
                sampler.sampled_read_bytes if sampler.io_unavailable_samples == 0 else None
            ),
            "io_write_bytes_sampled": (
                sampler.sampled_write_bytes if sampler.io_unavailable_samples == 0 else None
            ),
            "io_unavailable_samples": sampler.io_unavailable_samples,
        }

    def run(self, *, on_interval_complete: Callable[[], None] | None = None) -> dict[str, object]:
        """Run the exact eight-reader schedule and retain every observation and refusal.

        The caller starts this only after the signed local services are active. The
        startup/discovery interval is excluded from all warm latency percentiles.
        An optional callback runs as soon as the steady readers stop, before
        independent raw replay; it can request orderly service shutdown.
        Optional feature serving composes the retained native sources with the
        existing versioned store during this same finite interval.
        """
        self.output.mkdir(parents=True, exist_ok=False)
        discovery_started = time.perf_counter()
        try:
            config, index = self._discover()
            index.poll()
        except (OSError, ValueError, TypeError) as error:
            (self.output / "failure.json").write_bytes(
                self.codec.encode_json(
                    {
                        "phase": "startup",
                        "error": type(error).__name__,
                        "reason": str(error),
                    }
                )
            )
            raise
        startup_seconds = time.perf_counter() - discovery_started
        if any(source.deliveries == 0 for source in index.sources.values()):
            (self.output / "failure.json").write_bytes(
                self.codec.encode_json(
                    {
                        "phase": "startup",
                        "error": "MissingDelivery",
                        "reason": "steady read interval requires a retained delivery per source",
                    }
                )
            )
            raise ValueError("steady read interval requires a retained delivery per source")
        feature_observer = (
            CapacityFeatureObserver(
                self.output / "features",
                config,
                index,
                measurement_root=self.service_root.parent / "measurements",
                cohort=self.feature_cohort,
            )
            if self.features
            else None
        )
        if feature_observer is not None:
            feature_observer.prepare()
        sampler_started = time.perf_counter()
        context = multiprocessing.get_context("spawn")
        parent_control, child_control = cast(
            "tuple[Connection[object, object], Connection[object, object]]", context.Pipe()
        )
        sampler_stop = context.Event()
        sampler_process = context.Process(
            target=_ResourceSampler.run_process,
            args=(
                self.process_pids,
                self.occupied_roots,
                self.output,
                child_control,
                sampler_stop,
                self.duration_seconds,
            ),
            daemon=True,
        )
        started_process = False
        dashboard_processes: list[tuple[str, BaseProcess, Connection[object, object]]] = []
        startup_phase = "resource_sampler_startup"
        try:
            sampler_process.start()
            started_process = True
            child_control.close()
            if not parent_control.poll(5) or parent_control.recv() != "ready":
                raise TimeoutError("capacity resource sampler did not become ready")
            sampler_startup_seconds = time.perf_counter() - sampler_started
            startup_phase = "dashboard_reader_startup"
            reader_started = time.perf_counter()
            for account in config.accounts:
                reader_control, reader_child = cast(
                    "tuple[Connection[object, object], Connection[object, object]]",
                    context.Pipe(),
                )
                reader_process: BaseProcess = context.Process(
                    target=self._dashboard_process,
                    args=(
                        self.output / "dashboard-readers" / account.account_id,
                        self.service_root,
                        account.account_id,
                        account.configuration.mode,
                        reader_child,
                        self.duration_seconds,
                    ),
                    daemon=True,
                )
                try:
                    reader_process.start()
                finally:
                    reader_child.close()
                dashboard_processes.append((account.account_id, reader_process, reader_control))
            reader_deadline = time.monotonic() + 5
            for _, _, reader_control in dashboard_processes:
                reader_control.send(reader_deadline)
            for account_id, _, reader_control in dashboard_processes:
                if (
                    not reader_control.poll(max(0.0, reader_deadline - time.monotonic()))
                    or reader_control.recv() != "ready"
                ):
                    raise TimeoutError(f"dashboard reader {account_id} did not become ready")
            reader_startup_seconds = time.perf_counter() - reader_started
            started_at_utc = datetime.now(UTC)
            started = time.monotonic()
            stop = started + self.duration_seconds
            parent_control.send((started, stop))
            for _, _, reader_control in dashboard_processes:
                reader_control.send((started, stop))
        except Exception as error:
            sampler_stop.set()
            if started_process and sampler_process.is_alive():
                sampler_process.terminate()
                sampler_process.join(2)
            for _, reader_process, _ in dashboard_processes:
                if reader_process.is_alive():
                    reader_process.terminate()
                reader_process.join(2)
            (self.output / "failure.json").write_bytes(
                self.codec.encode_json(
                    {
                        "phase": startup_phase,
                        "error": type(error).__name__,
                        "reason": str(error),
                        "dashboard_reader_processes": {
                            account_id: {
                                "pid": reader_process.pid,
                                "exitcode": reader_process.exitcode,
                                "alive_after_join": reader_process.is_alive(),
                            }
                            for account_id, reader_process, _ in dashboard_processes
                        },
                        "resource_sampler_process": {
                            "pid": sampler_process.pid,
                            "exitcode": sampler_process.exitcode,
                            "alive_after_join": sampler_process.is_alive(),
                        },
                    }
                )
            )
            raise
        finally:
            parent_control.close()
            child_control.close()
            for _, _, reader_control in dashboard_processes:
                reader_control.close()
        stop_event = threading.Event()
        threads = [threading.Thread(target=self._poll, args=(index, stop_event), daemon=True)]
        threads.extend(
            threading.Thread(
                target=self._depth_worker,
                args=(index, name, started, stop),
                daemon=True,
            )
            for name in index.sources
        )
        for thread in threads:
            thread.start()
        if feature_observer is not None:
            feature_observer.start(started, stop)
        remaining = stop - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        steady_ended = time.monotonic()
        steady_ended_at_utc = datetime.now(UTC)
        stop_event.set()
        sampler_stop.set()
        postprocess_error: Exception | None = None
        parity: dict[str, dict[str, object]] | None = None
        postprocess_phase = "interval_complete_callback"
        try:
            if on_interval_complete is not None:
                on_interval_complete()
        except Exception as error:
            postprocess_error = error
        join_deadline = steady_ended + 5
        for thread in threads:
            thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
        for _, reader_process, _ in dashboard_processes:
            reader_process.join(timeout=max(0.0, join_deadline - time.monotonic()))
        stuck_readers = any(reader.is_alive() for _, reader, _ in dashboard_processes)
        if (
            any(thread.is_alive() for thread in threads) or stuck_readers
        ) and postprocess_error is None:
            postprocess_phase = "read_worker_join"
            postprocess_error = TimeoutError(
                "capacity read worker did not stop within bounded interval"
            )
        for _, reader_process, _ in dashboard_processes:
            if reader_process.is_alive():
                reader_process.terminate()
                reader_process.join(2)
        for account_id, reader_process, _ in dashboard_processes:
            samples = self.output / "dashboard-readers" / account_id / "samples.jsonl"
            if samples.is_file():
                for line in samples.read_bytes().splitlines():
                    self._record(msgspec.json.decode(line, type=dict[str, object]))
            if reader_process.exitcode != 0 and postprocess_error is None:
                postprocess_phase = "dashboard_reader"
                postprocess_error = RuntimeError(f"dashboard reader {account_id} failed")
        feature_summary: dict[str, object] = {
            "status": "not_measured",
            "reason": "integrated_feature_workload_not_selected",
        }
        if feature_observer is not None:
            feature_summary = feature_observer.finish(join_deadline)
            if feature_summary["status"] == "fail" and postprocess_error is None:
                postprocess_phase = "integrated_feature_serving"
                postprocess_error = RuntimeError("integrated feature workload did not complete")
        if postprocess_error is None:
            postprocess_phase = "native_replay_parity"
            try:
                index.poll()
                parity = index.replay_parity()
            except Exception as error:
                postprocess_error = error
        if postprocess_error is not None:
            (self.output / "failure.json").write_bytes(
                self.codec.encode_json(
                    {
                        "phase": postprocess_phase,
                        "error": type(postprocess_error).__name__,
                        "reason": str(postprocess_error),
                    }
                )
            )
        sampler_process.join(timeout=5)
        if sampler_process.is_alive():
            sampler_process.terminate()
            sampler_process.join(2)
        resource_path = self.output / "resources-summary.json"
        resources: dict[str, object] = (
            msgspec.json.decode(resource_path.read_bytes(), type=dict[str, object])
            if resource_path.is_file() and sampler_process.exitcode == 0
            else {
                "status": "unmeasured",
                "reason": "resource_sampler_process_did_not_complete",
                "pid_roots": self.process_pids,
                "occupied_roots": tuple(str(root) for root in self.occupied_roots),
            }
        )
        if resources["status"] == "unmeasured" and postprocess_error is None:
            postprocess_error = RuntimeError("resource sampler process did not complete")
            postprocess_phase = "resource_sampler"
            (self.output / "failure.json").write_bytes(
                self.codec.encode_json(
                    {
                        "phase": postprocess_phase,
                        "error": type(postprocess_error).__name__,
                        "reason": str(postprocess_error),
                    }
                )
            )
        interval = {
            "started_monotonic_ns": round(started * 1_000_000_000),
            "steady_ended_monotonic_ns": round(steady_ended * 1_000_000_000),
            "scheduled_stop_monotonic_ns": round(stop * 1_000_000_000),
            "started_at_utc": started_at_utc.isoformat(),
            "steady_ended_at_utc": steady_ended_at_utc.isoformat(),
            "steady_duration_seconds": self.duration_seconds,
            "steady_elapsed_seconds": steady_ended - started,
            "postprocess_elapsed_seconds": time.monotonic() - steady_ended,
            "startup_discovery_seconds": startup_seconds,
            "startup_sampler_seconds": sampler_startup_seconds,
            "startup_dashboard_seconds": reader_startup_seconds,
            "cache_class": "warm_initialized_components_and_exact_payload_reuse",
            "dashboard_execution": "four_independent_reader_processes",
            "dashboard_reader_processes": {
                account_id: {
                    "pid": reader_process.pid,
                    "exitcode": reader_process.exitcode,
                    "alive_after_join": reader_process.is_alive(),
                }
                for account_id, reader_process, _ in dashboard_processes
            },
            "resource_sampler_process": {
                "pid": sampler_process.pid,
                "exitcode": sampler_process.exitcode,
                "alive_after_join": sampler_process.is_alive(),
            },
            "source_requests": {
                name: source.request.identity for name, source in index.sources.items()
            },
            "source_deliveries": {
                name: source.deliveries for name, source in index.sources.items()
            },
            "depth_bbo": self._summary(self._samples["depth_bbo"], self._failures["depth_bbo"]),
            "dashboard": self._summary(self._samples["dashboard"], self._failures["dashboard"]),
            "feature": feature_summary,
            "resources": resources,
            "native_replay_parity": parity,
            "postprocess_status": "pass" if postprocess_error is None else "fail",
            "postprocess_failure": None
            if postprocess_error is None
            else f"{type(postprocess_error).__name__}: {postprocess_error}",
            "poll_failure": (self.output / "poll-failure.json").exists(),
        }
        (self.output / "summary.json").write_bytes(self.codec.encode_json(interval))
        if postprocess_error is not None:
            raise postprocess_error
        return interval
