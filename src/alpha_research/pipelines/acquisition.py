"""Compose one admitted partition fetch with verified durable raw publication."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import datetime
from http.client import HTTPSConnection
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
from msgspec.structs import replace

# project library imports
from alpha_research.data.providers.tardis.transport import TardisTransport
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.serialization import DomainCodec


def fetch_partition(
    request: SourceRequest,
    *,
    store: RawStore,
    connection: HTTPSConnection,
    clock: Callable[[], datetime],
    report: Callable[[str], None],
    timeout_seconds: float,
    max_bytes: int,
    permitted_rights_reference: str,
    api_key: str | None = None,
) -> RawObject:
    """Fetch, describe and publish one partition, reporting safe JSON progress.

    Args:
        request: Resolved job/instrument/minute selection, revalidated before I/O.
        store: Explicit durably provisioned raw destination, owned by the caller.
        connection: Unopened Tardis HTTPS connection or injected fake HTTP boundary.
        clock: UTC clock sampled after fetch and after durable publication.
        report: Synchronous JSON sink; must succeed or propagate its failure.
        timeout_seconds: Finite positive socket inactivity timeout in seconds.
        max_bytes: Positive limit for each compressed/expanded representation.
        permitted_rights_reference: Confirmed access/use/retention evidence matching job.
        api_key: Explicit optional credential; never included in reports or descriptors.

    Returns:
        Verified raw descriptor with original receipt and durable-ingestion clocks.
        Caller retains it with the request; no persistent manifest exists yet.

    Raises:
        ValueError: Request, admission, response or supplied clock is invalid.
        OSError: Transport, timeout, authentication or publication fails.
        Exception: Callback failure propagates; the terminal report may also fail.
    """
    progress: dict[str, str | int] = {
        "run_identity": request.manifest.identity,
        "request_identity": request.identity,
        "partition_start": request.start.isoformat(),
        "stage": "fetch",
        "status": "started",
        "bytes": 0,
    }
    codec = DomainCodec()
    try:
        report(codec.encode_json(progress).decode())
        transport = TardisTransport(
            connection, timeout_seconds=timeout_seconds, max_bytes=max_bytes
        )
        payload = transport.fetch(
            request, permitted_rights_reference=permitted_rights_reference, api_key=api_key
        )
        received = clock()
        progress.update(stage="store", status="received", bytes=len(payload))
        report(codec.encode_json(progress).decode())
        with TemporaryDirectory(prefix="tardis-partition-") as temporary:
            source = Path(temporary) / "response.gz"
            source.write_bytes(payload)
            descriptor = RawObject.from_file(
                source,
                request=request,
                retrieval_reference=f"tardis:{request.identity}",
                ts_received=received,
                ts_ingested=received,
            )
            store.publish(source, descriptor=descriptor, request=request)
        descriptor = replace(descriptor, ts_ingested=clock())
        progress.update(status="stored", sha256=descriptor.sha256)
        report(codec.encode_json(progress).decode())
        return descriptor
    except Exception as error:
        progress.update(status="failed", error_type=type(error).__name__)
        report(codec.encode_json(progress).decode())
        raise
