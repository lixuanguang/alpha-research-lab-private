"""Exercise fresh components through installed temporal studies and exact economics."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from dataclasses import replace as dataclass_replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from applications.explore import (
    StudyComponents,
    StudyJobHandler,
    compare_studies,
    evaluate_study,
    schedule_study,
)
from financial_units import ExactRatio
from research.experiments import AttemptStore, Fingerprint, TimeWindow
from research.studies import (
    ClearMLDestination,
    DecisionComparison,
    DecisionStudy,
    PublicationPolicy,
    StudyArtifact,
    StudyReportReader,
    StudyResult,
)
from runtime import (
    ImplementationIdentity,
    JobQueue,
    JobRun,
    JobSpec,
    JobWorkerPool,
    WorkspaceBackup,
)
from serialization import DomainCodec
from strategies import OrderIntent


class _ScenarioView(Protocol):
    """Expose the authored clock required by scheduled study acceptance."""

    def at(self, second: int) -> datetime:
        """Return one authored UTC clock."""
        ...


class _LostStudyAcknowledgement:
    """Lose one response after a real completed study to exercise retry reconciliation."""

    def __init__(self, handler: StudyJobHandler) -> None:
        """Bind the actual installed workflow and one bounded transport failure."""
        self._handler = handler
        self._lost = False

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Retain the real completed effect before the first artificial response loss."""
        result = self._handler.execute(spec, run)
        if not self._lost:
            self._lost = True
            raise OSError("injected completed-study acknowledgement loss")
        return result


class _Run:
    """Assert the installed API's retained behavior with independent hand economics."""

    @staticmethod
    def read(root: Path) -> None:
        """Reopen typed results and custom reports in a fresh isolated process."""
        ids = msgspec.json.decode((root / "attempt-ids.json").read_bytes(), type=tuple[str, ...])
        store = AttemptStore(root / "attempts")
        for attempt in ids:
            result = StudyResult.read(store, attempt)
            report = StudyReportReader.read(store, attempt)
            assert len(result.folds) == 2
            assert tuple(f.economics.mark.net.value for f in result.folds) == (
                Decimal("-2.20"),
                Decimal("-2.20"),
            )
            assert report.metrics[0].definition.name == "installed-fill-count"
            assert report.metrics[0].value == ExactRatio(numerator="2", denominator="1")
            assert report.charts[0].title == "Custom fold net profit"
            assert b"Custom fold net profit" in store.artifact(attempt, "report-html")

    @staticmethod
    def jobs(
        root: Path, scenario: _ScenarioView, components: StudyComponents, study: DecisionStudy
    ) -> None:
        """Recover completed study effects and reopen queue/results after a clean restore."""
        workspace = root / "workspace"
        queue = JobQueue(workspace / "jobs")
        handler = StudyJobHandler({study.identity: components}, workspace / "studies")
        spec = schedule_study(
            queue,
            study,
            job_id="retained-study",
            run_at=scenario.at(0),
            publication=PublicationPolicy(mode="local"),
            retry_delay_seconds=0,
        )
        pool = JobWorkerPool(
            queue,
            {"decision-study": _LostStudyAcknowledgement(handler)},
            max_workers=2,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=StudyJobHandler.environment_sha256(),
        )
        pool.run_until_idle()
        state = queue.read(spec.job_id)
        assert state.status == "completed" and state.attempts == 2
        family = hashlib.sha256(study.family.encode()).hexdigest()
        store = AttemptStore(workspace / "studies" / family)
        histories = store.histories()
        assert len(histories) == 1 and histories[0].status == "completed"
        assert len(StudyResult.read(store, histories[0].start.attempt_id).folds) == 2
        queue.submit(spec)
        assert queue.read(spec.job_id) == state
        WorkspaceBackup.create(workspace, root / "workspace-backup", components=("jobs", "studies"))
        restored = root / "workspace-restored"
        WorkspaceBackup.restore(root / "workspace-backup", restored)
        assert JobQueue(restored / "jobs").read(spec.job_id) == state
        reopened = AttemptStore(restored / "studies" / family)
        assert reopened.histories() == histories
        assert StudyResult.read(reopened, histories[0].start.attempt_id) == StudyResult.read(
            store, histories[0].start.attempt_id
        )

    @staticmethod
    def execute(root: Path) -> None:
        """Run typed, serialized, search, local/deferred and holdout paths."""
        consumer_root = str(Path(__file__).resolve().parent)
        if consumer_root not in sys.path:
            sys.path.insert(0, consumer_root)
        # third party library imports
        from research_workflows.scenario import (
            _DecisionInputClock,
            _MarketClocks,
            _OrderPolicy,
            _Scenario,
            _ShiftedDecisionSource,
            _TargetPolicy,
        )

        root.mkdir(exist_ok=True)
        codec, scenario = DomainCodec(), _Scenario()
        buy = _TargetPolicy(scenario.dimension, threshold=5)
        flat = _TargetPolicy(scenario.dimension, threshold=100)
        failing = _TargetPolicy(scenario.dimension, threshold=5, fail=True)
        study = scenario.study(buy, fitted=True)
        components = scenario.components(buy, fitted=True)
        _Run.jobs(root, scenario, components, study)
        changed_payload = scenario.artifact.payload + b"\n# changed extension bytes\n"
        changed_artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name=scenario.artifact.fingerprint.name,
                sha256=hashlib.sha256(changed_payload).hexdigest(),
            ),
            payload=changed_payload,
        )
        changed_study = replace(study, extensions=(changed_artifact.fingerprint,))
        assert changed_study.identity != study.identity
        attempts = root / "attempts"
        local = PublicationPolicy(mode="local")
        first = evaluate_study(study, components=components, attempts=attempts, publication=local)
        assert first.status == "completed"
        assert (
            Fingerprint(
                name=f"extension:{scenario.artifact.fingerprint.name}",
                sha256=scenario.artifact.fingerprint.sha256,
            )
            in first.start.spec.components
        )
        config = root / "study.json"
        config.write_bytes(codec.encode_json(study))
        changed_config = root / "changed-study.json"
        changed_config.write_bytes(codec.encode_json(changed_study))
        assert DecisionStudy.read(config).identity == study.identity
        assert DecisionStudy.read(changed_config).identity == changed_study.identity
        assert DecisionStudy.read(changed_config).identity != DecisionStudy.read(config).identity
        destination = ClearMLDestination(
            project="installed-studies",
            api_uri="http://127.0.0.1:18008",
            files_uri="http://127.0.0.1:18081",
        )
        second = evaluate_study(
            config,
            components=components,
            attempts=attempts,
            publication=PublicationPolicy(mode="deferred", destination=destination),
        )
        assert second.status == "completed"
        store = AttemptStore(attempts)
        assert "clearml-destination" not in store.artifacts(first.start.attempt_id)
        assert "clearml-destination" in store.artifacts(second.start.attempt_id)
        assert "clearml-receipt" not in store.artifacts(second.start.attempt_id)
        for history in (first, second):
            assert (
                store.artifact(history.start.attempt_id, "extension-0000")
                == scenario.artifact.payload
            )
            result = StudyResult.read(store, history.start.attempt_id)
            assert len(result.folds) == 2
            for fold, trained in zip(result.folds, ((1, 2), (3, 4)), strict=True):
                assert fold.model is not None
                assert len(fold.model.fit_rows) == 2
                assert (
                    tuple(int(value) for value in fold.model.state.decode().split(",")) == trained
                )
                assert fold.economics.mark.net.value == Decimal("-2.20")
                assert fold.economics.ledger.fills[0].effective.value == Decimal("101")
                assert fold.economics.ledger.fills[0].fee.value == Decimal("0.20")
                assert not any(item.status == "holdout_consumed" for item in history.events)
        (root / "attempt-ids.json").write_bytes(
            codec.encode_json((first.start.attempt_id, second.start.attempt_id))
        )
        subprocess.run([sys.executable, "-I", __file__, str(root), "read"], check=True, timeout=90)
        rule = scenario.study(flat, fitted=False, family="installed-rule-only-control")
        rule_result = evaluate_study(
            rule,
            components=scenario.components(flat, fitted=False),
            attempts=attempts,
            publication=local,
        )
        assert rule_result.status == "completed"
        assert (
            StudyResult.read(store, rule_result.start.attempt_id).folds[0].economics.mark.net.value
            == 0
        )
        shifted_policy = _TargetPolicy(scenario.dimension, threshold=0)
        shifted = scenario.study(
            shifted_policy, fitted=True, transformed=True, family="installed-shifted-study"
        )
        shifted_history = evaluate_study(
            shifted,
            components=scenario.components(shifted_policy, fitted=True, transformed=True),
            attempts=attempts,
            publication=local,
        )
        assert shifted_history.status == "completed"
        shifted_result = StudyResult.read(store, shifted_history.start.attempt_id)
        for fold, center, prediction in zip(
            shifted_result.folds,
            (b"3/2", b"7/2"),
            (
                ExactRatio(numerator="11", denominator="2"),
                ExactRatio(numerator="9", denominator="2"),
            ),
            strict=True,
        ):
            assert fold.transform is not None and fold.transform.state == center
            assert fold.model is not None and fold.model.state == b"shifted-training-only"
            assert fold.transform.fit_rows == fold.model.fit_rows
            assert len(fold.transform.fit_rows) == 2
            assert tuple(item.value for item in fold.predictions) == (prediction,)
            assert fold.economics.mark.net.value == Decimal("-2.20")
        order_policy = _OrderPolicy(scenario)
        for optimistic, filled_at, ahead in (
            (False, scenario.at(14), scenario.quantity("2")),
            (True, scenario.at(13), scenario.quantity("0")),
        ):
            order_study = scenario.study(
                order_policy,
                fitted=False,
                passive=True,
                optimistic=optimistic,
                family=f"installed-passive-order-{optimistic}",
            )
            order_history = evaluate_study(
                order_study,
                components=scenario.components(
                    order_policy, fitted=False, passive=True, optimistic=optimistic
                ),
                attempts=attempts,
                publication=local,
            )
            assert order_history.status == "completed"
            order_result = StudyResult.read(store, order_history.start.attempt_id).folds[0]
            assert order_result.decisions[0].intent == OrderIntent(
                side="buy",
                quantity=scenario.quantity("1"),
                limit=scenario.price("99"),
                time_in_force="post-only",
            )
            assert len(order_result.economics.orders) == 1
            order = order_result.economics.orders[0]
            assert order.status == "filled" and order.queue_ahead == ahead
            assert len(order.fills) == 1 and order.fills[0].filled_at == filled_at
            assert order.fills[0].effective.value == Decimal("99")
            assert order.fills[0].fee.value == Decimal("0.20")
            assert order_result.economics.mark.net.value == Decimal("-0.20")
            order_report = StudyReportReader.read(store, order_history.start.attempt_id)
            assert order_report.metrics[0].value == ExactRatio(numerator="1", denominator="1")
            assert order_report.charts[0].observations[0].value == ExactRatio(
                numerator="-1", denominator="5"
            )
            assert b"Custom fold net profit" in store.artifact(
                order_history.start.attempt_id, "report-html"
            )
        boundary = scenario.study(flat, fitted=False, family="installed-contiguous-validation")
        boundary_fold = boundary.folds[0]
        boundary = replace(
            boundary,
            folds=(
                replace(
                    boundary_fold,
                    split=replace(
                        boundary_fold.split,
                        validation=TimeWindow(
                            start=boundary_fold.split.validation.start,
                            end=boundary_fold.split.holdout.start,
                        ),
                    ),
                ),
            ),
        )
        boundary_history = evaluate_study(
            boundary,
            components=scenario.components(flat, fitted=False),
            attempts=attempts,
            publication=local,
        )
        assert boundary_history.status == "completed"
        retained_market = msgspec.json.decode(
            store.artifact(boundary_history.start.attempt_id, "market-0000"),
            type=tuple[_MarketClocks, ...],
        )
        assert retained_market
        assert max(row.source_at for row in retained_market) < boundary_fold.split.holdout.start
        assert (
            max(max(row.source_at, row.known_at) for row in retained_market)
            < boundary_fold.split.holdout.start
        )
        shifted_source_study = scenario.study(
            flat, fitted=False, family="installed-shifted-source-rejected"
        )
        try:
            evaluate_study(
                shifted_source_study,
                components=dataclass_replace(
                    scenario.components(flat, fitted=False),
                    source=_ShiftedDecisionSource(scenario.source),
                ),
                attempts=attempts,
                publication=local,
            )
        except ValueError as error:
            assert "source input differs" in str(error)
        else:
            raise AssertionError("source silently advanced the declared decision cutoff")
        shifted_source_attempts = tuple(
            history
            for history in store.histories()
            if history.start.spec.family == shifted_source_study.family
        )
        assert len(shifted_source_attempts) == 1
        failed_source = shifted_source_attempts[0]
        assert (
            failed_source.status == "failed"
            and failed_source.start.request == codec.encode_json(shifted_source_study)
        )
        failed_artifacts = store.artifacts(failed_source.start.attempt_id)
        assert "inputs-0000" in failed_artifacts
        captured_inputs = msgspec.json.decode(
            store.artifact(failed_source.start.attempt_id, "inputs-0000"),
            type=tuple[_DecisionInputClock, ...],
        )
        assert len(captured_inputs) == 1
        assert captured_inputs[0].entity == scenario.entity
        assert captured_inputs[0].decision_at == scenario.at(10) + timedelta(microseconds=1)
        assert not {
            "features-0000",
            "market-0000",
            "fold-0000",
            "study-result",
            "study-report",
            "report-html",
        } & set(failed_artifacts)
        variants = (
            study,
            scenario.study(flat, fitted=True),
            scenario.study(failing, fitted=True),
        )
        search = DecisionComparison(
            name="installed-decision-search",
            variants=variants,
            budget=3,
            seed=17,
            minimum_return=ExactRatio(numerator="-1", denominator="1"),
        )
        bindings = {
            run.identity: scenario.components(policy, fitted=True)
            for run, policy in zip(variants, (buy, flat, failing), strict=True)
        }
        journal = root / "search.log"
        early = compare_studies(
            search,
            bindings=bindings,
            attempts=attempts,
            journal=journal,
            publication=local,
            max_trials=1,
        )
        assert len(early) == 1
        original_history = store.read(early[0])
        assert "clearml-destination" not in store.artifacts(early[0])
        deferred = PublicationPolicy(mode="deferred", destination=destination)
        searched = compare_studies(
            search, bindings=bindings, attempts=attempts, journal=journal, publication=deferred
        )
        assert len(searched) == 3
        assert store.read(early[0]) == original_history
        searched_histories = {item: store.read(item) for item in searched}
        for item, history in searched_histories.items():
            assert codec.decode_json(history.start.request, DecisionStudy).identity in bindings
            assert (
                codec.decode_json(store.artifact(item, "clearml-destination"), ClearMLDestination)
                == destination
            )
            assert "clearml-receipt" not in store.artifacts(item)
        assert (
            compare_studies(
                search, bindings=bindings, attempts=attempts, journal=journal, publication=deferred
            )
            == searched
        )
        assert {item: store.read(item) for item in searched} == searched_histories
        assert all("clearml-receipt" not in store.artifacts(item) for item in searched)
        assert {store.read(item).status for item in searched} == {"completed", "failed"}
        assert not any(
            event.status == "holdout_consumed"
            for item in searched
            for event in store.read(item).events
        )
        holdout = scenario.study(buy, fitted=True, partition="holdout")
        try:
            evaluate_study(
                holdout,
                components=scenario.components(buy, fitted=True, fail_holdout_market=True),
                attempts=attempts,
                publication=local,
            )
        except OSError as error:
            assert "holdout market" in str(error)
        else:
            raise AssertionError("holdout read failure was not propagated")
        consumed = tuple(
            history
            for history in store.histories()
            if history.start.spec.family == holdout.family
            and any(event.status == "holdout_consumed" for event in history.events)
        )
        assert len(consumed) == 1 and consumed[0].status == "failed"
        try:
            evaluate_study(
                scenario.study(flat, fitted=True, partition="holdout"),
                components=scenario.components(flat, fitted=True),
                attempts=attempts,
                publication=local,
            )
        except ValueError as error:
            assert "already consumed" in str(error)
        else:
            raise AssertionError("changed run reused the family holdout")
        print(
            codec.encode_json(
                {
                    "typed_and_json": True,
                    "fresh_model_feature_policy_metric_chart": True,
                    "fitted_transform_train_only": True,
                    "passive_order_queue_sensitive": True,
                    "contiguous_validation_precedes_holdout": True,
                    "shifted_source_rejected": True,
                    "walk_forward_folds": 2,
                    "deferred_retained": True,
                    "search_attempts": len(searched),
                    "failed_holdout_recorded": True,
                    "job_retry_single_study_and_workspace_restore": True,
                }
            ).decode()
        )


if __name__ == "__main__":
    _Run.read(Path(sys.argv[1])) if len(sys.argv) == 3 else _Run.execute(Path(sys.argv[1]))
