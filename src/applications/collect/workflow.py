"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import hashlib
import signal
import sys
import time
from pathlib import Path
from uuid import uuid4

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from applications.collect.rollover import CaptureRunSignals, collect_run
from configuration import CaptureConfig, CaptureRunConfig, UniverseSelection
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.adapters.venues.coinbase import CoinbaseAccessError, CoinbaseCredentials
from market_data.collection import CaptureRunner
from market_data.contracts import CaptureRequest, CaptureRunRequest
from market_data.datasets import DatasetPublication
from market_data.replay import SavedCapture, SavedCaptureRun
from market_data.storage import RawStore
from runtime import ImplementationIdentity, InstalledIdentity, ProcessSupervisor
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics, HealthPolicy


async def collect(
    config: CaptureConfig,
    output: Path,
    *,
    implementation_identity: str,
    credentials: CoinbaseCredentials | None = None,
    transport: VenueTransport | None = None,
    snapshot_directory: Path | None = None,
    snapshot_records: int | None = None,
    health: HealthMetrics | None = None,
    universes: UniverseSelection | None = None,
) -> dict[str, object]:
    """Collect one finite recording with bounded retry, durable-before-apply and replay parity.

    Output is a unique directory, never appended to a prior recording. Persistence
    failures propagate without trying to write success onto the failing medium.
    The incomplete journal remains visible for explicit offline inspection.
    Drain accepted queue entries and the epoch's single snapshot before retrying.
    Coinbase reserves one message slot for that response; unused slots stay unused.

    Args:
        config: Validated native spot source selection and resource budgets.
        output: Parent directory for a new UUID-named recording.
        implementation_identity: SHA-256 identity of the installed runtime implementation.
        credentials: Explicit Exchange signing capability; required only for Coinbase.
        transport: Explicit transport override for deterministic integration tests.
        snapshot_directory: Optional provisioned destination for an exploratory book snapshot.
        snapshot_records: Explicit raw-prefix bound required with snapshot_directory.
        health: Optional shared progress observed by an independent supervisor.
        universes: Optional independent scope selection retained in the capture request.

    Returns:
        Saved-input identity, replay parity, bounded counts and gap summary.

    Raises:
        CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
        ValueError: The source schema, identity, continuity or resource contract is invalid.
    """
    config.__post_init__()
    if (snapshot_directory is None) != (snapshot_records is None) or (
        snapshot_records is not None
        and (type(snapshot_records) is not int or not 1 <= snapshot_records <= 10_000)
    ):
        raise ValueError("book publication requires a destination and 1..10000 raw records")
    if config.venue == "coinbase" and credentials is None:
        raise CoinbaseAccessError("Coinbase Exchange credentials are required before connection")
    transport = transport if transport is not None else VenueTransport(config)
    request = CaptureRequest(
        config=config,
        recording_id=str(uuid4()),
        implementation_identity=implementation_identity,
        universes=universes,
    )
    subscriptions = VenueSubscriptions(credentials)
    result = await CaptureRunner(
        book_factory=BookAdapters.create,
        transport=transport,
        subscriptions=subscriptions,
        snapshot_ready=subscriptions.needs_snapshot,
        snapshot_records=snapshot_records,
        readers=SourceAdapters() if snapshot_records is not None else None,
        health=health,
    ).run(request, output)
    summary = result.summary
    if snapshot_directory is not None and snapshot_records is not None:
        publication = asyncio.create_task(
            asyncio.to_thread(
                DatasetPublication(
                    SourceAdapters(), ImplementationIdentity.sha256()
                ).publish_captures,
                (result.root,),
                RawStore(result.root),
                snapshot_directory,
                max_records=snapshot_records,
                max_bytes=config.max_bytes,
            )
        )
        try:
            try:
                summary["snapshot_identity"] = (await asyncio.shield(publication)).single
            except asyncio.CancelledError:
                await publication
                raise
        except OSError:
            if health is not None:
                health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            raise
        (result.root / "summary.json").write_bytes(DomainCodec().encode_json(summary))
    return summary


async def monitored_capture(
    config: CaptureConfig,
    output: Path,
    health: HealthMetrics,
    credentials: CoinbaseCredentials | None,
    transport: VenueTransport | None,
) -> None:
    """Own the heartbeat task throughout the existing finite capture operation.

    Args:
        config: Validated native feed and resource limits.
        output: Unique supervisor-owned capture destination.
        health: Shared bounded clocks and counters.
        credentials: Explicit optional Exchange access capability.
        transport: Optional spawn-picklable synthetic transport; native transport is built in child.

    Raises:
        SystemExit: Capture finished with gaps or without synchronization.
    """
    for metric in (HealthMetric.INGESTION, HealthMetric.PERSISTENCE, HealthMetric.MARKET):
        health.set(metric, time.monotonic_ns())
    async with asyncio.TaskGroup() as group:
        heartbeat = group.create_task(ProcessSupervisor.heartbeat(health))
        try:
            result = await collect(
                config,
                output,
                implementation_identity=InstalledIdentity.sha256(),
                credentials=credentials,
                transport=transport,
                health=health,
            )
        finally:
            heartbeat.cancel()
    if result.get("gaps") or not result.get("synchronized"):
        raise SystemExit(2)


class _CaptureWorkload:
    """Bind collector configuration to a spawn-picklable child workload.

    Credentials refuse serialization, so the workload carries the credential
    file's path and the child loads the credentials itself.
    """

    def __init__(
        self,
        config: CaptureConfig,
        credential_file: Path | None,
        transport: VenueTransport | None,
    ) -> None:
        """Retain explicit child inputs without opening transports or reading credentials."""
        self.config, self.credential_file, self.transport = config, credential_file, transport

    def __call__(self, output: Path, health: HealthMetrics) -> None:
        """Run the finite capture and translate unhandled child failure to its existing exit."""
        try:
            credentials = (
                None
                if self.credential_file is None
                else CoinbaseCredentials.read(self.credential_file)
            )
            asyncio.run(monitored_capture(self.config, output, health, credentials, self.transport))
        except Exception:
            raise SystemExit(2) from None


def supervise(
    config: CaptureConfig,
    output: Path,
    policy: HealthPolicy,
    *,
    credential_file: Path | None = None,
    transport: VenueTransport | None = None,
) -> dict[str, object]:
    """Watch a separate collector; stop it before attempting a bounded local alert.

    Args:
        config: Explicit feed selection and resource ceilings.
        output: Parent directory for a unique supervision record and child capture.
        policy: Independent liveness, progress, freshness and count limits.
        credential_file: Optional Exchange credential file, read by the child;
            credentials themselves cannot cross the spawn boundary.
        transport: Optional deterministic transport at the existing boundary.

    Returns:
        Retained policy, last observation, stop reason and local alert delivery status.

    Raises:
        ValueError: Configuration is invalid or queue policy exceeds capture capacity.
    """
    config.__post_init__()
    policy.__post_init__()
    if policy.max_queue >= config.queue_capacity:
        raise ValueError("health queue threshold must be below capture capacity")
    root = output / str(uuid4())
    root.mkdir(parents=True)
    (root / "capture-config.json").write_bytes(DomainCodec().encode_json(config))
    workload = _CaptureWorkload(config, credential_file, transport)
    return ProcessSupervisor.run(
        root,
        policy,
        workload,
        duration_seconds=config.duration_seconds,
        label=f"{config.venue}:{config.symbol}",
        implementation_identity=InstalledIdentity.sha256(),
    )


class CaptureArguments(argparse.Namespace):
    """Typed installed command arguments; no credential values are accepted on the command line."""

    action: str
    config: Path | None
    output: Path
    secrets: Path | None
    capture: Path
    interrupted: bool
    snapshot_directory: Path | None
    snapshot_records: int | None
    health_config: Path | None
    universes: Path | None
    run_directory: Path
    window: Path | None
    resume: bool
    max_seconds: int


def main() -> None:
    """Run an explicit bounded capture, native product probe or saved-input replay.

    Raises:
        CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
        SystemExit: The command reports invalid input, access failure or incomplete capture.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--config", type=Path, required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("--secrets", type=Path)
    capture_parser.add_argument("--snapshot-directory", type=Path)
    capture_parser.add_argument("--snapshot-records", type=int)
    capture_parser.add_argument("--health-config", type=Path)
    capture_parser.add_argument("--universes", type=Path)
    probe_parser = commands.add_parser("probe")
    probe_parser.add_argument("--config", type=Path, required=True)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--capture", type=Path, required=True)
    replay_parser.add_argument("--interrupted", action="store_true")
    run_parser = commands.add_parser("capture-run")
    run_parser.add_argument("--run-directory", type=Path, required=True)
    run_parser.add_argument("--config", type=Path)
    run_parser.add_argument("--window", type=Path)
    run_parser.add_argument("--universes", type=Path)
    run_parser.add_argument("--resume", action="store_true")
    run_replay_parser = commands.add_parser("capture-run-replay")
    run_replay_parser.add_argument("--run-directory", type=Path, required=True)
    run_replay_parser.add_argument("--max-seconds", type=int, required=True)
    arguments = parser.parse_args(namespace=CaptureArguments())
    try:
        if arguments.action == "capture-run":
            implementation_identity = InstalledIdentity.sha256()
            if arguments.resume:
                if any(
                    value is not None
                    for value in (arguments.config, arguments.window, arguments.universes)
                ):
                    raise ValueError(
                        "resume uses only the exact retained source/window/universe request"
                    )
                request = DomainCodec().decode_json(
                    (arguments.run_directory / "run-request.json").read_bytes(), CaptureRunRequest
                )
                if request.implementation_identity != implementation_identity:
                    raise ValueError(
                        "resume requires the originally installed collector implementation"
                    )
            else:
                if arguments.config is None or arguments.window is None:
                    raise ValueError("capture-run requires explicit --config and --window")
                request = CaptureRunRequest(
                    config=CaptureConfig.read(arguments.config),
                    window=CaptureRunConfig.read(arguments.window),
                    run_id=str(uuid4()),
                    implementation_identity=implementation_identity,
                    universes=None
                    if arguments.universes is None
                    else UniverseSelection.read(arguments.universes),
                )
            stopping = CaptureRunSignals()
            previous_term = signal.signal(signal.SIGTERM, stopping.request)
            previous_int = signal.signal(signal.SIGINT, stopping.request)
            try:
                result = asyncio.run(
                    collect_run(
                        request,
                        arguments.run_directory,
                        resume=arguments.resume,
                        stop_requested=stopping.requested,
                    )
                )
            finally:
                signal.signal(signal.SIGTERM, previous_term)
                signal.signal(signal.SIGINT, previous_int)
        elif arguments.action == "capture-run-replay":
            replay = SavedCaptureRun.read(
                arguments.run_directory,
                book_factory=BookAdapters.create,
                max_seconds=arguments.max_seconds,
            )
            result = {**replay.summary(), "replay_parity": True}
        elif arguments.action == "replay":
            result = SavedCapture.read(
                arguments.capture,
                book_factory=BookAdapters.create,
                completed=not arguments.interrupted,
            ).summary()
        else:
            if arguments.config is None:
                raise ValueError("capture or probe requires an explicit configuration")
            config = CaptureConfig.read(arguments.config)
            if arguments.action == "probe":
                raw = VenueTransport(config).discover()
                result = {
                    "venue": config.venue,
                    "symbol": config.symbol,
                    "available": True,
                    "discovery_sha256": hashlib.sha256(raw).hexdigest(),
                }
            else:
                credentials = None
                if config.venue == "coinbase":
                    if arguments.secrets is None:
                        raise CoinbaseAccessError(
                            "--secrets must select the local Coinbase Exchange secrets file"
                        )
                    credentials = CoinbaseCredentials.read(arguments.secrets)
                if arguments.health_config is not None:
                    if arguments.universes is not None:
                        raise ValueError(
                            "scoped capture currently requires the foreground collector"
                        )
                    if (
                        arguments.snapshot_directory is not None
                        or arguments.snapshot_records is not None
                    ):
                        raise ValueError("supervised capture does not publish book snapshots")
                    # The credentials were read above only to refuse a bad file early.
                    result = supervise(
                        config,
                        arguments.output,
                        DomainCodec().decode_json(
                            arguments.health_config.read_bytes(), HealthPolicy
                        ),
                        credential_file=None if credentials is None else arguments.secrets,
                    )
                else:
                    result = asyncio.run(
                        collect(
                            config,
                            arguments.output,
                            credentials=credentials,
                            implementation_identity=InstalledIdentity.sha256(),
                            snapshot_directory=arguments.snapshot_directory,
                            snapshot_records=arguments.snapshot_records,
                            universes=None
                            if arguments.universes is None
                            else UniverseSelection.read(arguments.universes),
                        )
                    )
        print(DomainCodec().encode_json(result).decode(), flush=True)
        if arguments.action == "capture-run" and (
            result.get("gaps") or not result.get("reached_stop_deadline")
        ):
            raise SystemExit(2)
        if arguments.action == "capture" and (
            result.get("gaps")
            or (
                result.get("stop_reason") != "completed"
                if arguments.health_config is not None
                else not result.get("synchronized")
            )
        ):
            raise SystemExit(2)
    except CoinbaseAccessError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
    except OSError, ValueError, WebSocketException:
        print(
            "Capture/probe/replay failed; inspect the saved prefix; no continuity is claimed",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("Interrupted; inspect the saved journal with replay --interrupted", file=sys.stderr)
        raise SystemExit(130) from None
