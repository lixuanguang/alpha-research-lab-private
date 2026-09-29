"""Verify functional import boundaries, command ownership and installed identity scope."""

from __future__ import annotations

# standard library imports
from importlib.machinery import ModuleSpec
from importlib.metadata import PathDistribution
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.source_layout import SourceLayoutChecker
from runtime import ImplementationIdentity, InstalledIdentity, RuntimeFiles

_ROOT = Path(__file__).parents[2]


class TestFunctionalOwnership:
    """Reject representative direction, API and entrypoint violations without importing code."""

    @pytest.mark.parametrize(
        ("module", "source", "message"),
        [
            (
                "market_data.storage.raw",
                "from applications.acquire import acquire",
                "application workflows",
            ),
            (
                "applications.collect.workflow",
                "from applications.acquire import acquire",
                "application workflows",
            ),
            (
                "market_data.contracts.inputs",
                "from market_data.storage import RawStore",
                "neutral contracts",
            ),
            (
                "market_data.validation.quality",
                "from market_data.adapters.sources import SourceAdapters",
                "injected source",
            ),
            (
                "market_data.replay.events",
                "from market_data.adapters.venues.okx import OKXBook",
                "injected source",
            ),
            ("configuration.capture", "from runtime import InstalledIdentity", "configuration"),
            ("simulation.economics", "from accounting.ledger import Ledger", "public API"),
            (
                "risk.spot",
                "from applications.backtest import run_backtest",
                "application workflows",
            ),
            ("strategies.rules", "from simulation import _Internal", "private import"),
            (
                "financial_units.models",
                "from reference_data.instruments.models import InstrumentId",
                "public API",
            ),
            (
                "market_data.replay.events",
                "from market_data.query import _Partition",
                "private import",
            ),
            ("market_data.replay.events", "from ..query.asof import _Partition", "private import"),
            ("serialization.codec", "def main(): pass", "entry functions"),
            ("applications.collect.alternate", "def replay_main(): pass", "entry functions"),
            ("serialization.__main__", "pass", "independently runnable"),
            ("market_data.storage.raw", 'if __name__ == "__main__": pass', "installed application"),
            ("applications.explore.workflow", "import alpha_research", "retired"),
        ],
    )
    def test_rejects_forbidden_boundaries(self, module: str, source: str, message: str) -> None:
        """Cover concrete bypasses instead of asserting the implementation's source text."""
        assert any(message in issue for issue in SourceLayoutChecker.scan(module, source))

    @pytest.mark.parametrize(
        ("module", "source"),
        [
            ("market_data.replay.books", "from market_data.replay.events import _EventSteps"),
            ("market_data.query.reader", "from .asof import _Partition"),
            ("market_data.storage.raw", "from market_data.contracts import RequestBinding"),
            (
                "reference_data.instruments.models",
                "from reference_data._validation import validation_error",
            ),
            (
                "applications.acquire.workflow",
                "from market_data.adapters.sources import SourceAdapters\n"
                "def main(): pass\ndef acquire(): pass",
            ),
        ],
    )
    def test_accepts_owned_internals_and_real_composition(self, module: str, source: str) -> None:
        """Permit useful same-owner implementation access and multiple genuine orchestrators."""
        assert SourceLayoutChecker.scan(module, source) == ()

    def test_grouping_parent_and_explicit_api(self) -> None:
        """Keep grouping imports inert and require curated library exports."""
        assert SourceLayoutChecker.scan("market_data", '"""Group packages."""', is_api=True) == ()
        assert SourceLayoutChecker.scan(
            "market_data", "from market_data.storage import RawStore", is_api=True
        )
        assert (
            SourceLayoutChecker.scan(
                "serialization",
                'from serialization.codec import DomainCodec\n__all__ = ["DomainCodec"]',
                is_api=True,
            )
            == ()
        )
        assert SourceLayoutChecker.scan("serialization", "pass", is_api=True)
        assert SourceLayoutChecker.scan("serialization", '__all__ = ["Missing"]', is_api=True)

    def test_lazy_public_export_requires_typed_exact_mapping(self) -> None:
        """Permit a deferred owner import only when its runtime and type bindings agree."""
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from risk.admission import AdmissionDecision\n"
            "def __getattr__(name: str) -> object:\n"
            "    if name in {'AdmissionDecision'}:\n"
            "        from risk import admission\n"
            "        exports: dict[str, object] = "
            "{'AdmissionDecision': admission.AdmissionDecision}\n"
            "        return exports[name]\n"
            "    raise AttributeError(name)\n"
            "__all__ = ['AdmissionDecision']\n"
        )
        assert SourceLayoutChecker.scan("risk", source, is_api=True) == ()
        mismapped = source.replace("admission.AdmissionDecision", "admission.OtherDecision")
        assert any(
            "public export AdmissionDecision is not bound" in issue
            for issue in SourceLayoutChecker.scan("risk", mismapped, is_api=True)
        )
        untyped = source.replace(
            "if TYPE_CHECKING:\n    from risk.admission import AdmissionDecision\n", ""
        )
        assert any(
            "public export AdmissionDecision is not bound" in issue
            for issue in SourceLayoutChecker.scan("risk", untyped, is_api=True)
        )
        unguarded = source.replace("'AdmissionDecision'}", "'OtherDecision'}")
        assert any(
            "public export AdmissionDecision is not bound" in issue
            for issue in SourceLayoutChecker.scan("risk", unguarded, is_api=True)
        )

    def test_duplicate_entrypoints_and_metadata(self, tmp_path: Path) -> None:
        """Detect separate mains in one application and non-API command bindings."""
        app = tmp_path / "src/applications/example"
        app.mkdir(parents=True)
        (app / "__init__.py").write_text(
            'from applications.example.workflow import main\n__all__ = ["main"]\n'
        )
        (app / "workflow.py").write_text("def main(): pass\n")
        project = tmp_path / "pyproject.toml"
        project.write_text('[project.scripts]\nexample = "applications.example:main"\n')
        assert SourceLayoutChecker.findings(tmp_path) == ()
        (app / "second.py").write_text("def main(): pass\n")
        assert any("at most one" in issue for issue in SourceLayoutChecker.findings(tmp_path))
        project.write_text('[project.scripts]\nexample = "applications.example.workflow:main"\n')
        assert any("command must bind" in issue for issue in SourceLayoutChecker.findings(tmp_path))

    def test_submodule_import_cannot_bypass_public_api(self, tmp_path: Path) -> None:
        """Reject implicit submodule imports that Python permits absent a curated export."""
        library = tmp_path / "src/financial_units"
        library.mkdir(parents=True)
        (library / "__init__.py").write_text('__all__ = ["Currency"]\n')
        (library / "models.py").write_text("class Currency: pass\n")
        consumer = tmp_path / "src/serialization"
        consumer.mkdir()
        (consumer / "__init__.py").write_text('__all__ = ["Codec"]\n')
        (consumer / "codec.py").write_text("from financial_units import models\n")
        (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\n')
        assert any(
            "not in the owner's public API" in issue
            for issue in SourceLayoutChecker.findings(tmp_path)
        )
        assert SourceLayoutChecker.scan("financial_units.models", '__all__ = ["Currency"]')

    def test_current_runtime_obeys_ownership(self) -> None:
        """Check the actual cross-package graph and the four installed command bindings."""
        assert SourceLayoutChecker.findings(_ROOT) == ()


class TestInstalledRuntimeIdentity:
    """Prove input coverage and the distinct capture and resolved-job identity contracts."""

    @staticmethod
    def _installation(root: Path) -> PathDistribution:
        """Build a minimal real distribution inventory for identity fault injection."""
        package = root / "financial_units"
        package.mkdir()
        names = ("__init__.py", "models.py", "py.typed", "default_currencies.json")
        for name in names:
            (package / name).write_text("{}" if name.endswith("json") else "")
        metadata = root / "fixture.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text("Name: alpha-research-lab\nVersion: 0.1.0\n")
        (metadata / "RECORD").write_text("".join(f"financial_units/{name},,\n" for name in names))
        return PathDistribution(metadata)

    def test_exact_scope_resources_shadowing_and_missing_files(self, tmp_path: Path) -> None:
        """Check resource scope and reject missing or shadowed inputs."""
        installed = self._installation(tmp_path)
        origin = tmp_path / "financial_units/__init__.py"
        spec = ModuleSpec("financial_units", loader=None, origin=str(origin))
        with (
            patch("runtime.identity.distribution", return_value=installed),
            patch.object(RuntimeFiles, "roots", ("financial_units",)),
            patch("runtime.identity.find_spec", return_value=spec),
        ):
            source_id, resolved_id = InstalledIdentity.sha256(), ImplementationIdentity.sha256()
            (tmp_path / "unrelated.py").write_text("secret = 'never inspected'")
            (tmp_path / "financial_units/neighbor.py").write_text("unowned = True")
            assert InstalledIdentity.sha256() == source_id
            assert ImplementationIdentity.sha256() == resolved_id
            resource = tmp_path / "financial_units/default_currencies.json"
            resource.write_text('{"changed": true}')
            assert InstalledIdentity.sha256() == source_id
            assert ImplementationIdentity.sha256() != resolved_id
            module = tmp_path / "financial_units/models.py"
            module.write_text("changed = True")
            assert InstalledIdentity.sha256() != source_id
            with patch(
                "runtime.identity.find_spec",
                return_value=ModuleSpec(
                    "financial_units", loader=None, origin=str(tmp_path / "other.py")
                ),
            ):
                with pytest.raises(ValueError, match="shadowed"):
                    RuntimeFiles.inputs()
            module.unlink()
            with pytest.raises(ValueError, match="missing runtime"):
                RuntimeFiles.inputs()

    def test_installed_files_cover_all_shipped_roots_and_assets(self) -> None:
        """Identify every functional root without scanning neighboring site-packages."""
        inputs = dict(RuntimeFiles.inputs())
        assert {name.split("/")[0] for name in inputs} == set(RuntimeFiles.roots)
        assert "financial_units/default_currencies.json" in inputs
        for root in RuntimeFiles.roots:
            assert f"{root}/py.typed" in inputs
        assert InstalledIdentity.sha256() != ImplementationIdentity.sha256()
