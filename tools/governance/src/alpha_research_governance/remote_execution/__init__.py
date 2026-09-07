"""Expose the canonical remote-execution policy, sharding, and runner API."""

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
from alpha_research_governance.remote_execution.policy import (
    load_policy,
    validate_repository,
)
from alpha_research_governance.remote_execution.runner import (
    run_quarantine_diagnostics,
    run_remote_build,
    run_remote_test_shard,
    validate_trusted_context,
)
from alpha_research_governance.remote_execution.sharding import (
    select_shard,
    shard_targets,
)

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
    """Store the repository root and validated policy for one remote CLI invocation.

    Attributes:
        repository_root: Repository directory used by the selected command.
        policy: Validated remote-execution policy for that repository.
    """

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
    """Retrieve validated remote-execution state from a Typer context.

    Args:
        context: Typer invocation context carrying the initialized state.

    Returns:
        The repository root and validated remote-execution policy stored by the
        initialization callback.

    Raises:
        RuntimeError: The context does not contain the expected remote state.
    """
    state = context.obj
    if not isinstance(state, _RemoteExecutionCLIState):
        raise RuntimeError("remote-execution CLI state is unavailable")
    return state


def _print_validation_result(policy: RemoteExecutionPolicy) -> None:
    """Print the successful remote-execution policy summary to standard output.

    Args:
        policy: Validated policy whose package status is displayed.
    """
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
    """Validate or execute one governed remote-execution lane from Typer.

    With no command, validate the repository policy and print its summary. Selected
    build, test, and quarantine commands can invoke Git and Bazel and create then
    remove a temporary credential Bazel rc file while running a lane.

    Args:
        arguments: Explicit CLI arguments, or ``None`` to read ``sys.argv[1:]``.

    Returns:
        The translated Typer status, including a lane's integer status, ``0`` for
        successful ``None`` results, ``1`` for handled policy or operational
        errors, or a parser error's exit code.

    Raises:
        TypeError: A dispatched command returns a result other than ``None`` or an integer.
        Exception: An unexpected exception is not renderable as a Typer parser
            error and therefore escapes the adapter.
    """
    return run_typer(
        _APP,
        arguments=arguments,
        handled_errors=(OSError, RemoteExecutionError, ValueError),
        program_name="alpha-governance-remote-execution",
    )
