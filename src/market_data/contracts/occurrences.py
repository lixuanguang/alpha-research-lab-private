"""Bind canonical observations to exact raw occurrences and their affected input scope."""

from __future__ import annotations

# standard library imports
import hashlib
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from market_data.contracts.archive_trades import ArchiveTrade
from market_data.contracts.binance import Trade
from market_data.contracts.events import Disconnect, MarketEventRecord
from market_data.contracts.raw import RawObject
from market_data.contracts.requests import SourceRequest
from serialization import DomainCodec


class Occurrence(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain a source message and decoded record without asserting economic uniqueness.

    The request binds source, instrument subscription, partition and selected universe.
    A Disconnect affects that binding even though its own instrument is null. These
    file inputs have no live session identity. Position is the zero-based source row
    or line; record_index distinguishes records sharing a source message. Raw bytes
    include their original terminator. No source message or capture text is rewritten.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    request: SourceRequest
    origin: RawObject
    position: int
    raw: bytes
    event: ArchiveTrade | Trade | Disconnect
    record_index: int = 0

    def __post_init__(self) -> None:
        """Reject foreign bindings, unselected instruments and inconsistent source lineage.

        Raises:
            ValueError: Schema, raw binding, position or event lineage is invalid.
            TypeError: A supplied event or domain field has an incompatible type.
        """
        if (
            self.schema_version != "1"
            or type(self.request) is not SourceRequest
            or type(self.origin) is not RawObject
        ):
            raise ValueError("occurrence requires version 1, a request and raw origin")
        self.origin.__post_init__()
        if self.origin.request_identity != self.request.identity:
            raise ValueError("occurrence raw origin differs from request binding")
        for name, value in (("position", self.position), ("record_index", self.record_index)):
            MarketEventRecord._require_int(value, field_name=name)
        if type(self.raw) is not bytes or not self.raw:
            raise ValueError("occurrence requires original source bytes")
        event, instrument = self.event, self.request.instrument
        if isinstance(event, ArchiveTrade):
            event.__post_init__()
            if self.request.manifest.job.provider != "binance-archive":
                raise ValueError("archive event requires an archive binding")
            if not self.request.start <= event.ts_event < self.request.end:
                raise ValueError("archive event outside request partition")
        elif isinstance(event, (Trade, Disconnect)):
            event.validate()
            provenance = event.provenance
            if self.request.manifest.job.provider != "tardis" or (
                provenance.source_id,
                provenance.source_digest,
                provenance.source_sequence,
                provenance.ts_received,
                provenance.ts_ingested,
            ) != (
                instrument.source,
                self.origin.sha256,
                self.position,
                self.origin.ts_received,
                self.origin.ts_ingested,
            ):
                raise ValueError("captured event differs from occurrence source lineage")
            if self.raw.decode("utf-8").removesuffix("\n").removesuffix("\r") != event.raw_line:
                raise ValueError("captured event differs from original source line")
            capture = provenance.ts_source_received
            if (
                capture is None
                or not self.request.start <= capture <= self.request.end
                or (capture == self.request.end and not isinstance(event, Disconnect))
            ):
                raise ValueError("captured event outside request partition")
        else:
            raise TypeError("occurrence requires an archive trade, captured trade or disconnect")
        if not isinstance(event, Disconnect) and (event.instrument_id, event.symbol) != (
            instrument.instrument_id,
            instrument.symbol,
        ):
            raise ValueError("occurrence event instrument differs from selected binding")

    @property
    def message_identity(self) -> str:
        """Identify one original message independently of its decoded record count.

        Returns:
            SHA-256 of request binding, raw digest and zero-based source position.
        """
        self.__post_init__()
        return hashlib.sha256(
            self._codec.encode_json(
                (
                    self.schema_version,
                    self.origin.request_identity,
                    self.origin.sha256,
                    self.position,
                )
            )
        ).hexdigest()

    @property
    def identity(self) -> str:
        """Identify a decoded occurrence independently of trade ID or rebuild attempt.

        Returns:
            SHA-256 of the original message identity and its decoded record index.
        """
        return hashlib.sha256(
            self._codec.encode_json((self.message_identity, self.record_index))
        ).hexdigest()
