"""Re-export the historical market-data API from cohesive defining modules."""

# project library imports
from alpha_research.data.events import (
    Disconnect,
    EventTimeBasis,
    MarketEventError,
    PriceLevel,
    Symbol,
)
from alpha_research.data.providers.tardis.binance import BinanceTardisDecoder, decode_tardis_line
from alpha_research.data.venues.binance.codecs import (
    MarketEvent,
    decode_market_event,
    encode_market_event,
    validate_market_event,
)
from alpha_research.data.venues.binance.events import (
    DepthSnapshot,
    DepthUpdate,
    Trade,
)

__all__ = [
    "BinanceTardisDecoder",
    "DepthSnapshot",
    "DepthUpdate",
    "Disconnect",
    "EventTimeBasis",
    "MarketEvent",
    "MarketEventError",
    "PriceLevel",
    "Symbol",
    "Trade",
    "decode_market_event",
    "decode_tardis_line",
    "encode_market_event",
    "validate_market_event",
]
