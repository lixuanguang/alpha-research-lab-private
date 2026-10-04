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
)

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
    """Profile one native public book, its reference data and the paper account services.

    The installed application declares these profiles from the components it
    binds; a candidate's requirements resolve against them before any source or
    account work. A profile match never grants trading authority.
    """

    def __init__(self, *, venue: str, freshness_us: int, clocks: tuple[str, ...]) -> None:
        """Bind the venue, source freshness and source clocks this environment supports."""
        if type(freshness_us) is not int or freshness_us <= 0 or not clocks:
            raise ValueError("paper capabilities require positive freshness and source clocks")
        self.venue, self.freshness_us, self.clocks = venue, freshness_us, clocks

    def registry(self) -> CapabilityRegistry:
        """Return one installed profile per capability family."""
        return CapabilityRegistry(tuple(self._profile(kind) for kind in _KINDS))

    def selections(
        self, requirements: tuple[CapabilityRequirement, ...]
    ) -> tuple[CapabilitySelection, ...]:
        """Select this environment's profile of the same family for every requirement."""
        return tuple(
            CapabilitySelection(name=item.name, profile=self._name(item.kind))
            for item in requirements
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
