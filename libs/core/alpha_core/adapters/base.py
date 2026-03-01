"""Abstract venue adapter interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models


class VenueAdapter(ABC):
    """Abstract interface for venue connectivity."""

    @abstractmethod
    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        """Fetch market metadata mapped to canonical market specs."""

    @abstractmethod
    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        """Fetch canonical trade events for a market outcome."""

    @abstractmethod
    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        """Fetch the current canonical order book snapshot for a market outcome."""

    @abstractmethod
    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        """Fetch canonical OHLCV bars for a market outcome."""

    @abstractmethod
    def venue_name(self) -> str:
        """Return normalized venue identifier."""

    @abstractmethod
    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        """Fetch canonical markets plus corresponding raw vendor payloads."""

    @abstractmethod
    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        """Fetch canonical trades plus corresponding raw vendor payloads."""

    @abstractmethod
    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        """Fetch canonical order book plus corresponding raw vendor payload."""

    @abstractmethod
    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        """Fetch canonical OHLCV bars plus corresponding raw vendor payloads."""
