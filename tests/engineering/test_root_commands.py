"""Contract tests for the direct uv source and wheel-smoke command interface."""

from __future__ import annotations

# standard library imports
import os
import subprocess
from pathlib import Path
from shlex import quote

# third party library imports
import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]


class TestIndependentLockfiles:
    """Require every independently installed environment to have a current lock."""

    @pytest.mark.parametrize(
        "project",
        (
            "packages/collector",
            "packages/execution",
            "packages/paper-services",
            "configs/development/research-worker",
            "configs/development/clearml/worker",
        ),
    )
    def test_stale_environment_lock_stops_source_checks(self, tmp_path: Path, project: str) -> None:
        """Propagate a worker or operating lock failure before running source tooling."""
        log = tmp_path / "uv.log"
        fake_uv = tmp_path / "uv"
        fake_uv.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {quote(str(log))}\n"
            f'if [ "$3" = --project ] && [ "$4" = {quote(project)} ]; then exit 19; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        fake_uv.chmod(0o755)

        result = TestRootCommands.run_make(f"UV={fake_uv}", "source-check")

        assert result.returncode != 0
        assert "Error 19" in result.stderr
        invocations = log.read_text(encoding="utf-8").splitlines()
        assert invocations[-1] == f"lock --check --project {project}"
        assert not any(invocation.startswith("run ") for invocation in invocations)


class TestRootCommands:
    """Keep the root Make targets, hosted workflow and build entry points authoritative."""

    @staticmethod
    def run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Run Make from the repository root while capturing output and status.

        Args:
            *arguments: Make options, targets and variable assignments passed without a shell.

        Returns:
            Completed process with captured text stdout and stderr; nonzero exit status does not
            raise because callers assert it explicitly.
        """
        # A caller's own make (for example ``make -k source-check``) exports its flags;
        # inheriting -k would make the nested make continue past the failure under test.
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES")
        }
        return subprocess.run(
            ["make", "--no-print-directory", *arguments],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_authoritative_check_has_one_direct_uv_source_path_and_wheel_smoke(self) -> None:
        """Require frozen source checks, security checks, one pytest path and installed smoke."""
        result = self.run_make("-n", "check")

        assert result.returncode == 0, result.stderr
        commands = result.stdout.splitlines()
        assert commands.count("uv lock --check") == 1
        assert (
            commands.count(
                "uv run --frozen ruff check src tests tools/governance/src tools/typing/stubs "
                "examples extensions"
            )
            == 1
        )
        assert commands.count("uv run --frozen alpha-governance-ci scan-secrets --all") == 1
        assert commands.count("uv run --frozen --no-editable pytest -q -m 'not performance'") == 1
        assert (
            commands.count("uv run --frozen python -m alpha_research_governance.wheel_smoke") == 1
        )
        assert any("mypy.stubtest" in command for command in commands)
        assert any("bandit" in command for command in commands)

    def test_hosted_workflow_has_one_source_job_and_cross_platform_smoke(self) -> None:
        """Require direct CI steps, merged-result identity and cross-platform smoke."""
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        secrets = (
            REPOSITORY_ROOT
            / "tools"
            / "governance"
            / "src"
            / "alpha_research_governance"
            / "ci_policy"
            / "secrets.py"
        ).read_text(encoding="utf-8")

        assert "name: Source validation" in workflow
        assert "name: Authoritative merged-result full lane" in workflow
        assert "runs-on: macos-14" in workflow
        assert workflow.count("make source-check") == 1
        assert workflow.count("make wheel-smoke") == 2
        assert "merged result parents do not match" in workflow
        assert "checked-out commit does not match the merged result" in workflow
        assert "detect-private-key" in secrets
        assert "alpha-governance-ci scan-secrets --all" in makefile
        assert "dependency-audit:" in makefile
        assert "bandit" in makefile

    def test_build_produces_the_runtime_wheel(self) -> None:
        """Build the runtime wheel using the frozen project environment."""
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

        assert "build:" in makefile
        result = self.run_make("-n", "build")
        assert result.returncode == 0, result.stderr
        assert "tools/governance --out-dir" not in result.stdout
        assert (
            "$(UV) run --frozen --no-editable uv build --no-build-isolation --wheel "
            "--no-sources . --out-dir dist" in makefile
        )

    def test_source_check_propagates_a_required_phase_failure(self, tmp_path: Path) -> None:
        """Stop after a failed direct uv phase and preserve its nonzero status."""
        log = tmp_path / "uv.log"
        fake_uv = tmp_path / "uv"
        fake_uv.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {log}\n"
            'if [ "$1" = run ] && [ "$3" = ruff ] && [ "$4" = check ]; then\n'
            "  exit 17\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_uv.chmod(0o755)

        result = self.run_make(f"UV={fake_uv}", "source-check")

        assert result.returncode != 0
        assert "Error 17" in result.stderr
        invocations = log.read_text(encoding="utf-8").splitlines()
        assert invocations[:7] == [
            "lock --check",
            "lock --check --project packages/collector",
            "lock --check --project packages/execution",
            "lock --check --project packages/paper-services",
            "lock --check --project configs/development/research-worker",
            "lock --check --project configs/development/clearml/worker",
            "run --frozen ruff check src tests tools/governance/src tools/typing/stubs examples "
            "extensions",
        ]
        assert not any("format" in invocation or "mypy" in invocation for invocation in invocations)

    def test_test_target_passes_marker_expression_as_one_argument(self, tmp_path: Path) -> None:
        """Keep the pytest marker expression intact at Make's process boundary."""
        log = tmp_path / "uv-args.log"
        fake_uv = tmp_path / "uv"
        fake_uv.write_text(
            f"#!/bin/sh\nfor arg do printf '<%s>\\n' \"$arg\" >> {log}; done\n",
            encoding="utf-8",
        )
        fake_uv.chmod(0o755)

        result = self.run_make(f"UV={fake_uv}", "test")

        assert result.returncode == 0, result.stderr
        assert log.read_text(encoding="utf-8").splitlines() == [
            "<run>",
            "<--frozen>",
            "<--no-editable>",
            "<pytest>",
            "<-q>",
            "<-m>",
            "<not performance>",
        ]
