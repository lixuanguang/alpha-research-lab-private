"""Publish retained attempts to ClearML with durable intent and reconciliation receipts."""

from __future__ import annotations

# standard library imports
import hashlib
import math
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

# third party library imports
import msgspec
from clearml import Model, OutputModel, Task
from clearml.backend_api import Session

# project library imports
from research.experiments import AttemptStore, Fingerprint
from research.studies.configuration import BacktestRun
from research.studies.diagnostics import AlphalensReport
from research.studies.evaluation import EvaluationRecord, TrialEvaluation
from serialization import DomainCodec, WireRecord


class ClearMLDestination(WireRecord, frozen=True, kw_only=True):
    """Select a non-secret publication destination; SDK credentials stay outside records."""

    project: str
    api_uri: str
    files_uri: str

    def __post_init__(self) -> None:
        """Refuse empty projects and embedded storage credentials/query secrets."""
        if type(self.project) is not str or not self.project.strip():
            raise ValueError("tracking requires an explicit project")
        for uri in (self.api_uri, self.files_uri):
            parts = urlsplit(uri)
            if (
                parts.scheme not in ("http", "https")
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValueError("tracking requires non-secret HTTP(S) endpoints")


class TrackedModel(WireRecord, frozen=True, kw_only=True):
    """Describe immutable model bytes without coupling tracking to a model implementation."""

    version_sha256: str
    state_sha256: str
    state_bytes: bytes
    manifest_bytes: bytes
    creation_attempt: str

    def __post_init__(self) -> None:
        """Verify both actual artifacts before linking mutable server model records."""
        if type(self.state_bytes) is not bytes or type(self.manifest_bytes) is not bytes:
            raise TypeError("tracked model requires immutable artifact bytes")
        Fingerprint(name="version", sha256=self.version_sha256)
        Fingerprint(name="state", sha256=self.state_sha256)
        if (
            hashlib.sha256(self.state_bytes).hexdigest() != self.state_sha256
            or hashlib.sha256(self.manifest_bytes).hexdigest() != self.version_sha256
            or re.fullmatch(r"[a-f0-9]{32}", self.creation_attempt) is None
        ):
            raise ValueError("tracked model artifact integrity mismatch")


class PublicationReceipt(WireRecord, frozen=True, kw_only=True):
    """Bind server task/model IDs to the exact retained terminal outcome."""

    attempt_id: str
    task_id: str
    model_ids: tuple[tuple[str, str], ...]
    history_sha256: str
    published_at: datetime

    def __post_init__(self) -> None:
        """Reject missing mappings and unversioned terminal evidence."""
        if type(self.model_ids) is not tuple or any(
            type(pair) is not tuple or len(pair) != 2 for pair in self.model_ids
        ):
            raise TypeError("receipt model mappings must be immutable pairs")
        if re.fullmatch(r"[a-f0-9]{32}", self.attempt_id) is None or not self.task_id:
            raise ValueError("receipt requires an attempt/task mapping")
        Fingerprint(name="history", sha256=self.history_sha256)
        self._require_utc(self.published_at, field_name="published_at")
        for version, model_id in self.model_ids:
            Fingerprint(name="model", sha256=version)
            if not model_id:
                raise ValueError("receipt requires model IDs")


class ClearMLPublication:
    """Reconcile one local single-writer outbox without refitting or rereading holdouts.

    Task.create disables repository discovery and does not install Task.init's
    framework, argparse, stream or resource hooks. Only explicit retained records
    and typed metric projections are uploaded. SDK task reuse/reset is never used.
    """

    def __init__(self, store: AttemptStore, destination: ClearMLDestination) -> None:
        """Bind the owning writer and explicit non-secret destination.

        Args:
            store: Entered retained attempt store; no second writer is introduced.
            destination: Server project and artifact endpoint; SDK auth is configured externally.
        """
        destination.__post_init__()
        self._store, self._destination = store, destination
        self._codec = DomainCodec()

    def enqueue(self, attempt_id: str) -> None:
        """Persist publication intent before computation starts or terminal evidence is exposed.

        Args:
            attempt_id: Existing retained execution.
        """
        self._store.retain(
            attempt_id, "clearml-destination", self._codec.encode_json(self._destination)
        )

    def publish(self, attempt_id: str) -> PublicationReceipt:
        """Reconcile existing task/model identity, then publish exact retained terminal bytes.

        Args:
            attempt_id: Terminal execution; failures/rejections/abandonment remain their outcomes.

        Returns:
            Durable receipt. Repeating publication returns the existing receipt unchanged.

        Raises:
            ValueError: The outcome is incomplete, artifacts differ, or reconciliation is ambiguous.
            RuntimeError: The server did not acknowledge an artifact or metric flush.
            Exception: SDK/transport failures propagate; local terminal history is unchanged.
        """
        try:
            return self._publish(attempt_id)
        except (Exception, KeyboardInterrupt) as error:
            self._store.retain(
                attempt_id,
                f"clearml-failure-{uuid4().hex}",
                self._codec.encode_json(
                    {
                        "recorded_at": datetime.now(UTC),
                        "error_type": type(error).__name__,
                        "status": "pending publication; retry does not rerun computation",
                    }
                ),
            )
            raise

    def _publish(self, attempt_id: str) -> PublicationReceipt:
        """Commit publication only after explicit remote artifact and terminal acknowledgments."""
        self.enqueue(attempt_id)
        history = self._store.read(attempt_id)
        if history.status == "incomplete":
            raise ValueError("incomplete execution must be finished or explicitly abandoned")
        history_bytes = self._codec.encode_json(history)
        names = self._store.artifacts(attempt_id)
        if "clearml-receipt" in names:
            receipt = self._codec.decode_json(
                self._store.artifact(attempt_id, "clearml-receipt"), PublicationReceipt
            )
            if receipt.history_sha256 != hashlib.sha256(history_bytes).hexdigest():
                raise ValueError("receipt differs from retained terminal history")
            return receipt
        if Session.get_api_server_host().rstrip("/") != self._destination.api_uri.rstrip("/"):
            raise ValueError("SDK API server differs from the retained publication destination")
        task = self._task(attempt_id)
        if task.status == "created":
            task.mark_started()
            if task.status != "in_progress":
                raise RuntimeError("ClearML did not acknowledge task start")
        expected_status = "completed" if history.status == "completed" else "failed"
        if task.status not in ("in_progress", expected_status):
            raise ValueError("ClearML task outcome conflicts with immutable local history")
        if task.status == "in_progress":
            task.output_uri = self._destination.files_uri
        parameters = {
            "retained/attempt_id": attempt_id,
            "retained/run_identity": history.start.run_identity,
            "retained/family": history.start.spec.family,
            "retained/outcome": history.status,
            "retained/reason": history.events[-1].reason,
        }
        model_ids: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory(prefix="alpha-clearml-publication-") as directory:
            staging = Path(directory)
            self._upload(task, staging, "attempt-history", history_bytes)
            for name in names:
                if not name.startswith("clearml-"):
                    self._upload(task, staging, name, self._store.artifact(attempt_id, name))
            if "tracked-models" in names:
                models = msgspec.json.decode(
                    self._store.artifact(attempt_id, "tracked-models"),
                    type=tuple[TrackedModel, ...],
                )
                for model in models:
                    model_id = self._model(task, attempt_id, model, staging)
                    model_ids.append((model.version_sha256, model_id))
            if "evaluation" in names:
                evaluation = self._codec.decode_json(
                    self._store.artifact(attempt_id, "evaluation"), EvaluationRecord
                )
                ratio = evaluation.mean_squared_error
                projection = int(ratio.numerator) / int(ratio.denominator)
                if not math.isfinite(projection):
                    raise ValueError("metric cannot be projected to a finite dashboard value")
                parameters.update(
                    {
                        "evaluation/selection": evaluation.selection,
                        "evaluation/reason": evaluation.reason,
                        "evaluation/units": evaluation.units,
                    }
                )
                # A single value replaces the same projection on a retry; immutable
                # exact results remain in the retained evaluation artifact.
                if task.status == "in_progress":
                    task.get_logger().report_single_value(
                        "predictive/mean_squared_error", projection
                    )
            search = dict(history.start.spec.parameters).get("search")
            if search is not None and "trial" in dict(history.start.spec.parameters):
                parameters.update(
                    {
                        "comparison/search": search,
                        "comparison/trial": dict(history.start.spec.parameters)["trial"],
                    }
                )
                variants = tuple(
                    item for item in history.start.spec.inputs if item.name == "variant"
                )
                if variants:
                    variant = self._codec.decode_json(history.start.request, BacktestRun)
                    if variant.identity != variants[0].sha256:
                        raise ValueError("trial configuration differs from its retained identity")
                    parameters.update(
                        {
                            "comparison/variant": variant.identity,
                            "comparison/rule": variant.economics.rule,
                            "comparison/instance": variant.economics.instance,
                        }
                    )
                if "trial-evaluation" in names:
                    trial_evaluation = self._codec.decode_json(
                        self._store.artifact(attempt_id, "trial-evaluation"), TrialEvaluation
                    )
                    ratio = trial_evaluation.net_return
                    projection = int(ratio.numerator) / int(ratio.denominator)
                    if not math.isfinite(projection):
                        raise ValueError("trial objective has no finite dashboard projection")
                    parameters["comparison/exact_net_return"] = (
                        f"{ratio.numerator}/{ratio.denominator}"
                    )
                    if task.status == "in_progress":
                        task.get_logger().report_single_value("comparison/net_return", projection)
            if "factor-diagnostics" in names:
                report = self._codec.decode_json(
                    self._store.artifact(attempt_id, "factor-diagnostics"), AlphalensReport
                )
                parameters.update(
                    {
                        "factor/selection_identity": report.selection_identity,
                        "factor/horizon_us": str(report.horizon_us),
                        "factor/inapplicable_reason": report.inapplicable_reason or "applicable",
                        "factor/late_labels": str(len(report.late_labels)),
                        "factor/dropped_rows": str(len(report.dropped_rows)),
                    }
                )
                if task.status == "in_progress":
                    for kind, metrics in (
                        ("ic", report.information_coefficients),
                        ("quantile-return", report.quantile_returns),
                        ("turnover", report.turnover),
                    ):
                        for index, metric in enumerate(metrics):
                            if metric.value is not None:
                                task.get_logger().report_single_value(
                                    f"factor/{kind}/{index}/{metric.name}/{metric.period}",
                                    metric.value,
                                )
            if task.status == "in_progress":
                task.set_parameters(parameters)
                if not task.flush(wait_for_uploads=True):
                    raise RuntimeError("ClearML publication flush was not acknowledged")
            elif task.get_parameters() != parameters:
                raise ValueError("terminal ClearML task parameters differ from retained evidence")
            if task.status != expected_status:
                if history.status == "completed":
                    task.mark_completed(ignore_errors=False)
                else:
                    task.mark_failed(ignore_errors=False, status_reason=history.status)
            receipt = PublicationReceipt(
                attempt_id=attempt_id,
                task_id=task.id,
                model_ids=tuple(model_ids),
                history_sha256=hashlib.sha256(history_bytes).hexdigest(),
                published_at=datetime.now(UTC),
            )
            self._store.retain(attempt_id, "clearml-receipt", self._codec.encode_json(receipt))
            return receipt

    def _task(self, attempt_id: str) -> Task:
        """Resolve uncertain creation by unique exact name before any create request."""
        name = f"attempt-{attempt_id}"
        tasks = Task.get_tasks(
            project_name=self._destination.project, task_name=f"^{name}$", allow_archived=True
        )
        if len(tasks) > 1:
            raise ValueError("multiple ClearML tasks match one retained attempt")
        if tasks:
            return tasks[0]
        if "clearml-task-intent" in self._store.artifacts(attempt_id):
            raise ValueError(
                "uncertain task creation: no match; reconcile server absence explicitly"
            )
        self._store.retain(attempt_id, "clearml-task-intent", name.encode())
        return Task.create(
            project_name=self._destination.project,
            task_name=name,
            task_type="testing",
            detect_repository=False,
            add_task_init_call=False,
            packages=[],
        )

    def _model(self, task: Task, attempt_id: str, model: TrackedModel, staging: Path) -> str:
        """Reconcile an immutable version before linking its input or output model record."""
        model.__post_init__()
        matches = Model.query_models(
            project_name=self._destination.project,
            model_name=model.version_sha256,
            include_archived=True,
        )
        if len(matches) > 1:
            raise ValueError("multiple ClearML models match one retained version")
        is_output = model.creation_attempt == attempt_id
        if matches:
            found = matches[0]
            local = found.get_local_copy(raise_on_error=True)
            if (
                local is None
                or hashlib.sha256(Path(local).read_bytes()).hexdigest() != model.state_sha256
            ):
                raise ValueError("ClearML model bytes differ from retained state")
            model_id = found.id
            if is_output and task.status == "in_progress":
                OutputModel(task=task, base_model_id=model_id, name=model.version_sha256).publish()
        elif is_output and task.status == "in_progress":
            marker = f"clearml-model-{model.version_sha256}"
            if marker in self._store.artifacts(attempt_id):
                raise ValueError("uncertain model creation: reconcile server absence explicitly")
            self._store.retain(attempt_id, marker, model.manifest_bytes)
            output = OutputModel(
                task=task,
                name=model.version_sha256,
                framework="Custom",
                config_text=model.manifest_bytes.decode(),
            )
            state = staging / f"{model.state_sha256}.json"
            state.write_bytes(model.state_bytes)
            output.update_weights(
                weights_filename=str(state),
                upload_uri=self._destination.files_uri,
                auto_delete_file=False,
                async_enable=False,
            )
            output.publish()
            model_id = output.id
        else:
            raise ValueError("input model is unpublished; publish its creation attempt first")
        if not is_output and task.status == "in_progress":
            task.set_input_model(
                model_id=model_id,
                name=model.version_sha256,
                update_task_design=False,
                update_task_labels=False,
            )
        task.reload()
        role = "output" if is_output else "input"
        if model_id not in tuple(item.id for item in task.models.get(role, ())):
            raise ValueError("ClearML task is missing its retained model association")
        return model_id

    @staticmethod
    def _upload(task: Task, staging: Path, name: str, payload: bytes) -> None:
        """Verify a prior upload after an uncertain response instead of replacing its bytes."""
        existing = task.artifacts.get(name)
        if existing is not None:
            local = existing.get_local_copy()
            if local is None or Path(local).read_bytes() != payload:
                raise ValueError("ClearML artifact differs from retained publication")
            return
        if task.status != "in_progress":
            raise ValueError("terminal ClearML task is missing a retained artifact")
        suffix = ".html" if name.endswith("-html") else ".json"
        path = staging / f"{name}{suffix}"
        path.write_bytes(payload)
        if not task.upload_artifact(
            name=name, artifact_object=str(path), auto_pickle=False, wait_on_upload=True
        ):
            raise RuntimeError("ClearML artifact upload was not acknowledged")
