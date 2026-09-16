"""Resolve explicit spot capture selections without activating a service."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.instrument_identity import InstrumentId
from alpha_research.serialization import DomainCodec


class CaptureConfig(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Select one native spot feed and hard resource limits for one invocation."""

    venue: Literal["bitfinex", "coinbase", "okx"]
    symbol: str
    instrument_id: InstrumentId
    base_currency: str
    quote_currency: str
    channel: Literal["R0", "level3", "books"]
    depth: int
    duration_seconds: int
    max_messages: int
    max_bytes: int
    max_frame_bytes: int
    queue_capacity: int
    max_orders: int
    retries: int
    idle_seconds: int
    schema_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        """Reject unsupported modes, malformed identity and unbounded resource requests."""
        if self.schema_version != "1" or self.venue not in ("bitfinex", "coinbase", "okx"):
            raise ValueError("unsupported capture schema or venue")
        if self.channel != {"bitfinex": "R0", "coinbase": "level3", "okx": "books"}[self.venue]:
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
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid capture resource limit")
        if self.max_bytes < 8192 or self.max_frame_bytes > self.max_bytes // 2:
            raise ValueError("journal budget must leave room for frames and control records")
        if type(self.retries) is not int or not 0 <= self.retries <= 5:
            raise ValueError("retries must be between zero and five")
        if (
            type(self.depth) is not int
            or self.depth
            not in ({"bitfinex": (1, 25, 100, 250), "coinbase": (0,), "okx": (400,)}[self.venue])
        ):
            raise ValueError("unsupported venue depth")
        if self.venue == "okx" and self.max_orders != 800:
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


class CaptureRequest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind a unique recording to config and installed implementation identity."""

    config: CaptureConfig
    recording_id: str
    implementation_identity: str

    def __post_init__(self) -> None:
        """Validate the immutable identity used by shared raw-object storage."""
        self.config.__post_init__()
        if not re.fullmatch(r"[a-f0-9-]{36}", self.recording_id):
            raise ValueError("invalid recording identity")
        if not re.fullmatch(r"[a-f0-9]{64}", self.implementation_identity):
            raise ValueError("implementation identity must be SHA-256")

    @property
    def identity(self) -> str:
        """Return deterministic identity for this selected recording and implementation.

        Returns:
            Stable SHA-256 of the current bound identity or visible state.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
