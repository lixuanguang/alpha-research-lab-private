"""Keep the installed experiment package boundary lightweight for retained attempts."""

from __future__ import annotations

# standard library imports
import subprocess
import sys
from pathlib import Path


class TestExperimentImportBoundary:
    """Exercise the core package import in a clean installed interpreter."""

    def test_attempt_store_import_does_not_initialize_optional_integrations(
        self, tmp_path: Path
    ) -> None:
        """Import core records without loading comparison, tracking or pipeline SDKs."""
        script = """
import sys

from research.experiments import AttemptStore, ExperimentSpec, TemporalSplit

assert AttemptStore.__name__ == "AttemptStore"
assert ExperimentSpec.__name__ == "ExperimentSpec"
assert TemporalSplit.__name__ == "TemporalSplit"
optional_modules = {
    name
    for name in sys.modules
    if name == "clearml"
    or name.startswith("clearml.")
    or name == "optuna"
    or name.startswith("optuna.")
    or name == "research.studies"
    or name.startswith("research.studies.")
    or name.startswith("research.experiments.")
    and name.rsplit(".", 1)[-1] not in {"identity", "splits", "store"}
}
assert not optional_modules, sorted(optional_modules)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
