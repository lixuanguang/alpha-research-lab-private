"""Decode Bitfinex public spot trades with loss-aware timestamp pagination."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

# project library imports
from configuration import DataCapability, PublicDataJob
from market_data.adapters.wire import Wire
from market_data.contracts import PublicRequest, PublicTrade, TradePage
from reference_data.catalogs import InstrumentDefinition, VenueSpecification


class BitfinexPublic:
    """Own native signed amounts and overlapping millisecond history pages."""

    @property
    def capability(self) -> DataCapability:
        """Declare exact native trades and partial observed reference rules."""
        return DataCapability(
            adapter="bitfinex.public-trades",
            version="1",
            venue="bitfinex",
            product="spot",
            channel="trades",
            representation="trades",
            modes=("backfill", "capture", "replay"),
            depth=None,
            source_clock="milliseconds",
            sequence="trade_id",
            reference="observed",
            calendar="continuous-utc",
            recovery="overlapping-time-pages",
        )

    def endpoint(self, job: PublicDataJob, request: PublicRequest) -> tuple[str, str]:
        """Select fixed unauthenticated endpoints; funding and derivative symbols fail."""
        self.capability.admit(request.instrument, channel="trades", mode=job.mode)
        instrument = request.instrument
        if (
            instrument.symbol
            not in (
                f"t{instrument.base_currency}{instrument.quote_currency}",
                f"t{instrument.base_currency}:{instrument.quote_currency}",
            )
            or "F0" in instrument.symbol
        ):
            raise ValueError("Bitfinex spot native symbol differs from configured units")
        if request.kind == "reference":
            return "api-pub.bitfinex.com", "/v2/conf/pub:list:pair:exchange,pub:info:pair"
        query: dict[str, str | int] = {
            "limit": job.page_size,
            "sort": -1 if job.mode == "capture" else 1,
        }
        if job.mode == "backfill":
            query.update(
                start=self._milliseconds(job.start)
                if request.cursor is None
                else int(request.cursor),
                end=self._milliseconds(job.end) - 1,
            )
        return "api-pub.bitfinex.com", "/v2/trades/" + quote(
            instrument.symbol, safe=""
        ) + "/hist?" + urlencode(query)

    def trades(self, job: PublicDataJob, request: PublicRequest, payload: bytes) -> TradePage:
        """Overlap page boundaries, refusing an unpageable saturated millisecond."""
        self.endpoint(job, request)
        rows = Wire.array(Wire.decode(payload))
        if len(rows) > job.page_size:
            raise ValueError("Bitfinex returned more rows than requested")
        trades: list[PublicTrade] = []
        for row in rows:
            values = Wire.array(row)
            if len(values) != 4:
                raise ValueError("Bitfinex trading-pair trade requires four fields")
            amount = Wire.decimal(values[2])
            trades.append(
                PublicTrade(
                    trade_id=str(Wire.integer(values[0])),
                    event_ms=Wire.integer(values[1]),
                    price=Wire.decimal(values[3]),
                    quantity=amount.copy_abs(),
                    side="buy" if amount > 0 else "sell",
                )
            )
        times = [trade.event_ms for trade in trades]
        if times != sorted(times, reverse=job.mode == "capture") or len(
            {t.trade_id for t in trades}
        ) != len(trades):
            raise ValueError("Bitfinex page order or trade IDs are inconsistent")
        continuation = None
        if job.mode == "backfill":
            start = self._milliseconds(job.start) if request.cursor is None else int(request.cursor)
            if any(not start <= instant < self._milliseconds(job.end) for instant in times):
                raise ValueError("Bitfinex trade lies outside requested interval")
            if len(trades) == job.page_size:
                if times[-1] <= start:
                    raise ValueError(
                        "Bitfinex saturated millisecond cannot be paged without loss; "
                        "increase page_size"
                    )
                continuation = str(times[-1])
        return TradePage(trades=tuple(trades), next_cursor=continuation)

    def reference(
        self, instrument: InstrumentDefinition, payload: bytes, received: datetime
    ) -> VenueSpecification:
        """Keep native minimum size; unavailable fixed tick and lot steps remain unknown."""
        response = Wire.array(Wire.decode(payload))
        if len(response) != 2 or instrument.symbol[1:] not in Wire.array(response[0]):
            raise ValueError("Bitfinex pair is absent from current exchange spot listings")
        matches = [
            Wire.array(row)
            for row in Wire.array(response[1])
            if Wire.array(row) and Wire.array(row)[0] == instrument.symbol[1:]
        ]
        if len(matches) != 1 or len(matches[0]) != 2:
            raise ValueError("Bitfinex pair specification absent or ambiguous")
        values = Wire.array(matches[0][1])
        if len(values) < 5:
            raise ValueError("Bitfinex pair specification lacks minimum order size")
        return VenueSpecification(
            instrument=instrument,
            valid_from=received,
            valid_to=None,
            ts_knowledge=received,
            source_digest=hashlib.sha256(payload).hexdigest(),
            basis="current_observation",
            price_tick=None,
            quantity_step=None,
            minimum_quantity=Wire.decimal(values[3]),
            status="live",
        )

    @staticmethod
    def _milliseconds(instant: datetime) -> int:
        """Project aware UTC to the source's integer millisecond boundary."""
        delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
