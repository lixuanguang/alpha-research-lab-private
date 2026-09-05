"""Direct orchestration tests for affected and authoritative CI lanes."""

from __future__ import annotations

# standard library imports
import json
from io import StringIO
from pathlib import Path
from typing import IO

# third party library imports
import pytest

# project library imports
from alpha_research_governance.ci_policy import runner as ci_runner
from alpha_research_governance.ci_policy.models import (
    AffectedSelection,
    ChangedPath,
    CIPolicyError,
)
from alpha_research_governance.ci_policy.policy import load_continuous_integration_policy

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "ci-policy.toml"


def test_authoritative_lane_runs_every_control_and_complete_test_path_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require full-lane preflight, whole-graph build/test and rollback checks in order."""
    policy = load_continuous_integration_policy(POLICY_PATH)
    base = "b" * 40
    revision = "a" * 40
    calls: list[tuple[object, ...]] = []

    def fake_resolve_git_commit(_root: Path, reference: str) -> str:
        """Resolve the fixture's two revision names without invoking Git.

        Args:
            _root: Repository path supplied by the runner; unused by this fake.
            reference: Either ``base`` or ``HEAD`` from the full-lane workflow.

        Returns:
            The fixture commit assigned to the requested reference.

        Raises:
            KeyError: The runner requests an unexpected reference.
        """
        return {"base": base, "HEAD": revision}[reference]

    def record_generated_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
        """Record the generated-artifact preflight inputs without inspecting files.

        Args:
            paths: Tracked paths submitted for inspection.
            prefixes: Policy directory prefixes forbidden in tracked changes.
        """
        calls.append(("generated", paths, prefixes))

    def record_secret_scan(_root: Path, paths: tuple[str, ...]) -> None:
        """Record secret-scan order and scope without reading file contents.

        Args:
            _root: Repository path supplied by the runner; unused by this recorder.
            paths: Tracked paths submitted for scanning.
        """
        calls.append(("secrets", paths))

    def record_schema_check(_root: Path, *, modules: tuple[str, ...], base: str) -> None:
        """Record schema-compatibility scope and its resolved comparison revision.

        Args:
            _root: Repository path supplied by the runner; unused by this recorder.
            modules: Protobuf module roots selected for compatibility checks.
            base: Resolved commit against which schemas would be compared.
        """
        calls.append(("schemas", modules, base))

    def record_pre_commit(_root: Path, arguments: list[str]) -> None:
        """Snapshot pre-commit arguments for the ordered full-lane assertion.

        Args:
            _root: Repository path supplied by the runner; unused by this recorder.
            arguments: File-scope arguments passed to pre-commit.
        """
        calls.append(("pre-commit", tuple(arguments)))

    def record_timed_phase(
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
        """Record phase commands and event context without running commands or writing events.

        Args:
            commands: Ordered argument vectors, copied to tuples for later comparison.
            root: Execution directory recorded with the phase.
            phase: Build or test phase identifier.
            event_stream: Open log stream whose writability is recorded.
            run_id: Run identity to which the phase would be attributed.
            revision: Resolved source commit measured by the phase.
            evidence_url: Retained evidence link, empty for this local fixture.
            environment: Execution environment label passed through by the runner.
            target: Lane label used in duration-event dimensions.
        """
        calls.append(
            (
                "phase",
                phase,
                tuple(tuple(command) for command in commands),
                root,
                event_stream.writable(),
                run_id,
                revision,
                evidence_url,
                environment,
                target,
            )
        )

    monkeypatch.setattr(
        ci_runner, "validate_continuous_integration_repository", lambda _root: policy
    )
    monkeypatch.setattr(ci_runner, "resolve_git_commit", fake_resolve_git_commit)
    monkeypatch.setattr(ci_runner, "_git_tracked_paths", lambda _root: ("tracked.py",))
    monkeypatch.setattr(ci_runner, "_reject_generated_artifact_paths", record_generated_paths)
    monkeypatch.setattr(ci_runner, "_scan_paths_for_secrets", record_secret_scan)
    monkeypatch.setattr(ci_runner, "_check_schema_compatibility", record_schema_check)
    monkeypatch.setattr(ci_runner, "_run_pre_commit_without_mutation", record_pre_commit)
    monkeypatch.setattr(ci_runner, "_run_timed_ci_phase", record_timed_phase)

    ci_runner.run_authoritative_full_ci_lane(
        tmp_path,
        base_ref="base",
        event_log=Path("build/ci/events.jsonl"),
        run_id="full-run",
        evidence_url="",
        environment="local",
    )

    assert calls == [
        ("generated", ("tracked.py",), policy.generated_artifact_prefixes),
        ("secrets", ("tracked.py",)),
        ("schemas", policy.schema_module_roots, base),
        ("pre-commit", ("--all-files",)),
        (
            "phase",
            "build",
            (("bazel", "build", "--config=ci", "//..."),),
            tmp_path,
            True,
            "full-run",
            revision,
            "",
            "local",
            "full",
        ),
        (
            "phase",
            "test",
            (
                ("bazel", "test", "--config=ci", "//..."),
                ("make", "--no-print-directory", "rollback-check"),
            ),
            tmp_path,
            True,
            "full-run",
            revision,
            "",
            "local",
            "full",
        ),
    ]


def test_affected_lane_executes_forced_full_selection_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broaden a foundational diff to whole-graph commands after affected-lane preflight."""
    policy = load_continuous_integration_policy(POLICY_PATH)
    base = "b" * 40
    head = "a" * 40
    change = ChangedPath(status="M", path="MODULE.bazel")
    selection = AffectedSelection(
        changed_paths=(change.path,),
        owner_targets=(),
        build_targets=("//...",),
        test_targets=("//...",),
        force_full=True,
        reason="foundational_change",
    )
    calls: list[tuple[object, ...]] = []

    def record_changed_paths(
        _root: Path, base_ref: str, head_ref: str
    ) -> tuple[str, str, tuple[ChangedPath, ...]]:
        """Record requested refs and return the fixture's resolved foundational change.

        Args:
            _root: Repository path supplied by the runner; unused by this fake.
            base_ref: Requested comparison-base reference.
            head_ref: Requested change-head reference.

        Returns:
            Base commit, head commit and the single modified ``MODULE.bazel`` record.
        """
        calls.append(("changes", base_ref, head_ref))
        return base, head, (change,)

    def record_generated_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
        """Record the changed-path generated-artifact preflight without inspecting files.

        Args:
            paths: Changed repository paths submitted for inspection.
            prefixes: Policy directory prefixes forbidden in tracked changes.
        """
        calls.append(("generated", paths, prefixes))

    def record_schema_check(_root: Path, *, modules: tuple[str, ...], base: str) -> None:
        """Record the affected schema roots and resolved comparison commit.

        Args:
            _root: Repository path supplied by the runner; unused by this recorder.
            modules: Changed Protobuf module roots, empty for the foundational fixture.
            base: Resolved comparison-base commit.
        """
        calls.append(("schemas", modules, base))

    def record_selection(_root: Path, *, base_ref: str, head_ref: str) -> AffectedSelection:
        """Record selection refs and supply a preconstructed whole-graph fallback.

        Args:
            _root: Repository path supplied by the runner; unused by this fake.
            base_ref: Resolved comparison-base commit supplied to selection.
            head_ref: Resolved change-head commit supplied to selection.

        Returns:
            The fixture's full fallback selection, without copying or querying Bazel.
        """
        calls.append(("selection", base_ref, head_ref))
        return selection

    def record_timed_phase(
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
        """Record affected-lane phase order, command vectors and target label only.

        Args:
            commands: Ordered argument vectors, copied to tuples for later comparison.
            root: Execution directory supplied by the runner; unused by this recorder.
            phase: Build or test phase identifier to record.
            event_stream: Runner-owned event log; this recorder does not access it.
            run_id: Run identity supplied for callback compatibility; unused here.
            revision: Source commit supplied for callback compatibility; unused here.
            evidence_url: Evidence link supplied for callback compatibility; unused here.
            environment: Environment label supplied for callback compatibility; unused here.
            target: Lane label to retain alongside the phase commands.
        """
        calls.append(("phase", phase, tuple(tuple(command) for command in commands), target))

    monkeypatch.setattr(
        ci_runner, "validate_continuous_integration_repository", lambda _root: policy
    )
    monkeypatch.setattr(ci_runner, "git_changed_paths_between", record_changed_paths)
    monkeypatch.setattr(ci_runner, "resolve_git_commit", lambda _root, _reference: head)
    monkeypatch.setattr(ci_runner, "_reject_generated_artifact_paths", record_generated_paths)
    monkeypatch.setattr(
        ci_runner,
        "_scan_paths_for_secrets",
        lambda _root, paths: calls.append(("secrets", paths)),
    )
    monkeypatch.setattr(ci_runner, "_check_schema_compatibility", record_schema_check)
    monkeypatch.setattr(
        ci_runner,
        "_run_pre_commit_without_mutation",
        lambda _root, arguments: calls.append(("pre-commit", tuple(arguments))),
    )
    monkeypatch.setattr(ci_runner, "select_affected_targets", record_selection)
    monkeypatch.setattr(ci_runner, "_run_timed_ci_phase", record_timed_phase)

    observed = ci_runner.run_affected_ci_lane(
        tmp_path,
        base_ref="base",
        head_ref="head",
        event_log=Path("build/ci/events.jsonl"),
        run_id="fast-run",
        evidence_url="",
        environment="local",
    )

    assert observed == selection
    assert calls == [
        ("changes", "base", "head"),
        ("generated", (change.path,), policy.generated_artifact_prefixes),
        ("secrets", (change.path,)),
        ("schemas", (), base),
        ("pre-commit", ("--from-ref", base, "--to-ref", head)),
        ("selection", base, head),
        ("phase", "build", (("bazel", "build", "--config=ci", "//..."),), "fast"),
        ("phase", "test", (("bazel", "test", "--config=ci", "//..."),), "fast"),
    ]


def test_timed_phase_stops_on_failure_and_emits_a_failed_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Emit the failed test event and propagate the error before a third command runs."""
    observed_commands: list[tuple[str, ...]] = []

    def fail_second_command(command: list[str], *, root: Path) -> None:
        """Record each attempted command and fail on the fixture's second command.

        Args:
            command: Argument vector whose first token selects the simulated failure.
            root: Execution directory, required to equal the test's temporary path.

        Raises:
            AssertionError: The runner supplies an unexpected execution directory.
            CIPolicyError: The command starts with the token ``second``.
        """
        observed_commands.append(tuple(command))
        assert root == tmp_path
        if command[0] == "second":
            raise CIPolicyError(["synthetic phase failure"])

    monkeypatch.setattr(ci_runner, "_run_command_with_visible_output", fail_second_command)
    event_stream = StringIO()

    with pytest.raises(CIPolicyError, match="synthetic phase failure"):
        ci_runner._run_timed_ci_phase(
            (["first"], ["second"], ["unreachable"]),
            root=tmp_path,
            phase="test",
            event_stream=event_stream,
            run_id="run-1",
            revision="a" * 40,
            evidence_url="",
            environment="local",
            target="full",
        )

    assert observed_commands == [("first",), ("second",)]
    event = json.loads(event_stream.getvalue())
    assert event["dimensions"] == {
        "environment": "local",
        "outcome": "failed",
        "target": "full",
    }
    assert event["source_revision"] == "a" * 40


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
