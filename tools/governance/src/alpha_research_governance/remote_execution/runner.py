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
    """Run one Bazel lane with a temporary file-backed remote credential.

    Read the configured credential and pass it through a temporary rc file changed
    to mode ``0o600`` before launch. The invocation includes the explicit
    ``--config=remote-execution`` option. The context manager attempts to remove
    the temporary directory on normal and exceptional exit, including process
    startup failure; cleanup errors can propagate as ``OSError``. The rc path,
    rather than the credential value, enters the Bazel argument vector, and the
    configured credential variable is removed from the replacement child
    environment. This helper does not inspect unrelated environment entries or
    caller-supplied arguments and assumes its caller has already performed trust
    and credential validation.

    Args:
        policy: Loaded policy supplying the credential variable and auth header.
        repository_root: Directory supplied as Bazel's current working directory.
        environment: Complete environment to copy for Bazel after removing the
            configured credential variable.
        command: Bazel subcommand passed after the temporary ``--bazelrc`` option.
        targets: Target labels appended to the Bazel argument vector after ``--``.
        extra_arguments: Additional Bazel options inserted before the target
            separator, such as the quarantine-diagnostics configuration.

    Returns:
        Bazel's integer process status, including a nonzero status for a failed
        lane. A nonzero status is returned for the caller to interpret.
        No local fallback is attempted here.

    Raises:
        KeyError: The configured credential variable is absent from ``environment``.
        RemoteExecutionError: ``bazel`` cannot be resolved through the host PATH.
        OSError: The temporary directory or credential file cannot be created,
            changed, removed, or the Bazel process cannot be started.
    """
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
    """Run Git with captured text output and return its successful standard output.

    Resolve ``git`` through the host process's PATH, pass the supplied arguments
    as an argv vector, and use ``repository_root`` as the process working
    directory. Git output is captured and decoded as text; standard error is
    captured but is not included in the returned value or nonzero-status error.
    The arguments are passed through unchanged, so this helper does not perform
    general Git-argument validation.

    Args:
        repository_root: Directory supplied as Git's current working directory.
        *arguments: Git subcommand and options passed after the executable.

    Returns:
        Git's standard output with leading and trailing whitespace removed when
        Git exits successfully.

    Raises:
        RemoteExecutionError: ``git`` cannot be resolved to an absolute executable
            on host PATH, or Git exits with a nonzero status.
        OSError: Git cannot be started or its working directory is invalid.
        UnicodeDecodeError: Captured Git output cannot be decoded as text by the
            subprocess text-mode decoder.
    """
    completed = _run_process(
        (_resolve_executable("git"), *arguments),
        repository_root=repository_root,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RemoteExecutionError([f"git {' '.join(arguments)} failed"])
    return completed.stdout.strip()


def _resolve_executable(name: str) -> str:
    """Resolve an allowed tool name to an absolute executable path on host PATH.

    The lookup uses the current process's host environment and does not consult
    a child environment supplied to another helper. Only the literal names
    ``bazel`` and ``git`` are admitted; no process is started by this function.

    Args:
        name: Executable basename to resolve; it must be ``bazel`` or ``git``.

    Returns:
        The absolute path returned by ``shutil.which`` for the allowed tool.

    Raises:
        RemoteExecutionError: ``name`` is outside the allowlist, no matching
            executable is found on host PATH, or the match is not absolute.
    """
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
    """Run an argv vector without a shell and return its completed text process.

    Convert ``arguments`` to a list and invoke it with ``repository_root`` as
    ``cwd`` and ``check=False``. With ``environment=None``, ``subprocess``
    inherits the current process environment; with a mapping, the copied mapping
    replaces the inherited environment. ``capture_output`` controls both output
    streams: captured streams are decoded as text, while the default leaves the
    streams attached to the parent process. No subprocess timeout is supplied.
    For Bazel invocations, remote-operation timeouts are configured separately
    through Bazel arguments or configuration; this generic helper also handles
    Git. This helper does not validate the executable or every argv value, and it
    returns nonzero statuses instead of raising for them.

    Args:
        arguments: Executable and arguments passed as one shell-free argv vector.
        repository_root: Directory supplied as the child process's ``cwd``.
        environment: Replacement child environment, or ``None`` to inherit the
            current process environment.
        capture_output: Whether to capture stdout and stderr as decoded strings.

    Returns:
        The completed process, including its return code. A nonzero ``returncode``
        is retained; captured output is available as text, and uncaptured output
        fields are ``None``.

    Raises:
        OSError: The process cannot be started or ``repository_root`` is invalid.
        UnicodeDecodeError: Captured output cannot be decoded by the default
            subprocess text-mode decoder.
    """
    return subprocess.run(  # nosec B603  # [owner=platform; rationale=validated argv executes without a command shell; expires=2027-02-28]
        list(arguments),
        cwd=repository_root,
        env=None if environment is None else dict(environment),
        check=False,
        capture_output=capture_output,
        text=True,
    )
