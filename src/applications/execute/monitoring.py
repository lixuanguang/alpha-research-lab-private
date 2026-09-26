"""Reopen local monitoring facts through the installed execution application."""

from __future__ import annotations

# standard library imports
from pathlib import Path
from typing import Literal

# project library imports
from serialization import DomainCodec, WireRecord
from telemetry import (
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    DashboardSnapshot,
    MetricRegistry,
    MetricSpec,
    MonitoringDefinitions,
    MonitoringEvent,
    MonitoringQuery,
    OperationalAlerts,
    TelemetryStore,
)


class MonitoringConfiguration(WireRecord, frozen=True):
    """Select a query, exact metric code and presentation without executable authority."""

    query: MonitoringQuery
    metrics: tuple[MetricSpec, ...]
    dashboard: DashboardConfig
    schema_version: Literal["monitoring-configuration-v1"] = "monitoring-configuration-v1"

    def __post_init__(self) -> None:
        """Require every selected panel/rule to resolve to exactly one declared definition."""
        if type(self.query) is not MonitoringQuery or type(self.dashboard) is not DashboardConfig:
            raise TypeError("monitoring configuration requires typed query and dashboard")
        self.query.__post_init__()
        self.dashboard.__post_init__()
        if type(self.metrics) is not tuple or not 1 <= len(self.metrics) <= 64:
            raise ValueError("monitoring configuration requires bounded metric definitions")
        for metric in self.metrics:
            if type(metric) is not MetricSpec:
                raise TypeError("monitoring definitions must be typed")
            metric.__post_init__()
        identities = tuple(metric.identity for metric in self.metrics)
        if len(set(identities)) != len(identities) or set(identities) != set(
            self.dashboard.metric_identities
        ):
            raise ValueError("monitoring definitions differ from selected panels and alerts")
        if self.schema_version != "monitoring-configuration-v1":
            raise ValueError("unsupported monitoring configuration schema")

    @classmethod
    def defaults(
        cls, query: MonitoringQuery, events: tuple[MonitoringEvent, ...] = ()
    ) -> MonitoringConfiguration:
        """Create editable operating views with explicit installed code and no alert routes."""
        if query.mode == "research":
            raise ValueError("research monitoring requires selected research metric definitions")
        definitions = MonitoringDefinitions.defaults(query.mode, events)
        return cls(
            query=query,
            metrics=definitions,
            dashboard=DashboardConfig(
                title=f"Operating observations · {query.scope}",
                panels=tuple(
                    DashboardPanel(
                        title=spec.name.replace(".", " / "),
                        metric_identity=spec.identity,
                        kind="line",
                    )
                    for spec in definitions
                ),
            ),
        )


class MonitoringApplication:
    """Compose installed queries, reviewed metrics, optional local routes and retained HTML."""

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        output: Path,
        alerts_path: Path | None = None,
    ) -> DashboardSnapshot:
        """Render a retained dashboard; alert routes run only with an explicit alert journal.

        The command never opens a venue transport, modifies account state or
        grants trading authority. It refuses incompatible metric bytes and query
        overflow. Disk, schema and read failures propagate visibly to the CLI.
        """
        if config_path.stat().st_size > 1_048_576:
            raise ValueError("monitoring configuration exceeds 1 MiB")
        config = DomainCodec().decode_json(config_path.read_bytes(), MonitoringConfiguration)
        config.__post_init__()
        registry = MetricRegistry(MonitoringDefinitions.resolve(config.metrics))
        events = TelemetryStore(journal_path).query(config.query)
        snapshot = DashboardBuilder.build(
            config.dashboard,
            config.query,
            events,
            registry,
            None if alerts_path is None else OperationalAlerts(alerts_path),
        )
        snapshot.write(output)
        return snapshot
