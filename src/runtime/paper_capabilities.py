"""Declare what the supervised public-paper environment offers one native book source."""

from __future__ import annotations

# project library imports
from configuration import (
    CapabilityField,
    CapabilityKind,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    CaptureConfig,
)
from research.features import FeatureStoreDefinition

_BOOK_FIELDS = (
    CapabilityField(name="imbalance", units="dimensionless"),
    CapabilityField(name="ask", units="quote/base"),
    CapabilityField(name="bid", units="quote/base"),
    CapabilityField(name="ask_size", units="base"),
    CapabilityField(name="bid_size", units="base"),
)
_KINDS: tuple[CapabilityKind, ...] = (
    "market_data",
    "reference_data",
    "calendar",
    "valuation",
    "account",
    "execution",
)


class PaperCapabilities:
    """Profile one native public book, its optional trades, reference data and paper services.

    The installed application declares these profiles from the sources it
    provisions; a candidate's requirements resolve against them before any source
    or account work. A ``trade`` channel requirement resolves only when the source
    records its public trades feed; that profile's freshness is the feed's idle
    bound and its fields carry the feed's own currencies, as trade inputs do. A
    feature-served candidate's inputs resolve against profiles derived from the
    registered feature-store definition that serves it, because the store, not a
    live feed, provides those values. A profile match never grants trading authority.
    """

    def __init__(
        self,
        *,
        venue: str,
        freshness_us: int,
        clocks: tuple[str, ...],
        trades: CaptureConfig | None = None,
        features: FeatureStoreDefinition | None = None,
    ) -> None:
        """Bind the venue, book freshness and clocks, the optional trades feed and store."""
        if type(freshness_us) is not int or freshness_us <= 0 or not clocks:
            raise ValueError("paper capabilities require positive freshness and source clocks")
        if trades is not None and (trades.channel != "trades" or trades.venue != venue):
            raise ValueError("paper capabilities require this venue's trades feed")
        self.venue, self.freshness_us, self.clocks = venue, freshness_us, clocks
        self.trades = trades
        self.features = features

    def registry(self) -> CapabilityRegistry:
        """Return one installed profile per capability family and provisioned feed."""
        profiles = tuple(self._profile(kind) for kind in _KINDS)
        if self.trades is not None:
            profiles += (self._trades(self.trades),)
        if self.features is not None:
            profiles += self._served(self.features)
        return CapabilityRegistry(profiles)

    def selections(
        self,
        requirements: tuple[CapabilityRequirement, ...],
        served: frozenset[str] = frozenset(),
    ) -> tuple[CapabilitySelection, ...]:
        """Select this environment's profile of the same family and feed for each requirement.

        Requirements named in ``served`` are the store-served candidate's inputs.
        """
        return tuple(
            CapabilitySelection(
                name=item.name,
                profile=(
                    f"paper-served-{item.kind.replace('_', '-')}"
                    if item.name in served
                    else "paper-market-trades"
                    if item.kind == "market_data" and item.channel == "trade"
                    else self._name(item.kind)
                ),
            )
            for item in requirements
        )

    def _served(self, definition: FeatureStoreDefinition) -> tuple[CapabilityProfile, ...]:
        """Describe the store-served inputs of one registered definition, per family kind."""
        profiles: tuple[CapabilityProfile, ...] = ()
        kinds: tuple[CapabilityKind, ...] = ("market_data", "reference_data")
        for kind in kinds:
            inputs = tuple(
                item
                for item in definition.schema.inputs
                if (item.family == "reference") == (kind == "reference_data")
            )
            if not inputs:
                continue
            fields: tuple[CapabilityField, ...] = ()
            for item in inputs:
                field = CapabilityField(name=item.field.name, units=item.field.units)
                fields += () if field in fields else (field,)
            profiles += (
                CapabilityProfile(
                    name=f"paper-served-{kind.replace('_', '-')}",
                    kind=kind,
                    implementation_identity=definition.identity,
                    version="1",
                    products=("spot",),
                    venues=(self.venue,),
                    calendars=("continuous-utc",),
                    modes=("runtime",),
                    channels=tuple(sorted({item.family for item in inputs})),
                    clocks=tuple(sorted({item.clock for item in inputs})),
                    max_freshness_us=min(item.max_age_us for item in inputs),
                    fields=fields,
                    qualification="read_only",
                ),
            )
        return profiles

    def _trades(self, feed: CaptureConfig) -> CapabilityProfile:
        """Describe the public trades feed recorded beside the book, in its currencies."""
        base, quote = feed.base_currency, feed.quote_currency
        return CapabilityProfile(
            name="paper-market-trades",
            kind="market_data",
            implementation_identity="installed-paper-market_data-trades",
            version="1",
            products=("spot",),
            venues=(self.venue,),
            calendars=("continuous-utc",),
            modes=("runtime",),
            channels=("trade",),
            clocks=("event",),
            max_freshness_us=feed.idle_seconds * 1_000_000,
            fields=(
                CapabilityField(name="price", units=f"{quote}/{base}"),
                CapabilityField(name="quantity", units=base),
                CapabilityField(name="signed_quantity", units=base),
                CapabilityField(name="signed_flow", units=base),
            ),
            qualification="read_only",
        )

    def _profile(self, kind: CapabilityKind) -> CapabilityProfile:
        """Describe one capability family of the supervised paper environment."""
        market = kind == "market_data"
        return CapabilityProfile(
            name=self._name(kind),
            kind=kind,
            implementation_identity=f"installed-paper-{kind}",
            version="1",
            products=("spot",),
            venues=(self.venue,),
            calendars=("continuous-utc",),
            modes=("runtime",),
            channels=("book",) if market else (),
            clocks=self.clocks if market else (),
            max_freshness_us=self.freshness_us if market else None,
            fields=_BOOK_FIELDS if market else (),
            operations=(
                ("intent:target", "intent:exposure", "intent:order", "intent:quote")
                if kind == "execution"
                else ()
            ),
            order_types=("gtc", "ioc", "post-only") if kind == "execution" else (),
            qualification="read_only" if market else "fixture",
        )

    @staticmethod
    def _name(kind: CapabilityKind) -> str:
        """Name the installed profile of one capability family."""
        return f"paper-{kind.replace('_', '-')}"
