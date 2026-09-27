"""Retain aligned feature diagnostics and delayed labels over pinned saved trade inputs."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from research.experiments import (
    ExperimentSpec,
    Fingerprint,
    SampleInterval,
    TemporalSplit,
    TimeWindow,
)
from research.exploration.selection import (
    ResearchReader,
    ResearchSelection,
    TradeResearchInput,
    TradeSelection,
)
from research.features import FeatureDefinition, FeatureRegistry, FeatureValue, TrailingReturn
from research.labels import ForwardReturn, LabelValue
from research.results import FeatureStudyResult
from serialization import DomainCodec, WireRecord


class FeatureStudy(WireRecord, frozen=True, kw_only=True):
    """Configure an unfitted diagnostic with separate inputs and decision windows.

    The generated decision/instrument grid is limited to 16,384 rows.
    """

    schema_version: Literal["feature-study-v1"] = "feature-study-v1"
    family: str
    question: str
    selection: ResearchSelection
    split: TemporalSplit
    partition: Literal["validation", "holdout"]
    decisions: TimeWindow
    feature: TrailingReturn
    label: ForwardReturn | None
    feature_implementation: str = "trailing-return-v1"

    def __post_init__(self) -> None:
        """Reject unsupported sources, temporal leakage and unbounded materialized studies."""
        if self.schema_version != "feature-study-v1":
            raise ValueError("unsupported feature study schema")
        for text in (self.family, self.question):
            if type(text) is not str or not text.strip():
                raise ValueError("study requires a family and research question")
        if (
            type(self.feature_implementation) is not str
            or not self.feature_implementation
            or self.feature_implementation != self.feature_implementation.strip()
        ):
            raise ValueError("feature study requires a valid implementation identity")
        if (
            type(self.selection) is not ResearchSelection
            or type(self.split) is not TemporalSplit
            or type(self.decisions) is not TimeWindow
            or type(self.feature) is not TrailingReturn
        ):
            raise TypeError(
                "feature study requires typed selection, split, decisions and definition"
            )
        self.selection.__post_init__()
        self.split.__post_init__()
        self.decisions.__post_init__()
        self.feature.__post_init__()
        if self.label is not None:
            if type(self.label) is not ForwardReturn:
                raise TypeError("feature study requires ForwardReturn or no label")
            self.label.__post_init__()
        if (
            self.partition not in ("validation", "holdout")
            or self.split.fit_mode != "none"
            or self.split.samples
        ):
            raise ValueError("diagnostics require no fit and generate their own sample intervals")
        window = self.split.validation if self.partition == "validation" else self.split.holdout
        if not window.start <= self.decisions.start < self.decisions.end <= window.end:
            raise ValueError("decisions must lie in the selected split partition")
        cadence = timedelta(microseconds=self.feature.cadence_us)
        count = (
            self.decisions.end - self.decisions.start - timedelta(microseconds=1)
        ) // cadence + 1
        bindings = sum(
            sum(binding[2] in item.query.instruments for binding in item.query.precedence)
            for item in self.selection.inputs
            if isinstance(item, TradeSelection)
        )
        if count * bindings > 16_384:
            raise ValueError("feature study exceeds 16384 decision/instrument rows")
        last = self.decisions.start + (count - 1) * cadence
        first_input = self.decisions.start - timedelta(
            microseconds=self.feature.processing_delay_us + self.feature.policy.lookback_us
        )
        last_input = last - timedelta(microseconds=self.feature.processing_delay_us)
        if self.label is not None:
            first_input = min(
                first_input,
                self.decisions.start
                + timedelta(microseconds=self.label.horizon_us - self.label.policy.lookback_us),
            )
            last_input = last + timedelta(microseconds=self.label.horizon_us)
            information_end = last_input + timedelta(microseconds=self.label.availability_delay_us)
            if self.partition == "validation" and information_end >= self.split.holdout.start:
                raise ValueError("validation outcome information reaches the frozen holdout")
        for item in self.selection.inputs:
            if not isinstance(item, TradeSelection):
                raise ValueError(
                    "feature study supports trade prices only; book/macro formulas absent"
                )
            if "revision" not in item.query.columns:
                raise ValueError("feature study requires revision input for causal event clocks")
            if not item.query.start <= first_input < last_input <= item.query.end:
                raise ValueError(
                    "selected input envelope must contain lookback and outcome windows"
                )
            if item.query.known_at < last:
                raise ValueError("study observation cutoff precedes a feature decision")

    def specification(self, *, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the declared diagnostic and optional outcome to reproducible semantic inputs.

        Args:
            implementation: SHA-256 of the actual installed implementation and resources.
            environment: SHA-256 of the actual interpreter/platform and installed dependencies.

        Returns:
            Identity excluding output paths, batching, byte ceilings and execution clocks.
        """
        self.__post_init__()
        components = [
            Fingerprint(name="installed-implementation", sha256=implementation),
            Fingerprint(name="feature-definition", sha256=self.feature.identity),
        ]
        if self.label is not None:
            components.append(Fingerprint(name="label-definition", sha256=self.label.identity))
        return ExperimentSpec(
            family=self.family,
            inputs=(
                Fingerprint(name="research-selection", sha256=self.selection.identity),
                Fingerprint(
                    name="decision-window",
                    sha256=hashlib.sha256(DomainCodec().encode_json(self.decisions)).hexdigest(),
                ),
            ),
            components=tuple(components),
            parameters=(
                ("feature-implementation", self.feature_implementation),
                ("partition", self.partition),
                ("question", self.question),
            ),
            seeds=(),
            environment_sha256=environment,
            split=self.split,
        )

    def resolve_feature(self, registry: FeatureRegistry | None = None) -> FeatureDefinition:
        """Resolve this study's definition through one explicit feature registry.

        Args:
            registry: Optional registry; the default retains the installed feature.

        Returns:
            Validated feature definition for this study.

        Raises:
            ValueError: The selected implementation is not registered.
        """
        self.__post_init__()
        resolved_registry = FeatureRegistry() if registry is None else registry
        return resolved_registry.resolve(self.feature_implementation, self.feature)

    def evaluate(self, reader: ResearchReader, *, registry: FeatureRegistry | None = None) -> bytes:
        """Read every feature at its own cutoff and retain separate aligned forward outcomes.

        Args:
            reader: Explicit saved-data reader; the application records holdout access first.
            registry: Optional feature registry used to resolve the selected definition.

        Returns:
            Deterministic JSON with ordered feature/label rows, input evidence, definitions,
            source selection identity and truthful sample intervals. No state is fitted.

        Raises:
            ValueError: The saved reader returns an incompatible input family.
        """
        definition = self.resolve_feature(registry)
        codec = DomainCodec()
        features: list[tuple[str, FeatureValue]] = []
        labels: list[tuple[str, LabelValue]] = []
        samples: list[SampleInterval] = []
        decision = self.decisions.start
        while decision < self.decisions.end:
            feature_end = decision - timedelta(microseconds=definition.processing_delay_us)
            feature_selection = self._selection(
                end=feature_end, known_at=feature_end, lookback_us=definition.policy.lookback_us
            )
            dataset = reader.read(feature_selection)
            outcome_dataset = None
            if self.label is not None:
                outcome_at = decision + timedelta(microseconds=self.label.horizon_us)
                available = outcome_at + timedelta(microseconds=self.label.availability_delay_us)
                if available <= self.selection.inputs[0].query.known_at:
                    outcome_dataset = reader.read(
                        self._selection(
                            end=outcome_at,
                            known_at=available,
                            lookback_us=self.label.policy.lookback_us,
                        )
                    )
            for index, item in enumerate(dataset.inputs):
                if not isinstance(item, TradeResearchInput):
                    raise ValueError("diagnostic reader returned a non-trade input")
                for coverage in item.coverage:
                    feature = definition.evaluate(
                        item.batches, binding=coverage.binding, decision_at=decision
                    )
                    row_id = codec.encode_json((item.name, coverage.binding, decision)).decode()
                    label = None
                    if self.label is not None:
                        outcome_batches = None
                        if outcome_dataset is not None:
                            outcome_input = outcome_dataset.inputs[index]
                            if not isinstance(outcome_input, TradeResearchInput):
                                raise ValueError("diagnostic reader returned a non-trade outcome")
                            outcome_batches = outcome_input.batches
                        label = self.label.evaluate(
                            feature,
                            outcome_batches,
                            known_at=self.selection.inputs[0].query.known_at,
                        )
                        labels.append((row_id, label))
                    features.append((row_id, feature))
                    samples.append(
                        SampleInterval(
                            row_id=row_id,
                            input_sha256=hashlib.sha256(
                                codec.encode_json((feature, label))
                            ).hexdigest(),
                            decision_at=decision,
                            information_start=feature.window.start
                            if label is None
                            else label.information_start,
                            information_end=decision if label is None else label.information_end,
                            features_available_at=feature.available_at,
                            label_available_at=None if label is None else label.available_at,
                        )
                    )
            decision += timedelta(microseconds=definition.cadence_us)
        return codec.encode_json(
            FeatureStudyResult(
                schema_version="feature-study-result-v1",
                selection_identity=self.selection.identity,
                feature_definition=self.feature,
                label_definition=self.label,
                features=tuple(features),
                labels=tuple(labels),
                samples=tuple(samples),
                split_identity=self.split.identity,
                fitting="not applicable: fixed diagnostic has no fitted state",
                scope="exploratory_degraded",
            )
        )

    def _selection(
        self, *, end: datetime, known_at: datetime, lookback_us: int
    ) -> ResearchSelection:
        """Resolve only the declared cutoff window while preserving pinned source configuration."""
        return ResearchSelection(
            inputs=tuple(
                replace(
                    item,
                    query=replace(
                        item.query,
                        start=end - timedelta(microseconds=lookback_us),
                        end=end,
                        known_at=known_at,
                    ),
                )
                for item in self.selection.inputs
                if isinstance(item, TradeSelection)
            )
        )
