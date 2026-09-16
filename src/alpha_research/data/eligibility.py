"""Read retained eligibility assertions and select evidence known at a decision."""

from __future__ import annotations

# standard library imports
import hashlib
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


class EligibilityAssertion(_ReferenceRecord, frozen=True, kw_only=True, omit_defaults=True):
    """Retain one included or excluded assertion over a half-open UTC valid interval."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    instrument_id: InstrumentId
    valid_from: datetime
    valid_to: datetime
    ts_knowledge: datetime
    state: Literal["included", "excluded"]
    reason: str
    evidence: EligibilityEvidence
    supersedes: str | None = None

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
        if self.supersedes is not None and (
            not isinstance(self.supersedes, str)
            or len(self.supersedes) != 64
            or any(character not in "0123456789abcdef" for character in self.supersedes)
        ):
            raise ValueError("supersedes must be a lowercase SHA-256 assertion identity")

    @property
    def identity(self) -> str:
        """Identify all assertion fields, including evidence and correction linkage.

        Returns:
            SHA-256 of the validated canonical assertion encoding.
        """
        self.__post_init__()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()


class EligibilityAssertions(_ReferenceRecord, frozen=True, kw_only=True):
    """Keep all assertions and their exact authored catalog, including excluded members.

    Catalog linkage binds identity and units, not historical truth. Assertion valid
    intervals do not rewrite catalog intervals; exclusions may outlive a listing.
    Contradictory overlaps fail while simultaneously known unless an explicit
    correction retires a predecessor. Empty history never implies membership.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1", "2"] = "1"
    catalog: CatalogSnapshot
    assertions: tuple[EligibilityAssertion, ...]

    def __post_init__(self) -> None:
        """Validate the whole file without pruning history or inferring membership.

        Raises:
            ValueError: Schema, linkage or contradictory overlapping assertions are invalid.
            TypeError: Catalog or assertions have unsafe types.
        """
        if self.schema_version not in ("1", "2"):
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
            previous.append(assertion)
        successors = self._successors()
        for previous in retained.values():
            for index, assertion in enumerate(previous):
                for other in previous[:index]:
                    if (
                        other.state != assertion.state
                        and other.valid_from < assertion.valid_to
                        and assertion.valid_from < other.valid_to
                        and (
                            other.identity not in successors
                            or assertion.ts_knowledge < successors[other.identity].ts_knowledge
                        )
                        and (
                            assertion.identity not in successors
                            or other.ts_knowledge < successors[assertion.identity].ts_knowledge
                        )
                    ):
                        raise ValueError(
                            f"contradictory eligibility overlap: {assertion.instrument_id}"
                        )

    def _successors(self) -> dict[str, EligibilityAssertion]:
        """Validate a linear correction history independent of file ordering."""
        by_identity = {item.identity: item for item in self.assertions}
        successors: dict[str, EligibilityAssertion] = {}
        for assertion in self.assertions:
            if assertion.supersedes is not None:
                if self.schema_version != "2":
                    raise ValueError("eligibility corrections require schema version 2")
                predecessor = by_identity.get(assertion.supersedes)
                if (
                    predecessor is None
                    or predecessor.instrument_id != assertion.instrument_id
                    or predecessor.ts_knowledge >= assertion.ts_knowledge
                    or predecessor.evidence.identity == assertion.evidence.identity
                ):
                    raise ValueError(
                        "correction requires a retained same-member predecessor, "
                        "later knowledge and distinct evidence"
                    )
                if successors.setdefault(assertion.supersedes, assertion) != assertion:
                    raise ValueError("eligibility correction history cannot branch")
        return successors

    def append(self, assertion: EligibilityAssertion) -> EligibilityAssertions:
        """Return a new history retaining every predecessor and its original evidence.

        Args:
            assertion: New membership or an evidenced correction naming its predecessor.

        Returns:
            A validated version-2 history; this history remains unchanged.

        Raises:
            TypeError: An assertion or nested record has an unsafe Python type.
            ValueError: Evidence, correction linkage or active membership conflicts.
        """
        self.__post_init__()
        return EligibilityAssertions(
            schema_version="2", catalog=self.catalog, assertions=(*self.assertions, assertion)
        )

    def select(
        self, instrument_id: InstrumentId, *, valid_at: datetime, known_at: datetime
    ) -> EligibilityAssertion | Literal["unknown", "unsupported"]:
        """Select membership at an independent validity instant and knowledge cutoff.

        Args:
            instrument_id: Canonical member to query in this history's catalog.
            valid_at: UTC instant within the assertion's half-open valid interval.
            known_at: Inclusive UTC decision cutoff; later assertions cannot affect it.

        Returns:
            Included/excluded assertion, unknown when no known active assertion covers
            validity, or unsupported for a member absent from the bound catalog. Among
            agreeing assertions choose latest knowledge, then greatest identity. Catalog
            validity is authored metadata, not an additional membership filter.

        Raises:
            TypeError: The identifier, clocks or history contain unsafe Python values.
            ValueError: A clock is non-UTC or retained history is invalid.
        """
        self.__post_init__()
        if type(instrument_id) is not InstrumentId:
            raise TypeError("eligibility selection requires a canonical InstrumentId")
        self._require_utc(valid_at, field_name="valid_at")
        self._require_utc(known_at, field_name="known_at")
        if instrument_id not in {item.instrument_id for item in self.catalog.instruments}:
            return "unsupported"
        known = tuple(item for item in self.assertions if item.ts_knowledge <= known_at)
        superseded = {item.supersedes for item in known}
        matches = {
            (item.ts_knowledge, item.identity): item
            for item in known
            if item.instrument_id == instrument_id
            and item.identity not in superseded
            and item.valid_from <= valid_at < item.valid_to
        }
        return matches[max(matches)] if matches else "unknown"

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
