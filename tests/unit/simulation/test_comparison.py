"""Prove frozen search budgets, exact objectives and durable unsuccessful trial history."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

# third party library imports
import optuna
import pytest
from economic_examples import ReplayInputs as _ReplayInputs
from msgspec.structs import replace
from optuna.storages import JournalStorage
from optuna.storages.journal import JournalFileBackend
from optuna.trial import Trial

# project library imports
from applications.backtest import EconomicComparison
from financial_units import ExactRatio
from research.experiments import AttemptStore, TemporalSplit, TimeWindow
from research.exploration import EdaQuery, ResearchSelection, TradeSelection
from research.studies import (
    BacktestRun,
    BenchmarkPeriod,
    ClearMLDestination,
    ClearMLPublication,
    ComparisonStudy,
    ParameterComparison,
    PublicationReceipt,
    ReportPolicy,
    ResultManifest,
    TrialEvaluation,
)
from serialization import DomainCodec

_RETAIN = AttemptStore.retain


class _RetentionFailure:
    """Fail one post-start artifact boundary while leaving terminal retention writable."""

    @staticmethod
    def retain(store: AttemptStore, attempt_id: str, name: str, payload: bytes) -> str:
        """Inject a definition-write failure after the attempt and journal mapping exist."""
        if name == "comparison-definition":
            raise OSError("injected definition write failure")
        return _RETAIN(store, attempt_id, name, payload)


class _Publication:
    """Acknowledge only publication while preserving the actual local attempt and optimizer."""

    def publish(self, attempt_id: str) -> PublicationReceipt:
        """Supply a deterministic fake transport receipt for one completed local attempt.

        Args:
            attempt_id: Mapped immutable local execution.

        Returns:
            Transport-only receipt; these tests make no real server assertion.
        """
        return PublicationReceipt(
            attempt_id=attempt_id,
            task_id=f"task-{attempt_id}",
            model_ids=(),
            history_sha256="a" * 64,
            published_at=datetime(2026, 9, 21, tzinfo=UTC),
        )


class _FailedEvaluation:
    """Fail at the evaluation boundary after the real trial has been retained."""

    def evaluate(
        self, run: BacktestRun, trial: Trial, store: AttemptStore, attempt_id: str
    ) -> TrialEvaluation:
        """Preserve the actual failure rather than inventing an objective.

        Args:
            run: Selected configuration.
            trial: Already sampled Optuna trial.
            store: Entered real attempt writer.
            attempt_id: Retained execution identity.

        Raises:
            OSError: Deliberate unreadable input for recovery proof.
        """
        raise OSError("declared test input is unavailable")


class TestParameterComparison:
    """Exercise the real Optuna journal and installed economic adapters on known prices."""

    @staticmethod
    def _definition() -> tuple[ComparisonStudy, EconomicComparison]:
        """Build two resolved variants sharing one immutable selection and temporal split."""
        reader, economics = _ReplayInputs._inputs(_ReplayInputs.rows)
        zero = ExactRatio.from_fraction(Fraction(0))
        policy = ReportPolicy(
            benchmark_name="explicit-flat-control",
            benchmark=tuple(
                BenchmarkPeriod(end=economics.start + timedelta(minutes=i), value=zero)
                for i in range(1, 5)
            ),
            cadence_seconds=60,
            periods_per_year=525_600,
            annual_risk_free=zero,
        )
        split = TemporalSplit(
            fit_mode="none",
            training=None,
            fit_cutoff=None,
            validation=TimeWindow(start=economics.start, end=economics.end),
            holdout=TimeWindow(
                start=economics.end + timedelta(days=1), end=economics.end + timedelta(days=2)
            ),
            samples=(),
            embargo_us=0,
            rationale="No fitted state; final holdout stays untouched",
        )
        first = BacktestRun(
            family="parameter-comparison",
            snapshot_id=reader.identity,
            economics=economics,
            report=policy,
            split=split,
        )
        second = replace(
            first, economics=replace(economics, instance="flat-control", rule="no-trade-v1")
        )
        selection = ResearchSelection(
            inputs=(
                TradeSelection(
                    name="economics",
                    query=EdaQuery(
                        snapshot_id=reader.identity,
                        precedence=(economics.binding,),
                        instruments=(economics.binding[2],),
                        start=economics.start,
                        end=economics.end,
                        known_at=economics.end,
                        columns=("revision", "price"),
                        mode="cutoff",
                        batch_size=256,
                        max_bytes=2_000_000,
                    ),
                ),
            )
        )
        return ComparisonStudy(
            name="known-spot-comparison",
            variants=(first, second),
            budget=2,
            seed=17,
            minimum_return=ExactRatio.from_fraction(Fraction(-1)),
        ), EconomicComparison(reader, selection)

    @staticmethod
    def _search(definition: ComparisonStudy, path: Path) -> ParameterComparison:
        """Pin synthetic implementation/environment identities for cross-invocation tests."""
        return ParameterComparison(
            definition, journal=path / "optuna.log", implementation="a" * 64, environment="b" * 64
        )

    @staticmethod
    def _tracking() -> ClearMLDestination:
        """Name a transport-only test destination without issuing network requests."""
        return ClearMLDestination(
            project="tests", api_uri="http://127.0.0.1:18008", files_uri="http://127.0.0.1:18081"
        )

    def test_real_grid_resume_retains_exact_economics_and_shared_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resume a two-trial budget without rerunning its first attempt or losing exact output."""
        monkeypatch.setattr(ClearMLPublication, "publish", _Publication.publish)
        definition, evaluator = self._definition()
        with AttemptStore(tmp_path / "attempts") as store:
            one = self._search(definition, tmp_path).run(
                store, evaluator, self._tracking(), max_trials=1
            )
            first_bytes = DomainCodec().encode_json(store.read(one[0]))
            both = self._search(definition, tmp_path).run(store, evaluator, self._tracking())
            assert len(one) == 1 and len(both) == 2
            assert DomainCodec().encode_json(store.read(one[0])) == first_bytes
            assert (
                self._search(definition, tmp_path).run(store, evaluator, self._tracking()) == both
            )
            assert len({store.artifact(i, "selection-identity") for i in both}) == 1
            objectives = set()
            for attempt in both:
                ResultManifest.read(store, attempt)
                history = store.read(attempt)
                variant = DomainCodec().decode_json(history.start.request, BacktestRun)
                fingerprints = {item.name: item.sha256 for item in history.start.spec.inputs}
                assert fingerprints["resolved-configuration"] == variant.identity
                assert fingerprints["variant"] == variant.identity
                result = DomainCodec().decode_json(
                    store.artifact(attempt, "trial-evaluation"), TrialEvaluation
                )
                objectives.add(
                    Fraction(int(result.net_return.numerator), int(result.net_return.denominator))
                )
                assert not any(e.status == "holdout_consumed" for e in store.read(attempt).events)
            assert objectives == {Fraction(0), Fraction(-1447, 200_000_000)}
            with pytest.raises(ValueError, match="configuration, code or environment"):
                self._search(replace(definition, seed=18), tmp_path).run(
                    store, evaluator, self._tracking()
                )

    def test_pruned_rejected_and_failed_trials_cannot_be_successful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Retain every non-successful outcome with a reason and no completed manifest."""
        monkeypatch.setattr(ClearMLPublication, "publish", _Publication.publish)
        definition, evaluator = self._definition()
        zero = ExactRatio.from_fraction(Fraction(0))
        for label, selected, runner, expected in (
            (
                "pruned",
                replace(definition, prune_below=zero),
                evaluator,
                {"abandoned", "completed"},
            ),
            (
                "rejected",
                replace(definition, minimum_return=zero),
                evaluator,
                {"rejected", "completed"},
            ),
            ("failed", definition, _FailedEvaluation(), {"failed"}),
        ):
            path = tmp_path / label
            with AttemptStore(path / "attempts") as store:
                attempts = self._search(selected, path).run(store, runner, self._tracking())
                assert len(attempts) == 2
                assert {store.read(i).status for i in attempts} == expected
                for attempt in attempts:
                    history = store.read(attempt)
                    assert history.events[-1].reason
                    if history.status != "completed":
                        assert history.events[-1].result is None
                        with pytest.raises(ValueError, match="completed result"):
                            ResultManifest.read(store, attempt)

    def test_interrupted_unmapped_trial_counts_against_frozen_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crash after Optuna ask remains abandoned and cannot become a winning evaluation."""
        monkeypatch.setattr(ClearMLPublication, "publish", _Publication.publish)
        definition, evaluator = self._definition()
        study = optuna.create_study(
            study_name=definition.name,
            storage=JournalStorage(JournalFileBackend(str(tmp_path / "optuna.log"))),
            direction="maximize",
        )
        study.set_user_attr("run_identity", definition.specification("a" * 64, "b" * 64).identity)
        study.ask()
        with AttemptStore(tmp_path / "attempts") as store:
            attempts = self._search(definition, tmp_path).run(store, evaluator, self._tracking())
            assert len(attempts) == 2
            assert {store.read(i).status for i in attempts} == {"abandoned", "completed"}
            assert len(study.trials) == 2

    def test_post_start_retention_failure_is_terminal_and_resume_does_not_repeat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure before evaluation remains failed and consumes its fixed budget slot."""
        monkeypatch.setattr(ClearMLPublication, "publish", _Publication.publish)
        monkeypatch.setattr(AttemptStore, "retain", _RetentionFailure.retain)
        definition, evaluator = self._definition()
        with AttemptStore(tmp_path / "attempts") as store:
            attempts = self._search(definition, tmp_path).run(store, evaluator, self._tracking())
            assert len(attempts) == 2
            assert {store.read(i).status for i in attempts} == {"failed"}
            assert all(
                "definition write failure" in store.read(i).events[-1].reason for i in attempts
            )
            assert (
                self._search(definition, tmp_path).run(store, evaluator, self._tracking())
                == attempts
            )

    def test_terminal_journal_without_attempt_history_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A moved or mismatched attempt root cannot turn an exhausted journal into success."""
        monkeypatch.setattr(ClearMLPublication, "publish", _Publication.publish)
        definition, evaluator = self._definition()
        with AttemptStore(tmp_path / "attempts") as store:
            self._search(definition, tmp_path).run(store, evaluator, self._tracking())
        with AttemptStore(tmp_path / "wrong-attempts") as other:
            with pytest.raises(ValueError, match="mapping differs"):
                self._search(definition, tmp_path).run(other, evaluator, self._tracking())


def test_comparison_configuration_byte_limit(tmp_path: Path) -> None:
    """Refuse oversized configuration before decoding for CLI and pipeline consumers."""
    path = tmp_path / "comparison.json"
    path.write_bytes(b" " * 1_048_577)
    with pytest.raises(ValueError, match="exceeds one MiB"):
        ComparisonStudy.read(path)


def test_unrepresentable_objective_fails_before_terminal_success() -> None:
    """An exact but oversized return cannot become a completed Optuna objective."""
    with pytest.raises(ValueError, match="finite Optuna projection"):
        TrialEvaluation(net_return=ExactRatio(numerator="1" + "0" * 400, denominator="1"))
