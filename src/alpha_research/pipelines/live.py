"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import argparse
import asyncio
import contextlib
import hashlib
import sys
import time
from pathlib import Path
from uuid import uuid4

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.live.replay import CaptureReplay
from alpha_research.data.live.transport import FeedSocket, VenueTransport
from alpha_research.data.venues.coinbase.auth import CoinbaseAccessError, CoinbaseCredentials
from alpha_research.data.venues.coinbase.book import CoinbaseBook
from alpha_research.serialization import DomainCodec


async def receive_frames(
    socket: FeedSocket,
    queue: asyncio.Queue[CaptureRecord],
    config: CaptureConfig,
    epoch: int,
    deadline: float,
    remaining: int,
) -> None:
    """Timestamp receipt independently of persistence; stop visibly on overload or disconnect.

    Args:
        socket: This epoch's open message connection.
        queue: Bounded queue shared with the durable consumer.
        config: Validated native spot source selection and resource budgets.
        epoch: Connection epoch within the current recording.
        deadline: Monotonic receive deadline in seconds.
        remaining: Maximum additional received WebSocket messages.
    """
    reason = "message_limit"
    awaiting_pong = False
    received = 0
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
    except OSError, ValueError:
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
) -> dict[str, object]:
    """Collect one finite recording with bounded retry, durable-before-apply and replay parity.

    Output is a unique directory, never appended to a prior recording. Persistence
    failures propagate without trying to write success onto the failing medium.
    The incomplete journal remains visible for explicit offline inspection.

    Args:
        config: Validated native spot source selection and resource budgets.
        output: Parent directory for a new UUID-named recording.
        implementation_identity: SHA-256 identity of the installed runtime implementation.
        credentials: Explicit Exchange signing capability; required only for Coinbase.
        transport: Explicit transport override for deterministic integration tests.

    Returns:
        Saved-input identity, replay parity, bounded counts and gap summary.

    Raises:
        CoinbaseAccessError: Exchange credentials are missing, malformed or incompatible.
        ValueError: The source schema, identity, continuity or resource contract is invalid.
    """
    config.__post_init__()
    if config.venue == "coinbase" and credentials is None:
        raise CoinbaseAccessError("Coinbase Exchange credentials are required before connection")
    transport = transport if transport is not None else VenueTransport(config)
    request = CaptureRequest(
        config=config, recording_id=str(uuid4()), implementation_identity=implementation_identity
    )
    root = output / request.recording_id
    journal, replay, codec = CaptureJournal(root, request), CaptureReplay(config), DomainCodec()
    journal.start()
    deadline, reason = time.monotonic() + config.duration_seconds, "not_started"
    for epoch in range(config.retries + 1):
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
                        config.max_messages - replay.messages,
                    )
                )
                while True:
                    record = await queue.get()
                    if record.kind == "session_end":
                        reason = record.reason
                        break
                    try:
                        await asyncio.to_thread(journal.append, record)
                    except OverflowError:
                        reason = "storage_limit_unknown_tail"
                        break
                    outcome = replay.apply(record)
                    if outcome == "invalid_frame" or record.kind == "gap":
                        reason = "invalid_stream_requires_snapshot"
                        break
                    if (
                        isinstance(replay.book, CoinbaseBook)
                        and replay.book.acknowledged
                        and replay.book.schema
                        and snapshot is None
                    ):
                        snapshot = asyncio.create_task(receive_snapshot(transport, queue, epoch))
                    if replay.messages >= config.max_messages:
                        reason = "message_limit"
                        break
        finally:
            for task in (reader, snapshot):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            if socket is not None:
                await socket.close()
        if reason not in ("duration_limit", "message_limit"):
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
    offline = CaptureReplay.read(root)
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
    }
    (root / "summary.json").write_bytes(codec.encode_json(summary))
    return summary


class CaptureArguments(argparse.Namespace):
    """Typed installed command arguments; no credential values are accepted on the command line."""

    action: str
    config: Path
    output: Path
    secrets: Path | None
    capture: Path
    interrupted: bool


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
                result = asyncio.run(
                    collect(
                        config,
                        arguments.output,
                        credentials=credentials,
                        implementation_identity=InstalledIdentity.sha256(),
                    )
                )
        print(DomainCodec().encode_json(result).decode(), flush=True)
        if arguments.action == "capture" and (result.get("gaps") or not result.get("synchronized")):
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
