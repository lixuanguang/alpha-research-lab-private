"""Compose declared serial parameter trials through the existing economic and report path."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
from optuna import TrialPruned
from optuna.trial import Trial

# project library imports
from applications.backtest.workflow import run_backtest
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryReader
from market_data.storage import RawStore
from research.experiments import (
    AttemptStore,
    BacktestRun,
    ClearMLDestination,
    ComparisonStudy,
    ExperimentSpec,
    ParameterComparison,
    QuantStatsReport,
    ResearchInputs,
    TrialEvaluation,
)
from research.exploration import EdaQuery, QuerySummary, ResearchSelection, TradeSelection
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import EconomicResult, VectorbtAdapter


class EconomicComparison:
    """Connect one verified immutable input to isolated economic trial instances."""

    def __init__(
        self,
        reader: QueryReader,
        selection: ResearchSelection,
        *,
        step: tuple[str, str] | None = None,
    ) -> None:
        """Bind verified source input and its shared EDA/replay/formal selection.

        Args:
            reader: Admitted saved source partitions.
            selection: Exact selection retained by EDA and the formal comparison.
            step: Optional actual ClearML controller/task association, retained before evaluation.

        Raises:
            ValueError: The selected snapshot differs from the admitted reader.
        """
        if len(selection.inputs) != 1 or selection.inputs[0].query.snapshot_id != reader.identity:
            raise ValueError("comparison selection differs from the verified reader")
        self._reader = reader
        self._selection = selection
        self._step = step

    def evaluate(
        self, run: BacktestRun, trial: Trial, store: AttemptStore, attempt_id: str
    ) -> TrialEvaluation:
        """Retain exact economics before pruning and complete the bounded vectorbt comparison.

        Args:
            run: Resolved no-fit validation variant.
            trial: Optuna trial owning the declared pruning decision.
            store: Entered attempt store retaining all partial outputs.
            attempt_id: Current mapped attempt ID.

        Returns:
            Exact net objective only after full reference/adapter/report completion.

        Raises:
            ValueError: Selection differs or reference economics cannot yield a complete objective.
            TrialPruned: The declared Optuna threshold stops the remaining comparison work.
        """
        item = self._selection.inputs[0]
        if not isinstance(item, TradeSelection):
            raise ValueError("economic comparison requires a trade selection")
        query = item.query
        spec = run.economics
        if (
            query.snapshot_id != run.snapshot_id
            or query.start != spec.start
            or query.end != spec.end
            or query.known_at != spec.end
            or query.precedence != (spec.binding,)
            or query.instruments != (spec.binding[2],)
        ):
            raise ValueError("economic variant differs from the shared research selection")
        codec = DomainCodec()
        if self._step is not None:
            store.retain(attempt_id, "pipeline-step", codec.encode_json(self._step))
        store.retain(attempt_id, "research-selection", codec.encode_json(self._selection))
        store.retain(attempt_id, "selection-identity", self._selection.identity.encode())
        summary = QuerySummary.collect(
            self._reader.batches(
                query.instruments,
                start=query.start,
                end=query.end,
                known_at=query.known_at,
                columns=query.columns,
                batch_size=query.batch_size,
                mode=query.mode,
            )
        )
        store.retain(attempt_id, "eda-summary", codec.encode_json(summary))
        inputs = ResearchInputs.collect(run, self._reader)
        store.retain(attempt_id, "research-inputs", codec.encode_json(inputs))
        result = run_backtest(self._reader, spec)
        if not isinstance(result, EconomicResult):
            raise ValueError("comparison requires terminal economic completion")
        store.retain(attempt_id, "economic-reference", codec.encode_json(result))
        report = QuantStatsReport.build(result, run.report)
        store.retain(attempt_id, "report", codec.encode_json(report))
        if report.net_return is None or any(p.net_return is None for p in report.periods):
            raise ValueError("missing economic observations cannot supply a search objective")
        projection = int(report.net_return.numerator) / int(report.net_return.denominator)
        trial.report(projection, 0)
        if trial.should_prune():
            raise TrialPruned(
                "Declared net-return threshold pruned before vectorbt/report completion"
            )
        store.retain(
            attempt_id, "vectorbt-comparison", codec.encode_json(VectorbtAdapter.run(result))
        )
        store.retain(attempt_id, "report-html", QuantStatsReport.render(report))
        return TrialEvaluation(net_return=report.net_return)


def compare_parameters(
    config: Path,
    snapshots: Path,
    raw: Path,
    *,
    attempts: Path,
    journal: Path,
    max_bytes: int,
    tracking: ClearMLDestination,
    max_trials: int | None = None,
    step: tuple[str, str] | None = None,
) -> tuple[str, ...]:
    """Resume a frozen comparison with the existing installed sources, ledger and reports.

    Args:
        config: Strict ComparisonStudy JSON, at most one MiB.
        snapshots: Existing published snapshot root.
        raw: Existing raw object store.
        attempts: Single-writer history root shared by the complete research family.
        journal: Retained local Optuna journal; back up together with attempts.
        max_bytes: Explicit input admission ceiling.
        tracking: Required ClearML destination; never contains credentials.
        max_trials: Optional invocation chunk; total budget remains in the frozen configuration.
        step: Optional actual ClearML controller/task association for every new trial.

    Returns:
        All mapped attempt IDs after acknowledged publication, including unsuccessful trials.

    Raises:
        ValueError: Configuration or saved inputs fail admission.
    """
    study = ComparisonStudy.read(config)
    first = study.variants[0]
    reader = QueryReader.read(
        snapshots,
        RawStore(raw),
        readers=SourceAdapters(),
        identity=first.snapshot_id,
        precedence=(first.economics.binding,),
        max_bytes=max_bytes,
    )
    selection = ResearchSelection(
        inputs=(
            TradeSelection(
                name="economics",
                query=EdaQuery(
                    snapshot_id=first.snapshot_id,
                    precedence=(first.economics.binding,),
                    instruments=(first.economics.binding[2],),
                    start=first.economics.start,
                    end=first.economics.end,
                    known_at=first.economics.end,
                    columns=("identity", "ts_knowledge", "price", "quantity", "revision"),
                    mode="cutoff",
                    batch_size=256,
                    max_bytes=max_bytes,
                ),
            ),
        )
    )
    comparison = ParameterComparison(
        study,
        journal=journal,
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    with AttemptStore(attempts) as store:
        return comparison.run(
            store, EconomicComparison(reader, selection, step=step), tracking, max_trials=max_trials
        )
