"""Admit bounded duplicate trades with retained occurrences and explicit conflict failures."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.venues.binance.events import Trade
from alpha_research.instrument_identity import InstrumentId
from alpha_research.serialization import DomainCodec

type TradeKey = tuple[str, str, InstrumentId, str, int]


class TradeRevision(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain one economic payload and all exact duplicate lineage before correction support."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    occurrences: tuple[Occurrence, ...]

    def __post_init__(self) -> None:
        """Validate immutable duplicate membership.

        Raises:
            ValueError: A schema or occurrence group is inconsistent.
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
        """Retain the earliest evidenced capture, without substituting archive acquisition.

        Returns:
            UTC capture knowledge, or None for unevidenced archive availability.
        """
        self.__post_init__()
        captures = [
            max(item.event.provenance.ts_knowledge, item.event.provenance.ts_source_received)
            for item in self.occurrences
            if isinstance(item.event, Trade)
            and item.event.provenance.ts_source_received is not None
        ]
        return min(captures) if captures else None

    @classmethod
    def admit(cls, occurrences: Iterable[Occurrence]) -> tuple[TradeRevision, ...]:
        """Admit one immutable envelope per trade and reject conflicting payloads.

        Args:
            occurrences: Complete bounded batch, consumed into local memory.

        Returns:
            Heads sorted by payload identity; repeated identical occurrences are idempotent.

        Raises:
            RevisionConflictError: One economic key has different payloads.
            TypeError: A supplied record is not a supported trade occurrence.
        """
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
        heads: dict[TradeKey, TradeRevision] = {}
        for head in versions.values():
            if head.key in heads:
                raise RevisionConflictError(tuple(versions.values()))
            heads[head.key] = head
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
