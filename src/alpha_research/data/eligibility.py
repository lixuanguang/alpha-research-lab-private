"""Read retained eligibility assertions without selecting an as-of universe."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal

# project library imports
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import CatalogSnapshot, _ReferenceRecord
from alpha_research.serialization import DomainCodec


class EligibilityEvidence(_ReferenceRecord, frozen=True, kw_only=True):
    """Identify retained evidence and distinguish authored assumptions from source facts.

    Identity is an explicit retained document/revision reference, not a fetched or
    authenticated source. Synthetic availability is hypothetical. Recording old
    source evidence today does not move its evidenced availability to today.
    """

    identity: str
    basis: Literal["research_assumption", "source_evidence", "synthetic"]
    recorded_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        """Reject missing evidence, unsupported bases and invented assumption dates.

        Raises:
            ValueError: Evidence identity, basis or clock ordering is invalid.
            TypeError: An identity or clock has the wrong type.
        """
        CatalogSnapshot._require_text(self.identity, field_name="evidence identity")
        if len(self.identity) > 256 or not self.identity.isprintable():
            raise ValueError("evidence identity must be printable and at most 256 characters")
        if self.basis not in ("research_assumption", "source_evidence", "synthetic"):
            raise ValueError("unsupported eligibility evidence basis")
        for name, instant in (
            ("recorded_at", self.recorded_at),
            ("available_at", self.available_at),
        ):
            self._require_utc(instant, field_name=name)
        if self.available_at > self.recorded_at:
            raise ValueError("evidence availability cannot follow its recording")
        if self.basis == "research_assumption" and self.available_at != self.recorded_at:
            raise ValueError("research assumption availability must equal its authored recording")


class EligibilityAssertion(_ReferenceRecord, frozen=True, kw_only=True):
    """Retain one included or excluded assertion over a half-open UTC valid interval."""

    instrument_id: InstrumentId
    valid_from: datetime
    valid_to: datetime
    ts_knowledge: datetime
    state: Literal["included", "excluded"]
    reason: str
    evidence: EligibilityEvidence

    def __post_init__(self) -> None:
        """Validate immutable membership and its independent evidence-backed knowledge.

        Raises:
            ValueError: State, reason, interval or knowledge is invalid.
            TypeError: An identifier, evidence record or timestamp has the wrong type.
        """
        if type(self.instrument_id) is not InstrumentId:
            raise TypeError("eligibility requires a canonical InstrumentId")
        if type(self.evidence) is not EligibilityEvidence:
            raise TypeError("eligibility requires an EligibilityEvidence record")
        self.evidence.__post_init__()
        for name, instant in (
            ("valid_from", self.valid_from),
            ("valid_to", self.valid_to),
            ("ts_knowledge", self.ts_knowledge),
        ):
            self._require_utc(instant, field_name=name)
        if self.valid_from >= self.valid_to:
            raise ValueError("eligibility valid interval must be nonempty")
        if self.ts_knowledge < self.evidence.available_at:
            raise ValueError("eligibility knowledge cannot precede evidenced availability")
        if self.state not in ("included", "excluded"):
            raise ValueError("eligibility state must be included or excluded")
        CatalogSnapshot._require_text(self.reason, field_name="eligibility reason")


class EligibilityAssertions(_ReferenceRecord, frozen=True, kw_only=True):
    """Keep all assertions and their exact authored catalog, including excluded members.

    Catalog linkage binds identity and units, not historical truth. Assertion valid
    intervals do not rewrite catalog intervals; exclusions may outlive a listing.
    Contradictory overlaps fail regardless of knowledge order until MR 12 supplies
    explicit correction semantics. Empty history does not imply eligible membership.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    catalog: CatalogSnapshot
    assertions: tuple[EligibilityAssertion, ...]

    def __post_init__(self) -> None:
        """Validate the whole file without pruning history or inferring membership.

        Raises:
            ValueError: Schema, linkage or contradictory overlapping assertions are invalid.
            TypeError: Catalog or assertions have unsafe types.
        """
        if self.schema_version != "1":
            raise ValueError("unsupported eligibility schema version")
        if type(self.catalog) is not CatalogSnapshot or type(self.assertions) is not tuple:
            raise TypeError("eligibility requires a CatalogSnapshot and immutable assertions")
        self.catalog.validate()
        members = {item.instrument_id for item in self.catalog.instruments}
        retained: dict[InstrumentId, list[EligibilityAssertion]] = {}
        evidence_by_identity: dict[str, EligibilityEvidence] = {}
        for assertion in self.assertions:
            if type(assertion) is not EligibilityAssertion:
                raise TypeError("eligibility requires EligibilityAssertion records")
            assertion.__post_init__()
            evidence = assertion.evidence
            if evidence_by_identity.setdefault(evidence.identity, evidence) != evidence:
                raise ValueError("eligibility evidence identity has conflicting metadata")
            if assertion.instrument_id not in members:
                raise ValueError("eligibility instrument is absent from the selected catalog")
            previous = retained.setdefault(assertion.instrument_id, [])
            for other in previous:
                if (
                    other.state != assertion.state
                    and other.valid_from < assertion.valid_to
                    and assertion.valid_from < other.valid_to
                ):
                    raise ValueError(
                        f"contradictory eligibility overlap: {assertion.instrument_id}"
                    )
            previous.append(assertion)

    @classmethod
    def read(cls, path: Path, *, catalog: CatalogSnapshot) -> EligibilityAssertions:
        """Read a bounded strict JSON file tied to the caller's selected catalog/units.

        Args:
            path: Explicit local eligibility file, at most one MiB.
            catalog: Selected authored catalog; its complete identity must match the file.

        Returns:
            All validated assertions in original file order, with evidence and exclusions.

        Raises:
            OSError: The file is missing or unreadable.
            TypeError: The selected catalog has an unsafe Python type.
            ValueError: JSON, schema, evidence, overlap, size or catalog linkage is invalid.
        """
        if type(catalog) is not CatalogSnapshot:
            raise TypeError("selected catalog must be a CatalogSnapshot")
        catalog.validate()
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("eligibility file exceeds one MiB")
        result = cls._codec.decode_json(payload, cls)
        if result.catalog.identity != catalog.identity:
            raise ValueError("eligibility file differs from the selected catalog/units")
        return result
