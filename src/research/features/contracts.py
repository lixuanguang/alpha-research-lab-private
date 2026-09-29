"""Execute versioned multi-input features with explicit, portable incremental state."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from research.observations import DecisionInputs, InputRequirement, NumericField
from serialization import DomainCodec, WireRecord


class FeatureSchema(WireRecord, frozen=True):
    """Bind ordered output names/units to an implementation, parameters and input contract."""

    implementation: str
    inputs: tuple[InputRequirement, ...]
    outputs: tuple[NumericField, ...]
    parameters: tuple[tuple[str, str], ...]
    mode: Literal["batch", "incremental"]
    ttl_us: int
    schema_version: Literal["feature-schema"] = "feature-schema"

    def __post_init__(self) -> None:
        """Refuse ambiguous signatures, unsupported lifecycle and implicit freshness."""
        if (
            self.schema_version != "feature-schema"
            or not isinstance(self.implementation, str)
            or not self.implementation.strip()
        ):
            raise ValueError("feature requires a supported schema and implementation version")
        for rows in (self.inputs, self.outputs):
            if type(rows) is not tuple or not rows:
                raise ValueError("feature requires nonempty immutable signatures")
            for row in rows:
                row.__post_init__()
        if len({(r.name, r.field.name) for r in self.inputs}) != len(self.inputs) or len(
            {r.name for r in self.outputs}
        ) != len(self.outputs):
            raise ValueError("feature signature contains duplicate names")
        if (
            self.mode not in ("batch", "incremental")
            or type(self.ttl_us) is not int
            or not 0 <= self.ttl_us <= 31_536_000_000_000
        ):
            raise ValueError("invalid feature lifecycle or TTL")
        if type(self.parameters) is not tuple or any(
            type(p) is not tuple or len(p) != 2 or any(type(v) is not str or not v for v in p)
            for p in self.parameters
        ):
            raise ValueError("parameters must be named immutable strings")
        if len(dict(self.parameters)) != len(self.parameters):
            raise ValueError("duplicate feature parameter")

    @property
    def identity(self) -> str:
        """Pin definition, ordered signature, parameters and lifecycle for MR04 retrieval."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class FeatureVector(WireRecord, frozen=True):
    """Retain exact named features separately from labels and fitted preprocessing.

    Availability and TTL are inclusive; event time and input lineage stay explicit.
    Missing values retain per-column reasons. No imputation or unit conversion is
    performed. Definition and transform IDs are feature-store version bindings.
    """

    entity: str
    decision_at: datetime
    event_at: datetime
    information_start: datetime
    available_at: datetime
    expires_at: datetime
    definition: str
    fields: tuple[NumericField, ...]
    values: tuple[ExactRatio | None, ...]
    reasons: tuple[str, ...]
    input_identity: str
    transform_identity: str | None = None

    def __post_init__(self) -> None:
        """Validate signature, exact numeric values, clocks and immutable missingness."""
        for name, at in (
            ("decision", self.decision_at),
            ("event", self.event_at),
            ("information_start", self.information_start),
            ("availability", self.available_at),
            ("expiry", self.expires_at),
        ):
            self._require_utc(at, field_name=name)
        if (
            not self.information_start <= self.event_at <= self.decision_at
            or not self.decision_at <= self.available_at <= self.expires_at
        ):
            raise ValueError("invalid feature clocks")
        for text in (self.entity, self.definition, self.input_identity):
            if type(text) is not str or not text:
                raise ValueError("feature requires entity and version identities")
        if self.transform_identity is not None and (
            type(self.transform_identity) is not str or not self.transform_identity
        ):
            raise ValueError("invalid fitted transform identity")
        if (
            any(type(rows) is not tuple for rows in (self.fields, self.values, self.reasons))
            or not self.fields
            or not len(self.fields) == len(self.values) == len(self.reasons)
        ):
            raise ValueError("feature signature and value lengths differ")
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError("duplicate feature name")
        for field, value, reason in zip(self.fields, self.values, self.reasons, strict=True):
            if type(field) is not NumericField:
                raise TypeError("feature requires NumericField")
            field.__post_init__()
            if type(reason) is not str or not reason:
                raise ValueError("feature requires quality reasons")
            if value is not None:
                if type(value) is not ExactRatio:
                    raise TypeError("feature requires exact rational values")
                value.__post_init__()

    @property
    def identity(self) -> str:
        """Identify actual values and lineage independently of later input revisions."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def require_available(self, at: datetime) -> None:
        """Reject a future decision, unavailable result or expired served value."""
        self.__post_init__()
        self._require_utc(at, field_name="retrieval")
        if not self.decision_at <= self.available_at <= at <= self.expires_at:
            raise ValueError("feature unavailable or expired")


class FeatureTransition(WireRecord, frozen=True):
    """Return values and immutable successor state; kernels must not mutate hidden state."""

    values: tuple[ExactRatio | None, ...]
    reasons: tuple[str, ...]
    state: bytes

    def __post_init__(self) -> None:
        """Refuse mutable state and inconsistent outputs."""
        if (
            type(self.state) is not bytes
            or type(self.values) is not tuple
            or type(self.reasons) is not tuple
            or len(self.values) != len(self.reasons)
        ):
            raise ValueError("invalid feature transition")


class FeatureKernel(Protocol):
    """Supply a pure transition and state validator for a versioned arbitrary feature schema."""

    @property
    def schema(self) -> FeatureSchema:
        """Return the complete supported feature definition."""
        ...

    def initial_state(self) -> bytes:
        """Return immutable empty/warm-up state for one independent instance/entity."""
        ...

    def validate_state(self, state: bytes) -> None:
        """Reject incompatible or malformed state without modifying the kernel."""
        ...

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Compute only from admitted inputs and prior bytes, leaving both unchanged."""
        ...


class FeatureCheckpoint(WireRecord, frozen=True):
    """Bind restart bytes to the exact definition, instance, entity and completed cutoff."""

    definition: str
    instance: str
    entity: str
    last_at: datetime | None
    information_start: datetime | None
    state: bytes
    sha256: str
    schema_version: Literal["feature-checkpoint"] = "feature-checkpoint"

    def __post_init__(self) -> None:
        """Detect corrupted or unsafe copied state; this is integrity, not authentication."""
        if self.schema_version != "feature-checkpoint" or type(self.state) is not bytes:
            raise ValueError("invalid feature checkpoint schema/state")
        if any(type(v) is not str or not v for v in (self.definition, self.instance, self.entity)):
            raise ValueError("checkpoint requires definition, instance and entity")
        if self.last_at is not None:
            self._require_utc(self.last_at, field_name="last_at")
        if (self.last_at is None) != (self.information_start is None):
            raise ValueError("checkpoint information interval is incomplete")
        if self.information_start is not None:
            self._require_utc(self.information_start, field_name="information_start")
            if self.last_at is not None and self.information_start > self.last_at:
                raise ValueError("checkpoint information interval is reversed")
        if self.sha256 != self.digest(
            self.definition,
            self.instance,
            self.entity,
            self.last_at,
            self.information_start,
            self.state,
        ):
            raise ValueError("feature checkpoint digest mismatch")

    @staticmethod
    def digest(
        definition: str,
        instance: str,
        entity: str,
        last_at: datetime | None,
        information_start: datetime | None,
        state: bytes,
    ) -> str:
        """Bind all semantic restart fields, not merely the payload bytes."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                (definition, instance, entity, last_at, information_start, state)
            )
        ).hexdigest()


class FeatureSession:
    """Own transactional incremental execution; batch consumers call the same transitions."""

    def __init__(
        self,
        kernel: FeatureKernel,
        *,
        instance: str,
        entity: str,
        checkpoint: FeatureCheckpoint | None = None,
    ) -> None:
        """Bind one isolated state stream and reject foreign or incompatible restart bytes."""
        kernel.schema.__post_init__()
        self._kernel, self._schema = kernel, kernel.schema
        self._instance, self._entity = instance, entity
        self._last_at: datetime | None = None
        self._information_start: datetime | None = None
        self._state = kernel.initial_state()
        if checkpoint is not None:
            checkpoint.__post_init__()
            if (checkpoint.definition, checkpoint.instance, checkpoint.entity) != (
                self._schema.identity,
                instance,
                entity,
            ):
                raise ValueError("incompatible feature checkpoint binding")
            self._last_at, self._state = checkpoint.last_at, checkpoint.state
            self._information_start = checkpoint.information_start
        kernel.validate_state(self._state)
        self.checkpoint()

    def evaluate(self, inputs: DecisionInputs) -> FeatureVector:
        """Advance one strictly increasing decision only after full result/state validation.

        Failure leaves the committed state unchanged. Late inputs can affect future
        decisions but cannot revise an already completed cutoff. Batch kernels start
        fresh at each call; incremental kernels receive the committed prior bytes.
        """
        inputs.__post_init__()
        if (
            self._kernel.schema != self._schema
            or inputs.entity != self._entity
            or tuple(r.input for r in inputs.observations) != self._schema.inputs
        ):
            raise ValueError("feature input signature or definition mismatch")
        if self._last_at is not None and inputs.decision_at <= self._last_at:
            raise ValueError("feature decisions must strictly advance")
        state = self._state if self._schema.mode == "incremental" else self._kernel.initial_state()
        transition = self._kernel.step(inputs, state)
        transition.__post_init__()
        self._kernel.validate_state(transition.state)
        information_start = min(row.event_at for row in inputs.observations)
        if self._schema.mode == "incremental" and self._information_start is not None:
            information_start = min(information_start, self._information_start)
        result = FeatureVector(
            entity=inputs.entity,
            decision_at=inputs.decision_at,
            event_at=max(row.event_at for row in inputs.observations),
            information_start=information_start,
            available_at=inputs.decision_at,
            expires_at=inputs.decision_at + timedelta(microseconds=self._schema.ttl_us),
            definition=self._schema.identity,
            fields=self._schema.outputs,
            values=transition.values,
            reasons=transition.reasons,
            input_identity=hashlib.sha256(
                DomainCodec().encode_json((inputs.identity, state))
            ).hexdigest(),
        )
        self._state, self._last_at = transition.state, inputs.decision_at
        self._information_start = information_start
        return result

    def checkpoint(self) -> FeatureCheckpoint:
        """Snapshot immutable state for serialization and exact reload-only continuation."""
        return FeatureCheckpoint(
            definition=self._schema.identity,
            instance=self._instance,
            entity=self._entity,
            last_at=self._last_at,
            information_start=self._information_start,
            state=self._state,
            sha256=FeatureCheckpoint.digest(
                self._schema.identity,
                self._instance,
                self._entity,
                self._last_at,
                self._information_start,
                self._state,
            ),
        )


class ProjectionFeature:
    """Project named source columns unchanged through the generic batch lifecycle."""

    def __init__(self, schema: FeatureSchema) -> None:
        """Require an explicit one-to-one mapping with matching units and no parameters."""
        schema.__post_init__()
        if (
            schema.implementation != "named-projection"
            or schema.mode != "batch"
            or schema.parameters
            or tuple(r.field.units for r in schema.inputs) != tuple(f.units for f in schema.outputs)
        ):
            raise ValueError("unsupported projection feature definition")
        self._schema = schema

    @property
    def schema(self) -> FeatureSchema:
        """Expose the selected versioned projection."""
        return self._schema

    def initial_state(self) -> bytes:
        """Use no fitted or incremental state for a pure projection."""
        return b""

    def validate_state(self, state: bytes) -> None:
        """Reject accidental fitted or incremental state."""
        if state != b"" or type(state) is not bytes:
            raise ValueError("projection feature must be stateless")

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Preserve then-known values and all missingness reasons in authored order."""
        self.validate_state(state)
        return FeatureTransition(
            values=tuple(r.value for r in inputs.observations),
            reasons=tuple(r.reason for r in inputs.observations),
            state=b"",
        )


class RunningMeanFeature:
    """Maintain one exact expanding mean per field, resetting a field on missing input."""

    def __init__(self, schema: FeatureSchema) -> None:
        """Require the explicit incremental mean definition and unchanged units."""
        schema.__post_init__()
        if (
            schema.implementation != "running-mean"
            or schema.mode != "incremental"
            or schema.parameters
            or tuple(r.field.units for r in schema.inputs) != tuple(f.units for f in schema.outputs)
        ):
            raise ValueError("unsupported running mean definition")
        self._schema, self._codec = schema, DomainCodec()

    @property
    def schema(self) -> FeatureSchema:
        """Expose exact expanding-mean and missing-reset semantics."""
        return self._schema

    def initial_state(self) -> bytes:
        """Start each column with zero observations and no warm-up value."""
        return self._codec.encode_json(
            _MeanState(
                counts=(0,) * len(self.schema.outputs),
                totals=(ExactRatio.from_fraction(Fraction()),) * len(self.schema.outputs),
            )
        )

    def validate_state(self, state: bytes) -> None:
        """Reject corrupt counts or a foreign column signature."""
        decoded = self._codec.decode_json(state, _MeanState)
        if len(decoded.counts) != len(self.schema.outputs):
            raise ValueError("running mean state width mismatch")

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Advance exact sums; missing input resets only its own column."""
        prior = self._codec.decode_json(state, _MeanState)
        counts: list[int] = []
        totals: list[ExactRatio] = []
        values: list[ExactRatio | None] = []
        for row, count, total in zip(inputs.observations, prior.counts, prior.totals, strict=True):
            value = row.value
            n = 0 if value is None else count + 1
            accumulated = (
                Fraction()
                if value is None
                else Fraction(int(total.numerator), int(total.denominator))
                + Fraction(int(value.numerator), int(value.denominator))
            )
            counts.append(n)
            totals.append(ExactRatio.from_fraction(accumulated))
            values.append(None if not n else ExactRatio.from_fraction(accumulated / n))
        return FeatureTransition(
            values=tuple(values),
            reasons=tuple(r.reason for r in inputs.observations),
            state=self._codec.encode_json(_MeanState(counts=tuple(counts), totals=tuple(totals))),
        )


class _MeanState(WireRecord, frozen=True):
    """Retain exact counts and sums for the reference incremental feature."""

    counts: tuple[int, ...]
    totals: tuple[ExactRatio, ...]

    def __post_init__(self) -> None:
        """Reject malformed or inconsistent state before continuation."""
        if (
            type(self.counts) is not tuple
            or type(self.totals) is not tuple
            or len(self.counts) != len(self.totals)
        ):
            raise ValueError("invalid running mean state")
        for count, total in zip(self.counts, self.totals, strict=True):
            total.__post_init__()
            if type(count) is not int or count < 0 or (count == 0 and total.numerator != "0"):
                raise ValueError("invalid running mean count/total")
