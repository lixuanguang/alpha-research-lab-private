"""Admit bounded trade histories with retained occurrences and evidenced correction links."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from market_data.contracts import ArchiveAvailability, ArchiveTrade, Occurrence, Trade
from reference_data.instruments import InstrumentId
from serialization import DomainCodec

type TradeKey = tuple[str, str, InstrumentId, str, int]


class Correction(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind two payload identities to explicit publication and usable-availability evidence.

    The reference identifies retained non-secret evidence, not a URL to fetch. UTC
    availability cannot precede publication. An authored synthetic assertion proves
    software behavior only; archive acquisition time is not correction evidence.
    """

    supersedes: str
    replacement: str
    ts_published: datetime
    ts_available: datetime
    evidence_reference: str

    def __post_init__(self) -> None:
        """Reject malformed links, missing evidence and invalid correction clocks.

        Raises:
            ValueError: Identities, evidence or UTC publication/availability are invalid.
        """
        for identity in (self.supersedes, self.replacement):
            if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
                raise ValueError("correction links must be lowercase SHA-256 identities")
        reference = self.evidence_reference
        if (
            not isinstance(reference, str)
            or not 1 <= len(reference) <= 256
            or reference != reference.strip()
            or not reference.isprintable()
        ):
            raise ValueError("correction requires a printable trimmed evidence reference")
        for instant in (self.ts_published, self.ts_available):
            if not isinstance(instant, datetime) or instant.utcoffset() != timedelta(0):
                raise ValueError("correction clocks must be timezone-aware UTC")
        if self.supersedes == self.replacement or self.ts_available < self.ts_published:
            raise ValueError("correction must change payload and be available after publication")


class TradeRevision(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain one economic version, every duplicate lineage and its immutable predecessor.

    One admitted head contributes once per TradeKey; previous envelopes preserve
    earlier versions. Consumers must use ts_knowledge here, not the embedded event's
    uncorrected clock. Missing archive knowledge stays unknown on the original;
    explicit correction evidence can establish availability of the corrected version.
    Serialize the complete head through a reused DomainCodec, including its history.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    occurrences: tuple[Occurrence, ...]
    availability: ArchiveAvailability | None = None
    previous: TradeRevision | None = None
    correction: Correction | None = None

    def __post_init__(self) -> None:
        """Validate duplicate membership and the complete ordered correction chain.

        Raises:
            ValueError: A schema, occurrence group or evidenced predecessor is inconsistent.
            TypeError: A record is not a supported trade occurrence.
        """
        if (
            self.schema_version != "1"
            or type(self.occurrences) is not tuple
            or not self.occurrences
        ):
            raise ValueError("revision requires version 1 and nonempty immutable occurrences")
        signatures = {self._signature(item) for item in self.occurrences}
        if len(signatures) != 1:
            raise ValueError("revision occurrences must share an economic key and payload")
        if self.availability is not None:
            if type(self.availability) is not ArchiveAvailability or any(
                not isinstance(item.event, ArchiveTrade) for item in self.occurrences
            ):
                raise ValueError("external availability requires archive occurrences")
            self.availability.__post_init__()
        if self.previous is None and self.correction is None:
            return
        if type(self.previous) is not TradeRevision or type(self.correction) is not Correction:
            raise ValueError("revision requires both predecessor and correction evidence")
        self.previous.__post_init__()
        self.correction.__post_init__()
        if self.key != self.previous.key or (
            self.correction.supersedes,
            self.correction.replacement,
        ) != (self.previous.identity, self.identity):
            raise ValueError("correction does not link these economic versions")
        earlier = self.previous.correction
        if earlier is not None and (
            self.correction.ts_published < earlier.ts_published
            or self.correction.ts_available < earlier.ts_available
        ):
            raise ValueError("correction publication and availability must follow predecessor")
        ancestor: TradeRevision | None = self.previous
        while ancestor is not None:
            if ancestor.identity == self.identity:
                raise ValueError(
                    "cyclic payload revisions require distinct source revision evidence"
                )
            ancestor = ancestor.previous

    @staticmethod
    def _signature(item: Occurrence) -> tuple[TradeKey, tuple[object, ...]]:
        """Exclude positional lineage while retaining every selected economic payload field."""
        if type(item) is not Occurrence:
            raise TypeError("revision requires an Occurrence")
        item.__post_init__()
        event, job = item.event, item.request.manifest.job
        if not isinstance(event, (ArchiveTrade, Trade)) or job.stream != "trade":
            raise TypeError("revision admission supports individual trades only")
        key = (
            item.request.instrument.source,
            job.venue,
            event.instrument_id,
            job.stream,
            event.trade_id,
        )
        detail = (
            (
                event.timestamp,
                event.timestamp_unit,
                event.quote_quantity.as_integer_ratio(),
                event.is_best_match,
            )
            if isinstance(event, ArchiveTrade)
            else (event.provenance.ts_event,)
        )
        return key, (
            event.event_type,
            event.price.as_integer_ratio(),
            event.quantity.as_integer_ratio(),
            event.is_buyer_maker,
            detail,
        )

    @property
    def key(self) -> TradeKey:
        """Identify source, venue, instrument, stream and individual trade ID.

        Returns:
            Economic key independent of file positions, partitions and revision payload.
        """
        return self._signature(self.occurrences[0])[0]

    @property
    def identity(self) -> str:
        """Identify the economic payload independently of duplicate count or decimal scale.

        Returns:
            Versioned SHA-256 of the economic key and exact payload, without raw positions.
        """
        return hashlib.sha256(
            self._codec.encode_json(("1", self._signature(self.occurrences[0])))
        ).hexdigest()

    @property
    def ts_knowledge(self) -> datetime | None:
        """Bound usable knowledge by original capture, predecessor and correction availability.

        Returns:
            UTC effective knowledge, or None for an archive version with no evidence.
            Duplicate captures use the earliest evidenced observation; local archive
            receipt is never substituted. Correction boundaries are inclusive.
        """
        self.__post_init__()
        captures = [
            max(item.event.provenance.ts_knowledge, item.event.provenance.ts_source_received)
            for item in self.occurrences
            if isinstance(item.event, Trade)
            and item.event.provenance.ts_source_received is not None
        ]
        bounds = [min(captures)] if captures else []
        if isinstance(self.availability, ArchiveAvailability):
            bounds.append(self.availability.available_at)
        if self.previous is not None and (previous_time := self.previous.ts_knowledge) is not None:
            bounds.append(previous_time)
        if self.correction is not None:
            bounds.append(self.correction.ts_available)
        return max(bounds) if bounds else None

    @classmethod
    def admit(
        cls,
        occurrences: Iterable[Occurrence],
        *,
        policy: Literal["reject", "evidenced"],
        corrections: tuple[Correction, ...],
    ) -> tuple[TradeRevision, ...]:
        """Resolve a complete bounded batch before returning one history head per trade.

        Args:
            occurrences: Validated decoded inputs; consumed completely into local memory.
            policy: Reject conflicts, or admit a linear chain justified by supplied evidence.
            corrections: Explicit links for this batch, with publication and availability.

        Returns:
            Immutable heads sorted by payload identity, retaining all earlier versions.
            Repeated identical occurrences are idempotent; distinct lineage is preserved.

        Raises:
            ValueError: Policy/evidence is invalid, dangling, ambiguous or cyclic.
            RevisionConflictError: Multiple payloads for one trade lack a complete chain.
            TypeError: An occurrence or evidence record has an unsupported type.
        """
        if policy not in ("reject", "evidenced") or type(corrections) is not tuple:
            raise ValueError("admission requires an explicit supported policy and evidence tuple")
        if corrections and policy == "reject":
            raise ValueError("reject policy does not admit corrections")
        groups: dict[tuple[TradeKey, tuple[object, ...]], list[Occurrence]] = {}
        for item in occurrences:
            group = groups.setdefault(cls._signature(item), [])
            if item not in group:
                group.append(item)
        versions = {
            version.identity: version
            for group in groups.values()
            for version in (cls(occurrences=tuple(sorted(group, key=cls._codec.encode_json))),)
        }
        links: dict[str, Correction] = {}
        targets: set[str] = set()
        for evidence in corrections:
            if type(evidence) is not Correction:
                raise TypeError("admission evidence must be a Correction")
            evidence.__post_init__()
            if (
                evidence.supersedes not in versions
                or evidence.replacement not in versions
                or evidence.supersedes in links
                or evidence.replacement in targets
            ):
                raise ValueError("correction links must be present, unique and unbranched")
            links[evidence.supersedes] = evidence
            targets.add(evidence.replacement)
        heads: dict[TradeKey, TradeRevision] = {}
        visited: set[str] = set()
        for identity in sorted(versions.keys() - targets):
            head = versions[identity]
            while True:
                visited.add(head.identity)
                if head.identity not in links:
                    break
                evidence = links[head.identity]
                head = cls(
                    occurrences=versions[evidence.replacement].occurrences,
                    previous=head,
                    correction=evidence,
                )
            if head.key in heads:
                raise RevisionConflictError(tuple(versions.values()))
            heads[head.key] = head
        if len(visited) != len(versions):
            raise ValueError("cyclic correction links cannot establish revision order")
        return tuple(sorted(heads.values(), key=cls._identity))

    @staticmethod
    def _identity(version: TradeRevision) -> str:
        """Order admitted histories independently of input traversal."""
        return version.identity


class RevisionConflictError(ValueError):
    """Retain conflicting payload envelopes and all raw lineage on failed admission."""

    def __init__(self, revisions: tuple[TradeRevision, ...]) -> None:
        """Expose the rejected versions for diagnostics without discarding source bytes.

        Args:
            revisions: Batch versions whose economic conflicts remain unresolved.
        """
        self.revisions = revisions
        super().__init__(
            "unresolved trade revisions: " + ", ".join(item.identity for item in revisions)
        )
