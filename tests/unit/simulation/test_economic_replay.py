"""Prove causal economic transitions over fully re-decoded synthetic source partitions."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

# third party library imports
import pytest
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
from simulation import (
    BacktestSpec,
    EconomicCheckpoint,
    EconomicResult,
    SpotCosts,
    VectorbtAdapter,
    VectorbtResult,
)

_ROOT = Path(__file__).parents[3]
_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()
type _Row = tuple[int, int, str | None]


class TestEconomicReplay:
    """Exercise exact baseline economics and the scheduler's consequential boundaries."""

    rows: tuple[_Row, ...] = (
        (50, 50, "100"),
        (110, 110, "110"),
        (121, 121, "111"),
        (170, 170, "105"),
        (181, 181, "104"),
        (230, 230, "106"),
    )

    @staticmethod
    def _knowledge(row: _Row) -> int:
        """Order synthetic rows by source availability, preserving equal-time insertion order."""
        return row[1]

    @staticmethod
    def _canonical(
        rows: tuple[_Row, ...], *, instrument: int = 0
    ) -> tuple[tuple[bytes, ...], BacktestSpec]:
        """Admit native synthetic capture bytes with explicit membership and source order."""
        config = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve(
            "btc-fixture" if instrument == 0 else "eth-fixture",
            catalog,
            implementation_identity="a" * 64,
        )
        job = replace(run.job, end=_START + timedelta(minutes=4))
        run = replace(run, job=job)
        history = replace(
            _CODEC.decode_json(
                (_ROOT / "tests/fixtures/eligibility/membership-corrections.json").read_bytes(),
                EligibilityAssertions,
            ),
            catalog=catalog,
        )
        partitions: list[bytes] = []
        decoder = TardisDecoder(BinancePayloadDecoder(run.instruments), run.instruments[0].source)
        for request in SourceRequest.partition(run):
            occurrences: list[Occurrence] = []
            for index, (event, known, price) in enumerate(
                sorted(rows, key=TestEconomicReplay._knowledge)
            ):
                instant = _START + timedelta(seconds=known)
                if not request.start <= instant < request.end:
                    continue
                raw = (
                    b"\n"
                    if price is None
                    else (
                        instant.isoformat().replace("+00:00", "Z").encode()
                        + b" "
                        + _CODEC.encode_json(
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
                    ts_received=_START + timedelta(days=1),
                    ts_ingested=_START + timedelta(days=1),
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
                QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1))
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
            start=_START,
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
        cls, rows: tuple[_Row, ...], *, instrument: int = 0
    ) -> tuple[QueryReader, BacktestSpec]:
        """Compose a public query reader from completely admitted fixture partitions."""
        canonical, spec = cls._canonical(rows, instrument=instrument)
        return QueryReader(
            canonical, readers=SourceAdapters(), precedence=(spec.binding,), max_bytes=2_000_000
        ), spec

    @classmethod
    def _run(cls, rows: tuple[_Row, ...] | None = None) -> EconomicResult:
        """Complete an independent synthetic run through the public application."""
        reader, spec = cls._inputs(cls.rows if rows is None else rows)
        result = run_backtest(reader, spec)
        assert isinstance(result, EconomicResult)
        return result

    def test_independent_baseline_costs_no_trade_and_instrument_reuse(self) -> None:
        """Reconcile hand arithmetic and isolate BTC/ETH control and momentum instances."""
        for instrument in (0, 1):
            reader, spec = self._inputs(self.rows, instrument=instrument)
            for precision in (2, 28):
                with localcontext() as context:
                    context.prec = precision
                    result = run_backtest(reader, spec)
                    assert isinstance(result, EconomicResult)
                    assert result.terminal.nav.value == Decimal("999.99276500")
                    fills = result.checkpoint.state.ledger.fills
                    assert tuple(fill.filled_at for fill in fills) == (
                        _START + timedelta(seconds=121),
                        _START + timedelta(seconds=181),
                    )
                    assert fills[0].fee.value == Decimal("0.00011101")
                    assert fills[1].fee.value == Decimal("0.00010399")
                    assert result.terminal.gross.value == Decimal("-0.007")
            flat = run_backtest(reader, replace(spec, rule="no-trade-v1"))
            assert isinstance(flat, EconomicResult)
            assert flat.terminal.nav.value == 1000 and not flat.checkpoint.state.ledger.fills

    def test_batches_and_full_economic_resume(self) -> None:
        """Retain identical economics across batches and checkpoints before and after fills."""
        reader, spec = self._inputs(self.rows)
        result = run_backtest(reader, spec, batch_size=256)
        assert isinstance(result, EconomicResult)
        for size in (1, 2, 256):
            assert run_backtest(reader, spec, batch_size=size) == result
        for second in (50, 60, 110, 120, 121, 150, 180, 181, 230):
            checkpoint = run_backtest(
                reader, spec, batch_size=1, stop_at=_START + timedelta(seconds=second)
            )
            assert isinstance(checkpoint, EconomicCheckpoint)
            checkpoint = _CODEC.decode_json(_CODEC.encode_json(checkpoint), EconomicCheckpoint)
            assert run_backtest(reader, spec, checkpoint=checkpoint, batch_size=2) == result
        assert isinstance(checkpoint, EconomicCheckpoint)
        with pytest.raises(ValueError, match="assumptions"):
            run_backtest(reader, replace(spec, delay_seconds=2), checkpoint=checkpoint)
        with pytest.raises(ValueError, match="corrupt"):
            replace(checkpoint, state_sha256="0" * 64)

    def test_same_time_gap_cancels_but_later_gap_cannot_undo_fill(self) -> None:
        """Admit all tied controls before fills, while preserving already posted economics."""
        baseline = self.rows
        tied = self._run((*baseline[:3], (121, 121, None), *baseline[3:]))
        assert not tied.checkpoint.state.ledger.fills
        later = self._run((*baseline[:3], (150, 150, None), *baseline[3:]))
        assert len(later.checkpoint.state.ledger.fills) == 1
        assert later.checkpoint.state.ledger.fills[0].filled_at == _START + timedelta(seconds=121)
        assert later.terminal.nav.value == Decimal("999.99487899")

    def test_expiry_positive_delay_and_unaffordable_fill(self) -> None:
        """Reject exact-expiry, old-event and unaffordable prints without resizing or postings."""
        expiry = self._run(
            (self.rows[0], self.rows[1], (119, 130, "110"), (180, 180, "111"), self.rows[-1])
        )
        assert not expiry.checkpoint.state.ledger.fills
        assert "expired" in {item.reason for item in expiry.checkpoint.state.trace}
        old = self._run(
            (self.rows[0], self.rows[1], (119, 121, "111"), self.rows[3], self.rows[-1])
        )
        assert old.checkpoint.state.ledger.fills[0].filled_at == _START + timedelta(seconds=170)
        costly = self._run((self.rows[0], self.rows[1], (121, 121, "2000000"), *self.rows[3:]))
        assert not costly.checkpoint.state.ledger.fills
        assert costly.terminal.nav.value == 1000
        assert "insufficient_cash" in {item.reason for item in costly.checkpoint.state.trace}

    def test_future_event_schedule_frozen_windows_and_required_terminal_mark(self) -> None:
        """Schedule a known future event, freeze a close and refuse a stale open-position NAV."""
        future = self._run((self.rows[0], self.rows[1], (122, 121, "111"), *self.rows[3:]))
        assert future.checkpoint.state.ledger.fills[0].filled_at == _START + timedelta(seconds=122)
        late = self._run((self.rows[0], self.rows[1], (115, 130, "1000"), *self.rows[2:]))
        assert late.checkpoint.state.observations.completed[1].point is not None
        assert late.checkpoint.state.observations.completed[1].point.price.value == 110
        with pytest.raises(ValueError, match="terminal valuation"):
            self._run(
                (self.rows[0], self.rows[1], self.rows[2], (170, 170, "115"), (181, 181, "116"))
            )

    def test_vectorbt_real_engine_delayed_targets_and_roundtrip(self) -> None:
        """Compare independently regenerated delayed targets with the real pinned backend."""
        reference = self._run()
        result = VectorbtAdapter.run(reference)
        assert result.nav[-1] == pytest.approx(999.992765, abs=1e-10, rel=1e-12)
        assert result.cash[0] == pytest.approx(999.88887899, abs=1e-10, rel=1e-12)
        assert result.holdings == (0.001, 0.0, 0.0)
        assert result.orders[0].executed_at == _START + timedelta(seconds=121)
        assert _CODEC.decode_json(_CODEC.encode_json(result), VectorbtResult) == result
        reader, spec = self._inputs(self.rows)
        flat = run_backtest(reader, replace(spec, rule="no-trade-v1"))
        assert isinstance(flat, EconomicResult)
        assert VectorbtAdapter.run(flat).nav == (1000.0,)
        gapped = self._run((*self.rows[:3], (150, 150, None), *self.rows[3:]))
        with pytest.raises(ValueError, match="gaps"):
            VectorbtAdapter.run(gapped)

    def test_projection_isolates_unrelated_controls_and_future_perturbations(self) -> None:
        """Keep another instrument's gap and future-only prices out of the causal prefix."""
        canonical, spec = self._canonical(self.rows)
        other, other_spec = self._canonical(
            (*self.rows[:3], (121, 121, None), *self.rows[3:]), instrument=1
        )
        both = QueryReader(
            (*canonical, *other),
            readers=SourceAdapters(),
            precedence=(spec.binding, other_spec.binding),
            max_bytes=2_000_000,
        )
        selected = run_backtest(both, spec, batch_size=1)
        baseline = self._run()
        assert isinstance(selected, EconomicResult)
        assert selected.checkpoint.state == baseline.checkpoint.state
        changed = self._run((*self.rows[:3], (170, 170, "1000"), *self.rows[4:]))
        cutoff = _START + timedelta(seconds=121)
        assert tuple(
            event for event in changed.checkpoint.state.trace if event.at <= cutoff
        ) == tuple(event for event in baseline.checkpoint.state.trace if event.at <= cutoff)

    def test_exact_return_and_terminal_holding_are_not_a_liquidation(self) -> None:
        """Keep the nonterminating observed return and open holdings in exact final NAV."""
        result = self._run(((50, 50, "100.03"), (110, 110, "100.04"), *self.rows[2:]))
        decision = next(
            event
            for event in result.checkpoint.state.trace
            if event.phase == "decision" and event.at == _START + timedelta(seconds=120)
        )
        assert decision.return_ratio is not None
        assert (decision.return_ratio.numerator, decision.return_ratio.denominator) == (
            "1",
            "10003",
        )
        opened = self._run((*self.rows[:3], (170, 170, "115"), *self.rows[4:]))
        assert len(opened.checkpoint.state.ledger.fills) == 1
        assert opened.checkpoint.state.trace[-1].balance.holding.value == Decimal("0.001")
        assert opened.terminal.nav.value == Decimal("999.99487899")

    def test_limits_and_unsupported_products_fail_without_resizing(self) -> None:
        """Enforce product, grid and holding limits independently of the selected rule."""
        reader, spec = self._inputs(self.rows)
        with pytest.raises(ValueError, match="spot"):
            replace(spec.limits, product="future")
        off_lot = spec.quantity.model_copy(update={"value": Decimal("0.000015")})
        assert spec.limits.target_reason(off_lot, spec.quantity, pending=False) == "off_lot_target"
        oversized = spec.quantity.model_copy(update={"value": Decimal("0.002")})
        assert spec.limits.target_reason(oversized, spec.quantity, pending=False) == "holding_limit"
        off_tick = spec.limits.tick.model_copy(update={"value": Decimal("100.005")})
        assert spec.limits.price_reason(off_tick) == "invalid_reference_price"
        with pytest.raises(ValueError, match="timing"):
            run_backtest(reader, replace(spec, delay_seconds=0))

    def test_control_at_close_blocks_intent_without_rewriting_the_completed_window(self) -> None:
        """Treat the half-open window and the current control as separate decision facts."""
        result = self._run((self.rows[0], self.rows[1], (120, 120, None), *self.rows[2:]))
        decision = next(
            event
            for event in result.checkpoint.state.trace
            if event.phase == "decision" and event.at == _START + timedelta(seconds=120)
        )
        assert decision.observation is not None and decision.observation.reason == "valid"
        assert decision.reason == "known_gap"
        assert not result.checkpoint.state.ledger.fills
