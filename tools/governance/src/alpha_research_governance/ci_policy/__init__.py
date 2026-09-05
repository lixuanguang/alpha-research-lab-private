"""Canonical affected and full continuous-integration policy API and command."""

from __future__ import annotations

# standard library imports
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, NamedTuple

# third party library imports
import typer

# project library imports
from alpha_research_governance._cli import run_typer
from alpha_research_governance.ci_policy.models import (
    AffectedSelection,
    ChangedPath,
    CIEvent,
    CILane,
    CIPolicy,
    CIPolicyError,
)
from alpha_research_governance.ci_policy.policy import (
    load_continuous_integration_policy,
    validate_continuous_integration_repository,
)
from alpha_research_governance.ci_policy.runner import (
    _check_schema_compatibility,
    _git_tracked_paths,
    _scan_paths_for_secrets,
    git_changed_paths_between,
    resolve_git_commit,
    run_affected_ci_lane,
    run_authoritative_full_ci_lane,
    select_affected_targets,
    verify_git_merge_parents,
)
from alpha_research_governance.ci_policy.secrets import scan_secret_bytes, scan_secret_paths
from alpha_research_governance.ci_policy.selection import (
    attach_bazel_reverse_dependencies,
    bazel_source_owners_from_query_xml,
    normalize_changed_paths,
    parse_git_name_status,
    select_bazel_owners_for_changes,
)

__all__ = [
    "AffectedSelection",
    "CIEvent",
    "CILane",
    "CIPolicy",
    "CIPolicyError",
    "ChangedPath",
    "attach_bazel_reverse_dependencies",
    "bazel_source_owners_from_query_xml",
    "git_changed_paths_between",
    "load_continuous_integration_policy",
    "main",
    "normalize_changed_paths",
    "parse_git_name_status",
    "resolve_git_commit",
    "run_affected_ci_lane",
    "run_authoritative_full_ci_lane",
    "scan_secret_bytes",
    "scan_secret_paths",
    "select_affected_targets",
    "select_bazel_owners_for_changes",
    "validate_continuous_integration_repository",
    "verify_git_merge_parents",
]


def _serialize_affected_selection(selection: AffectedSelection) -> str:
    return json.dumps(selection.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class _CICLIState(NamedTuple):
    repository_root: Path
    policy: CIPolicy


_DEFAULT_EVENT_LOG = Path("build/ci/continuous-integration-events.jsonl")
_APP = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
    suggest_commands=False,
)


def _state(context: typer.Context) -> _CICLIState:
    state = context.obj
    if not isinstance(state, _CICLIState):
        raise RuntimeError("continuous-integration CLI state is unavailable")
    return state


def _print_validation_result(policy: CIPolicy) -> None:
    print(
        f"CI policy passed for {len(policy.lanes)} lanes and "
        f"{len(policy.schema_module_roots)} schema module; package status is partial."
    )


@_APP.callback()
def _initialize_cli(
    context: typer.Context,
    repository_root: Annotated[
        Path | None,
        typer.Option("--repository-root", help="Repository root to validate."),
    ] = None,
) -> None:
    """Validate or execute the governed continuous-integration interfaces."""
    root = (Path.cwd() if repository_root is None else repository_root).resolve(strict=True)
    policy = validate_continuous_integration_repository(root)
    context.obj = _CICLIState(root, policy)
    if context.invoked_subcommand is None:
        _print_validation_result(policy)


@_APP.command("select")
def _select(
    context: typer.Context,
    base_ref: Annotated[str, typer.Option("--base-ref", help="Base Git reference.")],
    head_ref: Annotated[str, typer.Option("--head-ref", help="Head Git reference.")],
) -> None:
    """Select the targets affected between two Git references."""
    root = _state(context).repository_root
    print(
        _serialize_affected_selection(
            select_affected_targets(root, base_ref=base_ref, head_ref=head_ref)
        )
    )


@_APP.command("scan-secrets")
def _scan_secrets(
    context: typer.Context,
    paths: Annotated[list[str] | None, typer.Argument(help="Repository-relative paths.")] = None,
    scan_all: Annotated[
        bool,
        typer.Option("--all", help="Scan every tracked path."),
    ] = False,
    base_ref: Annotated[str | None, typer.Option("--base-ref", help="Base Git reference.")] = None,
    head_ref: Annotated[str | None, typer.Option("--head-ref", help="Head Git reference.")] = None,
) -> None:
    """Scan paths, all tracked files, or a complete Git reference pair."""
    root = _state(context).repository_root
    modes = sum((scan_all, bool(base_ref or head_ref), bool(paths)))
    if modes != 1:
        raise CIPolicyError(["scan-secrets accepts paths, --all, or one complete ref pair"])
    if scan_all:
        selected_paths = _git_tracked_paths(root)
    elif base_ref and head_ref:
        _, _, changes = git_changed_paths_between(root, base_ref, head_ref)
        selected_paths = tuple(item.path for item in changes)
    elif paths:
        selected_paths = tuple(paths)
    else:
        raise CIPolicyError(["scan-secrets requires both --base-ref and --head-ref"])
    _scan_paths_for_secrets(root, selected_paths)
    print(f"Secret scan passed for {len(selected_paths)} governed paths.")


@_APP.command("schema-check")
def _schema_check(
    context: typer.Context,
    base_ref: Annotated[str, typer.Option("--base-ref", help="Base Git reference.")] = "HEAD",
) -> None:
    """Check governed schema compatibility against a Git reference."""
    state = _state(context)
    base = resolve_git_commit(state.repository_root, base_ref)
    _check_schema_compatibility(
        state.repository_root,
        modules=state.policy.schema_module_roots,
        base=base,
    )
    print(f"Schema compatibility passed for {len(state.policy.schema_module_roots)} modules.")


@_APP.command("verify-merged-result")
def _verify_merged_result(
    context: typer.Context,
    base_ref: Annotated[str, typer.Option("--base-ref", help="Base Git reference.")],
    head_ref: Annotated[str, typer.Option("--head-ref", help="Head Git reference.")],
    revision: Annotated[
        str,
        typer.Option("--revision", help="Merged revision to verify."),
    ] = "HEAD",
) -> None:
    """Verify the exact base and head parents of a merged result."""
    root = _state(context).repository_root
    merged = verify_git_merge_parents(
        root,
        base_ref=base_ref,
        head_ref=head_ref,
        revision=revision,
    )
    print(f"Merged-result identity passed for {merged}.")


@_APP.command("fast")
def _fast(
    context: typer.Context,
    base_ref: Annotated[str, typer.Option("--base-ref", help="Base Git reference.")],
    head_ref: Annotated[str, typer.Option("--head-ref", help="Head Git reference.")],
    event_log: Annotated[
        Path,
        typer.Option("--event-log", help="Repository-local CI event log."),
    ] = _DEFAULT_EVENT_LOG,
    run_id: Annotated[str, typer.Option("--run-id", help="CI run identifier.")] = "local",
    environment: Annotated[
        str,
        typer.Option("--environment", help="Execution environment."),
    ] = "local",
    evidence_url: Annotated[
        str,
        typer.Option("--evidence-url", help="Retained CI evidence URL."),
    ] = "",
) -> None:
    """Run the affected-target CI lane."""
    root = _state(context).repository_root
    selection = run_affected_ci_lane(
        root,
        base_ref=base_ref,
        head_ref=head_ref,
        event_log=event_log,
        run_id=run_id,
        evidence_url=evidence_url,
        environment=environment,
    )
    print(_serialize_affected_selection(selection))


@_APP.command("full")
def _full(
    context: typer.Context,
    base_ref: Annotated[str, typer.Option("--base-ref", help="Base Git reference.")],
    event_log: Annotated[
        Path,
        typer.Option("--event-log", help="Repository-local CI event log."),
    ] = _DEFAULT_EVENT_LOG,
    run_id: Annotated[str, typer.Option("--run-id", help="CI run identifier.")] = "local",
    environment: Annotated[
        str,
        typer.Option("--environment", help="Execution environment."),
    ] = "local",
    evidence_url: Annotated[
        str,
        typer.Option("--evidence-url", help="Retained CI evidence URL."),
    ] = "",
) -> None:
    """Run the authoritative full CI lane."""
    root = _state(context).repository_root
    run_authoritative_full_ci_lane(
        root,
        base_ref=base_ref,
        event_log=event_log,
        run_id=run_id,
        evidence_url=evidence_url,
        environment=environment,
    )
    print("Authoritative full CI lane passed.")


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate or execute the governed continuous-integration interfaces."""
    return run_typer(
        _APP,
        arguments=arguments,
        handled_errors=(CIPolicyError, OSError, UnicodeError, ValueError),
        program_name="alpha-governance-ci",
    )
