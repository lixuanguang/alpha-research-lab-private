"""Connector lifecycle abstractions for data collection."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum

import alpha_core.events.models as event_models
import apps.data_collector.connectors.metrics as connector_metrics

EmitCallback = Callable[[list[event_models.CanonicalMarketEvent]], Awaitable[None] | None]


class ConnectorState(StrEnum):
    """Runtime state of a connector lifecycle."""

    IDLE = "idle"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    ERROR = "error"


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
        emit: EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue)
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be > 0")
        self.interval_seconds = interval_seconds
        self._emit = emit

    @abstractmethod
    async def poll_once(self) -> list[event_models.CanonicalMarketEvent]:
        """Execute one polling cycle and return canonical events."""

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
                events = await self.poll_once()
                self._record_events(events)
                await self._emit_events(events, self._emit)
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
