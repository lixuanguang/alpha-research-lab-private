"""Venue-specific normalization quirks and capability metadata."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

VenueName = Literal[
    "kalshi",
    "kalshidemo",
    "polymarket",
    "limitless",
    "baozi",
    "myriad",
    "probable",
]


@dataclass(frozen=True)
class VenueQuirks:
    """Venue normalization controls for canonical adapter mappings."""

    tick_size: Decimal
    price_scale: Decimal
    side_aliases: dict[str, str]


@dataclass(frozen=True)
class VenueCapabilities:
    """Supported read capabilities for a venue adapter."""

    fetch_markets: bool = True
    fetch_trades: bool = True
    fetch_order_book: bool = True
    fetch_ohlcv: bool = True


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
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "kalshidemo": VenueQuirks(
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "polymarket": VenueQuirks(
        tick_size=Decimal("0.001"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "limitless": VenueQuirks(
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "baozi": VenueQuirks(
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "myriad": VenueQuirks(
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
    "probable": VenueQuirks(
        tick_size=Decimal("0.01"),
        price_scale=Decimal("1"),
        side_aliases=dict(_DEFAULT_SIDE_ALIASES),
    ),
}

_VENUE_CAPABILITIES: dict[str, VenueCapabilities] = {
    venue_name: VenueCapabilities() for venue_name in _VENUE_QUIRKS
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


def get_venue_capabilities(venue_name: str) -> VenueCapabilities:
    """Return capability matrix entry for a supported venue."""
    normalized = normalize_venue_name(venue_name)
    return _VENUE_CAPABILITIES[normalized]


def get_exchange_class_name(venue_name: str) -> str:
    """Return the configured pmxt exchange class for a supported venue."""
    normalized = normalize_venue_name(venue_name)
    return _VENUE_EXCHANGE_CLASSES[normalized]
