"""Execute affected and full CI lanes through pinned repository interfaces."""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404  # [owner=platform; rationale=required shell-free governed tool boundary; expires=2027-02-28]
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from alpha_research_governance.ci_policy.models import (
    AffectedSelection,
    ChangedPath,
    CIEvent,
    CIPolicyError,
)
from alpha_research_governance.ci_policy.policy import (
    validate_continuous_integration_repository,
)
from alpha_research_governance.ci_policy.secrets import scan_secret_paths
from alpha_research_governance.ci_policy.selection import (
    attach_bazel_reverse_dependencies,
    bazel_source_owners_from_query_xml,
    normalize_changed_paths,
    parse_git_name_status,
    select_bazel_owners_for_changes,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVENT_ID_TOKEN = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _run_command_and_capture_output(
    command: list[str], *, root: Path, environment: dict[str, str] | None = None
) -> bytes:
    try:
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=validated argv executes without a command shell; expires=2027-02-28]
            command,
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise CIPolicyError([f"command could not start ({command[0]}): {error}"]) from error
    if completed.returncode:
        output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
        raise CIPolicyError([f"command failed ({' '.join(command[:3])}): {output.strip()}"])
    return completed.stdout


def _run_command_with_visible_output(command: list[str], *, root: Path) -> None:
    try:
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=validated argv executes without a command shell; expires=2027-02-28]
            command, cwd=root, check=False
        )
    except OSError as error:
        raise CIPolicyError([f"command could not start ({command[0]}): {error}"]) from error
    if completed.returncode:
        raise CIPolicyError(
            [f"command failed with exit {completed.returncode}: {' '.join(command)}"]
        )


def resolve_git_commit(root: Path, revision: str) -> str:
    """Resolve an untrusted ref to an exact commit SHA."""
    if not revision or revision.startswith("-"):
        raise CIPolicyError(["revision must be a non-option Git ref"])
    payload = _run_command_and_capture_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        root=root,
    )
    resolved = payload.decode("ascii", errors="strict").strip()
    if _REVISION.fullmatch(resolved) is None:
        raise CIPolicyError([f"Git resolved an invalid commit identity for {revision}"])
    return resolved


def git_changed_paths_between(
    root: Path, base_ref: str, head_ref: str
) -> tuple[str, str, tuple[ChangedPath, ...]]:
    """Return exact refs and normalized paths changed between them."""
    policy = validate_continuous_integration_repository(root)
    base = resolve_git_commit(root, base_ref)
    head = resolve_git_commit(root, head_ref)
    payload = _run_command_and_capture_output(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base,
            head,
            "--",
        ],
        root=root,
    )
    return (
        base,
        head,
        parse_git_name_status(payload, maximum_changed_files=policy.maximum_changed_files),
    )


def _git_tracked_paths(root: Path) -> tuple[str, ...]:
    payload = _run_command_and_capture_output(["git", "ls-files", "-z"], root=root)
    return tuple(path for path in payload.decode("utf-8", errors="strict").split("\0") if path)


def _reject_generated_artifact_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
    generated = [path for path in paths if any(path.startswith(prefix) for prefix in prefixes)]
    if generated:
        raise CIPolicyError([f"generated artifacts cannot enter the source diff: {generated}"])


def _scan_paths_for_secrets(root: Path, paths: tuple[str, ...]) -> None:
    policy = validate_continuous_integration_repository(root)
    normalized = normalize_changed_paths(tuple(("M", path) for path in paths))
    existing = tuple(item.path for item in normalized if (root / item.path).is_file())
    scan_secret_paths(
        root,
        existing,
        maximum_file_bytes=policy.secret_scan_maximum_file_bytes,
    )
    if existing:
        environment = os.environ.copy()
        environment.update({"LC_ALL": "C.UTF-8", "TZ": "UTC"})
        _run_command_and_capture_output(
            [policy.secret_scanner_executable, "--", *existing],
            root=root,
            environment=environment,
        )


def verify_git_merge_parents(root: Path, *, base_ref: str, head_ref: str, revision: str) -> str:
    """Require a two-parent merge commit with the declared base and head parents."""
    base = resolve_git_commit(root, base_ref)
    head = resolve_git_commit(root, head_ref)
    merged = resolve_git_commit(root, revision)
    parents = _run_command_and_capture_output(
        ["git", "show", "-s", "--format=%P", merged], root=root
    )
    observed = tuple(parents.decode("ascii", errors="strict").strip().split())
    if observed != (base, head):
        raise CIPolicyError(
            [f"merged-result parents do not match declared base/head: observed={observed}"]
        )
    return merged


def _query_bazel_labels(root: Path, expression: str) -> tuple[str, ...]:
    payload = _run_command_and_capture_output(
        ["bazel", "query", expression, "--output=label"], root=root
    )
    return tuple(sorted({line for line in payload.decode("utf-8").splitlines() if line}))


def select_affected_targets(root: Path, *, base_ref: str, head_ref: str) -> AffectedSelection:
    """Select Bazel owners, reverse dependencies, and affected tests."""
    policy = validate_continuous_integration_repository(root)
    _, _, changes = git_changed_paths_between(root, base_ref, head_ref)
    xml = _run_command_and_capture_output(
        ["bazel", "query", "//...", "--output=xml"], root=root
    ).decode("utf-8")
    selection = select_bazel_owners_for_changes(
        changes, bazel_source_owners_from_query_xml(xml), policy
    )
    if selection.force_full or not selection.owner_targets:
        return selection
    target_set = " ".join(selection.owner_targets)
    reverse_dependencies = f"rdeps(//..., set({target_set}))"
    build_targets = _query_bazel_labels(root, f'kind(".* rule", {reverse_dependencies})')
    test_targets = _query_bazel_labels(root, f"tests({reverse_dependencies})")
    return attach_bazel_reverse_dependencies(
        selection,
        build_targets=build_targets,
        test_targets=test_targets,
    )


def _changed_schema_modules(paths: tuple[str, ...], modules: tuple[str, ...]) -> tuple[str, ...]:
    selected = {
        module
        for module in modules
        if any(path == module or path.startswith(f"{module}/") for path in paths)
    }
    return tuple(sorted(selected))


def _check_schema_compatibility(root: Path, *, modules: tuple[str, ...], base: str) -> None:
    for module in modules:
        _run_command_with_visible_output(
            [
                "bazel",
                "run",
                "--config=ci",
                "@rules_buf_toolchains//:buf",
                "--",
                "lint",
                module,
            ],
            root=root,
        )
        baseline = _run_command_and_capture_output(
            ["git", "ls-tree", "-z", base, "--", f"{module}/buf.yaml"],
            root=root,
        )
        if baseline:
            _run_command_with_visible_output(
                [
                    "bazel",
                    "run",
                    "--config=ci",
                    "@rules_buf_toolchains//:buf",
                    "--",
                    "breaking",
                    module,
                    "--against",
                    f".git#ref={base},subdir={module}",
                ],
                root=root,
            )


def _git_worktree_state(root: Path) -> bytes:
    return _run_command_and_capture_output(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        root=root,
    )


def _run_pre_commit_without_mutation(root: Path, arguments: list[str]) -> None:
    before = _git_worktree_state(root)
    _run_command_with_visible_output(["pre-commit", "run", *arguments], root=root)
    if _git_worktree_state(root) != before:
        raise CIPolicyError(
            ["pre-commit changed the worktree; commit the formatted result and rerun"]
        )


def _require_clean_hosted_checkout(root: Path, *, environment: str) -> None:
    if environment != "local" and _git_worktree_state(root):
        raise CIPolicyError(["hosted CI requires a clean checkout for revision-bound events"])


def _validate_ci_event_context(
    *,
    run_id: str,
    revision: str,
    evidence_url: str,
    environment: str,
    target: str,
) -> None:
    for field_name, value in (("environment", environment), ("target", target)):
        if _TOKEN.fullmatch(value) is None:
            raise CIPolicyError([f"{field_name} is not a safe CI event token"])
    if _EVENT_ID_TOKEN.fullmatch(run_id) is None:
        raise CIPolicyError(["run_id is not a safe program-observation event identifier"])
    if _REVISION.fullmatch(revision) is None:
        raise CIPolicyError(["revision is not a full lowercase commit digest"])
    if evidence_url:
        try:
            parsed_url = urlsplit(evidence_url)
        except ValueError as error:
            raise CIPolicyError(
                ["evidence_url must be a valid credential-free HTTPS URL"]
            ) from error
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise CIPolicyError(["evidence_url must be a credential-free HTTPS URL"])
    elif environment != "local":
        raise CIPolicyError(["non-local CI events require a retained HTTPS evidence URL"])


def _build_ci_duration_event(
    *,
    phase: str,
    run_id: str,
    revision: str,
    evidence_url: str,
    environment: str,
    outcome: str,
    target: str,
    started_at: datetime,
    ended_at: datetime,
) -> CIEvent:
    if phase not in {"build", "test"} or outcome not in {"failed", "passed"}:
        raise CIPolicyError(["CI event phase or outcome is invalid"])
    _validate_ci_event_context(
        run_id=run_id,
        revision=revision,
        evidence_url=evidence_url,
        environment=environment,
        target=target,
    )
    if started_at.tzinfo != UTC or ended_at.tzinfo != UTC or ended_at <= started_at:
        raise CIPolicyError(["CI event window must be positive and expressed in UTC"])
    event_type = f"ci_{phase}_completed"
    return CIEvent(
        schema_version=1,
        event_id=f"continuous-integration.{run_id}.{phase}",
        metric_id=f"kpi.{phase}_duration_seconds",
        source_event_type=event_type,
        source_run_id=run_id,
        source_revision=revision,
        evidence_url=evidence_url,
        window_start=started_at,
        window_end=ended_at,
        dimensions={"environment": environment, "outcome": outcome, "target": target},
    )


def _serialize_ci_event(event: CIEvent) -> str:
    payload = event.model_dump(mode="json")
    payload["window_start"] = event.window_start.isoformat().replace("+00:00", "Z")
    payload["window_end"] = event.window_end.isoformat().replace("+00:00", "Z")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _run_timed_ci_phase(
    commands: tuple[list[str], ...],
    *,
    root: Path,
    phase: str,
    event_stream: IO[str],
    run_id: str,
    revision: str,
    evidence_url: str,
    environment: str,
    target: str,
) -> None:
    started_at = datetime.now(UTC)
    outcome = "passed"
    try:
        for command in commands:
            _run_command_with_visible_output(command, root=root)
    except CIPolicyError:
        outcome = "failed"
        raise
    finally:
        ended_at = max(datetime.now(UTC), started_at + timedelta(microseconds=1))
        event_stream.write(
            _serialize_ci_event(
                _build_ci_duration_event(
                    phase=phase,
                    run_id=run_id,
                    revision=revision,
                    evidence_url=evidence_url,
                    environment=environment,
                    outcome=outcome,
                    target=target,
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )
            + "\n"
        )
        event_stream.flush()


def _open_ci_event_log(root: Path, path: Path, *, event_log_directory: str = "build/ci") -> IO[str]:
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    allowed_root = (root / event_log_directory).resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise CIPolicyError(["CI event log must remain under build/ci"])
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved.open("w", encoding="utf-8")


def run_affected_ci_lane(
    root: Path,
    *,
    base_ref: str,
    head_ref: str,
    event_log: Path,
    run_id: str,
    evidence_url: str,
    environment: str,
) -> AffectedSelection:
    """Run preflight and the Bazel-affected build/test set."""
    policy = validate_continuous_integration_repository(root)
    with _open_ci_event_log(
        root, event_log, event_log_directory=policy.event_log_directory
    ) as events:
        base, head, changes = git_changed_paths_between(root, base_ref, head_ref)
        if resolve_git_commit(root, "HEAD") != head:
            raise CIPolicyError(["fast lane head ref must be the checked-out revision"])
        _validate_ci_event_context(
            run_id=run_id,
            revision=head,
            evidence_url=evidence_url,
            environment=environment,
            target="fast",
        )
        _require_clean_hosted_checkout(root, environment=environment)
        paths = tuple(sorted({item.path for item in changes}))
        _reject_generated_artifact_paths(paths, prefixes=policy.generated_artifact_prefixes)
        _scan_paths_for_secrets(root, paths)
        _check_schema_compatibility(
            root,
            modules=_changed_schema_modules(paths, policy.schema_module_roots),
            base=base,
        )
        if paths:
            _run_pre_commit_without_mutation(root, ["--from-ref", base, "--to-ref", head])
        selection = select_affected_targets(root, base_ref=base, head_ref=head)
        if selection.build_targets:
            _run_timed_ci_phase(
                (["bazel", "build", "--config=ci", *selection.build_targets],),
                root=root,
                phase="build",
                event_stream=events,
                run_id=run_id,
                revision=head,
                evidence_url=evidence_url,
                environment=environment,
                target="fast",
            )
        if selection.test_targets:
            _run_timed_ci_phase(
                (["bazel", "test", "--config=ci", *selection.test_targets],),
                root=root,
                phase="test",
                event_stream=events,
                run_id=run_id,
                revision=head,
                evidence_url=evidence_url,
                environment=environment,
                target="fast",
            )
    return selection


def run_authoritative_full_ci_lane(
    root: Path,
    *,
    base_ref: str,
    event_log: Path,
    run_id: str,
    evidence_url: str,
    environment: str,
) -> None:
    """Run the authoritative complete graph and frozen-uv compatibility path."""
    policy = validate_continuous_integration_repository(root)
    with _open_ci_event_log(
        root, event_log, event_log_directory=policy.event_log_directory
    ) as events:
        base = resolve_git_commit(root, base_ref)
        revision = resolve_git_commit(root, "HEAD")
        _validate_ci_event_context(
            run_id=run_id,
            revision=revision,
            evidence_url=evidence_url,
            environment=environment,
            target="full",
        )
        _require_clean_hosted_checkout(root, environment=environment)
        paths = _git_tracked_paths(root)
        _reject_generated_artifact_paths(paths, prefixes=policy.generated_artifact_prefixes)
        _scan_paths_for_secrets(root, paths)
        _check_schema_compatibility(root, modules=policy.schema_module_roots, base=base)
        _run_pre_commit_without_mutation(root, ["--all-files"])
        _run_timed_ci_phase(
            (["bazel", "build", "--config=ci", "//..."],),
            root=root,
            phase="build",
            event_stream=events,
            run_id=run_id,
            revision=revision,
            evidence_url=evidence_url,
            environment=environment,
            target="full",
        )
        _run_timed_ci_phase(
            (
                ["bazel", "test", "--config=ci", "//..."],
                ["make", "--no-print-directory", "rollback-check"],
            ),
            root=root,
            phase="test",
            event_stream=events,
            run_id=run_id,
            revision=revision,
            evidence_url=evidence_url,
            environment=environment,
            target="full",
        )
