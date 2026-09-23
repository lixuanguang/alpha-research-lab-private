"""Keep the installed experiment package boundary lightweight for retained attempts."""

from __future__ import annotations

# standard library imports
import subprocess
import sys
from pathlib import Path

# third party library imports
import pytest


class TestExperimentImportBoundary:
    """Exercise the core package import in a clean installed interpreter."""

    def test_attempt_store_import_does_not_initialize_optional_integrations(
        self, tmp_path: Path
    ) -> None:
        """Import core records without loading comparison, tracking or pipeline SDKs."""
        script = """
import importlib.abc
import sys

class RejectOperationalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in {
            "QuantLib",
            "exchange_calendars",
            "numpy",
            "pandas",
        }:
            raise AssertionError(f"Operational dependency imported: {fullname}")
        return None

sys.meta_path.insert(0, RejectOperationalDependencies())

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

    @pytest.mark.parametrize(
        "statement",
        (
            "from research.results import FeatureStudyResult",
            "from research.studies import BookReport, ClearMLDestination, ComparisonStudy",
            "from research.exploration import ResearchSelection, DuckDBFeatureAnalysis, "
            "PolarsFeatureAnalysis",
            "from applications.backtest import run_books",
            "from applications.explore import inspect_eda",
        ),
    )
    def test_local_apis_do_not_import_unused_sdks(self, tmp_path: Path, statement: str) -> None:
        """Keep local records and workflows usable when optional SDK imports are unavailable."""
        script = """
import importlib.abc
import sys

class RejectUnusedSDKs(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"clearml", "optuna", "duckdb", "polars"}:
            raise AssertionError(f"Unused SDK imported: {fullname}")
        return None

sys.meta_path.insert(0, RejectUnusedSDKs())
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script + statement],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
