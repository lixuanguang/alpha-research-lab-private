"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import contextlib
import hashlib
import multiprocessing
import sys
import time
from http.client import HTTPException
from pathlib import Path
from uuid import uuid4

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from alpha_research.data.book_datasets import BookCapture
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.health import HealthAlert, HealthMetric, HealthMetrics, HealthPolicy
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.live.replay import CaptureReplay
from alpha_research.data.live.transport import FeedSocket, VenueTransport
from alpha_research.data.raw_store import RawStore
from alpha_research.data.venues.coinbase.auth import CoinbaseAccessError, CoinbaseCredentials
from alpha_research.data.venues.coinbase.book import CoinbaseBook
from alpha_research.pipelines.dataset import publish_book_dataset
from alpha_research.serialization import DomainCodec


async def receive_frames(
    socket: FeedSocket,
    queue: asyncio.Queue[CaptureRecord],
    config: CaptureConfig,
    epoch: int,
    deadline: float,
    remaining: int,
    health: HealthMetrics | None = None,
) -> None:
    """Timestamp receipt independently of persistence; stop visibly on overload or disconnect.

    Args:
        socket: This epoch's open message connection.
        queue: Bounded queue shared with the durable consumer.
        config: Validated native spot source selection and resource budgets.
        epoch: Connection epoch within the current recording.
        deadline: Monotonic receive deadline in seconds.
        remaining: Maximum additional received WebSocket messages.
        health: Optional shared progress observed by an independent supervisor.
    """
    reason = "message_limit"
    awaiting_pong = False
    received = 0
    queue_peak = 0 if health is None else health.snapshot()[HealthMetric.QUEUE]
    try:
        while received < remaining:
            budget = deadline - time.monotonic()
            if budget <= 0:
                reason = "duration_limit"
                break
            try:
                idle = (
                    min(config.idle_seconds, 20) if config.venue == "okx" else config.idle_seconds
                )
                async with asyncio.timeout(min(budget, idle)):
                    message = await socket.recv()
            except TimeoutError:
                if config.venue == "okx" and not awaiting_pong and time.monotonic() < deadline:
                    async with asyncio.timeout(max(0, deadline - time.monotonic())):
                        await socket.send("ping")
                    awaiting_pong = True
                    continue
                reason = "duration_limit" if time.monotonic() >= deadline else "idle_timeout"
                break
            awaiting_pong = False
            received += 1
            record = CaptureRecord(
                kind="frame",
                epoch=epoch,
                received_ns=time.time_ns(),
                raw=message.encode() if isinstance(message, str) else message,
            )
            if len(record.raw) > config.max_frame_bytes:
                reason = "frame_limit_unknown_loss"
                break
            try:
                queue.put_nowait(record)
                if health is not None:
                    health.set(HealthMetric.INGESTION, time.monotonic_ns())
                    queue_peak = max(queue_peak, queue.qsize())
                    health.set(HealthMetric.QUEUE, queue_peak)
            except asyncio.QueueFull:
                reason = "overload_unknown_loss"
                break
    except OSError, WebSocketException, TimeoutError:
        reason = "disconnect_unknown_loss"
    await queue.put(
        CaptureRecord(kind="session_end", epoch=epoch, received_ns=time.time_ns(), reason=reason)
    )


async def receive_snapshot(
    transport: VenueTransport,
    queue: asyncio.Queue[CaptureRecord],
    epoch: int,
) -> None:
    """Capture the independently fetched REST snapshot while WebSocket receipt continues.

    Args:
        transport: Explicit transport override for deterministic integration tests.
        queue: Bounded queue shared with the durable consumer.
        epoch: Connection epoch within the current recording.
    """
    try:
        raw = await asyncio.to_thread(transport.snapshot)
        record = CaptureRecord(kind="snapshot", epoch=epoch, received_ns=time.time_ns(), raw=raw)
    except OSError, ValueError, HTTPException:
        record = CaptureRecord(
            kind="gap",
            epoch=epoch,
            received_ns=time.time_ns(),
            reason="snapshot_failed_unknown_loss",
        )
    await queue.put(record)


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
        config=config, recording_id=str(uuid4()), implementation_identity=implementation_identity
    )
    root = output / request.recording_id
    journal, codec = CaptureJournal(root, request), DomainCodec()
    replay = (
        CaptureReplay(config) if snapshot_records is None else BookCapture(config, snapshot_records)
    )
    journal.start()
    deadline, reason = time.monotonic() + config.duration_seconds, "not_started"
    for epoch in range(config.retries + 1):
        if health is not None:
            health.set(HealthMetric.RECONNECTS, epoch)
        start = CaptureRecord(kind="session", epoch=epoch, received_ns=time.time_ns())
        journal.append(start)
        replay.apply(start)
        socket: FeedSocket | None = None
        reader: asyncio.Task[None] | None = None
        snapshot: asyncio.Task[None] | None = None
        queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(config.queue_capacity)
        try:
            budget = deadline - time.monotonic()
            if budget <= 0:
                reason = "duration_limit"
                break
            try:
                socket = await transport.open(budget)
                if config.venue == "bitfinex":
                    subscriptions: tuple[dict[str, object], ...] = (
                        {"event": "conf", "flags": 65536},
                        {
                            "event": "subscribe",
                            "channel": "book",
                            "symbol": config.symbol,
                            "prec": "R0",
                            "freq": "F0",
                            "len": str(config.depth),
                        },
                    )
                elif config.venue == "okx":
                    subscriptions = (
                        {
                            "op": "subscribe",
                            "args": [{"channel": "books", "instId": config.symbol}],
                        },
                    )
                else:
                    if credentials is None:
                        raise CoinbaseAccessError("missing Exchange credentials")
                    subscriptions = (
                        credentials.subscription(config.symbol, str(int(time.time()))),
                    )
                for subscription in subscriptions:
                    async with asyncio.timeout(max(0, deadline - time.monotonic())):
                        await socket.send(codec.encode_json(subscription).decode())
                del subscriptions
            except OSError, WebSocketException, TimeoutError:
                reason = "connect_failed_unknown_loss"
            else:
                reader = asyncio.create_task(
                    receive_frames(
                        socket,
                        queue,
                        config,
                        epoch,
                        deadline,
                        # Reserve the single REST response before accepting stream input.
                        config.max_messages - replay.messages - (config.venue == "coinbase"),
                        health,
                    )
                )
                reason = "message_limit"
                while (
                    not queue.empty()
                    or not reader.done()
                    or (snapshot is not None and not snapshot.done())
                ):
                    record = await queue.get()
                    if record.kind == "session_end":
                        if not replay.invalid or record.reason == "overload_unknown_loss":
                            reason = record.reason
                        if record.reason in ("duration_limit", "message_limit"):
                            continue
                        record = CaptureRecord(
                            kind="gap",
                            epoch=epoch,
                            received_ns=record.received_ns,
                            reason=record.reason,
                        )
                    try:
                        await asyncio.to_thread(journal.append, record)
                    except OSError:
                        if health is not None:
                            health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                        raise
                    except OverflowError:
                        reason = "storage_limit_unknown_tail"
                        break
                    if health is not None:
                        health.set(HealthMetric.PERSISTENCE, time.monotonic_ns())
                    previous_market_ns = replay.quality.last_market_ns
                    outcome = await asyncio.to_thread(replay.apply, record)
                    if health is not None:
                        health.set(HealthMetric.INVALID, len(replay.gaps))
                        if (
                            replay.quality.last_market_ns is not None
                            and replay.quality.last_market_ns != previous_market_ns
                        ):
                            age_ns = max(0, time.time_ns() - replay.quality.last_market_ns)
                            health.set(HealthMetric.MARKET, time.monotonic_ns() - age_ns)
                    if outcome == "invalid_frame" or record.kind == "gap":
                        if outcome == "invalid_frame":
                            reason = "invalid_stream_requires_snapshot"
                        elif reason == "message_limit":
                            reason = record.reason
                        reader.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await reader
                    if (
                        not replay.invalid
                        and isinstance(replay.book, CoinbaseBook)
                        and replay.book.acknowledged
                        and replay.book.schema
                        and snapshot is None
                    ):
                        snapshot = asyncio.create_task(receive_snapshot(transport, queue, epoch))
        finally:
            for task in (reader, snapshot):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            if socket is not None:
                await socket.close()
        if reason not in ("duration_limit", "message_limit") and not replay.invalid:
            gap = CaptureRecord(kind="gap", epoch=epoch, received_ns=time.time_ns(), reason=reason)
            journal.append(gap)
            replay.apply(gap)
        ending = CaptureRecord(
            kind="session_end", epoch=epoch, received_ns=time.time_ns(), reason=reason
        )
        journal.append(ending)
        replay.apply(ending)
        if reason in (
            "duration_limit",
            "message_limit",
            "storage_limit_unknown_tail",
            "overload_unknown_loss",
        ):
            break
        if epoch < config.retries and time.monotonic() < deadline:
            await asyncio.sleep(min(float(1 << epoch), max(0, deadline - time.monotonic())))
    if not replay.book.ready and not replay.invalid:
        gap = CaptureRecord(
            kind="gap",
            epoch=replay.epoch,
            received_ns=time.time_ns(),
            reason="capture_ended_before_synchronization",
        )
        journal.append(gap)
        replay.apply(gap)
    end = CaptureRecord(kind="end", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason)
    journal.append(end)
    replay.apply(end)
    descriptor = journal.finish(replay.started_ns or end.received_ns)
    if health is not None:
        health.set(HealthMetric.FINALIZING, 1)
    offline = CaptureReplay.read(root)
    if isinstance(replay, BookCapture):
        replay.verify(root)
    if offline.summary() != replay.summary():
        raise ValueError("saved-input replay differs from captured message-boundary state")
    summary = {
        **offline.summary(),
        "request_identity": request.identity,
        "saved_input_identity": descriptor.sha256,
        "saved_bytes": descriptor.size_bytes,
        "capture_directory": str(root.absolute()),
        "stop_reason": reason,
        "replay_parity": True,
        "canonical_parity": isinstance(replay, BookCapture),
    }
    (root / "summary.json").write_bytes(codec.encode_json(summary))
    if snapshot_directory is not None and snapshot_records is not None:
        summary["snapshot_identity"] = publish_book_dataset(
            (root,),
            RawStore(root),
            snapshot_directory,
            max_records=snapshot_records,
            max_bytes=config.max_bytes,
        )
        (root / "summary.json").write_bytes(codec.encode_json(summary))
    return summary


async def capture_heartbeat(health: HealthMetrics) -> None:
    """Advance process liveness independently of data and disk progress.

    Args:
        health: Shared observation owned by this child and its parent watchdog.
    """
    while True:
        health.set(HealthMetric.HEARTBEAT, time.monotonic_ns())
        await asyncio.sleep(0.1)


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
        heartbeat = group.create_task(capture_heartbeat(health))
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


def capture_process(
    config: CaptureConfig,
    output: Path,
    health: HealthMetrics,
    credentials: CoinbaseCredentials | None,
    transport: VenueTransport | None,
) -> None:
    """Run the collector in the watchdog's explicitly owned child process.

    Args:
        config: Validated native feed and resource limits.
        output: Unique supervisor-owned capture destination.
        health: Shared bounded clocks and counters.
        credentials: Explicit optional Exchange access capability.
        transport: Optional deterministic transport at the existing boundary.

    Raises:
        SystemExit: The parent records collector failure without logging exception payloads.
    """
    try:
        asyncio.run(monitored_capture(config, output, health, credentials, transport))
    except Exception:
        raise SystemExit(2) from None


def supervise(
    config: CaptureConfig,
    output: Path,
    policy: HealthPolicy,
    *,
    credentials: CoinbaseCredentials | None = None,
    transport: VenueTransport | None = None,
) -> dict[str, object]:
    """Watch a separate collector; stop it before attempting a bounded local alert.

    Args:
        config: Explicit feed selection and resource ceilings.
        output: Parent directory for a unique supervision record and child capture.
        policy: Independent liveness, progress, freshness and count limits.
        credentials: Explicit optional Exchange access capability.
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
    root, codec, health = output / str(uuid4()), DomainCodec(), HealthMetrics()
    root.mkdir(parents=True)
    (root / "health-policy.json").write_bytes(codec.encode_json(policy))
    (root / "capture-config.json").write_bytes(codec.encode_json(config))
    process = multiprocessing.get_context("spawn").Process(
        target=capture_process, args=(config, root, health, credentials, transport)
    )
    reason, values = "", health.snapshot()
    deadline = (
        time.monotonic()
        + policy.startup_seconds
        + config.duration_seconds
        + policy.progress_seconds
    )
    process.start()
    try:
        while True:
            process.join(0.1)
            try:
                values = health.snapshot()
                reason = policy.reason(values, now_ns=time.monotonic_ns())
            except TimeoutError:
                reason = "health_observation_stalled"
            if not reason and time.monotonic() > deadline:
                reason = "completion_stalled"
            if reason or not process.is_alive():
                reason = reason or ("collector_lost" if process.exitcode != 0 else "completed")
                break
    finally:
        if process.is_alive():
            process.terminate()
            process.join(1)
        if process.is_alive():
            process.kill()
            process.join(1)
    result: dict[str, object] = {
        "stop_reason": reason,
        "implementation_identity": InstalledIdentity.sha256(),
        "policy_identity": hashlib.sha256(codec.encode_json(policy)).hexdigest(),
        "supervision_directory": str(root.absolute()),
        "collector_stopped": not process.is_alive(),
        "exitcode": process.exitcode,
        "health": {metric.name.lower(): values[metric] for metric in HealthMetric},
        "alert_delivered": reason != "completed"
        and HealthAlert.deliver(
            policy.alert_socket, f"{root.name} {config.venue}:{config.symbol} {reason}"
        ),
    }
    (root / "health-summary.json").write_bytes(codec.encode_json(result))
    return result


class CaptureArguments(argparse.Namespace):
    """Typed installed command arguments; no credential values are accepted on the command line."""

    action: str
    config: Path
    output: Path
    secrets: Path | None
    capture: Path
    interrupted: bool
    snapshot_directory: Path | None
    snapshot_records: int | None
    health_config: Path | None


class InstalledIdentity:
    """Fingerprint the installed runtime source used by a capture, outside Git assumptions."""

    @staticmethod
    def sha256() -> str:
        """Hash installed modules in stable path order without reading local secrets.

        Returns:
            SHA-256 of the installed package source bytes and relative paths.
        """
        root = Path(__file__).resolve().parents[1]
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*.py")):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()


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
    probe_parser = commands.add_parser("probe")
    probe_parser.add_argument("--config", type=Path, required=True)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--capture", type=Path, required=True)
    replay_parser.add_argument("--interrupted", action="store_true")
    arguments = parser.parse_args(namespace=CaptureArguments())
    try:
        if arguments.action == "replay":
            result = CaptureReplay.read(
                arguments.capture, completed=not arguments.interrupted
            ).summary()
        else:
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
                    if (
                        arguments.snapshot_directory is not None
                        or arguments.snapshot_records is not None
                    ):
                        raise ValueError("supervised capture does not publish book snapshots")
                    result = supervise(
                        config,
                        arguments.output,
                        DomainCodec().decode_json(
                            arguments.health_config.read_bytes(), HealthPolicy
                        ),
                        credentials=credentials,
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
                        )
                    )
        print(DomainCodec().encode_json(result).decode(), flush=True)
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
