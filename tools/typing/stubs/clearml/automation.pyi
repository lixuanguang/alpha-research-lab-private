"""Describe serial ClearML 2.1.12 pipeline composition."""

class PipelineController:
    """Describe the selected local controller and queued agent steps."""
    def __init__(
        self,
        *,
        name: str,
        project: str,
        version: str,
        pool_frequency: float,
        abort_on_failure: bool,
        retry_on_failure: int,
        packages: list[str],
        repo: str,
        enable_local_imports: bool,
        output_uri: str,
    ) -> None:
        """Create an explicit pipeline using the current controller task.

        Args:
            name: Unique pipeline name.
            project: Selected project.
            version: Owned pipeline schema version.
            pool_frequency: Status poll interval in minutes.
            abort_on_failure: Stop dependent work on failure.
            retry_on_failure: Zero; retain original failures.
            packages: Empty; use the pinned installed artifact.
            repo: Empty; no repository discovery.
            enable_local_imports: False; use installed imports only.
            output_uri: Explicit artifact service.
        """
        ...
    def set_default_execution_queue(self, default_execution_queue: str) -> None:
        """Select the dedicated serial local worker.

        Args:
            default_execution_queue: Explicit local queue name.
        """
        ...
    def add_step(
        self,
        *,
        name: str,
        base_task_id: str,
        clone_base_task: bool,
        parents: list[str],
        parameter_override: dict[str, str],
        cache_executed_step: bool,
        retry_on_failure: int,
        continue_on_fail: bool,
    ) -> bool:
        """Connect one fresh task to exact preceding output references.

        Args:
            name: Unique stage name.
            base_task_id: Fresh installed-command task.
            clone_base_task: False; task already belongs to this execution.
            parents: Required successful predecessor stages.
            parameter_override: Explicit upstream attempt reference.
            cache_executed_step: False; preserve execution and holdout records.
            retry_on_failure: Zero; retries use fresh executions.
            continue_on_fail: False; dependent work cannot claim success.

        Returns:
            Whether the step was added.
        """
        ...
    def start_locally(self, run_pipeline_steps_locally: bool = ...) -> None:
        """Run the controller locally while an actual agent executes queued steps.

        Args:
            run_pipeline_steps_locally: False; use the selected agent queue.
        """
        ...
    def is_successful(self) -> bool:
        """Check all required step outcomes.

        Returns:
            Whether the complete pipeline succeeded.
        """
        ...
