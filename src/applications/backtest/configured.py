"""Compose configured retained economics and reports without changing reference simulation."""

from __future__ import annotations

# standard library imports
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

# third party library imports
import msgspec
from clearml import Task
from lakefs_sdk import ApiClient, Configuration
from msgspec.structs import replace

# project library imports
from applications.backtest.workflow import _Rules, run_backtest
from market_data.adapters.sources import SourceAdapters
from market_data.query import QueryReader
from market_data.storage import DatasetVersion, LakeFSStorage, RawStore
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    BacktestRun,
    ClearMLDestination,
    ClearMLPublication,
    ExperimentSpec,
    PipelineRun,
    QuantStatsReport,
    ResearchInputs,
    ResultManifest,
    RunCheckpoint,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec
from simulation import EconomicCheckpoint


class _StorageAccess:
    """Compose an explicitly selected private lakeFS connection for an application action."""

    @staticmethod
    def open(endpoint: str, credentials: Path) -> ApiClient:
        """Read the selected private credentials without copying them into research records."""
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("lakeFS requires an explicit non-secret HTTP(S) API endpoint")
        fields = msgspec.json.decode(credentials.read_bytes(), type=dict[str, msgspec.Raw])
        return ApiClient(
            Configuration(
                host=endpoint,
                username=msgspec.json.decode(fields["access_key_id"], type=str),
                password=msgspec.json.decode(fields["secret_access_key"], type=str),
            )
        )


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
    if selected.economics.rule not in _Rules.definitions:
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
    task = Task.get_task(task_id=os.environ["CLEARML_TASK_ID"])
    parameters = task.get_parameters()
    codec = DomainCodec()
    plan = codec.decode_json(parameters["Run/plan"].encode(), PipelineRun)
    if (
        ImplementationIdentity.sha256() != plan.implementation_sha256
        or ExperimentSpec.installed_environment() != plan.environment_sha256
    ):
        raise ValueError("worker installed artifact/environment differs from pipeline pin")
    selected = codec.decode_json(parameters["Run/configuration"].encode(), BacktestRun)
    stage = parameters["Run/stage"]
    if stage not in ("inputs", "complete"):
        raise ValueError("unknown pipeline research stage")
    output = Path(parameters["Run/output"])
    config = output / f"{stage}-{task.id}.json"
    ResultManifest.export(config, codec.encode_json(selected))
    inputs = Path(plan.inputs_root)
    attempts = Path(plan.attempts)
    association = (parameters["Run/controller"], task.id)
    client = None
    if plan.dataset_version is not None and plan.lakefs_endpoint is not None:
        client = _StorageAccess.open(
            plan.lakefs_endpoint, Path(os.environ["ALPHA_LAKEFS_CREDENTIALS"])
        )
    try:
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
            storage=None if client is None else LakeFSStorage(client),
        )
    finally:
        if client is not None:
            client.close()
        store = AttemptStore(attempts)
        for history in store.histories():
            attempt = history.start.attempt_id
            if "pipeline-step" in store.artifacts(attempt) and store.artifact(
                attempt, "pipeline-step"
            ) == codec.encode_json(association):
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
                ResultManifest.export(
                    output / f"{stage}-{task.id}-attempt.json", codec.encode_json(history)
                )
