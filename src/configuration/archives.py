"""Bind one public UTC-day L2 archive to explicit native identity and resource limits."""

from __future__ import annotations

# standard library imports
import re
from datetime import date
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from reference_data.instruments import InstrumentId
from serialization import DomainCodec


class OKXHistoryConfig(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Select one 400-level spot archive; replay limits describe an explicit prefix."""

    symbol: str
    instrument_id: InstrumentId
    base_currency: str
    quote_currency: str
    day: date
    max_bytes: int
    max_expanded_bytes: int
    max_records: int
    max_line_bytes: int
    duration_seconds: int
    timeout_seconds: int
    retries: int

    def __post_init__(self) -> None:
        """Reject unsupported native identities, days and unbounded acquisition or replay."""
        if any(
            not re.fullmatch(r"[A-Z0-9]{2,12}", c)
            for c in (self.base_currency, self.quote_currency)
        ):
            raise ValueError("invalid OKX currency identity")
        if self.symbol != f"{self.base_currency}-{self.quote_currency}":
            raise ValueError("OKX native spot symbol differs from configured currencies")
        if not isinstance(self.instrument_id, InstrumentId) or type(self.day) is not date:
            raise ValueError("OKX archive requires canonical identity and UTC calendar date")
        for value, maximum in (
            (self.max_bytes, 1_000_000_000),
            (self.max_expanded_bytes, 8_000_000_000),
            (self.max_records, 10_000_000),
            (self.max_line_bytes, 1_000_000),
            (self.duration_seconds, 3600),
            (self.timeout_seconds, 60),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid OKX archive resource limit")
        if type(self.retries) is not int or not 0 <= self.retries <= 5:
            raise ValueError("invalid OKX archive retry limit")

    @property
    def filename(self) -> str:
        """Return the precise selected public archive name.

        Returns:
            Native symbol, depth and UTC day filename.
        """
        return f"{self.symbol}-L2orderbook-400lv-{self.day.isoformat()}.tar.gz"

    @property
    def start_ms(self) -> int:
        """Return inclusive UTC midnight without floating-point clock conversion.

        Returns:
            Unix milliseconds at the selected day boundary.
        """
        return (self.day - date(1970, 1, 1)).days * 86_400_000

    @property
    def index_path(self) -> str:
        """Select exactly one UTC day from the public inclusive-date archive API.

        Returns:
            Fixed public request path with explicit module and instrument.
        """
        return (
            "/api/v5/public/market-data-history?module=4&instType=SPOT"
            f"&instIdList={self.symbol}&dateAggrType=daily"
            f"&begin={self.start_ms}&end={self.start_ms}"
        )

    @classmethod
    def read(cls, path: Path) -> OKXHistoryConfig:
        """Read and validate a maintained archive selection.

        Args:
            path: Explicit non-secret JSON config file.

        Returns:
            Validated single-day archive configuration.
        """
        return DomainCodec().decode_json(path.read_bytes(), cls)
