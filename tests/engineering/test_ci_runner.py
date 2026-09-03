"""Direct orchestration tests for affected and authoritative CI lanes."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import IO

import pytest

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
    policy = load_continuous_integration_policy(POLICY_PATH)
    base = "b" * 40
    revision = "a" * 40
    calls: list[tuple[object, ...]] = []

    def fake_resolve_git_commit(_root: Path, reference: str) -> str:
        return {"base": base, "HEAD": revision}[reference]

    def record_generated_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
        calls.append(("generated", paths, prefixes))

    def record_secret_scan(_root: Path, paths: tuple[str, ...]) -> None:
        calls.append(("secrets", paths))

    def record_schema_check(_root: Path, *, modules: tuple[str, ...], base: str) -> None:
        calls.append(("schemas", modules, base))

    def record_pre_commit(_root: Path, arguments: list[str]) -> None:
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
        calls.append(("changes", base_ref, head_ref))
        return base, head, (change,)

    def record_generated_paths(paths: tuple[str, ...], *, prefixes: tuple[str, ...]) -> None:
        calls.append(("generated", paths, prefixes))

    def record_schema_check(_root: Path, *, modules: tuple[str, ...], base: str) -> None:
        calls.append(("schemas", modules, base))

    def record_selection(_root: Path, *, base_ref: str, head_ref: str) -> AffectedSelection:
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
    observed_commands: list[tuple[str, ...]] = []

    def fail_second_command(command: list[str], *, root: Path) -> None:
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
