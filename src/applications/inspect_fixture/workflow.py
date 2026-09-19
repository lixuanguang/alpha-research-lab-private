"""Inspect fixtures and compose saved-input admission through atomic snapshot publication."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

# project library imports
from configuration import Configuration, ResolvedManifest
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import MarketEventRecord, SourceRequest
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec


class _InspectionArguments(argparse.Namespace):
    """Keep command input types explicit at the argparse boundary."""

    config: Path
    catalog: Path
    job: str
    fixture: Path
    received: str
    ingested: str
    sequence: int


def inspect_fixture(
    manifest: ResolvedManifest,
    fixture: Path,
    *,
    local_received: datetime,
    local_ingested: datetime,
    source_sequence: int,
) -> tuple[SourceRequest, MarketEventRecord, str]:
    """Read a bounded saved frame, compose the decoders and bind its source request.

    Args:
        manifest: Resolved selection validated before fixture access.
        fixture: UTF-8 file with exactly one nonblank trade frame, at most one MiB.
        local_received: Explicit original receipt time; never inferred from this attempt.
        local_ingested: Explicit original ingestion time, preserved by the decoder.
        source_sequence: Original zero-based line position, supplied by the caller.

    Returns:
        Matching minute request, exact canonical trade and SHA-256 of the saved bytes.

    Raises:
        OSError: The fixture cannot be read.
        ValueError: Frame, clocks, stream, instrument or capture interval is invalid.
        TypeError: A supplied decoder boundary value has an invalid type.
    """
    manifest.__post_init__()
    if manifest.job.pipeline != "dataset.inspect":
        raise ValueError("fixture inspection requires the dataset.inspect pipeline")
    with fixture.open("rb") as source:
        payload = source.read(1_048_577)
    if len(payload) > 1_048_576:
        raise ValueError("fixture exceeds one MiB; supply one saved trade frame")
    line = payload.decode("utf-8").removesuffix("\n").removesuffix("\r")
    if not line or "\n" in line or "\r" in line:
        raise ValueError("fixture must contain exactly one nonblank trade frame")
    digest = hashlib.sha256(payload).hexdigest()
    decoder = SourceAdapters.fixture(manifest)
    request, event = decoder.decode(
        line,
        source_sequence=source_sequence,
        local_received=local_received,
        local_ingested=local_ingested,
        source_digest=digest,
    )
    return request, event, digest


def main(argv: list[str] | None = None) -> int:
    """Resolve an offline job and print a canonical event or an actionable diagnostic.

    Args:
        argv: Command arguments, or process arguments when omitted.

    Returns:
        Zero on success, two for configuration/usage, three for fixture/decoding,
        or four for local I/O failure. Argument syntax errors exit with two.

    Raises:
        SystemExit: Argument parsing handles help or invalid command syntax.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("config", "catalog", "fixture"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    for option in ("job", "received", "ingested"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    arguments = parser.parse_args(argv, namespace=_InspectionArguments())
    codec = DomainCodec()
    run_identity: str | None = None
    stage = "configuration"
    try:
        configuration = Configuration.read(arguments.config)
        with arguments.catalog.open("rb") as source:
            catalog_bytes = source.read(1_048_577)
        if len(catalog_bytes) > 1_048_576:
            raise ValueError("catalog exceeds one MiB")
        catalog = codec.decode_json(catalog_bytes, CatalogSnapshot)
        manifest = configuration.resolve(
            arguments.job, catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        run_identity = manifest.identity
        stage = "fixture"
        request, event, digest = inspect_fixture(
            manifest,
            arguments.fixture,
            local_received=datetime.fromisoformat(arguments.received),
            local_ingested=datetime.fromisoformat(arguments.ingested),
            source_sequence=arguments.sequence,
        )
        print(
            codec.encode_json(
                {
                    "schema_version": "1",
                    "run_identity": run_identity,
                    "manifest": manifest,
                    "request_identity": request.identity,
                    "request_start": request.start,
                    "request_end": request.end,
                    "fixture_sha256": digest,
                    "event": event,
                }
            ).decode()
        )
    except (OSError, ValueError, TypeError, OverflowError) as error:
        status = 4 if isinstance(error, OSError) else (2 if stage == "configuration" else 3)
        print(
            codec.encode_json(
                {
                    "status": "error",
                    "stage": stage,
                    "exit_code": status,
                    "job": arguments.job,
                    "run_identity": run_identity,
                    "diagnostic": str(error),
                }
            ).decode(),
            file=sys.stderr,
        )
        return status
    return 0
