"""Define exact per-book quotes without implying freshness or execution qualification."""

from __future__ import annotations

# standard library imports
import re
from decimal import Decimal
from typing import Literal

# third party library imports
import msgspec

# project library imports
from market_data.contracts.levels import Level
from reference_data.instruments import InstrumentId


class BookQuoteSide(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain one native price and aggregate quantity/count in the instrument's units."""

    price: Decimal
    quantity: Decimal
    order_count: int

    def __post_init__(self) -> None:
        """Reject inexact, nonpositive prices, quantities and order counts."""
        if type(self.price) is not Decimal or not self.price.is_finite() or self.price <= 0:
            raise ValueError("book quote requires a positive exact price")
        Level(self.quantity, self.order_count)


class BookQuote(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Expose one complete book boundary with native identity, clocks and quality.

    Unknown source, receipt and availability stay unknown. Availability is supplied
    by the delivering caller; receipt is not silently substituted. A quote is not
    a freshness query or a consolidated market. Missing sides on an accepted empty
    book differ from an unavailable control, stale or invalid boundary.
    """

    venue: str
    instrument_id: InstrumentId
    source_id: str
    channel: str
    position: int
    epoch: int | None
    sequence: int | None
    source_time: str | None
    received_ns: int | None
    available_ns: int | None
    outcome: str
    status: str
    reason: str
    state_identity: str
    bid: BookQuoteSide | None
    ask: BookQuoteSide | None

    def __post_init__(self) -> None:
        """Validate identity, original clocks, quality and explicit side availability."""
        if (
            any(
                type(value) is not str or not value.strip()
                for value in (self.venue, self.source_id, self.channel, self.outcome, self.reason)
            )
            or type(self.instrument_id) is not InstrumentId
        ):
            raise ValueError("book quote requires native source and instrument identity")
        InstrumentId(self.instrument_id.uuid_value)
        if (
            type(self.position) is not int
            or any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    self.position,
                    self.epoch,
                    self.sequence,
                    self.received_ns,
                    self.available_ns,
                )
            )
            or (self.source_time is not None and type(self.source_time) is not str)
            or (
                self.received_ns is not None
                and self.available_ns is not None
                and self.available_ns < self.received_ns
            )
        ):
            raise ValueError("book quote has invalid original clocks or coordinates")
        if (
            self.status not in ("degraded", "stale", "recovering", "unavailable")
            or type(self.state_identity) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", self.state_identity)
        ):
            raise ValueError("book quote has invalid quality or state identity")
        for side in (self.bid, self.ask):
            if side is not None:
                if type(side) is not BookQuoteSide:
                    raise ValueError("book quote requires typed sides")
                side.__post_init__()
        if (self.status != "degraded" or self.outcome not in ("snapshot", "update")) and (
            self.bid is not None or self.ask is not None
        ):
            raise ValueError("unavailable book quote cannot expose prices")

    @property
    def market_state(
        self,
    ) -> Literal["unavailable", "empty", "one_sided", "locked", "crossed", "two_sided"]:
        """Distinguish unavailable state, missing sides and native locked/crossed books."""
        if self.status != "degraded" or self.outcome not in ("snapshot", "update"):
            return "unavailable"
        if self.bid is None and self.ask is None:
            return "empty"
        if self.bid is None or self.ask is None:
            return "one_sided"
        if self.bid.price == self.ask.price:
            return "locked"
        return "crossed" if self.bid.price > self.ask.price else "two_sided"
