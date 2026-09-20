"""Describe the explicit ClearML 2.1.12 publication surface; no automatic hooks are used."""

# standard library imports
from collections.abc import Mapping, Sequence

class Artifact:
    """Describe a retained artifact's downloadable file."""
    def get_local_copy(self) -> str | None:
        """Download the explicitly named artifact file.

        Returns:
            Local file path, or absence on failure.
        """
        ...

class Logger:
    """Describe dashboard projections of retained exact metrics."""
    def report_single_value(self, name: str, value: float) -> None:
        """Publish one replaceable dashboard metric projection.

        Args:
            name: Explicit artifact, metric or model name.
            value: Finite dashboard projection; retained results remain exact.
        """
        ...

class Task:
    """Describe manually created, non-reused tasks."""

    @classmethod
    def init(
        cls,
        *,
        project_name: str,
        task_name: str,
        task_type: str,
        reuse_last_task_id: bool,
        auto_connect_frameworks: dict[str, bool],
        auto_connect_arg_parser: bool,
        auto_connect_streams: bool,
        auto_resource_monitoring: bool,
    ) -> Task:
        """Create a fresh controller with automatic capture disabled.

        Args:
            project_name: Selected local project.
            task_name: Distinct execution name.
            task_type: Controller task category.
            reuse_last_task_id: False for fresh executions.
            auto_connect_frameworks: Explicit disabled instrumentation switches.
            auto_connect_arg_parser: Disable argument hooks.
            auto_connect_streams: Disable stream hooks.
            auto_resource_monitoring: Disable resource hooks.

        Returns:
            Fresh controller task.
        """
        ...
    @classmethod
    def get_task(cls, *, task_id: str) -> Task:
        """Read the task supplied by the local agent.

        Args:
            task_id: Explicit server task identity.

        Returns:
            Existing server task.
        """
        ...
    @classmethod
    def clone(cls, *, source_task: str, name: str) -> Task:
        """Create a fresh editable task without resetting the original execution.

        Args:
            source_task: Original task ID.
            name: Distinct manual execution name.

        Returns:
            Fresh draft task.
        """
        ...
    @classmethod
    def enqueue(cls, *, task: Task, queue_name: str) -> object:
        """Submit an explicit task to the selected serial local queue.

        Args:
            task: Fresh draft execution.
            queue_name: Dedicated worker queue.

        Returns:
            Server acknowledgement.
        """
        ...
    def set_script(
        self, *, repository: str, working_dir: str, entry_point: str, binary: str, diff: str
    ) -> None:
        """Bind a minimal handoff to the verified installed environment.

        Args:
            repository: Empty; do not clone mutable source.
            working_dir: Explicit local launch directory.
            entry_point: SDK handoff filename.
            binary: Pinned installed Python interpreter.
            diff: Minimal process handoff to the installed application command.
        """
        ...
    def close(self) -> None:
        """Flush and close the controller task."""
        ...
    id: str
    status: str
    output_uri: str
    def reload(self) -> None:
        """Refresh acknowledged server associations before checking their identities."""
        ...
    def mark_started(self) -> None:
        """Start a newly created projection without forcing a historical task reset."""
        ...
    artifacts: dict[str, Artifact]
    models: Mapping[str, Sequence[Model]]
    def get_parameters(self) -> dict[str, str]:
        """Read searchable parameters for immutable terminal reconciliation.

        Returns:
            Explicit stored task parameters.
        """
        ...
    @classmethod
    def create(
        cls,
        *,
        project_name: str,
        task_name: str,
        task_type: str,
        detect_repository: bool,
        add_task_init_call: bool,
        packages: Sequence[str],
    ) -> Task:
        """Create a distinct task with automatic code discovery explicitly disabled.

        Args:
            project_name: Selected ClearML project.
            task_name: Unique retained attempt name or exact-match query.
            task_type: Declared research task category.
            detect_repository: Disable automatic repository discovery.
            add_task_init_call: Disable automatic instrumentation injection.
            packages: Explicit package list; no automatic environment capture.

        Returns:
            New server task handle.
        """
        ...
    @classmethod
    def get_tasks(
        cls, *, project_name: str, task_name: str, allow_archived: bool = ...
    ) -> list[Task]:
        """Find server tasks for exact retained execution reconciliation.

        Args:
            project_name: Selected ClearML project.
            task_name: Unique retained attempt name or exact-match query.
            allow_archived: Include archived execution history.

        Returns:
            Matching tasks, including archived history when requested.
        """
        ...
    def set_parameters(self, *args: Mapping[str, str]) -> None:
        """Store explicitly authored non-secret searchable parameters.

        Args:
            args: Resolved non-secret parameter mapping.
        """
        ...
    def set_input_model(
        self, *, model_id: str, name: str, update_task_design: bool, update_task_labels: bool
    ) -> None:
        """Link an existing published model without overriding retained definitions.

        Args:
            model_id: Existing server model identity.
            name: Explicit artifact, metric or model name.
            update_task_design: Whether to replace task design; disabled by this consumer.
            update_task_labels: Whether to replace labels; disabled by this consumer.
        """
        ...
    def get_logger(self) -> Logger:
        """Access explicit dashboard reporting for this task.

        Returns:
            Task logger.
        """
        ...
    def upload_artifact(
        self, *, name: str, artifact_object: str, auto_pickle: bool, wait_on_upload: bool
    ) -> bool:
        """Upload a specified file and wait for its acknowledgement.

        Args:
            name: Explicit artifact, metric or model name.
            artifact_object: Explicit local file path.
            auto_pickle: Whether pickling is permitted; disabled by this consumer.
            wait_on_upload: Wait for upload acknowledgement.

        Returns:
            Whether the upload succeeded.
        """
        ...
    def flush(self, wait_for_uploads: bool = ...) -> bool:
        """Wait for outstanding explicit uploads and metrics.

        Args:
            wait_for_uploads: Wait for all outstanding artifact transfers.

        Returns:
            Whether pending publication completed.
        """
        ...
    def mark_completed(self, *, ignore_errors: bool) -> object:
        """Mark the remote projection complete after retained local completion.

        Args:
            ignore_errors: Suppress server errors only when explicitly requested.

        Returns:
            SDK response; failure propagates when errors are enabled.
        """
        ...
    def mark_failed(self, *, ignore_errors: bool, status_reason: str) -> object:
        """Project retained failure, rejection or abandonment without resetting history.

        Args:
            ignore_errors: Suppress server errors only when explicitly requested.
            status_reason: Retained local terminal outcome.

        Returns:
            SDK response; failure propagates when errors are enabled.
        """
        ...

class Model:
    """Describe existing immutable-version model projections."""

    id: str
    @classmethod
    def query_models(
        cls, *, project_name: str, model_name: str, include_archived: bool
    ) -> list[Model]:
        """Find model versions by project and exact immutable manifest name.

        Args:
            project_name: Selected ClearML project.
            model_name: Exact immutable version manifest query.
            include_archived: Include archived model history.

        Returns:
            Matching server model handles.
        """
        ...
    def get_local_copy(self, *, raise_on_error: bool) -> str | None:
        """Download retained state for digest verification.

        Args:
            raise_on_error: Propagate state-download failures.

        Returns:
            State file path, or absence on failure.
        """
        ...

class OutputModel:
    """Describe explicit output model serialization and input provenance."""

    id: str
    def __init__(
        self,
        *,
        task: Task,
        name: str,
        framework: str | None = ...,
        config_text: str | None = ...,
        base_model_id: str | None = ...,
    ) -> None:
        """Bind an output model to its construction task and immutable manifest.

        Args:
            task: Construction task receiving the model.
            name: Explicit artifact, metric or model name.
            framework: Explicit custom model framework description.
            config_text: Immutable version manifest as JSON text.
            base_model_id: Existing model identity during reconciliation.
        """
        ...
    def update_weights(
        self, *, weights_filename: str, upload_uri: str, auto_delete_file: bool, async_enable: bool
    ) -> str:
        """Upload exact state bytes synchronously without deleting retained inputs.

        Args:
            weights_filename: Local exact state file.
            upload_uri: Non-secret artifact destination.
            auto_delete_file: Whether to delete the supplied state file; disabled by this consumer.
            async_enable: Whether to upload in the background; disabled by this consumer.

        Returns:
            Registered model state location.
        """
        ...
    def publish(self) -> None:
        """Publish a verified numerical model for later input-model linking."""
        ...
