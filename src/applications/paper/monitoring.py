"""Retain and reopen public-paper diagnostics independently of account execution."""

from __future__ import annotations

# standard library imports
import hashlib
import html
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from accounting import PaperAccountReport
from execution import PaperAccount, PaperMonitoring, PortfolioCommit
from financial_units import ExactRatio
from market_data.contracts import CaptureRequest
from runtime import SharedBookDelivery
from serialization import DomainCodec, WireRecord
from telemetry import (
    DashboardBuilder,
    DashboardSnapshot,
    HealthRecorder,
    HealthRecorderState,
    MetricRegistry,
    MonitoringConfiguration,
    MonitoringDefinitions,
    MonitoringEvent,
    MonitoringIdentity,
    MonitoringQuery,
    OperationalAlerts,
    TelemetryStore,
)


class PaperSourceClock(WireRecord, frozen=True):
    """Preserve native source text and precision without inferring source clock accuracy."""

    position: int
    source_time: str | None
    received_ns: int
    available_at: datetime


class PaperMonitoringInput(WireRecord, frozen=True):
    """Freeze actual received facts and their retrievable paper evidence identities."""

    events: tuple[MonitoringEvent, ...]
    source_clocks: tuple[PaperSourceClock, ...]
    artifacts: tuple[tuple[str, str], ...]
    schema_version: str = "paper-monitoring-input-v1"

    def __post_init__(self) -> None:
        """Reject incompatible or unbounded input envelopes and invalid facts."""
        if (
            self.schema_version != "paper-monitoring-input-v1"
            or not 1 <= len(self.events) <= 100_000
        ):
            raise ValueError("paper monitoring requires bounded versioned facts")
        for event in self.events:
            event.__post_init__()
        for clock in self.source_clocks:
            self._require_utc(clock.available_at, field_name="source availability")
            if clock.position < 0 or clock.received_ns <= 0:
                raise ValueError("invalid retained source clocks")
        if len(set(name for name, _ in self.artifacts)) != len(self.artifacts):
            raise ValueError("duplicate paper evidence artifact")
        for name, digest in self.artifacts:
            if (
                Path(name).name != name
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ValueError("paper evidence requires local names and SHA256 identities")

    @classmethod
    def retain(
        cls,
        root: Path,
        events: tuple[MonitoringEvent, ...],
        *,
        source_clocks: tuple[PaperSourceClock, ...],
    ) -> Path:
        """Write one immutable receipt envelope after economic result artifacts exist."""
        names = (
            "manifest.json",
            "paper-result.json",
            "execution-traces.json",
            "cost-report.json",
            "deliveries.jsonl",
        )
        value = cls(
            events=events,
            source_clocks=source_clocks,
            artifacts=tuple(
                (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                for name in names
                if (root / name).is_file()
            ),
        )
        path = root / "monitoring-input.json"
        with path.open("xb") as stream:
            stream.write(DomainCodec().encode_json(value))
        return path

    @classmethod
    def read(cls, path: Path) -> PaperMonitoringInput:
        """Verify input and original committed evidence before re-ingesting saved receipts."""
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("paper monitoring input exceeds 128 MiB")
        value = DomainCodec().decode_json(path.read_bytes(), cls)
        value.__post_init__()
        for name, digest in value.artifacts:
            if hashlib.sha256((path.parent / name).read_bytes()).hexdigest() != digest:
                raise ValueError("paper monitoring evidence bytes changed")
        return value


class PaperMonitoringResult(WireRecord, frozen=True):
    """Expose diagnostic failures without making them execution failures."""

    dashboards: tuple[str, ...] = ()
    inserted: int = 0
    dropped: int = 0
    failures: int = 0
    pending: int = 0
    worker_alive: bool = False
    errors: tuple[str, ...] = ()


class PaperSourceMonitoring:
    """Project actual local delivery and callback observations without exchange-latency claims."""

    @staticmethod
    def project(
        *,
        root: Path,
        context: MonitoringIdentity,
        observed_at: datetime,
        summary: dict[str, object],
        processing_ns: int | None,
        delivered_count: int,
        faulted: bool = False,
    ) -> tuple[tuple[MonitoringEvent, ...], tuple[PaperSourceClock, ...]]:
        """Keep source clocks verbatim and label unavailable measurements explicitly.

        Processing duration is the last actual monotonic match/decision callback
        duration. It excludes feed transport and persistence. Source drift and
        receipt-to-durable latency are not inferred from different UTC clocks.
        """
        codec = DomainCodec()
        clocks: list[PaperSourceClock] = []
        path = root / "deliveries.jsonl"
        for line in path.read_bytes().splitlines() if path.is_file() else ():
            delivery = codec.decode_json(line, SharedBookDelivery)
            clocks.append(
                PaperSourceClock(
                    position=delivery.source.book.position,
                    source_time=delivery.source.book.source_time,
                    received_ns=delivery.source.record.received_ns,
                    available_at=delivery.source.available_at,
                )
            )
        signals: list[tuple[str, str, Fraction | None, str | None]] = [
            (
                "runtime.processing_seconds",
                "seconds",
                None if processing_ns is None else Fraction(processing_ns, 1_000_000_000),
                "not_measured" if processing_ns is None else None,
            ),
            ("runtime.delivered_records", "count", Fraction(delivered_count), None),
            ("runtime.stopped", "boolean", Fraction(1), None),
            ("runtime.faulted", "boolean", Fraction(faulted), None),
            ("data.source_clock_drift_seconds", "seconds", None, "not_measured"),
            ("data.receipt_to_durable_seconds", "seconds", None, "not_measured"),
        ]
        synchronized = summary.get("synchronized")
        signals.append(
            (
                "data.unavailable",
                "boolean",
                Fraction(not synchronized) if type(synchronized) is bool else None,
                None if type(synchronized) is bool else "not_measured",
            )
        )
        gaps = summary.get("gaps")
        signals.append(
            (
                "data.gaps",
                "count",
                None
                if gaps is None
                else Fraction(len(msgspec.convert(gaps, type=tuple[object, ...], strict=True))),
                "not_measured" if gaps is None else None,
            )
        )
        for key in ("frames", "updates", "snapshots", "epochs", "duplicates"):
            value = summary.get(key)
            signals.append(
                (
                    f"data.{key}",
                    "count",
                    Fraction(value) if type(value) is int else None,
                    None if type(value) is int else "not_measured",
                )
            )
        sample = hashlib.sha256(codec.encode_json((context, observed_at, summary))).hexdigest()
        return tuple(
            MonitoringEvent(
                context=context,
                name=name,
                version="1",
                sample=sample,
                at=observed_at,
                available_at=observed_at,
                recorded_at=observed_at,
                units=units,
                value=None if value is None else ExactRatio.from_fraction(value),
                missing_reason=reason,
            )
            for name, units, value, reason in signals
        ), tuple(clocks)


def render_paper_monitoring(
    input_path: Path,
    *,
    journal_path: Path,
    output: Path,
    alert_socket: str | None = None,
) -> PaperMonitoringResult:
    """Recover or render diagnostics using saved receipt bytes, never account operations.

    Use an absent output directory for each render. Reusing the telemetry journal
    is idempotent. All journal, routing and rendering failures are returned and,
    where output storage works, retained in monitoring-status.json. Configured
    alerts mean local datagram delivery only, never human acknowledgement.
    """
    errors: list[str] = []
    dashboards: list[str] = []
    links: list[str] = []
    state = HealthRecorderState(0, 0, 0, 0, False, None)
    recorder: HealthRecorder | None = None
    try:
        value = PaperMonitoringInput.read(input_path)
        output.mkdir(parents=True, exist_ok=False)
        recorder = HealthRecorder(journal_path, max_batches=64)
        recorder.start()
        for offset in range(0, len(value.events), 64):
            recorder.offer(value.events[offset : offset + 64])
        state = recorder.close(wait_seconds=1)
        if state.error is not None:
            errors.append(f"telemetry:{state.error}")
        if state.dropped or state.pending or state.worker_alive:
            errors.append("telemetry:incomplete_ingestion")
        if state.dropped or state.pending or state.worker_alive or state.failures:
            raise ValueError(
                "monitoring ingestion is incomplete; replay retained input before rendering"
            )
        store = TelemetryStore(journal_path)
        receipt_cutoff = max(event.recorded_at for event in value.events)
        end = max(event.at for event in value.events) + timedelta(microseconds=1)
        as_of = max(receipt_cutoff, end)
        alerts = (
            None
            if alert_socket is None
            else OperationalAlerts(journal_path.with_suffix(".alerts.sqlite3"))
        )
        for scope in sorted({event.context.scope for event in value.events}):
            query = MonitoringQuery(
                scope=scope,
                mode="paper",
                start=min(event.at for event in value.events),
                end=end,
                as_of=as_of,
                limit=100_000,
            )
            events = store.query(query)
            configs = MonitoringConfiguration.paper(query, value.events, alert_socket=alert_socket)
            for page, config in enumerate(configs):
                name = f"{hashlib.sha256(scope.encode()).hexdigest()[:16]}-{page + 1}"
                (output / f"{name}.json").write_bytes(DomainCodec().encode_json(config))
                snapshot = DashboardBuilder.build(
                    config.dashboard,
                    query,
                    events,
                    MetricRegistry(MonitoringDefinitions.resolve(config.metrics)),
                    alerts,
                )
                snapshot.write(output / name)
                DashboardSnapshot.read(output / name)
                dashboards.append(name)
                links.append(
                    f'<li><a href="{name}/dashboard.html">'
                    f"{html.escape(config.dashboard.title)}</a></li>"
                )
                if any(
                    item.delivery_error
                    or (item.delivery is not None and item.delivery.status != "delivered")
                    for item in snapshot.alert_results
                ):
                    errors.append(f"alert:{name}:delivery_unconfirmed")
        input_href = html.escape(
            input_path.resolve().relative_to(output.resolve(), walk_up=True).as_posix()
        )
        report_path = input_path.parent / "cost-report.json"
        report_note = "Cost report unavailable for this invocation."
        if report_path.is_file():
            report_href = html.escape(
                report_path.resolve().relative_to(output.resolve(), walk_up=True).as_posix()
            )
            report_note = (
                "Off-chain gas applicability and its reason are retained in the "
                f'<a href="{report_href}">cost report</a>.'
            )
        (output / "index.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Public paper monitoring</title><style>"
            "body{font:17px system-ui;max-width:70rem;margin:3rem auto;padding:0 2rem;"
            "background:#f8fafc;color:#162234}li{margin:1rem 0}a{color:#124f86}</style>"
            "<h1>Public paper monitoring</h1><p>Retained observations from committed "
            "paper facts. Each account and strategy keeps separate exact currency series.</p>"
            "<p>Valuation: last eligible bid. Gross P&amp;L is before modeled fees, rebates "
            "and slippage; net P&amp;L includes costs once. " + report_note + "</p>"
            "<ul>" + "".join(links) + "</ul>"
            "<p>Processing delay measures the local match/decision callback. Source clock "
            "drift and receipt-to-durable delay are not measured by this invocation. "
            "Configured alerts record socket delivery; "
            "human acknowledgement is not established.</p>"
            '<p><a href="monitoring-status.json">Ingestion and delivery status</a> · '
            f'<a href="{input_href}">Received inputs and source clocks</a></p></html>',
            encoding="utf-8",
        )
    except Exception as error:
        # This task boundary deliberately cannot retry or alter a committed account.
        errors.append(f"monitoring:{type(error).__name__}")
    finally:
        if recorder is not None:
            state = recorder.close(wait_seconds=0)
    result = PaperMonitoringResult(
        dashboards=tuple(dashboards),
        inserted=state.inserted,
        dropped=state.dropped,
        failures=state.failures,
        pending=state.pending,
        worker_alive=state.worker_alive,
        errors=tuple(errors),
    )
    try:
        (output / "monitoring-status.json").write_bytes(DomainCodec().encode_json(result))
    except OSError as error:
        return PaperMonitoringResult(
            dashboards=result.dashboards,
            inserted=result.inserted,
            dropped=result.dropped,
            failures=result.failures,
            pending=result.pending,
            worker_alive=result.worker_alive,
            errors=(*result.errors, f"status:{type(error).__name__}"),
        )
    return result


def retain_public_paper_monitoring(
    journal: PaperAccount,
    *,
    account_id: str,
    request: CaptureRequest,
    root: Path,
    observed_at: datetime,
    report: PaperAccountReport | None,
    decisions: tuple[PortfolioCommit, ...],
    prior_trace_ids: frozenset[str],
    summary: dict[str, object],
    processing_ns: int | None,
    delivered_count: int,
    alert_socket: str | None,
    faulted: bool = False,
) -> PaperMonitoringResult:
    """Observe committed facts once, preserving failures outside the execution handler."""
    try:
        projector = PaperMonitoring(release=request.implementation_identity)
        events = projector.account(
            journal,
            account_id=account_id,
            observed_at=observed_at,
            sample=request.identity,
            report=report,
            source=request.identity,
            venue=request.config.venue,
            decisions=decisions,
        )
        for trace in journal.paper_traces(account_id):
            if trace.input_sha256 in prior_trace_ids:
                continue
            events += projector.trace(
                trace,
                observed_at=observed_at,
                source=request.identity,
                venue=request.config.venue,
                children=tuple(
                    child for child in journal.orders() if child.account_id == account_id
                ),
            )
        source_events, clocks = PaperSourceMonitoring.project(
            root=root,
            context=MonitoringIdentity(
                scope=f"account:{account_id}",
                mode="paper",
                account=account_id,
                venue=request.config.venue,
                source=request.identity,
                release=request.implementation_identity,
            ),
            observed_at=observed_at,
            summary=summary,
            processing_ns=processing_ns,
            delivered_count=delivered_count,
            faulted=faulted,
        )
        path = PaperMonitoringInput.retain(root, events + source_events, source_clocks=clocks)
        return render_paper_monitoring(
            path,
            journal_path=root / "monitor.sqlite3",
            output=root / "monitoring",
            alert_socket=alert_socket,
        )
    except Exception as error:
        result = PaperMonitoringResult(errors=(f"projection:{type(error).__name__}",))
        try:
            (root / "monitoring-error.json").write_bytes(DomainCodec().encode_json(result))
        except OSError:
            pass  # The returned error remains visible when even diagnostic storage is unavailable.
        return result
