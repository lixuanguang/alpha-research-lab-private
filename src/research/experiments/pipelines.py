"""Launch serial ClearML research steps against one explicit installed environment."""

from __future__ import annotations

# standard library imports
import hashlib
import sys
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

# third party library imports
from clearml import Task
from clearml.automation import PipelineController

# project library imports
from market_data.storage import DatasetVersion
from research.experiments.comparison import ComparisonStudy
from research.experiments.configuration import BacktestRun
from research.experiments.identity import ExperimentSpec, Fingerprint
from research.experiments.tracking import ClearMLDestination
from runtime import ImplementationIdentity, RuntimeFiles
from serialization import DomainCodec, WireRecord


class PipelineRun(WireRecord, frozen=True):
    """Describe one local serial workflow and its verified installed artifact boundary."""

    configuration: BacktestRun
    tracking: ClearMLDestination
    inputs_root: str
    attempts: str
    output_root: str
    max_bytes: int
    implementation_sha256: str
    environment_sha256: str
    artifact_sha256: str
    python: str
    command: str
    queue: str
    dataset_version: DatasetVersion | None = None
    lakefs_endpoint: str | None = None
    comparison: ComparisonStudy | None = None
    schema_version: str = "research-pipeline-v1"

    def __post_init__(self) -> None:
        """Refuse relative paths, missing identities and unsupported execution definitions."""
        self.configuration.__post_init__()
        self.tracking.__post_init__()
        if self.comparison is not None:
            self.comparison.__post_init__()
            if self.comparison.variants[0] != self.configuration:
                raise ValueError("pipeline comparison must include its configured run first")
        if (self.dataset_version is None) != (self.configuration.versioned_inputs_sha256 is None):
            raise ValueError("pipeline requires the configured immutable dataset version")
        if self.dataset_version is not None and (
            self.dataset_version.identity != self.configuration.versioned_inputs_sha256
            or self.lakefs_endpoint is None
        ):
            raise ValueError("pipeline dataset version or endpoint is absent/incompatible")
        for digest in (self.implementation_sha256, self.environment_sha256, self.artifact_sha256):
            Fingerprint(name="pipeline", sha256=digest)
        if (
            self.schema_version != "research-pipeline-v1"
            or type(self.max_bytes) is not int
            or self.max_bytes <= 0
            or not self.queue
        ):
            raise ValueError("invalid pipeline execution definition")
        for path in (self.inputs_root, self.attempts, self.output_root, self.python, self.command):
            if not Path(path).is_absolute():
                raise ValueError("pipeline paths must be explicit and absolute")
        if (
            Path(self.command).name != "alpha-backtest"
            or Path(self.command).parent != Path(self.python).parent
        ):
            raise ValueError(
                "pipeline must use the installed backtest command beside its interpreter"
            )

    @classmethod
    def capture(
        cls,
        configuration: BacktestRun,
        tracking: ClearMLDestination,
        *,
        inputs_root: Path,
        attempts: Path,
        output_root: Path,
        max_bytes: int,
        wheel: Path,
        queue: str,
        dataset_version: DatasetVersion | None = None,
        lakefs_endpoint: str | None = None,
        comparison: ComparisonStudy | None = None,
    ) -> PipelineRun:
        """Verify installed owned bytes against the selected wheel before dispatch.

        Args:
            configuration: Resolved configured study, editable explicitly in task parameters.
            tracking: Explicit local ClearML destination.
            inputs_root: Saved raw/snapshot root, without implicit acquisition.
            attempts: Single-writer retained history shared by serial steps.
            output_root: Parent for distinct per-pipeline launch records.
            max_bytes: Positive input byte ceiling.
            wheel: Exact installed runtime wheel, retained for reproduction.
            queue: Dedicated local queue served by one worker.
            dataset_version: Optional immutable storage manifest selected by configuration.
            lakefs_endpoint: Explicit API endpoint; worker credentials remain outside the plan.
            comparison: Optional frozen comparison grid whose first variant is configuration.

        Returns:
            Verified installed environment and artifact manifest.

        Raises:
            ValueError: Installed code differs from the retained wheel or command is absent.
        """
        with ZipFile(wheel) as archive:
            for name, path in RuntimeFiles.inputs():
                if archive.read(name) != path.read_bytes():
                    raise ValueError("installed runtime differs from selected pipeline wheel")
        command = Path(sys.executable).parent / "alpha-backtest"
        if not command.is_file():
            raise ValueError("installed backtest entrypoint is missing")
        return cls(
            configuration=configuration,
            tracking=tracking,
            inputs_root=str(inputs_root.resolve()),
            attempts=str(attempts.resolve()),
            output_root=str(output_root.resolve()),
            max_bytes=max_bytes,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=ExperimentSpec.installed_environment(),
            artifact_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
            python=sys.executable,
            command=str(command),
            queue=queue,
            dataset_version=dataset_version,
            lakefs_endpoint=lakefs_endpoint,
            comparison=comparison,
        )


class ResearchPipeline:
    """Compose verified selection/features then economics/reports with caching and retries off."""

    @staticmethod
    def run(plan: PipelineRun) -> str:
        """Launch ordered agent tasks and wait for their acknowledged outcome.

        Args:
            plan: Verified installed execution and declared inputs; one dedicated local worker.

        Returns:
            Completed controller task ID; step tasks retain actual attempts and upstream outputs.

        Raises:
            RuntimeError: A step failed or was aborted; dependent work cannot complete.
        """
        plan.__post_init__()
        codec = DomainCodec()
        launch = Path(plan.output_root) / uuid4().hex
        launch.mkdir(parents=True)
        (launch / "plan.json").write_bytes(codec.encode_json(plan))
        controller = Task.init(
            project_name=plan.tracking.project,
            task_name=f"research-pipeline-{launch.name}",
            task_type="controller",
            reuse_last_task_id=False,
            auto_connect_frameworks={
                key: False
                for key in (
                    "detect_repository",
                    "matplotlib",
                    "tensorflow",
                    "tensorboard",
                    "pytorch",
                    "xgboost",
                    "scikit",
                    "fastai",
                    "lightgbm",
                    "hydra",
                    "tfdefines",
                    "joblib",
                    "megengine",
                    "catboost",
                    "gradio",
                    "jax",
                    "keras",
                    "plotly",
                )
            },
            auto_connect_arg_parser=False,
            auto_connect_streams=False,
            auto_resource_monitoring=False,
        )
        controller.output_uri = plan.tracking.files_uri
        controller.upload_artifact(
            name="installed-plan",
            artifact_object=str(launch / "plan.json"),
            auto_pickle=False,
            wait_on_upload=True,
        )
        pipeline = PipelineController(
            name=f"research-pipeline-{launch.name}",
            project=plan.tracking.project,
            version="1.0.0",
            pool_frequency=0.05,
            abort_on_failure=True,
            retry_on_failure=0,
            packages=[],
            repo="",
            enable_local_imports=False,
            output_uri=plan.tracking.files_uri,
        )
        pipeline.set_default_execution_queue(plan.queue)
        previous: str | None = None
        stages: tuple[str, ...] = ("inputs", "complete")
        if plan.comparison is not None:
            stages = (*stages, "comparison")
        for stage in stages:
            task = Task.create(
                project_name=plan.tracking.project,
                task_name=f"{launch.name}-{stage}",
                task_type="data_processing",
                detect_repository=False,
                add_task_init_call=False,
                packages=[],
            )
            # The agent executes this minimal process handoff; all behavior remains
            # in the sole installed application entry, with environment checks there.
            task.set_script(
                repository="",
                working_dir=str(launch),
                entry_point="installed.py",
                binary=plan.python,
                diff=(
                    "import os\n"
                    f"os.execv({plan.python!r}, [{plan.python!r}, '-I', "
                    f"{plan.command!r}, 'worker'])\n"
                ),
            )
            parameters = {
                "Run/plan": codec.encode_json(plan).decode(),
                "Run/configuration": codec.encode_json(plan.configuration).decode(),
                "Run/stage": stage,
                "Run/controller": controller.id,
                "Run/output": str(launch),
                "Run/upstream": "",
            }
            if plan.comparison is not None:
                parameters["Run/comparison"] = codec.encode_json(plan.comparison).decode()
                parameters["Run/journal"] = str(Path(plan.output_root) / "comparison-journal.jsonl")
            task.set_parameters(parameters)
            pipeline.add_step(
                name=stage,
                base_task_id=task.id,
                clone_base_task=False,
                parents=[] if previous is None else [previous],
                parameter_override={}
                if previous is None
                else {"Run/upstream": "${inputs.parameters.retained/attempt_id}"},
                cache_executed_step=False,
                retry_on_failure=0,
                continue_on_fail=False,
            )
            previous = stage
        try:
            pipeline.start_locally(run_pipeline_steps_locally=False)
            if not pipeline.is_successful():
                raise RuntimeError(f"research pipeline failed; controller {controller.id}")
            return controller.id
        finally:
            controller.close()
