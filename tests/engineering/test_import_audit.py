"""Audit external extension sources for supported platform imports and admissible metadata."""

from __future__ import annotations

# standard library imports
import shutil
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain.builds import ExternalExtension
from alpha_research_governance.engineering_standards import ImportAudit, main

_TEMPLATE = Path("extensions/engineering-candidates")
_SHIPPED = ExternalExtension.shipped(Path.cwd())


class TestImportAudit:
    """Classify imports of installed owners without importing them."""

    @staticmethod
    def _tree(root: Path, source: str) -> Path:
        """Write one module of an external package."""
        package = root / "src" / "qr_signals"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(source, encoding="utf-8")
        return root

    def test_unsupported_imports_and_path_mutation_are_findings(self, tmp_path: Path) -> None:
        """Private, deep and unexported imports and sys.path changes are reported."""
        root = self._tree(
            tmp_path,
            "import sys\n"
            "import json\n"
            "from research.observations import NumericField\n"
            "from research.observations.live import LiveBookDecisionSource\n"
            "from runtime import _hidden, NotExported\n"
            "import serialization.codec\n"
            "sys.path.insert(0, '/elsewhere')\n",
        )
        audit = ImportAudit()
        findings = audit.audit(root)
        assert [(item.line, item.rule, item.symbol) for item in findings] == [
            (4, "deep-import", "research.observations.live.LiveBookDecisionSource"),
            (5, "private-import", "runtime._hidden"),
            (5, "unexported-import", "runtime.NotExported"),
            (6, "deep-import", "serialization.codec"),
            (7, "path-mutation", "sys.path"),
        ]
        assert all("(" in line for line in audit.report(findings))
        assert main(["import-audit", str(root)]) == 1

    def test_supported_imports_and_the_reference_extension_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Owner APIs pass; the maintained extension template is itself clean."""
        root = self._tree(
            tmp_path, "from runtime import ExtensionFactories\nimport research.observations\n"
        )
        assert ImportAudit().audit(root) == ()
        assert main(["import-audit", str(_TEMPLATE.resolve())]) == 0
        assert "Import audit passed" in capsys.readouterr().out
        assert main(["import-audit"]) == 2
        assert main(["import-audit", str(tmp_path / "absent")]) == 1

    def test_a_release_refuses_modules_it_does_not_ship(self, tmp_path: Path) -> None:
        """An import of an unshipped module is reported, also inside a function."""
        root = self._tree(
            tmp_path,
            "from research.reports import FoldSummary\n"
            "from research.studies import StudyResult\n"
            "def evaluate() -> None:\n"
            "    from research.studies import DecisionStudy\n",
        )
        findings = ImportAudit(shipped=_SHIPPED).audit(root)
        assert [(item.line, item.rule, item.symbol) for item in findings] == [
            (2, "unshipped-import", "research.studies.StudyResult"),
            (4, "unshipped-import", "research.studies.DecisionStudy"),
        ]
        assert ImportAudit().audit(root) == ()


class TestExternalExtension:
    """Admit only provider-only, source-free, cleanly importing external projects."""

    @staticmethod
    def _copy(root: Path, name: str = "qr-signals") -> Path:
        """Copy the reference extension under a new project name outside the repository."""
        project = root / name
        shutil.copytree(_TEMPLATE, project)
        for cache in tuple(project.rglob("__pycache__")):
            shutil.rmtree(cache)
        text = (project / "pyproject.toml").read_text(encoding="utf-8")
        (project / "pyproject.toml").write_text(
            text.replace('name = "engineering-candidates"', f'name = "{name}"', 1),
            encoding="utf-8",
        )
        return project

    def test_external_project_is_read_with_its_exact_source(self, tmp_path: Path) -> None:
        """The project's metadata and every source file are retained."""
        extension = ExternalExtension.read(self._copy(tmp_path), _SHIPPED)
        assert extension.name == "qr-signals"
        names = {name for name, _ in extension.files}
        assert "pyproject.toml" in names
        assert "src/engineering_candidates/components.py" in names

    @pytest.mark.parametrize(
        ("change", "source"),
        [
            ('name = "qr-signals"', 'name = "alpha-research-qr"'),
            ("[project.entry-points", '[project.scripts]\nrun = "x:y"\n\n[project.entry-points'),
            ("[tool.uv]", '[tool.uv.sources]\nnumpy = { path = "/x" }\n\n[tool.uv]'),
        ],
    )
    def test_inadmissible_metadata_is_refused(
        self, tmp_path: Path, change: str, source: str
    ) -> None:
        """Platform names, scripts and uv sources are refused."""
        project = self._copy(tmp_path)
        text = (project / "pyproject.toml").read_text(encoding="utf-8")
        assert change in text
        (project / "pyproject.toml").write_text(text.replace(change, source, 1), encoding="utf-8")
        with pytest.raises(ValueError, match="not admissible"):
            ExternalExtension.read(project, _SHIPPED)

    def test_unsupported_imports_and_relative_paths_are_refused(self, tmp_path: Path) -> None:
        """The import audit runs before any build; a relative path is refused."""
        project = self._copy(tmp_path)
        module = project / "src/engineering_candidates/components.py"
        module.write_text(
            "from runtime.extensions import InstalledExtensions\n"
            + module.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="deep-import"):
            ExternalExtension.read(project, _SHIPPED)
        module.write_text(
            "from research.studies import StudyResult\n"
            + module.read_text(encoding="utf-8").split("\n", 1)[1],
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unshipped-import"):
            ExternalExtension.read(project, _SHIPPED)
        with pytest.raises(ValueError, match="absolute project"):
            ExternalExtension.read(Path("qr-signals"), _SHIPPED)
