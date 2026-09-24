"""Describe reproducible walk-forward studies over explicitly supplied decision components."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.experiments import ExperimentSpec, Fingerprint, TemporalSplit, TimeWindow
from research.studies.evaluation import TrialEvaluation
from serialization import DomainCodec, WireRecord
from simulation import IntentSimulationSpec


class StudyFold(WireRecord, frozen=True):
    """Freeze schedules and earlier-only fitting policy before any input is read.

    The configured split has no sample records. The application derives those
    records from actual feature/outcome bytes and retains the resolved split.
    Each fold starts independent feature, strategy and cash state; the study is
    a walk-forward evaluation, not a continuously invested stitched portfolio.
    """

    name: str
    split: TemporalSplit
    training_decisions: tuple[datetime, ...]
    decisions: tuple[datetime, ...]
    evaluated_as_of: datetime

    def __post_init__(self) -> None:
        """Reject precomputed samples, invalid schedules and implicit fitting choices."""
        self.split.__post_init__()
        self._require_utc(self.evaluated_as_of, field_name="evaluation cutoff")
        if type(self.name) is not str or not self.name or self.split.samples:
            raise ValueError("fold requires a name and an unresolved sample inventory")
        for schedule in (self.training_decisions, self.decisions):
            if type(schedule) is not tuple or len(schedule) > 1024:
                raise ValueError("study schedule must be an immutable bounded tuple")
            for at in schedule:
                self._require_utc(at, field_name="decision")
            if any(a >= b for a, b in pairwise(schedule)):
                raise ValueError("study schedule must strictly advance")
        if not self.decisions or self.evaluated_as_of < self.decisions[-1]:
            raise ValueError("fold requires decisions preceding evaluation cutoff")
        if self.split.fit_mode == "none":
            if self.training_decisions:
                raise ValueError("unfitted rule must not manufacture a training sample")
        elif (
            not self.training_decisions
            or self.split.training is None
            or any(not self.split.training.contains(at) for at in self.training_decisions)
        ):
            raise ValueError("fitted fold requires an explicit earlier training schedule")


class DecisionStudy(WireRecord, frozen=True, kw_only=True):
    """Select a complete bounded study with immutable adapter and report identities.

    Trusted supplied code implements these identities; JSON never imports code.
    Paths and publication destinations do not change economic run identity.
    Supported economics remain cash-funded spot, with separately qualified source
    and calendar capabilities. A declaration cannot grant execution authority.
    """

    family: str
    source_identity: str
    feature_identity: str
    policy_identity: str
    model_identity: str | None
    transform_identity: str | None
    label_identity: str | None
    output: Literal["target", "exposure", "order", "quote"]
    calendar: str
    required_capabilities: tuple[str, ...]
    folds: tuple[StudyFold, ...]
    partition: Literal["validation", "holdout"]
    economics: IntentSimulationSpec
    metrics: tuple[Fingerprint, ...]
    charts: tuple[Fingerprint, ...]
    extensions: tuple[Fingerprint, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    seeds: tuple[tuple[str, int], ...] = ()
    schema_version: Literal["decision-study-v1"] = "decision-study-v1"

    def __post_init__(self) -> None:
        """Validate complete selections and nonoverlapping folds before creating attempts."""
        if (
            self.schema_version != "decision-study-v1"
            or self.partition not in ("validation", "holdout")
            or self.output not in ("target", "exposure", "order", "quote")
        ):
            raise ValueError("unsupported decision study schema or partition")
        for value in (
            self.family,
            self.source_identity,
            self.feature_identity,
            self.policy_identity,
            self.calendar,
        ):
            if type(value) is not str or not value:
                raise ValueError("study requires explicit component and family identities")
        for optional in (self.model_identity, self.transform_identity, self.label_identity):
            if optional is not None and (type(optional) is not str or not optional):
                raise ValueError("invalid optional study component")
        self.economics.__post_init__()
        if type(self.folds) is not tuple or not 1 <= len(self.folds) <= 32:
            raise ValueError("study requires one to 32 explicit folds")
        if len({f.name for f in self.folds}) != len(self.folds):
            raise ValueError("fold names must be unique")
        if self.partition == "holdout" and len(self.folds) != 1:
            raise ValueError("final holdout requires one frozen evaluation")
        previous: TimeWindow | None = None
        for fold in self.folds:
            fold.__post_init__()
            if fold.split.holdout != self.folds[0].split.holdout:
                raise ValueError("walk-forward folds must share the frozen final holdout")
            window = self.window(fold)
            if any(not window.contains(at) for at in fold.decisions):
                raise ValueError("decisions must lie in the selected evaluation partition")
            if not window.start <= fold.evaluated_as_of <= window.end:
                raise ValueError("evaluation cutoff must remain within its partition")
            if self.partition == "validation" and fold.evaluated_as_of >= fold.split.holdout.start:
                raise ValueError("validation label cutoff must precede the frozen holdout")
            self.market_window(fold)
            if previous is not None and previous.end > window.start:
                raise ValueError("walk-forward evaluations must advance without overlap")
            previous = window
            expected = (
                "labels"
                if self.model_identity
                else "features"
                if self.transform_identity
                else "none"
            )
            if fold.split.fit_mode != expected or (
                self.model_identity is not None and self.label_identity is None
            ):
                raise ValueError("fitting policy does not match selected implementations")
        for selections in (self.metrics, self.charts, self.extensions):
            if type(selections) is not tuple:
                raise TypeError("report selections must be immutable")
            for item in selections:
                item.__post_init__()
            if len({item.name for item in selections}) != len(selections):
                raise ValueError("duplicate report selection")
        if not self.metrics or not self.charts:
            raise ValueError("study requires explicit metric and chart selections")
        if (
            type(self.required_capabilities) is not tuple
            or any(type(v) is not str or not v for v in self.required_capabilities)
            or len(set(self.required_capabilities)) != len(self.required_capabilities)
        ):
            raise ValueError("invalid study capabilities")
        if (
            type(self.parameters) is not tuple
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or not pair[0]
                or type(pair[1]) is not str
                for pair in self.parameters
            )
            or len(dict(self.parameters)) != len(self.parameters)
        ):
            raise ValueError("study parameters require unique immutable text pairs")
        if (
            type(self.seeds) is not tuple
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or not pair[0]
                or type(pair[1]) is not int
                or pair[1] < 0
                or pair[0] == "optuna-grid"
                for pair in self.seeds
            )
            or len(dict(self.seeds)) != len(self.seeds)
        ):
            raise ValueError("study seeds require unique nonnegative integer pairs")

    def window(self, fold: StudyFold) -> TimeWindow:
        """Return the explicitly selected validation or final holdout interval."""
        return fold.split.validation if self.partition == "validation" else fold.split.holdout

    def market_window(self, fold: StudyFold) -> TimeWindow:
        """Keep inclusive execution input reads strictly before an untouched holdout.

        Valuation still occurs at the configured terminal time using the latest
        fresh earlier book. A contiguous validation boundary must not consume the
        first held-out observation merely to obtain a terminal mark.
        """
        window = self.window(fold)
        end = (
            min(window.end, fold.split.holdout.start - timedelta(microseconds=1))
            if self.partition == "validation"
            else window.end
        )
        return TimeWindow(start=window.start, end=end)

    @property
    def identity(self) -> str:
        """Bind exact selections, economic assumptions, schedules and seeds."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def read(cls, path: Path) -> DecisionStudy:
        """Read strict bounded JSON; in-memory callers use the identical record contract."""
        with path.open("rb") as source:
            payload = source.read(4_194_305)
        if len(payload) > 4_194_304:
            raise ValueError("study configuration exceeds four MiB")
        return DomainCodec().decode_json(payload, cls)

    def specification(self, implementation: str, environment: str) -> ExperimentSpec:
        """Bind configuration and inputs before work; retain resolved sample bytes afterward."""
        return ExperimentSpec(
            family=self.family,
            inputs=(Fingerprint(name="resolved-configuration", sha256=self.identity),),
            components=(
                Fingerprint(name="implementation", sha256=implementation),
                *(
                    Fingerprint(name=f"extension:{item.name}", sha256=item.sha256)
                    for item in self.extensions
                ),
            ),
            parameters=self.parameters,
            seeds=self.seeds,
            environment_sha256=environment,
            split=self.folds[0].split,
        )


class DecisionComparison(WireRecord, frozen=True):
    """Freeze complete compatible validation variants for the existing Optuna controller."""

    name: str
    variants: tuple[DecisionStudy, ...]
    budget: int
    seed: int
    minimum_return: ExactRatio
    prune_below: ExactRatio | None = None
    schema_version: Literal["decision-comparison-v1"] = "decision-comparison-v1"

    def __post_init__(self) -> None:
        """Refuse holdout search, changed samples/report objectives and unbounded grids."""
        if (
            self.schema_version != "decision-comparison-v1"
            or type(self.name) is not str
            or not self.name
        ):
            raise ValueError("invalid decision comparison")
        if type(self.variants) is not tuple or not 1 <= len(self.variants) <= 32:
            raise ValueError("comparison requires one to 32 variants")
        if (
            type(self.budget) is not int
            or not 1 <= self.budget <= len(self.variants)
            or type(self.seed) is not int
            or not 0 <= self.seed < 2**32
        ):
            raise ValueError("invalid comparison budget or seed")
        first = self.variants[0]
        for run in self.variants:
            run.__post_init__()
            if run.partition != "validation" or (
                run.family,
                run.source_identity,
                run.folds,
                run.metrics,
                run.charts,
                run.extensions,
                run.seeds,
                run.economics.source_identity,
                run.economics.entity,
                run.economics.initial_cash,
            ) != (
                first.family,
                first.source_identity,
                first.folds,
                first.metrics,
                first.charts,
                first.extensions,
                first.seeds,
                first.economics.source_identity,
                first.economics.entity,
                first.economics.initial_cash,
            ):
                raise ValueError(
                    "search requires identical validation samples, capital and reports"
                )
        if len({run.identity for run in self.variants}) != len(self.variants):
            raise ValueError("search variants must be distinct")
        TrialEvaluation(net_return=self.minimum_return)
        if self.prune_below is not None:
            TrialEvaluation(net_return=self.prune_below)

    @property
    def identity(self) -> str:
        """Identify the frozen search including failed-trial budget and selection threshold."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def specification(self, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the complete search to the original family's frozen holdout."""
        base = self.variants[0].specification(implementation, environment)
        return ExperimentSpec(
            family=base.family,
            inputs=(*base.inputs, Fingerprint(name="comparison", sha256=self.identity)),
            components=base.components,
            parameters=base.parameters,
            seeds=(*base.seeds, ("optuna-grid", self.seed)),
            environment_sha256=environment,
            split=base.split,
        )

    @classmethod
    def read(cls, path: Path) -> DecisionComparison:
        """Load a bounded serialized search without executable code discovery."""
        with path.open("rb") as source:
            payload = source.read(4_194_305)
        if len(payload) > 4_194_304:
            raise ValueError("comparison configuration exceeds four MiB")
        return DomainCodec().decode_json(payload, cls)
