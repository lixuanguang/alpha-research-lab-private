"""Adversarial tests for affected and authoritative full CI policy behavior."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import pytest

from alpha_research.ci_policy import (
    CIPolicyError,
    attach_bazel_reverse_dependencies,
    bazel_source_owners_from_query_xml,
    load_continuous_integration_policy,
    normalize_changed_paths,
    parse_git_name_status,
    resolve_git_commit,
    scan_secret_bytes,
    scan_secret_paths,
    select_bazel_owners_for_changes,
    validate_continuous_integration_repository,
    verify_git_merge_parents,
)
from alpha_research.program_governance import load_observations, load_program
from alpha_research_governance import ci_policy
from alpha_research_governance.ci_policy.policy import (
    _private_key_scanner_dependency_findings,
)
from alpha_research_governance.ci_policy.runner import (
    _build_ci_duration_event,
    _open_ci_event_log,
    _require_clean_hosted_checkout,
    _run_command_and_capture_output,
    _serialize_ci_event,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "ci-policy.toml"
PROGRAM_PATH = REPOSITORY_ROOT / "docs" / "governance" / "program-governance.toml"


def test_repository_ci_policy_is_complete_partial_and_fail_closed() -> None:
    policy = validate_continuous_integration_repository(REPOSITORY_ROOT)

    assert policy.package_status == "partial"
    assert policy.successor_package == "B06"
    assert policy.full_lane_authoritative
    assert policy.require_merged_result_on_pull_request
    assert policy.event_log_directory == "build/ci"
    assert policy.hosted_artifact_retention_days == 30
    assert policy.unknown_path_behavior == "full_lane"
    assert policy.fast_lane_target_status == "pending_owner_approval"
    assert tuple(lane.lane_id for lane in policy.lanes) == ("fast", "full")
    assert policy.lanes[0].authoritative is False
    assert policy.lanes[1].authoritative is True
    assert policy.open_finding_ids == ("B05-F01", "B05-F02", "B05-F03")


def test_name_status_parser_retains_rename_boundaries_and_rejects_invalid_input() -> None:
    changes = parse_git_name_status(
        b"M\0src/current.py\0R100\0src/old.py\0src/new.py\0",
        maximum_changed_files=3,
    )
    assert tuple((item.status, item.path) for item in changes) == (
        ("M", "src/current.py"),
        ("R100", "src/new.py"),
        ("R100", "src/old.py"),
    )

    with pytest.raises(CIPolicyError, match="truncated"):
        parse_git_name_status(b"R100\0src/old.py\0", maximum_changed_files=2)
    with pytest.raises(CIPolicyError, match="repository-relative"):
        normalize_changed_paths((("M", "../outside.py"),))
    with pytest.raises(CIPolicyError, match="unsupported Git change status"):
        normalize_changed_paths((("M100", "src/current.py"),))
    with pytest.raises(CIPolicyError, match="unsupported Git change status"):
        normalize_changed_paths((("R101", "src/current.py"),))
    with pytest.raises(CIPolicyError, match="exceeds limit"):
        parse_git_name_status(b"M\0one.py\0M\0two.py\0", maximum_changed_files=1)


def test_bazel_owner_selection_includes_reverse_dependencies_and_safe_broadening() -> None:
    policy = load_continuous_integration_policy(POLICY_PATH)
    query_xml = """<?xml version="1.0"?>
<query version="2">
  <rule class="py_library" name="//src/example:library">
    <list name="srcs"><label value="//src/example:library.py"/></list>
  </rule>
</query>"""
    owners = bazel_source_owners_from_query_xml(query_xml)
    changes = normalize_changed_paths((("M", "src/example/library.py"),))
    direct = select_bazel_owners_for_changes(changes, owners, policy)
    selected = attach_bazel_reverse_dependencies(
        direct,
        build_targets=("//src/example:library", "//tests/example:test"),
        test_targets=("//tests/example:test",),
    )
    assert selected.owner_targets == ("//src/example:library",)
    assert selected.build_targets == ("//src/example:library", "//tests/example:test")
    assert selected.test_targets == ("//tests/example:test",)

    unowned = select_bazel_owners_for_changes(
        normalize_changed_paths((("A", "new/unowned.py"),)),
        owners,
        policy,
    )
    assert unowned.force_full
    assert unowned.build_targets == ("//...",)
    foundational = select_bazel_owners_for_changes(
        normalize_changed_paths((("M", "MODULE.bazel"),)),
        owners,
        policy,
    )
    assert foundational.reason == "foundational_change"
    assert foundational.force_full

    with pytest.raises(CIPolicyError, match="declarations or entities"):
        bazel_source_owners_from_query_xml("<!DOCTYPE query><query version='2'/>")


@pytest.mark.performance
def test_selection_workload_stays_inside_the_repository_local_budget() -> None:
    policy = load_continuous_integration_policy(POLICY_PATH)
    records = tuple(("M", f"src/example/file_{index}.py") for index in range(1000))
    owners = {path: ("//src/example:library",) for _, path in records}

    started_at = perf_counter()
    selection = select_bazel_owners_for_changes(normalize_changed_paths(records), owners, policy)
    elapsed_ms = (perf_counter() - started_at) * 1000

    assert selection.owner_targets == ("//src/example:library",)
    assert elapsed_ms <= policy.selection_workload_budget_ms


def test_secret_detection_covers_tokens_keys_boundaries_and_safe_errors(tmp_path: Path) -> None:
    assigned = b"api_key=" + b"A" * 24
    github = b"gh" + b"p_" + b"B" * 36
    private_key = b"-----BEGIN " + b"PRIVATE KEY-----"
    assert scan_secret_bytes(assigned) == ("assigned_credential",)
    assert scan_secret_bytes(github) == ("github_token",)
    assert scan_secret_bytes(private_key) == ("private_key",)
    assert scan_secret_bytes(b"API_KEY_ENV=") == ()
    assert scan_secret_bytes(b"FIRST_API_KEY=\nSECOND_PRIVATE_KEY=\n") == ()

    secret = tmp_path / "secret.txt"
    secret.write_bytes(assigned)
    with pytest.raises(CIPolicyError, match="secret pattern"):
        scan_secret_paths(tmp_path, ("secret.txt",), maximum_file_bytes=100)

    oversized = tmp_path / "oversized.txt"
    oversized.write_bytes(b"x" * 101)
    with pytest.raises(CIPolicyError, match="exceeds 100 bytes"):
        scan_secret_paths(tmp_path, ("oversized.txt",), maximum_file_bytes=100)

    symlink = tmp_path / "secret-link.txt"
    symlink.symlink_to(secret)
    with pytest.raises(CIPolicyError, match="non-regular path"):
        scan_secret_paths(tmp_path, ("secret-link.txt",), maximum_file_bytes=100)

    with pytest.raises(CIPolicyError, match="repository-relative"):
        scan_secret_paths(tmp_path, ("../outside.txt",), maximum_file_bytes=100)
    with pytest.raises(CIPolicyError, match="repository-relative"):
        scan_secret_paths(tmp_path, (str(secret),), maximum_file_bytes=100)


def test_ci_duration_event_matches_program_observation_contract_and_local_log_scope_is_bounded(
    tmp_path: Path,
) -> None:
    started_at = datetime(2026, 9, 2, tzinfo=UTC)
    event = _build_ci_duration_event(
        phase="build",
        run_id="run-1",
        revision="1" * 40,
        evidence_url="https://forge.example/runs/run-1",
        environment="ci",
        outcome="passed",
        target="fast",
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=2),
    )
    event_path = tmp_path / "event.jsonl"
    event_path.write_text(_serialize_ci_event(event) + "\n", encoding="utf-8")
    program = load_program(PROGRAM_PATH, repository_root=REPOSITORY_ROOT)
    observations = load_observations(event_path, program=program)
    assert len(observations) == 1
    assert observations[0].event_id == "continuous-integration.run-1.build"
    assert observations[0].duration_seconds == 2

    with pytest.raises(CIPolicyError, match="under build/ci"):
        _open_ci_event_log(
            REPOSITORY_ROOT,
            Path("outside-events.jsonl"),
            event_log_directory=load_continuous_integration_policy(POLICY_PATH).event_log_directory,
        )

    with pytest.raises(CIPolicyError, match="retained HTTPS"):
        _build_ci_duration_event(
            phase="test",
            run_id="run-2",
            revision="2" * 40,
            evidence_url="",
            environment="github",
            outcome="passed",
            target="full",
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=1),
        )
    with pytest.raises(CIPolicyError, match="positive and expressed in UTC"):
        _build_ci_duration_event(
            phase="test",
            run_id="run-2",
            revision="2" * 40,
            evidence_url="",
            environment="local",
            outcome="passed",
            target="full",
            started_at=started_at,
            ended_at=started_at,
        )


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_merged_result_verification_binds_exact_base_and_head_parents(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch", "main")
    _git(repository, "config", "user.email", "ci-policy@example.invalid")
    _git(repository, "config", "user.name", "CI Policy Test")
    tracked = repository / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")

    _git(repository, "switch", "-c", "feature")
    (repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repository, "add", "feature.txt")
    _git(repository, "commit", "-m", "feature")
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "switch", "main")
    _git(repository, "merge", "--no-ff", "feature", "-m", "merge feature")
    merged = _git(repository, "rev-parse", "HEAD")

    assert (
        verify_git_merge_parents(
            repository,
            base_ref=base,
            head_ref=head,
            revision=merged,
        )
        == merged
    )
    _require_clean_hosted_checkout(repository, environment="github_merged_result")
    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(CIPolicyError, match="clean checkout"):
        _require_clean_hosted_checkout(repository, environment="github_merged_result")
    with pytest.raises(CIPolicyError, match="parents do not match"):
        verify_git_merge_parents(
            repository,
            base_ref=base,
            head_ref=base,
            revision=merged,
        )


def test_policy_rejects_status_gate_and_lane_weakening(tmp_path: Path) -> None:
    text = POLICY_PATH.read_text(encoding="utf-8")
    mutations = (
        ('package_status = "partial"', 'package_status = "validated"', "package_status"),
        ('  "QG12",\n', "", "applicable gates"),
        ("authoritative = true", "authoritative = false", "full_lane_authoritative"),
    )
    for old, new, message in mutations:
        path = tmp_path / f"{message.replace(' ', '-')}.toml"
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        with pytest.raises(CIPolicyError, match=message):
            load_continuous_integration_policy(path)


def test_policy_rejects_unsafe_paths_and_dependency_record_drift(tmp_path: Path) -> None:
    policy_text = POLICY_PATH.read_text(encoding="utf-8").replace(
        'schema_module_roots = ["tests/build/fixtures/proto"]',
        'schema_module_roots = ["../outside"]',
    )
    policy_path = tmp_path / "policy.toml"
    policy_path.write_text(policy_text, encoding="utf-8")
    with pytest.raises(CIPolicyError, match="unsafe repository path"):
        load_continuous_integration_policy(policy_path)

    architecture = tmp_path / "docs" / "architecture"
    architecture.mkdir(parents=True)
    dependency_source = REPOSITORY_ROOT / "docs" / "architecture" / "ci-tool-dependencies.toml"
    dependency_text = dependency_source.read_text(encoding="utf-8")
    (architecture / "ci-tool-dependencies.toml").write_text(
        dependency_text.replace('license = "MIT"', 'license = "unknown"'),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    findings = _private_key_scanner_dependency_findings(tmp_path)
    assert "scanner dependency record drifted" in findings
    assert "scanner version or digest is not bound to uv.lock" in findings


def test_command_and_revision_failures_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(CIPolicyError, match="command could not start"):
        _run_command_and_capture_output(
            ["continuous-integration-command-does-not-exist"], root=tmp_path
        )
    with pytest.raises(CIPolicyError, match="non-option Git ref"):
        resolve_git_commit(tmp_path, "--unsafe")


def test_ci_cli_uses_typed_dispatch_and_preserves_domain_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = load_continuous_integration_policy(POLICY_PATH)
    scanned: list[tuple[Path, tuple[str, ...]]] = []
    monkeypatch.setattr(
        ci_policy,
        "validate_continuous_integration_repository",
        lambda _root: policy,
    )
    monkeypatch.setattr(
        ci_policy,
        "_scan_paths_for_secrets",
        lambda root, paths: scanned.append((root, tuple(paths))),
    )
    root_arguments = ["--repository-root", str(tmp_path)]

    assert ci_policy.main(root_arguments) == 0
    assert "CI policy passed for 2 lanes" in capsys.readouterr().out

    assert ci_policy.main([*root_arguments, "scan-secrets", "src/alpha.py", "tests/test.py"]) == 0
    assert scanned == [(tmp_path, ("src/alpha.py", "tests/test.py"))]
    assert "Secret scan passed for 2 governed paths." in capsys.readouterr().out

    assert ci_policy.main([*root_arguments, "scan-secrets"]) == 1
    assert "scan-secrets accepts paths" in capsys.readouterr().err

    assert ci_policy.main([*root_arguments, "select", "--base-ref", "HEAD"]) == 2
    assert "--head-ref" in capsys.readouterr().err

    assert ci_policy.main(["-h"]) == 0
    help_output = capsys.readouterr().out
    assert "scan-secrets" in help_output
    assert "install-completion" not in help_output
