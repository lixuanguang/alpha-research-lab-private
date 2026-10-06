"""Compose fresh decision implementations into retained temporal studies and costed reports."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from financial_units import ExactRatio
from research.experiments import AttemptHistory, AttemptStore, ExperimentSpec, SampleInterval
from research.features import FeatureKernel, FeatureSession, FeatureVector, FittedTransform
from research.models import EstimatorLifecycle
from research.observations import DecisionSource
from research.reports import (
    ChartDefinition,
    FoldSummary,
    LedgerPoint,
    MetricDefinition,
    ReportContext,
)
from research.results import Prediction
from research.studies import (
    ClearMLPublication,
    DecisionComparison,
    DecisionStudy,
    ParameterComparison,
    PublicationPolicy,
    ResultManifest,
    StudyArtifact,
    StudyFold,
    StudyFoldResult,
    StudyMarketSource,
    StudyOutcomeSource,
    StudyReportBuilder,
    StudyResult,
    TrialEvaluation,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import IntentCostModel, IntentExecutionModel, IntentSimulation
from strategies import DecisionContext, DecisionPolicy, DecisionRecord, DecisionSession

if TYPE_CHECKING:
    # third party library imports
    from optuna.trial import Trial


@dataclass(frozen=True)
class StudyComponents:
    """Bind trusted implementations explicitly; every selection must match configuration.

    Stateful feature/strategy adapters obey the MR02 pure-transition contract.
    The application creates fresh sessions and ledgers for each fold and trial.
    Source adapters retain their actual bytes; component code is supplied by the
    caller and must be retained alongside the pinned implementation identities.
    """

    source: DecisionSource
    market: StudyMarketSource
    feature: FeatureKernel
    policy: DecisionPolicy
    execution: IntentExecutionModel
    costs: IntentCostModel
    capabilities: tuple[str, ...]
    metrics: tuple[MetricDefinition, ...]
    charts: tuple[ChartDefinition, ...]
    model: EstimatorLifecycle | None = None
    transform: FittedTransform | None = None
    labels: StudyOutcomeSource | None = None
    artifacts: tuple[StudyArtifact, ...] = ()

    def admit(self, config: DecisionStudy) -> None:
        """Reject substituted selections or unsupported signatures before source reads."""
        config.__post_init__()
        required = {
            "product:spot",
            f"calendar:{config.calendar}",
            f"intent:{config.output}",
            f"feature:{self.feature.schema.mode}",
            *config.required_capabilities,
            *(f"input:{item.family}" for item in self.feature.schema.inputs),
        }
        if not required <= set(self.capabilities):
            raise ValueError("missing study capability")
        actual = (
            self.source.identity,
            self.market.identity,
            self.feature.schema.identity,
            self.policy.identity,
            self.policy.output,
            self.execution.identity,
            self.costs.identity,
            None if self.model is None else self.model.identity,
            None if self.transform is None else self.transform.identity,
            None if self.labels is None else self.labels.identity,
        )
        expected = (
            config.source_identity,
            config.economics.source_identity,
            config.feature_identity,
            config.policy_identity,
            config.output,
            config.economics.execution_identity,
            config.economics.cost_identity,
            config.model_identity,
            config.transform_identity,
            config.label_identity,
        )
        if actual != expected or self.source.requirements != self.feature.schema.inputs:
            raise ValueError("selected study implementations or source signatures differ")
        if (
            tuple(m.identity for m in self.metrics) != config.metrics
            or tuple(c.identity for c in self.charts) != config.charts
        ):
            raise ValueError("selected metric/chart implementations differ")
        if (
            type(self.artifacts) is not tuple
            or tuple(item.fingerprint for item in self.artifacts) != config.extensions
        ):
            raise ValueError("supplied extension artifacts differ from configuration")
        for item in self.artifacts:
            item.__post_init__()

    def evaluate(self, run: DecisionStudy, *, store: AttemptStore, attempt: str) -> TrialEvaluation:
        """Sequence actual folds, retain their inputs/state and render selected report extensions.

        Args:
            run: Validated study whose folds are executed with these self.
            store: Attempt store retaining each fold, the result and the report.
            attempt: Attempt receiving the retained outputs.

        Returns:
            The trial's mean net return across folds.
        """
        codec = DomainCodec()
        for artifact_index, artifact in enumerate(self.artifacts):
            store.retain(attempt, f"extension-{artifact_index:04d}", artifact.payload)
        store.retain(attempt, "feature-schema", codec.encode_json(self.feature.schema))
        results: list[StudyFoldResult] = []
        summaries: list[FoldSummary] = []
        for index, fold in enumerate(run.folds):
            result = self._evaluate_fold(run, fold, store=store, attempt=attempt, index=index)
            results.append(result)
            store.retain(attempt, f"fold-{index:04d}", codec.encode_json(result))
            window = run.window(fold)
            summaries.append(
                FoldSummary(
                    fold_id=fold.name,
                    window=window,
                    ledger=result.economics.ledger,
                    terminal_mark=result.economics.mark,
                    terminal_missing_reason=result.economics.unvalued_reason,
                    curve=(
                        LedgerPoint(
                            at=window.start,
                            mark=Ledger(
                                LedgerState(
                                    initial_cash=run.economics.initial_cash,
                                    dimension=run.economics.limits.lot.dimension,
                                )
                            ).mark(None),
                        ),
                        LedgerPoint(
                            at=window.end,
                            mark=result.economics.mark,
                            missing_reason=result.economics.unvalued_reason,
                        ),
                    ),
                    diagnostics=result.prediction_errors(window),
                )
            )
        report = StudyReportBuilder.build(
            ReportContext(
                study_identity=store.read(attempt).start.run_identity, folds=tuple(summaries)
            ),
            expected_metrics=run.metrics,
            expected_charts=run.charts,
            metrics=self.metrics,
            charts=self.charts,
            limitations=tuple(
                sorted(
                    {item for result in results for item in result.economics.limitations}
                    | {"Folds have independent cash/state; endpoints omit intraperiod NAV."}
                )
            ),
        )
        store.retain(
            attempt,
            "study-result",
            codec.encode_json(StudyResult(config=run, folds=tuple(results))),
        )
        store.retain(attempt, "study-report", codec.encode_json(report))
        store.retain(attempt, "report-html", report.render())
        unvalued = [r.economics for r in results if r.economics.mark is None]
        if unvalued:
            return TrialEvaluation(
                net_return=None,
                missing_reason=f"{len(unvalued)} of {len(results)} folds unvalued: "
                + str(unvalued[0].unvalued_reason),
            )
        returns = tuple(
            Fraction(r.economics.mark.net.value) / Fraction(run.economics.initial_cash.value)
            for r in results
            if r.economics.mark is not None
        )
        return TrialEvaluation(
            net_return=ExactRatio.from_fraction(sum(returns, Fraction()) / len(returns))
        )

    def _evaluate_fold(
        self,
        run: DecisionStudy,
        fold: StudyFold,
        *,
        store: AttemptStore,
        attempt: str,
        index: int,
    ) -> StudyFoldResult:
        """Read causal vectors, resolve split bytes, fit or reload and execute one fresh account."""
        codec = DomainCodec()
        feature_session = FeatureSession(
            self.feature, instance=run.economics.instance, entity=run.economics.entity
        )
        schedule = (*fold.training_decisions, *fold.decisions)
        inputs = tuple(self.source.read(run.economics.entity, at) for at in schedule)
        store.retain(attempt, f"inputs-{index:04d}", codec.encode_json(inputs))
        if any(
            (value.entity, value.decision_at) != (run.economics.entity, at)
            for value, at in zip(inputs, schedule, strict=True)
        ):
            raise ValueError("source input differs from the requested entity or decision cutoff")
        rows = tuple(feature_session.evaluate(value) for value in inputs)
        store.retain(attempt, f"features-{index:04d}", codec.encode_json(rows))
        outcomes = (
            ()
            if self.labels is None
            else tuple(self.labels.read(row, as_of=fold.evaluated_as_of) for row in rows)
        )
        for outcome in outcomes:
            outcome.__post_init__()
            if outcome.value is not None and (
                outcome.available_at is None or outcome.available_at > fold.evaluated_as_of
            ):
                raise ValueError("outcome unavailable at study evaluation cutoff")
            if (
                run.partition == "validation"
                and outcome.information_end >= fold.split.holdout.start
            ):
                raise ValueError("validation outcome crosses the frozen holdout")
        samples = (
            tuple(outcome.sample(row) for row, outcome in zip(rows, outcomes, strict=True))
            if outcomes
            else tuple(
                SampleInterval(
                    row_id=row.identity,
                    input_sha256=row.identity,
                    decision_at=row.decision_at,
                    information_start=row.information_start,
                    information_end=row.decision_at,
                    features_available_at=row.available_at,
                    label_available_at=None,
                )
                for row in rows
            )
        )
        split = replace(fold.split, samples=samples)
        store.retain(attempt, f"split-{index:04d}", codec.encode_json(split))
        store.retain(attempt, f"outcomes-{index:04d}", codec.encode_json(outcomes))
        excluded = list(split.exclusions())
        store.retain(attempt, f"fit-exclusions-{index:04d}", codec.encode_json(tuple(excluded)))
        transform_version = None
        model_version = None
        if self.transform is not None:
            if split.fit_cutoff is None:
                raise ValueError("transform requires a fitting cutoff")
            transform_version = self.transform.fit(rows, split, available_at=split.fit_cutoff)
            store.retain(attempt, f"transform-{index:04d}", codec.encode_json(transform_version))
        if self.model is not None:
            if split.fit_cutoff is None:
                raise ValueError("estimator requires a fitting cutoff")
            model_version = self.model.fit(
                rows,
                outcomes,
                split,
                available_at=split.fit_cutoff,
                transform=self.transform,
                transform_version=transform_version,
            )
            store.retain(attempt, f"model-{index:04d}", codec.encode_json(model_version))
        policy = DecisionSession(
            self.policy,
            run_identity=run.identity,
            instance=run.economics.instance,
            entity=run.economics.entity,
        )
        predictions: list[Prediction] = []
        decisions: list[DecisionRecord] = []
        for raw in rows[len(fold.training_decisions) :]:
            vector: FeatureVector = raw
            if self.transform is not None and transform_version is not None:
                vector = self.transform.apply(transform_version, raw)
            prediction = None
            if self.model is not None and model_version is not None:
                if any(value is None for value in vector.values):
                    excluded.append((raw.identity, "missing inference feature"))
                    continue
                prediction = self.model.predict(model_version, vector)
                predictions.append(prediction)
            decisions.append(
                policy.evaluate(DecisionContext(features=vector, prediction=prediction))
            )
        window = run.window(fold)
        market_window = run.market_window(fold)
        market = self.market.read(market_window)
        if any(
            row.source_at > market_window.end or row.available_at > market_window.end
            for row in market
        ):
            raise ValueError("execution source exceeded its admitted evaluation cutoff")
        store.retain(attempt, f"market-{index:04d}", codec.encode_json(market))
        spec = replace(run.economics, start=window.start, end=window.end)
        ledger = Ledger(
            LedgerState(initial_cash=spec.initial_cash, dimension=spec.limits.lot.dimension)
        )
        economics = IntentSimulation(spec, self.execution, self.costs, ledger).run(
            tuple(decisions), market
        )
        return StudyFoldResult(
            name=fold.name,
            split=split,
            features=rows,
            outcomes=outcomes,
            transform=transform_version,
            model=model_version,
            predictions=tuple(predictions),
            decisions=tuple(decisions),
            exclusions=tuple(excluded),
            feature_state=feature_session.checkpoint(),
            policy_state=policy.checkpoint(),
            economics=economics,
        )


class _StudyJobKey:
    """Resolve a study job key against the attempts that already bound it."""

    @staticmethod
    def completed(
        store: AttemptStore, key: str, spec: ExperimentSpec, publication: PublicationPolicy
    ) -> AttemptHistory | None:
        """Return the completed attempt a job key already bound, abandoning interrupted ones.

        Call inside the store's transaction, before the start that binds the key.
        """
        for previous in store.histories():
            previous_id = previous.start.attempt_id
            if "job-key" not in store.artifacts(previous_id):
                continue
            if store.artifact(previous_id, "job-key") != key.encode():
                continue
            if previous.start.spec != spec or store.artifact(
                previous_id, "publication-policy"
            ) != DomainCodec().encode_json(publication):
                raise ValueError("study job key already binds different inputs or publication")
            if previous.status == "completed":
                return previous
            if previous.status == "incomplete":
                store.finish(
                    previous_id,
                    status="abandoned",
                    at=datetime.now(UTC),
                    reason="interrupted job attempt retained before retry",
                )
        return None


def evaluate_study(
    config: DecisionStudy | Path,
    *,
    components: StudyComponents,
    attempts: Path,
    publication: PublicationPolicy,
    idempotency_key: str | None = None,
) -> AttemptHistory:
    """Execute a typed or serialized formal study, retaining local results before publication.

    Local mode performs no tracking I/O. Deferred mode retains the existing
    ClearML outbox for publish_experiments without contacting the server. Immediate
    mode attempts publication after terminal computation; a transport failure
    propagates while the completed result remains readable. Holdout access is
    recorded before features, outcomes or execution inputs are read.

    An optional job key reopens a completed attempt after a lost acknowledgement.
    It is bound to the exact run, installed implementation and publication policy.
    Failed/interrupted attempts remain in the same family history on retry.
    """
    run = DecisionStudy.read(config) if isinstance(config, Path) else config
    run = DomainCodec().decode_json(DomainCodec().encode_json(run), DecisionStudy)
    publication.__post_init__()
    spec = run.specification(
        ImplementationIdentity.sha256(), ExperimentSpec.installed_environment()
    )
    if idempotency_key is not None and (
        not idempotency_key or idempotency_key != idempotency_key.strip()
    ):
        raise ValueError("study idempotency key must be nonempty trimmed text")
    with AttemptStore(attempts) as store:
        # Concurrent studies share the store: the key lookup and the start that binds
        # the key commit together, so one key never starts two attempts.
        with store.transaction():
            previous = (
                None
                if idempotency_key is None
                else _StudyJobKey.completed(store, idempotency_key, spec, publication)
            )
            if previous is None:
                attempt = store.start(
                    spec,
                    at=datetime.now(UTC),
                    invocation="applications.explore.evaluate_study",
                    request=DomainCodec().encode_json(run),
                ).attempt_id
                store.retain(attempt, "publication-policy", DomainCodec().encode_json(publication))
                if idempotency_key is not None:
                    store.retain(attempt, "job-key", idempotency_key.encode())
        if previous is not None:
            StudyResult.read(store, previous.start.attempt_id)
            if publication.mode == "immediate" and publication.destination is not None:
                ClearMLPublication(store, publication.destination).publish(
                    previous.start.attempt_id
                )
            return previous
        publisher = (
            None
            if publication.destination is None
            else ClearMLPublication(store, publication.destination)
        )
        try:
            if publisher is not None:
                publisher.enqueue(attempt)
            components.admit(run)
            if run.partition == "holdout":
                store.consume_holdout(
                    attempt,
                    at=datetime.now(UTC),
                    reason="selected final decision study before any source read",
                )
            components.evaluate(run, store=store, attempt=attempt)
            manifest = ResultManifest.retain(
                store,
                attempt,
                {
                    name: store.artifact(attempt, name)
                    for name in store.artifacts(attempt)
                    if not name.startswith("clearml-")
                },
            )
            store.finish(
                attempt,
                status="completed",
                at=datetime.now(UTC),
                reason="completed declared temporal study; no strategy or deployment acceptance",
                result=DomainCodec().encode_json(manifest),
            )
        except (Exception, KeyboardInterrupt) as error:
            if store.read(attempt).status == "incomplete":
                store.finish(
                    attempt,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            raise
        if publisher is not None and publication.mode == "immediate":
            publisher.publish(attempt)
        return store.read(attempt)


class StudyComparisonEvaluator:
    """Resolve configured variants to supplied components inside the existing search controller."""

    def __init__(self, bindings: Mapping[str, StudyComponents]) -> None:
        """Bind exact variant identities to their implementations without mutable defaults."""
        self._bindings = dict(bindings)

    def evaluate(
        self, run: DecisionStudy, trial: Trial, store: AttemptStore, attempt_id: str
    ) -> TrialEvaluation:
        """Evaluate validation only and retain exact objective before Optuna float projection."""
        # third party library imports
        from optuna import TrialPruned

        if run.partition != "validation":
            raise ValueError("parameter search cannot read the final holdout")
        components = self._bindings[run.identity]
        components.admit(run)
        result = components.evaluate(run, store=store, attempt=attempt_id)
        if result.net_return is None:
            # No objective to report or prune on; the search rejects it with its reason.
            return result
        trial.report(
            int(result.net_return.numerator) / int(result.net_return.denominator),
            step=len(run.folds),
        )
        if trial.should_prune():
            raise TrialPruned("declared completed-fold objective failed pruning threshold")
        return result


def compare_studies(
    config: DecisionComparison | Path,
    *,
    bindings: Mapping[str, StudyComponents],
    attempts: Path,
    journal: Path,
    publication: PublicationPolicy,
    max_trials: int | None = None,
) -> tuple[str, ...]:
    """Resume the existing bounded Optuna search with complete injected study implementations.

    Each variant uses validation only, fresh fold state and independent capital.
    The objective is the exact arithmetic mean of independent fold net returns;
    it is not a compounded or continuously invested walk-forward account.
    """
    definition = DecisionComparison.read(config) if isinstance(config, Path) else config
    definition = DomainCodec().decode_json(
        DomainCodec().encode_json(definition), DecisionComparison
    )
    if set(bindings) != {run.identity for run in definition.variants}:
        raise ValueError("every configured search variant requires exact supplied bindings")
    controller = ParameterComparison(
        definition,
        journal=journal,
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    with AttemptStore(attempts) as store:
        return controller.run(
            store,
            StudyComparisonEvaluator(bindings),
            publication=publication,
            max_trials=max_trials,
        )
