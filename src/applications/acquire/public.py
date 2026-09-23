"""Compose bounded public-trade ingestion and reference capture through installed commands."""

from __future__ import annotations

# standard library imports
import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from configuration import PublicDataJob
from market_data.acquisition import PublicIngestion
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.transport import PublicHTTPS
from market_data.contracts import PublicRequest
from market_data.storage import RawStore
from runtime import InstalledIdentity
from serialization import DomainCodec


class _PublicArguments(argparse.Namespace):
    """Type the explicit bounded job and caller-owned resume directory."""

    config: Path
    output: Path


class _UTCClock:
    """Observe UTC only at the actual acquisition boundary."""

    @staticmethod
    def now() -> datetime:
        """Return the actual local UTC observation time."""
        return datetime.now(UTC)


def acquire_public(argv: list[str]) -> int:
    """Resolve one public job, retain original responses and resume its exact checkpoint.

    No credentials or trading endpoints are used. Completed runs reopen without
    network access; changed jobs or installed implementations require a new output.
    Exit 2 preserves a failed/incomplete checkpoint, and 130 reports interruption.
    """
    parser = argparse.ArgumentParser(prog="alpha-acquire public", description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv, namespace=_PublicArguments())
    try:
        job = PublicDataJob.read(args.config)
        sources, implementation = SourceAdapters(), InstalledIdentity.sha256()
        for instrument in job.instruments:
            if instrument.instrument_id in job.universes.collection:
                request = PublicRequest(
                    job_identity=job.identity,
                    implementation_identity=implementation,
                    instrument=instrument,
                    kind="reference",
                    cursor=None,
                    ordinal=0,
                )
                sources.public(instrument).endpoint(job, request)
        args.output.mkdir(exist_ok=True)
        raw_path = args.output / "raw"
        raw_path.mkdir(exist_ok=True)
        for directory in (args.output.parent, args.output):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        ingestion = PublicIngestion(sources, RawStore(raw_path))
        state = ingestion.resume(
            job,
            implementation_identity=implementation,
            path=args.output / "acquisition.json",
            transport=PublicHTTPS(max_bytes=job.max_bytes, timeout_seconds=job.timeout_seconds),
            clock=_UTCClock.now,
            sleep=time.sleep,
        )
        print(
            DomainCodec()
            .encode_json(
                {
                    "status": "complete",
                    "job_identity": job.identity,
                    "implementation_identity": implementation,
                    "responses": len(state.receipts),
                    "raw_bytes": sum(r.raw.size_bytes for r in state.receipts),
                    "reference_identity": ingestion.references(state).identity,
                    "scope": "local_observations_only",
                    "output": str(args.output.resolve()),
                }
            )
            .decode()
        )
        return 0
    except (ValueError, TypeError, OSError) as error:
        print(
            DomainCodec()
            .encode_json(
                {"status": "failed", "error": str(error), "retained": str(args.output.resolve())}
            )
            .decode(),
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(
            "Interrupted; resume the same job and output to verify retained responses",
            file=sys.stderr,
        )
        return 130
