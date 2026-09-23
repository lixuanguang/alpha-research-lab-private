"""Decode public OKX spot trade pages and observed instrument specifications."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from itertools import pairwise
from urllib.parse import urlencode

# project library imports
from configuration import DataCapability, PublicDataJob
from market_data.adapters.wire import Wire
from market_data.contracts import PublicRequest, PublicTrade, TradePage
from reference_data.catalogs import InstrumentDefinition, VenueSpecification


class OKXPublic:
    """Own OKX REST pagination and source meaning; never infer original availability."""

    @property
    def capability(self) -> DataCapability:
        """Declare public spot trades, observed reference rules and continuous UTC scheduling."""
        return DataCapability(
            adapter="okx.public-trades",
            version="1",
            venue="okx",
            product="spot",
            channel="trades",
            representation="trades",
            modes=("backfill", "capture", "replay"),
            depth=None,
            source_clock="milliseconds",
            sequence="trade_id",
            reference="observed",
            calendar="continuous-utc",
            recovery="durable-page-cursor",
        )

    def endpoint(self, job: PublicDataJob, request: PublicRequest) -> tuple[str, str]:
        """Select official public endpoints after product, symbol and page-size admission."""
        self.capability.admit(request.instrument, channel="trades", mode=job.mode)
        instrument = request.instrument
        if (
            instrument.symbol != f"{instrument.base_currency}-{instrument.quote_currency}"
            or job.page_size > 100
        ):
            raise ValueError("OKX spot symbol mismatch or page size exceeds 100")
        if request.kind == "reference":
            path = "/api/v5/public/instruments?" + urlencode(
                {"instType": "SPOT", "instId": instrument.symbol}
            )
        elif job.mode == "capture":
            path = "/api/v5/market/trades?" + urlencode(
                {"instId": instrument.symbol, "limit": job.page_size}
            )
        else:
            path = "/api/v5/market/history-trades?" + urlencode(
                {
                    "instId": instrument.symbol,
                    "limit": job.page_size,
                    "type": "2" if request.cursor is None else "1",
                    "after": str(self._milliseconds(job.end))
                    if request.cursor is None
                    else request.cursor,
                }
            )
        return "www.okx.com", path

    def trades(self, job: PublicDataJob, request: PublicRequest, payload: bytes) -> TradePage:
        """Retain native IDs and aggressor sides; continue backwards using trade IDs."""
        self.endpoint(job, request)
        rows = self._rows(payload)
        if len(rows) > job.page_size:
            raise ValueError("OKX returned more rows than requested")
        trades: list[PublicTrade] = []
        for row in rows:
            item = Wire.mapping(row)
            if item.get("instId") != request.instrument.symbol:
                raise ValueError("OKX trade instrument mismatch")
            side = item.get("side")
            if side not in ("buy", "sell"):
                raise ValueError("invalid OKX trade side")
            trades.append(
                PublicTrade(
                    trade_id=Wire.text(item.get("tradeId")),
                    event_ms=Wire.integer(item.get("ts")),
                    price=Wire.decimal(item.get("px")),
                    quantity=Wire.decimal(item.get("sz")),
                    side="buy" if side == "buy" else "sell",
                )
            )
        if any(
            a.event_ms < b.event_ms or int(a.trade_id) <= int(b.trade_id)
            for a, b in pairwise(trades)
        ):
            raise ValueError("OKX page order or trade IDs are inconsistent")
        if job.mode == "backfill" and trades:
            if trades[0].event_ms >= self._milliseconds(job.end) or (
                request.cursor is not None and int(trades[0].trade_id) >= int(request.cursor)
            ):
                raise ValueError("OKX history cursor did not advance")
        continuation = None
        if (
            job.mode == "backfill"
            and len(trades) == job.page_size
            and trades[-1].event_ms >= self._milliseconds(job.start)
        ):
            continuation = trades[-1].trade_id
        return TradePage(trades=tuple(trades), next_cursor=continuation)

    def reference(
        self, instrument: InstrumentDefinition, payload: bytes, received: datetime
    ) -> VenueSpecification:
        """Retain current tick/lot/minimum rules from raw endpoint evidence at receipt."""
        rows = self._rows(payload)
        if len(rows) != 1:
            raise ValueError("OKX instrument discovery requires exactly one listing")
        item = Wire.mapping(rows[0])
        if any(
            item.get(key) != value
            for key, value in {
                "instType": "SPOT",
                "instId": instrument.symbol,
                "baseCcy": instrument.base_currency,
                "quoteCcy": instrument.quote_currency,
            }.items()
        ):
            raise ValueError("OKX reference identity mismatch")
        return VenueSpecification(
            instrument=instrument,
            valid_from=received,
            valid_to=None,
            ts_knowledge=received,
            source_digest=hashlib.sha256(payload).hexdigest(),
            basis="current_observation",
            price_tick=Wire.decimal(item.get("tickSz")),
            quantity_step=Wire.decimal(item.get("lotSz")),
            minimum_quantity=Wire.decimal(item.get("minSz")),
            status=Wire.text(item.get("state")),
        )

    @staticmethod
    def _rows(payload: bytes) -> list[object]:
        """Reject application errors before parsing source rows."""
        response = Wire.mapping(Wire.decode(payload))
        if response.get("code") != "0":
            raise ValueError("OKX public endpoint rejected request")
        return Wire.array(response.get("data"))

    @staticmethod
    def _milliseconds(instant: datetime) -> int:
        """Project UTC instants without floating-point clock arithmetic."""
        delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
