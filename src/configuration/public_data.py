"""Resolve explicit public data jobs, adapter requirements and independent universes."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from reference_data.catalogs import InstrumentDefinition
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class UniverseSelection(WireRecord, frozen=True, kw_only=True):
    """Pin four independent memberships; data/research selection never grants authority."""

    collection: tuple[InstrumentId, ...]
    research: tuple[InstrumentId, ...]
    strategy: tuple[InstrumentId, ...]
    authorized_trading: tuple[InstrumentId, ...]
    authorization_reference: str | None = None

    @classmethod
    def read(cls, path: Path) -> UniverseSelection:
        """Read an explicit scope file under the same one-MiB configuration bound."""
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("universe configuration exceeds one MiB")
        return DomainCodec().decode_json(payload, cls)

    def __post_init__(self) -> None:
        """Reject duplicate members and authority without an explicit external reference."""
        for members in (self.collection, self.research, self.strategy, self.authorized_trading):
            if (
                type(members) is not tuple
                or len(members) > 32
                or any(type(i) is not InstrumentId for i in members)
            ):
                raise ValueError("universes require at most 32 canonical instrument IDs")
            if len(set(members)) != len(members):
                raise ValueError("duplicate universe member")
        if self.authorized_trading and not self.authorization_reference:
            raise ValueError("trading membership requires separate authorization evidence")
        if self.authorization_reference is not None and (
            type(self.authorization_reference) is not str
            or not self.authorization_reference.strip()
            or len(self.authorization_reference) > 256
        ):
            raise ValueError("invalid authorization reference")

    def require(
        self,
        instrument_id: InstrumentId,
        purpose: Literal["collection", "research", "strategy", "authorized_trading"],
    ) -> None:
        """Enforce one explicit scope without inheriting membership from another universe.

        An authorized-trading match is necessary configuration evidence only. The
        future independent runtime/risk authority checks remain mandatory.
        """
        self.__post_init__()
        members = {
            "collection": self.collection,
            "research": self.research,
            "strategy": self.strategy,
            "authorized_trading": self.authorized_trading,
        }.get(purpose)
        if members is None or instrument_id not in members:
            raise ValueError(f"instrument is outside the {purpose} universe")


class DataCapability(WireRecord, frozen=True, kw_only=True):
    """Declare installed product/channel, reference, calendar and recovery semantics."""

    adapter: str
    version: str
    venue: str
    product: str
    channel: str
    representation: Literal["trades", "L2", "L3", "reference"]
    modes: tuple[Literal["backfill", "capture", "replay"], ...]
    depth: int | None
    source_clock: Literal["milliseconds", "iso8601", "unknown"]
    sequence: Literal["linked", "consecutive", "trade_id", "unknown"]
    reference: Literal["observed", "historical", "none"]
    calendar: str
    recovery: str

    def __post_init__(self) -> None:
        """Reject unsupported record shapes without declaring unavailable capabilities."""
        for value in (
            self.adapter,
            self.version,
            self.venue,
            self.product,
            self.channel,
            self.calendar,
            self.recovery,
        ):
            if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) is None:
                raise ValueError("invalid capability identity")
        if (
            self.representation not in ("trades", "L2", "L3", "reference")
            or type(self.modes) is not tuple
            or not self.modes
            or len(set(self.modes)) != len(self.modes)
            or any(mode not in ("backfill", "capture", "replay") for mode in self.modes)
            or self.source_clock not in ("milliseconds", "iso8601", "unknown")
            or self.sequence not in ("linked", "consecutive", "trade_id", "unknown")
            or self.reference not in ("observed", "historical", "none")
            or (self.depth is not None and (type(self.depth) is not int or self.depth <= 0))
        ):
            raise ValueError("invalid data capability")

    def admit(
        self,
        instrument: InstrumentDefinition,
        *,
        channel: str,
        mode: str,
        historical_reference: bool = False,
    ) -> None:
        """Reject incompatible inputs before transport, storage or consumer effects."""
        self.__post_init__()
        instrument.__post_init__()
        if (
            (instrument.venue, instrument.product, instrument.calendar)
            != (self.venue, self.product, self.calendar)
            or channel != self.channel
            or mode not in self.modes
            or (historical_reference and self.reference != "historical")
        ):
            raise ValueError("input requires unsupported market/reference/calendar capabilities")


class PublicDataJob(WireRecord, frozen=True, kw_only=True):
    """Select bounded public trade backfill or repeated recent-trade polling.

    Backfill uses a half-open UTC event interval; capture polls within that wall
    interval and retains actual receipt clocks. Neither mode promises exhaustive
    venue history. All definitions and all four memberships are pinned in the job.
    """

    schema_version: Literal["public-data-job"] = "public-data-job"
    name: str
    instruments: tuple[InstrumentDefinition, ...]
    universes: UniverseSelection
    mode: Literal["backfill", "capture"]
    start: datetime
    end: datetime
    page_size: int
    max_pages: int
    max_bytes: int
    timeout_seconds: int
    poll_seconds: int
    rights_reference: str

    def __post_init__(self) -> None:
        """Resolve selected definitions and hard budgets without importing source adapters."""
        if self.schema_version != "public-data-job" or self.mode not in ("backfill", "capture"):
            raise ValueError("unsupported public data job")
        if type(self.name) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) is None:
            raise ValueError("invalid public job name")
        self._require_utc(self.start, field_name="start")
        self._require_utc(self.end, field_name="end")
        if self.start >= self.end or (self.end - self.start).total_seconds() > 86400:
            raise ValueError("public job requires a nonempty interval of at most one day")
        if self.start.microsecond % 1000 or self.end.microsecond % 1000:
            raise ValueError("public trade intervals require millisecond alignment")
        if type(self.universes) is not UniverseSelection:
            raise ValueError("job requires independent universes")
        self.universes.__post_init__()
        if type(self.instruments) is not tuple or not 1 <= len(self.instruments) <= 32:
            raise ValueError("job requires bounded instrument definitions")
        for instrument in self.instruments:
            if type(instrument) is not InstrumentDefinition:
                raise ValueError("invalid instrument definition")
            instrument.__post_init__()
        ids = tuple(i.instrument_id for i in self.instruments)
        native = tuple((i.venue, i.symbol) for i in self.instruments)
        if len(set(ids)) != len(ids) or len(set(native)) != len(native):
            raise ValueError("duplicate instrument or native mapping")
        if not self.universes.collection or any(
            i not in ids
            for members in (
                self.universes.collection,
                self.universes.research,
                self.universes.strategy,
                self.universes.authorized_trading,
            )
            for i in members
        ):
            raise ValueError("universe contains undefined instrument")
        for value, lower, upper in (
            (self.page_size, 1, 10000),
            (self.max_pages, 1, 10000),
            (self.max_bytes, 1024, 100_000_000),
            (self.timeout_seconds, 1, 60),
            (self.poll_seconds, 5, 3600),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("invalid public data resource budget")
        if (
            type(self.rights_reference) is not str
            or not self.rights_reference.strip()
            or len(self.rights_reference) > 256
        ):
            raise ValueError("public data access/use/retention reference required")

    @property
    def identity(self) -> str:
        """Pin definitions, memberships, interval, limits and permitted-use reference."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def read(cls, path: Path) -> PublicDataJob:
        """Read strict configuration under a one-MiB bound; unknown fields fail."""
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("public data config exceeds one MiB")
        return DomainCodec().decode_json(payload, cls)
