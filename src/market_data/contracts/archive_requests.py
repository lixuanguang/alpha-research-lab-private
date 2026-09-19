"""Bind retained OKX archive requests without discovery or storage behavior."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import UTC, datetime

# third party library imports
import msgspec

# project library imports
from configuration import OKXHistoryConfig
from market_data.contracts.raw import RequestBinding
from serialization import DomainCodec


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
    def binding(self) -> RequestBinding:
        """Revalidate the complete source request before admitting its storage identity.

        Returns:
            Neutral immutable binding after source-specific invariants have passed.
        """
        return RequestBinding(self.identity)

    @property
    def identity(self) -> str:
        """Identify the specific archive retrieval and all persisted source metadata.

        Returns:
            Stable SHA-256 request identity.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
