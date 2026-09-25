"""Select independent book sources and explicit economic equivalence assertions."""

from __future__ import annotations

# standard library imports
import hashlib
from typing import Literal

# project library imports
from configuration.capture import CaptureConfig
from configuration.public_data import DataCapability
from financial_units import QuantityKind
from reference_data.catalogs import InstrumentDefinition
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class BookKey(WireRecord, frozen=True):
    """Identify an independent venue listing, never an implicitly fungible market."""

    venue: str
    instrument_id: InstrumentId

    def __post_init__(self) -> None:
        """Require an explicit venue and canonical instrument."""
        if type(self.venue) is not str or not self.venue.strip():
            raise ValueError("book key requires a venue")
        if type(self.instrument_id) is not InstrumentId:
            raise ValueError("book key requires a canonical instrument")
        InstrumentId(self.instrument_id.uuid_value)


class BookSelection(WireRecord, frozen=True):
    """Admit one source/channel per listing with explicit units and age policy.

    Freshness is inclusive and checks original receipt, availability and any
    declared source clock. Degraded visible-book quality requires explicit opt-in;
    it remains degraded in every result and never establishes full coverage.
    """

    instrument: InstrumentDefinition
    source_id: str
    capability: DataCapability
    quantity_unit: QuantityKind
    max_age_ns: int
    allow_degraded: bool

    def __post_init__(self) -> None:
        """Reject untyped, incompatible or unbounded source selections."""
        if (
            type(self.instrument) is not InstrumentDefinition
            or type(self.capability) is not DataCapability
        ):
            raise ValueError("book selection requires reference and capability records")
        self.instrument.__post_init__()
        self.capability.admit(self.instrument, channel=self.capability.channel, mode="replay")
        if self.capability.representation not in ("L2", "L3"):
            raise ValueError("book selection requires a book capability")
        if type(self.source_id) is not str or not self.source_id.strip():
            raise ValueError("book selection requires a source identity")
        if type(self.quantity_unit) is not QuantityKind:
            raise ValueError("book selection requires explicit quantity units")
        if (
            type(self.max_age_ns) is not int
            or self.max_age_ns <= 0
            or type(self.allow_degraded) is not bool
        ):
            raise ValueError(
                "book selection requires positive freshness and explicit quality policy"
            )

    @classmethod
    def from_capture(
        cls,
        config: CaptureConfig,
        *,
        source_id: str,
        capability: DataCapability,
        max_age_ns: int,
        allow_degraded: bool,
    ) -> BookSelection:
        """Bind a spot capture's native reference units to an explicit admitted capability.

        The caller supplies the installed adapter capability and exact recording
        identity. This constructor performs no adapter discovery or activation.
        """
        config.__post_init__()
        capability.admit(
            instrument := InstrumentDefinition(
                instrument_id=config.instrument_id,
                venue=config.venue,
                symbol=config.symbol,
                product="spot",
                base_currency=config.base_currency,
                quote_currency=config.quote_currency,
                calendar="continuous-utc",
            ),
            channel=config.channel,
            mode="replay",
        )
        return cls(
            instrument=instrument,
            source_id=source_id,
            capability=capability,
            quantity_unit=QuantityKind.BASE_UNIT,
            max_age_ns=max_age_ns,
            allow_degraded=allow_degraded,
        )

    @property
    def key(self) -> BookKey:
        """Return the native independent state key."""
        return BookKey(venue=self.instrument.venue, instrument_id=self.instrument.instrument_id)


class BookEquivalence(WireRecord, frozen=True):
    """Assert comparable native units over an explicit known, half-open interval.

    The reference identifies the authored economic assertion, not a symbol-based
    inference. Matching product/base/quote/unit fields is necessary, not evidence
    of fungibility. No FX, contract multiplier or quantity conversion is performed.
    """

    name: str
    reference: str
    members: tuple[BookKey, ...]
    known_ns: int
    valid_from_ns: int
    valid_to_ns: int | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous membership, unnamed assertions and invalid reference clocks."""
        if any(
            type(value) is not str or not value.strip() for value in (self.name, self.reference)
        ):
            raise ValueError("book equivalence requires a name and reference")
        if type(self.members) is not tuple or not self.members:
            raise ValueError("book equivalence requires selected members")
        for member in self.members:
            if type(member) is not BookKey:
                raise ValueError("book equivalence requires typed keys")
            member.__post_init__()
        if len({member.venue for member in self.members}) != len(self.members):
            raise ValueError("book equivalence selects one listing per venue")
        if any(
            type(value) is not int or value < 0 for value in (self.known_ns, self.valid_from_ns)
        ):
            raise ValueError("invalid book reference clocks")
        if self.valid_to_ns is not None and (
            type(self.valid_to_ns) is not int or self.valid_to_ns <= self.valid_from_ns
        ):
            raise ValueError("book reference interval must be nonempty")


class BookRegistryConfiguration(WireRecord, frozen=True, kw_only=True):
    """Pin book admission, equivalent markets and a finite per-book history budget."""

    schema_version: Literal["book-registry-v1"] = "book-registry-v1"
    selections: tuple[BookSelection, ...]
    equivalences: tuple[BookEquivalence, ...]
    history_capacity: int

    def __post_init__(self) -> None:
        """Resolve mappings and reject currency, product, asset or unit mismatches."""
        if (
            self.schema_version != "book-registry-v1"
            or type(self.history_capacity) is not int
            or self.history_capacity < 1
        ):
            raise ValueError("invalid book registry schema or history capacity")
        if (
            type(self.selections) is not tuple
            or not self.selections
            or type(self.equivalences) is not tuple
        ):
            raise ValueError("book registry requires immutable selections and mappings")
        selected: dict[BookKey, BookSelection] = {}
        for selection in self.selections:
            if type(selection) is not BookSelection:
                raise ValueError("book registry requires typed selections")
            selection.__post_init__()
            if selection.key in selected:
                raise ValueError("book registry admits one source per book")
            selected[selection.key] = selection
        names: set[str] = set()
        for group in self.equivalences:
            if type(group) is not BookEquivalence:
                raise ValueError("book registry requires typed equivalence mappings")
            group.__post_init__()
            if group.name in names or any(key not in selected for key in group.members):
                raise ValueError("duplicate or unresolved book equivalence")
            names.add(group.name)
            economics = {
                (
                    selected[key].instrument.product,
                    selected[key].instrument.base_currency,
                    selected[key].instrument.quote_currency,
                    selected[key].quantity_unit,
                )
                for key in group.members
            }
            if len(economics) != 1:
                raise ValueError(
                    "book equivalence currency, product, asset or quantity unit mismatch"
                )

    @property
    def identity(self) -> str:
        """Identify the exact reference mapping, source selection and query policy."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
