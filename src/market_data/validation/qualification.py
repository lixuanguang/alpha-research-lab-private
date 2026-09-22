"""Admit bounded archive histories against retained, externally reviewed provider records."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from market_data.contracts import ArchiveAvailability, ArchiveTrade, SourceRequest
from market_data.validation.revisions import TradeRevision
from reference_data.eligibility import EligibilityAssertions
from serialization import DomainCodec, WireRecord


class ProviderDocument(WireRecord, frozen=True, kw_only=True):
    """Retain provider bytes and retrieval provenance independently of historical facts.

    A digest checks integrity, not authenticity or the truth of a provider's claims.
    Publication and retrieval clocks describe this document, not trade availability.
    Retrospective audit records may substantiate earlier facts after human review.
    """

    sha256: str
    issuer: str
    reference: str
    published_at: datetime
    received_at: datetime
    payload: bytes

    def __post_init__(self) -> None:
        """Reject altered bytes, missing provenance and impossible document clocks.

        Raises:
            ValueError: Content, provenance, size or clock ordering is invalid.
        """
        for value in (self.issuer, self.reference):
            EvidenceCitation._text(value)
        self._require_utc(self.published_at, field_name="document publication")
        self._require_utc(self.received_at, field_name="document receipt")
        if (
            type(self.payload) is not bytes
            or not 0 < len(self.payload) <= 16_777_216
            or hashlib.sha256(self.payload).hexdigest() != self.sha256
            or self.published_at > self.received_at
        ):
            raise ValueError("provider document bytes, digest, size or clocks disagree")


class EvidenceCitation(WireRecord, frozen=True, kw_only=True):
    """Locate the reviewed supporting passage within an immutable provider document."""

    document_sha256: str
    locator: str

    def __post_init__(self) -> None:
        """Reject malformed content references and absent passage locations.

        Raises:
            ValueError: The digest or locator is invalid.
        """
        self._digest(self.document_sha256)
        self._text(self.locator)

    @staticmethod
    def _digest(value: str) -> None:
        """Require an exact lowercase content identity at the evidence boundary."""
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("evidence requires a lowercase SHA-256 identity")

    @staticmethod
    def _text(value: str) -> None:
        """Reject blank, oversized or control-bearing provenance fields."""
        if (
            type(value) is not str
            or not 1 <= len(value) <= 1024
            or value != value.strip()
            or not value.isprintable()
        ):
            raise ValueError("evidence requires a printable trimmed reference")


class TradeAvailability(WireRecord, frozen=True, kw_only=True):
    """Bind every original or corrected economic payload to reviewed availability facts.

    The payload identity covers all archive fields, including quote quantity and
    best-match flag. Availability is when this version could be used on the feed
    specified by the provider record; a local download is not that evidence.
    """

    version_identity: str
    published_at: datetime
    available_at: datetime
    evidence: EvidenceCitation

    def __post_init__(self) -> None:
        """Validate full-payload linkage and independent UTC publication/availability.

        Raises:
            ValueError: A link, citation or historical clock is invalid.
        """
        EvidenceCitation._digest(self.version_identity)
        self._require_utc(self.published_at, field_name="version publication")
        self._require_utc(self.available_at, field_name="version availability")
        if type(self.evidence) is not EvidenceCitation or self.available_at < self.published_at:
            raise ValueError("version requires a citation and availability after publication")
        self.evidence.__post_init__()


class SourceQualification(WireRecord, frozen=True, kw_only=True):
    """Bind reviewed instrument, full-window coverage and exhaustive revision evidence.

    This is an explicit human review trust boundary, not an automatic provider
    certification. The reviewer checks authenticity and that cited passages support
    the exact request/catalog, coverage count, complete history through the stated
    cutoff, and every availability clock. There is no completeness override flag.
    Software rechecks bytes, bindings, inventory, clocks and historical eligibility.
    All supporting original/revised archives must also survive native verification.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    request_identity: str
    archive_sha256s: tuple[str, ...]
    start: datetime
    end: datetime
    history_through: datetime
    trade_count: int
    documents: tuple[ProviderDocument, ...]
    instrument: EvidenceCitation
    coverage: EvidenceCitation
    revision_history: EvidenceCitation
    versions: tuple[TradeAvailability, ...]
    reviewer: str
    review_reference: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        """Validate bounded retained evidence and its review provenance.

        Raises:
            ValueError: Evidence is malformed, incomplete, duplicated or backdated.
        """
        EvidenceCitation._digest(self.request_identity)
        for value in (self.reviewer, self.review_reference):
            EvidenceCitation._text(value)
        for instant in (self.start, self.end, self.history_through, self.reviewed_at):
            self._require_utc(instant, field_name="qualification clock")
        if (
            self.schema_version != "1"
            or not self.start < self.end <= self.history_through <= self.reviewed_at
            or type(self.trade_count) is not int
            or self.trade_count <= 0
            or type(self.archive_sha256s) is not tuple
            or not self.archive_sha256s
            or len(set(self.archive_sha256s)) != len(self.archive_sha256s)
            or type(self.documents) is not tuple
            or not 1 <= len(self.documents) <= 64
            or type(self.versions) is not tuple
            or not self.versions
        ):
            raise ValueError("qualification requires bounded complete evidence and ordered clocks")
        for digest in self.archive_sha256s:
            EvidenceCitation._digest(digest)
        documents: dict[str, ProviderDocument] = {}
        for document in self.documents:
            if type(document) is not ProviderDocument:
                raise ValueError("qualification requires ProviderDocument records")
            document.__post_init__()
            if document.sha256 in documents or document.received_at > self.reviewed_at:
                raise ValueError("provider documents are duplicated or not received by review")
            documents[document.sha256] = document
        identities: set[str] = set()
        citations = [self.instrument, self.coverage, self.revision_history]
        for version in self.versions:
            if type(version) is not TradeAvailability:
                raise ValueError("qualification requires TradeAvailability records")
            version.__post_init__()
            if (
                version.version_identity in identities
                or version.available_at > self.history_through
            ):
                raise ValueError("version inventory is duplicated or exceeds history cutoff")
            identities.add(version.version_identity)
            citations.append(version.evidence)
        for citation in citations:
            if type(citation) is not EvidenceCitation:
                raise ValueError("qualification requires EvidenceCitation records")
            citation.__post_init__()
            if citation.document_sha256 not in documents:
                raise ValueError("cited provider document is not retained")
        if (
            documents[self.coverage.document_sha256].published_at < self.end
            or documents[self.revision_history.document_sha256].published_at < self.history_through
        ):
            raise ValueError("provider coverage/history record cannot certify a future interval")

    @property
    def identity(self) -> str:
        """Identify the retained documents, facts and external review without local paths.

        Returns:
            SHA-256 of the complete validated qualification bundle.
        """
        self.__post_init__()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()

    @classmethod
    def read(cls, path: Path, *, max_bytes: int) -> SourceQualification:
        """Read one explicit bounded reviewed bundle without fetching provider records.

        Args:
            path: Saved JSON containing documents and reviewed fact extraction.
            max_bytes: Positive serialized byte limit, including embedded document bytes.

        Returns:
            Validated evidence; admission still requires the selected raw data and eligibility.

        Raises:
            ValueError: The file, size limit or evidence contract is invalid.
            OSError: The file is absent or unreadable.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("qualification max_bytes must be a positive integer")
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("qualification exceeds max_bytes")
        return cls._codec.decode_json(payload, cls)

    def qualify(
        self,
        request: SourceRequest,
        heads: tuple[TradeRevision, ...],
        eligibility: EligibilityAssertions,
    ) -> tuple[TradeRevision, ...]:
        """Match the complete native-verified history before assigning evidenced knowledge.

        Args:
            request: Exact source, units, instrument and selected half-open interval.
            heads: All admitted original/revised payloads, including duplicate lineage.
            eligibility: Full source-backed history; the quality policy checks decision times.

        Returns:
            Rebuilt histories with effective availability, preserving every original clock.
            An independent capture can delay but never accelerate qualified availability.

        Raises:
            ValueError: Bindings, coverage, inventory, eligibility or correction facts disagree.
        """
        identity = self.identity
        if (
            request.identity != self.request_identity
            or (self.start, self.end)
            != (
                max(request.start, request.manifest.job.start),
                min(request.end, request.manifest.job.end),
            )
            or len(heads) != self.trade_count
        ):
            raise ValueError("qualification request, interval or trade count differs from input")
        for assertion in eligibility.assertions:
            if (
                assertion.instrument_id == request.instrument.instrument_id
                and (assertion.valid_from < self.end and self.start < assertion.valid_to)
                and (
                    assertion.evidence.basis != "source_evidence"
                    or assertion.evidence.identity != self.instrument.document_sha256
                    or assertion.evidence.recorded_at > self.reviewed_at
                )
            ):
                raise ValueError("historical eligibility requires retained provider documents")
        facts = {version.version_identity: version for version in self.versions}
        used: set[str] = set()
        archives: set[str] = set()
        result: list[TradeRevision] = []
        for head in heads:
            chain: list[TradeRevision] = []
            current: TradeRevision | None = head
            while current is not None:
                chain.append(current)
                current = current.previous
            for version in reversed(chain):
                fact = facts.get(version.identity)
                if fact is None or version.identity in used:
                    raise ValueError("provider version inventory differs from retained history")
                used.add(version.identity)
                archives.update(item.origin.sha256 for item in version.occurrences)
                event = version.occurrences[0].event
                if not isinstance(event, ArchiveTrade) or fact.published_at < event.ts_event:
                    raise ValueError("qualified archive publication precedes its event time")
                correction = version.correction
                if correction is not None and (
                    correction.ts_published != fact.published_at
                    or correction.ts_available != fact.available_at
                    or correction.evidence_reference != fact.evidence.document_sha256
                ):
                    raise ValueError("correction linkage differs from provider version evidence")
                if (
                    current is not None
                    and current.ts_knowledge is not None
                    and (fact.available_at < current.ts_knowledge)
                ):
                    raise ValueError("qualified version availability regresses")
                available_at = fact.available_at
                if isinstance(version.availability, ArchiveAvailability):
                    available_at = max(available_at, version.availability.available_at)
                current = replace(
                    version,
                    previous=current,
                    availability=ArchiveAvailability(
                        evidence_identity=identity, available_at=available_at
                    ),
                )
            if current is not None:
                result.append(current)
        if used != facts.keys() or archives != set(self.archive_sha256s):
            raise ValueError("provider version/archive inventory differs from retained history")
        return tuple(result)
