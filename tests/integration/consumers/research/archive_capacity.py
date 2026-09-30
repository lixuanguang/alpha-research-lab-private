"""Profile saved native book prefixes through installed publication and reopening APIs."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import resource
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from itertools import zip_longest
from pathlib import Path

# third party library imports
import msgspec

# project library imports
import market_data
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import BookAdmissionReport, BookInput, BookSnapshot, DatasetPublication
from market_data.query import BookQuery, BookQueryReader
from market_data.replay import BookReplay
from market_data.storage import RawStore
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Select completed local archives, a fresh evidence directory and a bounded prefix."""

    archives: list[Path] | None
    output: Path
    max_records: int
    max_bytes: int
    reopen: bool


class _ReopenPlan(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Pin the independent process to original inputs and exact result digests."""

    archives: tuple[str, ...]
    snapshot_identity: str
    query_sha256: str
    replay_sha256: str
    max_records: int
    max_bytes: int


class NativeArchiveCapacity:
    """Own one installed saved-source diagnostic and its reproducible evidence."""

    def __init__(
        self, output: Path, *, max_records: int, max_bytes: int, implementation: str
    ) -> None:
        """Bind explicit publication and query limits without changing source contracts."""
        if not 1 <= max_records <= 1_000_000 or max_bytes <= 0:
            raise ValueError("diagnostic requires an existing bounded book prefix")
        self.output = output
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.raw = RawStore(output / "raw")
        self.snapshots = output / "snapshots"
        self.readers = SourceAdapters()
        self.codec = DomainCodec()
        self.implementation = implementation
        self.session: BookSnapshot | None = None
        self.stages: list[dict[str, object]] = []
        self.quality: list[dict[str, object]] = []

    @staticmethod
    def _rss_bytes() -> int:
        """Normalize the platform's peak resident-set unit for retained process evidence."""
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024

    @staticmethod
    def _disk_bytes(root: Path) -> int:
        """Count consumer-owned retained bytes without opening source archives."""
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    def _begin(self) -> tuple[int, int]:
        """Sample wall and process CPU clocks at an owned operation boundary."""
        return time.perf_counter_ns(), time.process_time_ns()

    def _end(self, name: str, started: tuple[int, int]) -> None:
        """Retain one operation's duration, process CPU, peak RSS and output disk bytes."""
        wall, cpu = started
        self.stages.append(
            {
                "operation": name,
                "wall_seconds": (time.perf_counter_ns() - wall) / 1_000_000_000,
                "cpu_seconds": (time.process_time_ns() - cpu) / 1_000_000_000,
                "peak_rss_bytes": self._rss_bytes(),
                "output_disk_bytes": self._disk_bytes(self.output),
                "output_allocated_bytes": sum(
                    path.stat().st_blocks * 512 for path in self.output.rglob("*") if path.is_file()
                ),
                "input_block_operations": resource.getrusage(resource.RUSAGE_SELF).ru_inblock,
                "output_block_operations": resource.getrusage(resource.RUSAGE_SELF).ru_oublock,
                "physical_io_bytes": "unavailable on Darwin; block counts are not bytes",
            }
        )
        with (self.output / "samples.jsonl").open("ab") as output:
            output.write(self.codec.encode_json(self.stages[-1]) + b"\n")

    def _write(self, name: str, record: object) -> None:
        """Retain a small typed result in the exclusive attempt directory."""
        (self.output / name).write_bytes(self.codec.encode_json(record))

    def _quality(self, identity: str, report: BookAdmissionReport) -> None:
        """Keep actual per-partition admission outcomes before publication completes."""
        self.quality.append(
            {
                "request_identity": identity,
                "scope": report.scope,
                "reasons": report.reasons,
                "invalid_count": report.invalid_count,
                "gap_count": report.gap_count,
                "duplicate_count": report.duplicate_count,
                "canonical_sha256": report.sha256,
                "record_count": report.record_count,
            }
        )

    def _query(self, selected: BookInput, identity: str) -> dict[str, object]:
        """Reopen one archive partition without fabricating receipt-time market rows."""
        archive = selected.archive
        if archive is None:
            raise ValueError("capacity diagnostic requires a completed archive")
        start = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=archive.config.start_ms)
        query = BookQuery(
            snapshot_id=identity,
            request_identity=archive.identity,
            instrument=archive.config.instrument_id,
            start=start,
            end=start + timedelta(days=1),
            known_at=start + timedelta(days=1),
            columns=("bids", "asks"),
            batch_size=100,
            max_bytes=self.max_bytes,
        )
        if self.session is None:
            raise ValueError("diagnostic requires initialized snapshot session")
        batches = tuple(BookQueryReader(self.session).batches(query))
        count = sum(len(batch.rows) for batch in batches)
        reasons = tuple(sorted({reason for batch in batches for reason in batch.reasons}))
        if count != 0 or not any("availability unknown" in reason for reason in reasons):
            raise AssertionError("archive query invented decision-eligible receipt-time values")
        return {
            "request_identity": archive.identity,
            "query_identity": batches[0].identity,
            "batches": len(batches),
            "market_rows": count,
            "reasons": reasons,
            "availability": "unknown_original_receipts",
        }

    def _replay(self, selected: BookInput, identity: str) -> dict[str, object]:
        """Reopen every selected original position while leaving archive rows unscheduled."""
        archive = selected.archive
        if archive is None:
            raise ValueError("capacity diagnostic requires a completed archive")
        terminal = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            milliseconds=archive.config.start_ms + 86_400_000
        )
        if self.session is None or self.session.identity != identity:
            raise ValueError("diagnostic requires initialized snapshot session")
        replay = BookReplay(
            self.session,
            request_identity=archive.identity,
            terminal=terminal,
            config_identity=self.implementation,
            batch_size=250,
        )
        trace = hashlib.sha256()
        count, snapshots, updates = 0, 0, 0
        first_source: str | None = None
        last_source: str | None = None
        for batch in replay.batches():
            for row in batch:
                if row.received_ns is not None:
                    raise AssertionError("archive replay invented original receipt clocks")
                count += 1
                snapshots += row.outcome == "snapshot"
                updates += row.outcome == "update"
                if first_source is None:
                    first_source = row.source_time
                last_source = row.source_time
                trace.update(
                    self.codec.encode_json(
                        (row.position, row.outcome, row.state_identity, row.source_time)
                    )
                )
        if count == 0 or count > self.max_records or replay.cursor is not None:
            raise AssertionError("archive replay prefix or scheduling changed")
        return {
            "request_identity": archive.identity,
            "rows": count,
            "snapshots": snapshots,
            "updates": updates,
            "first_source_ms": first_source,
            "last_source_ms": last_source,
            "trace_sha256": trace.hexdigest(),
            "scheduled_rows": 0,
        }

    def publish(self, archives: tuple[Path, ...], command: tuple[str, ...]) -> None:
        """Publish a bounded actual prefix and retain cold, warm and process-reopen evidence."""
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "raw").mkdir()
        self.snapshots.mkdir()
        try:
            self._publish(archives, command)
        except AssertionError, OSError, ValueError, TimeoutError, subprocess.SubprocessError:
            self._write(
                "failure.json",
                {
                    "traceback": traceback.format_exc(),
                    "stages": self.stages,
                    "quality": self.quality,
                    "scope": "representative_saved_source_diagnostic_only",
                },
            )
            raise

    def _publish(self, archives: tuple[Path, ...], command: tuple[str, ...]) -> None:
        """Coordinate strict selection, publication and independent second-process reopening."""
        if not archives:
            raise ValueError("at least one completed archive is required")
        if "site-packages" not in Path(market_data.__file__).parts:
            raise AssertionError("diagnostic must use an independently installed distribution")
        selected = tuple(BookInput.read(path, max_records=self.max_records) for path in archives)
        for item in selected:
            if item.archive is None:
                raise ValueError("diagnostic input is not a completed archive")
        try:
            BookInput.read(archives[0], max_records=1_000_001)
        except ValueError as error:
            refusal = str(error)
            if "bounded prefix" not in refusal:
                raise AssertionError("unexpected 1,000,001-record refusal") from error
        else:
            raise AssertionError("1,000,001-record book input unexpectedly admitted")
        sources = []
        for path, item in zip(archives, selected, strict=True):
            archive = item.archive
            if archive is None:
                raise ValueError("missing archive provenance")
            sources.append(
                {
                    "directory": str(path.resolve()),
                    "request_identity": archive.identity,
                    "implementation_identity": archive.implementation_identity,
                    "symbol": archive.config.symbol,
                    "day": archive.config.day,
                    "depth": 400,
                    "raw_sha256": item.raw.sha256,
                    "raw_size_bytes": item.raw.size_bytes,
                    "selected_max_records": item.max_records,
                    "original_receipt_clocks": "unknown",
                }
            )
        publisher = DatasetPublication(self.readers, self.implementation)
        started = self._begin()
        identity = publisher.publish_books(
            archives,
            self.raw,
            self.snapshots,
            max_records=self.max_records,
            max_bytes=self.max_bytes,
            report=self._quality,
        )
        self._end("publish_and_internal_verification", started)
        started = self._begin()
        self.session = BookSnapshot.read(
            self.snapshots,
            self.raw,
            readers=self.readers,
            identity=identity,
            max_bytes=self.max_bytes,
        )
        self._end("snapshot_initial_verification", started)
        queries = []
        replays = []
        for item in selected:
            archive = item.archive
            if archive is None:
                raise ValueError("missing archive provenance")
            started = self._begin()
            cold = self._query(item, identity)
            self._end(f"query_first_projection:{archive.identity}", started)
            started = self._begin()
            warm = self._query(item, identity)
            self._end(f"query_application_warm:{archive.identity}", started)
            if cold != warm:
                raise AssertionError("application-cold and warm query results differ")
            queries.append(cold)
            started = self._begin()
            replays.append(self._replay(item, identity))
            self._end(f"replay_verified_stream:{archive.identity}", started)
        for item in selected:
            started = self._begin()
            actual = self.session.observations(item.request.identity)
            expected = self.readers.books(item, self.raw)
            count = 0
            for left, right in zip_longest(actual, expected, fillvalue=None):
                if left != right:
                    raise AssertionError(f"reference reconstruction differs at position {count}")
                count += 1
            self._end(f"exact_reference_comparison:{item.request.identity}", started)
        self._write(
            "summary.json",
            {
                "scope": "representative_saved_source_diagnostic_only",
                "acceptance": "not_R1_or_full_72_hour_coverage",
                "command": command,
                "executable": sys.executable,
                "installed_market_data": str(Path(market_data.__file__).resolve()),
                "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "normalization_identity": self.implementation,
                "snapshot_identity": identity,
                "max_records": self.max_records,
                "max_bytes": self.max_bytes,
                "bounds_refusal_above_1000000": refusal,
                "sources": tuple(sources),
                "quality": tuple(self.quality),
                "queries": tuple(queries),
                "replays": tuple(replays),
                "stages": tuple(self.stages),
                "final_output_disk_bytes": self._disk_bytes(self.output),
                "cache_condition": (
                    "initial verification separate from first/warm projections; "
                    "OS page cache uncontrolled"
                ),
            },
        )
        self._write(
            "reopen-plan.json",
            _ReopenPlan(
                archives=tuple(str(path.resolve()) for path in archives),
                snapshot_identity=identity,
                query_sha256=hashlib.sha256(self.codec.encode_json(queries)).hexdigest(),
                replay_sha256=hashlib.sha256(self.codec.encode_json(replays)).hexdigest(),
                max_records=self.max_records,
                max_bytes=self.max_bytes,
            ),
        )
        reopened = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--output",
                str(self.output),
                "--max-records",
                str(self.max_records),
                "--max-bytes",
                str(self.max_bytes),
                "--reopen",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        self._write(
            "reopen-process.json",
            {
                "returncode": reopened.returncode,
                "stdout": reopened.stdout[-4096:],
                "stderr": reopened.stderr[-4096:],
            },
        )
        if reopened.returncode != 0:
            raise ValueError("independent process reopening failed; inspect reopen-process.json")

    def reopen(self) -> None:
        """Read a completed snapshot from a new installed process and compare exact summaries."""
        plan = self.codec.decode_json((self.output / "reopen-plan.json").read_bytes(), _ReopenPlan)
        if (plan.max_records, plan.max_bytes) != (self.max_records, self.max_bytes):
            raise ValueError("reopen limits differ from original publication")
        identity = plan.snapshot_identity
        selections = tuple(
            BookInput.read(Path(directory), max_records=self.max_records)
            for directory in plan.archives
        )
        started = self._begin()
        self.session = BookSnapshot.read(
            self.snapshots,
            self.raw,
            readers=self.readers,
            identity=identity,
            max_bytes=self.max_bytes,
        )
        self._end("process_reopen_verification", started)
        queries, replays = [], []
        for item in selections:
            archive = item.archive
            if archive is None:
                raise ValueError("missing archive provenance")
            started = self._begin()
            queries.append(self._query(item, identity))
            self._end(f"query_process_reopen:{archive.identity}", started)
            started = self._begin()
            replays.append(self._replay(item, identity))
            self._end(f"replay_process_reopen:{archive.identity}", started)
        if hashlib.sha256(self.codec.encode_json(queries)).hexdigest() != plan.query_sha256 or (
            hashlib.sha256(self.codec.encode_json(replays)).hexdigest() != plan.replay_sha256
        ):
            raise AssertionError("new-process query or replay differs from original")
        self._write(
            "reopen.json",
            {
                "scope": "representative_saved_source_diagnostic_only",
                "executable": sys.executable,
                "installed_market_data": str(Path(market_data.__file__).resolve()),
                "snapshot_identity": identity,
                "queries": tuple(queries),
                "replays": tuple(replays),
                "stages": tuple(self.stages),
                "cache_condition": "new process; OS page cache uncontrolled",
            },
        )


def main() -> None:
    """Run an installed, local, bounded saved-source diagnostic with retained failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-records", default=1_000, type=int)
    parser.add_argument("--max-bytes", default=1_000_000_000, type=int)
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    diagnostic = NativeArchiveCapacity(
        args.output,
        max_records=args.max_records,
        max_bytes=args.max_bytes,
        implementation=ImplementationIdentity.sha256(),
    )
    if args.reopen:
        diagnostic.reopen()
        return
    diagnostic.publish(tuple(args.archives or ()), tuple(sys.argv))


if __name__ == "__main__":
    main()
