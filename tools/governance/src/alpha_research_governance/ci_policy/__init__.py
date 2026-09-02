"""Canonical affected and full continuous-integration policy API and command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

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


def _build_command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpha-governance-ci")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command")

    select = commands.add_parser("select")
    select.add_argument("--base-ref", required=True)
    select.add_argument("--head-ref", required=True)

    scan = commands.add_parser("scan-secrets")
    scan.add_argument("--all", action="store_true")
    scan.add_argument("--base-ref")
    scan.add_argument("--head-ref")
    scan.add_argument("paths", nargs="*")

    schema = commands.add_parser("schema-check")
    schema.add_argument("--base-ref", default="HEAD")

    merged = commands.add_parser("verify-merged-result")
    merged.add_argument("--base-ref", required=True)
    merged.add_argument("--head-ref", required=True)
    merged.add_argument("--revision", default="HEAD")

    for lane_id in ("fast", "full"):
        lane = commands.add_parser(lane_id)
        lane.add_argument("--base-ref", required=True)
        if lane_id == "fast":
            lane.add_argument("--head-ref", required=True)
        lane.add_argument(
            "--event-log",
            type=Path,
            default=Path("build/ci/continuous-integration-events.jsonl"),
        )
        lane.add_argument("--run-id", default="local")
        lane.add_argument("--environment", default="local")
        lane.add_argument("--evidence-url", default="")
    return parser


def _serialize_affected_selection(selection: AffectedSelection) -> str:
    return json.dumps(selection.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate or execute the governed continuous-integration interfaces."""
    try:
        namespace = _build_command_parser().parse_args(
            list(sys.argv[1:] if arguments is None else arguments)
        )
        root = namespace.repository_root.resolve(strict=True)
        policy = validate_continuous_integration_repository(root)
        if namespace.command is None:
            print(
                f"CI policy passed for {len(policy.lanes)} lanes and "
                f"{len(policy.schema_module_roots)} schema module; package status is partial."
            )
        elif namespace.command == "select":
            print(
                _serialize_affected_selection(
                    select_affected_targets(
                        root,
                        base_ref=namespace.base_ref,
                        head_ref=namespace.head_ref,
                    )
                )
            )
        elif namespace.command == "scan-secrets":
            modes = sum(
                (
                    bool(namespace.all),
                    bool(namespace.base_ref or namespace.head_ref),
                    bool(namespace.paths),
                )
            )
            if modes != 1:
                raise CIPolicyError(["scan-secrets accepts paths, --all, or one complete ref pair"])
            if namespace.all:
                paths = _git_tracked_paths(root)
            elif namespace.base_ref and namespace.head_ref:
                _, _, changes = git_changed_paths_between(
                    root,
                    namespace.base_ref,
                    namespace.head_ref,
                )
                paths = tuple(item.path for item in changes)
            elif namespace.paths:
                paths = tuple(namespace.paths)
            else:
                raise CIPolicyError(["scan-secrets requires both --base-ref and --head-ref"])
            _scan_paths_for_secrets(root, paths)
            print(f"Secret scan passed for {len(paths)} governed paths.")
        elif namespace.command == "schema-check":
            base = resolve_git_commit(root, namespace.base_ref)
            _check_schema_compatibility(root, modules=policy.schema_module_roots, base=base)
            print(f"Schema compatibility passed for {len(policy.schema_module_roots)} modules.")
        elif namespace.command == "verify-merged-result":
            merged = verify_git_merge_parents(
                root,
                base_ref=namespace.base_ref,
                head_ref=namespace.head_ref,
                revision=namespace.revision,
            )
            print(f"Merged-result identity passed for {merged}.")
        elif namespace.command == "fast":
            selection = run_affected_ci_lane(
                root,
                base_ref=namespace.base_ref,
                head_ref=namespace.head_ref,
                event_log=namespace.event_log,
                run_id=namespace.run_id,
                evidence_url=namespace.evidence_url,
                environment=namespace.environment,
            )
            print(_serialize_affected_selection(selection))
        elif namespace.command == "full":
            run_authoritative_full_ci_lane(
                root,
                base_ref=namespace.base_ref,
                event_log=namespace.event_log,
                run_id=namespace.run_id,
                evidence_url=namespace.evidence_url,
                environment=namespace.environment,
            )
            print("Authoritative full CI lane passed.")
        else:
            raise CIPolicyError([f"unknown CI command: {namespace.command}"])
    except (CIPolicyError, OSError, UnicodeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0
