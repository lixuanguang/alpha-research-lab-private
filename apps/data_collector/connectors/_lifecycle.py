"""Base connector lifecycle primitives."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime

import alpha_core.events.models as event_models
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.connectors.metrics as connector_metrics

EmitCallback = Callable[[list[event_models.CanonicalMarketEvent]], Awaitable[None] | None]


class BaseConnector(ABC):
    """Lifecycle-managed connection to a venue."""

    def __init__(self, *, venue: str) -> None:
        normalized_venue = venue.strip().lower()
        if not normalized_venue:
            raise ValueError("`venue` must be non-empty")

        self.venue = normalized_venue
        self.state = connector_types.ConnectorState.IDLE
        self._metrics = connector_metrics.ConnectorMetrics()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._started_at_monotonic: float | None = None
        self._emit: EmitCallback | None = None

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
            connector_types.ConnectorState.RUNNING,
            connector_types.ConnectorState.RECONNECTING,
        }:
            snapshot.uptime_seconds = time.monotonic() - self._started_at_monotonic
        return snapshot

    def set_emit_callback(self, emit: EmitCallback | None) -> None:
        """Set connector event callback used by lifecycle loops."""
        self._emit = emit

    async def wait_until_stopped(self) -> None:
        """Await the connector run task when started."""
        if self._task is None:
            return
        await self._task

    async def cancel_run_task(self) -> None:
        """Cancel and await an in-flight run task, if present."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task

    def _mark_running(self) -> None:
        if self._started_at_monotonic is None:
            self._started_at_monotonic = time.monotonic()
            self._metrics.uptime_seconds = 0.0
        self.state = connector_types.ConnectorState.RUNNING

    def _mark_stopped(self) -> None:
        self._freeze_uptime()
        self.state = connector_types.ConnectorState.STOPPED
        self._started_at_monotonic = None

    def record_runtime_error(self, message: str) -> None:
        """Record a runtime error and transition connector state to error."""
        self._freeze_uptime()
        self.state = connector_types.ConnectorState.ERROR
        self._started_at_monotonic = None
        self._metrics.events_rejected += 1
        self._metrics.errors.append(message)

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

    async def _emit_events(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        if not events or self._emit is None:
            return
        emitted = self._emit(events)
        if inspect.isawaitable(emitted):
            await emitted


__all__ = ["BaseConnector", "EmitCallback"]
