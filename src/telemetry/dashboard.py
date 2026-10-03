"""Retain exact monitoring dashboards and route explicitly configured local alerts."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import html
import os
import re
import shutil
import sqlite3
import stat
from collections import OrderedDict
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, DurableDirectory, WireRecord
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringQuery
from telemetry.metrics import (
    MetricPoint,
    MetricRegistry,
    MetricSpec,
    SeriesMetric,
)
from telemetry.operations import OperationalAlerts, OperationAlert
from telemetry.store import ProvenanceCursor, TelemetryRow, TelemetrySelection

ChartKind = Literal["line", "bar", "table"]
# A panel retains its most recent points; the snapshot counts and digests every input.
POINT_LIMIT = 120
_SHA256_TEXT = re.compile(r"[0-9a-f]{64}")
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
    schema_version: Literal["dashboard-config"] = "dashboard-config"

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
        if self.schema_version != "dashboard-config":
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


class PanelResult(WireRecord, frozen=True):
    """Retain one metric's exact outcome, its input count and digest, and its last points.

    ``inputs_sha256`` hashes the SHA256 digests of the definition's selected input
    payloads in query order, which are their monitoring event identities.
    ``points`` holds at most ``POINT_LIMIT`` of the ``point_count`` points, the last.
    """

    spec: MetricSpec
    value: ExactRatio | None
    status: Literal["ok", "missing", "stale", "inapplicable"]
    reason: str | None
    input_count: int
    inputs_sha256: str
    point_count: int
    points: tuple[MetricPoint, ...] = ()
    schema_version: Literal["panel-result"] = "panel-result"

    def __post_init__(self) -> None:
        """Reject incompatible output, ambiguous missingness and unbounded points."""
        if type(self.spec) is not MetricSpec:
            raise TypeError("panel result requires a typed definition")
        self.spec.__post_init__()
        if self.status not in ("ok", "missing", "stale", "inapplicable"):
            raise ValueError("invalid metric status")
        if self.status == "ok":
            if type(self.value) is not ExactRatio or self.reason is not None:
                raise ValueError("successful metric requires exact value")
            self.value.__post_init__()
        elif self.value is not None or self.reason is None:
            raise ValueError("unavailable metric requires reason and no value")
        else:
            MonitoringIdentity.check_text(self.reason)
        if (
            type(self.input_count) is not int
            or not 0 <= self.input_count <= 100_000
            or type(self.point_count) is not int
            or not 0 <= self.point_count <= 100_000
            or type(self.inputs_sha256) is not str
            or _SHA256_TEXT.fullmatch(self.inputs_sha256) is None
        ):
            raise ValueError("panel input count, point count and digest must be bounded")
        if type(self.points) is not tuple or len(self.points) != min(self.point_count, POINT_LIMIT):
            raise ValueError("panel retains exactly its last bounded points")
        if self.status == "inapplicable" and (self.input_count or self.point_count):
            raise ValueError("an inapplicable metric has no inputs or points")
        seen: set[str] = set()
        previous: datetime | None = None
        for point in self.points:
            if type(point) is not MetricPoint:
                raise TypeError("metric points must be typed")
            point.__post_init__()
            if point.sample in seen or (previous is not None and point.at < previous):
                raise ValueError("metric points must be distinct and ordered")
            seen.add(point.sample)
            previous = point.at
        if self.schema_version != "panel-result":
            raise ValueError("unsupported panel result schema")


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
    def assess(cls, rule: AlertRule, result: PanelResult) -> AlertEvaluation:
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
    event_count: int
    events_sha256: str
    results: tuple[PanelResult, ...]

    def __post_init__(self) -> None:
        """Reject substituted metric results, unbounded inputs and query mismatches."""
        if type(self.config) is not DashboardConfig or type(self.query) is not MonitoringQuery:
            raise TypeError("dashboard requires typed config and query")
        self.config.__post_init__()
        self.query.__post_init__()
        if (
            type(self.event_count) is not int
            or not 0 <= self.event_count <= self.query.limit
            or type(self.events_sha256) is not str
            or _SHA256_TEXT.fullmatch(self.events_sha256) is None
        ):
            raise ValueError("dashboard requires a bounded counted and digested selection")
        if type(self.results) is not tuple or len(self.results) != len(
            self.config.metric_identities
        ):
            raise ValueError("dashboard results must match all metric selections")
        for metric_identity, result in zip(
            self.config.metric_identities, self.results, strict=True
        ):
            if type(result) is not PanelResult:
                raise TypeError("dashboard results must be typed")
            result.__post_init__()
            if result.spec.identity != metric_identity:
                raise ValueError("dashboard result replaced selected metric")
            if (result.status == "inapplicable") == (self.query.mode in result.spec.modes):
                raise ValueError("dashboard metric applicability differs from selected mode")
            if result.input_count > self.event_count or any(
                not self.query.start <= point.at < self.query.end for point in result.points
            ):
                raise ValueError("dashboard result exceeds its selected query")

    @property
    def identity(self) -> str:
        """Hash selected input and exact outputs before any alert side effect."""
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class _DashboardManifest(WireRecord, frozen=True):
    """Verify retained JSON, HTML and provenance bytes independently of the live store."""

    json_sha256: str
    html_sha256: str
    provenance_sha256: str
    schema_version: Literal["dashboard-manifest"] = "dashboard-manifest"

    def __post_init__(self) -> None:
        """Require complete content digests and a known manifest version."""
        for digest in (self.json_sha256, self.html_sha256, self.provenance_sha256):
            if type(digest) is not str or _SHA256_TEXT.fullmatch(digest) is None:
                raise ValueError("dashboard manifest requires SHA256 digests")
        if self.schema_version != "dashboard-manifest":
            raise ValueError("unsupported dashboard manifest schema")


class DashboardSnapshot(WireRecord, frozen=True):
    """Retain a bounded, exact monitoring view over a counted and digested selection.

    The view holds every selected metric's exact outcome and its last points, not
    the selected events. ``events_sha256`` hashes the SHA256 digests of every
    selected payload in query order. A retained view keeps those payloads beside it;
    a live reader pages them with ``TelemetryStore.page``.
    """

    config: DashboardConfig
    query: MonitoringQuery
    event_count: int
    events_sha256: str
    results: tuple[PanelResult, ...]
    alert_results: tuple[AlertEvaluation, ...] = ()
    schema_version: Literal["dashboard-view"] = "dashboard-view"

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
        if self.schema_version != "dashboard-view":
            raise ValueError("unsupported dashboard snapshot schema")

    def _evidence(self) -> _DashboardEvidence:
        """Collect the immutable input and metric results used for alert identity."""
        return _DashboardEvidence(
            config=self.config,
            query=self.query,
            event_count=self.event_count,
            events_sha256=self.events_sha256,
            results=self.results,
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
        """Reopen only digest-valid JSON, matching HTML and the complete selected payloads."""
        codec = DomainCodec()
        manifest = codec.decode_json((directory / "manifest.json").read_bytes(), _DashboardManifest)
        manifest.__post_init__()
        json_bytes = (directory / "snapshot.json").read_bytes()
        html_bytes = (directory / "dashboard.html").read_bytes()
        provenance = (directory / "provenance.jsonl").read_bytes()
        if (
            hashlib.sha256(json_bytes).hexdigest() != manifest.json_sha256
            or hashlib.sha256(html_bytes).hexdigest() != manifest.html_sha256
            or hashlib.sha256(provenance).hexdigest() != manifest.provenance_sha256
        ):
            raise ValueError("retained dashboard content digest differs")
        snapshot = codec.decode_json(json_bytes, cls)
        snapshot.__post_init__()
        if snapshot.identity != manifest.json_sha256 or snapshot.render_html() != html_bytes:
            raise ValueError("retained dashboard differs from its selected evidence")
        payloads = tuple(provenance.splitlines()) if provenance else ()
        if provenance and not provenance.endswith(b"\n"):
            raise ValueError("retained dashboard provenance is incomplete")
        DashboardViewSelection.admit_all(snapshot.query, payloads, codec)
        if (len(payloads), DashboardViewSelection.digest(payloads)) != (
            snapshot.event_count,
            snapshot.events_sha256,
        ):
            raise ValueError("retained dashboard provenance differs from its selection")
        return snapshot

    def write(
        self, directory: Path, inputs: tuple[MonitoringEvent, ...] | TelemetrySelection
    ) -> Path:
        """Retain one complete view and its selected payloads; identical retries are no-ops.

        ``inputs`` must be the selection this view was built from. The view is staged
        in a hidden sibling and published by one directory rename, so a process that
        dies mid-write leaves either no view or a whole one. A directory holding only
        an interrupted earlier write's files, with no manifest, is moved aside to a
        hidden ``.<name>.interrupted-*`` sibling rather than deleted. A directory
        holding other files is refused. Writers of one directory take turns on an OS
        lock on the hidden ``.<name>.lock`` sibling, so each sees a published view
        whole and only verifies it.

        Raises:
            ValueError: The inputs differ from the view's selection, or the
                directory holds a different view or unrelated files.
            OSError: Staging, synchronization or publication fails; retry safely.
        """
        DashboardSnapshot.__post_init__(self)
        codec = DomainCodec()
        selection = DashboardViewSelection.of(self.query, inputs, codec)
        if (len(selection.rows), selection.digest_all()) != (
            self.event_count,
            self.events_sha256,
        ):
            raise ValueError("dashboard provenance differs from the view's selection")
        json_bytes = codec.encode_json(self)
        html_bytes = self.render_html()
        provenance = b"".join(row.payload + b"\n" for row in selection.rows)
        manifest = _DashboardManifest(
            json_sha256=hashlib.sha256(json_bytes).hexdigest(),
            html_sha256=hashlib.sha256(html_bytes).hexdigest(),
            provenance_sha256=hashlib.sha256(provenance).hexdigest(),
        )
        directory.parent.mkdir(parents=True, exist_ok=True)
        with directory.with_name(f".{directory.name}.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            return self._publish(
                directory,
                (
                    ("snapshot.json", json_bytes),
                    ("dashboard.html", html_bytes),
                    ("provenance.jsonl", provenance),
                    ("manifest.json", codec.encode_json(manifest)),
                ),
            )

    def _publish(self, directory: Path, files: tuple[tuple[str, bytes], ...]) -> Path:
        """Verify, move aside or publish the view while holding the directory's lock."""
        if (directory / "manifest.json").exists():
            return self._verified(directory)
        if directory.is_dir() and any(directory.iterdir()):
            names = {path.name for path in directory.iterdir()}
            if not names <= {"snapshot.json", "dashboard.html", "provenance.jsonl"}:
                raise ValueError("dashboard directory holds unrelated files")
            os.rename(
                directory,
                directory.with_name(f".{directory.name}.interrupted-{os.urandom(8).hex()}"),
            )
        # A plain mkdir, not a 0700 temporary directory: the published view gets
        # the umask's mode like any directory, so other users can serve it.
        staging = directory.with_name(f".{directory.name}.staging-{os.urandom(8).hex()}")
        staging.mkdir()
        try:
            if directory.is_dir():
                # A provisioned (empty) destination keeps its permission bits.
                staging.chmod(stat.S_IMODE(directory.stat().st_mode))
            for name, payload in files:
                with (staging / name).open("xb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
            if not DurableDirectory.publish(staging, directory):
                # A publisher outside this lock went first; its view must be this one.
                return self._verified(directory)
        finally:
            if staging.is_dir():
                shutil.rmtree(staging)
        return directory / "dashboard.html"

    def _verified(self, directory: Path) -> Path:
        """Accept an already published view only when it is this exact snapshot."""
        if self.read(directory) != self:
            raise ValueError("dashboard directory already contains different content")
        return directory / "dashboard.html"

    def render_html(self) -> bytes:
        """Render accessible, escaped charts and exact tables without external assets."""
        DashboardSnapshot.__post_init__(self)
        return self._render_validated_html()

    def _render_validated_html(self, *, snapshot_identity: str | None = None) -> bytes:
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
            f"<span><strong>{self.event_count}</strong> selected events</span>",
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
            f"<p>Snapshot SHA256 <code>{snapshot_identity}</code>. The view counts "
            f"<strong>{self.event_count}</strong> selected events; the SHA256 of their "
            f"payload digests in query order is <code>{self.events_sha256}</code>. "
            "A retained view keeps those payloads in <code>provenance.jsonl</code>; "
            "a live reader pages them from the telemetry store.</p>"
        )
        parts.append("</section></main></body></html>")
        return "".join(parts).encode("utf-8")

    @classmethod
    def _panel_html(cls, panel: DashboardPanel, result: PanelResult) -> list[str]:
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
            f"<span>{result.input_count} inputs · input SHA256 "
            f"<code>{result.inputs_sha256}</code></span>",
            f"<span>Showing the last {len(result.points)} of {result.point_count} points</span>",
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
                parts.append(cls._point_html(point, spec.units))
            parts.append("</tbody></table></div>")
        parts.append("</section>")
        return parts

    @classmethod
    def _point_html(cls, point: MetricPoint, units: str) -> str:
        """Format one chart point's table row from the point and its metric units alone."""
        return cls._row(
            (
                point.sample,
                point.at.isoformat(),
                cls._exact(point.value) if point.value is not None else "—",
                units,
                point.missing_reason or "",
            )
        )

    @classmethod
    def _chart_svg(cls, panel: DashboardPanel, result: PanelResult) -> str:
        """Project exact points to a visual scale while splitting paths at gaps."""
        points = result.points
        if not points:
            return ""
        exact = [
            None
            if point.value is None
            else Fraction(int(point.value.numerator), int(point.value.denominator))
            for point in points
        ]
        values = [value for value in exact if value is not None]
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
            for index, (point, value) in enumerate(zip(points, exact, strict=True)):
                x = cls._plot_x(point.at, start, duration, index, len(points))
                if value is None:
                    parts.append(cls._gap_marker(x, point.missing_reason or "gap"))
                    continue
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
            for index, (point, value) in enumerate(zip(points, exact, strict=True)):
                x = cls._plot_x(point.at, start, duration, index, len(points))
                if value is None:
                    if len(run) > 1:
                        parts.append(f'<path class="series" d="{" ".join(run)}"/>')
                    run = []
                    parts.append(cls._gap_marker(x, point.missing_reason or "gap"))
                    continue
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
            # Integer true division is correctly rounded, as float(Fraction(...)) is.
            return 48.0 + 684.0 * (cls._microseconds(at - start) / duration)
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
    def _row(values: tuple[str, ...]) -> str:
        """Escape every data-bearing cell at the HTML boundary."""
        return "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>"


class _ValueFields(msgspec.Struct, frozen=True):
    """Read only an aggregated input's exact value from its retained payload."""

    value: ExactRatio | None
    missing_reason: str | None = None


_VALUE_FIELDS = msgspec.json.Decoder(_ValueFields)


class _DecodeCache:
    """Reuse at most 10,000 decoded payloads of each kind across one renderer's reads.

    ``shared`` events go to injected definitions, which may mutate them, so a reused
    one is validated again. ``private`` events are only read by the installed series
    path and never handed out. Equal canonical bytes prove a private event unchanged;
    the one object it shares, a point's ``ExactRatio``, is validated with the point.
    """

    def __init__(self) -> None:
        """Start with no reusable events."""
        self.shared: OrderedDict[bytes, tuple[MonitoringEvent, str]] = OrderedDict()
        self.private: OrderedDict[bytes, tuple[MonitoringEvent, str]] = OrderedDict()


class DashboardViewSelection:
    """Hold one query's selected payloads in query order and admit events on demand.

    Payloads come from the store's latest-revision selection or from caller events
    admitted here. Every read of an event checks it against the query, its row and
    its exact bytes, so a definition that mutates an event cannot change what a
    later reader of the same row sees.
    """

    def __init__(
        self,
        query: MonitoringQuery,
        rows: tuple[TelemetryRow, ...],
        codec: DomainCodec,
        cache: _DecodeCache | None,
    ) -> None:
        """Bind rows to the query and an optional payload-keyed decode cache."""
        self.query, self.rows, self.codec = query, rows, codec
        self.cache = _DecodeCache() if cache is None else cache
        self.series: dict[tuple[str, str], list[int]] = {}
        for index, row in enumerate(rows):
            self.series.setdefault((row.name, row.version), []).append(index)
        self._digests: list[bytes] | None = None

    @classmethod
    def of(
        cls,
        query: MonitoringQuery,
        inputs: tuple[MonitoringEvent, ...] | TelemetrySelection,
        codec: DomainCodec,
        cache: _DecodeCache | None = None,
    ) -> DashboardViewSelection:
        """Accept a store selection for this query, or admit and order caller events."""
        query.__post_init__()
        if type(inputs) is TelemetrySelection:
            if inputs.query != query:
                raise ValueError("dashboard selection was made for another query")
            if (
                type(inputs.rows) is not tuple
                or len(inputs.rows) > query.limit
                or any(type(row) is not TelemetryRow for row in inputs.rows)
            ):
                raise ValueError("dashboard requires a bounded typed selection")
            return cls(query, inputs.rows, codec, cache)
        if type(inputs) is not tuple:
            raise TypeError("dashboard events must be an immutable tuple")
        if len(inputs) > query.limit:
            raise ValueError("dashboard requires bounded immutable input events")
        rows: list[TelemetryRow] = []
        for event in inputs:
            if type(event) is not MonitoringEvent:
                raise TypeError("dashboard input events must be typed")
            cls._admit(query, event)
            rows.append(
                TelemetryRow(
                    event.name,
                    event.version,
                    event.sample,
                    event.at.isoformat(timespec="microseconds"),
                    codec.encode_json(event),
                )
            )
        rows.sort(key=cls._order)
        if len({(row.name, row.version, row.sample) for row in rows}) != len(rows):
            raise ValueError("dashboard events require one selected revision per sample")
        return cls(query, tuple(rows), codec, cache)

    @staticmethod
    def _order(row: TelemetryRow) -> ProvenanceCursor:
        """Order rows as the store does."""
        return row.cursor

    @staticmethod
    def _admit(query: MonitoringQuery, event: MonitoringEvent) -> None:
        """Validate one event and require it inside the query's scope, window and cutoffs."""
        event.__post_init__()
        if (
            (event.context.scope, event.context.mode) != (query.scope, query.mode)
            or not query.start <= event.at < query.end
            or event.available_at > query.as_of
            or event.recorded_at > query.as_of
        ):
            raise ValueError("dashboard event violates the selected query")

    def event(self, index: int, *, private: bool = False) -> MonitoringEvent:
        """Admit the event of one row from its exact canonical bytes.

        A ``private`` event must never leave the installed series path.
        """
        row = self.rows[index]
        cache = self.cache.private if private else self.cache.shared
        cached = cache.get(row.payload)
        # Equal canonical bytes prove the cached values, and so its event-time text,
        # unchanged since it was decoded.
        if cached is None or self.codec.encode_json(cached[0]) != row.payload:
            event = self.codec.decode_json(row.payload, MonitoringEvent)
            if self.codec.encode_json(event) != row.payload:
                raise ValueError("telemetry payload is not canonical")
            cached = event, event.at.isoformat(timespec="microseconds")
            cache[row.payload] = cached
        elif not private:
            cached[0].__post_init__()
        cache.move_to_end(row.payload)
        if len(cache) > 10_000:
            cache.popitem(last=False)
        event, at = cached
        if (
            (event.context.scope, event.context.mode) != (self.query.scope, self.query.mode)
            or not self.query.start <= event.at < self.query.end
            or event.available_at > self.query.as_of
            or event.recorded_at > self.query.as_of
        ):
            raise ValueError("dashboard event violates the selected query")
        if (event.name, event.version, event.sample, at) != (
            row.name,
            row.version,
            row.sample,
            row.at,
        ):
            raise ValueError("telemetry payload differs from its selected row")
        return event

    @staticmethod
    def digest(payloads: tuple[bytes, ...] | list[bytes]) -> str:
        """Hash the SHA256 digests of payloads in order, each an event identity."""
        return hashlib.sha256(
            b"".join(hashlib.sha256(payload).digest() for payload in payloads)
        ).hexdigest()

    def digest_rows(self, indices: list[int] | range) -> str:
        """Hash the selected rows' payload digests in order, hashing each payload once."""
        if self._digests is None:
            self._digests = [hashlib.sha256(row.payload).digest() for row in self.rows]
        digests = self._digests
        return hashlib.sha256(b"".join(digests[index] for index in indices)).hexdigest()

    def digest_all(self) -> str:
        """Hash every selected payload digest in query order."""
        return self.digest_rows(range(len(self.rows)))

    @classmethod
    def admit_all(
        cls, query: MonitoringQuery, payloads: tuple[bytes, ...], codec: DomainCodec
    ) -> None:
        """Admit retained payloads as a complete, ordered, latest-revision selection."""
        selection = cls(query, (), codec, None)
        previous: tuple[str, str, str, str] | None = None
        samples: set[tuple[str, str, str]] = set()
        for payload in payloads:
            event = codec.decode_json(payload, MonitoringEvent)
            if codec.encode_json(event) != payload:
                raise ValueError("telemetry payload is not canonical")
            cls._admit(selection.query, event)
            key = (
                event.at.isoformat(timespec="microseconds"),
                event.name,
                event.sample,
                event.version,
            )
            sample = event.name, event.sample, event.version
            if (previous is not None and key <= previous) or sample in samples:
                raise ValueError("retained provenance must be ordered distinct revisions")
            previous = key
            samples.add(sample)


class DashboardBuilder:
    """Evaluate injected metric definitions over one selection and optional local delivery.

    An installed ``SeriesMetric`` reads its series' payloads without decoding most of
    them: it admits the events it shows (the last ``POINT_LIMIT`` and every event tied
    at the latest event time), reads only the exact value of other aggregated inputs,
    and checks every input's units in its bytes. Any other definition receives all of
    its admitted inputs through ``MetricRegistry.evaluate``.
    """

    @staticmethod
    def build(
        config: DashboardConfig,
        query: MonitoringQuery,
        inputs: tuple[MonitoringEvent, ...] | TelemetrySelection,
        registry: MetricRegistry,
        alerts: OperationalAlerts | None = None,
    ) -> DashboardSnapshot:
        """Build an immutable view whose alerts cannot invoke hard controls."""
        return DashboardBuilder._build(
            config, DashboardViewSelection.of(query, inputs, DomainCodec()), registry, alerts
        )

    @staticmethod
    def _build(
        config: DashboardConfig,
        selection: DashboardViewSelection,
        registry: MetricRegistry,
        alerts: OperationalAlerts | None,
    ) -> DashboardSnapshot:
        """Evaluate every selected metric, then assess and optionally deliver alerts."""
        config.__post_init__()
        query = selection.query
        results = tuple(
            DashboardBuilder._panel(identity, selection, registry)
            for identity in config.metric_identities
        )
        event_count, events_sha256 = len(selection.rows), selection.digest_all()
        result_by_id = dict(zip(config.metric_identities, results, strict=True))
        # Every rule is assessed before any delivery, so a bad rule sends nothing.
        assessments = tuple(
            AlertEvaluation.assess(rule, result_by_id[rule.metric_identity])
            for rule in config.alerts
        )
        evaluations: list[AlertEvaluation] = []
        for assessment in assessments:
            rule = assessment.rule
            if assessment.state == "triggered" and alerts is not None:
                # Delivery binds to evidence validated after every definition has run.
                evidence = _DashboardEvidence(
                    config=config,
                    query=query,
                    event_count=event_count,
                    events_sha256=events_sha256,
                    results=results,
                )
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
            event_count=event_count,
            events_sha256=events_sha256,
            results=results,
            alert_results=tuple(evaluations),
        )

    @staticmethod
    def _panel(
        identity: str, selection: DashboardViewSelection, registry: MetricRegistry
    ) -> PanelResult:
        """Evaluate one registered definition over its named, versioned inputs."""
        definition = registry.definition(identity)
        spec, query = definition.spec, selection.query
        if query.mode not in spec.modes:
            return PanelResult(
                spec=spec,
                value=None,
                status="inapplicable",
                reason="metric does not apply to this mode",
                input_count=0,
                inputs_sha256=DashboardViewSelection.digest(()),
                point_count=0,
            )
        if type(definition) is SeriesMetric:
            return DashboardBuilder._series(definition.spec, selection)
        indices = sorted(
            index
            for item in spec.inputs
            for index in selection.series.get((item.name, item.version), ())
        )
        result = registry.evaluate(
            identity, query, tuple(selection.event(index) for index in indices)
        )
        return PanelResult(
            spec=result.spec,
            value=result.value,
            status=result.status,
            reason=result.reason,
            input_count=len(result.input_ids),
            inputs_sha256=hashlib.sha256(
                b"".join(bytes.fromhex(item) for item in result.input_ids)
            ).hexdigest(),
            point_count=len(result.points),
            points=result.points[-POINT_LIMIT:],
        )

    @staticmethod
    def _series(spec: MetricSpec, selection: DashboardViewSelection) -> PanelResult:
        """Apply installed last/sum/mean/maximum semantics, decoding only what is shown.

        The result equals ``SeriesMetric.evaluate`` over every input, restricted to
        the last ``POINT_LIMIT`` points.
        """
        spec.__post_init__()
        item, query = spec.inputs[0], selection.query
        indices = selection.series.get((item.name, item.version), [])
        payloads = [selection.rows[index].payload for index in indices]
        units = b'"units":' + selection.codec.encode_json(item.units)
        if any(units not in payload for payload in payloads):
            raise ValueError("metric input units differ from definition")
        ties = 0
        while ties < len(indices) and (
            selection.rows[indices[-1 - ties]].at == selection.rows[indices[-1]].at
        ):
            ties += 1
        shown = [
            selection.event(index, private=True) for index in indices[-max(POINT_LIMIT, ties) :]
        ]
        status: Literal["ok", "missing", "stale"] = "ok"
        reason: str | None = None
        value: ExactRatio | None = None
        if spec.aggregation == "last":
            chosen = shown[-ties:] if shown else []
            values = [] if not chosen else [max(chosen, key=SeriesMetric._latest).value]
        else:
            values = [_VALUE_FIELDS.decode(payload).value for payload in payloads[: -len(shown)]]
            values += [event.value for event in shown] if shown else []
        if not values or any(observed is None for observed in values):
            status, reason = "missing", "missing input observation"
        elif (
            spec.stale_after_seconds is not None
            and (query.as_of - shown[-1].at).total_seconds() > spec.stale_after_seconds
        ):
            status, reason = "stale", "latest observation exceeds freshness budget"
        else:
            exact = tuple(
                Fraction(int(observed.numerator), int(observed.denominator))
                for observed in values
                if observed is not None
            )
            if spec.aggregation == "last":
                total = exact[-1]
            elif spec.aggregation == "maximum":
                total = max(exact)
            else:
                total = sum(exact, Fraction())
                if spec.aggregation == "mean":
                    total /= len(exact)
            value = ExactRatio.from_fraction(total)
        return PanelResult(
            spec=spec,
            value=value,
            status=status,
            reason=reason,
            input_count=len(indices),
            inputs_sha256=selection.digest_rows(indices),
            point_count=len(indices),
            points=tuple(
                MetricPoint(
                    sample=event.sample,
                    at=event.at,
                    value=event.value,
                    missing_reason=event.missing_reason,
                )
                for event in shown[-POINT_LIMIT:]
            ),
        )


class DashboardRenderer:
    """Build fresh validated views while reusing exact decoded payloads.

    This renderer owns its decode cache for its lifetime. Every call reads its own
    selection and rebuilds cutoffs, metrics, freshness, alerts, header and view
    identity. A cached event is reused only for identical canonical payload bytes
    and is checked against each read's query and row. No complete dashboard is cached.
    """

    def __init__(self, config: DashboardConfig, registry: MetricRegistry) -> None:
        """Bind explicit metric selection and a finite per-renderer decode cache."""
        config.__post_init__()
        self.config, self.registry = config, registry
        self.codec = DomainCodec()
        self._events = _DecodeCache()

    def render(
        self,
        query: MonitoringQuery,
        inputs: tuple[MonitoringEvent, ...] | TelemetrySelection,
    ) -> tuple[bytes, str]:
        """Build and render one private validated view before exposing any output.

        Returns:
            Complete HTML bytes and the identity of the same immutable view.
        """
        snapshot = DashboardBuilder._build(
            self.config,
            DashboardViewSelection.of(query, inputs, self.codec, self._events),
            self.registry,
            None,
        )
        identity = snapshot._identity()
        return snapshot._render_validated_html(snapshot_identity=identity), identity
