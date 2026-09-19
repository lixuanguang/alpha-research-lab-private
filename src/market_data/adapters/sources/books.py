"""Select implemented native reconstruction for explicitly configured captures."""

# project library imports
from configuration import CaptureConfig
from market_data.adapters.venues.bitfinex import BitfinexBook
from market_data.adapters.venues.coinbase import CoinbaseBook
from market_data.adapters.venues.okx import OKXBook
from market_data.books import NativeBook


class BookAdapters:
    """Map supported native feeds without dynamically importing configuration values."""

    @staticmethod
    def create(config: CaptureConfig) -> NativeBook:
        """Construct a fresh state for the selected native feed.

        Args:
            config: Strict native identity and bounded resource selection.

        Returns:
            Venue implementation with native sequence and timestamp semantics.
        """
        config.__post_init__()
        if config.venue == "okx":
            return OKXBook(config.symbol)
        return BitfinexBook(config) if config.venue == "bitfinex" else CoinbaseBook(config)
