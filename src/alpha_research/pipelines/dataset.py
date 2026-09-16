"""Inspect saved fixtures and stream bound occurrences without dataset publication."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
from collections.abc import Generator
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

# project library imports
from alpha_research.configuration import Configuration, ResolvedManifest
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import BinanceArchiveRows
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.providers.tardis.decoder import TardisDecoder
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.data.venues.binance.codecs import MarketEventCodec
from alpha_research.data.venues.binance.events import Trade
from alpha_research.data.venues.binance.payloads import BinancePayloadDecoder
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _InspectionArguments(argparse.Namespace):
    """Keep command input types explicit at the argparse boundary."""

    config: Path
    catalog: Path
    job: str
    fixture: Path
    received: str
    ingested: str
    sequence: int


def admit_saved_trades(
    manifests: tuple[AcquisitionManifest, ...],
    store: RawStore,
    *,
    max_bytes: int,
    policy: Literal["reject", "evidenced"],
    corrections: tuple[Correction, ...],
) -> tuple[TradeRevision, ...]:
    """Read complete saved inputs and admit duplicate/correction histories before return.

    Args:
        manifests: Explicit original and revised acquisitions for a bounded study.
        store: Verified immutable raw objects for every supplied acquisition.
        max_bytes: Positive compressed/expanded byte limit per archive.
        policy: Explicit conflict rejection or evidenced correction admission.
        corrections: Retained evidence linking the selected economic payload versions.

    Returns:
        One envelope per economic trade, including duplicate lineage and predecessors.
        The complete batch resides in memory; no snapshot or quality acceptance is implied.

    Raises:
        ValueError: A saved input, trade conflict or correction evidence fails admission.
        OSError: A required saved input is missing or unreadable.
    """
    inputs: list[Occurrence] = []
    for manifest in manifests:
        with closing(iter_occurrences(manifest, store, max_bytes=max_bytes)) as occurrences:
            inputs.extend(occurrences)
    return TradeRevision.admit(inputs, policy=policy, corrections=corrections)


def iter_occurrences(
    manifest: AcquisitionManifest, store: RawStore, *, max_bytes: int
) -> Generator[Occurrence]:
    """Decode verified saved archive inputs under their retained resolved selection.

    Args:
        manifest: Explicit saved acquisition state containing resolved universe/bindings.
        store: Immutable raw storage, protected by the caller from concurrent mutation.
        max_bytes: Positive compressed/expanded byte cap per daily archive.

    Yields:
        Bound trades in partition/row order within the half-open research interval.

    Raises:
        ValueError: An incompatible binding, damaged input or malformed trade is encountered.
        OSError: An expected completion or stored object is missing or unreadable.

    Notes:
        The MR 08 archive reader is the supported persisted adapter. Existing Tardis
        fixtures use inspect_fixture. All rows are decoded before interval selection;
        exhaust for complete validation, or close an abandoned prefix. No quality,
        coverage, revision or publication acceptance follows from a yielded prefix.
    """
    for partition in BinanceArchiveRows.from_manifest(manifest):
        with closing(partition.read(store, max_bytes=max_bytes)) as rows:
            for row in rows:
                event = ArchiveTrade.from_row(row, partition.request)
                if row.selection_start <= event.ts_event < row.selection_end:
                    yield Occurrence(
                        request=partition.request,
                        origin=row.origin,
                        position=row.position,
                        raw=row.payload,
                        event=event,
                    )


def inspect_fixture(
    manifest: ResolvedManifest,
    fixture: Path,
    *,
    local_received: datetime,
    local_ingested: datetime,
    source_sequence: int,
) -> tuple[SourceRequest, Trade, str]:
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
    decoder = TardisDecoder(
        BinancePayloadDecoder(manifest.instruments), source_id=manifest.instruments[0].source
    )
    event = decoder.decode_line(
        line,
        source_sequence=source_sequence,
        local_received=local_received,
        local_ingested=local_ingested,
        source_digest=digest,
    )
    if not isinstance(event, Trade):
        raise ValueError("configured stream is trade; fixture contains a different event kind")
    capture = event.provenance.ts_source_received
    if capture is None or not manifest.job.start <= capture < manifest.job.end:
        raise ValueError("fixture capture timestamp is outside the configured half-open interval")
    request = SourceRequest(
        manifest=manifest,
        instrument=next(
            item for item in manifest.instruments if item.instrument_id == event.instrument_id
        ),
        offset_minutes=(capture - manifest.job.start) // timedelta(minutes=1),
    )
    MarketEventCodec.validate(event)
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
        manifest = configuration.resolve(arguments.job, catalog)
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


if __name__ == "__main__":
    raise SystemExit(main())
