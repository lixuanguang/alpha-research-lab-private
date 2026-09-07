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
    """Validate the CI and checkout boundary for authenticated remote execution.

    The supplied environment is read as-is; this function neither merges it with
    the current process environment nor changes it. Validation requires an
    admitted trusted context, ``CI`` equal to ``"true"``,
    ``GITHUB_EVENT_NAME`` equal to ``"push"``, ``GITHUB_REF`` equal to
    ``"refs/heads/main"``, a credential of between 16 and 512 ASCII letters, digits, or
    ``. _ ~ -`` characters, a ``GITHUB_SHA`` matching ``git rev-parse HEAD``,
    and an empty ``git status --porcelain``. It starts those two Git commands
    through the host ``PATH`` with ``repository_root`` as their working
    directory; Git inherits the host process environment, while the validation
    comparisons inspect only the supplied mapping. The checks do not authenticate
    the credential, verify a commit signature, inspect remote configuration, or
    validate the policy beyond the fields they read. Environment findings are
    accumulated and reported after both Git commands; a Git failure propagates
    immediately and can supersede earlier environment findings.

    Args:
        policy: Loaded policy supplying the trusted contexts and credential
            environment-variable name to check.
        context: CI execution-context identifier to compare with the policy's
            trusted-context list.
        environment: Environment values to inspect. Missing expected values fail
            validation; the mapping is not modified or supplemented.
        repository_root: Git working-tree directory used for the local ``HEAD``
            and clean-checkout checks.

    Raises:
        RemoteExecutionError: If a trust or checkout condition fails, if the
            credential fails its character-set or length check, or if Git cannot
            be resolved or exits unsuccessfully.
        OSError: If Git cannot be started or ``repository_root`` is invalid.
        UnicodeDecodeError: If captured Git output cannot be decoded as text.
    """
    _RemoteExecutionRunner(policy, repository_root)._validate_trusted_context(context, environment)


def query_test_targets(repository_root: Path) -> tuple[str, ...]:
    """Return non-empty output lines from a shell-free complete-test-graph query.

    The function resolves ``bazel`` through the host process's ``PATH`` and
    starts ``bazel query tests(//...) --output=label`` with ``repository_root`` as
    its working directory. Standard output and standard error are captured, and
    the Bazel process inherits the current process environment because no
    replacement environment is supplied. Consequently, this function does not
    strip credentials, validate trust, or authenticate a remote provider; it also
    does not add a remote-execution configuration. Only the query exit status and
    the presence of non-blank output are validated. Target-label validation and
    partition checks belong to the downstream sharding boundary.

    Args:
        repository_root: Directory supplied as Bazel's current working directory.

    Returns:
        Non-blank output lines from Bazel standard output, stripped of surrounding
        whitespace and kept in query order, including duplicates. The lines are
        not validated as Bazel labels here.

    Raises:
        RemoteExecutionError: If Bazel cannot be resolved, exits unsuccessfully,
            or returns no non-blank output lines.
        OSError: If Bazel cannot be started or ``repository_root`` is invalid.
        UnicodeDecodeError: If captured Bazel output cannot be decoded as text.
    """
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


class _RemoteExecutionRunner:
    """Own authenticated remote-lane orchestration and checkout configuration."""

    def __init__(self, policy: RemoteExecutionPolicy, repository_root: Path) -> None:
        """Bind validated policy and checkout root without starting processes."""
        self._policy = policy
        self._repository_root = repository_root

    def _validate_trusted_context(self, context: str, environment: Mapping[str, str]) -> None:
        """Validate the CI and checkout boundary for authenticated remote execution.

        The supplied environment is read as-is; this function neither merges it with
        the current process environment nor changes it. Validation requires an
        admitted trusted context, ``CI`` equal to ``"true"``,
        ``GITHUB_EVENT_NAME`` equal to ``"push"``, ``GITHUB_REF`` equal to
        ``"refs/heads/main"``, a credential of between 16 and 512 ASCII letters, digits, or
        ``. _ ~ -`` characters, a ``GITHUB_SHA`` matching ``git rev-parse HEAD``,
        and an empty ``git status --porcelain``. It starts those two Git commands
        through the host ``PATH`` with ``repository_root`` as their working
        directory; Git inherits the host process environment, while the validation
        comparisons inspect only the supplied mapping. The checks do not authenticate
        the credential, verify a commit signature, inspect remote configuration, or
        validate the policy beyond the fields they read. Environment findings are
        accumulated and reported after both Git commands; a Git failure propagates
        immediately and can supersede earlier environment findings.

        Args:
            context: CI execution-context identifier to compare with the policy's
                trusted-context list.
            environment: Environment values to inspect. Missing expected values fail
                validation; the mapping is not modified or supplemented.

        Raises:
            RemoteExecutionError: If a trust or checkout condition fails, if the
                credential fails its character-set or length check, or if Git cannot
                be resolved or exits unsuccessfully.
            OSError: If Git cannot be started or ``repository_root`` is invalid.
            UnicodeDecodeError: If captured Git output cannot be decoded as text.
        """
        policy = self._policy
        repository_root = self._repository_root
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

    def _build(self, *, context: str, environment: Mapping[str, str] | None = None) -> int:
        """Run the governed build targets through authenticated remote Bazel.

        Copy ``environment`` into an execution snapshot, using the current process
        environment when it is ``None``, and validate that snapshot together with
        the Git checkout before starting Bazel. Trust comparisons inspect the copied
        snapshot, while the Git commands inherit the host process environment. The
        trust check uses ``repository_root`` for ``HEAD`` and clean-checkout checks;
        the authenticated build uses the same path as Bazel's working directory.
        Authentication reads the policy-configured credential from the snapshot,
        writes it to a temporary mode-0600 Bazel rc file, and removes that variable
        from the child environment. The build receives
        ``policy.local_fallback.build_targets`` as its target set. A nonzero Bazel
        status is returned unchanged; this entry point does not try a local fallback
        or retry the build, and it does not mutate the caller's mapping or the
        process environment.

        Args:
            context: CI execution-context identifier that must be trusted by ``policy``.
            environment: Environment values to validate and copy for Bazel. ``None``
                snapshots the current process environment; the configured credential
                variable must be present and satisfy the trust policy.

        Returns:
            The authenticated Bazel build process status, including a nonzero status
            for a failed remote build.

        Raises:
            RemoteExecutionError: If the context, required CI values, credential,
                checkout revision, or checkout cleanliness fails; if Git exits
                unsuccessfully or cannot be resolved; or if Bazel cannot be resolved
                through the host ``PATH``.
            OSError: If Git or Bazel cannot be started, if ``repository_root`` is
                invalid, or if the temporary credential directory/file cannot be
                created, written, permissioned, or removed.
            UnicodeDecodeError: If captured Git output cannot be decoded as text.
        """
        policy = self._policy
        repository_root = self._repository_root
        active_environment = dict(os.environ if environment is None else environment)
        validate_trusted_context(policy, context, active_environment, repository_root)
        return _run_authenticated_bazel(
            policy,
            repository_root=repository_root,
            environment=active_environment,
            command="build",
            targets=policy.local_fallback.build_targets,
        )

    def _test(
        self,
        *,
        context: str,
        shard_index: int,
        environment: Mapping[str, str] | None = None,
    ) -> int:
        """Run one deterministic test shard through authenticated remote Bazel.

        Copy ``environment`` into an execution snapshot, using the current process
        environment when it is ``None``, and validate that snapshot and the Git
        checkout before querying the complete test graph. Trust comparisons inspect
        the copied snapshot, while the Git commands inherit the host process
        environment. The graph query resolves Bazel through the host ``PATH``, uses
        ``repository_root`` as its working directory, and inherits that host
        environment (which may include credential variables); it does not use the
        supplied snapshot or the runner's temporary credential rc file. Select the
        requested shard with the policy's seeded partition settings. An empty
        selected shard returns ``0`` after trust validation and graph querying
        without creating a credential file or invoking authenticated remote Bazel.
        For a non-empty shard, run exactly one authenticated Bazel ``test`` command
        with its labels. The authenticated helper uses a temporary mode-0600 rc file,
        removes the credential variable from the child environment, and returns
        Bazel's status unchanged. No local fallback or whole-test retry is attempted,
        and caller or process environments are not mutated.

        Args:
            context: CI execution-context identifier that must be trusted by ``policy``.
            shard_index: Zero-based index of the shard to execute in the policy's
                complete partition.
            environment: Environment values to validate and copy for authenticated
                execution. ``None`` snapshots the current process environment; the
                graph query still inherits the process environment independently.

        Returns:
            ``0`` when the selected shard is empty, otherwise the authenticated Bazel
            test process status, including a nonzero status for a failed shard.

        Raises:
            RemoteExecutionError: If trust validation, graph querying, shard-index or
                target-set validation, or Bazel executable resolution fails.
            OSError: If Git, the graph-query process, or Bazel cannot be started, if
                ``repository_root`` is invalid, or if temporary credential
                directory/file operations fail.
            UnicodeDecodeError: If captured Git or graph-query output cannot be decoded
                as text.
        """
        policy = self._policy
        repository_root = self._repository_root
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

    def _quarantine(self, *, context: str, environment: Mapping[str, str] | None = None) -> int:
        """Run policy quarantine targets through the diagnostic Bazel lane.

        Read quarantine targets from ``policy.flakes.quarantines`` in their stored
        order and pass them unchanged to one authenticated Bazel ``test`` invocation
        with ``--config=remote-quarantine-diagnostics``. The selected Bazel profile
        supplies repetition behavior; this function does not read or enforce
        ``quarantine_repeat_count`` directly, query the test graph, alter normal
        shards, or perform a local fallback. When no quarantine entries exist, return
        ``0`` immediately without copying the environment, checking trust, reading
        the credential, touching Git, or starting Bazel. With active entries, copy
        ``environment`` (or snapshot the current process environment when it is
        ``None``), compare the copied values during trust validation, and validate
        the Git checkout using ``repository_root``; those Git commands inherit the
        host process environment. Then authenticate through a temporary mode-0600 rc
        file while removing the credential variable from the child environment. The
        caller's mapping and process environment are never mutated.

        Args:
            context: CI execution-context identifier that must be trusted by ``policy``
                when quarantine entries are active.
            environment: Environment values to validate and copy for authenticated
                execution. ``None`` snapshots the current process environment; it is
                not read when the quarantine list is empty.

        Returns:
            ``0`` when no quarantine targets are configured; otherwise the
            authenticated Bazel diagnostic-test process status, including nonzero
            statuses from failed repetitions.

        Raises:
            RemoteExecutionError: If active-entry trust validation fails, if Git
                exits unsuccessfully or cannot be resolved, or if Bazel cannot be
                resolved through the host ``PATH``.
            OSError: If Git or Bazel cannot be started, if ``repository_root`` is
                invalid, or if the temporary credential directory/file cannot be
                created, written, permissioned, or removed.
            UnicodeDecodeError: If captured Git output cannot be decoded as text.
        """
        policy = self._policy
        repository_root = self._repository_root
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


def run_remote_build(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run the governed build targets through authenticated remote Bazel.

    Copy ``environment`` into an execution snapshot, using the current process
    environment when it is ``None``, and validate that snapshot together with
    the Git checkout before starting Bazel. Trust comparisons inspect the copied
    snapshot, while the Git commands inherit the host process environment. The
    trust check uses ``repository_root`` for ``HEAD`` and clean-checkout checks;
    the authenticated build uses the same path as Bazel's working directory.
    Authentication reads the policy-configured credential from the snapshot,
    writes it to a temporary mode-0600 Bazel rc file, and removes that variable
    from the child environment. The build receives
    ``policy.local_fallback.build_targets`` as its target set. A nonzero Bazel
    status is returned unchanged; this entry point does not try a local fallback
    or retry the build, and it does not mutate the caller's mapping or the
    process environment.

    Args:
        policy: Loaded remote-execution policy supplying trust, credential, and
            governed build-target settings.
        context: CI execution-context identifier that must be trusted by ``policy``.
        repository_root: Git working-tree and Bazel working directory for the run.
        environment: Environment values to validate and copy for Bazel. ``None``
            snapshots the current process environment; the configured credential
            variable must be present and satisfy the trust policy.

    Returns:
        The authenticated Bazel build process status, including a nonzero status
        for a failed remote build.

    Raises:
        RemoteExecutionError: If the context, required CI values, credential,
            checkout revision, or checkout cleanliness fails; if Git exits
            unsuccessfully or cannot be resolved; or if Bazel cannot be resolved
            through the host ``PATH``.
        OSError: If Git or Bazel cannot be started, if ``repository_root`` is
            invalid, or if the temporary credential directory/file cannot be
            created, written, permissioned, or removed.
        UnicodeDecodeError: If captured Git output cannot be decoded as text.
    """
    return _RemoteExecutionRunner(policy, repository_root)._build(
        context=context, environment=environment
    )


def run_remote_test_shard(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    shard_index: int,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run one deterministic test shard through authenticated remote Bazel.

    Copy ``environment`` into an execution snapshot, using the current process
    environment when it is ``None``, and validate that snapshot and the Git
    checkout before querying the complete test graph. Trust comparisons inspect
    the copied snapshot, while the Git commands inherit the host process
    environment. The graph query resolves Bazel through the host ``PATH``, uses
    ``repository_root`` as its working directory, and inherits that host
    environment (which may include credential variables); it does not use the
    supplied snapshot or the runner's temporary credential rc file. Select the
    requested shard with the policy's seeded partition settings. An empty
    selected shard returns ``0`` after trust validation and graph querying
    without creating a credential file or invoking authenticated remote Bazel.
    For a non-empty shard, run exactly one authenticated Bazel ``test`` command
    with its labels. The authenticated helper uses a temporary mode-0600 rc file,
    removes the credential variable from the child environment, and returns
    Bazel's status unchanged. No local fallback or whole-test retry is attempted,
    and caller or process environments are not mutated.

    Args:
        policy: Loaded remote-execution policy supplying trust, credential,
            sharding, and remote-test settings.
        context: CI execution-context identifier that must be trusted by ``policy``.
        shard_index: Zero-based index of the shard to execute in the policy's
            complete partition.
        repository_root: Git working-tree and Bazel working directory for the run.
        environment: Environment values to validate and copy for authenticated
            execution. ``None`` snapshots the current process environment; the
            graph query still inherits the process environment independently.

    Returns:
        ``0`` when the selected shard is empty, otherwise the authenticated Bazel
        test process status, including a nonzero status for a failed shard.

    Raises:
        RemoteExecutionError: If trust validation, graph querying, shard-index or
            target-set validation, or Bazel executable resolution fails.
        OSError: If Git, the graph-query process, or Bazel cannot be started, if
            ``repository_root`` is invalid, or if temporary credential
            directory/file operations fail.
        UnicodeDecodeError: If captured Git or graph-query output cannot be decoded
            as text.
    """
    return _RemoteExecutionRunner(policy, repository_root)._test(
        context=context, shard_index=shard_index, environment=environment
    )


def run_quarantine_diagnostics(
    policy: RemoteExecutionPolicy,
    *,
    context: str,
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run policy quarantine targets through the diagnostic Bazel lane.

    Read quarantine targets from ``policy.flakes.quarantines`` in their stored
    order and pass them unchanged to one authenticated Bazel ``test`` invocation
    with ``--config=remote-quarantine-diagnostics``. The selected Bazel profile
    supplies repetition behavior; this function does not read or enforce
    ``quarantine_repeat_count`` directly, query the test graph, alter normal
    shards, or perform a local fallback. When no quarantine entries exist, return
    ``0`` immediately without copying the environment, checking trust, reading
    the credential, touching Git, or starting Bazel. With active entries, copy
    ``environment`` (or snapshot the current process environment when it is
    ``None``), compare the copied values during trust validation, and validate
    the Git checkout using ``repository_root``; those Git commands inherit the
    host process environment. Then authenticate through a temporary mode-0600 rc
    file while removing the credential variable from the child environment. The
    caller's mapping and process environment are never mutated.

    Args:
        policy: Loaded remote-execution policy supplying trusted-context,
            credential, and quarantine-target settings.
        context: CI execution-context identifier that must be trusted by ``policy``
            when quarantine entries are active.
        repository_root: Git working-tree and Bazel working directory for the run.
        environment: Environment values to validate and copy for authenticated
            execution. ``None`` snapshots the current process environment; it is
            not read when the quarantine list is empty.

    Returns:
        ``0`` when no quarantine targets are configured; otherwise the
        authenticated Bazel diagnostic-test process status, including nonzero
        statuses from failed repetitions.

    Raises:
        RemoteExecutionError: If active-entry trust validation fails, if Git
            exits unsuccessfully or cannot be resolved, or if Bazel cannot be
            resolved through the host ``PATH``.
        OSError: If Git or Bazel cannot be started, if ``repository_root`` is
            invalid, or if the temporary credential directory/file cannot be
            created, written, permissioned, or removed.
        UnicodeDecodeError: If captured Git output cannot be decoded as text.
    """
    return _RemoteExecutionRunner(policy, repository_root)._quarantine(
        context=context, environment=environment
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
