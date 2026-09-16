"""Bind one public UTC-day L2 archive to explicit native identity and resource limits."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from alpha_research.data.live.book import Wire
from alpha_research.instrument_identity import InstrumentId
from alpha_research.serialization import DomainCodec


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

    def select_url(self, raw: bytes) -> str:
        """Validate discovery identity and require the exact public CDN artifact.

        Args:
            raw: Bounded original public index response bytes.

        Returns:
            Verified HTTPS archive URL without authentication or query parameters.

        Raises:
            ValueError: The source response has no unique matching archive or exceeds limits.
        """
        response = Wire.mapping(Wire.decode(raw))
        rows = Wire.array(response.get("data"))
        if response.get("code") != "0" or len(rows) != 1:
            raise ValueError("OKX history index unavailable")
        group = Wire.mapping(rows[0])
        details = Wire.array(group.get("details"))
        if group.get("dateAggrType") != "daily" or len(details) != 1:
            raise ValueError("OKX archive unavailable for the selected UTC day")
        detail = Wire.mapping(details[0])
        if detail.get("instId") != self.symbol or detail.get("instType") != "SPOT":
            raise ValueError("OKX archive index instrument mismatch")
        files = Wire.array(detail.get("groupDetails"))
        if len(files) != 1:
            raise ValueError("OKX archive selection must resolve one file")
        entry = Wire.mapping(files[0])
        url = (
            "https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/"
            f"{self.day:%Y%m%d}/{self.filename}"
        )
        if entry.get("filename") != self.filename or entry.get("url") != url:
            raise ValueError("OKX archive filename or download host/path mismatch")
        if Wire.integer(entry.get("dateTs", entry.get("dataTs"))) != self.start_ms:
            raise ValueError("OKX archive UTC date mismatch")
        if Wire.decimal(entry.get("sizeMB")) * 1_048_576 > self.max_bytes:
            raise ValueError("OKX advertised archive exceeds compressed byte budget")
        return url


class OKXArchiveRequest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind original discovery, exact URL, selection and installed implementation."""

    config: OKXHistoryConfig
    implementation_identity: str
    index_sha256: str
    url: str
    index_received: datetime

    def __post_init__(self) -> None:
        """Validate immutable request metadata before raw-store admission."""
        self.config.__post_init__()
        for value in (self.implementation_identity, self.index_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("OKX archive identity must be SHA-256")
        expected = (
            "https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/"
            f"{self.config.day:%Y%m%d}/{self.config.filename}"
        )
        if self.url != expected or self.index_received.tzinfo != UTC:
            raise ValueError("invalid OKX archive origin or discovery receipt clock")

    @property
    def identity(self) -> str:
        """Identify the specific archive retrieval and all persisted source metadata.

        Returns:
            Stable SHA-256 request identity.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
