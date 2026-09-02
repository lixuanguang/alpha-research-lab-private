"""Deterministic and adversarial tests for remote-execution controls."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest

from alpha_research_governance.remote_execution import (
    RemoteExecutionError,
    load_policy,
    runner,
    select_shard,
    shard_targets,
    validate_repository,
    validate_trusted_context,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REMOTE_EXECUTION_POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/remote-execution.toml"
RUNNING_UNDER_BAZEL = bool(os.environ.get("TEST_SRCDIR"))


def _copy_remote_execution_policy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "remote-execution.toml"
    path.write_text(REMOTE_EXECUTION_POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace_policy_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.mark.skipif(
    RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
)
def test_repository_contract_is_partial_bounded_and_remote_disabled_by_default() -> None:
    policy = validate_repository(REPOSITORY_ROOT)

    assert policy.package_status == "partial"
    assert policy.successor_package == "B07"
    assert policy.risk_class == "R2"
    assert policy.trust.trusted_contexts == ("github_main_push",)
    assert policy.trust.upload_contexts == policy.trust.trusted_contexts
    assert policy.sharding.shard_count == 2
    assert policy.flakes.normal_test_attempts == 1
    assert policy.local_fallback.remote_cache_disabled
    assert policy.local_fallback.remote_execution_disabled
    assert policy.local_fallback.remote_upload_disabled
    assert policy.open_finding_ids == ("B06-F01", "B06-F02", "B06-F03")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "instance_name = "
            '"alpha-research-lab-private/trusted/'
            'bazel-9.1.0-python-3.12.14-linux-x86_64-v1"',
            'instance_name = "shared/default"',
            "instance name must isolate",
        ),
        ('upload_contexts = ["github_main_push"]', 'upload_contexts = ["developer"]', "uploads"),
        ("verify_downloads = true", "verify_downloads = false", "downloads must be verified"),
        ("remote_retries = 2", "remote_retries = 20", "resource budgets"),
        ("shard_count = 2", "shard_count = 1", "two bounded"),
        ("normal_test_attempts = 1", "normal_test_attempts = 2", "cannot silently pass"),
        ("remote_upload_disabled = true", "remote_upload_disabled = false", "local fallback"),
    ],
)
def test_poisoning_flake_budget_and_fallback_mutations_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = _copy_remote_execution_policy_fixture(tmp_path)
    _replace_policy_text(path, old, new)

    with pytest.raises(RemoteExecutionError, match=message):
        load_policy(path)


def test_unknown_and_malformed_policy_fields_fail_closed(tmp_path: Path) -> None:
    unknown = _copy_remote_execution_policy_fixture(tmp_path)
    unknown.write_text(unknown.read_text(encoding="utf-8") + "\nunknown = true\n", encoding="utf-8")
    with pytest.raises(RemoteExecutionError, match="missing or unknown fields"):
        load_policy(unknown)

    malformed = tmp_path / "malformed.toml"
    malformed.write_text("schema_version = [\n", encoding="utf-8")
    with pytest.raises(RemoteExecutionError, match="invalid TOML"):
        load_policy(malformed)


def test_quarantine_records_require_owner_reason_label_and_bounded_expiry(tmp_path: Path) -> None:
    path = _copy_remote_execution_policy_fixture(tmp_path)
    _replace_policy_text(
        path,
        "quarantines = []",
        """[[flakes.quarantines]]
target = "//tests/example:flaky_test"
owner_role = "platform_ci"
reason = "Investigate nondeterministic fixture ordering"
expires_on = 2026-09-10""",
    )
    policy = load_policy(path)
    assert policy.flakes.quarantines[0].owner_role == "platform_ci"

    _replace_policy_text(path, "expires_on = 2026-09-10", "expires_on = 2026-10-01")
    with pytest.raises(RemoteExecutionError, match="expire within"):
        load_policy(path)


def test_shards_are_order_independent_complete_disjoint_and_seeded() -> None:
    targets = tuple(f"//tests/example:test_{index}" for index in range(80))
    forward = shard_targets(targets, shard_count=2, seed="seed-a", maximum_targets=100)
    reverse = shard_targets(reversed(targets), shard_count=2, seed="seed-a", maximum_targets=100)
    changed_seed = shard_targets(targets, shard_count=2, seed="seed-b", maximum_targets=100)

    assert forward == reverse
    assert set(forward[0].targets).isdisjoint(forward[1].targets)
    assert set(forward[0].targets) | set(forward[1].targets) == set(targets)
    assert forward != changed_seed


def test_empty_shards_are_valid_but_bad_target_sets_and_indices_block() -> None:
    shards = shard_targets(("//tests/example:only",), shard_count=2, seed="seed", maximum_targets=2)
    assert sum(not shard.targets for shard in shards) == 1
    assert shard_targets(("//:root_test",), shard_count=1, seed="seed", maximum_targets=1)[
        0
    ].targets == ("//:root_test",)

    with pytest.raises(RemoteExecutionError, match="unique"):
        shard_targets(("//a:test", "//a:test"), shard_count=2, seed="seed", maximum_targets=2)
    with pytest.raises(RemoteExecutionError, match="invalid Bazel"):
        shard_targets(("not-a-label",), shard_count=2, seed="seed", maximum_targets=2)
    with pytest.raises(RemoteExecutionError, match="exceeds"):
        shard_targets(("//a:a", "//b:b"), shard_count=2, seed="seed", maximum_targets=1)
    with pytest.raises(RemoteExecutionError, match="half-open"):
        select_shard(("//a:test",), shard_index=2, shard_count=2, seed="seed", maximum_targets=2)


def test_trusted_context_rejects_untrusted_missing_secret_wrong_revision_and_dirty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
    clean_environment = {
        "CI": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "BUILDBUDDY_API_KEY": "synthetic-test-key",
    }
    monkeypatch.setattr(
        runner,
        "_run_git_command",
        lambda _root, *arguments: "a" * 40 if arguments == ("rev-parse", "HEAD") else "",
    )
    validate_trusted_context(policy, "github_main_push", clean_environment, REPOSITORY_ROOT)

    for context, mutation, message in (
        ("github_pull_request", {}, "not permitted"),
        ("github_main_push", {"BUILDBUDDY_API_KEY": ""}, "credential"),
        ("github_main_push", {"GITHUB_SHA": "b" * 40}, "GITHUB_SHA"),
    ):
        environment = clean_environment | mutation
        with pytest.raises(RemoteExecutionError, match=message):
            validate_trusted_context(policy, context, environment, REPOSITORY_ROOT)

    monkeypatch.setattr(
        runner,
        "_run_git_command",
        lambda _root, *arguments: "a" * 40 if arguments == ("rev-parse", "HEAD") else "M dirty.py",
    )
    with pytest.raises(RemoteExecutionError, match="clean checkout"):
        validate_trusted_context(policy, "github_main_push", clean_environment, REPOSITORY_ROOT)


def test_authenticated_runner_hides_secret_from_argv_and_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
    observed_arguments: list[str] = []
    observed_environment: dict[str, str] = {}
    observed_credential_text = ""
    observed_credential_mode = 0

    def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal observed_credential_mode, observed_credential_text
        observed_arguments.extend(arguments)
        observed_environment.update(cast(dict[str, str], kwargs["env"]))
        credential_path = Path(arguments[1].removeprefix("--bazelrc="))
        observed_credential_text = credential_path.read_text(encoding="utf-8")
        observed_credential_mode = stat.S_IMODE(credential_path.stat().st_mode)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(
        "alpha_research_governance.remote_execution.runner.subprocess.run", fake_run
    )
    monkeypatch.setattr(runner, "_resolve_executable", lambda _name: "/usr/bin/bazel")
    return_code = runner._run_authenticated_bazel(
        policy,
        repository_root=REPOSITORY_ROOT,
        environment={"BUILDBUDDY_API_KEY": "synthetic-test-key", "SAFE": "value"},
        command="build",
        targets=("//:docs_bundle",),
    )

    assert return_code == 0
    assert "synthetic-test-key" not in " ".join(observed_arguments)
    assert "BUILDBUDDY_API_KEY" not in observed_environment
    assert observed_credential_text.endswith("=synthetic-test-key\n")
    assert observed_credential_mode == 0o600


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
