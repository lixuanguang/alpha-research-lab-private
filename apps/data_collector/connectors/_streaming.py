"""Streaming connector lifecycle implementations."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

import apps.data_collector.connectors._lifecycle as connector_lifecycle
import apps.data_collector.connectors._types as connector_types

_ResultT = TypeVar("_ResultT")


class StreamingConnector(connector_lifecycle.BaseConnector):
    """Base for websocket/long-poll streaming connectors."""

    def __init__(
        self,
        *,
        venue: str,
        emit: connector_lifecycle.EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue)
        self.set_emit_callback(emit)

    async def connect(self) -> None:
        """Open underlying stream connection."""
        raise NotImplementedError

    async def stream_loop(self) -> None:
        """Connect → consume → normalise → emit, with auto-reconnect."""
        raise NotImplementedError

    async def reconnect(self, backoff: float) -> None:
        self.state = connector_types.ConnectorState.RECONNECTING
        self._metrics.reconnect_count += 1
        await asyncio.sleep(max(0.0, backoff))
        self._mark_running()

    async def start(self) -> None:
        if self.state in {
            connector_types.ConnectorState.RUNNING,
            connector_types.ConnectorState.RECONNECTING,
        }:
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
                    self.record_runtime_error(str(exc))
                    if self._stop_event.is_set():
                        break
                    await self.reconnect(backoff=1.0)
        finally:
            if self.state is not connector_types.ConnectorState.ERROR:
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
        emit: connector_lifecycle.EmitCallback | None = None,
    ) -> None:
        super().__init__(venue=venue, emit=emit)
        if heartbeat_timeout <= 0:
            raise ValueError("`heartbeat_timeout` must be > 0")
        self._outcome_ids = connector_types.normalize_outcome_ids(outcome_ids)
        self._heartbeat_timeout = heartbeat_timeout
        self._next_reconnect_delay = next_reconnect_delay
        self._on_reconnect_reset = on_reconnect_reset

    async def _stream_outcome(self, outcome_id: str) -> None:
        """Consume one outcome stream until stop, exhaustion, or error."""
        raise NotImplementedError

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
                except connector_types.FatalConnectorError as error:
                    self.record_runtime_error(str(error))
                    break
                except Exception as error:
                    if self._stop_event.is_set():
                        break
                    delay = self._next_reconnect_delay(attempt)
                    attempt += 1
                    self._metrics.reconnect_count += 1
                    self._metrics.errors.append(f"stream error (attempt {attempt}): {error}")
                    self.state = connector_types.ConnectorState.RECONNECTING
                    await asyncio.sleep(max(0.0, delay))
        finally:
            if self.state is not connector_types.ConnectorState.ERROR:
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


__all__ = ["OutcomeStreamingConnector", "StreamingConnector"]
