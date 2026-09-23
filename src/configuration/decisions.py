"""Select research decision components without granting executable account authority."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from typing import Literal

# project library imports
from serialization import DomainCodec, WireRecord


class DecisionRun(WireRecord, frozen=True):
    """Pin one instance/entity, component versions, schedule and required capabilities.

    Products/calendars are explicit admission names, not universal support claims.
    Callers provide the actual installed capability profile before any source read.
    State and account isolation are different: this record grants no account access.
    """

    instance: str
    entity: str
    product: str
    calendar: str
    source_identity: str
    feature_identity: str
    policy_identity: str
    model_identity: str | None
    transform_identity: str | None
    output: Literal["target", "exposure", "order", "quote"]
    decisions: tuple[datetime, ...]
    required_capabilities: tuple[str, ...]
    schema_version: Literal["decision-run-v1"] = "decision-run-v1"

    def __post_init__(self) -> None:
        """Reject missing bindings and non-increasing schedules before any work."""
        if self.schema_version != "decision-run-v1" or self.output not in (
            "target",
            "exposure",
            "order",
            "quote",
        ):
            raise ValueError("unsupported decision run schema/output")
        for value in (
            self.instance,
            self.entity,
            self.product,
            self.calendar,
            self.source_identity,
            self.feature_identity,
            self.policy_identity,
        ):
            if type(value) is not str or not value:
                raise ValueError("decision run requires explicit component bindings")
        for optional in (self.model_identity, self.transform_identity):
            if optional is not None and (type(optional) is not str or not optional):
                raise ValueError("invalid optional fitted component binding")
        if type(self.decisions) is not tuple or not self.decisions:
            raise ValueError("decision run requires an immutable schedule")
        for at in self.decisions:
            self._require_utc(at, field_name="decision")
        if any(a >= b for a, b in zip(self.decisions, self.decisions[1:])):
            raise ValueError("decision schedule must strictly advance")
        if (
            type(self.required_capabilities) is not tuple
            or any(type(v) is not str or not v for v in self.required_capabilities)
            or len(set(self.required_capabilities)) != len(self.required_capabilities)
        ):
            raise ValueError("invalid capability requirements")

    @property
    def identity(self) -> str:
        """Identify the complete resolved research configuration, excluding paths."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def admit(self, available: tuple[str, ...]) -> None:
        """Reject missing product/calendar/intent or authored capabilities before startup."""
        self.__post_init__()
        required = {
            f"product:{self.product}",
            f"calendar:{self.calendar}",
            f"intent:{self.output}",
            *self.required_capabilities,
        }
        missing = sorted(required - set(available))
        if missing:
            raise ValueError(f"missing decision capabilities: {', '.join(missing)}")
