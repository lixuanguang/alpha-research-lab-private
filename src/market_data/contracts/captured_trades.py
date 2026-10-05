"""Define the per-message and per-trade lineage of a captured public trades feed."""

from __future__ import annotations

# standard library imports
import re
from datetime import UTC, datetime, timedelta

# project library imports
from market_data.contracts.public_trades import PublicTrade
from reference_data.catalogs import InstrumentDefinition
from serialization import WireRecord

_SHA256 = re.compile(r"[0-9a-f]{64}")


class CapturedTrades(WireRecord, frozen=True, kw_only=True):
    """Retain one durable trades-capture message after the shared tape applied it.

    ``position`` counts every record of the whole segment chain from zero, as the
    live trade source does. ``synchronized`` is the tape's readiness without an
    invalid frame; ``trades`` are those this message added.
    """

    position: int
    epoch: int
    received_ns: int
    kind: str
    outcome: str
    synchronized: bool
    state_identity: str
    raw_sha256: str
    trades: tuple[PublicTrade, ...]

    def __post_init__(self) -> None:
        """Reject malformed coordinates, digests and trade values."""
        if (
            type(self.position) is not int
            or self.position < 0
            or type(self.epoch) is not int
            or type(self.received_ns) is not int
            or self.received_ns <= 0
            or not self.kind
            or not self.outcome
            or type(self.synchronized) is not bool
            or _SHA256.fullmatch(self.raw_sha256) is None
            or type(self.trades) is not tuple
        ):
            raise ValueError("invalid captured trades boundary")
        for trade in self.trades:
            if type(trade) is not PublicTrade:
                raise ValueError("captured trades require public trade records")
            trade.__post_init__()


class TradeBoundary(WireRecord, frozen=True, kw_only=True):
    """Retain one captured message's receipt and the coverage it belongs to.

    ``covered_from_ns`` is the receipt that opened the synchronized interval this
    message belongs to, or ``None`` while the tape is unsynchronized or after a gap,
    invalid frame or session end.
    """

    position: int
    received_ns: int
    covered_from_ns: int | None

    def __post_init__(self) -> None:
        """Require ordered nonnegative coordinates and coverage opened by a receipt."""
        if (
            type(self.position) is not int
            or self.position < 0
            or type(self.received_ns) is not int
            or self.received_ns <= 0
            or (
                self.covered_from_ns is not None
                and (
                    type(self.covered_from_ns) is not int
                    or not 0 < self.covered_from_ns <= self.received_ns
                )
            )
        ):
            raise ValueError("invalid captured trade boundary")

    @property
    def received_at(self) -> datetime:
        """Round the receipt up to microseconds so nothing is available early."""
        return CaptureTradeOrigin.utc(self.received_ns)

    @property
    def covered_from(self) -> datetime | None:
        """Round the coverage start up to microseconds, as the live source does."""
        return (
            None if self.covered_from_ns is None else CaptureTradeOrigin.utc(self.covered_from_ns)
        )


class CaptureTradeOrigin(WireRecord, frozen=True, kw_only=True):
    """Bind one captured trade to its recording, message position and durable receipt."""

    instrument: InstrumentDefinition
    request_identity: str
    position: int
    index: int
    received_ns: int
    raw_sha256: str

    def __post_init__(self) -> None:
        """Reject malformed identities and coordinates."""
        if type(self.instrument) is not InstrumentDefinition:
            raise ValueError("captured trade origin requires an instrument definition")
        self.instrument.__post_init__()
        if (
            _SHA256.fullmatch(self.request_identity) is None
            or _SHA256.fullmatch(self.raw_sha256) is None
            or type(self.position) is not int
            or self.position < 0
            or type(self.index) is not int
            or self.index < 0
            or type(self.received_ns) is not int
            or self.received_ns <= 0
        ):
            raise ValueError("invalid captured trade origin")

    @property
    def ts_knowledge(self) -> datetime:
        """Expose the durable receipt, rounded up to microseconds."""
        return self.utc(self.received_ns)

    @staticmethod
    def utc(ns: int) -> datetime:
        """Round Unix nanoseconds up to an aware UTC microsecond instant."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(ns + 999) // 1000)
