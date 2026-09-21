"""Provide one verified synthetic replay fixture for exact economic consumers."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from applications.backtest import run_backtest
from configuration import Configuration
from financial_units import Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import Disconnect, Occurrence, RawObject, SourceRequest, Trade
from market_data.query import QueryReader
from market_data.validation import QualityPolicy
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from risk import SpotLimits
from serialization import DomainCodec
from simulation import BacktestSpec, EconomicResult, SpotCosts

START = datetime(2024, 6, 1, tzinfo=UTC)
CODEC = DomainCodec()
ROOT = Path(__file__).parents[3]
type ReplayRow = tuple[int, int, str | None]


class ReplayInputs:
    """Build the same causally admitted rows for exact and comparison consumers."""

    rows: tuple[ReplayRow, ...] = (
        (50, 50, "100"),
        (110, 110, "110"),
        (121, 121, "111"),
        (170, 170, "105"),
        (181, 181, "104"),
        (230, 230, "106"),
    )

    @staticmethod
    def _knowledge(row: ReplayRow) -> int:
        """Order synthetic rows by source availability, preserving insertion ties."""
        return row[1]

    @classmethod
    def _canonical(
        cls, rows: tuple[ReplayRow, ...], *, instrument: int = 0
    ) -> tuple[tuple[bytes, ...], BacktestSpec]:
        """Admit native synthetic capture bytes with explicit source order and identity."""
        config = Configuration.read(ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = CODEC.decode_json(
            (ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve(
            "btc-fixture" if instrument == 0 else "eth-fixture",
            catalog,
            implementation_identity="a" * 64,
        )
        job = replace(run.job, end=START + timedelta(minutes=4))
        run = replace(run, job=job)
        history = CODEC.decode_json(
            (ROOT / "tests/fixtures/eligibility/membership-corrections.json").read_bytes(),
            EligibilityAssertions,
        )
        history = replace(history, catalog=catalog)
        partitions: list[bytes] = []
        decoder = TardisDecoder(BinancePayloadDecoder(run.instruments), run.instruments[0].source)
        for request in SourceRequest.partition(run):
            occurrences: list[Occurrence] = []
            for index, (event, known, price) in enumerate(sorted(rows, key=cls._knowledge)):
                instant = START + timedelta(seconds=known)
                if not request.start <= instant < request.end:
                    continue
                raw = (
                    b"\n"
                    if price is None
                    else (
                        instant.isoformat().replace("+00:00", "Z").encode()
                        + b" "
                        + CODEC.encode_json(
                            {
                                "stream": f"{request.instrument.symbol.lower()}@trade",
                                "data": {
                                    "e": "trade",
                                    "E": 1717200000000 + event * 1000,
                                    "T": 1717200000000 + event * 1000,
                                    "s": request.instrument.symbol,
                                    "t": index,
                                    "p": price,
                                    "q": "2",
                                    "m": True,
                                },
                            }
                        )
                        + b"\n"
                    )
                )
                origin = RawObject(
                    sha256="a" * 64,
                    size_bytes=4096,
                    request_identity=request.identity,
                    retrieval_reference="synthetic:economic-clock",
                    ts_received=START + timedelta(days=1),
                    ts_ingested=START + timedelta(days=1),
                )
                decoded = decoder.decode_line(
                    raw.decode().rstrip("\n"),
                    source_sequence=index,
                    local_received=origin.ts_received,
                    local_ingested=origin.ts_ingested,
                    source_digest=origin.sha256,
                    disconnect_capture_time=instant,
                )
                assert isinstance(decoded, (Trade, Disconnect))
                occurrences.append(
                    Occurrence(
                        request=request, origin=origin, position=index, raw=raw, event=decoded
                    )
                )
            partitions.append(
                QualityPolicy(use="exploratory", known_at=START, max_gap=timedelta(hours=1))
                .validate(
                    request,
                    occurrences,
                    eligibility=history,
                    verifier=SourceAdapters().verifier(request),
                )
                .require_canonical()
            )
        selected = run.instruments[0]
        dimension = Dimension(instrument_id=selected.instrument_id, kind=QuantityKind.BASE_UNIT)
        quantity = Quantity(value=Decimal("0.00100"), dimension=dimension)
        tick = Price(value=Decimal("0.01"), currency=selected.quote_currency, per=dimension)
        binding = (selected.source, "trade", selected.instrument_id)
        spec = BacktestSpec(
            instance="synthetic-momentum",
            binding=binding,
            start=START,
            end=job.end,
            initial_cash=Money(value=Decimal("1000"), currency=selected.quote_currency),
            quantity=quantity,
            limits=SpotLimits(
                maximum=quantity,
                lot=Quantity(value=Decimal("0.00001"), dimension=dimension),
                tick=tick,
                product="spot",
            ),
            costs=SpotCosts(adverse=tick, fee_rate=Decimal("0.001"), rounding="half_even"),
            rule="completed-price-momentum-v1",
            cadence_seconds=60,
            delay_seconds=1,
            max_age_seconds=30,
        )
        return tuple(partitions), spec

    @classmethod
    def _inputs(
        cls, rows: tuple[ReplayRow, ...], *, instrument: int = 0
    ) -> tuple[QueryReader, BacktestSpec]:
        """Compose a public query reader from completely admitted fixture partitions."""
        canonical, spec = cls._canonical(rows, instrument=instrument)
        return QueryReader(
            canonical, readers=SourceAdapters(), precedence=(spec.binding,), max_bytes=2_000_000
        ), spec

    @classmethod
    def _run(cls, rows: tuple[ReplayRow, ...] | None = None) -> EconomicResult:
        """Complete one independent synthetic run through the public application."""
        reader, spec = cls._inputs(cls.rows if rows is None else rows)
        result = run_backtest(reader, spec)
        assert isinstance(result, EconomicResult)
        return result
