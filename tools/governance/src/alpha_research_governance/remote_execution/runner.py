"""Trusted remote runner and explicitly remote-disabled local fallback."""

from __future__ import annotations

# standard library imports
import os
import re
import shutil
import subprocess  # nosec B404  # [owner=platform; rationale=required shell-free Bazel and Git boundary; expires=2027-02-28]
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.remote_execution.models import (
    RemoteExecutionError,
    RemoteExecutionPolicy,
)
from alpha_research_governance.remote_execution.sharding import select_shard

_CREDENTIAL = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")


def validate_trusted_context(
    policy: RemoteExecutionPolicy,
    context: str,
    environment: Mapping[str, str],
    repository_root: Path,
) -> None:
    """Reject remote credentials outside the exact clean main-push boundary."""
    findings: list[str] = []
    if context not in policy.trust.trusted_contexts:
        findings.append(f"remote execution is not permitted in context {context!r}")
    expected = {
        "CI": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
    }
    for key, value in expected.items():
        if environment.get(key) != value:
            findings.append(f"{key} must equal {value!r} for trusted remote execution")
    credential = environment.get(policy.provider.credential_environment_variable, "")
    if _CREDENTIAL.fullmatch(credential) is None:
        findings.append("the remote credential must use the safe API-key character set")

    head = _run_git_command(repository_root, "rev-parse", "HEAD")
    if environment.get("GITHUB_SHA") != head:
        findings.append("GITHUB_SHA must identify the checked-out HEAD")
    if _run_git_command(repository_root, "status", "--porcelain"):
        findings.append("trusted remote execution requires a clean checkout")
    if findings:
        raise RemoteExecutionError(findings)


def query_test_targets(repository_root: Path) -> tuple[str, ...]:
    """Query the complete Bazel test graph with no remote credentials."""
    completed = _run_process(
        (_resolve_executable("bazel"), "query", "tests(//...)", "--output=label"),
        repository_root=repository_root,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RemoteExecutionError([f"Bazel test query failed: {completed.stderr.strip()}"])
    targets = tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())
    if not targets:
        raise RemoteExecutionError(["Bazel test query returned no targets"])
    return targets


def run_remote_build(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Build the governed graph remotely after trust and secret checks."""
    active_environment = dict(os.environ if environment is None else environment)
    validate_trusted_context(policy, context, active_environment, repository_root)
    return _run_authenticated_bazel(
        policy,
        repository_root=repository_root,
        environment=active_environment,
        command="build",
        targets=policy.local_fallback.build_targets,
    )


def run_remote_test_shard(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    shard_index: int,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run exactly one deterministic shard with no whole-test retries."""
    active_environment = dict(os.environ if environment is None else environment)
    validate_trusted_context(policy, context, active_environment, repository_root)
    shard = select_shard(
        query_test_targets(repository_root),
        shard_index=shard_index,
        shard_count=policy.sharding.shard_count,
        seed=policy.sharding.seed,
        maximum_targets=policy.sharding.maximum_targets,
    )
    if not shard.targets:
        return 0
    return _run_authenticated_bazel(
        policy,
        repository_root=repository_root,
        environment=active_environment,
        command="test",
        targets=shard.targets,
    )


def run_quarantine_diagnostics(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Repeat quarantined tests diagnostically; never remove them from normal shards."""
    targets = tuple(entry.target for entry in policy.flakes.quarantines)
    if not targets:
        return 0
    active_environment = dict(os.environ if environment is None else environment)
    validate_trusted_context(policy, context, active_environment, repository_root)
    return _run_authenticated_bazel(
        policy,
        repository_root=repository_root,
        environment=active_environment,
        command="test",
        targets=targets,
        extra_arguments=("--config=remote-quarantine-diagnostics",),
    )


def _run_authenticated_bazel(
    policy: RemoteExecutionPolicy,
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    command: str,
    targets: Sequence[str],
    extra_arguments: Sequence[str] = (),
) -> int:
    credential_name = policy.provider.credential_environment_variable
    credential = environment[credential_name]
    child_environment = dict(environment)
    child_environment.pop(credential_name, None)
    with tempfile.TemporaryDirectory(prefix="alpha-remote-execution-") as temporary_directory:
        credential_rc = Path(temporary_directory) / "credential.bazelrc"
        credential_rc.write_text(
            f"build --remote_header={policy.provider.authentication_header}={credential}\n",
            encoding="utf-8",
        )
        credential_rc.chmod(0o600)
        completed = _run_process(
            (
                _resolve_executable("bazel"),
                f"--bazelrc={credential_rc}",
                command,
                "--config=remote-execution",
                *extra_arguments,
                "--",
                *targets,
            ),
            repository_root=repository_root,
            environment=child_environment,
        )
    return completed.returncode


def _run_git_command(repository_root: Path, *arguments: str) -> str:
    completed = _run_process(
        (_resolve_executable("git"), *arguments),
        repository_root=repository_root,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RemoteExecutionError([f"git {' '.join(arguments)} failed"])
    return completed.stdout.strip()


def _resolve_executable(name: str) -> str:
    if name not in {"bazel", "git"}:
        raise RemoteExecutionError([f"unsupported executable {name!r}"])
    executable = shutil.which(name)
    if executable is None or not Path(executable).is_absolute():
        raise RemoteExecutionError([f"required executable is unavailable: {name}"])
    return executable


def _run_process(
    arguments: Sequence[str],
    *,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603  # [owner=platform; rationale=validated argv executes without a command shell; expires=2027-02-28]
        list(arguments),
        cwd=repository_root,
        env=None if environment is None else dict(environment),
        check=False,
        capture_output=capture_output,
        text=True,
    )
