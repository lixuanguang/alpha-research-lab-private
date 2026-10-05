"""Run a walk-forward study over published captures with extension components.

This is the maintained example the [QR quickstart](qr-quickstart.md#4-write-and-run-a-study)
walks through. It composes every component role from an installed extension
(here the `engineering-candidates` template) and runs one of two studies over a
published book snapshot and a published trades snapshot:

- `rule`: a named projection of book imbalance and the touch, and the rule-only
  `TouchQuote` order/quote policy;
- `learned`: a named projection of book imbalance and trade flow, the fitted
  `CenterScale` transform, the exact `LeastSquares` estimator, the
  `ForwardMidReturn` label and the learned `PredictionTarget` policy.

Validation folds walk forward over the declared windows; ``--partition holdout``
runs the frozen final holdout once. Every study retains the extension's installed
`RECORD`, so a completed attempt can be packaged as a candidate.

Copy it into your own project and change the components, windows and economics.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
from engineering_candidates import (
    CenterScale,
    FoldNetChart,
    FoldNetMetric,
    ForwardMidReturn,
    LeastSquares,
    PredictionTarget,
    TouchQuote,
)

# project library imports
from applications.explore import StudyComponents, evaluate_study
from financial_units import (
    Currency,
    Dimension,
    ExactRatio,
    Money,
    Price,
    Quantity,
    QuantityKind,
)
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import BookSnapshot
from market_data.query import BookQuery, PublicTradeQuery
from market_data.storage import RawStore
from research.experiments import TemporalSplit, TimeWindow
from research.exploration import (
    BookSelection,
    PublicTradeSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import FeatureSchema, FittedTransform, ProjectionFeature
from research.models import EstimatorLifecycle
from research.observations import InputRequirement, NumericField
from research.studies import (
    CapturedStudyMarket,
    DecisionStudy,
    PublicationPolicy,
    StudyFold,
)
from risk import SpotLimits
from runtime import InstalledExtensions
from serialization import DomainCodec
from simulation import (
    IntentSimulationSpec,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)

_LIMIT = 4_000_000_000
_EXTENSION = "engineering-candidates"


class _Arguments(argparse.Namespace):
    """Type the study's command-line selection."""

    kind: Literal["rule", "learned"]
    partition: Literal["validation", "holdout"]
    snapshots: Path
    raw: Path
    attempts: Path
    book_snapshot: str
    instrument: str
    trades_snapshot: str
    start: datetime
    end: datetime
    train: int
    test: int
    holdout: int
    warmup: int
    folds: int
    cadence: int
    horizon: int
    quantity: Decimal
    lot: Decimal
    tick: Decimal
    cash: Decimal
    threshold: str
    max_levels: int


class StudyWindows:
    """Lay out walk-forward folds and the frozen holdout from declared seconds."""

    def __init__(self, args: _Arguments) -> None:
        """Bind the first training start, window lengths, fold count and cadence."""
        self.args = args
        self.second = timedelta(seconds=1)

    def at(self, seconds: int) -> datetime:
        """Return an instant ``seconds`` after the first training start.

        The first training window starts ``warmup`` seconds after the data, so every
        input window (30 s of trade flow here) is complete at the first decision: a
        fit refuses training rows with missing features.
        """
        return self.args.start + (self.args.warmup + seconds) * self.second

    @property
    def holdout(self) -> TimeWindow:
        """Return the frozen final window after the last validation."""
        start = self.args.train + self.args.folds * self.args.test
        return TimeWindow(start=self.at(start), end=self.at(start + self.args.holdout))

    def split(self, fold: int, *, fitted: bool) -> TemporalSplit:
        """Train on ``[t, t + train)`` and validate on the following ``test`` seconds."""
        train_start = fold * self.args.test
        train_end = train_start + self.args.train
        return TemporalSplit(
            training=TimeWindow(start=self.at(train_start), end=self.at(train_end))
            if fitted
            else None,
            validation=TimeWindow(
                start=self.at(train_end), end=self.at(train_end + self.args.test)
            ),
            holdout=self.holdout,
            samples=(),
            fit_mode="labels" if fitted else "none",
            fit_cutoff=self.at(train_end) if fitted else None,
            embargo_us=0,
            rationale="walk-forward training, then validation, before one frozen holdout",
        )

    def grid(self, window: TimeWindow, *, labelled: bool) -> tuple[datetime, ...]:
        """Return cadence instants inside a window, leaving a label horizon if needed."""
        step = self.args.cadence * self.second
        stop = window.end - (self.args.horizon * self.second if labelled else step)
        instants: list[datetime] = []
        at = window.start + step
        while at < stop:
            instants.append(at)
            at += step
        return tuple(instants)

    def folds(self, *, fitted: bool, holdout: bool) -> tuple[StudyFold, ...]:
        """Declare validation folds, or the single frozen holdout fold."""
        folds: list[StudyFold] = []
        for fold in range(self.args.folds):
            split = self.split(fold, fitted=fitted)
            training = (
                self.grid(split.training, labelled=True)
                if fitted and split.training is not None
                else ()
            )
            folds.append(
                StudyFold(
                    name=f"fold-{fold:02d}",
                    split=split,
                    training_decisions=training,
                    decisions=self.grid(split.validation, labelled=fitted),
                    evaluated_as_of=split.validation.end - timedelta(microseconds=1),
                )
            )
        if not holdout:
            return tuple(folds)
        last = folds[-1]
        return (
            StudyFold(
                name="holdout",
                split=last.split,
                training_decisions=last.training_decisions,
                decisions=self.grid(self.holdout, labelled=False),
                evaluated_as_of=self.holdout.end - timedelta(microseconds=1),
            ),
        )


class QRStudy:
    """Compose sources, components, economics and folds, then run one study."""

    def __init__(self, args: _Arguments) -> None:
        """Open the published inputs and the installed extension identity."""
        self.args = args
        self.windows = StudyWindows(args)
        self.raw = RawStore(args.raw)
        self.reader = ResearchReader(args.snapshots, self.raw, readers=SourceAdapters())
        book = BookSnapshot.read(
            args.snapshots,
            self.raw,
            readers=SourceAdapters(),
            identity=args.book_snapshot,
            max_bytes=_LIMIT,
        )
        matches = tuple(
            identity
            for identity in book.request_identities
            if str(book.selection(identity).request.config.instrument_id) == args.instrument
        )
        if len(matches) != 1:
            raise ValueError("the book snapshot must hold exactly one book for the instrument")
        self.book_request = matches[0]
        self.config = book.selection(self.book_request).request.config
        self.instrument = self.config.instrument_id
        self.dimension = Dimension(instrument_id=self.instrument, kind=QuantityKind.BASE_UNIT)
        self.currency = Currency.from_code(self.config.quote_currency)
        self.artifact = InstalledExtensions().artifact(_EXTENSION)

    def selection(self) -> ResearchSelection:
        """Pin the book and trades snapshots over the whole captured window."""
        args = self.args
        return ResearchSelection(
            inputs=(
                BookSelection(
                    name="book",
                    query=BookQuery(
                        snapshot_id=args.book_snapshot,
                        request_identity=self.book_request,
                        instrument=self.instrument,
                        start=args.start,
                        end=args.end,
                        known_at=args.end,
                        columns=("bids", "asks"),
                        batch_size=10_000,
                        max_bytes=_LIMIT,
                    ),
                ),
                PublicTradeSelection(
                    name="trades",
                    query=PublicTradeQuery(
                        snapshot_id=args.trades_snapshot,
                        instruments=(self.instrument,),
                        start=args.start,
                        end=args.end,
                        known_at=args.end,
                        max_bytes=_LIMIT,
                    ),
                ),
            )
        )

    def book(self, name: str, units: str) -> InputRequirement:
        """Select one book field, fresh within 15 seconds of receipt."""
        return InputRequirement(
            name="book",
            family="book",
            clock="receipt",
            field=NumericField(name=name, units=units),
            max_age_us=15_000_000,
        )

    def flow(self) -> InputRequirement:
        """Select signed trade flow over the last 30 seconds."""
        return InputRequirement(
            name="trades",
            family="trade",
            clock="event",
            field=NumericField(name="signed_flow", units=self.config.base_currency),
            max_age_us=30_000_000,
        )

    def schema(self, inputs: tuple[InputRequirement, ...], names: tuple[str, ...]) -> FeatureSchema:
        """Project the inputs unchanged under the given output names."""
        return FeatureSchema(
            implementation="named-projection",
            inputs=inputs,
            outputs=tuple(
                NumericField(name=name, units=item.field.units)
                for name, item in zip(names, inputs, strict=True)
            ),
            parameters=(),
            mode="batch",
            ttl_us=0,
        )

    def components(self) -> tuple[DecisionStudy, StudyComponents]:
        """Build the selected study and its matching components."""
        args = self.args
        fitted = args.kind == "learned"
        inputs: tuple[InputRequirement, ...]
        if fitted:
            inputs = (self.book("imbalance", "dimensionless"), self.flow())
            schema = self.schema(inputs, ("depth_imbalance", "trade_flow"))
            policy: TouchQuote | PredictionTarget = PredictionTarget.create(
                DomainCodec().encode_json(
                    {
                        "instrument": str(self.instrument),
                        "quantity": str(args.quantity),
                        "threshold": ExactRatio.from_fraction(Fraction(args.threshold)),
                    }
                )
            )
        else:
            inputs = (
                self.book("imbalance", "dimensionless"),
                self.book("bid", "quote/base"),
                self.book("ask", "quote/base"),
            )
            schema = self.schema(inputs, ("depth_imbalance", "bid", "ask"))
            policy = TouchQuote.create(
                DomainCodec().encode_json(
                    {
                        "instrument": str(self.instrument),
                        "quantity": str(args.quantity),
                        "tick": str(args.tick),
                        "currency": self.config.quote_currency,
                        "threshold": ExactRatio.from_fraction(Fraction(args.threshold)),
                    }
                )
            )
        selection = self.selection()
        source = SavedDecisionSource(self.reader, selection, inputs)
        touch = SavedDecisionSource(
            self.reader,
            selection,
            (self.book("bid", "quote/base"), self.book("ask", "quote/base")),
        )
        model = EstimatorLifecycle(LeastSquares()) if fitted else None
        transform = FittedTransform(CenterScale()) if fitted else None
        labels = ForwardMidReturn(touch, args.horizon * self.windows.second) if fitted else None
        market = CapturedStudyMarket(
            args.snapshots,
            self.raw,
            readers=SourceAdapters(),
            snapshot_id=args.book_snapshot,
            request_identity=self.book_request,
            max_bytes=_LIMIT,
            clock_assumption="receipt-as-matching",
            max_levels=args.max_levels,
        )
        execution = LimitOrderExecution(
            LimitExecutionConfig(
                entry_delay_us=1_000,
                cancel_delay_us=0,
                lifetime_us=args.cadence * 1_000_000,
                max_book_age_us=2_000_000,
                take_fraction=Decimal(1),
                queue_ahead_fraction=Decimal(1),
            )
        )
        zero = Price(value=Decimal(0), currency=self.currency, per=self.dimension)
        costs = SpotFeeModel(
            maker=SpotCosts(adverse=zero, fee_rate=Decimal("0.0008"), rounding="half_up"),
            taker=SpotCosts(adverse=zero, fee_rate=Decimal("0.001"), rounding="half_up"),
        )
        limits = SpotLimits(
            maximum=Quantity(value=args.quantity * 4, dimension=self.dimension),
            lot=Quantity(value=args.lot, dimension=self.dimension),
            tick=Price(value=args.tick, currency=self.currency, per=self.dimension),
            product="spot",
            specification_identity=hashlib.sha256(
                DomainCodec().encode_json(("authored-grid", str(args.lot), str(args.tick)))
            ).hexdigest(),
            minimum_order=Quantity(value=args.lot, dimension=self.dimension),
        )
        holdout = args.partition == "holdout"
        folds = self.windows.folds(fitted=fitted, holdout=holdout)
        first = folds[0].split.validation.start if not holdout else self.windows.holdout.start
        metrics = (FoldNetMetric(),)
        charts = (FoldNetChart(),)
        study = DecisionStudy(
            family=f"qr-{args.kind}-study",
            source_identity=source.identity,
            feature_identity=schema.identity,
            policy_identity=policy.identity,
            model_identity=None if model is None else model.identity,
            transform_identity=None if transform is None else transform.identity,
            label_identity=None if labels is None else labels.identity,
            output=policy.output,
            calendar="continuous-utc",
            required_capabilities=(),
            folds=folds,
            partition=args.partition,
            economics=IntentSimulationSpec(
                instance=f"qr-{args.kind}",
                entity=str(self.instrument),
                source_identity=market.identity,
                start=first,
                end=self.windows.holdout.end,
                initial_cash=Money(value=args.cash, currency=self.currency),
                limits=limits,
                execution_identity=execution.identity,
                cost_identity=costs.identity,
            ),
            metrics=tuple(metric.identity for metric in metrics),
            charts=tuple(chart.identity for chart in charts),
            extensions=(self.artifact.fingerprint,),
            parameters=(
                ("receipt-clock-assumption", "receipt-as-matching"),
                ("depth-bound-levels", str(args.max_levels)),
                ("order-grid-assumption", "authored lot and tick"),
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
                "calendar:continuous-utc",
                f"intent:{policy.output}",
                "feature:batch",
                "input:book",
                "input:trade",
            ),
            metrics=metrics,
            charts=charts,
            model=model,
            transform=transform,
            labels=labels,
            artifacts=(self.artifact,),
        )
        return study, components

    def run(self) -> dict[str, object]:
        """Run the study locally and summarize the attempt."""
        study, components = self.components()
        history = evaluate_study(
            study,
            components=components,
            attempts=self.args.attempts,
            publication=PublicationPolicy(mode="local"),
        )
        return {
            "kind": self.args.kind,
            "partition": self.args.partition,
            "attempt_id": history.start.attempt_id,
            "status": history.status,
            "family": study.family,
        }


def main() -> None:
    """Parse the selection, run one study and print its summary as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("rule", "learned"))
    parser.add_argument("--partition", choices=("validation", "holdout"), default="validation")
    for name in ("snapshots", "raw", "attempts"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("book-snapshot", "instrument", "trades-snapshot"):
        parser.add_argument(f"--{name}", required=True)
    for name in ("start", "end"):
        parser.add_argument(f"--{name}", type=datetime.fromisoformat, required=True)
    for name, default in (
        ("train", 600),
        ("test", 300),
        ("holdout", 300),
        ("warmup", 30),
        ("folds", 3),
        ("cadence", 15),
        ("horizon", 60),
        ("max-levels", 20),
    ):
        parser.add_argument(f"--{name}", type=int, default=default)
    for name, decimal in (
        ("quantity", "0.001"),
        ("lot", "0.00001"),
        ("tick", "0.1"),
        ("cash", "1000"),
    ):
        parser.add_argument(f"--{name}", type=Decimal, default=Decimal(decimal))
    parser.add_argument("--threshold", default="0")
    args = parser.parse_args(namespace=_Arguments())
    summary = QRStudy(args).run()
    sys.stdout.write(DomainCodec().encode_json(summary).decode() + "\n")
    if summary["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
