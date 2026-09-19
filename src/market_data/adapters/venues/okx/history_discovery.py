"""Validate bounded OKX discovery responses against the selected archive."""

# project library imports
from configuration import OKXHistoryConfig
from market_data.adapters.wire import Wire


class OKXArchiveDiscovery:
    """Validate native discovery identity and advertised archive resource bounds."""

    @staticmethod
    def select_url(config: OKXHistoryConfig, raw: bytes) -> str:
        """Validate discovery identity and require the exact public CDN artifact.

        Args:
            config: Validated archive selection and resource limits.
            raw: Bounded original public index response bytes.

        Returns:
            Verified HTTPS archive URL without authentication or query parameters.

        Raises:
            ValueError: The source response has no unique matching archive or exceeds limits.
        """
        response = Wire.mapping(Wire.decode(raw))
        rows = Wire.array(response.get("data"))
        if response.get("code") != "0" or len(rows) != 1:
            raise ValueError("OKX history index unavailable")
        group = Wire.mapping(rows[0])
        details = Wire.array(group.get("details"))
        if group.get("dateAggrType") != "daily" or len(details) != 1:
            raise ValueError("OKX archive unavailable for the selected UTC day")
        detail = Wire.mapping(details[0])
        if detail.get("instId") != config.symbol or detail.get("instType") != "SPOT":
            raise ValueError("OKX archive index instrument mismatch")
        files = Wire.array(detail.get("groupDetails"))
        if len(files) != 1:
            raise ValueError("OKX archive selection must resolve one file")
        entry = Wire.mapping(files[0])
        url = (
            "https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/"
            f"{config.day:%Y%m%d}/{config.filename}"
        )
        if entry.get("filename") != config.filename or entry.get("url") != url:
            raise ValueError("OKX archive filename or download host/path mismatch")
        if Wire.integer(entry.get("dateTs", entry.get("dataTs"))) != config.start_ms:
            raise ValueError("OKX archive UTC date mismatch")
        if Wire.decimal(entry.get("sizeMB")) * 1_048_576 > config.max_bytes:
            raise ValueError("OKX advertised archive exceeds compressed byte budget")
        return url
