"""Polling connector lifecycle implementation."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import TypeVar

import apps.data_collector.connectors._lifecycle as connector_lifecycle
import apps.data_collector.connectors._types as connector_types

_ResultT = TypeVar("_ResultT")


class PollingConnector(connector_lifecycle.BaseConnector):
    """Base for scheduled REST-polling connectors."""

    def __init__(
        self,
        *,
        venue: str,
        interval_seconds: float,
        request_timeout_seconds: float | None = 10.0,
        emit: connector_lifecycle.EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue)
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be > 0")
        if request_timeout_seconds is not None and request_timeout_seconds <= 0:
            raise ValueError("`request_timeout_seconds` must be > 0 when configured")
        self.interval_seconds = interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.set_emit_callback(emit)

    async def poll_once(self) -> connector_types.PollingBatch:
        """Execute one polling cycle and return canonical + raw payload batch."""
        raise NotImplementedError

    def event_types(self) -> list[str]:
        """Return event type dataset keys emitted by this connector."""
        return []

    async def execute_cycle(self) -> connector_types.PollingBatch:
        """Execute one cycle and update connector metrics/emit callback."""
        batch = await self.poll_once()
        self._record_events(batch.events)
        await self._emit_events(batch.events)
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
        if self.state in {
            connector_types.ConnectorState.RUNNING,
            connector_types.ConnectorState.RECONNECTING,
        }:
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
            if self.state is not connector_types.ConnectorState.ERROR:
                self._mark_stopped()


__all__ = ["PollingConnector"]
