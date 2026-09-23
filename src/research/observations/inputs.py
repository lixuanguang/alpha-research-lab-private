"""Describe named numeric observations without erasing their source family or clocks."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from serialization import DomainCodec, WireRecord


class NumericField(WireRecord, frozen=True):
    """Name an exact numeric field and its explicit units; no implicit conversion occurs."""

    name: str
    units: str

    def __post_init__(self) -> None:
        """Refuse unnamed or dimensionless-by-accident fields."""
        for value in (self.name, self.units):
            if type(value) is not str or not value.strip():
                raise ValueError("numeric field requires name and units")


class InputRequirement(WireRecord, frozen=True):
    """Select one named source field with an inclusive event-age limit in microseconds."""

    name: str
    family: Literal["trade", "book", "reference", "non-book"]
    clock: Literal["event", "receipt", "valid", "authored"]
    field: NumericField
    max_age_us: int

    def __post_init__(self) -> None:
        """Validate the typed signature and freshness contract before reading inputs."""
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("input requires a name")
        if self.clock not in ("event", "receipt", "valid", "authored"):
            raise ValueError("unsupported input clock")
        if self.family not in ("trade", "book", "reference", "non-book"):
            raise ValueError("unsupported input family")
        if type(self.field) is not NumericField:
            raise TypeError("input requires NumericField")
        self.field.__post_init__()
        if type(self.max_age_us) is not int or not 0 <= self.max_age_us <= 31_536_000_000_000:
            raise ValueError("input age must be integer microseconds within one year")


class NamedObservation(WireRecord, frozen=True):
    """Retain one admitted projection, including unknown availability and missingness.

    Lineage identifies actual source/query/revision bytes. Event time describes
    the measured value; availability describes knowledge, never inferred receipt.
    A non-book producer supplies its own projection without fabricating feed events.
    """

    input: InputRequirement
    entity: str
    event_at: datetime
    available_at: datetime | None
    value: ExactRatio | None
    reason: str
    lineage: str

    def __post_init__(self) -> None:
        """Require exact values, explicit lineage and consistent missingness."""
        if type(self.input) is not InputRequirement:
            raise TypeError("observation requires InputRequirement")
        self.input.__post_init__()
        self._require_utc(self.event_at, field_name="event_at")
        if self.available_at is not None:
            self._require_utc(self.available_at, field_name="available_at")
        for value in (self.entity, self.reason, self.lineage):
            if type(value) is not str or not value.strip():
                raise ValueError("observation requires entity, reason and lineage")
        if self.value is not None:
            if type(self.value) is not ExactRatio or self.available_at is None:
                raise ValueError("a value requires exact arithmetic and known availability")
            self.value.__post_init__()


class DecisionInputs(WireRecord, frozen=True):
    """Freeze ordered, then-known source projections for one entity and decision."""

    entity: str
    decision_at: datetime
    observations: tuple[NamedObservation, ...]

    def __post_init__(self) -> None:
        """Reject future, stale, cross-entity and duplicate source fields."""
        self._require_utc(self.decision_at, field_name="decision_at")
        if type(self.entity) is not str or not self.entity.strip():
            raise ValueError("decision requires an entity")
        if type(self.observations) is not tuple or not self.observations:
            raise ValueError("decision requires immutable named observations")
        keys: set[tuple[str, str]] = set()
        for row in self.observations:
            if type(row) is not NamedObservation:
                raise TypeError("decision requires NamedObservation")
            row.__post_init__()
            key = row.input.name, row.input.field.name
            if key in keys or row.entity != self.entity:
                raise ValueError("duplicate field or mixed decision entity")
            keys.add(key)
            if row.event_at > self.decision_at or (
                row.available_at is not None and row.available_at > self.decision_at
            ):
                raise ValueError("decision cannot consume future inputs")
            if row.value is not None and self.decision_at - row.event_at > timedelta(
                microseconds=row.input.max_age_us
            ):
                raise ValueError("decision cannot consume stale inputs")

    @property
    def identity(self) -> str:
        """Identify exact admitted inputs without including future source history."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class ObservationHistory:
    """Select numeric non-book or adapter projections at an inclusive knowledge cutoff.

    Equal event times use the latest known revision. Ambiguous simultaneous values
    fail; missing/stale values remain absent instead of falling back to older rows.
    This policy is explicit and does not replace source-specific query admission.
    """

    def __init__(self, rows: tuple[NamedObservation, ...]) -> None:
        """Bind immutable projected observations; validate before any selection."""
        if type(rows) is not tuple:
            raise TypeError("observation history requires a tuple")
        for row in rows:
            row.__post_init__()
        self._rows = rows

    def select(
        self, entity: str, at: datetime, requirements: tuple[InputRequirement, ...]
    ) -> DecisionInputs:
        """Select one entity, retaining unknown/missing/stale reasons and selected lineage."""
        DecisionInputs._require_utc(at, field_name="at")
        selected: list[NamedObservation] = []
        for requirement in requirements:
            requirement.__post_init__()
            candidates = tuple(
                row
                for row in self._rows
                if row.entity == entity
                and row.input == requirement
                and row.event_at <= at
                and row.available_at is not None
                and row.available_at <= at
            )
            if not candidates:
                selected.append(
                    NamedObservation(
                        input=requirement,
                        entity=entity,
                        event_at=at,
                        available_at=None,
                        value=None,
                        reason="missing_or_unknown",
                        lineage="no-admitted-observation",
                    )
                )
                continue
            row = max(candidates, key=self._order)
            if any(self._order(other) == self._order(row) and other != row for other in candidates):
                raise ValueError("ambiguous simultaneous observation revisions")
            if at - row.event_at > timedelta(microseconds=requirement.max_age_us):
                row = NamedObservation(
                    input=requirement,
                    entity=entity,
                    event_at=row.event_at,
                    available_at=row.available_at,
                    value=None,
                    reason="stale",
                    lineage=row.lineage,
                )
            selected.append(row)
        return DecisionInputs(entity=entity, decision_at=at, observations=tuple(selected))

    @staticmethod
    def _order(row: NamedObservation) -> tuple[datetime, datetime]:
        """Order known candidates by event and revision availability."""
        if row.available_at is None:
            raise ValueError("unknown availability cannot participate in precedence")
        return row.event_at, row.available_at


class DecisionSource(Protocol):
    """Expose source identity and exact named input signatures before causal reads."""

    @property
    def identity(self) -> str:
        """Pin actual source history/selection independently of a mutable path."""
        ...

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Declare the supported ordered projection and freshness policy."""
        ...

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Return only then-known admitted fields for the requested decision."""
        ...


class NumericHistorySource:
    """Adapt retained non-book numeric observations through the same causal source interface."""

    def __init__(
        self, rows: tuple[NamedObservation, ...], requirements: tuple[InputRequirement, ...]
    ) -> None:
        """Bind actual immutable input bytes and the selected signature explicitly."""
        self._history = ObservationHistory(rows)
        for requirement in requirements:
            requirement.__post_init__()
        self._requirements = requirements
        self._identity = hashlib.sha256(DomainCodec().encode_json((rows, requirements))).hexdigest()

    @property
    def identity(self) -> str:
        """Pin source values, revisions, units and selected projection."""
        return self._identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Return the declared named input signature."""
        return self._requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Select known observations with explicit revision and freshness semantics."""
        return self._history.select(entity, at, self._requirements)
