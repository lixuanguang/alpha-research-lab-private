"""Export deployed candidates' monitoring facts and render account dashboards from diagnostics."""

from __future__ import annotations

# standard library imports
import fcntl
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

# project library imports
from applications.execute.monitoring_store import MonitoringStore
from applications.execute.service_candidates import PaperServiceCandidates
from configuration import PaperServiceConfiguration
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    PaperMarket,
    PaperOwner,
    SocketPaperAccount,
)
from runtime import (
    CandidateEvidence,
    CandidateMonitoringExporter,
    SharedBookDelivery,
    SharedCandidateCheckpoint,
)
from serialization import DomainCodec
from telemetry import (
    DashboardBuilder,
    MetricRegistry,
    MetricThreshold,
    MonitoringConfiguration,
    MonitoringDefinitions,
    MonitoringEvent,
    MonitoringQuery,
    OperationalAlerts,
    TelemetryStore,
)


class CandidateTelemetry:
    """Export each deployed candidate's facts and render its account's dashboards.

    Runs inside the read-only diagnostics process. Per account sample it exports
    every instance's runtime metrics over its attributed fills, each newly decided
    instant's decision delay from the supervisor's fsynced delivery logs, and each
    newly committed learned prediction from the instance's continuation. At most
    every ``dashboard_seconds`` it renders the account's paper or shadow pages with
    the installed defaults, one panel per exported series and one alert rule per
    declared candidate warning band, delivered to ``alert_socket``. It holds no
    account authority: its only account call is a checkpoint inspection.

    Rendered views are bounded: after each rendering, every page keeps its newest
    view and the first view of each UTC hour, and older views are removed. A removed
    view can be rendered again while the telemetry store still holds its events, for
    the store's ``retention_days``. A delivered alert's outcome stays in the alert
    journal regardless.
    """

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        *,
        candidates: Path | None,
        runs: Path,
        root: Path,
        started_at: datetime,
        dashboard_seconds: float = 60.0,
        dashboard_window: timedelta = timedelta(minutes=15),
    ) -> None:
        """Load every configured instance's candidate and bind the run's delivery logs."""
        resolved = PaperServiceCandidates(configuration, candidates)
        self.retention = MonitoringStore.retention(configuration)
        releases = {owner.account_id: owner.release_identity for owner in owners}
        modes = {item.account_id: item.configuration.mode for item in configuration.accounts}
        self.exporters: dict[str, CandidateMonitoringExporter] = {}
        self.accounts: dict[str, str] = {}
        for instance in configuration.instances:
            loaded = resolved.candidate(instance)
            mode = modes[instance.account_id]
            if mode not in ("paper", "shadow"):
                raise ValueError("candidate telemetry requires paper or shadow accounts")
            # Each instance has its own scope, so candidates sharing an account and a
            # metric contract stay separate series.
            self.exporters[instance.instance_id] = CandidateMonitoringExporter(
                loaded,
                scope=f"account:{instance.account_id}:strategy:{instance.instance_id}",
                account=instance.account_id,
                mode="paper" if mode == "paper" else "shadow",
                clock_quality="observed",
                study=loaded.definition.identity,
                release=releases[instance.account_id],
            )
            self.accounts[instance.instance_id] = instance.account_id
        self.configuration, self.runs, self.root = configuration, runs, root
        root.mkdir(parents=True, exist_ok=True)
        self.started_at = started_at
        self.failures = 0
        self.last_error: str | None = None
        self._dashboard_seconds, self._dashboard_window = dashboard_seconds, dashboard_window
        self._next_dashboard: dict[str, float] = {}
        self._offsets: dict[Path, int] = {}
        self._predicted: dict[str, datetime] = {}
        self._codec = DomainCodec()

    def sample(
        self,
        account: SocketPaperAccount,
        state: AccountExecutionResult,
        markets: tuple[PaperMarket, ...],
        *,
        observed_at: datetime,
    ) -> None:
        """Export one account's candidate facts and, when due, render its dashboards.

        Failures are counted and kept visible; they never reach the account.
        """
        owner = account.paper_owner
        if owner is None:
            raise ValueError("candidate telemetry requires an identified account owner")
        account_id = owner.account_id
        try:
            events = (
                *self._metrics(account_id, state, markets, observed_at),
                *self._predictions(account, account_id, observed_at),
                *self._delays(account_id, observed_at),
            )
            # The service monitor owns pruning; this writer only shares its capacity.
            MonitoringStore.open(self.root, self.retention).append(events)
            due = self._next_dashboard.get(account_id, 0.0)
            mode = account.config.mode
            if time.monotonic() >= due and (mode == "paper" or mode == "shadow"):
                self._next_dashboard[account_id] = time.monotonic() + self._dashboard_seconds
                self._dashboards(account_id, mode, observed_at)
        except Exception as error:
            self.failures += 1
            self.last_error = f"candidate_telemetry:{type(error).__name__}: {error}"

    def _instances(self, account_id: str) -> tuple[str, ...]:
        """Return the account's configured instances in configuration order."""
        return tuple(name for name, owner in self.accounts.items() if owner == account_id)

    def _metrics(
        self,
        account_id: str,
        state: AccountExecutionResult,
        markets: tuple[PaperMarket, ...],
        observed_at: datetime,
    ) -> tuple[MonitoringEvent, ...]:
        """Evaluate each instance's runtime metrics over its attributed fills."""
        limits = {
            limit.instance_id: limit.maximum
            for item in self.configuration.accounts
            for limit in item.configuration.budgets.instances
        }
        events: list[MonitoringEvent] = []
        for name in self._instances(account_id):
            exporter = self.exporters[name]
            if not exporter.metrics:
                continue
            entity = exporter.loaded.deployment.entity
            marks = sorted(
                (item for item in markets if str(item.bid.per.instrument_id) == entity),
                key=self._market_order,
            )
            start = exporter.loaded.deployment.starts_at
            if observed_at <= start:
                continue
            events.extend(
                exporter.runtime_metrics(
                    CandidateEvidence(
                        fills=tuple(
                            item.fill for item in state.paper_fills if item.instance_id == name
                        ),
                        initial_cash=limits[name],
                        mark=marks[-1].bid if marks else None,
                        start=start,
                        cutoff=observed_at,
                    ),
                    recorded_at=observed_at,
                )
            )
        return tuple(events)

    def _predictions(
        self, account: SocketPaperAccount, account_id: str, observed_at: datetime
    ) -> tuple[MonitoringEvent, ...]:
        """Export each learned instance's newly committed prediction once."""
        events: list[MonitoringEvent] = []
        for name in self._instances(account_id):
            exporter = self.exporters[name]
            if exporter.loaded.estimator_version is None:
                continue
            result = account.execute(
                AccountExecutionRequest(
                    action="inspect",
                    account_id=account_id,
                    projection="checkpoint",
                    query_instance=name,
                )
            )
            if result.checkpoint is None:
                continue
            step = self._codec.decode_json(result.checkpoint, SharedCandidateCheckpoint).step
            if (
                step.status != "decided"
                or step.prediction is None
                or self._predicted.get(name, step.at - timedelta(microseconds=1)) >= step.at
            ):
                continue
            events.append(exporter.prediction(step, recorded_at=max(observed_at, step.at)))
            self._predicted[name] = step.at
        return tuple(events)

    def _delays(self, account_id: str, observed_at: datetime) -> tuple[MonitoringEvent, ...]:
        """Export the decision delay of every newly retained decided instant."""
        events: list[MonitoringEvent] = []
        for path in sorted(self.runs.glob(f"*/*-{account_id}.jsonl")):
            offset = self._offsets.get(path, 0)
            with path.open("rb") as stream:
                stream.seek(offset)
                payload = stream.read()
            complete = payload[: payload.rfind(b"\n") + 1]
            self._offsets[path] = offset + len(complete)
            for line in complete.splitlines():
                delivery = SharedBookDelivery.decode(line, self._codec)
                for group in delivery.decisions:
                    for item in group.inputs:
                        exporter = self.exporters.get(item.instance_id)
                        if exporter is None or self.accounts[item.instance_id] != account_id:
                            continue
                        events.append(
                            exporter.decision_delay(
                                group.at,
                                group.coordinated_at,
                                recorded_at=max(observed_at, group.coordinated_at),
                            )
                        )
        return tuple(events)

    def _dashboards(
        self, account_id: str, mode: Literal["paper", "shadow"], observed_at: datetime
    ) -> None:
        """Render the account's page and each candidate's pages, delivering breached bands.

        Superseded views are pruned only after every scope has rendered, so a pruning
        failure can never skip a candidate page or its alert delivery.
        """
        self._render(account_id, mode, observed_at, f"account:{account_id}", "account", ())
        for name in self._instances(account_id):
            exporter = self.exporters[name]
            self._render(account_id, mode, observed_at, exporter.scope, name, exporter.thresholds)
        self._prune(account_id, "account")
        for name in self._instances(account_id):
            self._prune(account_id, name)

    def _render(
        self,
        account_id: str,
        mode: Literal["paper", "shadow"],
        observed_at: datetime,
        scope: str,
        label: str,
        thresholds: tuple[MetricThreshold, ...],
    ) -> None:
        """Render one scope's pages, if it holds any displayable series."""
        store = TelemetryStore(self.root / "telemetry.sqlite3")
        # Queries select [start, end); the observation's own facts are at its clock.
        end = observed_at + timedelta(microseconds=1)
        query = MonitoringQuery(
            scope=scope,
            mode=mode,
            start=max(self.started_at, observed_at - self._dashboard_window),
            end=end,
            as_of=end,
            limit=100_000,
        )
        events = store.query(query)
        if not any(not item.name.startswith("execution.event.") for item in events):
            return
        configurations = MonitoringConfiguration.account(
            query,
            events,
            alert_socket=self.configuration.alert_socket,
            thresholds=thresholds,
        )
        stamp = observed_at.strftime("%Y%m%dT%H%M%S%fZ")
        alerts = OperationalAlerts(self.root / "alerts.sqlite3")
        for page, configuration in enumerate(configurations, start=1):
            registry = MetricRegistry(MonitoringDefinitions.resolve(configuration.metrics))
            selection = store.select(configuration.query)
            snapshot = DashboardBuilder.build(
                configuration.dashboard, configuration.query, selection, registry, alerts
            )
            snapshot.write(
                self.root / "dashboards" / account_id / f"{stamp}-{label}-{page}", selection
            )

    def _prune(self, account_id: str, label: str) -> None:
        """Keep each of the label's pages' newest view and its first view of each UTC hour.

        View names are ``<UTC stamp>-<label>-<page>``, so the stamp orders them and its
        first eleven characters name the hour. A removed view's directory is deleted
        under the same lock its writer takes; other files are never touched.
        """
        root = self.root / "dashboards" / account_id
        if not root.is_dir():
            return
        pages: dict[str, list[tuple[str, Path]]] = {}
        for path in root.iterdir():
            stamp, _, rest = path.name.partition("-")
            page = rest.removeprefix(f"{label}-")
            if path.name.startswith(".") or not path.is_dir() or page == rest:
                continue
            if page.isdigit():
                pages.setdefault(page, []).append((stamp, path))
        for views in pages.values():
            views.sort()
            kept = {views[-1][1]}
            hours: set[str] = set()
            for stamp, path in views:
                if stamp[:11] not in hours:
                    hours.add(stamp[:11])
                    kept.add(path)
            for _, path in views:
                if path in kept:
                    continue
                lock_path = path.with_name(f".{path.name}.lock")
                with lock_path.open("a+b") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    # Another pruner may have removed it while this one waited.
                    if path.is_dir():
                        shutil.rmtree(path)
                lock_path.unlink(missing_ok=True)

    @staticmethod
    def _market_order(market: PaperMarket) -> datetime:
        """Order observed markets by their clocks."""
        return market.at
