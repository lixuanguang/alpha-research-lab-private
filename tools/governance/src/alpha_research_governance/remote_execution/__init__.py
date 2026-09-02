"""Canonical remote-execution policy, sharding, and runner API."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.remote_execution.models import (
    RemoteExecutionError,
    RemoteExecutionPolicy,
    TestShard,
)
from alpha_research_governance.remote_execution.policy import load_policy, validate_repository
from alpha_research_governance.remote_execution.runner import (
    run_quarantine_diagnostics,
    run_remote_build,
    run_remote_test_shard,
    validate_trusted_context,
)
from alpha_research_governance.remote_execution.sharding import select_shard, shard_targets

__all__ = [
    "RemoteExecutionError",
    "RemoteExecutionPolicy",
    "TestShard",
    "load_policy",
    "main",
    "run_quarantine_diagnostics",
    "run_remote_build",
    "run_remote_test_shard",
    "select_shard",
    "shard_targets",
    "validate_repository",
    "validate_trusted_context",
]


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate the policy or execute one explicitly requested governed lane."""
    parser = argparse.ArgumentParser(prog="alpha-governance-remote-execution")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("validate")
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--context", required=True)
    test_parser = subparsers.add_parser("test")
    test_parser.add_argument("--context", required=True)
    test_parser.add_argument("--shard-index", type=int, required=True)
    quarantine_parser = subparsers.add_parser("quarantine")
    quarantine_parser.add_argument("--context", required=True)
    parsed_arguments = parser.parse_args(list(sys.argv[1:] if arguments is None else arguments))
    try:
        policy = validate_repository(parsed_arguments.repository_root)
        if parsed_arguments.command in (None, "validate"):
            print(
                "Remote execution policy passed for two deterministic shards; "
                f"package status is {policy.package_status}."
            )
            return 0
        if parsed_arguments.command == "build":
            return run_remote_build(
                policy,
                context=parsed_arguments.context,
                repository_root=parsed_arguments.repository_root,
            )
        if parsed_arguments.command == "test":
            return run_remote_test_shard(
                policy,
                context=parsed_arguments.context,
                shard_index=parsed_arguments.shard_index,
                repository_root=parsed_arguments.repository_root,
            )
        return run_quarantine_diagnostics(
            policy,
            context=parsed_arguments.context,
            repository_root=parsed_arguments.repository_root,
        )
    except (OSError, RemoteExecutionError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
