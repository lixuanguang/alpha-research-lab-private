"""Expose configured execution, checkpointing and publication through one installed command."""

from __future__ import annotations

# standard library imports
import argparse
import sys
from datetime import datetime
from pathlib import Path

# third party library imports
from lakefs_sdk import ApiClient

# project library imports
from applications.backtest.comparison import compare_parameters
from applications.backtest.configured import _StorageAccess, run_configured, run_worker
from market_data.storage import DatasetVersion, LakeFSStorage
from research.experiments import (
    AttemptStore,
    BacktestRun,
    ClearMLDestination,
    ClearMLPublication,
    ComparisonStudy,
    PipelineRun,
    ResearchPipeline,
    ResultManifest,
)
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Describe parsed command selections without an untyped argument boundary."""

    action: str
    config: Path
    snapshots: Path
    raw: Path
    attempts: Path
    max_bytes: int
    tracking: Path
    resume: Path | None
    stop_at: str | None
    attempt_id: str
    output: Path
    wheel: Path
    queue: str
    inputs: Path
    upstream: str | None
    dataset_version: Path | None
    lakefs_endpoint: str | None
    lakefs_credentials: Path | None
    journal: Path
    max_trials: int | None
    comparison_config: Path | None


def main(argv: list[str] | None = None) -> int:
    """Run configured economics or reopen retained outputs and publication intents.

    Args:
        argv: Explicit arguments or the process argument list.

    Returns:
        Zero for acknowledged success, two for invalid inputs, four for failed I/O/execution,
        or 130 for interruption. The retained attempt remains authoritative.

    Raises:
        SystemExit: Argument parsing handles help and malformed command syntax.
    """
    parser = argparse.ArgumentParser(prog="alpha-backtest", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    comparison = commands.add_parser("compare")
    for option in ("config", "snapshots", "raw", "attempts", "tracking", "journal"):
        comparison.add_argument(f"--{option}", type=Path, required=True)
    comparison.add_argument("--max-bytes", type=int, required=True)
    comparison.add_argument("--max-trials", type=int)
    for action in ("run", "prepare"):
        run = commands.add_parser(action)
        for option in ("config", "snapshots", "raw", "attempts", "tracking"):
            run.add_argument(f"--{option}", type=Path, required=True)
        run.add_argument("--max-bytes", type=int, required=True)
        run.add_argument("--resume", type=Path)
        run.add_argument("--stop-at")
        run.add_argument("--upstream")
        run.add_argument("--dataset-version", type=Path)
        run.add_argument("--lakefs-endpoint")
        run.add_argument("--lakefs-credentials", type=Path)
    pipeline = commands.add_parser("pipeline")
    for option in ("config", "tracking", "inputs", "attempts", "output", "wheel"):
        pipeline.add_argument(f"--{option}", type=Path, required=True)
    pipeline.add_argument("--max-bytes", type=int, required=True)
    pipeline.add_argument("--queue", required=True)
    pipeline.add_argument("--dataset-version", type=Path)
    pipeline.add_argument("--lakefs-endpoint")
    pipeline.add_argument("--comparison-config", type=Path)
    commands.add_parser("worker")
    for action in ("export", "checkpoint", "publish"):
        command = commands.add_parser(action)
        command.add_argument("--attempts", type=Path, required=True)
        command.add_argument("--attempt-id", required=True)
        command.add_argument(
            "--tracking" if action == "publish" else "--output", type=Path, required=True
        )
    args = parser.parse_args(argv, namespace=_Arguments())
    codec = DomainCodec()
    client: ApiClient | None = None
    try:
        if args.action == "compare":
            result = compare_parameters(
                args.config,
                args.snapshots,
                args.raw,
                attempts=args.attempts,
                journal=args.journal,
                max_bytes=args.max_bytes,
                tracking=codec.decode_json(args.tracking.read_bytes(), ClearMLDestination),
                max_trials=args.max_trials,
            )
            print(codec.encode_json(result).decode())
        elif args.action == "worker":
            run_worker()
        elif args.action == "pipeline":
            plan = PipelineRun.capture(
                BacktestRun.read(args.config),
                codec.decode_json(args.tracking.read_bytes(), ClearMLDestination),
                inputs_root=args.inputs,
                attempts=args.attempts,
                output_root=args.output,
                max_bytes=args.max_bytes,
                wheel=args.wheel,
                queue=args.queue,
                dataset_version=None
                if args.dataset_version is None
                else codec.decode_json(args.dataset_version.read_bytes(), DatasetVersion),
                lakefs_endpoint=args.lakefs_endpoint,
                comparison=None
                if args.comparison_config is None
                else ComparisonStudy.read(args.comparison_config),
            )
            print(ResearchPipeline.run(plan))
        elif args.action in ("run", "prepare"):
            version = None
            if args.dataset_version is not None:
                if args.lakefs_endpoint is None or args.lakefs_credentials is None:
                    raise ValueError("versioned inputs require an endpoint and private credentials")
                version = codec.decode_json(args.dataset_version.read_bytes(), DatasetVersion)
                client = _StorageAccess.open(args.lakefs_endpoint, args.lakefs_credentials)
            elif args.lakefs_endpoint is not None or args.lakefs_credentials is not None:
                raise ValueError("lakeFS options require a pinned dataset version")
            history = run_configured(
                args.config,
                args.snapshots,
                args.raw,
                attempts=args.attempts,
                max_bytes=args.max_bytes,
                tracking=codec.decode_json(args.tracking.read_bytes(), ClearMLDestination),
                resume=args.resume,
                stop_at=None if args.stop_at is None else datetime.fromisoformat(args.stop_at),
                stage="inputs" if args.action == "prepare" else "complete",
                upstream=args.upstream,
                version=version,
                storage=None if client is None else LakeFSStorage(client),
            )
            print(
                codec.encode_json(
                    {
                        "attempt_id": history.start.attempt_id,
                        "run_identity": history.start.run_identity,
                        "status": history.status,
                    }
                ).decode()
            )
        elif args.action == "publish":
            with AttemptStore(args.attempts) as store:
                destination = codec.decode_json(args.tracking.read_bytes(), ClearMLDestination)
                print(
                    codec.encode_json(
                        ClearMLPublication(store, destination).publish(args.attempt_id)
                    ).decode()
                )
        else:
            store = AttemptStore(args.attempts)
            if args.action == "export":
                ResultManifest.read(store, args.attempt_id)
            payload = store.artifact(
                args.attempt_id, "report-html" if args.action == "export" else "checkpoint"
            )
            ResultManifest.export(args.output, payload)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 4
    finally:
        if client is not None:
            client.close()
