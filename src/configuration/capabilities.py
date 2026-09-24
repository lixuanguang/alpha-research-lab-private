"""Resolve named candidate requirements against installed capability profiles."""

from __future__ import annotations

# standard library imports
import re
from typing import Literal

# project library imports
from serialization import WireRecord

type CapabilityKind = Literal[
    "market_data", "reference_data", "calendar", "valuation", "account", "execution"
]
type CapabilityQualification = Literal["fixture", "read_only", "external"]


class CapabilityField(WireRecord, frozen=True, kw_only=True):
    """Name one field with its units; matching never converts values implicitly."""

    name: str
    units: str

    def __post_init__(self) -> None:
        """Require an explicit name and unit expression."""
        for value in (self.name, self.units):
            if type(value) is not str or not value.strip() or len(value) > 128:
                raise ValueError("capability field requires a name and units")


class CapabilityRequirement(WireRecord, frozen=True, kw_only=True):
    """Declare one logical input or service without choosing an environment adapter."""

    name: str
    kind: CapabilityKind
    product: str
    venue: str
    calendar: str
    channel: str | None = None
    representation: str | None = None
    depth: int | None = None
    clock: str | None = None
    max_freshness_us: int | None = None
    fields: tuple[CapabilityField, ...] = ()
    operations: tuple[str, ...] = ()
    order_types: tuple[str, ...] = ()
    lifecycle: tuple[str, ...] = ()
    qualification: CapabilityQualification | None = None

    def __post_init__(self) -> None:
        """Refuse malformed or ambiguous signatures before adapter selection."""
        if self.kind not in (
            "market_data",
            "reference_data",
            "calendar",
            "valuation",
            "account",
            "execution",
        ):
            raise ValueError("unsupported capability kind")
        for value in (self.name, self.product, self.venue, self.calendar):
            self._require_name(value)
        for optional_value in (self.channel, self.representation, self.clock):
            if optional_value is not None:
                self._require_name(optional_value)
        if self.depth is not None and (type(self.depth) is not int or self.depth <= 0):
            raise ValueError("capability depth must be a positive integer")
        if self.max_freshness_us is not None and (
            type(self.max_freshness_us) is not int or self.max_freshness_us < 0
        ):
            raise ValueError("capability freshness must be nonnegative integer microseconds")
        self._require_fields(self.fields)
        for values in (self.operations, self.order_types, self.lifecycle):
            self._require_names(values)
        if self.qualification is not None and self.qualification not in (
            "fixture",
            "read_only",
            "external",
        ):
            raise ValueError("unsupported capability qualification")

    @staticmethod
    def _require_name(value: object) -> None:
        """Keep capability identifiers short, printable and stable in manifests."""
        if (
            type(value) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value) is None
        ):
            raise ValueError("invalid capability name")

    @classmethod
    def _require_names(cls, values: tuple[str, ...], *, required: bool = False) -> None:
        """Require immutable unique names, including nonempty scope axes."""
        if type(values) is not tuple or (required and not values):
            raise ValueError("capability names require a nonempty tuple")
        for value in values:
            cls._require_name(value)
        if len(set(values)) != len(values):
            raise ValueError("duplicate capability name")

    @staticmethod
    def _require_fields(fields: tuple[CapabilityField, ...]) -> None:
        """Keep field signatures immutable and unambiguous by field name."""
        if type(fields) is not tuple:
            raise ValueError("capability fields require a tuple")
        names: set[str] = set()
        for field in fields:
            if type(field) is not CapabilityField:
                raise ValueError("invalid capability field")
            field.__post_init__()
            if field.name in names:
                raise ValueError("duplicate capability field")
            names.add(field.name)


class CapabilityProfile(WireRecord, frozen=True, kw_only=True):
    """Describe one installed implementation's supported and qualified envelope.

    The composing application supplies these declarations from bound components.
    A declaration or successful match never grants account or order authority.
    """

    name: str
    kind: CapabilityKind
    implementation_identity: str
    version: str
    products: tuple[str, ...]
    venues: tuple[str, ...]
    calendars: tuple[str, ...]
    modes: tuple[str, ...]
    channels: tuple[str, ...] = ()
    representations: tuple[str, ...] = ()
    max_depth: int | None = None
    clocks: tuple[str, ...] = ()
    max_freshness_us: int | None = None
    fields: tuple[CapabilityField, ...] = ()
    operations: tuple[str, ...] = ()
    order_types: tuple[str, ...] = ()
    lifecycle: tuple[str, ...] = ()
    qualification: CapabilityQualification = "fixture"
    evidence_reference: str | None = None

    def __post_init__(self) -> None:
        """Reject unknown support and unsupported qualification claims."""
        if self.kind not in (
            "market_data",
            "reference_data",
            "calendar",
            "valuation",
            "account",
            "execution",
        ):
            raise ValueError("unsupported capability kind")
        for value in (self.name, self.implementation_identity, self.version):
            CapabilityRequirement._require_name(value)
        for values in (
            self.products,
            self.venues,
            self.calendars,
            self.modes,
        ):
            CapabilityRequirement._require_names(values, required=True)
        for values in (
            self.channels,
            self.representations,
            self.clocks,
            self.operations,
            self.order_types,
            self.lifecycle,
        ):
            CapabilityRequirement._require_names(values)
        CapabilityRequirement._require_fields(self.fields)
        if self.max_depth is not None and (type(self.max_depth) is not int or self.max_depth <= 0):
            raise ValueError("capability depth must be a positive integer")
        if self.max_freshness_us is not None and (
            type(self.max_freshness_us) is not int or self.max_freshness_us < 0
        ):
            raise ValueError("capability freshness must be nonnegative integer microseconds")
        if self.qualification not in ("fixture", "read_only", "external"):
            raise ValueError("unsupported capability qualification")
        if self.evidence_reference is not None and (
            type(self.evidence_reference) is not str
            or not self.evidence_reference.strip()
            or len(self.evidence_reference) > 256
        ):
            raise ValueError("invalid capability evidence reference")
        if self.qualification == "external" and self.evidence_reference is None:
            raise ValueError("external capability requires evidence reference")


class CapabilitySelection(WireRecord, frozen=True, kw_only=True):
    """Bind one logical requirement to one installed profile for a workflow."""

    name: str
    profile: str

    def __post_init__(self) -> None:
        """Reject absent or malformed selection names."""
        CapabilityRequirement._require_name(self.name)
        CapabilityRequirement._require_name(self.profile)


class CapabilityBinding(WireRecord, frozen=True, kw_only=True):
    """Retain a checked requirement, selected profile and workflow mode."""

    requirement: CapabilityRequirement
    profile: CapabilityProfile
    mode: str

    def __post_init__(self) -> None:
        """Enforce the full signature even after an unsafe record replacement."""
        if type(self.requirement) is not CapabilityRequirement:
            raise ValueError("binding requires a capability requirement")
        if type(self.profile) is not CapabilityProfile:
            raise ValueError("binding requires a capability profile")
        self.requirement.__post_init__()
        self.profile.__post_init__()
        CapabilityRequirement._require_name(self.mode)
        requirement = self.requirement
        profile = self.profile
        if (
            requirement.kind != profile.kind
            or requirement.product not in profile.products
            or requirement.venue not in profile.venues
            or requirement.calendar not in profile.calendars
            or self.mode not in profile.modes
            or (requirement.channel is not None and requirement.channel not in profile.channels)
            or (
                requirement.representation is not None
                and requirement.representation not in profile.representations
            )
            or (requirement.clock is not None and requirement.clock not in profile.clocks)
            or (
                requirement.depth is not None
                and (profile.max_depth is None or profile.max_depth < requirement.depth)
            )
            or (
                requirement.max_freshness_us is not None
                and (
                    profile.max_freshness_us is None
                    or profile.max_freshness_us > requirement.max_freshness_us
                )
            )
            or (
                requirement.qualification is not None
                and requirement.qualification != profile.qualification
            )
        ):
            raise ValueError(f"incompatible capability profile: {requirement.name}")
        if not set(requirement.fields).issubset(profile.fields):
            raise ValueError(f"capability field or units unavailable: {requirement.name}")
        for expected, available in (
            (requirement.operations, profile.operations),
            (requirement.order_types, profile.order_types),
            (requirement.lifecycle, profile.lifecycle),
        ):
            if not set(expected).issubset(available):
                raise ValueError(f"capability operation unavailable: {requirement.name}")


class CapabilityRegistry:
    """Resolve complete named selections against environment-owned profiles."""

    def __init__(self, profiles: tuple[CapabilityProfile, ...]) -> None:
        """Pin a validated immutable installed profile set with unique names."""
        if type(profiles) is not tuple:
            raise ValueError("capability profiles require a tuple")
        names: set[str] = set()
        for profile in profiles:
            if type(profile) is not CapabilityProfile:
                raise ValueError("invalid capability profile")
            profile.__post_init__()
            if profile.name in names:
                raise ValueError("duplicate capability profile")
            names.add(profile.name)
        self._profiles = profiles

    @property
    def profiles(self) -> tuple[CapabilityProfile, ...]:
        """Expose the exact immutable profiles admitted during composition."""
        return self._profiles

    def resolve(
        self,
        requirements: tuple[CapabilityRequirement, ...],
        selections: tuple[CapabilitySelection, ...],
        *,
        mode: str,
    ) -> tuple[CapabilityBinding, ...]:
        """Reject missing, extra, unknown or incompatible choices before work begins."""
        CapabilityRequirement._require_name(mode)
        if type(requirements) is not tuple or type(selections) is not tuple:
            raise ValueError("capability resolution requires immutable tuples")
        required: dict[str, CapabilityRequirement] = {}
        for requirement in requirements:
            if type(requirement) is not CapabilityRequirement:
                raise ValueError("invalid capability requirement")
            requirement.__post_init__()
            if requirement.name in required:
                raise ValueError("duplicate capability requirement")
            required[requirement.name] = requirement
        selected: dict[str, CapabilitySelection] = {}
        for selection in selections:
            if type(selection) is not CapabilitySelection:
                raise ValueError("invalid capability selection")
            selection.__post_init__()
            if selection.name in selected:
                raise ValueError("duplicate capability selection")
            selected[selection.name] = selection
        if required.keys() != selected.keys():
            raise ValueError("missing or extra capability selection")
        profiles = {profile.name: profile for profile in self._profiles}
        bindings: list[CapabilityBinding] = []
        for requirement in requirements:
            profile_name = selected[requirement.name].profile
            profile = profiles.get(profile_name)
            if profile is None:
                raise ValueError(f"unknown capability profile: {profile_name}")
            bindings.append(CapabilityBinding(requirement=requirement, profile=profile, mode=mode))
        return tuple(bindings)
