"""Symbology helpers for market/outcome identifiers and cross-venue matching."""

from __future__ import annotations

import re
from collections import defaultdict

import alpha_core.instruments.models as instrument_models

_QUESTION_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_CANONICAL_ID_SEPARATOR = ":"


def _normalize_component(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"`{name}` must be non-empty")
    if _CANONICAL_ID_SEPARATOR in cleaned:
        raise ValueError(
            f"`{name}` cannot contain `{_CANONICAL_ID_SEPARATOR}`; "
            "it is reserved as canonical ID separator"
        )
    return cleaned


def make_canonical_market_id(venue: str, market_id: str) -> str:
    """Build canonical market identifier as `{venue}:{market_id}`."""
    venue_clean = _normalize_component("venue", venue).lower()
    market_clean = _normalize_component("market_id", market_id)
    return f"{venue_clean}:{market_clean}"


def make_canonical_outcome_id(venue: str, market_id: str, outcome_id: str) -> str:
    """Build canonical outcome identifier as `{venue}:{market_id}:{outcome_id}`."""
    outcome_clean = _normalize_component("outcome_id", outcome_id)
    return f"{make_canonical_market_id(venue, market_id)}:{outcome_clean}"


def parse_canonical_outcome_id(canonical_id: str) -> tuple[str, str, str]:
    """Parse `{venue}:{market_id}:{outcome_id}` into components."""
    parts = canonical_id.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(
            "Invalid canonical outcome id format; expected "
            "`{venue}:{market_id}:{outcome_id}`"
        )
    venue, market_id, outcome_id = parts
    return venue.lower(), market_id, outcome_id


def normalize_question(question: str) -> str:
    """Normalize market title text for fuzzy cross-venue grouping."""
    compact = _QUESTION_NORMALIZE_RE.sub(" ", question.strip().lower())
    return " ".join(compact.split())


def find_cross_venue_groups(
    markets: list[instrument_models.MarketSpec],
) -> list[list[instrument_models.MarketSpec]]:
    """Group likely-equivalent markets across venues by normalized title text."""
    grouped: dict[str, list[instrument_models.MarketSpec]] = defaultdict(list)
    for market in markets:
        key = normalize_question(market.title)
        if key:
            grouped[key].append(market)

    matches: list[list[instrument_models.MarketSpec]] = []
    for group in grouped.values():
        venues = {market.venue for market in group}
        if len(venues) >= 2:
            matches.append(sorted(group, key=lambda market: (market.venue, market.market_id)))

    matches.sort(key=lambda group: (group[0].title.lower(), group[0].venue))
    return matches
