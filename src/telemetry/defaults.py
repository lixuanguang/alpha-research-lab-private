"""Provide explicit monitoring definitions for installed operating signals."""

from __future__ import annotations

# standard library imports
import hashlib
from pathlib import Path

# project library imports
from telemetry import metrics
from telemetry.events import MonitoringEvent, MonitoringMode
from telemetry.metrics import (
    DelayedLabelError,
    MetricInput,
    MetricSpec,
    MonitoringMetric,
    SeriesMetric,
)


class MonitoringDefinitions:
    """Construct the installed metric implementations without arbitrary configuration imports."""

    @staticmethod
    def code_identity() -> str:
        """Identify the actual installed exact metric implementation bytes."""
        return hashlib.sha256(Path(metrics.__file__).read_bytes()).hexdigest()

    @classmethod
    def resolve(cls, specs: tuple[MetricSpec, ...]) -> tuple[MonitoringMetric, ...]:
        """Resolve supported builtins only when the configured code digest matches installation."""
        result: list[MonitoringMetric] = []
        for spec in specs:
            if spec.implementation_sha256 != cls.code_identity():
                raise ValueError("configured metric implementation differs from installed bytes")
            result.append(
                DelayedLabelError(spec) if spec.aggregation == "custom" else SeriesMetric(spec)
            )
        return tuple(result)

    @classmethod
    def defaults(
        cls, mode: MonitoringMode, events: tuple[MonitoringEvent, ...] = ()
    ) -> tuple[MetricSpec, ...]:
        """Select explicit data/runtime or risk/account panels plus observed dimensioned balances.

        Missing signals stay missing. This does not manufacture venue observations
        or operating thresholds. The caller may edit the resulting definitions and
        alert policy before retaining a dashboard configuration.
        """
        signals: tuple[tuple[str, str], ...] = (
            (
                ("runtime.heartbeat_age_seconds", "seconds"),
                ("data.ingestion_age_seconds", "seconds"),
                ("data.persistence_age_seconds", "seconds"),
                ("data.market_age_seconds", "seconds"),
                ("data.queue_peak", "count"),
                ("data.queue_bytes", "bytes"),
                ("data.queue_age_seconds", "seconds"),
                ("data.receipt_to_durable_seconds", "seconds"),
                ("data.reconnects", "count"),
                ("data.invalid", "count"),
                ("data.duplicates", "count"),
                ("data.gaps", "count"),
                ("data.received_frames", "count"),
                ("data.durable_frames", "count"),
                ("data.persisted_records", "count"),
                ("data.source_clock_drift_seconds", "seconds"),
                ("data.persistence_failed", "count"),
                ("runtime.stopped", "boolean"),
                ("runtime.faulted", "boolean"),
                ("runtime.alert_delivery_failure", "boolean"),
            )
            if mode == "data"
            else (
                ("risk.blocked", "boolean"),
                ("risk.admission_rejected", "boolean"),
                ("account.reconciliation_age_seconds", "seconds"),
                ("account.reconciliation_failed", "boolean"),
                ("execution.open_orders", "count"),
                ("execution.uncertain", "count"),
                ("execution.rejected", "count"),
                ("execution.cancel_pending", "count"),
                ("runtime.alert_delivery_failure", "count"),
            )
        )
        if mode == "venue_test":
            signals += (
                ("execution.venue_recovery_required", "boolean"),
                ("execution.receipts", "count"),
            )
        selected = dict(signals)
        for event in events:
            if event.name.startswith(("account.cash.", "account.position.")):
                if event.name in selected and selected[event.name] != event.units:
                    raise ValueError("default monitoring balance has conflicting units")
                selected[event.name] = event.units
        if len(selected) > 32:
            raise ValueError("select explicit panels for more than 32 default signals")
        return tuple(
            MetricSpec(
                name=name,
                version="1",
                implementation_sha256=cls.code_identity(),
                inputs=(MetricInput(name=name, version="1", units=units),),
                units=units,
                modes=(mode,),
                aggregation="last",
                missingness="propagate",
                stale_after_seconds=60,
            )
            for name, units in selected.items()
        )
