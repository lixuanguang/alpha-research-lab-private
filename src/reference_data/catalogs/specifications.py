"""Resolve versioned venue facts at independent valid and knowledge times."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

# project library imports
from financial_units import DecimalGrid
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class InstrumentDefinition(WireRecord, frozen=True, kw_only=True):
    """Bind an authored listing to explicit native units without asserting venue history."""

    instrument_id: InstrumentId
    venue: str
    symbol: str
    product: str
    base_currency: str
    quote_currency: str
    calendar: str

    def __post_init__(self) -> None:
        """Require stable identities and explicit product, currency and calendar bindings."""
        if type(self.instrument_id) is not InstrumentId:
            raise ValueError("definition requires a canonical instrument ID")
        for value in (self.venue, self.symbol, self.product, self.calendar):
            if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) is None:
                raise ValueError("invalid instrument definition")
        for currency in (self.base_currency, self.quote_currency):
            if type(currency) is not str or re.fullmatch(r"[A-Z0-9]{2,12}", currency) is None:
                raise ValueError("invalid currency code")
        if self.base_currency == self.quote_currency:
            raise ValueError("base and quote currencies must differ")


class VenueSpecification(WireRecord, frozen=True, kw_only=True):
    """Retain one evidenced assertion; absent increments and historical facts stay unknown.

    Current REST observations start at their actual receipt, never at listing time.
    Revisions supersede only the same listing and valid interval. Quantities use
    base units and prices use quote/base units for the declared spot adapter.
    """

    instrument: InstrumentDefinition
    valid_from: datetime
    valid_to: datetime | None
    ts_knowledge: datetime
    source_digest: str
    basis: Literal["current_observation", "source_history", "synthetic"]
    price_tick: Decimal | None
    quantity_step: Decimal | None
    minimum_quantity: Decimal | None
    status: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous intervals, imprecise amounts and invented observation history."""
        if type(self.instrument) is not InstrumentDefinition:
            raise ValueError("specification requires an instrument definition")
        self.instrument.__post_init__()
        self._require_utc(self.valid_from, field_name="valid_from")
        self._require_utc(self.ts_knowledge, field_name="ts_knowledge")
        if self.valid_to is not None:
            self._require_utc(self.valid_to, field_name="valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("specification interval must be nonempty")
        if self.basis not in ("current_observation", "source_history", "synthetic"):
            raise ValueError("unsupported specification basis")
        if self.basis == "current_observation" and self.valid_from != self.ts_knowledge:
            raise ValueError("current metadata cannot establish historical validity")
        for digest in (self.source_digest, self.supersedes):
            if digest is not None and (
                type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            ):
                raise ValueError("specification requires source/correction digests")
        for amount in (self.price_tick, self.quantity_step, self.minimum_quantity):
            if amount is not None:
                DecimalGrid.require_decimal(amount)
                if amount <= 0:
                    raise ValueError("specification increments must be positive")
        if type(self.status) is not str or not self.status or len(self.status) > 80:
            raise ValueError("specification requires source status")

    @property
    def identity(self) -> str:
        """Identify the entire immutable assertion, including its evidence and clocks."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class ReferenceHistory(WireRecord, frozen=True, kw_only=True):
    """Preserve append-only specifications and resolve only facts known at the cutoff."""

    schema_version: Literal["reference-history-v1"] = "reference-history-v1"
    specifications: tuple[VenueSpecification, ...]

    def __post_init__(self) -> None:
        """Reject duplicate versions, conflicting definitions and invalid correction chains."""
        if self.schema_version != "reference-history-v1" or type(self.specifications) is not tuple:
            raise ValueError("invalid reference history")
        versions: dict[str, VenueSpecification] = {}
        definitions: dict[InstrumentId, InstrumentDefinition] = {}
        successors: set[str] = set()
        for spec in self.specifications:
            if type(spec) is not VenueSpecification:
                raise ValueError("invalid specification record")
            spec.__post_init__()
            if spec.identity in versions:
                raise ValueError("duplicate specification version")
            versions[spec.identity] = spec
            if (
                definitions.setdefault(spec.instrument.instrument_id, spec.instrument)
                != spec.instrument
            ):
                raise ValueError("conflicting instrument definitions")
        for spec in self.specifications:
            if spec.supersedes is not None:
                prior = versions.get(spec.supersedes)
                if (
                    prior is None
                    or prior.instrument != spec.instrument
                    or prior.valid_from != spec.valid_from
                    or prior.valid_to != spec.valid_to
                    or prior.ts_knowledge >= spec.ts_knowledge
                    or spec.supersedes in successors
                ):
                    raise ValueError("invalid or branched specification correction")
                successors.add(spec.supersedes)
        for index, spec in enumerate(self.specifications):
            for other in self.specifications[:index]:
                if (
                    other.instrument.instrument_id == spec.instrument.instrument_id
                    and other.valid_from == spec.valid_from
                    and other.ts_knowledge == spec.ts_knowledge
                ):
                    raise ValueError("ambiguous simultaneous specification assertions")
                if other.instrument == spec.instrument and other.valid_from == spec.valid_from:
                    newer, older = (
                        (spec, other) if spec.ts_knowledge > other.ts_knowledge else (other, spec)
                    )
                    while newer.supersedes is not None and newer.identity != older.identity:
                        newer = versions[newer.supersedes]
                    if newer.identity != older.identity:
                        raise ValueError(
                            "overlapping specification revisions require explicit supersedes"
                        )

    @property
    def identity(self) -> str:
        """Pin retained reference history independently of mutable file names."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def resolve(
        self, instrument_id: InstrumentId, *, valid_at: datetime, known_at: datetime
    ) -> VenueSpecification | None:
        """Return the latest applicable assertion, or explicit unknown history as None.

        Valid intervals are half-open; knowledge cutoffs are inclusive. Later known
        corrections cannot remove a predecessor from an earlier query. Observed
        metadata is an assertion, not proof that the venue made no unseen changes.
        """
        self.__post_init__()
        self._require_utc(valid_at, field_name="valid_at")
        self._require_utc(known_at, field_name="known_at")
        known = tuple(s for s in self.specifications if s.ts_knowledge <= known_at)
        retired = {s.supersedes for s in known}
        candidates = tuple(
            s
            for s in known
            if s.instrument.instrument_id == instrument_id
            and s.identity not in retired
            and s.valid_from <= valid_at
            and (s.valid_to is None or valid_at < s.valid_to)
        )
        return max(candidates, key=self._precedence) if candidates else None

    def require_order(
        self,
        instrument_id: InstrumentId,
        *,
        valid_at: datetime,
        known_at: datetime,
        max_age: timedelta,
    ) -> VenueSpecification:
        """Reject unknown, stale or incomplete spot rules before an order can be validated.

        This resolves reference rules only and grants no trading authority.
        """
        if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
            raise ValueError("order reference freshness must be positive")
        spec = self.resolve(instrument_id, valid_at=valid_at, known_at=known_at)
        if (
            spec is None
            or spec.instrument.product != "spot"
            or spec.status != "live"
            or spec.basis == "synthetic"
            or spec.price_tick is None
            or spec.quantity_step is None
            or spec.minimum_quantity is None
            or valid_at - spec.ts_knowledge > max_age
        ):
            raise ValueError("order specification unknown, stale, incomplete or unsupported")
        return spec

    @staticmethod
    def _precedence(spec: VenueSpecification) -> tuple[datetime, datetime]:
        """Prefer the most recent valid assertion and then its known correction."""
        return spec.valid_from, spec.ts_knowledge
