"""Retain configured causal feature diagnostics alongside immutable input selections."""

from __future__ import annotations

# standard library imports
from datetime import timedelta

# project library imports
from market_data.query import QueryReader
from research.experiments.configuration import BacktestRun
from research.features import FeatureValue
from serialization import WireRecord


class ResearchInputs(WireRecord, frozen=True):
    """Bind verified selection and optional diagnostic feature values to resolved choices."""

    configuration_identity: str
    snapshot_id: str
    features: tuple[FeatureValue, ...]
    limitations: tuple[str, ...]

    @classmethod
    def collect(cls, selected: BacktestRun, reader: QueryReader) -> ResearchInputs:
        """Evaluate the existing versioned feature at earlier-only configured cutoffs.

        Args:
            selected: Resolved validation study; model fitting is inapplicable.
            reader: Fully admitted snapshot with unchanged source and knowledge clocks.

        Returns:
            Retainable selection and optional diagnostics; never economic trading inputs.

        Raises:
            ValueError: Snapshot identity or feature cadence differs from configuration.
        """
        if reader.identity != selected.snapshot_id:
            raise ValueError("configured snapshot differs from verified reader")
        features: list[FeatureValue] = []
        feature = selected.feature
        if feature is not None:
            if feature.cadence_us != selected.economics.cadence_seconds * 1_000_000:
                raise ValueError("diagnostic cadence differs from selected observations")
            decision = selected.economics.start + timedelta(microseconds=feature.cadence_us)
            while decision < selected.economics.end:
                end = decision - timedelta(microseconds=feature.processing_delay_us)
                batches = tuple(
                    reader.batches(
                        (selected.economics.binding[2],),
                        start=end - timedelta(microseconds=feature.policy.lookback_us),
                        end=end,
                        known_at=end,
                        columns=("revision",),
                        batch_size=256,
                        mode="cutoff",
                    )
                )
                features.append(
                    feature.evaluate(
                        batches, binding=selected.economics.binding, decision_at=decision
                    )
                )
                decision += timedelta(microseconds=feature.cadence_us)
        return cls(
            configuration_identity=selected.identity,
            snapshot_id=reader.identity,
            features=tuple(features),
            limitations=(
                *(
                    ("Unfitted engineering sample; no validation, holdout or strategy selection.",)
                    if selected.split is None
                    else ()
                ),
                "Observed-price diagnostics are separate from the rule's completed-price inputs.",
                "No fitted model, label retrieval or holdout access is required by this rule.",
            ),
        )
