"""Connector orchestration utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.metrics as connector_metrics


class ConnectorManager:
    """Manages lifecycle of all connectors for all venues."""

    def __init__(self) -> None:
        self._connectors: dict[str, connector_base.BaseConnector] = {}

    def register(self, connector: connector_base.BaseConnector) -> None:
        if connector.connector_id in self._connectors:
            raise ValueError(f"Connector already registered: {connector.connector_id}")
        self._connectors[connector.connector_id] = connector

    async def start_all(self) -> None:
        await self._run_all("start", lambda connector: connector.start())

    async def stop_all(self) -> None:
        await self._run_all("stop", lambda connector: connector.stop())

    def status(self) -> dict[str, connector_base.ConnectorState]:
        return {name: connector.state for name, connector in self._connectors.items()}

    def metrics(self) -> dict[str, connector_metrics.ConnectorMetrics]:
        return {name: connector.metrics() for name, connector in self._connectors.items()}

    async def _run_all(
        self,
        action: str,
        operation: Callable[
            [connector_base.BaseConnector],
            Coroutine[object, object, None],
        ],
    ) -> None:
        connectors = list(self._connectors.values())
        if not connectors:
            return

        coroutines = [operation(connector) for connector in connectors]
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        failures: list[Exception] = []
        for connector, result in zip(connectors, results, strict=True):
            if not isinstance(result, BaseException):
                continue
            failures.append(RuntimeError(f"{action} failed for {connector.connector_id}: {result}"))

        if failures and action == "start":
            rollback_results = await asyncio.gather(
                *(connector.stop() for connector in connectors),
                return_exceptions=True,
            )
            for connector, result in zip(connectors, rollback_results, strict=True):
                if not isinstance(result, BaseException):
                    continue
                failures.append(
                    RuntimeError(f"rollback stop failed for {connector.connector_id}: {result}")
                )

        if failures:
            raise ExceptionGroup(f"Connector {action} failures", failures)
