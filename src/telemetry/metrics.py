"""Evaluate registered exact metrics over causal telemetry and research observations."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, WireRecord
from telemetry.events import MonitoringEvent, MonitoringIdentity, MonitoringMode, MonitoringQuery


class MetricInput(WireRecord, frozen=True):
    """Pin a named input series, its semantic version and exact units."""

    name: str
    version: str
    units: str

    def __post_init__(self) -> None:
        """Require bounded explicit input semantics."""
        for value in (self.name, self.version, self.units):
            MonitoringIdentity.check_text(value)


class MetricSpec(WireRecord, frozen=True):
    """Identify a metric implementation, applicability, aggregation and missingness.

    The implementation digest identifies selected code, not an import instruction.
    Applications inject reviewed implementations; configuration cannot execute code.
    """

    name: str
    version: str
    implementation_sha256: str
    inputs: tuple[MetricInput, ...]
    units: str
    modes: tuple[MonitoringMode, ...]
    aggregation: Literal["last", "sum", "mean", "maximum", "custom"]
    missingness: str
    stale_after_seconds: int | None = None
    schema_version: Literal["metric-spec-v1"] = "metric-spec-v1"

    def __post_init__(self) -> None:
        """Reject ambiguous input names, missing units and unsupported schemas."""
        for value in (self.name, self.version, self.units, self.missingness):
            MonitoringIdentity.check_text(value)
        if (
            type(self.implementation_sha256) is not str
            or len(self.implementation_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.implementation_sha256)
        ):
            raise ValueError("metric requires its implementation SHA256")
        if type(self.inputs) is not tuple or not 1 <= len(self.inputs) <= 16:
            raise ValueError("metric requires bounded named inputs")
        for item in self.inputs:
            if type(item) is not MetricInput:
                raise TypeError("metric inputs must be typed")
            item.__post_init__()
        if len({item.name for item in self.inputs}) != len(self.inputs):
            raise ValueError("duplicate metric input")
        if (
            type(self.modes) is not tuple
            or not self.modes
            or len(set(self.modes)) != len(self.modes)
        ):
            raise ValueError("metric requires distinct applicable modes")
        for mode in self.modes:
            MonitoringIdentity(scope="metric", mode=mode)
        if self.aggregation not in ("last", "sum", "mean", "maximum", "custom"):
            raise ValueError("unsupported metric aggregation")
        if self.stale_after_seconds is not None and (
            type(self.stale_after_seconds) is not int
            or not 1 <= self.stale_after_seconds <= 31_536_000
        ):
            raise ValueError("metric freshness budget must be bounded")
        if self.schema_version != "metric-spec-v1":
            raise ValueError("unsupported metric schema")

    @property
    def identity(self) -> str:
        """Bind every definition field to its configuration selection."""
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class MetricPoint(WireRecord, frozen=True):
    """Retain an exact derived point or explicit gap for a configured chart."""

    sample: str
    at: datetime
    value: ExactRatio | None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate UTC timing and forbid fabricated values for missing points."""
        MonitoringIdentity.check_text(self.sample)
        self._require_utc(self.at, field_name="metric point")
        if self.value is None:
            if self.missing_reason is None:
                raise ValueError("missing metric point requires a reason")
            MonitoringIdentity.check_text(self.missing_reason)
        elif type(self.value) is not ExactRatio or self.missing_reason is not None:
            raise ValueError("invalid exact metric point")
        else:
            self.value.__post_init__()


class MetricResult(WireRecord, frozen=True):
    """Retain exact evaluation, input identities, query cutoffs and chart points."""

    spec: MetricSpec
    query: MonitoringQuery
    value: ExactRatio | None
    status: Literal["ok", "missing", "stale", "inapplicable"]
    reason: str | None
    input_ids: tuple[str, ...]
    points: tuple[MetricPoint, ...] = ()
    schema_version: Literal["metric-result-v1"] = "metric-result-v1"

    def __post_init__(self) -> None:
        """Reject incompatible output, ambiguous missingness and unbounded references."""
        if type(self.spec) is not MetricSpec or type(self.query) is not MonitoringQuery:
            raise TypeError("metric result requires typed definition and query")
        self.spec.__post_init__()
        self.query.__post_init__()
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
        if type(self.input_ids) is not tuple or len(self.input_ids) > self.query.limit:
            raise ValueError("metric input identities must be bounded")
        if len(set(self.input_ids)) != len(self.input_ids) or any(
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            for value in self.input_ids
        ):
            raise ValueError("metric input identities must be distinct SHA256 values")
        if type(self.points) is not tuple or len(self.points) > self.query.limit:
            raise ValueError("metric points must be bounded")
        seen: set[str] = set()
        previous: datetime | None = None
        for point in self.points:
            if type(point) is not MetricPoint:
                raise TypeError("metric points must be typed")
            point.__post_init__()
            if (
                point.sample in seen
                or not self.query.start <= point.at < self.query.end
                or (previous is not None and point.at < previous)
            ):
                raise ValueError("metric points must be distinct and ordered within the query")
            seen.add(point.sample)
            previous = point.at
        if self.schema_version != "metric-result-v1":
            raise ValueError("unsupported metric result schema")


class MonitoringMetric(Protocol):
    """Allow independently authored metrics without collector or runtime changes."""

    @property
    def spec(self) -> MetricSpec:
        """Expose the immutable selected definition."""
        ...

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Compute an exact result from validated, available, unit-compatible input revisions."""
        ...


class MetricRegistry:
    """Resolve only explicitly injected metric implementations by complete definition digest."""

    def __init__(self, definitions: tuple[MonitoringMetric, ...]) -> None:
        """Reject duplicate registrations and validate selected definition contracts."""
        self._definitions: dict[str, MonitoringMetric] = {}
        names: set[tuple[str, str]] = set()
        for definition in definitions:
            definition.spec.__post_init__()
            key = definition.spec.name, definition.spec.version
            if key in names:
                raise ValueError("duplicate monitoring metric registration")
            names.add(key)
            self._definitions[definition.spec.identity] = definition

    def evaluate(
        self, identity: str, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]
    ) -> MetricResult:
        """Validate causal input and retain the selected output without substitution."""
        query.__post_init__()
        definition = self._definitions.get(identity)
        if definition is None or definition.spec.identity != identity:
            raise ValueError("unregistered or changed monitoring definition")
        spec = definition.spec
        if query.mode not in spec.modes:
            return MetricResult(
                spec=spec,
                query=query,
                value=None,
                status="inapplicable",
                reason="metric does not apply to this mode",
                input_ids=(),
            )
        selected: list[MonitoringEvent] = []
        inputs = {item.name: item for item in spec.inputs}
        keys: set[tuple[str, str]] = set()
        if type(events) is not tuple or len(events) > query.limit:
            raise ValueError("metric requires a bounded immutable event query")
        for event in events:
            event.__post_init__()
            if (
                (event.context.scope, event.context.mode) != (query.scope, query.mode)
                or not query.start <= event.at < query.end
                or event.recorded_at > query.as_of
                or event.available_at > query.as_of
            ):
                raise ValueError("metric input violates query scope or availability")
            item = inputs.get(event.name)
            if item is None or event.version != item.version:
                continue
            if event.units != item.units:
                raise ValueError("metric input units differ from definition")
            key = event.name, event.sample
            if key in keys:
                raise ValueError("metric requires one selected revision per input sample")
            keys.add(key)
            selected.append(event)
        rows = tuple(sorted(selected, key=self._order))
        result = definition.evaluate(query, rows)
        result.__post_init__()
        if (result.spec, result.query, result.input_ids) != (
            spec,
            query,
            tuple(event.identity for event in rows),
        ):
            raise ValueError(
                "metric implementation replaced selected definition or input identities"
            )
        return result

    @staticmethod
    def _order(event: MonitoringEvent) -> tuple[datetime, str, str]:
        """Keep independently emitted series deterministic at equal clocks."""
        return event.at, event.name, event.sample


class SeriesMetric:
    """Aggregate one exact series, preserving missing observations and freshness failures."""

    def __init__(self, spec: MetricSpec) -> None:
        """Select last/sum/mean/maximum semantics for one same-unit input."""
        spec.__post_init__()
        if (
            len(spec.inputs) != 1
            or spec.inputs[0].units != spec.units
            or spec.aggregation == "custom"
            or spec.missingness != "propagate"
        ):
            raise ValueError("series metric requires one same-unit input and propagate missingness")
        self.spec = spec

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Apply the selected aggregation; last uses only the final observed sample."""
        points = tuple(
            MetricPoint(sample=e.sample, at=e.at, value=e.value, missing_reason=e.missing_reason)
            for e in events
        )
        chosen = (
            (max(events, key=self._latest),)
            if events and self.spec.aggregation == "last"
            else events
        )
        status: Literal["ok", "missing", "stale"] = "ok"
        reason: str | None = None
        value: ExactRatio | None = None
        if not chosen or any(e.value is None for e in chosen):
            status, reason = "missing", "missing input observation"
        elif (
            self.spec.stale_after_seconds is not None
            and (query.as_of - chosen[-1].at).total_seconds() > self.spec.stale_after_seconds
        ):
            status, reason = "stale", "latest observation exceeds freshness budget"
        else:
            values = tuple(
                Fraction(int(e.value.numerator), int(e.value.denominator))
                for e in chosen
                if e.value is not None
            )
            if self.spec.aggregation == "last":
                total = values[-1]
            elif self.spec.aggregation == "maximum":
                total = max(values)
            else:
                total = sum(values, Fraction())
                if self.spec.aggregation == "mean":
                    total /= len(values)
            value = ExactRatio.from_fraction(total)
        return MetricResult(
            spec=self.spec,
            query=query,
            value=value,
            status=status,
            reason=reason,
            input_ids=tuple(e.identity for e in events),
            points=points,
        )

    @staticmethod
    def _latest(event: MonitoringEvent) -> tuple[datetime, datetime, datetime, str]:
        """Resolve equal event clocks by receipt/availability before stable sample identity."""
        return event.at, event.recorded_at, event.available_at, event.sample


class DelayedLabelError:
    """Join predictions and delayed outcome revisions at the query's knowledge cutoff."""

    def __init__(self, spec: MetricSpec) -> None:
        """Select prediction then outcome inputs with exact mean-square-error output units."""
        spec.__post_init__()
        if (
            len(spec.inputs) != 2
            or spec.inputs[0].units != spec.inputs[1].units
            or spec.units != f"({spec.inputs[0].units})^2"
            or spec.aggregation != "custom"
            or spec.stale_after_seconds is not None
            or spec.missingness != "pending labels remain gaps; mean uses observed pairs"
        ):
            raise ValueError(
                "delayed labels require compatible prediction/outcome units and policy"
            )
        self.spec = spec

    def evaluate(self, query: MonitoringQuery, events: tuple[MonitoringEvent, ...]) -> MetricResult:
        """Retain pending gaps and compute error only for labels known at this evaluation cutoff."""
        labels = {e.sample: e for e in events if e.name == self.spec.inputs[1].name}
        points: list[MetricPoint] = []
        values: list[Fraction] = []
        for event in events:
            if event.name != self.spec.inputs[0].name:
                continue
            label = labels.get(event.sample)
            if label is not None and (label.at, label.context) != (event.at, event.context):
                raise ValueError("delayed label correlation differs from prediction")
            value: ExactRatio | None = None
            reason: str | None = "pending label"
            if event.value is None:
                reason = event.missing_reason
            elif label is not None and label.value is None:
                reason = label.missing_reason
            elif label is not None and label.value is not None:
                error = (
                    Fraction(int(event.value.numerator), int(event.value.denominator))
                    - Fraction(int(label.value.numerator), int(label.value.denominator))
                ) ** 2
                values.append(error)
                value, reason = ExactRatio.from_fraction(error), None
            points.append(
                MetricPoint(sample=event.sample, at=event.at, value=value, missing_reason=reason)
            )
        result_value = (
            None if not values else ExactRatio.from_fraction(sum(values, Fraction()) / len(values))
        )
        return MetricResult(
            spec=self.spec,
            query=query,
            value=result_value,
            status="missing" if not values else "ok",
            reason="no observed prediction/label pairs" if not values else None,
            input_ids=tuple(e.identity for e in events),
            points=tuple(points),
        )
