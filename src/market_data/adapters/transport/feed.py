"""Bounded read-only public discovery, snapshot and WebSocket transport adapters."""

from __future__ import annotations

# standard library imports
import http.client
import logging
import ssl

# third party library imports
from websockets.asyncio.client import connect

# project library imports
from configuration import CaptureConfig
from market_data.adapters.wire import Wire
from market_data.contracts import FeedSocket


class VenueTransport:
    """Use fixed official market-data endpoints; credentials cannot target arbitrary hosts."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind resource limits and a private disabled logger to avoid auth-frame logging.

        Args:
            config: Validated native spot source selection and resource budgets.
        """
        self.config = config
        self._logger = logging.Logger("alpha.capture.private")
        self._logger.disabled = True

    async def open(self, timeout: float) -> FeedSocket:
        """Open a TLS feed with bounded frame buffers, heartbeat and shutdown deadlines.

        Args:
            timeout: Remaining connection budget in seconds.

        Returns:
            Bounded connection for the selected feed or synthetic session.
        """
        url = {
            "bitfinex": "wss://api-pub.bitfinex.com/ws/2",
            "coinbase": "wss://ws-feed.exchange.coinbase.com",
            "okx": "wss://ws.okx.com:8443/ws/v5/public",
        }[self.config.venue]
        return await connect(
            url,
            open_timeout=min(timeout, 10),
            close_timeout=2,
            ping_interval=15,
            ping_timeout=10,
            compression=None,
            max_size=self.config.max_frame_bytes,
            max_queue=self.config.queue_capacity,
            logger=self._logger,
        )

    def discover(self) -> bytes:
        """Verify native spot product availability and return original discovery bytes.

        Returns:
            Original public product discovery response bytes.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if self.config.venue == "bitfinex":
            raw = self._get("api-pub.bitfinex.com", "/v2/conf/pub:list:pair:exchange")
            listings = Wire.array(Wire.decode(raw))
            if not listings or self.config.symbol[1:] not in Wire.array(listings[0]):
                raise ValueError("Bitfinex native spot pair unavailable")
        elif self.config.venue == "okx":
            raw = self._get(
                "www.okx.com",
                f"/api/v5/public/instruments?instType=SPOT&instId={self.config.symbol}",
            )
            response = Wire.mapping(Wire.decode(raw))
            products = Wire.array(response.get("data"))
            if response.get("code") != "0" or len(products) != 1:
                raise ValueError("OKX native spot product unavailable")
            product = Wire.mapping(products[0])
            expected = {
                "instId": self.config.symbol,
                "instType": "SPOT",
                "state": "live",
                "baseCcy": self.config.base_currency,
                "quoteCcy": self.config.quote_currency,
            }
            if any(product.get(key) != value for key, value in expected.items()):
                raise ValueError("OKX native spot identity differs from configuration")
        else:
            raw = self._get("api.exchange.coinbase.com", f"/products/{self.config.symbol}")
            product = Wire.mapping(Wire.decode(raw))
            if any(
                (
                    product.get("id") != self.config.symbol,
                    product.get("base_currency") != self.config.base_currency,
                    product.get("quote_currency") != self.config.quote_currency,
                    product.get("status") != "online",
                    product.get("trading_disabled") is True,
                )
            ):
                raise ValueError("Coinbase native spot product unavailable")
        return raw

    def snapshot(self) -> bytes:
        """Fetch only the complete Coinbase L3 snapshot; no aggregate-depth fallback.

        Returns:
            Original complete Coinbase L3 REST snapshot bytes.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        if self.config.venue != "coinbase":
            raise ValueError("REST snapshot is only used for Coinbase")
        return self._get(
            "api.exchange.coinbase.com", f"/products/{self.config.symbol}/book?level=3"
        )

    def _get(self, host: str, path: str) -> bytes:
        """Read a bounded HTTPS response without redirects, credentials or error-body logging."""
        connection = http.client.HTTPSConnection(
            host, timeout=10, context=ssl.create_default_context()
        )
        try:
            connection.request("GET", path, headers={"User-Agent": "alpha-research-l3/1"})
            response = connection.getresponse()
            if response.status != 200:
                raise OSError(f"market data HTTP status {response.status}")
            payload = response.read(self.config.max_frame_bytes + 1)
            if len(payload) > self.config.max_frame_bytes:
                raise ValueError("market data response exceeds frame budget")
            return payload
        finally:
            connection.close()
