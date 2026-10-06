"""Resolve explicit spot capture selections without activating a service."""

from __future__ import annotations

# standard library imports
import re
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class CaptureConfig(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Select one native spot feed and hard resource limits for one invocation.

    A feed is a venue book channel or, for OKX and Bitfinex, the public ``trades``
    channel. A trade feed has no depth (``depth`` 0); ``max_orders`` is unused.
    ``clock_interval_ms`` is how long a connected feed may receive nothing before its
    writer retains a ``clock`` record, so consumers know the feed has passed an instant.
    """

    venue: Literal["bitfinex", "coinbase", "okx"]
    symbol: str
    instrument_id: InstrumentId
    base_currency: str
    quote_currency: str
    channel: Literal["R0", "level3", "books", "trades"]
    depth: int
    duration_seconds: int
    max_messages: int
    max_bytes: int
    max_frame_bytes: int
    queue_capacity: int
    max_orders: int
    retries: int
    idle_seconds: int
    clock_interval_ms: int
    schema_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        """Reject unsupported modes, malformed identity and unbounded resource requests."""
        if self.schema_version != "1" or self.venue not in ("bitfinex", "coinbase", "okx"):
            raise ValueError("unsupported capture schema or venue")
        is_trades = self.channel == "trades" and self.venue in ("bitfinex", "okx")
        if (
            self.channel != {"bitfinex": "R0", "coinbase": "level3", "okx": "books"}[self.venue]
            and not is_trades
        ):
            raise ValueError("unsupported venue/channel")
        if not re.fullmatch(r"[A-Za-z0-9:-]{3,40}", self.symbol):
            raise ValueError("invalid native symbol")
        if self.venue == "bitfinex" and not self.symbol.startswith("t"):
            raise ValueError("Bitfinex capture supports trading pairs only")
        if self.venue == "bitfinex" and self.symbol not in (
            f"t{self.base_currency}{self.quote_currency}",
            f"t{self.base_currency}:{self.quote_currency}",
        ):
            raise ValueError("Bitfinex native pair must match configured currencies")
        if (
            self.venue in ("coinbase", "okx")
            and self.symbol != f"{self.base_currency}-{self.quote_currency}"
        ):
            raise ValueError("native spot product must match configured currencies")
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("capture requires canonical instrument identity")
        if any(
            not re.fullmatch(r"[A-Z0-9]{2,12}", c)
            for c in (self.base_currency, self.quote_currency)
        ):
            raise ValueError("invalid currency identity")
        for value, maximum in (
            (self.duration_seconds, 3600),
            (self.max_messages, 1_000_000),
            (self.max_bytes, 1_000_000_000),
            (self.max_frame_bytes, 32_000_000),
            (self.queue_capacity, 4096),
            (self.max_orders, 1_000_000),
            (self.idle_seconds, 120),
            (self.clock_interval_ms, 10_000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid capture resource limit")
        if self.clock_interval_ms < 10:
            raise ValueError("capture clock interval must be at least 10 ms")
        if self.max_bytes < 8192 or self.max_frame_bytes > self.max_bytes // 2:
            raise ValueError("journal budget must leave room for frames and control records")
        if type(self.retries) is not int or not 0 <= self.retries <= 5:
            raise ValueError("retries must be between zero and five")
        depths = {"bitfinex": (1, 25, 100, 250), "coinbase": (0,), "okx": (400,)}[self.venue]
        if type(self.depth) is not int or self.depth not in ((0,) if is_trades else depths):
            raise ValueError("unsupported venue depth")
        if self.venue == "okx" and not is_trades and self.max_orders != 800:
            raise ValueError("OKX books requires the 800-entry aggregate level budget")

    @classmethod
    def read(cls, path: Path) -> CaptureConfig:
        """Read a maintained non-secret configuration through the exact domain codec.

        Args:
            path: Explicit local file path; secret values are never reported.

        Returns:
            Validated native spot configuration with explicit resource ceilings.
        """
        return DomainCodec().decode_json(path.read_bytes(), cls)
