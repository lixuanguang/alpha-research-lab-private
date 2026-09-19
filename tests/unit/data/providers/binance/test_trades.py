"""Protect exact archive-trade decoding and the absence of historical availability."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.providers.binance.rows import ArchiveRow
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.requests import SourceRequest
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[5]
_CODEC = DomainCodec()
_PAYLOAD = b'11,"100.00",2.0,199.999,1717200000001,True,false\r\n'


class TestArchiveTrade:
    """Exercise direct, wire and raw-CSV boundaries without source access."""

    @pytest.fixture()
    def selection(self) -> SourceRequest:
        """Resolve the maintained one-day selection.

        Returns:
            Authored Binance archive binding with its narrower research interval.
        """
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(config.resolve("btc-archive", catalog))[0]

    @staticmethod
    def _row(selection: SourceRequest, payload: bytes = _PAYLOAD) -> ArchiveRow:
        """Supply a synthetic row with explicit acquisition metadata and position."""
        return ArchiveRow(
            origin=RawObject(
                sha256="a" * 64,
                size_bytes=200,
                request_identity=selection.identity,
                retrieval_reference="synthetic:mr09",
                ts_received=datetime(2026, 9, 16, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
            ),
            selection_start=selection.manifest.job.start,
            selection_end=selection.manifest.job.end,
            position=7,
            payload=payload,
        )

    def test_exact_values_clocks_and_roundtrip(self, selection: SourceRequest) -> None:
        """Keep decimal scale, publisher quote quantity, raw precision and unknown clocks."""
        row = self._row(selection)
        event = ArchiveTrade.from_row(row, selection)
        assert str(event.price) == "100.00"
        assert str(event.quantity) == "2.0"
        assert event.quote_quantity == Decimal("199.999")
        assert event.quote_quantity != event.price * event.quantity
        assert event.trade_id == 11 and event.is_buyer_maker and not event.is_best_match
        assert (event.timestamp, event.timestamp_unit) == (1717200000001, "ms")
        assert event.ts_event == selection.start + timedelta(milliseconds=1)
        assert event.ts_source_received is event.ts_knowledge is None
        assert event.instrument_id == selection.instrument.instrument_id
        assert row.payload == _PAYLOAD
        assert _CODEC.decode_json(_CODEC.encode_json(event), ArchiveTrade) == event
        with pytest.raises(AttributeError):
            setattr(event, "timestamp", 0)

    @pytest.mark.parametrize(
        ("index", "field", "value"),
        [
            (1, "price", "1e30"),
            (2, "quantity", "1e-30"),
            (3, "quote_quantity", "0e-30"),
            (3, "quote_quantity", "0." + "1" * 40),
        ],
    )
    def test_decimal_bounds_preserve_exact_values_at_supported_edges(
        self, selection: SourceRequest, index: int, field: str, value: str
    ) -> None:
        """Retain exact source scale through the finite decimal boundary."""
        fields = list(self._row(selection).columns())
        fields[index] = value
        event = ArchiveTrade.from_row(self._row(selection, ",".join(fields).encode()), selection)
        if field == "price":
            observed = event.price
        elif field == "quantity":
            observed = event.quantity
        else:
            observed = event.quote_quantity
        assert observed.as_tuple() == Decimal(value).as_tuple()

    def test_microseconds_follow_source_date_not_magnitude(self, selection: SourceRequest) -> None:
        """Retain the last microsecond of a day and reject the wrong unit or next day."""
        start = datetime(2025, 1, 1, tzinfo=UTC)
        instrument = replace(
            selection.instrument, valid_from=start, valid_to=start + timedelta(days=1)
        )
        catalog = replace(selection.manifest.catalog, instruments=(instrument,))
        run = replace(
            selection.manifest,
            catalog=catalog,
            instruments=(instrument,),
            job=replace(selection.manifest.job, start=start, end=start + timedelta(hours=1)),
        )
        selection = SourceRequest.partition(run)[0]
        payload = _PAYLOAD.replace(b"1717200000001", b"1735775999999999")
        event = ArchiveTrade.from_row(self._row(selection, payload), selection)
        assert event.timestamp_unit == "us"
        assert event.ts_event == selection.end - timedelta(microseconds=1)
        for stamp in (b"1735689600000", b"1735776000000000"):
            with pytest.raises(ValueError, match="row 7"):
                ArchiveTrade.from_row(
                    self._row(selection, _PAYLOAD.replace(b"1717200000001", stamp)), selection
                )

    @pytest.mark.parametrize(
        ("index", "value"),
        [
            (0, "-1"),
            (0, "1.0"),
            (0, "\uff11"),
            (0, "1_1"),
            (1, "NaN"),
            (1, "1e31"),
            (1, "0"),
            (1, "-1"),
            (1, "no-price"),
            (2, "Infinity"),
            (2, "1e-31"),
            (2, "-1"),
            (3, "NaN"),
            (3, "0e-1000000000"),
            (3, "0." + "1" * 41),
            (3, "-1"),
            (4, "1e12"),
            (4, "99999999999999999999"),
            (4, "1717199999999"),
            (4, "1717286400000"),
            (4, "1717200000000001"),
            (5, "1"),
            (6, "TRUE"),
        ],
    )
    def test_malformed_numeric_time_and_flags(
        self, selection: SourceRequest, index: int, value: str
    ) -> None:
        """Reject invalid semantics with the original row position and recover on reuse."""
        fields = list(self._row(selection).columns())
        fields[index] = value
        with pytest.raises(ValueError, match="row 7"):
            ArchiveTrade.from_row(self._row(selection, ",".join(fields).encode()), selection)
        assert ArchiveTrade.from_row(self._row(selection), selection).trade_id == 11

    def test_foreign_binding_and_selection(self, selection: SourceRequest) -> None:
        """Reject origin substitution and narrower-row selections not authorized by the job."""
        row = self._row(selection)
        with pytest.raises(ValueError, match="identity"):
            ArchiveTrade.from_row(
                replace(row, origin=replace(row.origin, request_identity="b" * 64)), selection
            )
        with pytest.raises(ValueError, match="selection"):
            ArchiveTrade.from_row(
                replace(row, selection_start=row.selection_start + timedelta(minutes=1)), selection
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("trade_id", True),
            ("timestamp", -1),
            ("price", "invalid"),
            ("quantity", Decimal("NaN")),
            ("quote_quantity", Decimal("-1")),
            ("is_best_match", 1),
            ("is_buyer_maker", "true"),
            ("timestamp_unit", "ns"),
            ("ts_knowledge", datetime(2024, 6, 1, tzinfo=UTC)),
            ("ts_source_received", datetime(2024, 6, 1, tzinfo=UTC)),
            ("symbol", "btcusdt"),
            ("instrument_id", "BTCUSDT"),
        ],
    )
    def test_unsafe_instances_and_wire(
        self, selection: SourceRequest, field: str, value: object
    ) -> None:
        """Catch direct-constructor bypasses before consumption and reject them on the wire."""
        event = ArchiveTrade.from_row(self._row(selection), selection)
        msgspec.structs.force_setattr(event, field, value)
        with pytest.raises((TypeError, ValueError)):
            event.__post_init__()
        with pytest.raises((TypeError, ValueError)):
            _CODEC.decode_json(_CODEC.encode_json(event), ArchiveTrade)

    def test_strict_wire_and_direct_constructor(self, selection: SourceRequest) -> None:
        """Keep the existing exact JSON-number decoder contract and reject Python floats."""
        event = ArchiveTrade.from_row(self._row(selection), selection)
        payload = _CODEC.encode_json(event)
        with pytest.raises(ValueError, match="unknown field"):
            _CODEC.decode_json(payload[:-1] + b',"extra":1}', ArchiveTrade)
        assert b'"price":"100.00"' in payload
        numeric = payload.replace(b'"100.00"', b"9007199254740993.00000001")
        assert _CODEC.decode_json(numeric, ArchiveTrade).price == Decimal(
            "9007199254740993.00000001"
        )
        with pytest.raises(ValueError, match="price"):
            replace(event, price=Decimal("NaN"))
        msgspec.structs.force_setattr(event, "price", 1.0)
        with pytest.raises(TypeError, match="Decimal"):
            event.__post_init__()
