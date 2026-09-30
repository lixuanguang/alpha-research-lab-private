"""Check exact feature/label calculations against independent price and clock examples."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from applications.explore import inspect_experiment
from configuration import Configuration
from financial_units import ExactRatio
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.sources import SourceAdapters
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import Disconnect, Occurrence, RawObject, SourceRequest, Trade
from market_data.query import BookQuery, InputBinding, QueryBatch, QueryReader
from market_data.storage import RawStore
from market_data.validation import Correction, QualityPolicy, TradeRevision
from reference_data.catalogs import CatalogSnapshot
from reference_data.eligibility import EligibilityAssertions
from research.experiments import AttemptStore, SampleInterval, TemporalSplit, TimeWindow
from research.exploration import (
    BookSelection,
    EdaQuery,
    FeatureStudy,
    ResearchDataset,
    ResearchReader,
    ResearchSelection,
    TradeCoverage,
    TradeResearchInput,
    TradeSelection,
)
from research.features import (
    FeatureDefinition,
    FeatureRegistry,
    FeatureValue,
    TrailingReturn,
    WindowPolicy,
)
from research.labels import ForwardReturn
from research.models import ModelDataset
from research.results import FeatureStudyResult
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_START = datetime(2024, 6, 1, tzinfo=UTC)
_CODEC = DomainCodec()


class _AdmittedPrices(ResearchReader):
    """Supply actual admitted native query results while recording requested cutoff windows."""

    def __init__(self, reader: QueryReader, request: SourceRequest) -> None:
        """Bind admitted prices without performing disk reads in this temporal boundary test."""
        self.reader, self.request = reader, request
        self.cutoffs: list[datetime] = []

    def read(self, selection: ResearchSelection) -> ResearchDataset:
        """Return exactly the selected actual query and its binding evidence."""
        results = []
        for item in selection.inputs:
            assert isinstance(item, TradeSelection)
            query = item.query
            self.cutoffs.append(query.known_at)
            batches = tuple(
                self.reader.batches(
                    query.instruments,
                    start=query.start,
                    end=query.end,
                    known_at=query.known_at,
                    columns=query.columns,
                    batch_size=query.batch_size,
                )
            )
            coverage = TradeCoverage(
                TestPriceDiagnostics._binding(self.request),
                sum(len(batch.rows) for batch in batches),
                (),
            )
            results.append(TradeResearchInput(item.name, batches, (coverage,)))
        return ResearchDataset(selection, selection.identity, tuple(results))


class _DelegatingFeature:
    """Expose one registered feature engine while retaining the typed definition contract."""

    def __init__(self, definition: TrailingReturn) -> None:
        """Bind the immutable definition delegated to the installed evaluator."""
        self._definition = definition

    @property
    def schema_version(self) -> str:
        """Return the retained schema identity."""
        return self._definition.schema_version

    @property
    def units(self) -> str:
        """Return the retained output units."""
        return self._definition.units

    @property
    def policy(self) -> WindowPolicy:
        """Return the retained causal policy."""
        return self._definition.policy

    @property
    def cadence_us(self) -> int:
        """Return the retained decision cadence."""
        return self._definition.cadence_us

    @property
    def processing_delay_us(self) -> int:
        """Return the retained processing delay."""
        return self._definition.processing_delay_us

    @property
    def identity(self) -> str:
        """Return the retained immutable definition identity."""
        return self._definition.identity

    def __post_init__(self) -> None:
        """Validate the retained typed definition."""
        self._definition.__post_init__()

    def evaluate(
        self, batches: tuple[QueryBatch, ...], *, binding: InputBinding, decision_at: datetime
    ) -> FeatureValue:
        """Delegate evaluation to the retained definition."""
        return self._definition.evaluate(batches, binding=binding, decision_at=decision_at)


class TestPriceDiagnostics:
    """Use native source decoding and admission; expected ratios are hand calculations."""

    @staticmethod
    def _request(instrument: int = 0) -> SourceRequest:
        """Resolve the existing fixture contract without changing source availability."""
        config = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve("both-fixture", catalog, implementation_identity="a" * 64)
        return SourceRequest(manifest=run, instrument=run.instruments[instrument], offset_minutes=0)

    @staticmethod
    def _binding(request: SourceRequest) -> InputBinding:
        """Keep each native source/stream/instrument independent."""
        return (
            request.instrument.source,
            request.manifest.job.stream,
            request.instrument.instrument_id,
        )

    @staticmethod
    def _item(
        request: SourceRequest,
        event_second: int,
        capture_second: int,
        price: str,
        trade_id: int,
        position: int,
        *,
        disconnect: bool = False,
    ) -> Occurrence:
        """Decode independently authored business/capture clocks and positional order."""
        capture = _START + timedelta(seconds=capture_second)
        event_ms = 1717200000000 + event_second * 1000
        payload = _CODEC.encode_json(
            {
                "stream": request.instrument.symbol.lower() + "@trade",
                "data": {
                    "e": "trade",
                    "E": event_ms,
                    "T": event_ms,
                    "s": request.instrument.symbol,
                    "t": trade_id,
                    "p": price,
                    "q": "2.0",
                    "m": True,
                },
            }
        )
        raw = (
            b"\n"
            if disconnect
            else capture.isoformat().replace("+00:00", "Z").encode() + b" " + payload + b"\n"
        )
        origin = RawObject(
            sha256="b" * 64,
            size_bytes=8192,
            request_identity=request.identity,
            retrieval_reference="synthetic:price-diagnostic",
            ts_received=_START + timedelta(days=1),
            ts_ingested=_START + timedelta(days=1),
        )
        event = TardisDecoder(
            BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
        ).decode_line(
            raw.decode().rstrip("\n"),
            source_sequence=position,
            source_digest=origin.sha256,
            local_received=origin.ts_received,
            local_ingested=origin.ts_ingested,
            disconnect_capture_time=capture,
        )
        assert isinstance(event, (Trade, Disconnect))
        return Occurrence(request=request, origin=origin, position=position, raw=raw, event=event)

    @staticmethod
    def _payload(
        request: SourceRequest,
        items: tuple[Occurrence, ...],
        corrections: tuple[Correction, ...] = (),
    ) -> bytes:
        """Admit one partition's occurrences through full native validation."""
        history = _CODEC.decode_json(
            (_ROOT / "tests/fixtures/eligibility/membership-corrections.json").read_bytes(),
            EligibilityAssertions,
        )
        return (
            QualityPolicy(use="exploratory", known_at=_START, max_gap=timedelta(hours=1))
            .validate(
                request,
                items,
                eligibility=replace(history, catalog=request.manifest.catalog),
                corrections=corrections,
                verifier=SourceAdapters.verifier(request),
            )
            .require_canonical()
        )

    @classmethod
    def _reader(
        cls,
        request: SourceRequest,
        items: tuple[Occurrence, ...],
        corrections: tuple[Correction, ...] = (),
    ) -> QueryReader:
        """Require full native admission before the feature can observe any rows."""
        return QueryReader(
            (cls._payload(request, items, corrections),),
            readers=SourceAdapters(),
            precedence=(cls._binding(request),),
            max_bytes=262_144,
        )

    @staticmethod
    def _batches(
        reader: QueryReader,
        request: SourceRequest,
        start: int,
        end: int,
        cutoff: int,
        batch_size: int = 1,
    ) -> tuple[QueryBatch, ...]:
        """Read independent half-open business and inclusive availability windows."""
        return tuple(
            reader.batches(
                (request.instrument.instrument_id,),
                start=_START + timedelta(seconds=start),
                end=_START + timedelta(seconds=end),
                known_at=_START + timedelta(seconds=cutoff),
                columns=("revision",),
                batch_size=batch_size,
            )
        )

    @staticmethod
    def _feature() -> TrailingReturn:
        """Declare a ten-second diagnostic with two observations and a two-second stale limit."""
        return TrailingReturn(
            policy=WindowPolicy(lookback_us=10_000_000, min_trades=2, max_staleness_us=2_000_000),
            cadence_us=10_000_000,
            processing_delay_us=0,
        )

    def test_hand_returns_labels_and_decimal_context(self) -> None:
        """100.03→100.04 is 1/10003; 100.04→100.05 is 1/10004 after its delay."""
        request = self._request()
        rows = (
            self._item(request, 0, 1, "100.03", 1, 0),
            self._item(request, 9, 9, "100.04", 2, 1),
            self._item(request, 19, 19, "100.05", 3, 2),
        )
        reader = self._reader(request, rows)
        feature = self._feature()
        label = ForwardReturn(
            horizon_us=10_000_000,
            availability_delay_us=1_000_000,
            policy=WindowPolicy(lookback_us=10_000_000, min_trades=1, max_staleness_us=2_000_000),
        )
        with localcontext() as context:
            context.prec = 2
            value = feature.evaluate(
                self._batches(reader, request, 0, 10, 10),
                binding=self._binding(request),
                decision_at=_START + timedelta(seconds=10),
            )
            assert value.value == ExactRatio(numerator="1", denominator="10003")
            outcome = label.evaluate(
                value,
                self._batches(reader, request, 10, 20, 21),
                known_at=_START + timedelta(seconds=21),
            )
            assert outcome.value == ExactRatio(numerator="1", denominator="10004")
        assert outcome.available_at == outcome.information_end == _START + timedelta(seconds=21)
        pending = label.evaluate(value, None, known_at=_START + timedelta(seconds=20))
        assert pending.value is None and pending.available_at is None
        assert pending.missing == "outcome not yet available"
        assert (
            feature.evaluate(
                self._batches(reader, request, 0, 10, 10, 100),
                binding=self._binding(request),
                decision_at=value.decision_at,
            )
            == value
        )
        assert _CODEC.decode_json(_CODEC.encode_json(feature), TrailingReturn) == feature
        assert _CODEC.decode_json(_CODEC.encode_json(outcome.value), ExactRatio) == outcome.value

    def test_future_perturbation_and_late_correction(self) -> None:
        """An earlier event corrected after the decision cannot change its frozen feature."""
        request = self._request()
        first = self._item(request, 0, 1, "100", 1, 0)
        last = self._item(request, 9, 9, "101", 2, 1)
        revised = self._item(request, 9, 9, "999", 2, 2)
        correction = Correction(
            supersedes=TradeRevision(occurrences=(last,)).identity,
            replacement=TradeRevision(occurrences=(revised,)).identity,
            ts_published=_START + timedelta(seconds=11),
            ts_available=_START + timedelta(seconds=12),
            evidence_reference="synthetic:late-price-correction",
        )
        future = self._item(request, 19, 20, "888", 3, 3)
        original = self._reader(request, (first, last))
        changed = self._reader(request, (first, last, revised, future), (correction,))
        feature = self._feature()
        earlier = feature.evaluate(
            self._batches(original, request, 0, 10, 10),
            binding=self._binding(request),
            decision_at=_START + timedelta(seconds=10),
        )
        perturbed = feature.evaluate(
            self._batches(changed, request, 0, 10, 10),
            binding=self._binding(request),
            decision_at=earlier.decision_at,
        )
        assert earlier.value == perturbed.value == ExactRatio(numerator="1", denominator="100")
        assert earlier.window.points == perturbed.window.points
        assert earlier.window.query_identity != perturbed.window.query_identity
        with pytest.raises(ValueError, match="cutoff"):
            feature.evaluate(
                self._batches(changed, request, 0, 10, 12),
                binding=self._binding(request),
                decision_at=earlier.decision_at,
            )

    def test_event_order_ties_warmup_missing_stale_and_controls(self) -> None:
        """Business time governs endpoints; ties use admitted order and gaps never become prices."""
        request = self._request()
        rows = (
            self._item(request, 0, 1, "100", 1, 0),
            self._item(request, 8, 9, "110", 2, 1),
            self._item(request, 7, 9, "120", 3, 2),
        )
        reader = self._reader(request, rows)
        feature = self._feature()
        value = feature.evaluate(
            self._batches(reader, request, 0, 10, 10),
            binding=self._binding(request),
            decision_at=_START + timedelta(seconds=10),
        )
        assert value.value == ExactRatio(numerator="1", denominator="5")
        assert [point.price for point in value.window.points] == [
            Decimal("100"),
            Decimal("110"),
            Decimal("120"),
        ]
        stale = replace(feature, policy=replace(feature.policy, max_staleness_us=999_999))
        assert (
            stale.evaluate(
                self._batches(reader, request, 0, 10, 10),
                binding=self._binding(request),
                decision_at=value.decision_at,
            ).window.missing
            == "stale final trade"
        )
        early = feature.evaluate(
            self._batches(reader, request, -5, 5, 5),
            binding=self._binding(request),
            decision_at=_START + timedelta(seconds=5),
        )
        assert (
            early.value is None
            and early.window.missing is not None
            and "warm-up" in early.window.missing
        )
        empty = feature.evaluate(
            self._batches(reader, request, 10, 20, 20),
            binding=self._binding(request),
            decision_at=_START + timedelta(seconds=20),
        )
        assert empty.window.missing == "insufficient available trades"
        disconnected = self._reader(
            request, (*rows, self._item(request, 0, 10, "1", 4, 3, disconnect=True))
        )
        gap = feature.evaluate(
            self._batches(disconnected, request, 0, 10, 10),
            binding=self._binding(request),
            decision_at=value.decision_at,
        )
        assert (
            gap.value is None
            and gap.window.controls
            and gap.window.missing is not None
            and "disconnect" in gap.window.missing
        )

    def _recovery_capture(self, request: SourceRequest) -> tuple[Occurrence, ...]:
        """A disconnect at 20 s answered by a trade captured at the same instant, later."""
        return (
            self._item(request, 1, 1, "100", 1, 0),
            self._item(request, 0, 20, "1", 0, 1, disconnect=True),
            self._item(request, 20, 20, "101", 2, 2),
            self._item(request, 31, 31, "102", 3, 3),
            self._item(request, 35, 35, "103", 4, 4),
            self._item(request, 39, 39, "104", 5, 5),
        )

    def _recovery_batches(
        self, reader: QueryReader, request: SourceRequest, start: int, end: int
    ) -> tuple[QueryBatch, ...]:
        """Query a cutoff window that also returns disconnect recoveries."""
        return tuple(
            reader.batches(
                (request.instrument.instrument_id,),
                start=_START + timedelta(seconds=start),
                end=_START + timedelta(seconds=end),
                known_at=_START + timedelta(seconds=end),
                columns=("revision",),
                batch_size=4,
                recoveries=True,
            )
        )

    def test_first_binding_message_recovery_is_opt_in_and_bounded(self) -> None:
        """A disconnect answered before the window gives a value only when the policy accepts it."""
        request = self._request()
        reader = self._reader(request, self._recovery_capture(request))
        binding = self._binding(request)
        strict = WindowPolicy(lookback_us=10_000_000, min_trades=2, max_staleness_us=2_000_000)
        accepting = replace(strict, accept_first_binding_message=True)
        end = _START + timedelta(seconds=40)
        batches = self._recovery_batches(reader, request, 30, 40)
        (recovery,) = batches[0].recoveries
        assert recovery.binding == binding
        assert recovery.resumed_at == _START + timedelta(seconds=20)
        assert recovery.basis == "first_binding_message"
        # The default policy keeps refusing, even when recoveries were queried.
        refused = strict.collect(batches, binding=binding, end=end, known_at=end)
        assert refused.missing == "scoped disconnect: recovery is unproven"
        assert refused.recoveries == ()
        window = accepting.collect(batches, binding=binding, end=end, known_at=end)
        assert window.missing is None and len(window.points) == 3
        assert window.recoveries == (recovery,)
        (control,) = window.controls
        assert isinstance(control.event, Disconnect)
        assert control.identity == recovery.disconnect_identity
        with pytest.raises(ValueError, match="history requires revision"):
            next(
                reader.batches(
                    (request.instrument.instrument_id,),
                    start=_START,
                    end=end,
                    known_at=end,
                    columns=("revision",),
                    batch_size=4,
                    mode="history",
                    recoveries=True,
                )
            )
        # Without queried recoveries, or with one for another binding, nothing answers.
        plain = self._batches(reader, request, 30, 40, 40)
        assert plain[0].recoveries == ()
        assert (
            accepting.collect(plain, binding=binding, end=end, known_at=end).missing
            == "scoped disconnect: recovery is unproven"
        )
        other = replace(recovery, binding=("another.source", "trade", binding[2]))
        foreign = tuple(batch._replace(recoveries=(other,)) for batch in batches)
        assert (
            accepting.collect(foreign, binding=binding, end=end, known_at=end).missing
            == "scoped disconnect: recovery is unproven"
        )
        late = tuple(
            batch._replace(recoveries=(replace(recovery, known_at=end + timedelta(seconds=1)),))
            for batch in batches
        )
        assert (
            accepting.collect(late, binding=binding, end=end, known_at=end).missing
            == "scoped disconnect: recovery is unproven"
        )
        # A disconnect inside the window, or answered only after its start, stays missing.
        inside_end = _START + timedelta(seconds=25)
        inside = accepting.collect(
            self._recovery_batches(reader, request, 15, 25),
            binding=binding,
            end=inside_end,
            known_at=inside_end,
        )
        assert inside.missing == "scoped disconnect inside window"
        after = replace(recovery, resumed_at=_START + timedelta(seconds=31))
        shifted = tuple(batch._replace(recoveries=(after,)) for batch in batches)
        assert (
            accepting.collect(shifted, binding=binding, end=end, known_at=end).missing
            == "scoped disconnect: recovery after window start"
        )

    def test_disconnects_at_one_position_of_two_partitions_keep_their_own_recovery(
        self,
    ) -> None:
        """A disconnect cannot borrow the recovery of another minute's disconnect."""
        first = self._request()
        second = replace(first, offset_minutes=1)
        # D1 at position 1 of minute 0 is answered at 20 s; D2 at position 1 of
        # minute 1 (70 s) is answered only at 80 s, after the window starts.
        reader = QueryReader(
            (
                self._payload(first, self._recovery_capture(first)),
                self._payload(
                    second,
                    (
                        self._item(second, 61, 61, "100", 11, 0),
                        self._item(second, 0, 70, "1", 0, 1, disconnect=True),
                        self._item(second, 80, 80, "101", 12, 2),
                        self._item(second, 90, 90, "102", 13, 3),
                        self._item(second, 95, 95, "103", 14, 4),
                    ),
                ),
            ),
            readers=SourceAdapters(),
            precedence=(self._binding(first),),
            max_bytes=524_288,
        )
        accepting = WindowPolicy(
            lookback_us=25_000_000,
            min_trades=2,
            max_staleness_us=10_000_000,
            accept_first_binding_message=True,
        )
        end = _START + timedelta(seconds=100)
        batches = self._recovery_batches(reader, second, 75, 100)
        assert len(batches[0].recoveries) == 2
        window = accepting.collect(batches, binding=self._binding(first), end=end, known_at=end)
        assert window.missing == "scoped disconnect: recovery after window start"
        assert window.recoveries == ()

    def test_recovery_needs_a_later_trade_known_by_the_cutoff(self) -> None:
        """A second disconnect with no later trade is unanswered and poisons later windows."""
        request = self._request()
        capture = (
            *self._recovery_capture(request),
            self._item(request, 0, 50, "1", 0, 6, disconnect=True),
        )
        reader = self._reader(request, capture)
        selector = reader._selector
        instruments = (request.instrument.instrument_id,)
        before = selector.recoveries(
            instruments, end=_START + timedelta(seconds=60), known_at=_START + timedelta(seconds=19)
        )
        assert before == ()
        after = selector.recoveries(
            instruments, end=_START + timedelta(seconds=60), known_at=_START + timedelta(seconds=59)
        )
        assert [item.resumed_at for item in after] == [_START + timedelta(seconds=20)]
        accepting = WindowPolicy(
            lookback_us=10_000_000,
            min_trades=1,
            max_staleness_us=10_000_000,
            accept_first_binding_message=True,
        )
        end = _START + timedelta(seconds=60)
        window = accepting.collect(
            self._recovery_batches(reader, request, 50, 60),
            binding=self._binding(request),
            end=end,
            known_at=end,
        )
        assert window.missing == "scoped disconnect inside window"
        # A later window starts after the unanswered disconnect and is still poisoned.
        later_end = _START + timedelta(seconds=59)
        later = replace(accepting, lookback_us=5_000_000, max_staleness_us=5_000_000).collect(
            self._recovery_batches(reader, request, 54, 59),
            binding=self._binding(request),
            end=later_end,
            known_at=later_end,
        )
        assert later.missing == "scoped disconnect: recovery is unproven"

    def test_definition_and_exact_ratio_validation(self) -> None:
        """Versions and parameters affect identity; malformed wire and unsafe mutation fail."""
        feature = self._feature()
        assert replace(feature, cadence_us=1).identity != feature.identity
        assert replace(feature, processing_delay_us=1).identity != feature.identity
        assert (
            replace(feature, policy=replace(feature.policy, min_trades=3)).identity
            != feature.identity
        )
        for numerator, denominator in (
            ("0", "2"),
            ("2", "4"),
            ("-0", "1"),
            ("1", "0"),
            ("1", "-2"),
            ("01", "2"),
        ):
            with pytest.raises(ValueError):
                ExactRatio(numerator=numerator, denominator=denominator)
        assert ExactRatio.from_fraction(Fraction(-2, 3)) == ExactRatio(
            numerator="-2", denominator="3"
        )
        with pytest.raises(ValueError):
            WindowPolicy(lookback_us=True, min_trades=2, max_staleness_us=0)
        with pytest.raises(ValueError):
            replace(feature, policy=replace(feature.policy, min_trades=1))
        force_setattr(feature.policy, "lookback_us", 0)
        with pytest.raises(ValueError):
            _ = feature.identity

    def test_processing_delay_and_independent_instrument(self) -> None:
        """The same definition accepts another configured instrument and freezes earlier inputs."""
        request = self._request(1)
        reader = self._reader(
            request, (self._item(request, 0, 1, "20", 1, 0), self._item(request, 9, 9, "22", 2, 1))
        )
        feature = replace(self._feature(), processing_delay_us=2_000_000)
        value = feature.evaluate(
            self._batches(reader, request, 0, 10, 10),
            binding=self._binding(request),
            decision_at=_START + timedelta(seconds=12),
        )
        assert value.value == ExactRatio(numerator="1", denominator="10")
        assert value.available_at == _START + timedelta(seconds=12)
        assert value.window.known_at == _START + timedelta(seconds=10)


class TestFeatureStudies:
    """Verify retained configuration, causal scheduling and honest generated sample intervals."""

    @staticmethod
    def _study() -> FeatureStudy:
        """Declare two decisions, a pending second outcome and explicit no-fit scope."""
        request = TestPriceDiagnostics._request()
        return FeatureStudy(
            family="causal-price-diagnostic",
            question="Inspect fixed price returns",
            selection=ResearchSelection(
                inputs=(
                    TradeSelection(
                        name="prices",
                        query=EdaQuery(
                            snapshot_id="a" * 64,
                            precedence=(TestPriceDiagnostics._binding(request),),
                            instruments=(request.instrument.instrument_id,),
                            start=_START,
                            end=_START + timedelta(seconds=30),
                            known_at=_START + timedelta(seconds=25),
                            columns=("revision",),
                            mode="cutoff",
                            batch_size=1,
                            max_bytes=262_144,
                        ),
                    ),
                )
            ),
            split=TemporalSplit(
                training=None,
                fit_cutoff=None,
                fit_mode="none",
                samples=(),
                embargo_us=0,
                rationale="No fitted state; explicit label horizons remain before holdout",
                validation=TimeWindow(start=_START, end=_START + timedelta(seconds=40)),
                holdout=TimeWindow(
                    start=_START + timedelta(seconds=50), end=_START + timedelta(seconds=60)
                ),
            ),
            partition="validation",
            decisions=TimeWindow(
                start=_START + timedelta(seconds=10), end=_START + timedelta(seconds=21)
            ),
            feature=TestPriceDiagnostics._feature(),
            label=ForwardReturn(
                horizon_us=10_000_000,
                availability_delay_us=1_000_000,
                policy=WindowPolicy(
                    lookback_us=10_000_000, min_trades=1, max_staleness_us=2_000_000
                ),
            ),
        )

    def test_schedule_pending_outcome_and_repeat_result(self) -> None:
        """Read only each feature cutoff and the available label; repeat without hidden state."""
        study = self._study()
        request = TestPriceDiagnostics._request()
        reader = TestPriceDiagnostics._reader(
            request,
            (
                TestPriceDiagnostics._item(request, 0, 1, "100", 1, 0),
                TestPriceDiagnostics._item(request, 8, 9, "110", 2, 1),
                TestPriceDiagnostics._item(request, 11, 11, "111", 3, 2),
                TestPriceDiagnostics._item(request, 19, 19, "121", 4, 3),
            ),
        )
        admitted = _AdmittedPrices(reader, request)
        payload = study.evaluate(admitted)
        assert admitted.cutoffs == [_START + timedelta(seconds=n) for n in (10, 21, 20)]
        admitted.cutoffs.clear()
        assert study.evaluate(admitted) == payload
        # third party library imports
        import msgspec

        fields = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
        samples = msgspec.json.decode(fields["samples"], type=tuple[SampleInterval, ...])
        assert [row.label_available_at for row in samples] == [_START + timedelta(seconds=21), None]
        assert [row.information_end for row in samples] == [
            _START + timedelta(seconds=21),
            _START + timedelta(seconds=31),
        ]
        assert samples[0].information_start == _START
        no_label = replace(study, label=None)
        admitted.cutoffs.clear()
        without_labels = no_label.evaluate(admitted)
        assert (
            msgspec.json.decode(without_labels, type=dict[str, msgspec.Raw])["features"]
            == fields["features"]
        )
        assert admitted.cutoffs == [_START + timedelta(seconds=n) for n in (10, 20)]

    def test_result_wire_compatibility_and_model_admission(self) -> None:
        """Preserve saved bytes and diagnostic ordering while models require aligned inputs."""
        study = self._study()
        request = TestPriceDiagnostics._request()
        reader = TestPriceDiagnostics._reader(
            request,
            (
                TestPriceDiagnostics._item(request, 0, 1, "100", 1, 0),
                TestPriceDiagnostics._item(request, 8, 9, "110", 2, 1),
                TestPriceDiagnostics._item(request, 11, 11, "111", 3, 2),
                TestPriceDiagnostics._item(request, 19, 19, "121", 4, 3),
            ),
        )
        payload = study.evaluate(_AdmittedPrices(reader, request))
        result = FeatureStudyResult.decode(payload)
        expected_fields = {
            "schema_version": "feature-study-result",
            "selection_identity": study.selection.identity,
            "feature_definition": study.feature,
            "label_definition": study.label,
            "features": result.features,
            "labels": result.labels,
            "samples": result.samples,
            "split_identity": study.split.identity,
            "fitting": "not applicable: fixed diagnostic has no fitted state",
            "scope": "exploratory_degraded",
        }
        assert _CODEC.encode_json(expected_fields) == payload
        assert _CODEC.encode_json(FeatureStudyResult.decode(payload)) == payload
        model = ModelDataset.from_results((payload,))
        assert model.rows[0].sample == result.samples[0]
        assert model.rows[1].label is None

        reordered_samples: tuple[SampleInterval, ...] = tuple(reversed(result.samples))
        reordered = replace(result, samples=reordered_samples)
        assert reordered.aligned_rows() == result.aligned_rows()
        with pytest.raises(ValueError, match="model input rows are not aligned"):
            ModelDataset.from_results((_CODEC.encode_json(reordered),))
        tampered_sample = replace(result.samples[0], input_sha256="0" * 64)
        tampered_samples: tuple[SampleInterval, ...] = (tampered_sample, *result.samples[1:])
        tampered = replace(result, samples=tampered_samples)
        with pytest.raises(ValueError, match="model input digest, definition or interval mismatch"):
            ModelDataset.from_results((_CODEC.encode_json(tampered),))
        with pytest.raises(ValueError, match="unknown field"):
            FeatureStudyResult.decode(_CODEC.encode_json({**expected_fields, "unexpected": True}))

    def test_formal_inspector_passes_registered_feature_engine(self, tmp_path: Path) -> None:
        """Resolve an injected feature engine through the formal retained workflow."""
        study = replace(self._study(), feature_implementation="delegating-trailing")
        config = tmp_path / "study.json"
        config.write_bytes(_CODEC.encode_json(study))
        request = TestPriceDiagnostics._request()
        reader = _AdmittedPrices(
            TestPriceDiagnostics._reader(
                request,
                (
                    TestPriceDiagnostics._item(request, 0, 1, "100", 1, 0),
                    TestPriceDiagnostics._item(request, 8, 9, "110", 2, 1),
                    TestPriceDiagnostics._item(request, 11, 11, "111", 3, 2),
                    TestPriceDiagnostics._item(request, 19, 19, "121", 4, 3),
                ),
            ),
            request,
        )
        resolved: list[str] = []

        def factory(definition: TrailingReturn) -> FeatureDefinition:
            """Record formal resolution and construct the compatible evaluator.

            Args:
                definition: Typed feature settings retained by the study.

            Returns:
                Evaluator preserving the selected definition contract.
            """
            resolved.append(definition.identity)
            return _DelegatingFeature(definition)

        registry = FeatureRegistry()
        registry.register("delegating-trailing", factory)
        with (
            patch("applications.explore.workflow.ResearchReader", return_value=reader),
            patch(
                "applications.explore.workflow.ImplementationIdentity.sha256",
                return_value="a" * 64,
            ),
            patch(
                "applications.explore.workflow.ExperimentSpec.installed_environment",
                return_value="b" * 64,
            ),
        ):
            history = inspect_experiment(
                config,
                tmp_path / "snapshots",
                RawStore(tmp_path / "raw"),
                attempts=tmp_path / "attempts",
                feature_registry=registry,
            )
        assert history.status == "completed"
        assert resolved == [study.feature.identity]

    def test_semantic_identity_bounds_and_holdout_protection(self) -> None:
        """Preserve identity across resource knobs and reject unsafe temporal scopes."""
        study = self._study()
        first = study.selection.inputs[0]
        assert isinstance(first, TradeSelection)
        adjusted = replace(
            study,
            selection=replace(
                study.selection,
                inputs=(
                    replace(first, query=replace(first.query, batch_size=16, max_bytes=524_288)),
                ),
            ),
        )
        assert (
            adjusted.specification(implementation="b" * 64, environment="c" * 64).identity
            == study.specification(implementation="b" * 64, environment="c" * 64).identity
        )
        changed = replace(
            study,
            feature=replace(study.feature, policy=replace(study.feature.policy, min_trades=3)),
        )
        assert (
            changed.specification(implementation="b" * 64, environment="c" * 64).identity
            != study.specification(implementation="b" * 64, environment="c" * 64).identity
        )
        with pytest.raises(ValueError, match="16384"):
            replace(study, feature=replace(study.feature, cadence_us=1))
        assert study.label is not None
        with pytest.raises(ValueError, match="holdout"):
            replace(study, label=replace(study.label, availability_delay_us=20_000_000))
        with pytest.raises(ValueError, match="envelope"):
            replace(study, feature=replace(study.feature, processing_delay_us=1))
        with pytest.raises(ValueError, match="observation cutoff"):
            replace(
                study,
                selection=replace(
                    study.selection,
                    inputs=(replace(first, query=replace(first.query, known_at=_START)),),
                ),
            )
        with pytest.raises(ValueError, match="revision"):
            replace(
                study,
                selection=replace(
                    study.selection,
                    inputs=(replace(first, query=replace(first.query, columns=("price",))),),
                ),
            )
        assert _CODEC.decode_json(_CODEC.encode_json(study), FeatureStudy) == study
        book = BookSelection(
            name="depth",
            query=BookQuery(
                snapshot_id="a" * 64,
                request_identity="b" * 64,
                instrument=first.query.instruments[0],
                start=first.query.start,
                end=first.query.end,
                known_at=first.query.known_at,
                columns=("bids",),
                batch_size=1,
                max_bytes=262_144,
            ),
        )
        with pytest.raises(ValueError, match="trade prices only"):
            replace(study, selection=ResearchSelection(inputs=(book,)))

    def test_retained_feature_failure_and_no_read_after_holdout_rejection(
        self, tmp_path: Path
    ) -> None:
        """The feature dispatcher retains failed reads and consumes final evidence before access."""
        study = self._study()
        study = replace(
            study,
            partition="holdout",
            split=replace(
                study.split,
                validation=TimeWindow(start=_START - timedelta(minutes=1), end=_START),
                holdout=study.split.validation,
            ),
        )
        path = tmp_path / "study.json"
        path.write_bytes(_CODEC.encode_json(study))
        with pytest.raises(OSError):
            inspect_experiment(
                path,
                tmp_path / "missing",
                RawStore(tmp_path / "raw"),
                attempts=tmp_path / "attempts",
            )
        history = AttemptStore(tmp_path / "attempts").histories()[0]
        assert history.status == "failed" and history.events[0].status == "holdout_consumed"
        path.write_bytes(_CODEC.encode_json(replace(study, question="changed comparison")))
        with patch.object(ResearchReader, "read", side_effect=AssertionError("must not read")):
            with pytest.raises(ValueError, match="already consumed"):
                inspect_experiment(
                    path,
                    tmp_path / "missing",
                    RawStore(tmp_path / "raw"),
                    attempts=tmp_path / "attempts",
                )
        assert {item.status for item in AttemptStore(tmp_path / "attempts").histories()} == {
            "failed",
            "rejected",
        }
