"""Retain exact monitoring dashboards and route explicitly configured local alerts."""

from __future__ import annotations

# standard library imports
import errno
import hashlib
import html
import os
import sqlite3
from collections import OrderedDict
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, WireRecord
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringQuery
from telemetry.metrics import MetricRegistry, MetricResult
from telemetry.operations import OperationalAlerts, OperationAlert

ChartKind = Literal["line", "bar", "table"]
AlertOperator = Literal[">", ">=", "<", "<=", "==", "!="]
UnavailablePolicy = Literal["trigger", "unavailable"]


class DashboardPanel(WireRecord, frozen=True):
    """Select one registered metric and its chart presentation by full identity."""

    title: str
    metric_identity: str
    kind: ChartKind

    def __post_init__(self) -> None:
        """Reject ambiguous or unbounded panel selections."""
        MonitoringIdentity.check_text(self.title)
        if (
            type(self.metric_identity) is not str
            or len(self.metric_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.metric_identity)
        ):
            raise ValueError("dashboard panel requires a metric SHA256 identity")
        if self.kind not in ("line", "bar", "table"):
            raise ValueError("unsupported dashboard panel kind")


class AlertRule(WireRecord, frozen=True):
    """Freeze an exact diagnostic threshold and explicit unavailable policies.

    A rule sends only to an explicitly configured local Unix datagram address.
    Its result is observational; it never changes a risk or stop control.
    """

    identity: str
    metric_identity: str
    operator: AlertOperator
    threshold: ExactRatio
    units: str
    address: str
    on_missing: UnavailablePolicy = "unavailable"
    on_stale: UnavailablePolicy = "unavailable"
    route: Literal["local_syslog"] = "local_syslog"

    def __post_init__(self) -> None:
        """Require exact units, a bounded route and clear missing/stale behavior."""
        MonitoringIdentity.check_text(self.identity)
        MonitoringIdentity.check_text(self.units)
        if (
            type(self.metric_identity) is not str
            or len(self.metric_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.metric_identity)
        ):
            raise ValueError("alert rule requires a metric SHA256 identity")
        if self.operator not in (">", ">=", "<", "<=", "==", "!="):
            raise ValueError("unsupported exact alert comparison")
        if type(self.threshold) is not ExactRatio:
            raise TypeError("alert threshold requires an exact ratio")
        self.threshold.__post_init__()
        if self.on_missing not in ("trigger", "unavailable") or self.on_stale not in (
            "trigger",
            "unavailable",
        ):
            raise ValueError("alert unavailability policy must be explicit")
        if (
            self.route != "local_syslog"
            or type(self.address) is not str
            or not self.address.startswith("/")
            or len(self.address.encode()) > 100
            or "\0" in self.address
            or any(ord(char) < 32 for char in self.address)
        ):
            raise ValueError("alert route requires a bounded local syslog socket")

    def delivery_identity(self, evidence_sha256: str) -> str:
        """Bind one delivery attempt to retained input, results and this full rule."""
        material = evidence_sha256.encode("ascii") + DomainCodec().encode_json(self)
        return f"monitor-{hashlib.sha256(material).hexdigest()}"


class DashboardConfig(WireRecord, frozen=True):
    """Select bounded dashboard panels and independently evaluated alert rules."""

    title: str
    panels: tuple[DashboardPanel, ...]
    alerts: tuple[AlertRule, ...] = ()
    schema_version: Literal["dashboard-config-v1"] = "dashboard-config-v1"

    def __post_init__(self) -> None:
        """Keep selections distinct and the persisted dashboard finite."""
        MonitoringIdentity.check_text(self.title)
        if type(self.panels) is not tuple or not 1 <= len(self.panels) <= 32:
            raise ValueError("dashboard requires one to 32 panels")
        if type(self.alerts) is not tuple or len(self.alerts) > 32:
            raise ValueError("dashboard permits at most 32 alert rules")
        for panel in self.panels:
            if type(panel) is not DashboardPanel:
                raise TypeError("dashboard panels must be typed")
            panel.__post_init__()
        for rule in self.alerts:
            if type(rule) is not AlertRule:
                raise TypeError("dashboard alert rules must be typed")
            rule.__post_init__()
        if len({panel.title for panel in self.panels}) != len(self.panels):
            raise ValueError("dashboard panel titles must be distinct")
        if len({rule.identity for rule in self.alerts}) != len(self.alerts):
            raise ValueError("dashboard alert rule identities must be distinct")
        if self.schema_version != "dashboard-config-v1":
            raise ValueError("unsupported dashboard configuration schema")

    @property
    def metric_identities(self) -> tuple[str, ...]:
        """Preserve first-use order across panels and alert-only metrics."""
        ordered: list[str] = []
        seen: set[str] = set()
        for identity in (
            *(panel.metric_identity for panel in self.panels),
            *(rule.metric_identity for rule in self.alerts),
        ):
            if identity not in seen:
                ordered.append(identity)
                seen.add(identity)
        return tuple(ordered)


class AlertEvaluation(WireRecord, frozen=True):
    """Retain threshold state separately from local delivery outcome."""

    rule: AlertRule
    state: Literal["triggered", "clear", "unavailable", "inapplicable"]
    observed: ExactRatio | None
    reason: str | None
    delivery: OperationAlert | None = None
    delivery_error: Literal["alert_persistence_failed"] | None = None

    def __post_init__(self) -> None:
        """Forbid an unavailable observation from appearing healthy."""
        if type(self.rule) is not AlertRule:
            raise TypeError("alert evaluation requires a typed rule")
        self.rule.__post_init__()
        if self.state not in ("triggered", "clear", "unavailable", "inapplicable"):
            raise ValueError("unsupported alert evaluation state")
        if self.observed is not None:
            if type(self.observed) is not ExactRatio or self.reason is not None:
                raise ValueError("observed alert values require exact ratios and no reason")
            self.observed.__post_init__()
        elif self.state == "clear" or self.reason is None:
            raise ValueError("unavailable alert observations require an explicit reason")
        else:
            MonitoringIdentity.check_text(self.reason)
        if self.state in ("unavailable", "inapplicable") and self.observed is not None:
            raise ValueError("unavailable alert cannot have an observed value")
        if self.delivery is not None:
            if (
                type(self.delivery) is not OperationAlert
                or self.state != "triggered"
                or self.delivery_error is not None
            ):
                raise ValueError("only triggered alerts can have delivery attempts")
            self.delivery.__post_init__()
            if self.delivery.address != self.rule.address:
                raise ValueError("alert delivery route differs from selected rule")
        if self.delivery_error is not None and (
            self.delivery_error != "alert_persistence_failed"
            or self.state != "triggered"
            or self.delivery is not None
        ):
            raise ValueError("invalid alert delivery failure state")

    @classmethod
    def assess(cls, rule: AlertRule, result: MetricResult) -> AlertEvaluation:
        """Compare exact values or apply the rule's named missing/stale policy."""
        rule.__post_init__()
        result.__post_init__()
        if rule.metric_identity != result.spec.identity or rule.units != result.spec.units:
            raise ValueError("alert metric identity or units differ from selected result")
        if result.status == "inapplicable":
            return cls(rule=rule, state="inapplicable", observed=None, reason=result.reason)
        if result.status in ("missing", "stale"):
            policy = rule.on_missing if result.status == "missing" else rule.on_stale
            state: Literal["triggered", "unavailable"] = (
                "triggered" if policy == "trigger" else "unavailable"
            )
            return cls(rule=rule, state=state, observed=None, reason=result.reason)
        if result.value is None:
            raise ValueError("successful metric has no exact value")
        observed = Fraction(int(result.value.numerator), int(result.value.denominator))
        threshold = Fraction(int(rule.threshold.numerator), int(rule.threshold.denominator))
        comparisons = {
            ">": observed > threshold,
            ">=": observed >= threshold,
            "<": observed < threshold,
            "<=": observed <= threshold,
            "==": observed == threshold,
            "!=": observed != threshold,
        }
        return cls(
            rule=rule,
            state="triggered" if comparisons[rule.operator] else "clear",
            observed=result.value,
            reason=None,
        )


class _DashboardEvidence(WireRecord, frozen=True):
    """Bind the complete evaluation input before delivery outcomes are known."""

    config: DashboardConfig
    query: MonitoringQuery
    events: tuple[MonitoringEvent, ...]
    results: tuple[MetricResult, ...]

    def __post_init__(self) -> None:
        """Reject substituted metric results, event revisions and query mismatches."""
        if type(self.config) is not DashboardConfig or type(self.query) is not MonitoringQuery:
            raise TypeError("dashboard requires typed config and query")
        self.config.__post_init__()
        self.query.__post_init__()
        if type(self.events) is not tuple or len(self.events) > self.query.limit:
            raise ValueError("dashboard requires bounded immutable input events")
        event_ids: set[str] = set()
        samples: set[tuple[str, str, str]] = set()
        previous: tuple[datetime, str, str] | None = None
        for event in self.events:
            if type(event) is not MonitoringEvent:
                raise TypeError("dashboard input events must be typed")
            event.__post_init__()
            if (
                (event.context.scope, event.context.mode) != (self.query.scope, self.query.mode)
                or not self.query.start <= event.at < self.query.end
                or event.available_at > self.query.as_of
                or event.recorded_at > self.query.as_of
            ):
                raise ValueError("dashboard event violates the selected query")
            order = event.at, event.name, event.sample
            key = event.name, event.version, event.sample
            identity = event.identity
            if (
                identity in event_ids
                or key in samples
                or (previous is not None and order < previous)
            ):
                raise ValueError("dashboard events require distinct ordered selected revisions")
            event_ids.add(identity)
            samples.add(key)
            previous = order
        if type(self.results) is not tuple or len(self.results) != len(
            self.config.metric_identities
        ):
            raise ValueError("dashboard results must match all metric selections")
        for metric_identity, result in zip(
            self.config.metric_identities, self.results, strict=True
        ):
            if type(result) is not MetricResult:
                raise TypeError("dashboard results must be typed")
            result.__post_init__()
            if result.spec.identity != metric_identity or result.query != self.query:
                raise ValueError("dashboard result replaced selected metric or query")
            if (result.status == "inapplicable") == (self.query.mode in result.spec.modes):
                raise ValueError("dashboard metric applicability differs from selected mode")
            if result.status == "inapplicable":
                expected: tuple[str, ...] = ()
            else:
                inputs = {item.name: item for item in result.spec.inputs}
                selected: list[str] = []
                for event in self.events:
                    item = inputs.get(event.name)
                    if item is None or event.version != item.version:
                        continue
                    if event.units != item.units:
                        raise ValueError("dashboard metric input units differ")
                    selected.append(event.identity)
                expected = tuple(selected)
            if result.input_ids != expected or any(
                item not in event_ids for item in result.input_ids
            ):
                raise ValueError("dashboard result input identities differ from retained events")

    @property
    def identity(self) -> str:
        """Hash selected input and exact outputs before any alert side effect."""
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class _DashboardManifest(WireRecord, frozen=True):
    """Verify retained JSON and HTML bytes independently of the live telemetry store."""

    json_sha256: str
    html_sha256: str
    schema_version: Literal["dashboard-manifest-v1"] = "dashboard-manifest-v1"

    def __post_init__(self) -> None:
        """Require complete content digests and a known manifest version."""
        for digest in (self.json_sha256, self.html_sha256):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("dashboard manifest requires SHA256 digests")
        if self.schema_version != "dashboard-manifest-v1":
            raise ValueError("unsupported dashboard manifest schema")


class DashboardSnapshot(WireRecord, frozen=True):
    """Retain enough bytes to reopen, verify and read an exact monitoring view."""

    config: DashboardConfig
    query: MonitoringQuery
    events: tuple[MonitoringEvent, ...]
    results: tuple[MetricResult, ...]
    alert_results: tuple[AlertEvaluation, ...] = ()
    schema_version: Literal["dashboard-snapshot-v1"] = "dashboard-snapshot-v1"

    def __post_init__(self) -> None:
        """Bind alert states and delivery attempts to the same selected evidence."""
        evidence = self._evidence()
        if type(self.alert_results) is not tuple or len(self.alert_results) != len(
            self.config.alerts
        ):
            raise ValueError("dashboard alert results must match selected rules")
        results = dict(zip(self.config.metric_identities, self.results, strict=True))
        for rule, evaluation in zip(self.config.alerts, self.alert_results, strict=True):
            if type(evaluation) is not AlertEvaluation:
                raise TypeError("dashboard alert results must be typed")
            evaluation.__post_init__()
            expected = AlertEvaluation.assess(rule, results[rule.metric_identity])
            if (evaluation.rule, evaluation.state, evaluation.observed, evaluation.reason) != (
                expected.rule,
                expected.state,
                expected.observed,
                expected.reason,
            ):
                raise ValueError("dashboard alert state differs from selected metric")
            if evaluation.delivery is not None and (
                evaluation.delivery.identity != rule.delivery_identity(evidence.identity)
                or evaluation.delivery.control_sha256 != evidence.identity
            ):
                raise ValueError("dashboard alert delivery differs from retained evidence")
        if self.schema_version != "dashboard-snapshot-v1":
            raise ValueError("unsupported dashboard snapshot schema")

    def _evidence(self) -> _DashboardEvidence:
        """Collect the immutable input and metric results used for alert identity."""
        return _DashboardEvidence(
            config=self.config, query=self.query, events=self.events, results=self.results
        )

    @property
    def identity(self) -> str:
        """Hash all retained bytes, including the final delivery outcomes."""
        DashboardSnapshot.__post_init__(self)
        return self._identity()

    def _identity(self) -> str:
        """Hash a snapshot after this invocation has validated all selected evidence."""
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def read(cls, directory: Path) -> DashboardSnapshot:
        """Reopen only digest-valid JSON whose HTML matches deterministic rendering."""
        codec = DomainCodec()
        manifest = codec.decode_json((directory / "manifest.json").read_bytes(), _DashboardManifest)
        manifest.__post_init__()
        json_bytes = (directory / "snapshot.json").read_bytes()
        html_bytes = (directory / "dashboard.html").read_bytes()
        if (
            hashlib.sha256(json_bytes).hexdigest() != manifest.json_sha256
            or hashlib.sha256(html_bytes).hexdigest() != manifest.html_sha256
        ):
            raise ValueError("retained dashboard content digest differs")
        snapshot = codec.decode_json(json_bytes, cls)
        snapshot.__post_init__()
        if snapshot.identity != manifest.json_sha256 or snapshot.render_html() != html_bytes:
            raise ValueError("retained dashboard differs from its selected evidence")
        return snapshot

    def write(self, directory: Path) -> Path:
        """Retain one complete JSON/HTML view; identical retries leave bytes untouched.

        The view is staged in a hidden sibling and published by one directory
        rename, so a process that dies mid-write leaves either no view or a whole
        one. A directory holding only an interrupted earlier write's files, with
        no manifest, is moved aside to a hidden ``.<name>.interrupted-*`` sibling
        rather than deleted. A directory holding other files is refused.

        Raises:
            ValueError: The directory holds a different view or unrelated files.
            OSError: Staging, synchronization or publication fails; retry safely.
        """
        DashboardSnapshot.__post_init__(self)
        codec = DomainCodec()
        json_bytes = codec.encode_json(self)
        html_bytes = self.render_html()
        manifest = _DashboardManifest(
            json_sha256=hashlib.sha256(json_bytes).hexdigest(),
            html_sha256=hashlib.sha256(html_bytes).hexdigest(),
        )
        if (directory / "manifest.json").exists():
            return self._verified(directory)
        if directory.is_dir() and any(directory.iterdir()):
            names = {path.name for path in directory.iterdir()}
            if not names <= {"snapshot.json", "dashboard.html"}:
                raise ValueError("dashboard directory holds unrelated files")
            os.rename(
                directory,
                directory.with_name(f".{directory.name}.interrupted-{os.urandom(8).hex()}"),
            )
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=directory.parent, prefix=f".{directory.name}.staging-") as root:
            staging = Path(root)
            for name, payload in (
                ("snapshot.json", json_bytes),
                ("dashboard.html", html_bytes),
                ("manifest.json", codec.encode_json(manifest)),
            ):
                with (staging / name).open("xb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
            self._sync_directory(staging)
            try:
                os.rename(staging, directory)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                # Another writer published first; its view must be this one.
                return self._verified(directory)
        self._sync_directory(directory.parent)
        return directory / "dashboard.html"

    def _verified(self, directory: Path) -> Path:
        """Accept an already published view only when it is this exact snapshot."""
        if self.read(directory) != self:
            raise ValueError("dashboard directory already contains different content")
        return directory / "dashboard.html"

    @staticmethod
    def _sync_directory(path: Path) -> None:
        """Make directory entries durable before reporting publication."""
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def render_html(self) -> bytes:
        """Render accessible, escaped charts and exact tables without external assets."""
        DashboardSnapshot.__post_init__(self)
        return self._render_validated_html()

    def _render_validated_html(
        self, renderer: DashboardRenderer | None = None, *, snapshot_identity: str | None = None
    ) -> bytes:
        """Render the complete snapshot already validated in this same owned invocation."""
        if snapshot_identity is None:
            snapshot_identity = self._identity()
        result_by_id = dict(zip(self.config.metric_identities, self.results, strict=True))
        escape = html.escape
        parts = [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            f"<title>{escape(self.config.title)} · Monitoring</title>",
            "<style>:root{color-scheme:light;--ink:#172432;--muted:#405468;"
            "--line:#aebdca;--surface:#f6f8fa;--accent:#17647a;--warn:#93422e;"
            "--ok:#1d654b}*{box-sizing:border-box}body{margin:0;background:#fff;"
            "color:var(--ink);font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"
            "Segoe UI,sans-serif}"
            "main{max-width:1140px;margin:auto;padding:2rem 1.5rem 5rem}h1{font-size:1.9rem;"
            "line-height:1.2;margin:.2rem 0 1rem}h2{font-size:1.25rem;margin:0 0 .6rem}"
            "h3{font-size:1rem;margin:0 0 .45rem}p{margin:.35rem 0 1rem}"
            "header{border-bottom:2px solid var(--ink);padding-bottom:1.2rem;margin-bottom:2rem}"
            ".meta{display:flex;flex-wrap:wrap;gap:.5rem 2rem;color:var(--muted)}"
            ".meta span{white-space:normal}.summary{display:flex;flex-wrap:wrap;gap:.4rem 1.5rem;"
            "margin:1rem 0}.summary strong{font-variant-numeric:tabular-nums}section.panel{"
            "border-top:1px solid var(--line);padding:1.5rem 0 1.8rem}.panel-head{display:flex;"
            "flex-wrap:wrap;justify-content:space-between;gap:.7rem 1rem;align-items:baseline}"
            ".state{font-weight:700}.state.ok,.state.clear{color:var(--ok)}"
            ".state.missing,.state.stale,.state.triggered,.state.failed{color:var(--warn)}"
            ".state.unavailable,.state.inapplicable{color:var(--muted)}"
            ".value{font-size:1.35rem;font-weight:650;font-variant-numeric:tabular-nums}"
            ".facts{display:flex;flex-wrap:wrap;gap:.25rem 1.2rem;color:var(--muted);"
            "font-size:.9rem;margin:.35rem 0 1rem}.facts span{overflow-wrap:anywhere}"
            ".chart{width:100%;height:auto;max-height:280px;background:var(--surface);"
            "border:1px solid var(--line)}.axis{stroke:var(--line);stroke-width:1}"
            ".series{fill:none;stroke:var(--accent);stroke-width:2.5;stroke-linecap:round;"
            "stroke-linejoin:round}.mark{fill:var(--accent)}.bar{fill:var(--accent)}"
            ".gap{stroke:var(--warn);stroke-width:2;stroke-dasharray:4 4}"
            ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;"
            "margin:.75rem 0 1rem}"
            "th,td{padding:.5rem .65rem;border-bottom:1px solid var(--line);text-align:left;"
            "vertical-align:top}th{background:var(--surface);font-weight:650}"
            "td{font-variant-numeric:tabular-nums}code{font:inherit;font-variant-numeric:tabular-nums;"
            "overflow-wrap:anywhere}small{color:var(--muted)}.empty{padding:1rem;background:var(--surface)}"
            "::selection{background:#b9dce4;color:var(--ink)}:focus-visible{"
            "outline:3px solid var(--accent);"
            "outline-offset:2px}@media(max-width:640px){main{padding:1rem .8rem 3rem}"
            "h1{font-size:1.5rem}th,td{padding:.4rem .45rem;font-size:.84rem}}"
            "</style></head><body><main>",
            f"<header><h1>{escape(self.config.title)}</h1>",
            '<div class="meta">',
            f"<span>Scope <code>{escape(self.query.scope)}</code> · "
            f"{escape(self.query.mode)}</span>",
            f"<span>Window <time>{escape(self.query.start.isoformat())}</time> to "
            f"<time>{escape(self.query.end.isoformat())}</time> (end exclusive)</span>",
            f"<span>Knowledge cutoff <time>{escape(self.query.as_of.isoformat())}</time></span>",
            "</div></header>",
            '<div class="summary" aria-label="Snapshot summary">',
            f"<span><strong>{len(self.config.panels)}</strong> panels</span>",
            f"<span><strong>{len(self.events)}</strong> retained events</span>",
            f"<span><strong>{len(self.config.alerts)}</strong> alert rules</span>",
            '</div><section aria-labelledby="panels-title"><h2 id="panels-title">'
            "Metric panels</h2>",
        ]
        for panel in self.config.panels:
            result = result_by_id[panel.metric_identity]
            parts.extend(self._panel_html(panel, result))
        parts.append(
            '</section><section aria-labelledby="alerts-title">'
            '<h2 id="alerts-title">Alert evaluation</h2>'
        )
        if not self.alert_results:
            parts.append('<p class="empty">No alert rules selected for this snapshot.</p>')
        else:
            parts.append(
                '<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Metric</th>'
                "<th>Threshold</th><th>State</th><th>Observation / reason</th>"
                "<th>Local delivery</th></tr></thead><tbody>"
            )
            for evaluation in self.alert_results:
                rule = evaluation.rule
                if evaluation.delivery_error is not None:
                    delivery = "alert persistence failed; delivery unknown"
                elif evaluation.delivery is not None:
                    delivery = evaluation.delivery.status
                elif evaluation.state == "triggered":
                    delivery = "not attempted (delivery not configured)"
                else:
                    delivery = "not needed"
                observed = (
                    self._exact(evaluation.observed)
                    if evaluation.observed is not None
                    else evaluation.reason or "unavailable"
                )
                cells = (
                    rule.identity,
                    result_by_id[rule.metric_identity].spec.name,
                    f"{rule.operator} {self._exact(rule.threshold)} {rule.units}; "
                    f"missing: {rule.on_missing}; stale: {rule.on_stale}",
                    evaluation.state,
                    observed,
                    f"{delivery} · {rule.route}: {rule.address}",
                )
                parts.append(self._row(cells))
            parts.append("</tbody></table></div>")
            parts.append(
                "<p><small>Missing and stale states follow each rule's configured policy; "
                "an inapplicable metric cannot be clear. "
                "Local delivery means socket acceptance only. "
                "These alerts do not operate risk controls.</small></p>"
            )
        parts.append(
            '</section><section aria-labelledby="source-title">'
            '<h2 id="source-title">Input provenance</h2>'
        )
        parts.append(
            f"<p>Snapshot SHA256 <code>{snapshot_identity}</code>. Event values and clocks "
            "below are the selected revisions used for this view.</p>"
        )
        if not self.events:
            parts.append('<p class="empty">No events were available at this cutoff.</p>')
        else:
            parts.append(
                '<div class="table-wrap"><table><thead><tr><th>Event</th><th>Sample / revision</th>'
                "<th>Event time</th><th>Available</th><th>Recorded</th><th>Value</th>"
                "<th>Context / clock / identity</th></tr></thead><tbody>"
            )
            for event in self.events:
                parts.append(
                    self._event_html(event) if renderer is None else renderer._event_html(event)
                )
            parts.append("</tbody></table></div>")
        parts.append("</section></main></body></html>")
        return "".join(parts).encode("utf-8")

    @classmethod
    def _event_html(cls, event: MonitoringEvent) -> str:
        """Format one event-only provenance row independently of query and dashboard selection."""
        return cls._row(
            (
                f"{event.name} · {event.version}",
                f"{event.sample} · r{event.revision}",
                event.at.isoformat(),
                event.available_at.isoformat(),
                event.recorded_at.isoformat(),
                f"{cls._exact(event.value)} {event.units}"
                if event.value is not None
                else f"gap: {event.missing_reason}",
                f"{cls._context(event.context)} · clock: {event.clock_quality} · {event.identity}",
            )
        )

    @classmethod
    def _panel_html(cls, panel: DashboardPanel, result: MetricResult) -> list[str]:
        """Show applicability, exact aggregate, visible chart gaps and source rows."""
        escape = html.escape
        spec = result.spec
        value = (
            cls._exact(result.value) if result.value is not None else result.reason or "unavailable"
        )
        parts = [
            f'<section class="panel"><div class="panel-head"><h3>{escape(panel.title)}</h3>'
            f'<span class="state {escape(result.status)}">{escape(result.status)}</span></div>',
            f'<p class="value">{escape(value)}'
            f" {escape(spec.units) if result.value is not None else ''}</p>",
            '<div class="facts">',
            f"<span>Metric {escape(spec.name)} · version {escape(spec.version)}</span>",
            f"<span>Aggregation {escape(spec.aggregation)} · "
            f"missingness {escape(spec.missingness)}</span>",
            f"<span>Applicable: {escape(', '.join(spec.modes))}</span>",
            f"<span>Freshness: {spec.stale_after_seconds} seconds</span>"
            if spec.stale_after_seconds is not None
            else "<span>Freshness: no configured budget</span>",
            f"<span>Definition SHA256 <code>{escape(panel.metric_identity)}</code></span>",
            f"<span>Implementation SHA256 <code>{escape(spec.implementation_sha256)}</code></span>",
            "</div>",
        ]
        if panel.kind != "table":
            parts.append(cls._chart_svg(panel, result))
        if not result.points:
            parts.append('<p class="empty">No plotted samples at this cutoff.</p>')
        else:
            parts.append(
                '<div class="table-wrap"><table><thead><tr><th>Sample</th><th>Event time</th>'
                "<th>Exact value</th><th>Units</th><th>Gap reason</th></tr></thead><tbody>"
            )
            for point in result.points:
                parts.append(
                    cls._row(
                        (
                            point.sample,
                            point.at.isoformat(),
                            cls._exact(point.value) if point.value is not None else "—",
                            spec.units,
                            point.missing_reason or "",
                        )
                    )
                )
            parts.append("</tbody></table></div>")
        parts.append("</section>")
        return parts

    @classmethod
    def _chart_svg(cls, panel: DashboardPanel, result: MetricResult) -> str:
        """Project exact points to a visual scale while splitting paths at gaps."""
        points = result.points
        if not points:
            return ""
        values = [
            Fraction(int(point.value.numerator), int(point.value.denominator))
            for point in points
            if point.value is not None
        ]
        if not values:
            return ""
        low, high = min([*values, Fraction(0)]), max([*values, Fraction(0)])
        start, end = points[0].at, points[-1].at
        duration = cls._microseconds(end - start)
        panel_sha256 = hashlib.sha256(DomainCodec().encode_json(panel)).hexdigest()
        title_id = f"chart-{panel_sha256[:16]}"
        parts = [
            f'<svg class="chart" viewBox="0 0 760 230" role="img" aria-labelledby="{title_id}">',
            f'<title id="{title_id}">{html.escape(panel.title)} · {panel.kind} chart; '
            "exact values and gap reasons follow in the table</title>",
            '<line class="axis" x1="48" y1="205" x2="732" y2="205"/>',
        ]
        baseline = cls._plot_y(Fraction(0), low, high)
        if panel.kind == "bar":
            width = min(38.0, 440.0 / len(points))
            for index, point in enumerate(points):
                x = cls._plot_x(point.at, start, duration, index, len(points))
                if point.value is None:
                    parts.append(cls._gap_marker(x, point.missing_reason or "gap"))
                    continue
                value = Fraction(int(point.value.numerator), int(point.value.denominator))
                y = cls._plot_y(value, low, high)
                top, height = min(y, baseline), max(abs(y - baseline), 1.5)
                label = html.escape(
                    f"{point.sample}: {cls._exact(point.value)} {result.spec.units}"
                )
                parts.append(
                    f'<rect class="bar" x="{x - width / 2:.2f}" y="{top:.2f}" '
                    f'width="{width:.2f}" height="{height:.2f}"><title>{label}</title></rect>'
                )
        else:
            run: list[str] = []
            for index, point in enumerate(points):
                x = cls._plot_x(point.at, start, duration, index, len(points))
                if point.value is None:
                    if len(run) > 1:
                        parts.append(f'<path class="series" d="{" ".join(run)}"/>')
                    run = []
                    parts.append(cls._gap_marker(x, point.missing_reason or "gap"))
                    continue
                value = Fraction(int(point.value.numerator), int(point.value.denominator))
                y = cls._plot_y(value, low, high)
                run.append(f"{'M' if not run else 'L'}{x:.2f},{y:.2f}")
                label = html.escape(
                    f"{point.sample}: {cls._exact(point.value)} {result.spec.units}"
                )
                parts.append(
                    f'<circle class="mark" cx="{x:.2f}" cy="{y:.2f}" r="3.4">'
                    f"<title>{label}</title></circle>"
                )
            if len(run) > 1:
                parts.append(f'<path class="series" d="{" ".join(run)}"/>')
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def _gap_marker(x: float, reason: str) -> str:
        """Mark an unavailable point without interpolating through it."""
        return (
            f'<line class="gap" x1="{x:.2f}" y1="24" x2="{x:.2f}" y2="205">'
            f"<title>Gap: {html.escape(reason)}</title></line>"
        )

    @staticmethod
    def _plot_y(value: Fraction, low: Fraction, high: Fraction) -> float:
        """Scale a rational into fixed SVG coordinates without large-float overflow."""
        return 114.0 if low == high else 22.0 + 174.0 * float((high - value) / (high - low))

    @classmethod
    def _plot_x(cls, at: datetime, start: datetime, duration: int, index: int, count: int) -> float:
        """Use event time, with stable spacing when all points share one clock."""
        if duration:
            return 48.0 + 684.0 * float(Fraction(cls._microseconds(at - start), duration))
        return 390.0 if count == 1 else 48.0 + 684.0 * index / (count - 1)

    @staticmethod
    def _microseconds(delta: timedelta) -> int:
        """Convert a nonnegative UTC clock delta to an exact integer offset."""
        return ((delta.days * 86_400 + delta.seconds) * 1_000_000) + delta.microseconds

    @staticmethod
    def _exact(value: ExactRatio | None) -> str:
        """Show a canonical rational without a floating-point approximation."""
        return "—" if value is None else f"{value.numerator}/{value.denominator}"

    @staticmethod
    def _context(identity: MonitoringIdentity) -> str:
        """Expose all populated fixed correlation fields in the provenance table."""
        fields = (
            ("release", identity.release),
            ("strategy", identity.strategy),
            ("model", identity.model),
            ("dataset", identity.dataset),
            ("source", identity.source),
            ("study", identity.study),
            ("account", identity.account),
            ("instrument", identity.instrument),
            ("venue", identity.venue),
            ("order", identity.order),
            ("fill", identity.fill),
            ("state epoch", identity.state_epoch),
            ("incident", identity.incident),
        )
        return ", ".join(f"{name}: {value}" for name, value in fields if value is not None)

    @staticmethod
    def _row(values: tuple[str, ...]) -> str:
        """Escape every data-bearing cell at the HTML boundary."""
        return "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>"


class DashboardRenderer:
    """Build fresh validated snapshots while reusing at most 10,000 exact event-only rows.

    This renderer owns the row cache for its lifetime. Every call rebuilds query
    cutoffs, metrics, freshness, alerts, header and snapshot identity. Only complete
    serialized event bytes can reuse provenance text; revisions and late arrivals
    still enter through the current query. No complete dashboard is cached.
    """

    def __init__(self, config: DashboardConfig, registry: MetricRegistry) -> None:
        """Bind explicit metric selection and a finite per-renderer provenance cache."""
        config.__post_init__()
        self.config, self.registry = config, registry
        self.codec = DomainCodec()
        self._event_rows: OrderedDict[bytes, str] = OrderedDict()

    def render(
        self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]
    ) -> tuple[bytes, str]:
        """Build and render one private validated snapshot before exposing any output.

        Returns:
            Complete HTML bytes and the identity of the same immutable snapshot.
        """
        snapshot = DashboardBuilder.build(self.config, query, events, self.registry)
        identity = snapshot._identity()
        return snapshot._render_validated_html(self, snapshot_identity=identity), identity

    def _event_html(self, event: MonitoringEvent) -> str:
        """Reuse event-only text after this invocation's complete snapshot validation."""
        payload = self.codec.encode_json(event)
        row = self._event_rows.get(payload)
        if row is None:
            row = DashboardSnapshot._event_html(event)
            self._event_rows[payload] = row
            if len(self._event_rows) > 10_000:
                self._event_rows.popitem(last=False)
        else:
            self._event_rows.move_to_end(payload)
        return row


class DashboardBuilder:
    """Evaluate injected metric definitions and optional local delivery once."""

    @staticmethod
    def build(
        config: DashboardConfig,
        query: MonitoringQuery,
        events: tuple[MonitoringEvent, ...],
        registry: MetricRegistry,
        alerts: OperationalAlerts | None = None,
    ) -> DashboardSnapshot:
        """Build an immutable view whose alerts cannot invoke hard controls."""
        config.__post_init__()
        query.__post_init__()
        if type(events) is not tuple:
            raise TypeError("dashboard events must be an immutable tuple")
        selected = tuple(sorted(events, key=DashboardBuilder._event_order))
        results = registry.evaluate_many(config.metric_identities, query, selected)
        evidence = (
            _DashboardEvidence(config=config, query=query, events=selected, results=results)
            if alerts is not None
            else None
        )
        result_by_id = dict(zip(config.metric_identities, results, strict=True))
        assessments = tuple(
            AlertEvaluation.assess(rule, result_by_id[rule.metric_identity])
            for rule in config.alerts
        )
        evaluations: list[AlertEvaluation] = []
        for assessment in assessments:
            rule = assessment.rule
            if assessment.state == "triggered" and alerts is not None:
                if evidence is None:
                    raise RuntimeError("alert delivery requires validated dashboard evidence")
                try:
                    delivery = alerts.send(
                        identity=rule.delivery_identity(evidence.identity),
                        control_sha256=evidence.identity,
                        address=rule.address,
                    )
                except OSError, sqlite3.Error:
                    assessment = AlertEvaluation(
                        rule=rule,
                        state=assessment.state,
                        observed=assessment.observed,
                        reason=assessment.reason,
                        delivery_error="alert_persistence_failed",
                    )
                else:
                    assessment = AlertEvaluation(
                        rule=rule,
                        state=assessment.state,
                        observed=assessment.observed,
                        reason=assessment.reason,
                        delivery=delivery,
                    )
            evaluations.append(assessment)
        return DashboardSnapshot(
            config=config,
            query=query,
            events=selected,
            results=results,
            alert_results=tuple(evaluations),
        )

    @staticmethod
    def _event_order(event: MonitoringEvent) -> tuple[datetime, str, str]:
        """Keep retained input ordering identical to registry evaluation ordering."""
        return event.at, event.name, event.sample
