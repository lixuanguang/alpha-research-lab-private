"""Retain bounded Optuna comparisons without losing unsuccessful or interrupted trials."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from research.experiments import AttemptStore, ExperimentSpec, Fingerprint
from research.studies.configuration import BacktestRun
from research.studies.evaluation import TrialEvaluation
from research.studies.publication import PublicationPolicy
from research.studies.results import ResultManifest
from research.studies.tracking import ClearMLPublication
from serialization import DomainCodec, WireRecord

if TYPE_CHECKING:
    # third party library imports
    from optuna.trial import Trial


class ComparisonStudy(WireRecord, frozen=True):
    """Freeze complete resolved variants, objective, budget and sampler seed before evaluation."""

    name: str
    variants: tuple[BacktestRun, ...]
    budget: int
    seed: int
    minimum_return: ExactRatio
    prune_below: ExactRatio | None = None
    objective: str = "exact-net-return-v1"
    schema_version: str = "research-comparison-v1"

    def __post_init__(self) -> None:
        """Refuse incompatible inputs, changed partitions and unsupported unbounded searches."""
        if (
            self.schema_version != "research-comparison-v1"
            or self.objective != "exact-net-return-v1"
            or type(self.name) is not str
            or not self.name.strip()
            or type(self.variants) is not tuple
            or not 1 <= len(self.variants) <= 32
            or type(self.budget) is not int
            or not 1 <= self.budget <= len(self.variants)
            or type(self.seed) is not int
            or not 0 <= self.seed < 2**32
        ):
            raise ValueError("comparison requires a bounded declared grid, budget and seed")
        for item in self.variants:
            if type(item) is not BacktestRun:
                raise TypeError("comparison variants must be resolved BacktestRun records")
            item.__post_init__()
            if item.split is None:
                raise ValueError("engineering samples cannot enter parameter selection")
            if item.versioned_inputs_sha256 is not None:
                raise ValueError(
                    "comparison requires local pinned snapshots; "
                    "remote version materialization is not supported"
                )
        first = self.variants[0]
        if any(
            item.family != first.family
            or item.snapshot_id != first.snapshot_id
            or item.split != first.split
            or item.report != first.report
            or item.economics.start != first.economics.start
            or item.economics.end != first.economics.end
            or item.economics.binding != first.economics.binding
            for item in self.variants
        ):
            raise ValueError("comparison variants require the same selection, split and reports")
        if len({item.identity for item in self.variants}) != len(self.variants):
            raise ValueError("comparison variants must be distinct")
        if type(self.minimum_return) is not ExactRatio:
            raise TypeError("selection threshold requires an exact ratio")
        for value in (self.minimum_return, self.prune_below):
            if value is not None:
                if type(value) is not ExactRatio:
                    raise TypeError("comparison thresholds require exact ratios")
                value.__post_init__()
                if not math.isfinite(float(Fraction(int(value.numerator), int(value.denominator)))):
                    raise ValueError("comparison threshold has no finite Optuna projection")

    @classmethod
    def read(cls, path: Path) -> ComparisonStudy:
        """Read one bounded strict comparison configuration for any application action.

        Args:
            path: Explicit UTF-8 JSON configuration path.

        Returns:
            Validated immutable comparison definition.

        Raises:
            ValueError: Configuration exceeds one MiB or violates its strict schema.
        """
        with path.open("rb") as source:
            payload = source.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("comparison configuration exceeds one MiB")
        return DomainCodec().decode_json(payload, cls)

    @property
    def identity(self) -> str:
        """Bind every search choice, including the reserved holdout, to a stable digest.

        Returns:
            SHA-256 of the complete immutable comparison definition.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def specification(self, implementation: str, environment: str) -> ExperimentSpec:
        """Attach search choices to the existing temporal and attempt contracts.

        Args:
            implementation: Actual installed code identity.
            environment: Actual installed interpreter and dependency identity.

        Returns:
            Semantic identity common to the serial search controller.
        """
        base = self.variants[0].specification(
            implementation=implementation, environment=environment
        )
        inputs: tuple[Fingerprint, ...] = (
            *base.inputs,
            Fingerprint(name="comparison", sha256=self.identity),
        )
        return replace(
            base,
            inputs=inputs,
            seeds=(("optuna-grid", self.seed),),
        )


class SearchVariant(Protocol):
    """Require an immutable serialized configuration with a stable content identity."""

    @property
    def identity(self) -> str:
        """Identify the complete resolved variant without its execution path."""
        ...


class SearchDefinition[Variant: SearchVariant](Protocol):
    """Describe one bounded validation search without prescribing its study schema."""

    @property
    def name(self) -> str:
        """Identify the local Optuna journal study."""
        ...

    @property
    def variants(self) -> tuple[Variant, ...]:
        """Return complete resolved variants in frozen order."""
        ...

    @property
    def budget(self) -> int:
        """Bound the total number of attempted trials."""
        ...

    @property
    def seed(self) -> int:
        """Seed the retained grid sampler."""
        ...

    @property
    def minimum_return(self) -> ExactRatio:
        """Return the frozen exact acceptance threshold."""
        ...

    @property
    def prune_below(self) -> ExactRatio | None:
        """Return the optional frozen projected pruning threshold."""
        ...

    def __post_init__(self) -> None:
        """Validate the complete search, its variants and their shared evaluation scope."""
        ...

    def specification(self, implementation: str, environment: str) -> ExperimentSpec:
        """Bind the search to the installed implementation and environment."""
        ...


class ComparisonEvaluator[Variant: SearchVariant](Protocol):
    """Require a real application evaluation with artifacts retained before returning."""

    def evaluate(
        self, run: Variant, trial: Trial, store: AttemptStore, attempt_id: str
    ) -> TrialEvaluation:
        """Evaluate one isolated instance through its authoritative economic path.

        Args:
            run: Complete resolved variant with no holdout access.
            trial: Optuna sampling/pruning record, never another search controller.
            store: Entered single-writer attempt owner.
            attempt_id: Already retained execution receiving partial and complete artifacts.

        Returns:
            Exact objective after the full comparison finishes.
        """
        ...


class _RejectedError(ValueError):
    """Keep a scientifically rejected evaluation out of successful Optuna objectives."""


class _EvaluationError(RuntimeError):
    """Preserve failed evaluation history while allowing the remaining declared trials."""


class ParameterComparison[Variant: SearchVariant]:
    """Own serial sampling, durable trial mapping and fail-closed interruption recovery.

    GridSampler's seed and grid are frozen in the run identity. Its grid IDs and
    every trial transition persist in Optuna's append-only journal; no pickle,
    inferred random seed, parallel worker or second optimizer is involved.
    """

    def __init__(
        self,
        study: SearchDefinition[Variant],
        *,
        journal: Path,
        implementation: str,
        environment: str,
    ) -> None:
        """Bind an explicit study and retained journal without starting computation.

        Args:
            study: Frozen research choices and resolved variants.
            journal: Persistent local Optuna journal, backed up with the attempt root.
            implementation: Installed owned source digest.
            environment: Installed environment digest.
        """
        study.__post_init__()
        self._definition = study
        self._journal = journal
        self._spec = study.specification(implementation, environment)

    def run(
        self,
        store: AttemptStore,
        evaluator: ComparisonEvaluator[Variant],
        *,
        publication: PublicationPolicy,
        max_trials: int | None = None,
    ) -> tuple[str, ...]:
        """Resume the fixed budget, retaining and publishing every attempted variant.

        Args:
            store: Entered sole writer, serializing all runs sharing mutable attempt state.
            evaluator: Actual installed application composing economics and vectorbt.
            publication: Explicit local, deferred or immediate publication policy.
            max_trials: Optional invocation chunk size; does not change the frozen total budget.

        Returns:
            All mapped attempt IDs, including rejected, pruned, failed and recovered trials.

        Raises:
            ValueError: Journal identity or retained mappings differ, or chunk size is invalid.
            Exception: Publication or storage fails; prior trial history remains authoritative.
        """
        # third party library imports
        import optuna
        from optuna.pruners import NopPruner, ThresholdPruner
        from optuna.samplers import GridSampler, RandomSampler
        from optuna.storages import JournalStorage
        from optuna.storages.journal import JournalFileBackend
        from optuna.trial import TrialState

        if max_trials is not None and (type(max_trials) is not int or max_trials < 1):
            raise ValueError("max_trials must be a positive invocation bound")
        publication.__post_init__()
        self._journal.parent.mkdir(parents=True, exist_ok=True)
        sampler = GridSampler(
            {"variant": list(range(len(self._definition.variants)))}, seed=self._definition.seed
        )
        lower = self._definition.prune_below
        study = optuna.create_study(
            study_name=self._definition.name,
            storage=JournalStorage(JournalFileBackend(str(self._journal))),
            load_if_exists=True,
            sampler=RandomSampler(seed=self._definition.seed),
            pruner=NopPruner()
            if lower is None
            else ThresholdPruner(lower=int(lower.numerator) / int(lower.denominator)),
            direction="maximize",
        )
        identity: object = study.user_attrs.get("run_identity")  # type: ignore[misc]  # [owner=research; rationale=receive SDK JSON metadata as object and narrow before admission; expires=2026-12-01]
        if identity is None and not study.trials:
            study.set_user_attr("run_identity", self._spec.identity)
        elif identity != self._spec.identity:
            raise ValueError("resumed search configuration, code or environment differs")
        objective = _ComparisonObjective(
            self._definition, self._spec, store, evaluator, publication
        )
        for trial in study.get_trials(deepcopy=False):
            mapped: object = trial.user_attrs.get("attempt_id")  # type: ignore[misc]  # [owner=research; rationale=narrow SDK JSON metadata before mapping retained attempts; expires=2026-12-01]
            retained = tuple(
                history
                for history in store.histories()
                if ("search", self._spec.identity) in history.start.spec.parameters
                and ("trial", str(trial.number)) in history.start.spec.parameters
            )
            if len(retained) > 1 or (
                isinstance(mapped, str) and (not retained or retained[0].start.attempt_id != mapped)
            ):
                raise ValueError("Optuna trial mapping differs from retained attempt history")
            if trial.state == TrialState.RUNNING:
                if not retained:
                    objective.interrupted(trial.number)
                    study.tell(trial.number, state=TrialState.FAIL)
                    continue
                history = retained[0]
                attempt = history.start.attempt_id
                if (
                    ("search", self._spec.identity) not in history.start.spec.parameters
                    or history.start.spec.parameters[-1] != ("trial", str(trial.number))
                    or history.start.spec.family != self._spec.family
                    or history.start.spec.split != self._spec.split
                ):
                    raise ValueError("Optuna trial points at a different retained attempt")
                if history.status == "completed":
                    ResultManifest.read(store, attempt)
                    result = DomainCodec().decode_json(
                        store.artifact(attempt, "trial-evaluation"), TrialEvaluation
                    )
                    study.tell(
                        trial.number,
                        int(result.net_return.numerator) / int(result.net_return.denominator),
                    )
                else:
                    if history.status == "incomplete":
                        store.finish(
                            attempt,
                            status="abandoned",
                            at=datetime.now(UTC),
                            reason="Interrupted Optuna trial; no successful full evaluation",
                        )
                    study.tell(trial.number, state=TrialState.FAIL)
            elif not retained:
                raise ValueError("terminal Optuna trial lacks its retained attempt history")
        study.sampler = sampler
        remaining = max(0, self._definition.budget - len(study.trials))
        count = remaining if max_trials is None else min(remaining, max_trials)
        if count:
            study.optimize(objective, n_trials=count, catch=(_RejectedError, _EvaluationError))
        attempts: list[str] = []
        publisher = (
            None
            if publication.destination is None
            else ClearMLPublication(store, publication.destination)
        )
        for history in store.histories():
            if ("search", self._spec.identity) in history.start.spec.parameters:
                attempts.append(history.start.attempt_id)
                if publisher is not None:
                    publisher.enqueue(history.start.attempt_id)
                    if publication.mode == "immediate":
                        publisher.publish(history.start.attempt_id)
        return tuple(attempts)


class _ComparisonObjective[Variant: SearchVariant]:
    """Commit attempt outcomes around one Optuna callback, preserving partial artifacts."""

    def __init__(
        self,
        definition: SearchDefinition[Variant],
        spec: ExperimentSpec,
        store: AttemptStore,
        evaluator: ComparisonEvaluator[Variant],
        publication: PublicationPolicy,
    ) -> None:
        """Bind the active single-writer evaluation lifetime."""
        self._definition = definition
        self._spec = spec
        self._store = store
        self._evaluator = evaluator
        self._publication = (
            None
            if publication.destination is None
            else ClearMLPublication(store, publication.destination)
        )

    def __call__(self, trial: Trial) -> float:
        """Retain every evaluated combination before invoking application code."""
        # third party library imports
        from optuna import TrialPruned

        selected = trial.suggest_int("variant", 0, len(self._definition.variants) - 1)
        run = self._definition.variants[selected]
        request = DomainCodec().encode_json(run)
        inputs: tuple[Fingerprint, ...] = (
            *(
                Fingerprint(name=item.name, sha256=run.identity)
                if item.name == "resolved-configuration"
                else item
                for item in self._spec.inputs
            ),
            Fingerprint(name="variant", sha256=run.identity),
        )
        parameters: tuple[tuple[str, str], ...] = (
            *self._spec.parameters,
            ("search", self._spec.identity),
            ("trial", str(trial.number)),
        )
        spec = replace(
            self._spec,
            inputs=inputs,
            parameters=parameters,
        )
        start = self._store.start(
            spec,
            at=datetime.now(UTC),
            invocation="alpha-backtest compare",
            request=request,
        )
        attempt = start.attempt_id
        try:
            trial.set_user_attr("attempt_id", attempt)
            if hashlib.sha256(request).hexdigest() != run.identity:
                raise ValueError(
                    "search variant identity differs from its serialized configuration"
                )
            if self._publication is not None:
                self._publication.enqueue(attempt)
            self._store.retain(
                attempt, "comparison-definition", DomainCodec().encode_json(self._definition)
            )
            result = self._evaluator.evaluate(run, trial, self._store, attempt)
            self._store.retain(attempt, "trial-evaluation", DomainCodec().encode_json(result))
            actual = Fraction(int(result.net_return.numerator), int(result.net_return.denominator))
            threshold = self._definition.minimum_return
            accepted = actual >= Fraction(int(threshold.numerator), int(threshold.denominator))
            if not accepted:
                raise _RejectedError(
                    "Exact validation net return is below the frozen selection threshold"
                )
            manifest = ResultManifest.retain(
                self._store,
                attempt,
                {
                    name: self._store.artifact(attempt, name)
                    for name in self._store.artifacts(attempt)
                    if not name.startswith("clearml-")
                },
            )
            self._store.finish(
                attempt,
                status="completed",
                at=datetime.now(UTC),
                reason="Accepted validation comparison; no promotion authority",
                result=DomainCodec().encode_json(manifest),
            )
            return float(actual)
        except (Exception, KeyboardInterrupt) as error:
            if self._store.read(attempt).status == "incomplete":
                self._store.finish(
                    attempt,
                    status="rejected"
                    if isinstance(error, _RejectedError)
                    else "abandoned"
                    if isinstance(error, (TrialPruned, KeyboardInterrupt))
                    else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            if isinstance(error, (TrialPruned, _RejectedError, KeyboardInterrupt)):
                raise
            raise _EvaluationError(
                f"Retained failed trial {trial.number}: {type(error).__name__}"
            ) from error

    def interrupted(self, number: int) -> str:
        """Retain interruption before the callback could map a variant to an attempt."""
        parameters: tuple[tuple[str, str], ...] = (
            *self._spec.parameters,
            ("search", self._spec.identity),
            ("trial", str(number)),
        )
        spec = replace(
            self._spec,
            parameters=parameters,
        )
        start = self._store.start(
            spec,
            at=datetime.now(UTC),
            invocation="alpha-backtest compare recovery",
            request=DomainCodec().encode_json(self._definition),
        )
        if self._publication is not None:
            self._publication.enqueue(start.attempt_id)
        self._store.finish(
            start.attempt_id,
            status="abandoned",
            at=datetime.now(UTC),
            reason="Interrupted before variant evaluation and attempt mapping",
        )
        return start.attempt_id
