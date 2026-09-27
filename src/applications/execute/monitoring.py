"""Reopen local monitoring facts through the installed execution application."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# project library imports
from serialization import DomainCodec
from telemetry import (
    DashboardBuilder,
    DashboardSnapshot,
    MetricRegistry,
    MonitoringDefinitions,
    OperationalAlerts,
    TelemetryStore,
)
from telemetry import MonitoringConfiguration as MonitoringConfiguration


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
