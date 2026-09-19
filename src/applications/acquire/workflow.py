"""Compose admitted partition fetches with durable publication and sequential resume."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import os
import sys
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from http.client import HTTPSConnection
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zlib import error as ZlibError

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from configuration import Configuration, OKXHistoryConfig, ResolvedManifest
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.providers.binance import BinanceArchiveTransport
from market_data.adapters.providers.tardis import TardisTransport
from market_data.adapters.venues.okx import (
    OKXArchiveDiscovery,
    OKXArchiveReader,
    OKXArchiveStore,
    OKXHistoryTransport,
)
from market_data.contracts import OKXArchiveRequest, RawObject, SourceRequest, TransientFetchError
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity, InstalledIdentity
from serialization import DomainCodec


class _AcquisitionArguments(argparse.Namespace):
    """Type the installed command's explicit selection, storage and resource limits."""

    config: Path
    catalog: Path
    manifest: Path
    store: Path
    job: str
    rights_reference: str
    api_key_env: str | None
    timeout_seconds: float
    max_bytes: int
    retry_delays: list[float]


class _AcquisitionOutput:
    """Flush command progress while retaining only acknowledged job totals per invocation."""

    def __init__(self) -> None:
        """Start with unknown persisted state until resume verification succeeds."""
        self._codec = DomainCodec()
        self._decoder = msgspec.json.Decoder(dict[str, object])
        self._retries = 0
        self._summary: dict[str, object] = {
            "completed": None,
            "persisted_bytes": None,
            "last_persistence": None,
            "stage": "configuration",
            "run_identity": None,
            "command_identity": None,
            "request_identity": None,
            "total": None,
        }

    def __call__(self, payload: str) -> None:
        """Consume the pipeline's scalar JSON reports and preserve job context."""
        fields = self._decoder.decode(payload)
        self._retries += fields.get("status") == "retry"
        self.emit(**fields)

    def emit(self, **fields: object) -> None:
        """Write one flushed record, routing terminal errors to stderr.

        Args:
            **fields: Owned JSON fields; credentials and raw exception text are excluded.
        """
        for key in self._summary:
            if key in fields:
                self._summary[key] = fields[key]
        record = {**self._summary, "scope": "partition", "retries": self._retries, **fields}
        destination = sys.stderr if fields.get("exit_code") else sys.stdout
        print(self._codec.encode_json(record).decode(), file=destination, flush=True)


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
        request: Resolved source-object selection, revalidated before I/O.
        store: Explicit durably provisioned raw destination, owned by the caller.
        connection: Unopened selected provider connection or injected fake HTTP boundary.
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
        transport_type = (
            BinanceArchiveTransport
            if request.manifest.job.provider == "binance-archive"
            else TardisTransport
        )
        transport = transport_type(connection, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
        payload = transport.fetch(
            request, permitted_rights_reference=permitted_rights_reference, api_key=api_key
        )
        received = clock()
        progress.update(stage="store", status="received", bytes=len(payload))
        report(codec.encode_json(progress).decode())
        with TemporaryDirectory(prefix="source-partition-") as temporary:
            source = Path(temporary) / "response"
            source.write_bytes(payload)
            descriptor = RawFiles.describe(
                source,
                request=request.binding,
                retrieval_reference=f"{request.manifest.job.provider}:{request.identity}",
                ts_received=received,
                ts_ingested=received,
            )
            if prepare is not None:
                prepare(descriptor)
            store.publish(source, descriptor=descriptor, request=request.binding)
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
    report(
        DomainCodec()
        .encode_json(
            {
                "scope": "job",
                "stage": "resume",
                "status": "resumed",
                "run_identity": run.identity,
                "total": len(requests),
                "completed": len(state.completed),
                "persisted_bytes": sum(item.size_bytes for item in state.completed),
                "last_persistence": state.completed[-1].ts_ingested if state.completed else None,
            }
        )
        .decode()
    )
    for request in requests[len(state.completed) :]:
        descriptor = state.pending
        if descriptor is not None:
            try:
                with store.open(descriptor=descriptor, request=request.binding):
                    pass
            except FileNotFoundError:
                descriptor = None
            else:
                store.publish(manifest_path, descriptor=descriptor, request=request.binding)
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
        report(
            DomainCodec()
            .encode_json(
                {
                    "stage": "checkpoint",
                    "status": "checkpointing",
                    "request_identity": request.identity,
                }
            )
            .decode()
        )
        state.save(manifest_path)
        report(
            DomainCodec()
            .encode_json(
                {
                    "run_identity": run.identity,
                    "request_identity": request.identity,
                    "status": "checkpointed",
                    "completed": len(state.completed),
                    "persisted_bytes": sum(item.size_bytes for item in state.completed),
                    "last_persistence": descriptor.ts_ingested,
                    "stage": "checkpoint",
                }
            )
            .decode()
        )
    return state


def acquire_history(
    config: OKXHistoryConfig,
    output: Path,
    *,
    implementation_identity: str,
    transport: OKXHistoryTransport | None = None,
) -> dict[str, object]:
    """Compose public discovery, bounded download, complete-file validation and durable storage.

    Args:
        config: Explicit historical spot selection with hard resource ceilings.
        output: Parent of a unique UUID-named archive directory.
        implementation_identity: SHA-256 of the installed implementation.
        transport: Optional injected public transport for deterministic failure tests.

    Returns:
        Saved-input identity, archive interval and independently repeatable prefix replay.

    Raises:
        TimeoutError: The finite download/validation budget is exhausted.
        OSError: Acquisition or persistence fails; no complete manifest is created.
    """
    config.__post_init__()
    source = transport if transport is not None else OKXHistoryTransport(config)
    deadline = time.monotonic() + config.duration_seconds
    index = source.index()
    request = OKXArchiveRequest(
        config=config,
        implementation_identity=implementation_identity,
        index_sha256=hashlib.sha256(index).hexdigest(),
        url=OKXArchiveDiscovery.select_url(config, index),
        index_received=datetime.now(UTC),
    )
    store = OKXArchiveStore(output / str(uuid4()))
    store.start(request, index)
    destination = store.root / "download.part"
    for attempt in range(config.retries + 1):
        try:
            source.download(request, destination, deadline)
            break
        except TransientFetchError, TimeoutError:
            if attempt == config.retries or time.monotonic() >= deadline:
                raise
            destination.unlink(missing_ok=True)
            time.sleep(min(1 << attempt, max(0, deadline - time.monotonic())))
    received = datetime.now(UTC)
    OKXArchiveReader(config).validate(destination, deadline)
    descriptor = store.finish(request, received)
    result = store.replay()
    result["download_attempts"] = attempt + 1
    result["saved_input_identity"] = descriptor.sha256
    (store.root / "summary.json").write_bytes(DomainCodec().encode_json(result))
    return result


class ArchiveArguments(argparse.Namespace):
    """Type the installed command's explicit public archive selection."""

    action: str
    config: Path
    output: Path
    archive: Path


def _archive(argv: list[str]) -> int:
    """Run foreground public history discovery, single-day acquisition or offline replay.

    Args:
        argv: Arguments following the existing acquisition command's archive subcommand.

    Returns:
        Zero for success, two for invalid or failed archive work, or 130 for interruption.

    Raises:
        SystemExit: Argparse handles help and invalid syntax.
    """
    parser = argparse.ArgumentParser(
        prog="alpha-acquire archive", description="Public native L2 archives (OKX 400-level spot)"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("index", "fetch"):
        command = commands.add_parser(action)
        command.add_argument("--config", type=Path, required=True)
        if action == "fetch":
            command.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv, namespace=ArchiveArguments())
    try:
        if args.action == "replay":
            result = OKXArchiveStore(args.archive).replay()
        else:
            config = OKXHistoryConfig.read(args.config)
            if args.action == "index":
                raw = OKXHistoryTransport(config).index()
                result = {
                    "venue": "okx",
                    "representation": "L2",
                    "symbol": config.symbol,
                    "url": OKXArchiveDiscovery.select_url(config, raw),
                    "index_sha256": hashlib.sha256(raw).hexdigest(),
                }
            else:
                result = acquire_history(
                    config, args.output, implementation_identity=InstalledIdentity.sha256()
                )
        print(DomainCodec().encode_json(result).decode(), flush=True)
    except OSError, ValueError, EOFError, tarfile.TarError, ZlibError:
        print(
            "OKX history failed; incomplete files are not admitted as completed archives",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("Interrupted; no incomplete archive is admitted for replay", file=sys.stderr)
        return 130

    return 0


def main(argv: list[str] | None = None) -> int:
    """Resolve a configured acquisition, resume its manifest and report terminal status.

    Args:
        argv: Explicit arguments, or process arguments when omitted. Credentials are
            read only from the explicitly named environment variable, never argv.

    Returns:
        Zero for completion, two for configuration, three for acquisition validation,
        four for I/O or unexpected failure, or 130 for a keyboard interruption.

    Raises:
        SystemExit: Argparse handles help and invalid argument syntax.
        OSError: A failed terminal report cannot be written to stderr.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["archive"]:
        return _archive(arguments[1:])
    parser = argparse.ArgumentParser(
        description=__doc__, epilog="For native L2 archives: alpha-acquire archive --help"
    )
    for option in ("config", "catalog", "manifest", "store"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    for option in ("job", "rights-reference"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--api-key-env", help="Name of an existing credential environment variable")
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--retry-delays", nargs="*", type=float, default=list[float]((1.0, 2.0)))
    args = parser.parse_args(arguments, namespace=_AcquisitionArguments())
    output = _AcquisitionOutput()
    stage = "configuration"
    try:
        configuration = Configuration.read(args.config)
        with args.catalog.open("rb") as source:
            catalog_bytes = source.read(1_048_577)
        if len(catalog_bytes) > 1_048_576:
            raise ValueError("catalog exceeds one MiB")
        codec = DomainCodec()
        run = configuration.resolve(
            args.job,
            codec.decode_json(catalog_bytes, CatalogSnapshot),
            implementation_identity=ImplementationIdentity.sha256(),
        )
        AcquisitionManifest(run=run)
        if args.manifest.resolve() in {args.config.resolve(), args.catalog.resolve()}:
            raise ValueError("manifest must not overwrite configuration or catalog")
        api_key = None if args.api_key_env is None else os.environ[args.api_key_env]
        if run.job.provider == "binance-archive" and args.api_key_env is not None:
            raise ValueError("Binance public archives require no credential environment variable")
        transport_type = (
            BinanceArchiveTransport if run.job.provider == "binance-archive" else TardisTransport
        )
        connection = HTTPSConnection(
            "data.binance.vision" if run.job.provider == "binance-archive" else "api.tardis.dev"
        )
        transport_type(connection, timeout_seconds=args.timeout_seconds, max_bytes=args.max_bytes)
        command = {
            "command": "alpha-acquire",
            "run_identity": run.identity,
            "manifest": str(args.manifest.resolve()),
            "store": str(args.store.resolve()),
            "timeout_seconds": args.timeout_seconds,
            "max_bytes": args.max_bytes,
            "retry_delays": args.retry_delays,
            "rights_reference": args.rights_reference,
            "api_key_env": args.api_key_env,
        }
        output.emit(
            scope="job",
            status="started",
            command=command,
            run_identity=run.identity,
            command_identity=hashlib.sha256(codec.encode_json(command)).hexdigest(),
        )
        stage = "acquisition"
        output.emit(scope="job", stage="resume", status="verifying")
        acquire(
            run,
            manifest_path=args.manifest,
            store=RawStore(args.store),
            connection=connection,
            clock=partial(datetime.now, UTC),
            sleep=time.sleep,
            report=output,
            timeout_seconds=args.timeout_seconds,
            max_bytes=args.max_bytes,
            permitted_rights_reference=args.rights_reference,
            retry_delays=tuple(args.retry_delays),
            api_key=api_key,
        )
        output.emit(scope="job", stage="complete", status="complete", exit_code=0)
    except (Exception, KeyboardInterrupt) as error:
        status = 2 if stage == "configuration" else (3 if isinstance(error, ValueError) else 4)
        if isinstance(error, KeyboardInterrupt):
            status = 130
        output.emit(
            scope="job",
            status="interrupted" if status == 130 else "failed",
            exit_code=status,
            error_type=type(error).__name__,
            diagnostic=str(error)
            if isinstance(error, ValueError)
            else "Check the reported stage, config/admission and retained manifest/store; "
            "correct the cause, then repeat the same command to verify and resume.",
        )
        return status
    return 0
