"""Unit tests for connector manager orchestration."""

from __future__ import annotations

import asyncio

import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.manager as connector_manager
import apps.data_collector.connectors.metrics as connector_metrics
import pytest


class _StubConnector(connector_base.BaseConnector):
    def __init__(self, venue: str, name: str) -> None:
        super().__init__(venue=venue)
        self._name = name
        self.started = False
        self.stopped = False

    @property
    def connector_id(self) -> str:
        return f"{self.venue}:{self._name}"

    async def start(self) -> None:
        self.started = True
        self.state = connector_base.ConnectorState.RUNNING

    async def stop(self) -> None:
        self.stopped = True
        self.state = connector_base.ConnectorState.STOPPED

    def metrics(self) -> connector_metrics.ConnectorMetrics:
        return connector_metrics.ConnectorMetrics(events_received=1, events_normalised=1)


class _FailingStartConnector(_StubConnector):
    async def start(self) -> None:
        self.started = True
        raise RuntimeError("start failed")


class _FailingStopConnector(_StubConnector):
    async def stop(self) -> None:
        self.stopped = True
        raise RuntimeError("stop failed")


async def _register_and_start(
    manager: connector_manager.ConnectorManager,
    connectors: list[_StubConnector],
) -> None:
    for connector in connectors:
        manager.register(connector)
    await manager.start_all()


async def _register_start_stop(
    manager: connector_manager.ConnectorManager,
    connectors: list[_StubConnector],
) -> None:
    await _register_and_start(manager, connectors)
    await manager.stop_all()


async def _capture_status_and_metrics(
    manager: connector_manager.ConnectorManager,
    connector: _StubConnector,
) -> tuple[
    dict[str, connector_base.ConnectorState],
    dict[str, connector_metrics.ConnectorMetrics],
]:
    manager.register(connector)
    await manager.start_all()
    statuses = manager.status()
    metrics = manager.metrics()
    await manager.stop_all()
    return statuses, metrics


def test_connector_manager_register_rejects_duplicates() -> None:
    manager = connector_manager.ConnectorManager()
    connector = _StubConnector("kalshi", "market_refresh")

    manager.register(connector)
    with pytest.raises(ValueError, match="Connector already registered"):
        manager.register(connector)


def test_connector_manager_noop_start_stop_with_no_registered_connectors() -> None:
    manager = connector_manager.ConnectorManager()

    asyncio.run(manager.start_all())
    asyncio.run(manager.stop_all())

    assert manager.status() == {}
    assert manager.metrics() == {}


def test_connector_manager_start_and_stop_all() -> None:
    manager = connector_manager.ConnectorManager()
    first = _StubConnector("kalshi", "first")
    second = _StubConnector("polymarket", "second")
    asyncio.run(_register_start_stop(manager, [first, second]))

    assert first.started and second.started
    assert first.stopped and second.stopped


def test_connector_manager_reports_status_and_metrics() -> None:
    manager = connector_manager.ConnectorManager()
    connector = _StubConnector("kalshi", "status")
    statuses, metrics = asyncio.run(_capture_status_and_metrics(manager, connector))

    assert statuses["kalshi:status"] == connector_base.ConnectorState.RUNNING
    assert metrics["kalshi:status"].events_received == 1


def test_connector_manager_start_all_rolls_back_started_connectors_on_failure() -> None:
    manager = connector_manager.ConnectorManager()
    failing = _FailingStartConnector("kalshi", "failing")
    healthy = _StubConnector("polymarket", "healthy")
    with pytest.raises(ExceptionGroup, match="Connector start failures"):
        asyncio.run(_register_and_start(manager, [failing, healthy]))

    assert failing.started
    assert healthy.started
    assert failing.stopped
    assert healthy.stopped


def test_connector_manager_stop_all_attempts_all_and_aggregates_failures() -> None:
    manager = connector_manager.ConnectorManager()
    failing = _FailingStopConnector("kalshi", "failing")
    healthy = _StubConnector("polymarket", "healthy")
    with pytest.raises(ExceptionGroup, match="Connector stop failures"):
        asyncio.run(_register_start_stop(manager, [failing, healthy]))

    assert failing.stopped
    assert healthy.stopped
