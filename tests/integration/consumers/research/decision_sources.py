"""Reopen retained venue inputs through generic named features without acquiring fresh data."""

from __future__ import annotations

# standard library imports
import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# project library imports
from applications.explore import inspect_decisions
from configuration import DecisionRun
from financial_units import Dimension, Quantity, QuantityKind
from market_data.adapters.sources import SourceAdapters
from market_data.query import BookMarketRow
from market_data.storage import RawStore
from research.exploration import (
    BookResearchInput,
    BookSelection,
    PublicTradeResearchInput,
    PublicTradeSelection,
    ReferenceSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.features import FeatureSchema, ProjectionFeature
from research.observations import InputRequirement, NumericField
from serialization import DomainCodec
from strategies import ConfirmedSignal


class _Arguments(argparse.Namespace):
    """Select existing immutable inputs and a separate output root."""

    selection: Path
    snapshots: Path
    raw: Path
    output: Path


def main() -> None:
    """Qualify named trade/book/reference consumption for each supplied venue listing."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection", "snapshots", "raw", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args(namespace=_Arguments())
    args.output.mkdir(exist_ok=False)
    codec = DomainCodec()
    selection = codec.decode_json(args.selection.read_bytes(), ResearchSelection)
    reader = ResearchReader(args.snapshots, RawStore(args.raw), readers=SourceAdapters())
    dataset = reader.read(selection)
    trades = next(item for item in dataset.inputs if isinstance(item, PublicTradeResearchInput))
    trade_selection = next(
        item for item in selection.inputs if isinstance(item, PublicTradeSelection)
    )
    reference_selection = next(
        item for item in selection.inputs if isinstance(item, ReferenceSelection)
    )
    results: list[tuple[str, str]] = []
    for instrument in trades.result.instruments:
        book_selection = next(
            item
            for item in selection.inputs
            if isinstance(item, BookSelection) and item.query.instrument == instrument.instrument_id
        )
        book = next(
            item
            for item in dataset.inputs
            if isinstance(item, BookResearchInput) and item.name == book_selection.name
        )
        states = tuple(
            row for batch in book.batches for row in batch.rows if isinstance(row, BookMarketRow)
        )
        if not states:
            raise ValueError("saved venue sample has no decision-eligible book state")
        last = states[-1]
        at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=(last.received_ns + 999) // 1000
        )
        chosen = ResearchSelection(inputs=(trade_selection, reference_selection, book_selection))
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
        source = SavedDecisionSource(reader, chosen, requirements)
        schema = FeatureSchema(
            implementation="named-projection-v1",
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
        policy = ConfirmedSignal(
            field=schema.outputs[2],
            quantity=Quantity(
                value=Decimal("1"),
                dimension=Dimension(
                    instrument_id=instrument.instrument_id, kind=QuantityKind.BASE_UNIT
                ),
            ),
            confirmations=1,
        )
        config = DecisionRun(
            instance=f"{instrument.venue}-saved-reference",
            entity=str(instrument.instrument_id),
            product=instrument.product,
            calendar=instrument.calendar,
            source_identity=source.identity,
            feature_identity=schema.identity,
            policy_identity=policy.identity,
            model_identity=None,
            transform_identity=None,
            output="target",
            decisions=(at,),
            required_capabilities=(),
        )
        history = inspect_decisions(
            config,
            source=source,
            feature=ProjectionFeature(schema),
            policy=policy,
            capabilities=(
                "product:spot",
                "calendar:continuous-utc",
                "input:trade",
                "input:reference",
                "input:book",
                "feature:batch",
                "intent:target",
            ),
            attempts=args.output / "attempts",
            family=f"{instrument.venue}-saved-decisions",
        )
        assert history.status == "completed"
        result = history.events[-1].result
        assert result is not None
        (args.output / f"{instrument.venue}.json").write_bytes(result)
        results.append((instrument.venue, history.start.attempt_id))
    print(
        codec.encode_json(
            {
                "attempts": tuple(results),
                "scope": "retained_source_reopening;no_fill_or_empirical_acceptance",
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
