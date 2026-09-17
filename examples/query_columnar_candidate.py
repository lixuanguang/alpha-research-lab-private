"""Measure a non-admitted Parquet scan candidate; this is not a query backend."""

from __future__ import annotations

# standard library imports
import hashlib
import json
import os
import resource
import sys
from itertools import batched
from pathlib import Path
from time import perf_counter

# third party library imports
import duckdb
import msgspec

# project library imports
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.revisions import TradeRevision
from alpha_research.serialization import DomainCodec


def main() -> None:
    """Convert or scan the fixed MR 18 snapshot in an isolated DuckDB environment.

    Keep complete revision JSON plus exact VARCHAR prices/quantities. This lower
    bound excludes verified reference loading, eligibility and control selection;
    its results alone cannot qualify a backend or admit the dependency.

    Raises:
        ValueError: Arguments, source identity, round trips or query content differ.
    """
    root, operation = Path(sys.argv[1]).resolve(), sys.argv[2]
    if sys.platform != "darwin" or operation not in ("convert", "scan", "io", "verify"):
        raise ValueError("requires macOS RSS units and operation convert, scan, io or verify")
    snapshot = "c0f8f3953dee8a15a79d1e9a597e37220c094b3d3c555c8f06d0ec366d3ed278"
    canonical = (
        root
        / "snapshots"
        / snapshot
        / "edf34ab6ea9c74174ec2bf7374a2f49f05781c77d229651a50d8d79cf6496dc5"
    )
    destination = root / "candidate-v1.parquet"
    codec = DomainCodec()
    with duckdb.connect(config={"threads": 1, "memory_limit": "512MB"}) as connection:
        started = perf_counter()
        if operation == "convert":
            with canonical.open("rb") as source:
                digest_hex = hashlib.file_digest(source, "sha256").hexdigest()
            if digest_hex != canonical.name:
                raise ValueError("canonical digest mismatch")
            if destination.exists():
                raise ValueError("retain the previous candidate; use a new experiment directory")
            # Split with the existing codec before native insertion: one giant JSON
            # object exceeded DuckDB's fixed memory budget on the first attempt.
            fields = msgspec.json.decode(canonical.read_bytes(), type=dict[str, msgspec.Raw])
            revisions = msgspec.json.decode(fields["revisions"], type=tuple[msgspec.Raw, ...])
            connection.execute(
                "CREATE TABLE candidate (position BIGINT, revision VARCHAR, "
                "business_time BIGINT, price VARCHAR, quantity VARCHAR)"
            )
            for chunk in batched(enumerate(revisions), 256):
                connection.executemany(
                    "INSERT INTO candidate SELECT position, revision, "
                    "json_extract_string(revision, '$.occurrences[0].event.timestamp')::BIGINT * "
                    "CASE json_extract_string(revision, '$.occurrences[0].event.timestamp_unit') "
                    "WHEN 'ms' THEN 1000 WHEN 'us' THEN 1 ELSE error('unknown clock unit') END, "
                    "json_extract_string(revision, '$.occurrences[0].event.price'), "
                    "json_extract_string(revision, '$.occurrences[0].event.quantity') "
                    "FROM (SELECT ?::BIGINT AS position, ?::VARCHAR AS revision)",
                    [(position, bytes(revision).decode()) for position, revision in chunk],
                )
            staging = destination.with_suffix(".staging.parquet")
            connection.execute(
                "COPY (SELECT * FROM candidate ORDER BY position) TO ? "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 2048)",
                [str(staging)],
            )
            # This experiment never modifies or replaces source snapshot bytes.
            os.replace(staging, destination)
            record: dict[str, object] = {
                "phase": "convert",
                "seconds": perf_counter() - started,
                "parquet_bytes": destination.stat().st_size,
                "duckdb": duckdb.__version__,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "canonical_sha256": canonical.name,
            }
            print(json.dumps(record), flush=True)
            return
        source_revisions: tuple[msgspec.Raw, ...] = ()
        if operation == "verify":
            fields = msgspec.json.decode(canonical.read_bytes(), type=dict[str, msgspec.Raw])
            source_revisions = msgspec.json.decode(
                fields["revisions"], type=tuple[msgspec.Raw, ...]
            )
        expected: dict[str, tuple[int, str]] = {}
        for repetition in range(10 if operation == "scan" else 1):
            for name, end in (
                ("minute_history", 1717200060000000),
                ("hour_history", 1717203600000000),
            ):
                if operation == "io":
                    connection.execute("SET enable_profiling = 'json'")
                    connection.execute(
                        "SET profiling_output = ?", [str(root / f"{name}.profile.json")]
                    )
                started, rows = perf_counter(), 0
                digest = hashlib.sha256()
                connection.execute(
                    "SELECT revision, price, quantity FROM read_parquet(?) "
                    "WHERE business_time >= ? AND business_time < ? ORDER BY position",
                    [str(destination), 1717200000000000, end],
                )
                while True:
                    batch: list[tuple[object, ...]] = connection.fetchmany(256)
                    if not batch:
                        break
                    for raw, price, quantity in batch:
                        if (
                            not isinstance(raw, str)
                            or not isinstance(price, str)
                            or not isinstance(quantity, str)
                        ):
                            raise ValueError("candidate changed exact string columns")
                        if operation == "verify" and name == "hour_history":
                            if raw.encode() != bytes(source_revisions[rows]):
                                raise ValueError(
                                    "Parquet changed a complete source revision payload"
                                )
                        revision = codec.decode_json(raw, TradeRevision)
                        if revision.previous is not None or revision.ts_knowledge is not None:
                            raise ValueError(
                                "scan experiment requires unknown original archive heads"
                            )
                        event = revision.occurrences[0].event
                        # Candidate scope is this archive, not captured controls or LOB data.
                        if operation == "verify" and (
                            codec.decode_json(codec.encode_json(revision), TradeRevision)
                            != revision
                        ):
                            raise ValueError("candidate revision round trip differs")
                        if (
                            not isinstance(event, ArchiveTrade)
                            or str(event.price) != price
                            or str(event.quantity) != quantity
                        ):
                            raise ValueError("projection differs from retained exact revision")
                        digest.update(str((event.price, event.quantity)).encode())
                        rows += 1
                if rows != (1236 if name == "minute_history" else 27_480):
                    raise ValueError("candidate changed selected row count")
                content = (rows, digest.hexdigest())
                if content != expected.setdefault(name, content):
                    raise ValueError("repeated native scan changed results")
                record = {
                    "phase": name,
                    "repetition": repetition,
                    "seconds": perf_counter() - started,
                    "rows": rows,
                    "values_sha256": content[1],
                    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "duckdb": duckdb.__version__,
                }
                print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
