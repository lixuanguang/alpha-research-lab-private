"""Venue-specific normalization quirks and capability metadata."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class VenueQuirks:
    """Venue normalization controls for canonical adapter mappings."""

    price_scale: Decimal
    side_aliases: dict[str, str]


_DEFAULT_SIDE_ALIASES = {
    "buy": "buy",
    "bid": "buy",
    "yes": "buy",
    "sell": "sell",
    "ask": "sell",
    "no": "sell",
}

_VENUE_QUIRKS: dict[str, VenueQuirks] = {
    "kalshi": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "kalshidemo": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "polymarket": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "limitless": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "baozi": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "myriad": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "probable": VenueQuirks(
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
}

_VENUE_EXCHANGE_CLASSES: dict[str, str] = {
    "kalshi": "Kalshi",
    "kalshidemo": "KalshiDemo",
    "polymarket": "Polymarket",
    "limitless": "Limitless",
    "baozi": "Baozi",
    "myriad": "Myriad",
    "probable": "Probable",
}


def normalize_venue_name(venue_name: str) -> str:
    """Normalize and validate venue identifiers."""
    normalized = venue_name.strip().lower()
    if normalized not in _VENUE_QUIRKS:
        raise ValueError(f"Unsupported venue: {venue_name}")
    return normalized


def get_venue_quirks(venue_name: str) -> VenueQuirks:
    """Return normalization quirks for a supported venue."""
    normalized = normalize_venue_name(venue_name)
    return _VENUE_QUIRKS[normalized]


def get_exchange_class_name(venue_name: str) -> str:
    """Return the configured pmxt exchange class for a supported venue."""
    normalized = normalize_venue_name(venue_name)
    return _VENUE_EXCHANGE_CLASSES[normalized]
