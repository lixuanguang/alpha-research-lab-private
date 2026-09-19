"""Decode individual archive trades without inventing historical capture clocks."""

from __future__ import annotations

# standard library imports
from decimal import Decimal, InvalidOperation

# project library imports
from market_data.adapters.providers.binance.rows import ArchiveRow, BinanceArchiveRows
from market_data.contracts import ArchiveTrade, SourceRequest


class BinanceArchiveTrades:
    """Construct strict archive records from validated provider rows."""

    @staticmethod
    def from_row(row: ArchiveRow, request: SourceRequest) -> ArchiveTrade:
        """Decode one verified seven-column individual-trade row for its explicit binding.

        Args:
            row: Original CSV bytes and origin supplied by the saved archive reader.
            request: Selected instrument/day; timestamp units follow the publisher's date rule.

        Returns:
            Exact trade values, including rows outside the narrower research selection.

        Raises:
            ValueError: Binding, source fields, units or the UTC partition is invalid.
        """
        row.__post_init__()
        BinanceArchiveRows(request=request, descriptor=row.origin)
        if (row.selection_start, row.selection_end) != (
            request.manifest.job.start,
            request.manifest.job.end,
        ):
            raise ValueError("archive row selection differs from request")
        fields = row.columns()
        try:
            if any(not fields[i].isascii() or not fields[i].isdecimal() for i in (0, 4)):
                raise ValueError("trade ID and timestamp must be unsigned ASCII integers")
            if any(fields[i] not in ("true", "false", "True", "False") for i in (5, 6)):
                raise ValueError("trade flags must be true/false or True/False")
            event = ArchiveTrade(
                instrument_id=request.instrument.instrument_id,
                symbol=request.instrument.symbol,
                trade_id=int(fields[0]),
                price=Decimal(fields[1]),
                quantity=Decimal(fields[2]),
                quote_quantity=Decimal(fields[3]),
                timestamp=int(fields[4]),
                timestamp_unit="us" if request.start.year >= 2025 else "ms",
                is_buyer_maker=fields[5].lower() == "true",
                is_best_match=fields[6].lower() == "true",
            )
            if not request.start <= event.ts_event < request.end:
                raise ValueError("trade timestamp outside requested UTC day")
            return event
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"invalid Binance trade at row {row.position}: {error}") from error
