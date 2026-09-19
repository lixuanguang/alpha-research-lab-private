"""Validate explicit source identity and bounded collection configuration."""

# standard library imports
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig
from serialization import DomainCodec

_ROOT = Path(__file__).parents[4]


class TestCaptureConfig:
    """Reject unsupported channels and unsafe local resource selections before I/O."""

    def test_roundtrip_and_native_identity(self) -> None:
        """Select distinct canonical listings while retaining both venue-native BTC/USD symbols."""
        bitfinex = CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json")
        coinbase = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        assert bitfinex.symbol == "tBTCUSD"
        assert coinbase.symbol == "BTC-USD"
        assert bitfinex.instrument_id != coinbase.instrument_id
        with pytest.raises(ValueError, match="currencies"):
            replace(bitfinex, base_currency="ETH")
        with pytest.raises(ValueError):
            replace(coinbase, depth=25)
        with pytest.raises(ValueError):
            replace(bitfinex, duration_seconds=0)
        with pytest.raises(ValueError):
            replace(bitfinex, retries=6)
        with pytest.raises(ValueError):
            replace(bitfinex, max_bytes=1)

    def test_unknown_config_field(self, tmp_path: Path) -> None:
        """Fail configuration drift rather than silently ignoring misspelled controls."""
        config = (_ROOT / "configs/live/bitfinex-btc-usd.json").read_text()
        path = tmp_path / "invalid.json"
        path.write_text(
            config.replace('"schema_version":', '"unknown_control": 1, "schema_version":')
        )
        with pytest.raises(ValueError):
            CaptureConfig.read(path)

    @pytest.mark.parametrize(
        ("original", "unsupported"),
        [
            ('"R0"', '"books"'),
            ('"R0"', '"trades"'),
            ('"tBTCUSD"', '"fUSD"'),
            ('"tBTCUSD"', '"tBTCF0:USTF0"'),
            ('"venue": "bitfinex"', '"venue": "unknown"'),
        ],
    )
    def test_unsupported_source_combinations(self, original: str, unsupported: str) -> None:
        """Refuse stream, product and venue substitutions at configuration decoding."""
        raw = (_ROOT / "configs/live/bitfinex-btc-usd.json").read_text()
        assert original in raw
        with pytest.raises(ValueError):
            DomainCodec().decode_json(raw.replace(original, unsupported).encode(), CaptureConfig)
