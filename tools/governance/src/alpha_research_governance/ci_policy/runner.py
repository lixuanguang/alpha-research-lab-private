"""Execute affected and full CI lanes through pinned repository interfaces."""

from __future__ import annotations

# standard library imports
import json
import os
import re
import subprocess  # nosec B404  # [owner=platform; rationale=required shell-free governed tool boundary; expires=2027-02-28]
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Literal, Protocol, TypeGuard
from urllib.parse import urlsplit

# project library imports
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


class _JsonDumpModel(Protocol):
    """Expose the JSON-mode model dump consumed by event serialization."""

    def model_dump(self, *, mode: Literal["json"]) -> object:
        """Return the model's JSON-compatible representation."""


def _is_object_dict(value: object) -> TypeGuard[dict[object, object]]:
    """Narrow a model serialization result to an object-valued dictionary."""
    return isinstance(value, dict)


def _run_command_and_capture_output(
    command: list[str], *, root: Path, environment: dict[str, str] | None = None
) -> bytes:
    """Run an argv command in ``root`` and return its captured standard output.

    The command is executed without a shell. Standard output and standard error
    are captured as bytes. A successful invocation returns only standard output;
    standard error is discarded in that case. On failure, both streams are
    decoded as UTF-8 with replacement characters for the diagnostic message.

    Args:
        command: Non-shell argument vector passed to ``subprocess.run``. The
            first token identifies the executable in startup diagnostics.
        root: Working directory supplied to the child process.
        environment: Optional complete child environment. ``None`` inherits the
            current process environment; a mapping replaces it for the child.

    Returns:
        The command's unmodified standard-output bytes on a zero exit status.

    Raises:
        CIPolicyError: If the executable cannot start or exits with a nonzero
            status. Startup errors retain the operating-system exception as the
            cause; exit diagnostics include the first three command tokens and
            the stripped combined output.
    """
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
    """Run an argv command in ``root`` while leaving its output visible.

    The command is passed directly to ``subprocess.run`` without a shell or
    output capture, so the child's standard output and standard error use the
    process's normal visible streams. The child inherits the current process
    environment, and the helper waits without imposing a timeout or returning
    the command's output.

    Args:
        command: Non-shell argument vector to execute. The complete vector is
            included in a nonzero-exit diagnostic.
        root: Working directory supplied to the child process.

    Raises:
        CIPolicyError: If the executable cannot start or exits with a nonzero
            status. Startup errors retain the operating-system exception as the
            cause.
    """
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


class CIRunner:
    """Own CI revision, selection, and lane execution for one repository root."""

    def __init__(self, repository_root: Path) -> None:
        """Bind CIRunner collaborators without filesystem or process I/O.

        Args:
            repository_root: Repository root used by later service operations.
        """
        self.repository_root = repository_root

    def _scan_paths_for_secrets(self, paths: tuple[str, ...]) -> None:
        """Run policy-bound local and external secret scanners for changed paths.

        Args:
            paths: Candidate repository-relative paths to normalize and inspect.

        Raises:
            CIPolicyError: If policy validation, path normalization, local scanning,
                or the configured external scanner fails.
            OSError: If delegated filesystem operations fail without translation.
            UnicodeError: If a delegated text boundary rejects repository content.
        """
        root = self.repository_root
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

    def _check_schema_compatibility(self, *, modules: tuple[str, ...], base: str) -> None:
        """Run ordered Buf compatibility checks under the bound repository root.

        Args:
            modules: Schema module identifiers to check in execution order.
            base: Git revision inserted into each baseline query and comparison locator.

        Raises:
            CIPolicyError: If any lint, baseline query, or breaking command fails.
        """
        root = self.repository_root
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

    def _run_pre_commit_without_mutation(self, arguments: list[str]) -> None:
        """Run pre-commit and reject an observed worktree mutation.

        Args:
            arguments: Additional argument tokens passed unchanged to pre-commit.

        Raises:
            CIPolicyError: If a command fails or the before/after Git status differs.
        """
        root = self.repository_root
        before = _git_worktree_state(root)
        _run_command_with_visible_output(["pre-commit", "run", *arguments], root=root)
        if _git_worktree_state(root) != before:
            raise CIPolicyError(
                ["pre-commit changed the worktree; commit the formatted result and rerun"]
            )

    def _run_timed_ci_phase(
        self,
        commands: tuple[list[str], ...],
        *,
        phase: str,
        event_stream: IO[str],
        run_id: str,
        revision: str,
        evidence_url: str,
        environment: str,
        target: str,
    ) -> None:
        """Run ordered phase commands and emit their bound CI duration event.

        Args:
            commands: Ordered non-shell argv vectors for the phase.
            phase: Build or test phase recorded in the duration event.
            event_stream: Caller-owned stream receiving one JSONL event.
            run_id: Event identity used in the duration record.
            revision: Commit digest measured by the phase.
            evidence_url: Retained evidence URL, or empty for local execution.
            environment: CI environment dimension.
            target: CI lane dimension.

        Raises:
            CIPolicyError: If a command or event boundary fails.
            OSError: If stream I/O fails after command execution.
            TypeError: If event serialization or stream writing rejects a value.
            ValueError: If event serialization or stream operations reject a value.
        """
        root = self.repository_root
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

    def resolve_git_commit(self, revision: str) -> str:
        """Resolve a Git revision expression to an exact commit SHA.

        Reject an empty expression or one beginning with ``-`` before passing the
        remaining expression as one argument to ``git rev-parse --verify
        --end-of-options <revision>^{commit}``. Run that shell-free command with
        ``root`` as its working directory. Git must emit one 40-character lowercase
        hexadecimal SHA; successful output is decoded as strict ASCII and stripped
        of surrounding whitespace. The command has no timeout.

        Args:
            revision: Non-empty Git revision expression that must not begin with
                ``-``; Git resolves it and requires the result to name a commit.

        Returns:
            The resolved 40-character lowercase hexadecimal commit SHA.

        Raises:
            CIPolicyError: If ``revision`` is empty or option-shaped, Git cannot
                start, Git exits unsuccessfully, or its successful output is not an
                exact commit SHA. Command failures use the command helper's
                translated diagnostics and preserve startup causes.
            ValueError: If ``revision`` contains an embedded NUL character and
                ``subprocess.run`` rejects the command argument before Git starts.
            UnicodeDecodeError: If successful Git output is not valid ASCII.
        """
        root = self.repository_root
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
        self, base_ref: str, head_ref: str
    ) -> tuple[str, str, tuple[ChangedPath, ...]]:
        """Return resolved commits and sorted paths changed between two revisions.

        Validate the repository CI policy, resolve ``base_ref`` and ``head_ref``
        with ``resolve_git_commit``, then run the shell-free command ``git diff
        --name-status -z --diff-filter=ACDMRTUXB <base> <head> --`` with ``root``
        as its working directory. The command has no timeout. Parse Git's
        NUL-delimited UTF-8 output with the policy's inclusive
        ``maximum_changed_files`` limit, counting expanded path records before
        normalization and deduplication; each rename or copy contributes two.
        Rename and copy records contribute both source and destination paths;
        deletion records retain their deleted path. Normalization validates
        repository-relative paths, removes duplicate ``(status, path)`` records,
        and sorts the remaining records lexically by status and then path.

        Args:
            base_ref: Git revision expression for the comparison base. It must be
                non-empty, must not begin with ``-``, and must resolve to a commit.
            head_ref: Git revision expression for the comparison head. It must be
                non-empty, must not begin with ``-``, and must resolve to a commit.

        Returns:
            A three-tuple containing the resolved base SHA, resolved head SHA, and
            unique ``ChangedPath`` records sorted by ``(status, path)``. The path
            tuple is empty when the resolved commits have no selected changes.

        Raises:
            CIPolicyError: If CI policy findings, revision resolution, the Git diff,
                the changed-file limit, status parsing, or path normalization rejects
                the operation. Git startup and nonzero exit failures are translated
                by the command helper.
            ChangeRiskPolicyError: If repository policy validation rejects the
                referenced change-risk policy.
            EvidenceGovernanceError: If repository policy validation rejects the
                retained CI evidence.
            ValidationError: If repository policy validation reaches an uncovered
                policy-model type failure.
            OSError: If repository policy validation encounters an unhandled
                filesystem or process-startup failure.
            UnicodeError: If repository policy validation encounters an unhandled
                text-decoding failure.
            UnicodeDecodeError: If Git's name-status output is not valid UTF-8, or
                a resolved revision command emits non-ASCII output.
            ValueError: If either revision contains an embedded NUL and
                ``subprocess.run`` rejects the command argument, or if Git emits a
                bare copy status with two paths and the existing status normalizer
                attempts to parse its missing score.
        """
        root = self.repository_root
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

    def verify_git_merge_parents(self, *, base_ref: str, head_ref: str, revision: str) -> str:
        """Verify that a revision has exactly the declared base and head parents.

        Resolve ``base_ref``, ``head_ref``, and ``revision`` with
        ``resolve_git_commit``, then run the shell-free command ``git show -s
        --format=%P <merged>`` with ``root`` as its working directory. The command
        has no timeout. Decode successful parent output as strict ASCII, strip
        surrounding whitespace, split on whitespace, and require the resulting
        sequence to equal ``(base_sha, head_sha)`` exactly. This enforces exactly
        two parents in the declared order. The command helper captures output and
        translates startup and nonzero-exit failures.

        Args:
            base_ref: Git revision expression for the expected first parent. It
                must be non-empty, must not begin with ``-``, and must resolve to a
                commit.
            head_ref: Git revision expression for the expected second parent. It
                must be non-empty, must not begin with ``-``, and must resolve to a
                commit.
            revision: Git revision expression for the merge result. It must be
                non-empty, must not begin with ``-``, and must resolve to a commit.

        Returns:
            The resolved 40-character lowercase hexadecimal merge-result SHA when
            its parent sequence is exactly ``(base_sha, head_sha)``.

        Raises:
            CIPolicyError: If any revision is empty or option-shaped, cannot be
                resolved, Git cannot start or exits unsuccessfully, or the observed
                parent sequence is not exactly the declared two-parent sequence.
            ValueError: If any revision contains an embedded NUL and
                ``subprocess.run`` rejects the command argument before Git starts.
            UnicodeDecodeError: If successful revision or parent output is not
                valid ASCII.
        """
        root = self.repository_root
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

    def select_affected_targets(self, *, base_ref: str, head_ref: str) -> AffectedSelection:
        """Select Bazel owners and reverse dependencies for changed paths.

        The repository CI policy is validated before the Git comparison. The
        comparison resolves ``base_ref`` and ``head_ref`` to commits and returns
        normalized changed paths. The function then always queries ``//...`` as
        Bazel XML, decodes that output as UTF-8, and derives the direct source
        owners. A foundational or unresolved path produces the policy's full-graph
        selection. Whenever selection is marked full or has no owner targets, the
        function returns without reverse-dependency queries; a non-full ownerless
        selection therefore retains its empty target tuples. Otherwise, the
        function queries reverse dependencies for build and test targets, validates
        the returned labels, and attaches sorted unique results. Git and Bazel
        commands run without a shell and their output is captured. The function
        performs no direct repository-file writes; invoked tools may have incidental
        cache effects.

        Args:
            base_ref: Non-empty Git revision expression for the comparison base;
                it must not begin with ``-`` and must resolve to a commit.
            head_ref: Non-empty Git revision expression for the comparison head;
                it must not begin with ``-`` and must resolve to a commit.

        Returns:
            An ``AffectedSelection`` containing sorted changed paths, direct owner
            labels, and either attached reverse-dependency targets or the full
            ``//...`` fallback. Empty changes produce no targets and
            ``reason="no_changed_paths"``.

        Raises:
            CIPolicyError: If repository policy, Git comparison, Bazel XML/query
                output, owner selection, or reverse-dependency labels are invalid.
                Git and Bazel startup or nonzero-exit failures are translated by
                the command boundary.
            ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
            EvidenceGovernanceError: If retained repository evidence is invalid.
            ValidationError: If policy model construction rejects a value not
                covered by explicit policy checks.
            OSError: If policy validation or an unhandled filesystem/process
                operation fails.
            UnicodeError: If policy validation or a delegated strict text boundary,
                including Git or Bazel output decoding, encounters invalid text.
            ValueError: If a revision contains an embedded NUL or Git emits a
                bare copy status that reaches the existing score conversion.
        """
        root = self.repository_root
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

    def run_affected_ci_lane(
        self,
        *,
        base_ref: str,
        head_ref: str,
        event_log: Path,
        run_id: str,
        evidence_url: str,
        environment: str,
    ) -> AffectedSelection:
        """Run fast-lane preflight and the selected Bazel build/test commands.

        The repository policy is validated first, then ``event_log`` is resolved
        under the policy's event-log directory. Relative paths are rooted at
        ``root``; parent directories are created and the UTF-8 log is opened in
        ``"w"`` mode, so an existing log is truncated before revision or event
        validation. The log is closed when the lane exits its context.

        The lane resolves the base and head refs and requires the resolved head to
        equal the checked-out ``HEAD``. It validates the fast-lane event context,
        requires a clean Git status for every environment other than the exact
        ``"local"`` value, and runs preflight in this order: generated-artifact
        rejection, secret scanning, changed-schema compatibility, and conditional
        pre-commit (only when paths changed). Pre-commit status is compared before
        and after execution; a detected mutation is rejected and left in place.
        Target selection is then performed with the resolved commits. Build and
        test phases run only when their target tuples are non-empty. A force-full
        selection still runs the ``fast`` lane's ``//...`` build and test phases
        and does not add the full lane's rollback check. Each executed phase uses
        the ``fast`` event target and attempts one JSONL duration event, flushing
        the stream in its ``finally`` path. A command failure stops later commands
        and phases; finalization or log I/O errors can leave a partial or empty log
        and can mask the command failure.

        Args:
            base_ref: Non-empty Git revision expression for the comparison base;
                it must not begin with ``-`` and must resolve to a commit.
            head_ref: Non-empty Git revision expression for the comparison head;
                it must not begin with ``-`` and must resolve to the checked-out
                commit.
            event_log: Event-log path, relative to ``root`` unless absolute. Its
                resolved path must equal or descend from the policy event-log
                directory.
            run_id: Lowercase event identifier used for phase duration records.
            evidence_url: Credential-free HTTPS evidence URL, or empty only when
                ``environment`` is exactly ``"local"``.
            environment: Bounded CI environment token. ``"local"`` permits a
                dirty checkout and an empty evidence URL; other values require
                both a clean checkout and an evidence URL.

        Returns:
            The affected selection used for the lane, including its changed paths,
            owner labels, build/test targets, full-fallback flag, and reason.

        Raises:
            CIPolicyError: If policy, revision identity, event context, path
                preflight, schema checks, pre-commit, target selection, phase
                commands, event emission, or event-log containment fails. A phase
                finalization failure can mask a command failure.
            ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
            EvidenceGovernanceError: If retained repository evidence is invalid.
            ValidationError: If policy model construction rejects an uncovered value.
            OSError: If policy validation, event-log I/O, or an unhandled delegated
                filesystem/process operation fails.
            UnicodeError: If policy or delegated strict text boundaries, including
                Git or Bazel output decoding, encounter invalid text.
            RuntimeError: If event-log path resolution encounters a symlink loop.
            TypeError: If delegated event serialization or stream writing rejects
                a value.
            ValueError: If a revision contains an embedded NUL, Git emits a bare
                copy status that reaches score conversion, or delegated event/log
                serialization rejects a value.
        """
        root = self.repository_root
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
            self._scan_paths_for_secrets(paths)
            self._check_schema_compatibility(
                modules=_changed_schema_modules(paths, policy.schema_module_roots),
                base=base,
            )
            if paths:
                self._run_pre_commit_without_mutation(["--from-ref", base, "--to-ref", head])
            selection = select_affected_targets(root, base_ref=base, head_ref=head)
            if selection.build_targets:
                self._run_timed_ci_phase(
                    (["bazel", "build", "--config=ci", *selection.build_targets],),
                    phase="build",
                    event_stream=events,
                    run_id=run_id,
                    revision=head,
                    evidence_url=evidence_url,
                    environment=environment,
                    target="fast",
                )
            if selection.test_targets:
                self._run_timed_ci_phase(
                    (["bazel", "test", "--config=ci", *selection.test_targets],),
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
        self,
        *,
        base_ref: str,
        event_log: Path,
        run_id: str,
        evidence_url: str,
        environment: str,
    ) -> None:
        """Run the authoritative full graph, rollback check, and CI preflight.

        The repository policy is validated first, then ``event_log`` is resolved
        under the policy's event-log directory. Relative paths are rooted at
        ``root``; parent directories are created and the UTF-8 log is opened in
        ``"w"`` mode, truncating an existing file before revision or event
        validation. The log is closed when the lane exits its context.

        The lane resolves ``base_ref`` and the checked-out ``HEAD``, validates a
        ``full`` event context, and requires a clean Git status outside the exact
        ``"local"`` environment. It rejects generated artifact prefixes among all
        tracked paths, scans those paths, checks every configured schema module,
        and runs pre-commit with ``--all-files``. It then runs a build phase for
        ``bazel build --config=ci //...`` and a test phase containing the ordered
        commands ``bazel test --config=ci //...`` followed by
        ``make --no-print-directory rollback-check``. Each command uses visible
        output. Each entered phase attempts one JSONL duration event, flushing the
        stream in its ``finally`` path. A failure stops subsequent commands or
        phases; the log may be empty or partial, and event finalization can mask a
        command failure.

        Args:
            base_ref: Non-empty Git revision expression used as the schema
                comparison baseline; it must not begin with ``-`` and must resolve
                to a commit.
            event_log: Event-log path, relative to ``root`` unless absolute. Its
                resolved path must equal or descend from the policy event-log
                directory.
            run_id: Lowercase event identifier used for phase duration records.
            evidence_url: Credential-free HTTPS evidence URL, or empty only when
                ``environment`` is exactly ``"local"``.
            environment: Bounded CI environment token. ``"local"`` permits a
                dirty checkout and an empty evidence URL; other values require
                both a clean checkout and an evidence URL.

        Raises:
            CIPolicyError: If policy, revision or event context, path preflight,
                schema checks, pre-commit, phase commands, event emission, or
                event-log containment fails. A phase finalization failure can mask
                a command failure.
            ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
            EvidenceGovernanceError: If retained repository evidence is invalid.
            ValidationError: If policy model construction rejects an uncovered value.
            OSError: If policy validation, event-log I/O, or an unhandled delegated
                filesystem/process operation fails.
            UnicodeError: If policy or delegated strict text boundaries, including
                Git output decoding, encounter invalid text.
            RuntimeError: If event-log path resolution encounters a symlink loop.
            TypeError: If delegated event serialization or stream writing rejects
                a value.
            ValueError: If ``base_ref`` contains an embedded NUL or delegated
                event/log serialization rejects a value.
        """
        root = self.repository_root
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
            self._scan_paths_for_secrets(paths)
            self._check_schema_compatibility(modules=policy.schema_module_roots, base=base)
            self._run_pre_commit_without_mutation(["--all-files"])
            self._run_timed_ci_phase(
                (["bazel", "build", "--config=ci", "//..."],),
                phase="build",
                event_stream=events,
                run_id=run_id,
                revision=revision,
                evidence_url=evidence_url,
                environment=environment,
                target="full",
            )
            self._run_timed_ci_phase(
                (
                    ["bazel", "test", "--config=ci", "//..."],
                    ["make", "--no-print-directory", "rollback-check"],
                ),
                phase="test",
                event_stream=events,
                run_id=run_id,
                revision=revision,
                evidence_url=evidence_url,
                environment=environment,
                target="full",
            )


def resolve_git_commit(root: Path, revision: str) -> str:
    """Resolve a Git revision expression to an exact commit SHA.

    Reject an empty expression or one beginning with ``-`` before passing the
    remaining expression as one argument to ``git rev-parse --verify
    --end-of-options <revision>^{commit}``. Run that shell-free command with
    ``root`` as its working directory. Git must emit one 40-character lowercase
    hexadecimal SHA; successful output is decoded as strict ASCII and stripped
    of surrounding whitespace. The command has no timeout.

    Args:
        root: Working directory supplied to Git for resolving the revision.
        revision: Non-empty Git revision expression that must not begin with
            ``-``; Git resolves it and requires the result to name a commit.

    Returns:
        The resolved 40-character lowercase hexadecimal commit SHA.

    Raises:
        CIPolicyError: If ``revision`` is empty or option-shaped, Git cannot
            start, Git exits unsuccessfully, or its successful output is not an
            exact commit SHA. Command failures use the command helper's
            translated diagnostics and preserve startup causes.
        ValueError: If ``revision`` contains an embedded NUL character and
            ``subprocess.run`` rejects the command argument before Git starts.
        UnicodeDecodeError: If successful Git output is not valid ASCII.
    """
    return CIRunner(root).resolve_git_commit(revision)


def git_changed_paths_between(
    root: Path, base_ref: str, head_ref: str
) -> tuple[str, str, tuple[ChangedPath, ...]]:
    """Return resolved commits and sorted paths changed between two revisions.

    Validate the repository CI policy, resolve ``base_ref`` and ``head_ref``
    with ``resolve_git_commit``, then run the shell-free command ``git diff
    --name-status -z --diff-filter=ACDMRTUXB <base> <head> --`` with ``root``
    as its working directory. The command has no timeout. Parse Git's
    NUL-delimited UTF-8 output with the policy's inclusive
    ``maximum_changed_files`` limit, counting expanded path records before
    normalization and deduplication; each rename or copy contributes two.
    Rename and copy records contribute both source and destination paths;
    deletion records retain their deleted path. Normalization validates
    repository-relative paths, removes duplicate ``(status, path)`` records,
    and sorts the remaining records lexically by status and then path.

    Args:
        root: Repository directory used for policy validation and as Git's
            working directory.
        base_ref: Git revision expression for the comparison base. It must be
            non-empty, must not begin with ``-``, and must resolve to a commit.
        head_ref: Git revision expression for the comparison head. It must be
            non-empty, must not begin with ``-``, and must resolve to a commit.

    Returns:
        A three-tuple containing the resolved base SHA, resolved head SHA, and
        unique ``ChangedPath`` records sorted by ``(status, path)``. The path
        tuple is empty when the resolved commits have no selected changes.

    Raises:
        CIPolicyError: If CI policy findings, revision resolution, the Git diff,
            the changed-file limit, status parsing, or path normalization rejects
            the operation. Git startup and nonzero exit failures are translated
            by the command helper.
        ChangeRiskPolicyError: If repository policy validation rejects the
            referenced change-risk policy.
        EvidenceGovernanceError: If repository policy validation rejects the
            retained CI evidence.
        ValidationError: If repository policy validation reaches an uncovered
            policy-model type failure.
        OSError: If repository policy validation encounters an unhandled
            filesystem or process-startup failure.
        UnicodeError: If repository policy validation encounters an unhandled
            text-decoding failure.
        UnicodeDecodeError: If Git's name-status output is not valid UTF-8, or
            a resolved revision command emits non-ASCII output.
        ValueError: If either revision contains an embedded NUL and
            ``subprocess.run`` rejects the command argument, or if Git emits a
            bare copy status with two paths and the existing status normalizer
            attempts to parse its missing score.
    """
    return CIRunner(root).git_changed_paths_between(base_ref, head_ref)


def _git_tracked_paths(root: Path) -> tuple[str, ...]:
    """List tracked repository-relative paths using Git's NUL-delimited output.

    The query runs ``git ls-files -z`` with ``root`` as its working directory.
    Callers are expected to provide the repository root, but this helper does
    not validate that expectation or check path containment. NUL delimiting
    keeps embedded newlines in a path unambiguous. Empty fields produced by
    splitting the payload are removed, while Git's order is retained; this
    helper does not sort or deduplicate the paths.

    Args:
        root: Repository directory in which Git resolves the index and worktree.

    Returns:
        A tuple of decoded paths in Git output order. With ``root`` set to the
        repository root these are repository-relative; a subdirectory working
        directory can cause Git to report paths relative to that directory.

    Raises:
        CIPolicyError: If Git cannot start or exits unsuccessfully; the command
            boundary supplies the translated diagnostic.
        UnicodeDecodeError: If Git emits a tracked path that is not valid UTF-8.
    """
    payload = _run_command_and_capture_output(["git", "ls-files", "-z"], root=root)
    return tuple(path for path in payload.decode("utf-8", errors="strict").split("\0") if path)


def _reject_generated_artifact_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
    """Reject paths whose raw names begin with a generated-artifact prefix.

    Matching is a lexical ``str.startswith`` check for each supplied prefix.
    The function does not normalize paths, require them to exist, enforce a
    path-component boundary, or remove duplicate inputs. Rejected paths remain
    in their input order in the diagnostic, including repeated occurrences.

    Args:
        paths: Repository-relative paths to inspect in the supplied order.
        prefixes: Raw prefixes that identify forbidden generated-artifact paths.
            A trailing slash is needed when a directory-component boundary is
            intended, such as ``"build/"``.

    Raises:
        CIPolicyError: If at least one path starts with any supplied prefix. The
            finding lists every matching input path in its original order.
    """
    generated = [path for path in paths if any(path.startswith(prefix) for prefix in prefixes)]
    if generated:
        raise CIPolicyError([f"generated artifacts cannot enter the source diff: {generated}"])


def _scan_paths_for_secrets(root: Path, paths: tuple[str, ...]) -> None:
    """Scan normalized existing paths with the policy's local and external checks.

    The repository policy is validated first. Each supplied path is wrapped in
    a synthetic ``M`` record and passed through ``normalize_changed_paths``;
    that step performs lexical path validation, removes duplicate ``(status,
    path)`` records, and returns paths in lexical order. Only normalized paths
    that are regular files according to ``Path.is_file`` are sent to the
    scanners. A missing path is silently omitted at this stage, while the
    delegated path scanner performs its own containment, symlink, type, size,
    and content checks.

    The local ``scan_secret_paths`` check runs before the configured executable.
    When at least one existing path remains, the executable receives the
    argument vector ``[executable, "--", *existing]`` with a copy of the
    process environment whose ``LC_ALL`` is ``C.UTF-8`` and ``TZ`` is ``UTC``.
    Its output is captured and discarded on success. An empty existing set
    means that no external process is started. Neither scanner promises to
    detect secrets outside the configured high-confidence patterns.

    Args:
        root: Repository directory used for policy validation and path joining.
        paths: Candidate repository-relative paths to normalize and inspect.

    Raises:
        CIPolicyError: If the policy, normalized paths, local scan, or external
            scanner command fails. Command-start and nonzero-exit failures are
            translated by the command helper; path and scanner findings retain
            the delegated diagnostics.
        OSError: If delegated filesystem operations fail without translation.
        UnicodeError: If repository-policy or another delegated strict text
            boundary encounters invalid encoding; local byte scanning and the
            captured-output command helper do not strictly decode their payloads.
    """
    return CIRunner(root)._scan_paths_for_secrets(paths)


def verify_git_merge_parents(root: Path, *, base_ref: str, head_ref: str, revision: str) -> str:
    """Verify that a revision has exactly the declared base and head parents.

    Resolve ``base_ref``, ``head_ref``, and ``revision`` with
    ``resolve_git_commit``, then run the shell-free command ``git show -s
    --format=%P <merged>`` with ``root`` as its working directory. The command
    has no timeout. Decode successful parent output as strict ASCII, strip
    surrounding whitespace, split on whitespace, and require the resulting
    sequence to equal ``(base_sha, head_sha)`` exactly. This enforces exactly
    two parents in the declared order. The command helper captures output and
    translates startup and nonzero-exit failures.

    Args:
        root: Repository directory used as Git's working directory.
        base_ref: Git revision expression for the expected first parent. It
            must be non-empty, must not begin with ``-``, and must resolve to a
            commit.
        head_ref: Git revision expression for the expected second parent. It
            must be non-empty, must not begin with ``-``, and must resolve to a
            commit.
        revision: Git revision expression for the merge result. It must be
            non-empty, must not begin with ``-``, and must resolve to a commit.

    Returns:
        The resolved 40-character lowercase hexadecimal merge-result SHA when
        its parent sequence is exactly ``(base_sha, head_sha)``.

    Raises:
        CIPolicyError: If any revision is empty or option-shaped, cannot be
            resolved, Git cannot start or exits unsuccessfully, or the observed
            parent sequence is not exactly the declared two-parent sequence.
        ValueError: If any revision contains an embedded NUL and
            ``subprocess.run`` rejects the command argument before Git starts.
        UnicodeDecodeError: If successful revision or parent output is not
            valid ASCII.
    """
    return CIRunner(root).verify_git_merge_parents(
        base_ref=base_ref, head_ref=head_ref, revision=revision
    )


def _query_bazel_labels(root: Path, expression: str) -> tuple[str, ...]:
    """Query Bazel for labels and return unique labels in lexical order.

    The expression is passed as one argument to ``bazel query`` with
    ``--output=label`` and ``root`` as the working directory. The command is
    executed without a shell. Bazel's UTF-8 output is split into lines; only
    empty lines are ignored, surrounding whitespace is retained, duplicate
    output lines are removed, and the remaining lines are sorted with Python's
    ordinary string ordering. This helper does not validate label syntax.

    Args:
        root: Repository directory in which Bazel evaluates the query.
        expression: Bazel query expression passed unchanged as one argv item.

    Returns:
        A tuple of unique, non-empty output lines sorted in ascending order.

    Raises:
        CIPolicyError: If Bazel cannot start or exits unsuccessfully; the
            command boundary supplies the translated diagnostic.
        UnicodeDecodeError: If successful Bazel output is not valid UTF-8.
    """
    payload = _run_command_and_capture_output(
        ["bazel", "query", expression, "--output=label"], root=root
    )
    return tuple(sorted({line for line in payload.decode("utf-8").splitlines() if line}))


def select_affected_targets(root: Path, *, base_ref: str, head_ref: str) -> AffectedSelection:
    """Select Bazel owners and reverse dependencies for changed paths.

    The repository CI policy is validated before the Git comparison. The
    comparison resolves ``base_ref`` and ``head_ref`` to commits and returns
    normalized changed paths. The function then always queries ``//...`` as
    Bazel XML, decodes that output as UTF-8, and derives the direct source
    owners. A foundational or unresolved path produces the policy's full-graph
    selection. Whenever selection is marked full or has no owner targets, the
    function returns without reverse-dependency queries; a non-full ownerless
    selection therefore retains its empty target tuples. Otherwise, the
    function queries reverse dependencies for build and test targets, validates
    the returned labels, and attaches sorted unique results. Git and Bazel
    commands run without a shell and their output is captured. The function
    performs no direct repository-file writes; invoked tools may have incidental
    cache effects.

    Args:
        root: Repository directory used for policy validation and Git/Bazel
            working directories.
        base_ref: Non-empty Git revision expression for the comparison base;
            it must not begin with ``-`` and must resolve to a commit.
        head_ref: Non-empty Git revision expression for the comparison head;
            it must not begin with ``-`` and must resolve to a commit.

    Returns:
        An ``AffectedSelection`` containing sorted changed paths, direct owner
        labels, and either attached reverse-dependency targets or the full
        ``//...`` fallback. Empty changes produce no targets and
        ``reason="no_changed_paths"``.

    Raises:
        CIPolicyError: If repository policy, Git comparison, Bazel XML/query
            output, owner selection, or reverse-dependency labels are invalid.
            Git and Bazel startup or nonzero-exit failures are translated by
            the command boundary.
        ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
        EvidenceGovernanceError: If retained repository evidence is invalid.
        ValidationError: If policy model construction rejects a value not
            covered by explicit policy checks.
        OSError: If policy validation or an unhandled filesystem/process
            operation fails.
        UnicodeError: If policy validation or a delegated strict text boundary,
            including Git or Bazel output decoding, encounters invalid text.
        ValueError: If a revision contains an embedded NUL or Git emits a
            bare copy status that reaches the existing score conversion.
    """
    return CIRunner(root).select_affected_targets(base_ref=base_ref, head_ref=head_ref)


def _changed_schema_modules(paths: tuple[str, ...], modules: tuple[str, ...]) -> tuple[str, ...]:
    """Select schema roots touched by a path or one of its descendants.

    A module matches when a path equals the module root or starts with the root
    followed by ``/``. The slash check prevents similarly named sibling roots
    from matching. Input path order and duplicate paths do not affect the
    result. Duplicate module names are collapsed by set construction, and the
    selected roots are returned in lexical order.

    Args:
        paths: Repository-relative paths changed by the governed comparison.
        modules: Repository-relative schema module roots eligible for checking.

    Returns:
        A tuple of selected module roots, unique and sorted lexically. It is
        empty when no supplied path belongs to a supplied module.
    """
    selected = {
        module
        for module in modules
        if any(path == module or path.startswith(f"{module}/") for path in paths)
    }
    return tuple(sorted(selected))


def _check_schema_compatibility(root: Path, *, modules: tuple[str, ...], base: str) -> None:
    """Run ordered Buf lint and conditional breaking checks for schema modules.

    For every module in the supplied tuple, the function first runs visible
    ``bazel run --config=ci @rules_buf_toolchains//:buf -- lint <module>``.
    After lint succeeds, it queries ``git ls-tree -z <base> -- <module>/buf.yaml``
    and runs the visible Buf ``breaking`` command only when that query returns
    non-empty bytes. The query's bytes only decide whether to invoke breaking;
    they do not establish that the baseline path is a regular file. The
    breaking command compares against the exact
    ``.git#ref=<base>,subdir=<module>`` locator. Modules are processed in input
    order, are not deduplicated, and are not validated here; the caller and the
    invoked tools supply any path or revision policy.

    A failure stops the loop immediately, so a failed lint has no corresponding
    baseline query and a failed baseline query has no breaking check. The Buf
    commands leave their output visible; the Git query captures raw bytes only
    to decide whether the baseline file exists.

    Args:
        root: Repository working directory for each Bazel and Git command.
        modules: Schema module identifiers to check, in execution order.
        base: Git revision inserted into the baseline query and Buf comparison
            locator without resolution or normalization by this function.

    Raises:
        CIPolicyError: If any command cannot start or exits unsuccessfully; the
            command helpers translate those failures and preserve startup causes.
    """
    return CIRunner(root)._check_schema_compatibility(modules=modules, base=base)


def _git_worktree_state(root: Path) -> bytes:
    """Capture Git's raw porcelain worktree status for comparison.

    The command uses ``--porcelain=v1`` for a stable machine-readable format,
    ``-z`` for NUL-delimited records, and ``--untracked-files=all`` to ask Git
    to list untracked files individually, subject to Git's ignore rules. The
    payload is returned without decoding, parsing, sorting, or normalization,
    so callers can compare exact status snapshots before and after a command or
    test whether any status bytes are present. It is a status snapshot, not a
    file-content fingerprint.

    Args:
        root: Repository directory whose index and worktree status is inspected.

    Returns:
        Raw bytes from ``git status``; a clean worktree normally produces an
        empty byte string.

    Raises:
        CIPolicyError: If Git cannot start or exits unsuccessfully; the command
            boundary supplies the translated diagnostic.
    """
    return _run_command_and_capture_output(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        root=root,
    )


def _require_clean_hosted_checkout(root: Path, *, environment: str) -> None:
    """Require an empty raw Git status for every environment except ``local``.

    The literal environment value ``local`` bypasses Git entirely, so this
    helper accepts a dirty local worktree and has no filesystem side effects.
    Every other environment invokes ``_git_worktree_state`` and rejects any
    non-empty porcelain status bytes. The check observes Git's tracked and
    untracked status representation, including its ignore-rule behavior; it
    does not hash file contents, inspect ignored files, validate the environment
    token, or establish that a hosted checkout is at a particular revision.

    Args:
        root: Repository directory whose worktree status is inspected for a
            hosted environment.
        environment: Execution environment label. Only an exact ``"local"``
            value selects the bypass; all other values select the clean check.

    Raises:
        CIPolicyError: If a non-local status snapshot contains any bytes, or if
            the Git status command cannot start or exits unsuccessfully.
    """
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
    """Validate event identity, token dimensions, revision and evidence URL.

    ``environment`` and ``target`` must each match the bounded token expression
    (an ASCII alphanumeric first character followed by at most 127 ASCII
    alphanumerics, dots, underscores, or hyphens). ``run_id`` must match the
    lowercase event-identifier expression, whose components are separated by a
    single dot, underscore, colon, or hyphen. ``revision`` must be exactly 40
    lowercase hexadecimal characters. Validation stops at the first failure in
    environment/target order, then run ID, revision, and evidence URL order.

    A non-empty ``evidence_url`` is parsed as a credential-free HTTPS URL: its
    parsed scheme must be ``https``, it must expose a hostname, it may not have
    a username or password, and it may not contain a query or fragment. An
    empty URL is accepted only for the exact ``local`` environment. URL parsing
    errors become ``CIPolicyError`` with the parsing exception as their cause.
    The function does not resolve the host, check certificates or reachability,
    verify retention, normalize the URL, or validate path and port semantics
    beyond the stated checks.

    Args:
        run_id: Program-observation event identifier to validate as a safe token.
        revision: Full lowercase Git commit digest bound to the event.
        evidence_url: Retained HTTPS evidence location, or empty for local use.
        environment: Bounded environment dimension and local/hosted discriminator.
        target: Bounded lane target dimension.

    Raises:
        CIPolicyError: If any token, revision, or evidence requirement fails.
            URL syntax failures preserve the underlying ``ValueError`` cause.
    """
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
    """Construct a validated build or test duration event for one CI phase.

    The phase must be exactly ``build`` or ``test`` and the outcome exactly
    ``failed`` or ``passed``. Context validation then enforces the run ID,
    revision, environment, target, and local-versus-hosted evidence rules. The
    timestamps' ``tzinfo`` values must compare equal to ``datetime.UTC`` and the
    end must be strictly later than the start. Timestamps are retained as
    supplied; this function does not convert zones, round or floor fractional
    seconds, or compute a separate duration number. Downstream observation code
    derives seconds from the interval between the start boundary and end
    boundary.

    The resulting frozen model, whose ``dimensions`` dictionary remains mutable,
    uses schema version 1, an event ID of
    ``continuous-integration.<run_id>.<phase>``, the matching build/test
    duration metric, a ``ci_<phase>_completed`` source event type, the supplied
    revision and evidence URL, and dimensions containing environment, outcome,
    and target. Direct model construction does not repeat these relationships;
    the validation in this builder is the boundary that enforces them.

    Args:
        phase: CI phase name, either ``build`` or ``test``.
        run_id: Safe event identifier used in the event ID and source metadata.
        revision: Full lowercase commit digest measured by the phase.
        evidence_url: Credential-free HTTPS evidence URL, or empty for local use.
        environment: Safe environment dimension and evidence-policy context.
        outcome: Phase result, either ``passed`` or ``failed``.
        target: Safe lane target dimension, such as ``fast`` or ``full``.
        started_at: UTC start boundary retained in the event window.
        ended_at: Strictly later UTC end boundary retained in the event window.

    Returns:
        A schema-version-1 ``CIEvent`` whose fields and dimensions are derived
        from the supplied phase context and timestamps.

    Raises:
        CIPolicyError: If phase or outcome is unsupported, event context is
            invalid, or either timestamp is not UTC or the window is non-positive.
    """
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
    """Serialize a CI event as compact, sorted-key JSON without a newline.

    The model is dumped in JSON mode, then the two window values are explicitly
    rendered with ``datetime.isoformat()`` and a trailing ``+00:00`` replaced by
    ``Z``. All other model values use the model serializer. JSON keys are sorted
    lexically and separators contain no insignificant whitespace. Fractional
    seconds are retained at the precision supplied by ``isoformat``; no rounding
    or flooring is performed, and this helper does not append the JSONL newline
    used by the timed-phase caller.

    Serialization copies the model representation and does not mutate ``event``.
    It does not independently validate the event schema, identity, URL, timezone,
    or positive interval. Consequently, a directly constructed ``CIEvent`` with
    inconsistent relationships is serialized as represented, subject only to
    the model and JSON serializers' own behavior.

    Args:
        event: CI event model to convert to one JSON object string.

    Returns:
        A deterministic compact JSON object with sorted keys and no trailing
        newline.

    Raises:
        TypeError: If JSON serialization encounters a value it cannot encode.
        ValueError: If the model's serialization layer rejects a value.
    """
    serializer: _JsonDumpModel = event
    serialized = serializer.model_dump(mode="json")
    if not _is_object_dict(serialized):
        raise TypeError("CI event serializer did not return an object")
    payload = dict(serialized)
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
    """Execute phase commands in order and emit a duration event in ``finally``.

    ``started_at`` is captured immediately before command execution. Each argv
    command is then passed, in tuple order, to the visible-output command helper
    with ``root`` as its working directory; execution stops at the first error.
    Only a ``CIPolicyError`` from a command marks the outcome ``failed`` and is
    re-raised. Other exception types leave the initial ``passed`` outcome in
    place while still propagating after the final event work succeeds.

    The ``finally`` block captures the end time after command execution and
    clamps it to at least one microsecond after the start, covering a clock that
    has equal or regressed readings. It builds and serializes the event, writes
    one JSON object plus a newline to ``event_stream``, and flushes the stream
    before the active exception can leave the function. Finalization can fail
    before a line is written. The event retains its start and end boundaries;
    downstream observation derives fractional ``total_seconds`` without rounding
    or flooring here.
    Event construction, serialization, writing, and flushing can therefore
    raise or mask the command exception. Invalid event metadata is discovered in
    this final emission path, after the commands have already run.

    The helper does not open or close ``event_stream`` and does not catch errors
    from event I/O. An empty command tuple still emits a passed event with an
    interval of at least one microsecond. Commands after a failure do not run;
    the event is attempted before the error propagates.

    Args:
        commands: Ordered non-shell argv vectors for the phase.
        root: Working directory supplied to every command.
        phase: Build/test phase passed to duration-event construction.
        event_stream: Caller-owned writable text stream receiving one JSONL event.
        run_id: Event identity supplied to duration-event construction.
        revision: Full commit digest measured by this phase.
        evidence_url: Retained HTTPS evidence URL, or empty for local execution.
        environment: Environment dimension and evidence-policy context.
        target: Lane target dimension included in the event.

    Raises:
        CIPolicyError: If a command fails, event metadata is invalid, or event
            serialization/emission surfaces a policy failure. A finalization
            failure may replace the original command failure.
        OSError: If a stream operation raises an operating-system error after
            the command boundary.
        TypeError: If the event serializer or stream rejects its supplied value.
        ValueError: If writing or flushing a closed stream fails, or another
            serializer/stream boundary rejects its value.
    """
    return CIRunner(root)._run_timed_ci_phase(
        commands,
        phase=phase,
        event_stream=event_stream,
        run_id=run_id,
        revision=revision,
        evidence_url=evidence_url,
        environment=environment,
        target=target,
    )


def _open_ci_event_log(root: Path, path: Path, *, event_log_directory: str = "build/ci") -> IO[str]:
    """Open a UTF-8 CI event log after resolving it under the allowed directory.

    Relative ``path`` values are resolved from ``root``; absolute values are
    resolved as supplied. The resulting path must equal or descend from the
    resolved ``root / event_log_directory`` boundary. The boundary is
    configurable and defaults to ``build/ci``; this check follows resolved
    paths, so existing symlinks that resolve outside the boundary are rejected.
    Resolution, containment checking, and opening are separate operations and
    are not atomic; a path can change between those steps. Symlink loops can
    raise ``RuntimeError`` from ``Path.resolve`` on Python 3.12. The function
    does not validate the directory token or require the final path to be a
    regular file before opening it.

    After the containment check, parent directories are created recursively with
    ``exist_ok=True``. The file is opened as UTF-8 text in ``"w"`` mode, which
    creates a missing file and truncates an existing one; it never appends. The
    returned stream is left open for the caller's context manager or explicit
    close. Parent creation can occur before a later open failure, and open or
    mkdir errors are allowed to propagate.

    Args:
        root: Repository root used to resolve relative log paths and the allowed
            event-log directory.
        path: Requested event-log path, relative to ``root`` unless absolute.
        event_log_directory: Repository-local containment directory, defaulting
            to ``"build/ci"``.

    Returns:
        An open writable UTF-8 text stream positioned at the start of the log.

    Raises:
        CIPolicyError: If the resolved path is outside the resolved allowed
            directory. The diagnostic currently names ``build/ci`` even when a
            caller supplies a different boundary.
        OSError: If path resolution, parent creation, or file opening fails.
        RuntimeError: If path resolution encounters a symlink loop.
    """
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
    """Run fast-lane preflight and the selected Bazel build/test commands.

    The repository policy is validated first, then ``event_log`` is resolved
    under the policy's event-log directory. Relative paths are rooted at
    ``root``; parent directories are created and the UTF-8 log is opened in
    ``"w"`` mode, so an existing log is truncated before revision or event
    validation. The log is closed when the lane exits its context.

    The lane resolves the base and head refs and requires the resolved head to
    equal the checked-out ``HEAD``. It validates the fast-lane event context,
    requires a clean Git status for every environment other than the exact
    ``"local"`` value, and runs preflight in this order: generated-artifact
    rejection, secret scanning, changed-schema compatibility, and conditional
    pre-commit (only when paths changed). Pre-commit status is compared before
    and after execution; a detected mutation is rejected and left in place.
    Target selection is then performed with the resolved commits. Build and
    test phases run only when their target tuples are non-empty. A force-full
    selection still runs the ``fast`` lane's ``//...`` build and test phases
    and does not add the full lane's rollback check. Each executed phase uses
    the ``fast`` event target and attempts one JSONL duration event, flushing
    the stream in its ``finally`` path. A command failure stops later commands
    and phases; finalization or log I/O errors can leave a partial or empty log
    and can mask the command failure.

    Args:
        root: Repository directory used for policy validation, path resolution,
            Git/Bazel/pre-commit commands, and the event log.
        base_ref: Non-empty Git revision expression for the comparison base;
            it must not begin with ``-`` and must resolve to a commit.
        head_ref: Non-empty Git revision expression for the comparison head;
            it must not begin with ``-`` and must resolve to the checked-out
            commit.
        event_log: Event-log path, relative to ``root`` unless absolute. Its
            resolved path must equal or descend from the policy event-log
            directory.
        run_id: Lowercase event identifier used for phase duration records.
        evidence_url: Credential-free HTTPS evidence URL, or empty only when
            ``environment`` is exactly ``"local"``.
        environment: Bounded CI environment token. ``"local"`` permits a
            dirty checkout and an empty evidence URL; other values require
            both a clean checkout and an evidence URL.

    Returns:
        The affected selection used for the lane, including its changed paths,
        owner labels, build/test targets, full-fallback flag, and reason.

    Raises:
        CIPolicyError: If policy, revision identity, event context, path
            preflight, schema checks, pre-commit, target selection, phase
            commands, event emission, or event-log containment fails. A phase
            finalization failure can mask a command failure.
        ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
        EvidenceGovernanceError: If retained repository evidence is invalid.
        ValidationError: If policy model construction rejects an uncovered value.
        OSError: If policy validation, event-log I/O, or an unhandled delegated
            filesystem/process operation fails.
        UnicodeError: If policy or delegated strict text boundaries, including
            Git or Bazel output decoding, encounter invalid text.
        RuntimeError: If event-log path resolution encounters a symlink loop.
        TypeError: If delegated event serialization or stream writing rejects
            a value.
        ValueError: If a revision contains an embedded NUL, Git emits a bare
            copy status that reaches score conversion, or delegated event/log
            serialization rejects a value.
    """
    return CIRunner(root).run_affected_ci_lane(
        base_ref=base_ref,
        head_ref=head_ref,
        event_log=event_log,
        run_id=run_id,
        evidence_url=evidence_url,
        environment=environment,
    )


def run_authoritative_full_ci_lane(
    root: Path,
    *,
    base_ref: str,
    event_log: Path,
    run_id: str,
    evidence_url: str,
    environment: str,
) -> None:
    """Run the authoritative full graph, rollback check, and CI preflight.

    The repository policy is validated first, then ``event_log`` is resolved
    under the policy's event-log directory. Relative paths are rooted at
    ``root``; parent directories are created and the UTF-8 log is opened in
    ``"w"`` mode, truncating an existing file before revision or event
    validation. The log is closed when the lane exits its context.

    The lane resolves ``base_ref`` and the checked-out ``HEAD``, validates a
    ``full`` event context, and requires a clean Git status outside the exact
    ``"local"`` environment. It rejects generated artifact prefixes among all
    tracked paths, scans those paths, checks every configured schema module,
    and runs pre-commit with ``--all-files``. It then runs a build phase for
    ``bazel build --config=ci //...`` and a test phase containing the ordered
    commands ``bazel test --config=ci //...`` followed by
    ``make --no-print-directory rollback-check``. Each command uses visible
    output. Each entered phase attempts one JSONL duration event, flushing the
    stream in its ``finally`` path. A failure stops subsequent commands or
    phases; the log may be empty or partial, and event finalization can mask a
    command failure.

    Args:
        root: Repository directory used for policy validation, path resolution,
            Git/Bazel/pre-commit/make commands, and the event log.
        base_ref: Non-empty Git revision expression used as the schema
            comparison baseline; it must not begin with ``-`` and must resolve
            to a commit.
        event_log: Event-log path, relative to ``root`` unless absolute. Its
            resolved path must equal or descend from the policy event-log
            directory.
        run_id: Lowercase event identifier used for phase duration records.
        evidence_url: Credential-free HTTPS evidence URL, or empty only when
            ``environment`` is exactly ``"local"``.
        environment: Bounded CI environment token. ``"local"`` permits a
            dirty checkout and an empty evidence URL; other values require
            both a clean checkout and an evidence URL.

    Returns:
        ``None`` after the authoritative CI lane completes.

    Raises:
        CIPolicyError: If policy, revision or event context, path preflight,
            schema checks, pre-commit, phase commands, event emission, or
            event-log containment fails. A phase finalization failure can mask
            a command failure.
        ChangeRiskPolicyError: If the referenced change-risk policy is invalid.
        EvidenceGovernanceError: If retained repository evidence is invalid.
        ValidationError: If policy model construction rejects an uncovered value.
        OSError: If policy validation, event-log I/O, or an unhandled delegated
            filesystem/process operation fails.
        UnicodeError: If policy or delegated strict text boundaries, including
            Git output decoding, encounter invalid text.
        RuntimeError: If event-log path resolution encounters a symlink loop.
        TypeError: If delegated event serialization or stream writing rejects
            a value.
        ValueError: If ``base_ref`` contains an embedded NUL or delegated
            event/log serialization rejects a value.
    """
    return CIRunner(root).run_authoritative_full_ci_lane(
        base_ref=base_ref,
        event_log=event_log,
        run_id=run_id,
        evidence_url=evidence_url,
        environment=environment,
    )
