"""Compose admitted partition fetches with durable publication and sequential resume."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import datetime
from functools import partial
from http.client import HTTPSConnection
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

# third party library imports
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import ResolvedManifest
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.tardis.transport import TardisTransport, TransientFetchError
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
    prepare: Callable[[RawObject], None] | None = None,
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
        prepare: Optional durable receipt sink, called before raw publication.

    Returns:
        Verified raw descriptor with original receipt and durable-ingestion clocks.
        Caller retains it with the request or acquisition manifest.

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
            if prepare is not None:
                prepare(descriptor)
            store.publish(source, descriptor=descriptor, request=request)
        descriptor = replace(descriptor, ts_ingested=clock())
        progress.update(status="stored", sha256=descriptor.sha256)
        report(codec.encode_json(progress).decode())
        return descriptor
    except Exception as error:
        progress.update(status="failed", error_type=type(error).__name__)
        report(codec.encode_json(progress).decode())
        raise


def acquire(
    run: ResolvedManifest,
    *,
    manifest_path: Path,
    store: RawStore,
    connection: HTTPSConnection,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    report: Callable[[str], None],
    timeout_seconds: float,
    max_bytes: int,
    permitted_rights_reference: str,
    retry_delays: tuple[float, ...] = (1.0, 2.0),
    api_key: str | None = None,
) -> AcquisitionManifest:
    """Resume an ordered run, checkpointing verified publications and bounded retries.

    Args:
        run: Expected resolved historical acquisition job.
        manifest_path: Exclusively owned checkpoint path in a durable directory.
        store: Explicit raw store, protected from external mutation or removal.
        connection: Reusable HTTPS connection; transport closes it after every attempt.
        clock: UTC clock for original receipt and confirmed durable ingestion.
        sleep: Explicit backoff callback accepting seconds.
        report: Synchronous safe JSON progress sink; callback failures are terminal.
        timeout_seconds: Positive finite socket inactivity timeout.
        max_bytes: Positive compressed and expanded response bound.
        permitted_rights_reference: Admitted rights reference for new source access.
        retry_delays: Finite nonnegative waits, one per allowed additional attempt.
        api_key: Optional explicit credential excluded from persisted state and reports.

    Returns:
        Complete manifest. Pending published bytes are reused with original receipt
        time and a recovery-time ingestion confirmation if completion was interrupted.

    Raises:
        ValueError: Retry policy, manifest, completed bytes or source schema is invalid.
        OSError: Terminal source/storage failure or transient retries are exhausted.
        Exception: Clock, backoff or report failures propagate without advancing work.
    """
    if type(retry_delays) is not tuple or any(
        type(delay) not in (int, float) or not isfinite(delay) or delay < 0
        for delay in retry_delays
    ):
        raise ValueError("retry_delays must be a tuple of finite nonnegative seconds")
    state = AcquisitionManifest.read(manifest_path, run=run, store=store)
    state.save(manifest_path)
    requests = SourceRequest.partition(run)
    for request in requests[len(state.completed) :]:
        descriptor = state.pending
        if descriptor is not None:
            try:
                with store.open(descriptor=descriptor, request=request):
                    pass
            except FileNotFoundError:
                descriptor = None
            else:
                store.publish(manifest_path, descriptor=descriptor, request=request)
                descriptor = replace(descriptor, ts_ingested=clock())
        if descriptor is None:
            for attempt in range(len(retry_delays) + 1):
                try:
                    descriptor = fetch_partition(
                        request,
                        store=store,
                        connection=connection,
                        clock=clock,
                        report=report,
                        timeout_seconds=timeout_seconds,
                        max_bytes=max_bytes,
                        permitted_rights_reference=permitted_rights_reference,
                        api_key=api_key,
                        prepare=partial(state.prepare, manifest_path),
                    )
                    break
                except TransientFetchError:
                    if attempt == len(retry_delays):
                        raise
                    report(
                        DomainCodec()
                        .encode_json(
                            {
                                "run_identity": run.identity,
                                "request_identity": request.identity,
                                "status": "retry",
                                "attempt": attempt + 1,
                                "delay_seconds": retry_delays[attempt],
                            }
                        )
                        .decode()
                    )
                    sleep(retry_delays[attempt])
        if descriptor is None:
            raise RuntimeError("acquisition produced no descriptor")
        completed: tuple[RawObject, ...] = (*state.completed, descriptor)
        state = replace(state, completed=completed, pending=None)
        state.save(manifest_path)
        report(
            DomainCodec()
            .encode_json(
                {
                    "run_identity": run.identity,
                    "request_identity": request.identity,
                    "status": "checkpointed",
                    "completed": len(state.completed),
                }
            )
            .decode()
        )
    return state
