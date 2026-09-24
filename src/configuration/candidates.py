"""Bind an immutable candidate to one intent-only replay or runtime instance."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID

# project library imports
from configuration.capabilities import CapabilitySelection
from configuration.public_data import UniverseSelection
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class CandidateDeployment(WireRecord, frozen=True):
    """Describe placement and input selection without credentials or trading authority.

    This manifest is a local binding, not evidence of installation or activation.
    Modes emit intents only. The independent authorized-trading universe cannot
    be expanded by collection, research or strategy membership.
    """

    name: str
    candidate_identity: str
    instance: str
    entity: str
    mode: Literal["replay", "runtime"]
    input_mode: Literal["source", "offline_features", "online_features"]
    source_identity: str
    starts_at: datetime
    selections: tuple[CapabilitySelection, ...]
    universes: UniverseSelection
    feature_version: str | None = None
    schema_version: Literal["candidate-deployment-v1"] = "candidate-deployment-v1"

    def __post_init__(self) -> None:
        """Reject ambiguous placement, unsupported modes and implicit store versions."""
        if self.schema_version != "candidate-deployment-v1":
            raise ValueError("unsupported candidate deployment schema")
        for value in (self.name, self.instance, self.entity, self.source_identity):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("candidate deployment requires trimmed identities")
        if (
            type(self.candidate_identity) is not str
            or len(self.candidate_identity) != 64
            or any(c not in "0123456789abcdef" for c in self.candidate_identity)
        ):
            raise ValueError("candidate deployment requires a SHA-256 candidate identity")
        self._require_utc(self.starts_at, field_name="starts_at")
        if self.mode not in ("replay", "runtime") or self.input_mode not in (
            "source",
            "offline_features",
            "online_features",
        ):
            raise ValueError("candidate deployment supports intent-only replay/runtime")
        if (self.input_mode == "source") != (self.feature_version is None):
            raise ValueError("feature serving requires an explicit immutable version")
        if self.feature_version is not None and (
            type(self.feature_version) is not str or not self.feature_version.strip()
        ):
            raise ValueError("invalid feature version")
        if self.input_mode == "online_features" and self.mode != "runtime":
            raise ValueError("online latest-value serving cannot impersonate historical replay")
        if type(self.selections) is not tuple or not self.selections:
            raise ValueError("candidate deployment requires capability selections")
        for selection in self.selections:
            selection.__post_init__()
        if len({s.name for s in self.selections}) != len(self.selections):
            raise ValueError("duplicate candidate capability selection")
        self.universes.__post_init__()
        self.universes.require(InstrumentId(UUID(self.entity)), purpose="strategy")
        if self.mode == "replay":
            self.universes.require(InstrumentId(UUID(self.entity)), purpose="research")

    @property
    def identity(self) -> str:
        """Bind candidate, input version, instance and universes to a stable deployment ID."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
