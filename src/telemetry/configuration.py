"""Select retained monitoring views through explicit installed metric identities."""

from __future__ import annotations

# standard library imports
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import ExactRatio
from serialization import WireRecord
from telemetry.dashboard import AlertOperator, AlertRule, DashboardConfig, DashboardPanel
from telemetry.defaults import MonitoringDefinitions
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringQuery
from telemetry.metrics import MetricInput, MetricSpec


class MetricThreshold(WireRecord, frozen=True):
    """Declare one exact diagnostic band edge for a named series, such as a candidate's.

    Missing or stale values are unavailable, never a breach: a declared band
    diagnoses the value, not the series' freshness.
    """

    name: str
    operator: AlertOperator
    threshold: ExactRatio

    def __post_init__(self) -> None:
        """Require a bounded name, an exact comparison and an exact threshold."""
        MonitoringIdentity.check_text(self.name)
        if self.operator not in ("<", ">") or type(self.threshold) is not ExactRatio:
            raise ValueError("invalid metric threshold")
        self.threshold.__post_init__()


class MonitoringConfiguration(WireRecord, frozen=True):
    """Select a query, exact metric code and presentation without executable authority."""

    query: MonitoringQuery
    metrics: tuple[MetricSpec, ...]
    dashboard: DashboardConfig
    schema_version: Literal["monitoring-configuration"] = "monitoring-configuration"

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
        if self.schema_version != "monitoring-configuration":
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

    @classmethod
    def paper(
        cls,
        query: MonitoringQuery,
        events: tuple[MonitoringEvent, ...],
        *,
        alert_socket: str | None = None,
        thresholds: tuple[MetricThreshold, ...] = (),
    ) -> tuple[MonitoringConfiguration, ...]:
        """Select dimensioned cumulative last values and optional diagnostic routes.

        Separate strategy scopes and currencies remain separate series. Up to 32
        panels per retained page keep the existing renderer's bounds. Lifecycle
        event facts remain in the journal for custom metric/chart consumers.
        Thresholds diagnose blocks, uncertainty, failed reconciliation and source
        failure; they do not implement hard controls. Missing/stale facts trigger
        the configured diagnostic route rather than silently appearing healthy.
        ``thresholds`` add declared band edges, such as a candidate metric's
        warning bands, on the page holding their series.
        """
        if query.mode != "paper":
            raise ValueError("paper views require paper mode")
        selected: dict[str, str] = {}
        for event in events:
            if event.context.scope != query.scope or event.context.mode != query.mode:
                continue
            if event.name.startswith("execution.event."):
                continue
            if event.name in selected and selected[event.name] != event.units:
                raise ValueError("paper series has conflicting units")
            selected[event.name] = event.units
        if not selected:
            raise ValueError("paper view requires declared input series")
        specs = tuple(
            MetricSpec(
                name=name,
                version="1",
                implementation_sha256=MonitoringDefinitions.code_identity(),
                inputs=(MetricInput(name=name, version="1", units=units),),
                units=units,
                modes=("paper",),
                aggregation="last",
                missingness="propagate",
                stale_after_seconds=60,
            )
            for name, units in sorted(selected.items())
        )
        diagnostics = {
            "risk.blocked": Fraction(0),
            "account.reconciliation_failed": Fraction(0),
            "execution.uncertain": Fraction(0),
            "runtime.faulted": Fraction(0),
            "data.unavailable": Fraction(0),
        }
        diagnostics.update(
            (name, Fraction(0)) for name in selected if name.startswith("paper.net_pnl.")
        )
        views: list[MonitoringConfiguration] = []
        for offset in range(0, len(specs), 32):
            page = specs[offset : offset + 32]
            views.append(
                cls(
                    query=query,
                    metrics=page,
                    dashboard=DashboardConfig(
                        title=f"Paper observations · {query.scope} · {offset // 32 + 1}",
                        panels=tuple(
                            DashboardPanel(
                                title=spec.name.replace(".", " / "),
                                metric_identity=spec.identity,
                                kind="table",
                            )
                            for spec in page
                        ),
                        alerts=tuple(
                            AlertRule(
                                identity=f"paper:{spec.name}",
                                metric_identity=spec.identity,
                                operator="<" if spec.name.startswith("paper.net_pnl.") else ">",
                                threshold=ExactRatio.from_fraction(diagnostics[spec.name]),
                                units=spec.units,
                                address=alert_socket,
                                on_missing="trigger",
                                on_stale="trigger",
                            )
                            for spec in page
                            if spec.name in diagnostics and alert_socket is not None
                        )
                        + tuple(
                            AlertRule(
                                identity=f"threshold:{spec.name}:{edge.operator}",
                                metric_identity=spec.identity,
                                operator=edge.operator,
                                threshold=edge.threshold,
                                units=spec.units,
                                address=alert_socket,
                            )
                            for spec in page
                            for edge in thresholds
                            if edge.name == spec.name and alert_socket is not None
                        ),
                    ),
                )
            )
        return tuple(views)
