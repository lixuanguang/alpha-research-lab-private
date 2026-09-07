"""Regression tests for typed developer-environment contract boundaries."""

from __future__ import annotations

# standard library imports
import shutil
from pathlib import Path

# third party library imports
import pytest
from developer_environment_test import DeveloperEnvironmentContractChecker

REPOSITORY_ROOT: Path = Path(__file__).parents[2]
EXPECTED_GATES: set[str] = {
    "QG01",
    "QG02",
    "QG03",
    "QG04",
    "QG05",
    "QG06",
    "QG09",
    "QG10",
    "QG11",
    "QG12",
    "QG13",
    "QG14",
}


class TestDeveloperEnvironmentContractChecker:
    """Exercise invocation recovery and malformed gate rejection."""

    @staticmethod
    def _passed_gates() -> list[dict[str, str]]:
        """Build the valid gate set used by evidence-boundary probes.

        Returns:
            One passed record for each reviewed evidence gate.
        """
        return [{"gate_id": gate_id, "status": "passed"} for gate_id in EXPECTED_GATES]

    def test_repeated_runs_reset_invocation_findings(self, tmp_path: Path) -> None:
        """Recover from a failed run after restoring one mutated input.

        Args:
            tmp_path: Temporary repository root used to isolate the mutation.
        """
        for relative_path in (
            ".python-version",
            ".bazelversion",
            ".envrc",
            "flake.nix",
            "flake.lock",
            "environments/dev/bootstrap.sh",
            "environments/dev/toolchain.toml",
        ):
            destination = tmp_path / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY_ROOT / relative_path, destination)
        shutil.copytree(
            REPOSITORY_ROOT / "docs/governance/evidence/examples/b03-r2-partial",
            tmp_path / "docs/governance/evidence/examples/b03-r2-partial",
        )
        checker = DeveloperEnvironmentContractChecker(tmp_path)
        python_version = tmp_path / ".python-version"
        original_version = python_version.read_text(encoding="utf-8")
        python_version.write_text("3.12.13\n", encoding="utf-8")

        assert checker.run() == 1
        python_version.write_text(original_version, encoding="utf-8")
        assert checker.run() == 0

    @pytest.mark.parametrize(
        "extra_gate",
        (
            {},
            {"gate_id": 7, "status": "passed"},
            "not-a-table",
            {"gate_id": ["QG99"], "status": "passed"},
        ),
    )
    def test_malformed_extra_gate_fails_closed(self, extra_gate: object) -> None:
        """Reject malformed extra gate records with the applicable-gates error.

        Args:
            extra_gate: Deliberately malformed gate record appended to the
                otherwise valid set.
        """
        checker = DeveloperEnvironmentContractChecker(REPOSITORY_ROOT)

        assert checker._gate_errors([*self._passed_gates(), extra_gate], EXPECTED_GATES) == [
            "evidence must bind the exact applicable R2 gates"
        ]

    def test_valid_gate_set_passes_and_failed_status_is_reported(self) -> None:
        """Accept the reviewed gate set and report a status failure separately."""
        checker = DeveloperEnvironmentContractChecker(REPOSITORY_ROOT)
        gates = self._passed_gates()

        assert checker._gate_errors(gates, EXPECTED_GATES) == []
        gates[0]["status"] = "failed"
        assert checker._gate_errors(gates, EXPECTED_GATES) == [
            "repository-local developer-environment gate evidence must pass"
        ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
