"""Measure MR 18's retained trade snapshot through the installed reference reader."""

from __future__ import annotations

# standard library imports
import hashlib
import io
import json
import platform
import resource
import sys
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import ClassVar, Literal
from unittest.mock import patch

# project library imports
import market_data
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import SourceRequest
from market_data.datasets import DatasetManifest
from market_data.query import QueryMarketRow, QueryReader
from market_data.storage import RawStore
from serialization import DomainCodec

SNAPSHOT = "c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278"
MAX_BYTES = 268_435_456


class _Reads(io.BufferedReader):
    """Count bytes returned by binary file reads, including repeated raw ZIP reads.

    The inspected reference path uses read, including ZipFile's seeks/reads.
    These are application reads, not physical device traffic or decompressed bytes.
    Instrument only the separate I/O run; normal timing uses ordinary file objects.
    """

    counts: ClassVar[dict[str, list[int]]] = {}

    def __init__(self, path: Path, mode: str = "r") -> None:
        """Bind a counted binary source and record its open.

        Args:
            path: Snapshot or raw file requested by the reference reader.
            mode: Binary read mode required by this bounded measurement.

        Raises:
            ValueError: A new caller requires an uninstrumented file mode.
        """
        if mode != "rb":
            raise ValueError("measurement supports binary reads only")
        super().__init__(io.FileIO(path, mode))
        self._counts = self.counts.setdefault(str(path), [0, 0, 0])
        self._counts[0] += 1

    def read(self, size: int | None = -1) -> bytes:
        """Count actual returned bytes, including zero-byte EOF calls.

        Args:
            size: Requested bytes, with a negative value reading to EOF.

        Returns:
            Unchanged source bytes.
        """
        result = super().read(size)
        self._counts[1] += 1
        self._counts[2] += len(result)
        return result

    @staticmethod
    def _open(path: Path, mode: str = "r") -> _Reads:
        """Supply the inspected Path.open boundary for the separate I/O run."""
        return _Reads(path, mode)


def main() -> None:
    """Open one retained snapshot and consume the preregistered serial queries.

    Args are the copied input directory and either timing or io. Run timing in
    three fresh processes; each records ten observations per query. See the MR
    record for budgets, cache conditions, percentile method and reproduction.

    Raises:
        ValueError: Arguments, identity, result stability or sample contract fail.
    """
    root, operation = Path(sys.argv[1]).resolve(), sys.argv[2]
    if sys.platform != "darwin" or operation not in ("timing", "io"):
        raise ValueError("requires macOS RSS units and operation timing or io")
    package = Path(market_data.__file__).resolve()
    if "site-packages" not in package.parts:
        raise ValueError("benchmark requires an installed candidate")
    manifest = DomainCodec().decode_json(
        (root / "snapshots" / SNAPSHOT / "manifest.json").read_bytes(), DatasetManifest
    )
    if manifest.identity != SNAPSHOT or len(manifest.partitions) != 1:
        raise ValueError("benchmark requires the retained MR 16 snapshot")
    request = SourceRequest.partition(manifest.partitions[0].acquisition.run)[0]
    binding = (
        request.instrument.source,
        request.manifest.job.stream,
        request.instrument.instrument_id,
    )
    record: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "package": str(package),
        "snapshot": SNAPSHOT,
        "operation": operation,
    }
    print(json.dumps(record), flush=True)
    # Manifest selection above is setup. QueryReader.read independently verifies it.
    context = patch.object(Path, "open", _Reads._open) if operation == "io" else nullcontext()
    with context:
        started = perf_counter()
        reader = QueryReader.read(
            root / "snapshots",
            RawStore(root / "raw"),
            readers=SourceAdapters(),
            identity=SNAPSHOT,
            max_bytes=MAX_BYTES,
            precedence=(binding,),
        )
        record = {
            "phase": "load",
            "seconds": perf_counter() - started,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "reads": _Reads.counts,
        }
        print(json.dumps(record), flush=True)
        scenarios: tuple[tuple[str, Literal["history", "cutoff"], int], ...] = (
            ("minute_history", "history", 60),
            ("hour_history", "history", 3600),
            ("hour_cutoff", "cutoff", 3600),
        )
        expected: dict[str, tuple[int, str]] = {}
        for repetition in range(10 if operation == "timing" else 1):
            for name, mode, seconds in scenarios:
                started, rows, batches = perf_counter(), 0, 0
                digest = hashlib.sha256()
                for batch in reader.batches(
                    (request.instrument.instrument_id,),
                    start=request.manifest.job.start,
                    end=request.manifest.job.start + timedelta(seconds=seconds),
                    known_at=request.manifest.job.end,
                    columns=("revision", "price", "quantity"),
                    batch_size=256,
                    mode=mode,
                ):
                    batches += 1
                    for row in batch.rows:
                        if not isinstance(row, QueryMarketRow):
                            raise ValueError("retained trade sample unexpectedly contains controls")
                        rows += 1
                        digest.update(str(row.values[1:]).encode())
                    identity = batch.identity
                elapsed = perf_counter() - started
                content = (rows, digest.hexdigest())
                if content != expected.setdefault(name, content):
                    raise ValueError("repeated query changed exact projected values")
                if (name == "hour_history" and rows != 27_480) or (mode == "cutoff" and rows != 0):
                    raise ValueError("retained sample count or unknown availability changed")
                record = {
                    "phase": name,
                    "repetition": repetition,
                    "seconds": elapsed,
                    "rows": rows,
                    "batches": batches,
                    "query_id": identity,
                    "values_sha256": content[1],
                    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "reads": _Reads.counts,
                }
                print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
