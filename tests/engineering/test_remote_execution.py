"""Deterministic and adversarial tests for remote-execution controls."""

from __future__ import annotations

# standard library imports
import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import TypeGuard

# third party library imports
import pytest

# project library imports
import alpha_research_governance.remote_execution as remote_execution
from alpha_research_governance.remote_execution import (
    RemoteExecutionError,
    load_policy,
    runner,
    select_shard,
    shard_targets,
    validate_repository,
    validate_trusted_context,
)
from alpha_research_governance.remote_execution.models import (
    QuarantineEntry,
    RemoteExecutionPolicy,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REMOTE_EXECUTION_POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/remote-execution.toml"
RUNNING_UNDER_BAZEL = bool(os.environ.get("TEST_SRCDIR"))


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, str]]:
    """Narrow a subprocess environment to string keys and values."""
    return (
        isinstance(value, Mapping)
        and all(isinstance(key, str) for key in value)
        and all(isinstance(item, str) for item in value.values())
    )


def _copy_remote_execution_policy_fixture(tmp_path: Path) -> Path:
    """Copy the checked-in remote policy to an isolated file for mutation tests.

    Args:
        tmp_path: Existing temporary directory in which to write the policy copy.

    Returns:
        The temporary ``remote-execution.toml`` path, overwritten if already present.

    Raises:
        OSError: The source policy cannot be read or its temporary copy cannot be written.
    """
    path = tmp_path / "remote-execution.toml"
    path.write_text(REMOTE_EXECUTION_POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace_policy_text(path: Path, old: str, new: str) -> None:
    """Replace one expected policy fragment in place without changing later occurrences.

    Args:
        path: Temporary UTF-8 policy file to read and overwrite.
        old: Exact fragment required to exist before the mutation.
        new: Replacement for the first occurrence of ``old``.

    Raises:
        AssertionError: The expected fragment is absent from the fixture.
        OSError: The policy file cannot be read or rewritten.
    """
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class TestRemoteExecutionPolicy:
    """Validate remote execution policy boundaries and quarantine records."""

    @pytest.mark.skipif(
        RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
    )
    def test_repository_contract_is_partial_bounded_and_remote_disabled_by_default(self) -> None:
        """Retain trusted-main-only writes, single test attempts and a remote-disabled fallback."""
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
            (
                'upload_contexts = ["github_main_push"]',
                'upload_contexts = ["developer"]',
                "uploads",
            ),
            ("verify_downloads = true", "verify_downloads = false", "downloads must be verified"),
            ("remote_retries = 2", "remote_retries = 20", "resource budgets"),
            ("shard_count = 2", "shard_count = 1", "two bounded"),
            ("normal_test_attempts = 1", "normal_test_attempts = 2", "cannot silently pass"),
            ("remote_upload_disabled = true", "remote_upload_disabled = false", "local fallback"),
        ],
    )
    def test_poisoning_flake_budget_and_fallback_mutations_fail_closed(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Reject mutations weakening cache isolation, budgets or local fallback."""
        path = _copy_remote_execution_policy_fixture(tmp_path)
        _replace_policy_text(path, old, new)

        with pytest.raises(RemoteExecutionError, match=message):
            load_policy(path)

    def test_unknown_and_malformed_policy_fields_fail_closed(self, tmp_path: Path) -> None:
        """Report domain errors for an unknown policy field and malformed TOML."""
        unknown = _copy_remote_execution_policy_fixture(tmp_path)
        unknown.write_text(
            unknown.read_text(encoding="utf-8") + "\nunknown = true\n", encoding="utf-8"
        )
        with pytest.raises(RemoteExecutionError, match="missing or unknown fields"):
            load_policy(unknown)

        malformed = tmp_path / "malformed.toml"
        malformed.write_text("schema_version = [\n", encoding="utf-8")
        with pytest.raises(RemoteExecutionError, match="invalid TOML"):
            load_policy(malformed)

    def test_quarantine_records_require_owner_reason_label_and_bounded_expiry(
        self, tmp_path: Path
    ) -> None:
        """Load an attributed quarantine and reject extending its expiry beyond the policy bound."""
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


class TestRemoteExecutionSharding:
    """Validate deterministic complete and bounded shard selection."""

    def test_shards_are_order_independent_complete_disjoint_and_seeded(self) -> None:
        """Partition every target exactly once, independent of input order and sensitive to seed."""
        targets = tuple(f"//tests/example:test_{index}" for index in range(80))
        forward = shard_targets(targets, shard_count=2, seed="seed-a", maximum_targets=100)
        reverse = shard_targets(
            reversed(targets), shard_count=2, seed="seed-a", maximum_targets=100
        )
        changed_seed = shard_targets(targets, shard_count=2, seed="seed-b", maximum_targets=100)

        assert forward == reverse
        assert set(forward[0].targets).isdisjoint(forward[1].targets)
        assert set(forward[0].targets) | set(forward[1].targets) == set(targets)
        assert forward != changed_seed

    def test_empty_shards_are_valid_but_bad_target_sets_and_indices_block(self) -> None:
        """Allow empty shards and root labels while rejecting invalid partitions and indices."""
        shards = shard_targets(
            ("//tests/example:only",), shard_count=2, seed="seed", maximum_targets=2
        )
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
            select_shard(
                ("//a:test",), shard_index=2, shard_count=2, seed="seed", maximum_targets=2
            )


class TestRemoteExecutionTrust:
    """Validate trusted context and credential isolation boundaries."""

    def test_trusted_context_rejects_untrusted_missing_secret_wrong_revision_and_dirty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Require trusted context, a credential, matching HEAD and a clean checkout together."""
        policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
        clean_environment = {
            "CI": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": "a" * 40,
            "BUILDBUDDY_API_KEY": "synthetic-test-key",
        }

        def clean_git_command(_root: Path, *arguments: str) -> str:
            """Return a clean synthetic HEAD for the trusted-context probe.

            Args:
                _root: Repository path supplied to the Git command; unused by this fake.
                *arguments: Git subcommand and operands requested by the probe.

            Returns:
                The expected commit for ``rev-parse HEAD`` or an empty clean status.
            """
            return "a" * 40 if arguments == ("rev-parse", "HEAD") else ""

        monkeypatch.setattr(
            runner,
            "_run_git_command",
            clean_git_command,
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

        def dirty_git_command(_root: Path, *arguments: str) -> str:
            """Return a synthetic dirty status for the checkout rejection probe.

            Args:
                _root: Repository path supplied to the Git command; unused by this fake.
                *arguments: Git subcommand and operands requested by the probe.

            Returns:
                The expected commit for ``rev-parse HEAD`` or a dirty status line.
            """
            return "a" * 40 if arguments == ("rev-parse", "HEAD") else "M dirty.py"

        monkeypatch.setattr(runner, "_run_git_command", dirty_git_command)
        with pytest.raises(RemoteExecutionError, match="clean checkout"):
            validate_trusted_context(policy, "github_main_push", clean_environment, REPOSITORY_ROOT)

    def test_authenticated_runner_hides_secret_from_argv_and_child_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass the synthetic key through a mode-0600 rc file, keeping it out of argv and env."""
        policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
        observed_arguments: list[str] = []
        observed_environment: dict[str, str] = {}
        observed_credential_text = ""
        observed_credential_mode = 0

        def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Inspect invocation and credential-file state without launching a process.

            Args:
                arguments: Subprocess argv containing the temporary ``--bazelrc`` path.
                **kwargs: Subprocess options; ``env`` supplies the child environment to record.

            Returns:
                A successful completion for the supplied argument vector.

            Raises:
                OSError: The temporary credential file cannot be read or inspected.
            """
            nonlocal observed_credential_mode, observed_credential_text, observed_environment
            observed_arguments.extend(arguments)
            raw_environment = kwargs["env"]
            assert _is_string_mapping(raw_environment)
            observed_environment = dict(raw_environment)
            credential_path = Path(arguments[1].removeprefix("--bazelrc="))
            observed_credential_text = credential_path.read_text(encoding="utf-8")
            observed_credential_mode = stat.S_IMODE(credential_path.stat().st_mode)
            return subprocess.CompletedProcess(arguments, 0)

        monkeypatch.setattr(
            "alpha_research_governance.remote_execution.runner.subprocess.run", fake_run
        )

        def resolve_bazel(_name: str) -> str:
            """Return the fixture executable path without consulting the host.

            Args:
                _name: Executable name requested by the runner; unused by this fake.

            Returns:
                A stable synthetic Bazel executable path.
            """
            return "/usr/bin/bazel"

        monkeypatch.setattr(runner, "_resolve_executable", resolve_bazel)
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


class TestRemoteExecutionRunner:
    """Validate remote runner orchestration and empty-shard behavior."""

    def test_remote_entrypoints_validate_select_and_propagate_results(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Preserve trust, query and execute order with shard and exit-status checks."""
        policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
        environment = {"BUILDBUDDY_API_KEY": "synthetic-test-key"}
        test_targets = ("//tests:alpha", "//tests:beta", "//tests:gamma")
        expected_shard = select_shard(
            test_targets,
            shard_index=1,
            shard_count=policy.sharding.shard_count,
            seed=policy.sharding.seed,
            maximum_targets=policy.sharding.maximum_targets,
        )
        quarantine = QuarantineEntry(
            target="//tests:quarantined",
            owner_role="platform_ci",
            reason="Exercise the diagnostic quarantine boundary",
            expires_on=date(2026, 9, 10),
        )
        quarantine_flakes_update: dict[str, object] = {"quarantines": (quarantine,)}
        quarantine_flakes = policy.flakes.model_copy(update=quarantine_flakes_update)
        quarantine_policy_update: dict[str, object] = {"flakes": quarantine_flakes}
        quarantine_policy = policy.model_copy(update=quarantine_policy_update)
        calls: list[tuple[object, ...]] = []

        def record_trust(
            _policy: RemoteExecutionPolicy,
            context: str,
            active_environment: Mapping[str, str],
            repository_root: Path,
        ) -> None:
            """Snapshot the trust-check invocation without validating credentials or Git state.

            Args:
                _policy: Loaded policy supplied for callback compatibility; unused here.
                context: Requested remote execution context.
                active_environment: Environment copied into the recorded call.
                repository_root: Repository path whose trust boundary would be checked.
            """
            calls.append(("trust", context, dict(active_environment), repository_root))

        def record_query(repository_root: Path) -> tuple[str, ...]:
            """Record the graph query and supply the fixture's complete test-target tuple.

            Args:
                repository_root: Repository path from which the test graph would be queried.

            Returns:
                The three fixture test labels without invoking Bazel.
            """
            calls.append(("query", repository_root))
            return test_targets

        def record_authenticated_bazel(
            _policy: RemoteExecutionPolicy,
            *,
            repository_root: Path,
            environment: Mapping[str, str],
            command: str,
            targets: Sequence[str],
            extra_arguments: Sequence[str] = (),
        ) -> int:
            """Snapshot authenticated invocation inputs and simulate command-specific exit codes.

            Args:
                _policy: Loaded policy supplied for callback compatibility; unused here.
                repository_root: Execution directory to record.
                environment: Environment copied into the recorded call.
                command: Either ``build`` or ``test``; selects the simulated status.
                targets: Target labels copied to a tuple for later comparison.
                extra_arguments: Additional Bazel options, empty outside quarantine diagnostics.

            Returns:
                Status 17 for a build or 23 for a test, without running Bazel.

            Raises:
                KeyError: The runner supplies an unexpected command.
            """
            calls.append(
                (
                    "execute",
                    command,
                    tuple(targets),
                    tuple(extra_arguments),
                    dict(environment),
                    repository_root,
                )
            )
            return {"build": 17, "test": 23}[command]

        monkeypatch.setattr(runner, "validate_trusted_context", record_trust)
        monkeypatch.setattr(runner, "query_test_targets", record_query)
        monkeypatch.setattr(runner, "_run_authenticated_bazel", record_authenticated_bazel)

        assert (
            runner.run_remote_build(
                policy,
                context="github_main_push",
                repository_root=REPOSITORY_ROOT,
                environment=environment,
            )
            == 17
        )
        assert (
            runner.run_remote_test_shard(
                policy,
                context="github_main_push",
                shard_index=1,
                repository_root=REPOSITORY_ROOT,
                environment=environment,
            )
            == 23
        )
        assert (
            runner.run_quarantine_diagnostics(
                policy,
                context="github_main_push",
                repository_root=REPOSITORY_ROOT,
                environment=environment,
            )
            == 0
        )
        assert (
            runner.run_quarantine_diagnostics(
                quarantine_policy,
                context="github_main_push",
                repository_root=REPOSITORY_ROOT,
                environment=environment,
            )
            == 23
        )

        assert calls == [
            ("trust", "github_main_push", environment, REPOSITORY_ROOT),
            (
                "execute",
                "build",
                policy.local_fallback.build_targets,
                (),
                environment,
                REPOSITORY_ROOT,
            ),
            ("trust", "github_main_push", environment, REPOSITORY_ROOT),
            ("query", REPOSITORY_ROOT),
            (
                "execute",
                "test",
                expected_shard.targets,
                (),
                environment,
                REPOSITORY_ROOT,
            ),
            ("trust", "github_main_push", environment, REPOSITORY_ROOT),
            (
                "execute",
                "test",
                (quarantine.target,),
                ("--config=remote-quarantine-diagnostics",),
                environment,
                REPOSITORY_ROOT,
            ),
        ]

    def test_empty_remote_shard_validates_context_without_invoking_bazel(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Validate trust and query the graph before returning success for an empty shard."""
        policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
        target = "//tests:only"
        shards = shard_targets(
            (target,),
            shard_count=policy.sharding.shard_count,
            seed=policy.sharding.seed,
            maximum_targets=policy.sharding.maximum_targets,
        )
        empty_index = next(shard.index for shard in shards if not shard.targets)
        calls: list[str] = []

        def record_trust(*_args: object, **_kwargs: object) -> None:
            """Record trust validation without touching credentials or Git.

            Args:
                *_args: Positional trust-validation inputs, ignored by this recorder.
                **_kwargs: Keyword trust-validation inputs, ignored by this recorder.
            """
            calls.append("trust")

        monkeypatch.setattr(runner, "validate_trusted_context", record_trust)

        def record_query(_root: Path) -> tuple[str, ...]:
            """Record the graph query and return the target used to locate an empty shard.

            Args:
                _root: Repository path supplied by the runner; unused by this fake.

            Returns:
                A one-element tuple containing the fixture's only test target.
            """
            calls.append("query")
            return (target,)

        monkeypatch.setattr(runner, "query_test_targets", record_query)

        def reject_execution(*_args: object, **_kwargs: object) -> int:
            """Fail the test if an empty shard reaches authenticated execution.

            Args:
                *_args: Positional invocation inputs; ignored because every call is forbidden.
                **_kwargs: Keyword invocation inputs; ignored because every call is forbidden.

            Returns:
                No status is returned; the integer annotation matches the replaced callback.

            Raises:
                AssertionError: Always, because an empty shard must not execute Bazel.
            """
            raise AssertionError("an empty shard must not invoke Bazel")

        monkeypatch.setattr(runner, "_run_authenticated_bazel", reject_execution)

        assert (
            runner.run_remote_test_shard(
                policy,
                context="github_main_push",
                shard_index=empty_index,
                repository_root=REPOSITORY_ROOT,
                environment={"BUILDBUDDY_API_KEY": "synthetic-test-key"},
            )
            == 0
        )
        assert calls == ["trust", "query"]


class TestRemoteExecutionCLI:
    """Validate command dispatch, usage errors and exit status propagation."""

    def test_remote_cli_dispatches_commands_and_preserves_exit_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Forward typed remote commands and retain runner, domain, usage and help exit codes."""
        policy = load_policy(REMOTE_EXECUTION_POLICY_PATH)
        calls: list[tuple[object, ...]] = []

        def record_build(
            _policy: RemoteExecutionPolicy, *, context: str, repository_root: Path
        ) -> int:
            """Record CLI build dispatch and simulate a nonzero runner status.

            Args:
                _policy: Validated policy passed by the CLI; unused by this recorder.
                context: Context parsed from the build command.
                repository_root: Repository root parsed from the CLI options.

            Returns:
                Status 17, allowing the test to detect replacement with a generic status.
            """
            calls.append(("build", context, repository_root))
            return 17

        def record_test(
            _policy: RemoteExecutionPolicy,
            *,
            context: str,
            shard_index: int,
            repository_root: Path,
        ) -> int:
            """Record CLI test dispatch, including the parsed integer shard index.

            Args:
                _policy: Validated policy passed by the CLI; unused by this recorder.
                context: Context parsed from the test command.
                shard_index: Zero-based integer index parsed from the shard option.
                repository_root: Repository root parsed from the CLI options.

            Returns:
                Status 23 to verify propagation of the test runner's result.
            """
            calls.append(("test", context, shard_index, repository_root))
            return 23

        def record_quarantine(
            _policy: RemoteExecutionPolicy, *, context: str, repository_root: Path
        ) -> int:
            """Record CLI quarantine dispatch and supply a distinct diagnostic status.

            Args:
                _policy: Validated policy passed by the CLI; unused by this recorder.
                context: Context parsed from the quarantine command.
                repository_root: Repository root parsed from the CLI options.

            Returns:
                Status 29 to verify propagation of the diagnostic runner's result.
            """
            calls.append(("quarantine", context, repository_root))
            return 29

        def record_policy(_root: Path) -> RemoteExecutionPolicy:
            """Return the loaded policy for CLI dispatch validation.

            Args:
                _root: Repository path supplied by the CLI; unused by this fake.

            Returns:
                The loaded remote-execution policy used by command dispatch.
            """
            return policy

        monkeypatch.setattr(remote_execution, "validate_repository", record_policy)
        monkeypatch.setattr(remote_execution, "run_remote_build", record_build)
        monkeypatch.setattr(remote_execution, "run_remote_test_shard", record_test)
        monkeypatch.setattr(remote_execution, "run_quarantine_diagnostics", record_quarantine)

        root_arguments = ["--repository-root", str(tmp_path)]
        assert remote_execution.main(root_arguments) == 0
        assert "Remote execution policy passed" in capsys.readouterr().out
        assert remote_execution.main([*root_arguments, "build", "--context", "trusted"]) == 17
        assert (
            remote_execution.main(
                [*root_arguments, "test", "--context", "trusted", "--shard-index", "1"]
            )
            == 23
        )
        assert remote_execution.main([*root_arguments, "quarantine", "--context", "trusted"]) == 29
        assert calls == [
            ("build", "trusted", tmp_path),
            ("test", "trusted", 1, tmp_path),
            ("quarantine", "trusted", tmp_path),
        ]

        def fail_build(
            _policy: RemoteExecutionPolicy, *, context: str, repository_root: Path
        ) -> int:
            """Raise a contextual domain error for the CLI's error-rendering assertion.

            Args:
                _policy: Validated policy passed by the CLI; unused by this failure fake.
                context: Requested context included in the diagnostic message.
                repository_root: Repository path whose basename is included in the diagnostic.

            Returns:
                No status is returned; the integer annotation matches the replaced callback.

            Raises:
                RemoteExecutionError: Always, with the supplied context and repository basename.
            """
            raise RemoteExecutionError([f"blocked {context} at {repository_root.name}"])

        monkeypatch.setattr(remote_execution, "run_remote_build", fail_build)
        assert remote_execution.main([*root_arguments, "build", "--context", "untrusted"]) == 1
        assert "blocked untrusted" in capsys.readouterr().err

        assert remote_execution.main([*root_arguments, "build"]) == 2
        assert "--context" in capsys.readouterr().err

        assert remote_execution.main(["-h"]) == 0
        help_output = capsys.readouterr().out
        assert "quarantine" in help_output
        assert "install-completion" not in help_output


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
