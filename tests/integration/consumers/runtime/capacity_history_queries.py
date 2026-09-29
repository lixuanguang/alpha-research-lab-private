"""Measure cold application components and warm queries over frozen populated history.

The read-only native history retains its original clocks and identities. A
separately identified authored telemetry fixture can populate a complete hour
to the 10,000-event query boundary without changing original evidence.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import math
import multiprocessing
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal, cast

# third party library imports
import msgspec
from capacity_reads import (
    CapacityReadObserver,
    _DashboardReader,
    _RetainedBookIndex,
    _SourceIndex,
)
from msgspec.structs import replace

# project library imports
from configuration import PaperServiceConfiguration
from serialization import DomainCodec
from telemetry import MonitoringQuery, TelemetryStore


class _Arguments(argparse.Namespace):
    """Select one frozen trial, one fresh output and a predeclared query sample count."""

    trial: Path
    output: Path
    samples_per_reader: int
    dashboard_events_per_account: int


class _Interval(msgspec.Struct, frozen=True):
    """Use the trial's original cutoff rather than current wall time."""

    steady_ended_at_utc: str


class CapacityHistoryQueries:
    """Own finite independent query measurements with exact result identity checks."""

    def __init__(
        self,
        trial: Path,
        output: Path,
        *,
        samples_per_reader: int,
        dashboard_events_per_account: int,
    ) -> None:
        """Declare counts before reading history and keep generated fixtures outside Git."""
        if not trial.is_absolute() or not output.is_absolute() or output.exists():
            raise ValueError("history queries require an absolute trial and fresh absolute output")
        if not 1 <= samples_per_reader <= 1000:
            raise ValueError("history query sample count must be between 1 and 1000 per reader")
        if not 0 <= dashboard_events_per_account <= 10_000:
            raise ValueError("authored dashboard fixture exceeds the retained query boundary")
        self.trial, self.output = trial, output
        self.samples_per_reader = samples_per_reader
        self.dashboard_events_per_account = dashboard_events_per_account
        self.codec = DomainCodec()
        self.write_lock = threading.Lock()
        self.config: PaperServiceConfiguration | None = None
        self.sources: dict[str, _SourceIndex] = {}
        self.query_at = datetime.fromisoformat(
            self.codec.decode_json(
                (trial / "reads/summary.json").read_bytes(), _Interval
            ).steady_ended_at_utc
        )
        self.dashboard_root = trial / "operating"
        self.expected: dict[str, str] = {}

    def _configuration(self) -> PaperServiceConfiguration:
        """Require the discovered exact four-source and four-owner selection."""
        if self.config is None:
            raise ValueError("history query selection is not prepared")
        return self.config

    def _depth_reader(self, source: _SourceIndex) -> _RetainedBookIndex:
        """Open one instrument's original finite history without loading unrelated sources."""
        return _RetainedBookIndex(
            self._configuration(),
            (
                _SourceIndex(
                    source.name,
                    source.request,
                    source.capture_root,
                    source.delivery_path,
                    10_000,
                ),
            ),
        )

    def _dashboard_reader(self, account_id: str) -> _DashboardReader:
        """Open the existing dashboard path with unchanged versioned metric definitions."""
        account = next(
            account
            for account in self._configuration().accounts
            if account.account_id == account_id
        )
        mode = account.configuration.mode
        if mode not in ("paper", "shadow"):
            raise ValueError("retained history queries require paper or shadow facts")
        return _DashboardReader.open(self.dashboard_root, account_id, mode)

    def _populate_dashboard(self) -> dict[str, object]:
        """Create explicit authored one-hour clocks while retaining original source event bytes."""
        if not self.dashboard_events_per_account:
            return {"basis": "original_retained_trial", "path": str(self.dashboard_root)}
        original = TelemetryStore(self.trial / "operating/monitoring/telemetry.sqlite3")
        self.dashboard_root = self.output / "authored-dashboard"
        target = TelemetryStore(
            self.dashboard_root / "monitoring/telemetry.sqlite3",
            max_events=self.dashboard_events_per_account * 4,
        )
        target.path.parent.mkdir(parents=True, exist_ok=True)
        accounts: list[dict[str, object]] = []
        for account in self._configuration().accounts:
            query = MonitoringQuery(
                scope=f"account:{account.account_id}",
                mode=account.configuration.mode,
                start=self.query_at - timedelta(hours=1),
                end=self.query_at,
                as_of=self.query_at,
                limit=10_000,
            )
            source = original.query(query)
            if not source:
                raise ValueError("representative dashboard requires populated original events")
            generated = []
            count = self.dashboard_events_per_account
            for index in range(count):
                event = source[index % len(source)]
                # Reserve five seconds at the upper cutoff for original
                # availability delays; late data still obeys its relative clock.
                at = (
                    self.query_at
                    - timedelta(hours=1)
                    + timedelta(microseconds=1_000_000 + index * 3_594_000_000 // max(1, count - 1))
                )
                shift = at - event.at
                generated.append(
                    replace(
                        event,
                        sample=f"history-query:{index}:{event.sample}",
                        at=at,
                        available_at=event.available_at + shift,
                        recorded_at=event.recorded_at + shift,
                    )
                )
            target.append(tuple(generated))
            accounts.append(
                {
                    "account": account.account_id,
                    "original_events": len(source),
                    "original_events_sha256": hashlib.sha256(
                        self.codec.encode_json(source)
                    ).hexdigest(),
                    "authored_events": len(generated),
                    "authored_events_sha256": hashlib.sha256(
                        self.codec.encode_json(tuple(generated))
                    ).hexdigest(),
                }
            )
        return {
            "basis": "authored_time_shifted_copies_of_exact_retained_public_paper_telemetry",
            "original_clocks": "remain_unchanged_in_original_trial",
            "corpus_qualification": "not_applicable_authored_query_workload",
            "path": str(target.path),
            "hard_event_limit": target.max_events,
            "query_window_seconds": 3600,
            "accounts": tuple(accounts),
        }

    def prepare(self) -> dict[str, object]:
        """Freeze source identities and matched-cutoff expected results before qualification."""
        self.output.mkdir(parents=True, exist_ok=False)
        observer = CapacityReadObserver(
            self.output,
            self.trial / "operating",
            process_pids=(os.getpid(),),
        )
        self.config, index = observer._discover()
        self.sources = index.sources
        plan: dict[str, object] = {
            "schema_version": "retained-history-query-sampling-v1",
            "trial": str(self.trial),
            "configuration": self.config.identity,
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "samples_per_reader_per_cache_class": self.samples_per_reader,
            "readers_per_boundary": 4,
            "minimum_percentile_samples_per_boundary_cache_class": 1000,
            "scheduled_cadence_ns": 200_000_000,
            "cold_budget_p99_ns": {"depth_bbo": 2_000_000_000, "dashboard": 3_000_000_000},
            "warm_budget_ms": {"depth_bbo": (50, 200, 500), "dashboard": (100, 400, 1000)},
            "query_at": self.query_at,
            "application_cold_boundary": "fresh_components_durable_index_open_query_render",
            "process_initialization": "excluded_imports_and_interpreter_are_already_loaded",
            "filesystem_cache": "uncontrolled_reads_after_frozen_history_preparation",
            "native_history_basis": "complete_actual_retained_bounded_trial",
            "longer_native_history": (
                "remaining_dependency_representative_sustained_retained_history"
            ),
        }
        # Publish the declaration before fixture creation or timed operations.
        (self.output / "sampling-plan.json").write_bytes(self.codec.encode_json(plan))
        began = time.monotonic_ns()
        dashboard = self._populate_dashboard()
        sources: list[dict[str, object]] = []
        for name, source in self.sources.items():
            reader = self._depth_reader(source)
            result = reader.read(name, cutoff_ns=reader._unix_ns(self.query_at))
            self.expected[name] = self._identity(result)
            sources.append(
                {
                    "source": name,
                    "request_identity": source.request.identity,
                    "recording_id": source.request.recording_id,
                    "delivery_path": str(source.delivery_path),
                    "delivery_sha256": hashlib.sha256(
                        source.delivery_path.read_bytes()
                    ).hexdigest(),
                    "delivery_bytes": source.delivery_path.stat().st_size,
                    "indexed_bytes": reader.sources[name].index.covered_bytes(),
                    "query_result": result,
                }
            )
        for account in self.config.accounts:
            result = self._dashboard_reader(account.account_id).read(self.query_at)
            self.expected[account.account_id] = self._identity(result)
        prepared = {
            "preparation_seconds": (time.monotonic_ns() - began) / 1_000_000_000,
            "sources": tuple(sources),
            "dashboard": dashboard,
            "expected_result_identities": self.expected,
        }
        (self.output / "prepared-history.json").write_bytes(self.codec.encode_json(prepared))
        return prepared

    @staticmethod
    def _identity(result: dict[str, object]) -> str:
        """Require exact serialized query-result identity for every cache class."""
        identity = result.get("result_sha256")
        if type(identity) is not str or len(identity) != 64:
            raise ValueError("retained query has no exact result identity")
        return identity

    def _worker(
        self,
        boundary: Literal["depth_bbo", "dashboard"],
        cache_class: Literal["application_cold", "warm"],
        target: str,
        started_ns: int,
        binding: _RetainedBookIndex | _DashboardReader | None = None,
    ) -> None:
        """Retain every paced request including initialization, backlog and mismatched results."""
        if cache_class == "warm" and binding is None:
            binding = (
                self._depth_reader(self.sources[target])
                if boundary == "depth_bbo"
                else self._dashboard_reader(target)
            )
            if isinstance(binding, _RetainedBookIndex):
                binding.read(target, cutoff_ns=binding._unix_ns(self.query_at))
            else:
                binding.read(self.query_at)
        for slot in range(self.samples_per_reader):
            due = started_ns + slot * 200_000_000
            remaining = due - time.monotonic_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000)
            began = time.monotonic_ns()
            try:
                if cache_class == "application_cold":
                    binding = (
                        self._depth_reader(self.sources[target])
                        if boundary == "depth_bbo"
                        else self._dashboard_reader(target)
                    )
                opened = time.monotonic_ns()
                if isinstance(binding, _RetainedBookIndex):
                    result = binding.read(target, cutoff_ns=binding._unix_ns(self.query_at))
                elif isinstance(binding, _DashboardReader):
                    result = binding.read(self.query_at)
                else:
                    raise ValueError("query worker has no application binding")
                if self._identity(result) != self.expected[target]:
                    raise ValueError("query cache class changed matched-cutoff result identity")
                status = "ok"
            except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error) as error:
                opened = time.monotonic_ns()
                result = {"failure": f"{type(error).__name__}: {error}"}
                status = "failed"
            finished = time.monotonic_ns()
            row = {
                "boundary": boundary,
                "cache_class": cache_class,
                "filesystem_cache": "uncontrolled",
                "target": target,
                "slot": slot,
                "status": status,
                "scheduled_monotonic_ns": due,
                "started_monotonic_ns": began,
                "completed_monotonic_ns": finished,
                "component_open_ns": opened - began,
                "service_ns": finished - began,
                "queue_delay_ns": max(0, began - due),
                "response_ns": finished - due,
                "query_at": self.query_at,
                "result": result,
            }
            with self.write_lock, (self.output / "samples.jsonl").open("ab") as stream:
                stream.write(self.codec.encode_json(row) + b"\n")

    @staticmethod
    def _dashboard_process(
        trial: Path,
        output: Path,
        dashboard_root: Path,
        account_id: str,
        cache_class: Literal["application_cold", "warm"],
        samples_per_reader: int,
        expected: dict[str, str],
        control: Connection[object, object],
    ) -> None:
        """Preserve the existing four-process dashboard boundary and exclude process startup."""
        child = CapacityHistoryQueries(
            trial,
            output,
            samples_per_reader=samples_per_reader,
            dashboard_events_per_account=0,
        )
        child.output.mkdir(parents=True, exist_ok=False)
        child.config = child.codec.decode_json(
            (trial / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        child.dashboard_root, child.expected = dashboard_root, expected
        binding = child._dashboard_reader(account_id) if cache_class == "warm" else None
        if binding is not None:
            binding.read(child.query_at)
        try:
            control.send("ready")
            schedule = control.recv()
            if type(schedule) is not int:
                raise ValueError("history dashboard process has no monotonic schedule")
            child._worker("dashboard", cache_class, account_id, schedule, binding)
        finally:
            control.close()

    @staticmethod
    def _summarize(values: tuple[int, ...], budget_ns: tuple[int, int, int]) -> dict[str, object]:
        """Apply the declared targets only to sufficient actual observations of one class."""
        ordered = sorted(values)
        result: dict[str, object] = {
            "samples": len(ordered),
            "minimum_ns": min(ordered, default=None),
            "maximum_ns": max(ordered, default=None),
            "budget_ns": budget_ns,
            "percentile_method": "empirical_nearest_rank",
        }
        if len(ordered) < 1000:
            result.update(status="unmeasured", reason="fewer_than_1000_samples_in_cache_class")
        else:
            ranks = tuple(ordered[math.ceil(len(ordered) * p) - 1] for p in (0.50, 0.95, 0.99))
            result.update(zip(("p50_ns", "p95_ns", "p99_ns"), ranks, strict=True))
            result["status"] = (
                "pass"
                if all(value <= budget for value, budget in zip(ranks, budget_ns, strict=True))
                else "fail"
            )
        return result

    def run(self) -> dict[str, object]:
        """Run four readers per class, preserving bounded native-history and OS-cache limits."""
        prepared = self.prepare()
        cache_classes: tuple[Literal["application_cold", "warm"], ...] = (
            "application_cold",
            "warm",
        )
        context = multiprocessing.get_context("spawn")
        for cache_class in cache_classes:
            readers = []
            for account in self._configuration().accounts:
                parent, child = cast(
                    "tuple[Connection[object, object], Connection[object, object]]", context.Pipe()
                )
                output = self.output / f"{cache_class}-{account.account_id}"
                process = context.Process(
                    target=self._dashboard_process,
                    args=(
                        self.trial,
                        output,
                        self.dashboard_root,
                        account.account_id,
                        cache_class,
                        self.samples_per_reader,
                        self.expected,
                        child,
                    ),
                    daemon=True,
                )
                process.start()
                child.close()
                readers.append((process, parent, output))
            for _, control, _ in readers:
                if not control.poll(30) or control.recv() != "ready":
                    raise TimeoutError("history dashboard reader did not initialize")
            bindings: dict[str, _RetainedBookIndex] = {}
            if cache_class == "warm":
                for name, source in self.sources.items():
                    binding = self._depth_reader(source)
                    binding.read(name, cutoff_ns=binding._unix_ns(self.query_at))
                    bindings[name] = binding
            with ThreadPoolExecutor(max_workers=4) as pool:
                started_ns = time.monotonic_ns() + 1_000_000_000
                for _, control, _ in readers:
                    control.send(started_ns)
                    control.close()
                futures = [
                    pool.submit(
                        self._worker,
                        "depth_bbo",
                        cache_class,
                        target,
                        started_ns,
                        bindings.get(target),
                    )
                    for target in self.sources
                ]
                for future in futures:
                    future.result()
            for process, _, output in readers:
                process.join(30)
                if process.is_alive():
                    process.terminate()
                    process.join(2)
                    raise TimeoutError("history dashboard reader did not complete")
                if process.exitcode:
                    raise RuntimeError("history dashboard reader failed")
                with (self.output / "samples.jsonl").open("ab") as stream:
                    stream.write((output / "samples.jsonl").read_bytes())
        rows = tuple(
            msgspec.json.decode(line, type=dict[str, object])
            for line in (self.output / "samples.jsonl").read_bytes().splitlines()
        )
        results: list[dict[str, object]] = []
        for boundary in ("depth_bbo", "dashboard"):
            for cache_class in ("application_cold", "warm"):
                selected = tuple(
                    row
                    for row in rows
                    if row["boundary"] == boundary and row["cache_class"] == cache_class
                )
                successful = tuple(row for row in selected if row["status"] == "ok")
                budget = (
                    (2_000_000_000,) * 3
                    if boundary == "depth_bbo" and cache_class == "application_cold"
                    else (3_000_000_000,) * 3
                    if cache_class == "application_cold"
                    else (50_000_000, 200_000_000, 500_000_000)
                    if boundary == "depth_bbo"
                    else (100_000_000, 400_000_000, 1_000_000_000)
                )
                results.append(
                    {
                        "boundary": boundary,
                        "cache_class": cache_class,
                        "requests": len(selected),
                        "failures": len(selected) - len(successful),
                        "service_latency": self._summarize(
                            tuple(self._integer(row, "service_ns") for row in successful), budget
                        ),
                        "scheduled_response_latency": self._summarize(
                            tuple(self._integer(row, "response_ns") for row in successful), budget
                        ),
                        "per_reader_samples": {
                            target: sum(row["target"] == target for row in successful)
                            for target in (
                                tuple(self.sources)
                                if boundary == "depth_bbo"
                                else tuple(
                                    account.account_id for account in self._configuration().accounts
                                )
                            )
                        },
                    }
                )
        result: dict[str, object] = {
            "schema_version": "retained-history-query-results-v1",
            "evidence_class": "independent_completed_history_query_path",
            "trial": str(self.trial),
            "prepared_history": prepared,
            "results": tuple(results),
            "matched_cutoff_parity": all(row["status"] == "ok" for row in rows),
            "filesystem_cold": {
                "status": "unmeasured",
                "dependency": (
                    "documented_host_cache_control_protocol_and_1000_observations_per_class"
                ),
            },
        }
        (self.output / "summary.json").write_bytes(self.codec.encode_json(result))
        return result

    @staticmethod
    def _integer(row: dict[str, object], field: str) -> int:
        """Require real nonnegative duration samples without manufacturing missing rows."""
        value = row[field]
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid retained query duration: {field}")
        return value


def main() -> None:
    """Declare a retained query experiment and publish every original measured duration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-reader", type=int, default=250)
    parser.add_argument("--dashboard-events-per-account", type=int, default=10_000)
    args = parser.parse_args(namespace=_Arguments())
    result = CapacityHistoryQueries(
        args.trial,
        args.output,
        samples_per_reader=args.samples_per_reader,
        dashboard_events_per_account=args.dashboard_events_per_account,
    ).run()
    print(
        DomainCodec()
        .encode_json(
            {"matched_cutoff_parity": result["matched_cutoff_parity"], "output": str(args.output)}
        )
        .decode()
    )


if __name__ == "__main__":
    main()
