"""Canonical remote-execution policy, sharding, and runner API."""

from __future__ import annotations

# standard library imports
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, NamedTuple

# third party library imports
import typer

# project library imports
from alpha_research_governance._cli import run_typer
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


class _RemoteExecutionCLIState(NamedTuple):
    repository_root: Path
    policy: RemoteExecutionPolicy


_APP = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
    suggest_commands=False,
)


def _state(context: typer.Context) -> _RemoteExecutionCLIState:
    state = context.obj
    if not isinstance(state, _RemoteExecutionCLIState):
        raise RuntimeError("remote-execution CLI state is unavailable")
    return state


def _print_validation_result(policy: RemoteExecutionPolicy) -> None:
    print(
        "Remote execution policy passed for two deterministic shards; "
        f"package status is {policy.package_status}."
    )


@_APP.callback()
def _initialize_cli(
    context: typer.Context,
    repository_root: Annotated[
        Path | None,
        typer.Option("--repository-root", help="Repository root to validate."),
    ] = None,
) -> None:
    """Validate the policy or execute one explicitly requested governed lane."""
    root = Path.cwd() if repository_root is None else repository_root
    policy = validate_repository(root)
    context.obj = _RemoteExecutionCLIState(root, policy)
    if context.invoked_subcommand is None:
        _print_validation_result(policy)


@_APP.command("validate")
def _validate(context: typer.Context) -> None:
    """Validate the remote-execution policy without running a lane."""
    _print_validation_result(_state(context).policy)


@_APP.command("build")
def _build(
    context: typer.Context,
    execution_context: Annotated[
        str,
        typer.Option("--context", help="Trusted execution context."),
    ],
) -> int:
    """Run the governed remote build lane."""
    state = _state(context)
    return run_remote_build(
        state.policy,
        context=execution_context,
        repository_root=state.repository_root,
    )


@_APP.command("test")
def _test(
    context: typer.Context,
    execution_context: Annotated[
        str,
        typer.Option("--context", help="Trusted execution context."),
    ],
    shard_index: Annotated[int, typer.Option("--shard-index", help="Zero-based shard index.")],
) -> int:
    """Run one governed remote test shard."""
    state = _state(context)
    return run_remote_test_shard(
        state.policy,
        context=execution_context,
        shard_index=shard_index,
        repository_root=state.repository_root,
    )


@_APP.command("quarantine")
def _quarantine(
    context: typer.Context,
    execution_context: Annotated[
        str,
        typer.Option("--context", help="Trusted execution context."),
    ],
) -> int:
    """Run governed quarantine diagnostics."""
    state = _state(context)
    return run_quarantine_diagnostics(
        state.policy,
        context=execution_context,
        repository_root=state.repository_root,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate the policy or execute one explicitly requested governed lane."""
    return run_typer(
        _APP,
        arguments=arguments,
        handled_errors=(OSError, RemoteExecutionError, ValueError),
        program_name="alpha-governance-remote-execution",
    )
