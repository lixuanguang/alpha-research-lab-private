"""Select implemented native reconstruction for explicitly configured captures."""

# project library imports
from configuration import CaptureConfig, DataCapability
from market_data.adapters.venues.bitfinex import BitfinexBook
from market_data.adapters.venues.coinbase import CoinbaseBook
from market_data.adapters.venues.okx import OKXBook
from market_data.books import NativeBook
from reference_data.catalogs import InstrumentDefinition


class BookAdapters:
    """Map supported native feeds without dynamically importing configuration values."""

    @staticmethod
    def capability(config: CaptureConfig) -> DataCapability:
        """Declare source-specific depth, source clocks and recovery for the installed feed."""
        config.__post_init__()
        return DataCapability(
            adapter=f"{config.venue}.native-book",
            version="1",
            venue=config.venue,
            product="spot",
            channel=config.channel,
            representation="L2" if config.venue == "okx" else "L3",
            modes=("capture", "replay"),
            depth=config.depth or None,
            source_clock="milliseconds"
            if config.venue == "okx"
            else "iso8601"
            if config.venue == "coinbase"
            else "unknown",
            sequence="linked" if config.venue == "okx" else "consecutive",
            reference="none",
            calendar="continuous-utc",
            recovery="new-snapshot-epoch",
        )

    @staticmethod
    def create(config: CaptureConfig) -> NativeBook:
        """Construct a fresh state for the selected native feed.

        Args:
            config: Strict native identity and bounded resource selection.

        Returns:
            Venue implementation with native sequence and timestamp semantics.
        """
        config.__post_init__()
        BookAdapters.capability(config).admit(
            InstrumentDefinition(
                instrument_id=config.instrument_id,
                venue=config.venue,
                symbol=config.symbol,
                product="spot",
                base_currency=config.base_currency,
                quote_currency=config.quote_currency,
                calendar="continuous-utc",
            ),
            channel=config.channel,
            mode="capture",
        )
        if config.venue == "okx":
            return OKXBook(config.symbol)
        return BitfinexBook(config) if config.venue == "bitfinex" else CoinbaseBook(config)
