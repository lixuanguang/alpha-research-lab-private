"""Evaluate both saved public-source venues through complete local costed studies."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# project library imports
from applications.explore import StudyComponents, evaluate_study
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import BookHistory, BookInput
from market_data.storage import RawStore
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory
from research.experiments import AttemptStore, Fingerprint, TemporalSplit, TimeWindow
from research.exploration import (
    BookSelection,
    PublicTradeResearchInput,
    PublicTradeSelection,
    ReferenceResearchInput,
    ReferenceSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import FeatureSchema, ProjectionFeature
from research.observations import InputRequirement, NumericField
from research.studies import (
    CapturedStudyMarket,
    DecisionStudy,
    LedgerCurveChart,
    NetReturnMetric,
    PublicationPolicy,
    ResultManifest,
    StudyArtifact,
    StudyFold,
    StudyReportReader,
    StudyResult,
)
from risk import SpotLimits
from serialization import DomainCodec
from simulation import (
    IntentSimulationSpec,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)
from strategies import DecisionContext, DecisionTransition, TargetIntent


class _Arguments(argparse.Namespace):
    """Bind original publication and capture roots to a new output directory."""

    selection: Path
    snapshots: Path
    raw: Path
    captures: Path
    output: Path


class _BuyThenFlat:
    """Exercise actual nonmissing saved features through one buy and one flat target."""

    def __init__(self, quantity: Quantity, fields: tuple[NumericField, ...]) -> None:
        """Bind an exact base-unit quantity and the selected complete feature signature."""
        quantity.model_copy()
        if type(fields) is not tuple or len(fields) != 3:
            raise ValueError("captured study rule requires three saved source features")
        self._quantity, self._fields = quantity, fields

    @property
    def identity(self) -> str:
        """Pin the two-decision rule, quantity and all consumed named fields."""
        return hashlib.sha256(
            DomainCodec().encode_json(("saved-buy-then-flat", self._quantity, self._fields))
        ).hexdigest()

    @property
    def output(self) -> Literal["target"]:
        """Declare absolute spot holding targets."""
        return "target"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the exact three fields and no implicit model prediction."""
        if fields != self._fields or prediction is not None:
            raise ValueError("captured study rule feature signature differs")

    def initial_state(self) -> bytes:
        """Start before the first long target."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Refuse an unknown or reused two-decision policy state."""
        if type(state) is not bytes or state not in (b"0", b"1", b"2"):
            raise ValueError("invalid captured study policy state")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Require all saved inputs, then request long and later flat once each."""
        self.validate_state(state)
        if context.features.fields != self._fields or any(
            value is None for value in context.features.values
        ):
            raise ValueError("captured study decision lacks a selected saved-source value")
        if state == b"2":
            raise ValueError("captured study policy supports exactly two decisions")
        quantity = (
            self._quantity
            if state == b"0"
            else Quantity(value=Decimal(0), dimension=self._quantity.dimension)
        )
        return DecisionTransition(
            intent=TargetIntent(quantity=quantity),
            state=b"1" if state == b"0" else b"2",
        )


class _CapturedScenario:
    """Resolve one selected native venue into pinned causal inputs and local economics."""

    def __init__(
        self,
        selection: ResearchSelection,
        reader: ResearchReader,
        captures: Path,
        consumer_artifact: StudyArtifact,
    ) -> None:
        """Keep original inputs and the exact external consumer source bytes."""
        selection.__post_init__()
        self._selection, self._reader, self._captures = selection, reader, captures
        self._consumer_artifact = consumer_artifact
        self._adapters = SourceAdapters()
        self._codec = DomainCodec()

    def build(
        self, book_selection: BookSelection
    ) -> tuple[str, DecisionStudy, StudyComponents, str, str]:
        """Select two known decisions before the untouched later holdout."""
        trade_selection = next(
            item for item in self._selection.inputs if isinstance(item, PublicTradeSelection)
        )
        reference_selection = next(
            item for item in self._selection.inputs if isinstance(item, ReferenceSelection)
        )
        chosen = ResearchSelection(inputs=(trade_selection, reference_selection, book_selection))
        dataset = self._reader.read(chosen)
        trades = next(item for item in dataset.inputs if isinstance(item, PublicTradeResearchInput))
        reference = next(
            item for item in dataset.inputs if isinstance(item, ReferenceResearchInput)
        )
        instrument = next(
            item
            for item in trades.result.instruments
            if item.instrument_id == book_selection.query.instrument
        )
        capture_directory = self._capture_directory(instrument.venue)
        captured = BookInput.read(capture_directory, max_records=100)
        if (
            captured.request.identity != book_selection.query.request_identity
            or captured.request.config.instrument_id != instrument.instrument_id
        ):
            raise ValueError("saved book selection differs from original captured request")
        market = CapturedStudyMarket(
            captured,
            RawStore(capture_directory),
            readers=self._adapters,
            max_bytes=32_000_000,
            clock_assumption="receipt-as-matching",
        )
        quality = captured.admit(
            RawStore(capture_directory), readers=self._adapters, max_bytes=32_000_000
        )
        if quality.canonical is None:
            raise ValueError("saved capture is not admitted by native reconstruction")
        history = self._codec.decode_json(quality.canonical, BookHistory)
        eligible = tuple(
            row
            for row in history.observations
            if row.status == "degraded"
            and row.outcome in ("snapshot", "update")
            and (bool(row.bids and row.asks) or bool(row.orders))
            and row.received_ns is not None
        )
        if len(eligible) < 75:
            raise ValueError("captured study requires enough observed eligible book states")
        first = self._receipt(eligible[0].received_ns)
        last = self._receipt(eligible[-1].received_ns)
        decisions = (
            self._receipt(eligible[10].received_ns) + timedelta(microseconds=1),
            self._receipt(eligible[70].received_ns) + timedelta(microseconds=1),
        )
        validation = TimeWindow(start=first, end=last + timedelta(microseconds=2))
        if not validation.start < decisions[0] < decisions[1] < validation.end:
            raise ValueError("captured decision clocks cannot support buy and flat")
        holdout = TimeWindow(
            start=validation.end + timedelta(seconds=1),
            end=validation.end + timedelta(seconds=2),
        )
        split = TemporalSplit(
            training=None,
            validation=validation,
            holdout=holdout,
            samples=(),
            fit_mode="none",
            fit_cutoff=None,
            embargo_us=0,
            rationale=(
                "No fitting; observed validation precedes an unobserved later holdout "
                "with no captured market sample."
            ),
        )
        dimension = Dimension(instrument_id=instrument.instrument_id, kind=QuantityKind.BASE_UNIT)
        currency = Currency.from_code(instrument.quote_currency)
        target = Quantity(value=Decimal("0.0001"), dimension=dimension)
        limits, reference_history, reference_age_us, grid_assumption = self._limits(
            instrument, reference.history, target, currency, decisions[0]
        )
        requirements = (
            InputRequirement(
                name=trade_selection.name,
                family="trade",
                clock="event",
                field=NumericField(name="quantity", units=instrument.base_currency),
                max_age_us=86_400_000_000,
            ),
            InputRequirement(
                name=reference_selection.name,
                family="reference",
                clock="valid",
                field=NumericField(name="minimum_quantity", units=instrument.base_currency),
                max_age_us=86_400_000_000,
            ),
            InputRequirement(
                name=book_selection.name,
                family="book",
                clock="receipt",
                field=NumericField(name="imbalance", units="dimensionless"),
                max_age_us=1_000_000,
            ),
        )
        source = SavedDecisionSource(self._reader, chosen, requirements)
        schema = FeatureSchema(
            implementation="named-projection",
            inputs=requirements,
            outputs=(
                NumericField(name="trade_size", units=instrument.base_currency),
                NumericField(name="minimum_quantity", units=instrument.base_currency),
                NumericField(name="imbalance", units="dimensionless"),
            ),
            parameters=(),
            mode="batch",
            ttl_us=0,
        )
        policy = _BuyThenFlat(target, schema.outputs)
        execution = LimitOrderExecution(
            LimitExecutionConfig(
                entry_delay_us=1_000,
                cancel_delay_us=0,
                lifetime_us=1_000_000,
                max_book_age_us=2_000_000,
                take_fraction=Decimal("1"),
                queue_ahead_fraction=Decimal("1"),
            )
        )
        costs = SpotFeeModel(
            maker=SpotCosts(
                adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                fee_rate=Decimal("0.0005"),
                rounding="half_up",
            ),
            taker=SpotCosts(
                adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                fee_rate=Decimal("0.001"),
                rounding="half_up",
            ),
        )
        economics = IntentSimulationSpec(
            instance=f"{instrument.venue}-captured-research",
            entity=str(instrument.instrument_id),
            source_identity=market.identity,
            start=validation.start,
            end=validation.end,
            initial_cash=Money(value=Decimal("1000"), currency=currency),
            limits=limits,
            execution_identity=execution.identity,
            cost_identity=costs.identity,
            reference_history=reference_history,
            reference_max_age_us=reference_age_us,
        )
        study = DecisionStudy(
            family=f"{instrument.venue}-captured-research-study",
            source_identity=source.identity,
            feature_identity=schema.identity,
            policy_identity=policy.identity,
            model_identity=None,
            transform_identity=None,
            label_identity=None,
            output="target",
            calendar=instrument.calendar,
            required_capabilities=(),
            folds=(
                StudyFold(
                    name=f"{instrument.venue}-validation",
                    split=split,
                    training_decisions=(),
                    decisions=decisions,
                    evaluated_as_of=decisions[-1],
                ),
            ),
            partition="validation",
            economics=economics,
            metrics=(NetReturnMetric.identity,),
            charts=(LedgerCurveChart.identity,),
            extensions=(self._consumer_artifact.fingerprint,),
            parameters=(
                ("original-selection", self._selection.identity),
                ("source-selection", chosen.identity),
                ("captured-request", captured.request.identity),
                ("receipt-clock-assumption", "receipt-as-matching"),
                ("order-grid-assumption", grid_assumption),
                ("source-scope", "offline research; no venue execution authority"),
                ("holdout-status", "later unobserved window; never evaluated"),
            ),
        )
        components = StudyComponents(
            source=source,
            market=market,
            feature=ProjectionFeature(schema),
            policy=policy,
            execution=execution,
            costs=costs,
            capabilities=(
                "product:spot",
                f"calendar:{instrument.calendar}",
                "input:trade",
                "input:reference",
                "input:book",
                "feature:batch",
                "intent:target",
            ),
            metrics=(NetReturnMetric(),),
            charts=(LedgerCurveChart(),),
            artifacts=(self._consumer_artifact,),
        )
        return instrument.venue, study, components, captured.raw.sha256, grid_assumption

    def _capture_directory(self, venue: str) -> Path:
        """Find exactly one completed original recording under the named venue root."""
        root = self._captures / f"{venue}-capture"
        candidates = tuple(
            path for path in root.iterdir() if path.is_dir() and (path / "request.json").is_file()
        )
        if len(candidates) != 1:
            raise ValueError(f"expected one completed {venue} capture directory")
        return candidates[0]

    @staticmethod
    def _receipt(received_ns: int | None) -> datetime:
        """Round original nanosecond receipt upward to a supported UTC microsecond."""
        if type(received_ns) is not int or received_ns <= 0:
            raise ValueError("saved capture lacks an original receipt clock")
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=(received_ns + 999) // 1000
        )

    def _limits(
        self,
        instrument: InstrumentDefinition,
        history: ReferenceHistory,
        maximum: Quantity,
        currency: Currency,
        at: datetime,
    ) -> tuple[SpotLimits, ReferenceHistory | None, int | None, str]:
        """Use then-known venue rules or explicitly mark incomplete grids as authored."""
        specification = history.resolve(instrument.instrument_id, valid_at=at, known_at=at)
        if specification is None or specification.minimum_quantity is None:
            raise ValueError("saved captured study lacks a then-known minimum order size")
        if specification.price_tick is not None and specification.quantity_step is not None:
            return (
                SpotLimits.from_reference(
                    history,
                    maximum=maximum,
                    quote_currency=currency,
                    valid_at=at,
                    known_at=at,
                    max_age=timedelta(hours=1),
                ),
                history,
                3_600_000_000,
                "then-known venue reference grids",
            )
        if instrument.venue != "bitfinex":
            raise ValueError("unknown venue grid has no authored scenario")
        lot = Decimal("0.00001")
        tick = Decimal("0.01")
        identity = hashlib.sha256(
            self._codec.encode_json(("authored-bitfinex-grid", specification.identity, lot, tick))
        ).hexdigest()
        return (
            SpotLimits(
                maximum=maximum,
                lot=Quantity(value=lot, dimension=maximum.dimension),
                tick=Price(value=tick, currency=currency, per=maximum.dimension),
                product="spot",
                specification_identity=identity,
                minimum_order=Quantity(
                    value=specification.minimum_quantity, dimension=maximum.dimension
                ),
            ),
            None,
            None,
            "authored Bitfinex 0.01 USD tick and 0.00001 BTC lot; "
            "saved reference minimum retained; venue grids unverified",
        )


def main() -> None:
    """Run two original saved-source research studies and export their verified outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection", "snapshots", "raw", "captures", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    codec = DomainCodec()
    selection = codec.decode_json(args.selection.read_bytes(), ResearchSelection)
    reader = ResearchReader(args.snapshots, RawStore(args.raw), readers=SourceAdapters())
    consumer_bytes = Path(__file__).read_bytes()
    consumer_artifact = StudyArtifact(
        fingerprint=Fingerprint(
            name="captured-study-consumer",
            sha256=hashlib.sha256(consumer_bytes).hexdigest(),
        ),
        payload=consumer_bytes,
    )
    scenarios = _CapturedScenario(selection, reader, args.captures, consumer_artifact)
    selections = tuple(item for item in selection.inputs if isinstance(item, BookSelection))
    if len(selections) != 2 or {item.name for item in selections} != {
        "okx_book",
        "bitfinex_book",
    }:
        raise ValueError("captured study requires both original named venue selections")
    prepared = tuple(scenarios.build(item) for item in selections)
    args.output.mkdir(parents=True, exist_ok=False)
    completed: list[dict[str, object]] = []
    for venue, study, components, original_sha256, grid_assumption in prepared:
        venue_output = args.output / venue
        venue_output.mkdir()
        ResultManifest.export(venue_output / "config.json", codec.encode_json(study))
        history = evaluate_study(
            venue_output / "config.json",
            components=components,
            attempts=venue_output / "attempts",
            publication=PublicationPolicy(mode="local"),
        )
        if history.status != "completed":
            raise ValueError("captured research study did not complete")
        attempt = history.start.attempt_id
        store = AttemptStore(venue_output / "attempts")
        result = StudyResult.read(store, attempt)
        report = StudyReportReader.read(store, attempt)
        fold = result.folds[0]
        fills = tuple(fill for order in fold.economics.orders for fill in order.fills)
        if not fills:
            raise ValueError("captured research study produced no costed spot fill")
        for artifact, destination in (
            ("study-result", "study-result.json"),
            ("study-report", "study-report.json"),
            ("report-html", "report.html"),
        ):
            ResultManifest.export(venue_output / destination, store.artifact(attempt, artifact))
        parameters = dict(study.parameters)
        completed.append(
            {
                "venue": venue,
                "attempt_id": attempt,
                "semantic_identity": history.start.run_identity,
                "original_selection_identity": parameters["original-selection"],
                "source_selection_identity": parameters["source-selection"],
                "captured_request_identity": parameters["captured-request"],
                "original_capture_sha256": original_sha256,
                "captured_market_identity": components.market.identity,
                "decisions": len(fold.decisions),
                "fills": len(fills),
                "fees": str(sum((fill.fee.value for fill in fills), Decimal(0))),
                "fee_currency": study.economics.initial_cash.currency.code,
                "net_return": fold.economics.net_return,
                "report_identity": report.study_identity,
                "grid_assumption": grid_assumption,
                "scope": (
                    "offline research; receipt-as-matching; "
                    "no passive-fill or venue execution claim"
                ),
            }
        )
    print(codec.encode_json({"completed": tuple(completed)}).decode())


if __name__ == "__main__":
    main()
