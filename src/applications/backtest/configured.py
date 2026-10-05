"""Compose configured retained economics and reports without changing reference simulation."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from applications.backtest.comparison import compare_parameters
from applications.backtest.workflow import run_backtest
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryReader
from market_data.storage import DatasetVersion, LakeFSStorage, RawStore
from research.experiments import AttemptHistory, AttemptStore, ExperimentSpec
from research.studies import (
    BacktestRun,
    ClearMLDestination,
    ClearMLPublication,
    ComparisonStudy,
    PipelineRun,
    PipelineStepTask,
    QuantStatsReport,
    ResearchInputs,
    ResultManifest,
    RunCheckpoint,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import EconomicCheckpoint
from strategies import RuleRegistry


def run_configured(
    config: Path,
    snapshots: Path,
    raw: Path,
    *,
    attempts: Path,
    max_bytes: int,
    tracking: ClearMLDestination,
    resume: Path | None = None,
    stop_at: datetime | None = None,
    stage: Literal["inputs", "complete"] = "complete",
    upstream: str | None = None,
    version: DatasetVersion | None = None,
    storage: LakeFSStorage | None = None,
    step: tuple[str, str] | None = None,
) -> AttemptHistory:
    """Retain a complete configured attempt, committing reports before success.

    Args:
        config: Strict resolved BacktestRun JSON; no activation or implicit acquisition.
        snapshots: Existing published dataset root.
        raw: Existing source byte store.
        attempts: Existing single-writer attempt root.
        max_bytes: Positive saved-query admission bound.
        tracking: Explicit destination; external publication is independently recoverable.
        resume: Optional complete checkpoint from the identical semantic run.
        stop_at: Optional completed-step clock; retains an abandoned checkpoint attempt.
        stage: Selection/features only or complete economics/report, using the same consumer.
        upstream: Optional completed selection attempt; verify its exact outputs before use.
        version: Optional immutable lakeFS manifest required by versioned configuration.
        storage: Explicit authenticated lakeFS adapter, without credentials in records.
        step: Optional pipeline/task IDs attached to the attempt before input access.

    Returns:
        Immutable terminal history after acknowledged ClearML publication.

    Raises:
        ValueError: Configuration, checkpoint or result admission fails.
        Exception: Computation or publication fails with retained original attempt outcome.
    """
    selected = BacktestRun.read(config)
    if not RuleRegistry().supports(selected.economics.rule):
        raise ValueError("unsupported installed target rule")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if stage not in ("inputs", "complete"):
        raise ValueError("unsupported configured execution stage")
    if (selected.versioned_inputs_sha256 is None) != (version is None):
        raise ValueError("versioned configuration requires its exact lakeFS manifest")
    if version is not None and (
        version.identity != selected.versioned_inputs_sha256 or storage is None
    ):
        raise ValueError("versioned inputs require the pinned manifest and lakeFS adapter")
    codec = DomainCodec()
    spec = selected.specification(
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    if stage == "inputs":
        if resume is not None or stop_at is not None:
            raise ValueError("input preparation does not resume economic checkpoints")
        parameters: tuple[tuple[str, str], ...] = (
            *spec.parameters,
            ("stage", "selection-features"),
        )
        spec = replace(spec, parameters=parameters)
    restored = None
    if resume is not None:
        restored = codec.decode_json(resume.read_bytes(), RunCheckpoint)
        if restored.run_identity != spec.identity:
            raise ValueError("checkpoint configuration, code or environment differs")
    with AttemptStore(attempts) as store:
        start = store.start(
            spec,
            at=datetime.now(UTC),
            invocation="alpha-backtest run",
            request=codec.encode_json(selected),
        )
        publication = ClearMLPublication(store, tracking)
        publication.enqueue(start.attempt_id)
        try:
            if step is not None:
                store.retain(start.attempt_id, "pipeline-step", codec.encode_json(step))
            if version is not None and storage is not None:
                if snapshots != raw.parent / "snapshots" or raw.name != "raw":
                    raise ValueError("versioned input cache requires sibling raw/snapshots roots")
                storage.materialize(version, raw.parent, max_bytes=max_bytes)
                store.retain(start.attempt_id, "dataset-version", codec.encode_json(version))
            reader = QueryReader.read(
                snapshots,
                RawStore(raw),
                readers=SourceAdapters(),
                identity=selected.snapshot_id,
                precedence=(selected.economics.binding,),
                max_bytes=max_bytes,
            )
            inputs = ResearchInputs.collect(selected, reader)
            if upstream is not None:
                ResultManifest.read(store, upstream)
                if store.artifact(upstream, "research-inputs") != codec.encode_json(inputs):
                    raise ValueError(
                        "upstream selection/features differ from resolved configuration"
                    )
                store.retain(
                    start.attempt_id,
                    "upstream-attempt",
                    codec.encode_json(
                        {
                            "attempt_id": upstream,
                            "result": store.read(upstream).events[-1].result,
                        }
                    ),
                )
            if version is not None:
                if "features" not in version.components:
                    raise ValueError("a versioned backtest requires derived feature bytes")
                if selected.feature is None or (
                    raw.parent / "features/diagnostics.json"
                ).read_bytes() != codec.encode_json(inputs.features):
                    raise ValueError("versioned derived features differ from causal recomputation")
            if stage == "inputs":
                manifest = ResultManifest.retain(
                    store,
                    start.attempt_id,
                    {
                        "resolved-configuration": codec.encode_json(selected),
                        "research-inputs": codec.encode_json(inputs),
                        "feature-snapshot": codec.encode_json(inputs.features),
                    },
                )
                store.finish(
                    start.attempt_id,
                    status="completed",
                    at=datetime.now(UTC),
                    reason="Verified selection and causal diagnostic features committed",
                    result=codec.encode_json(manifest),
                )
                publication.publish(start.attempt_id)
                return store.read(start.attempt_id)
            result = run_backtest(
                reader,
                selected.economics,
                checkpoint=None if restored is None else restored.economic,
                stop_at=stop_at,
            )
            if isinstance(result, EconomicCheckpoint):
                store.retain(
                    start.attempt_id,
                    "checkpoint",
                    codec.encode_json(RunCheckpoint(run_identity=spec.identity, economic=result)),
                )
                store.finish(
                    start.attempt_id,
                    status="abandoned",
                    at=datetime.now(UTC),
                    reason="Requested checkpoint; resume creates a new execution attempt",
                )
            else:
                report = QuantStatsReport.build(result, selected.report)
                if selected.split is None:
                    limitations: tuple[str, ...] = (*report.limitations, *inputs.limitations)
                    report = replace(report, limitations=limitations)
                manifest = ResultManifest.retain(
                    store,
                    start.attempt_id,
                    {
                        "resolved-configuration": codec.encode_json(selected),
                        "research-inputs": codec.encode_json(inputs),
                        "feature-snapshot": codec.encode_json(inputs.features),
                        "economic-reference": codec.encode_json(result),
                        "report-inputs": codec.encode_json((selected.report, report.periods)),
                        "report": codec.encode_json(report),
                        "report-html": QuantStatsReport.render(report),
                    },
                )
                store.finish(
                    start.attempt_id,
                    status="completed",
                    at=datetime.now(UTC),
                    reason="Exact economics and all report artifacts committed",
                    result=codec.encode_json(manifest),
                )
        except (Exception, KeyboardInterrupt) as error:
            if store.read(start.attempt_id).status == "incomplete":
                store.finish(
                    start.attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            raise
        publication.publish(start.attempt_id)
        return store.read(start.attempt_id)


def run_worker() -> None:
    """Read actual server overrides, validate the pinned installation and retain step lineage.

    Raises:
        ValueError: The installed environment, resolved configuration or stage is unsupported.
        Exception: The selected stage fails; the agent records its original failed task.
    """
    task = PipelineStepTask.get(os.environ["CLEARML_TASK_ID"])
    parameters = task.parameters()
    codec = DomainCodec()
    plan = codec.decode_json(parameters["Run/plan"].encode(), PipelineRun)
    if (
        ImplementationIdentity.sha256() != plan.implementation_sha256
        or ExperimentSpec.installed_environment() != plan.environment_sha256
    ):
        raise ValueError("worker installed artifact/environment differs from pipeline pin")
    selected = codec.decode_json(parameters["Run/configuration"].encode(), BacktestRun)
    stage = parameters["Run/stage"]
    if stage not in ("inputs", "complete", "comparison"):
        raise ValueError("unknown pipeline research stage")
    output = Path(parameters["Run/output"])
    if (
        output.parent != Path(plan.output_root)
        or len(output.name) != 32
        or any(character not in "0123456789abcdef" for character in output.name)
    ):
        raise ValueError("pipeline output differs from the resolved plan")
    config = output / (
        f"configuration-{stage}-{task.identity}.json"
        if stage == "comparison"
        else f"{stage}-{task.identity}.json"
    )
    ResultManifest.export(config, codec.encode_json(selected))
    inputs = Path(plan.inputs_root)
    attempts = Path(plan.attempts)
    association = (parameters["Run/controller"], task.identity)
    comparison_attempt_ids: tuple[str, ...] = ()
    storage = None
    if plan.dataset_version is not None and plan.lakefs_endpoint is not None:
        storage = LakeFSStorage.connect(
            plan.lakefs_endpoint, Path(os.environ["ALPHA_LAKEFS_CREDENTIALS"])
        )
    try:
        if stage == "comparison":
            if plan.comparison is None or "Run/comparison" not in parameters:
                raise ValueError("comparison pipeline stage has no comparison configuration")
            comparison = codec.decode_json(parameters["Run/comparison"].encode(), ComparisonStudy)
            if comparison != plan.comparison or comparison.variants[0] != selected:
                raise ValueError("comparison configuration differs from the resolved plan")
            journal = Path(parameters.get("Run/journal", ""))
            expected_journal = Path(plan.output_root) / "comparison-journal.jsonl"
            if journal != expected_journal:
                raise ValueError("comparison pipeline journal differs from the resolved output")
            comparison_config = output / f"comparison-{task.identity}.json"
            ResultManifest.export(comparison_config, codec.encode_json(comparison))
            comparison_attempt_ids = compare_parameters(
                comparison_config,
                inputs / "snapshots",
                inputs / "raw",
                attempts=attempts,
                journal=journal,
                max_bytes=plan.max_bytes,
                tracking=plan.tracking,
                step=association,
            )
        else:
            run_configured(
                config,
                inputs / "snapshots",
                inputs / "raw",
                attempts=attempts,
                max_bytes=plan.max_bytes,
                tracking=plan.tracking,
                stage="inputs" if stage == "inputs" else "complete",
                upstream=parameters["Run/upstream"] or None,
                step=association,
                version=plan.dataset_version,
                storage=storage,
            )
    finally:
        if storage is not None:
            storage.close()
        store = AttemptStore(attempts)
        matched: list[AttemptHistory] = []
        for history in store.histories():
            attempt = history.start.attempt_id
            pipeline_artifacts = tuple(
                name
                for name in store.artifacts(attempt)
                if name == "pipeline-step" or name.startswith("pipeline-step-")
            )
            if any(
                store.artifact(attempt, name) == codec.encode_json(association)
                for name in pipeline_artifacts
            ):
                matched.append(history)
                parameters.update(
                    {
                        "retained/attempt_id": attempt,
                        "retained/run_identity": history.start.run_identity,
                        "retained/outcome": history.status,
                        "retained/result_sha256": hashlib.sha256(
                            codec.encode_json(history)
                        ).hexdigest(),
                    }
                )
                task.set_parameters(parameters)
        if stage == "comparison":
            histories_by_id = {history.start.attempt_id: history for history in store.histories()}
            histories = (
                tuple(
                    histories_by_id[attempt_id]
                    for attempt_id in comparison_attempt_ids
                    if attempt_id in histories_by_id
                )
                if comparison_attempt_ids
                else tuple(matched)
            )
            if histories:
                last = histories[-1]
                parameters.update(
                    {
                        "retained/attempt_id": last.start.attempt_id,
                        "retained/run_identity": last.start.run_identity,
                        "retained/outcome": last.status,
                    }
                )
                task.set_parameters(parameters)
                parameters.update(
                    {
                        "retained/attempt_ids": codec.encode_json(
                            tuple(history.start.attempt_id for history in histories)
                        ).decode(),
                        "retained/result_sha256": hashlib.sha256(
                            codec.encode_json(histories)
                        ).hexdigest(),
                    }
                )
                task.set_parameters(parameters)
                ResultManifest.export(
                    output / f"{stage}-{task.identity}-attempts.json", codec.encode_json(histories)
                )
        elif matched:
            ResultManifest.export(
                output / f"{stage}-{task.identity}-attempt.json", codec.encode_json(matched[-1])
            )
