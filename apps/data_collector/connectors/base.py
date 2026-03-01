"""Connector lifecycle abstractions for data collection."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

import alpha_core.events.models as event_models
import apps.data_collector.connectors.metrics as connector_metrics

EmitCallback = Callable[[list[event_models.CanonicalMarketEvent]], Awaitable[None] | None]
_ResultT = TypeVar("_ResultT")


@dataclass(slots=True)
class PollingBatch:
    """One polling result: canonical events plus bronze-ready raw payloads."""

    events: list[event_models.CanonicalMarketEvent]
    raw_payloads: dict[str, list[dict[str, object]]]


def normalize_outcome_ids(outcome_ids: list[str]) -> list[str]:
    """Normalize and deduplicate outcome ids while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for outcome_id in outcome_ids:
        cleaned = outcome_id.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


class ConnectorState(StrEnum):
    """Runtime state of a connector lifecycle."""

    IDLE = "idle"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    ERROR = "error"


class FatalConnectorError(RuntimeError):
    """Non-recoverable connector error that should not trigger reconnect loops."""


class BaseConnector(ABC):
    """Lifecycle-managed connection to a venue."""

    def __init__(self, *, venue: str) -> None:
        normalized_venue = venue.strip().lower()
        if not normalized_venue:
            raise ValueError("`venue` must be non-empty")

        self.venue = normalized_venue
        self.state = ConnectorState.IDLE
        self._metrics = connector_metrics.ConnectorMetrics()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._started_at_monotonic: float | None = None

    @property
    def connector_id(self) -> str:
        """Stable connector identifier: `{venue}:{connector_class}`."""
        return f"{self.venue}:{self.__class__.__name__}"

    @abstractmethod
    async def start(self) -> None:
        """Start connector lifecycle."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop connector lifecycle."""

    def metrics(self) -> connector_metrics.ConnectorMetrics:
        """Return a snapshot of current connector metrics."""
        snapshot = replace(self._metrics, errors=list(self._metrics.errors))
        if self._started_at_monotonic is not None and self.state in {
            ConnectorState.RUNNING,
            ConnectorState.RECONNECTING,
        }:
            snapshot.uptime_seconds = time.monotonic() - self._started_at_monotonic
        return snapshot

    def _mark_running(self) -> None:
        if self._started_at_monotonic is None:
            self._started_at_monotonic = time.monotonic()
            self._metrics.uptime_seconds = 0.0
        self.state = ConnectorState.RUNNING

    def _mark_stopped(self) -> None:
        self._freeze_uptime()
        self.state = ConnectorState.STOPPED
        self._started_at_monotonic = None

    def _record_error(self, message: str) -> None:
        self._freeze_uptime()
        self.state = ConnectorState.ERROR
        self._started_at_monotonic = None
        self._metrics.events_rejected += 1
        self._metrics.errors.append(message)

    def record_runtime_error(self, message: str) -> None:
        """Record a runtime error and transition connector state to error."""
        self._record_error(message)

    def _record_poll_failure(
        self,
        *,
        scope: str,
        outcome_id: str,
        error: BaseException,
    ) -> None:
        self._metrics.events_rejected += 1
        self._metrics.errors.append(f"{scope} poll failed for {outcome_id}: {error}")

    def _freeze_uptime(self) -> None:
        if self._started_at_monotonic is None:
            return
        self._metrics.uptime_seconds = max(
            self._metrics.uptime_seconds,
            time.monotonic() - self._started_at_monotonic,
        )

    def _record_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        count = len(events)
        self._metrics.events_received += count
        self._metrics.events_normalised += count
        if events:
            self._metrics.last_event_ts = datetime.now(tz=UTC)

    async def _emit_events(
        self,
        events: list[event_models.CanonicalMarketEvent],
        emit: EmitCallback | None,
    ) -> None:
        if not events or emit is None:
            return
        emitted = emit(events)
        if inspect.isawaitable(emitted):
            await emitted


class PollingConnector(BaseConnector):
    """Base for scheduled REST-polling connectors."""

    def __init__(
        self,
        *,
        venue: str,
        interval_seconds: float,
        request_timeout_seconds: float | None = 10.0,
        emit: EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue)
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be > 0")
        if request_timeout_seconds is not None and request_timeout_seconds <= 0:
            raise ValueError("`request_timeout_seconds` must be > 0 when configured")
        self.interval_seconds = interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._emit = emit

    @abstractmethod
    async def poll_once(self) -> PollingBatch:
        """Execute one polling cycle and return canonical + raw payload batch."""

    def event_types(self) -> list[str]:
        """Return event type dataset keys emitted by this connector."""
        return []

    async def execute_cycle(self) -> PollingBatch:
        """Execute one cycle and update connector metrics/emit callback."""
        batch = await self.poll_once()
        self._record_events(batch.events)
        await self._emit_events(batch.events, self._emit)
        return batch

    async def _await_with_timeout(
        self,
        awaitable: Awaitable[_ResultT],
        *,
        operation: str,
    ) -> _ResultT:
        timeout_seconds = self.request_timeout_seconds
        if timeout_seconds is None:
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except TimeoutError as exc:
            raise TimeoutError(f"{operation} timed out after {timeout_seconds:.2f}s") from exc

    async def start(self) -> None:
        if self.state in {ConnectorState.RUNNING, ConnectorState.RECONNECTING}:
            return
        self._stop_event.clear()
        self._mark_running()
        self._task = asyncio.create_task(self.run_loop(), name=self.connector_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._mark_stopped()

    async def run_loop(self) -> None:
        """Poll → normalise → emit, with sleep between cycles."""
        try:
            while not self._stop_event.is_set():
                await self.execute_cycle()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(str(exc))
        finally:
            if self.state is not ConnectorState.ERROR:
                self._mark_stopped()


class StreamingConnector(BaseConnector):
    """Base for websocket/long-poll streaming connectors."""

    def __init__(self, *, venue: str, emit: EmitCallback | None = None) -> None:
        super().__init__(venue=venue)
        self._emit = emit

    @abstractmethod
    async def connect(self) -> None:
        """Open underlying stream connection."""

    @abstractmethod
    async def stream_loop(self) -> None:
        """Connect → consume → normalise → emit, with auto-reconnect."""

    async def reconnect(self, backoff: float) -> None:
        self.state = ConnectorState.RECONNECTING
        self._metrics.reconnect_count += 1
        await asyncio.sleep(max(0.0, backoff))
        self._mark_running()

    async def start(self) -> None:
        if self.state in {ConnectorState.RUNNING, ConnectorState.RECONNECTING}:
            return
        self._stop_event.clear()
        self._mark_running()
        self._task = asyncio.create_task(self._run_stream(), name=self.connector_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._mark_stopped()

    async def _run_stream(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await self.connect()
                    self._mark_running()
                    await self.stream_loop()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._record_error(str(exc))
                    if self._stop_event.is_set():
                        break
                    await self.reconnect(backoff=1.0)
        finally:
            if self.state is not ConnectorState.ERROR:
                self._mark_stopped()


class OutcomeStreamingConnector(StreamingConnector):
    """Streaming connector base for one task per outcome id with reconnect support."""

    def __init__(
        self,
        *,
        venue: str,
        outcome_ids: list[str],
        heartbeat_timeout: float = 120.0,
        next_reconnect_delay: Callable[[int], float],
        on_reconnect_reset: Callable[[], None] | None = None,
        emit: EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue, emit=emit)
        if heartbeat_timeout <= 0:
            raise ValueError("`heartbeat_timeout` must be > 0")
        self._outcome_ids = normalize_outcome_ids(outcome_ids)
        self._heartbeat_timeout = heartbeat_timeout
        self._next_reconnect_delay = next_reconnect_delay
        self._on_reconnect_reset = on_reconnect_reset

    @abstractmethod
    async def _stream_outcome(self, outcome_id: str) -> None:
        """Consume one outcome stream until stop, exhaustion, or error."""

    async def stream_loop(self) -> None:
        if not self._outcome_ids:
            await self._stop_event.wait()
            return

        tasks = {
            asyncio.create_task(
                self._stream_outcome(outcome_id),
                name=f"{self.connector_id}:{outcome_id}",
            )
            for outcome_id in self._outcome_ids
        }
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

            for task in done:
                if task.cancelled():
                    if self._stop_event.is_set():
                        continue
                    raise RuntimeError(f"Outcome stream cancelled unexpectedly ({task.get_name()})")
                error = task.exception()
                if error is not None:
                    raise error
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            raise

    async def _run_stream(self) -> None:
        attempt = 0
        try:
            while not self._stop_event.is_set():
                try:
                    await self.connect()
                    self._mark_running()
                    if self._on_reconnect_reset is not None:
                        self._on_reconnect_reset()
                    attempt = 0
                    await self.stream_loop()
                    if not self._stop_event.is_set():
                        raise RuntimeError(
                            "All outcome streams ended unexpectedly "
                            f"for connector `{self.connector_id}`"
                        )
                except asyncio.CancelledError:
                    raise
                except FatalConnectorError as error:
                    self._record_error(str(error))
                    break
                except Exception as error:
                    if self._stop_event.is_set():
                        break
                    delay = self._next_reconnect_delay(attempt)
                    attempt += 1
                    self._metrics.reconnect_count += 1
                    self._metrics.errors.append(f"stream error (attempt {attempt}): {error}")
                    self.state = ConnectorState.RECONNECTING
                    await asyncio.sleep(max(0.0, delay))
        finally:
            if self.state is not ConnectorState.ERROR:
                self._mark_stopped()

    async def _next_stream_item(
        self,
        stream: AsyncIterator[_ResultT],
        *,
        outcome_id: str,
    ) -> _ResultT:
        try:
            return await asyncio.wait_for(
                anext(stream),
                timeout=self._heartbeat_timeout,
            )
        except TimeoutError as error:
            raise TimeoutError(
                f"No data for outcome `{outcome_id}` within {self._heartbeat_timeout:.2f}s"
            ) from error
