"""Verify extension identity, registered providers and refusal of altered installs."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
from importlib.metadata import distribution
from pathlib import Path
from typing import Literal

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from research.experiments import CandidateArtifact, CandidateComponent
from runtime import InstalledExtensions

ComponentRole = Literal["feature", "transform", "estimator", "policy", "metric", "chart"]


class TestInstalledExtensions:
    """Load the installed engineering extension and refuse altered or foreign ones."""

    extension = "engineering-candidates"

    @staticmethod
    def _record(path: Path, content: bytes) -> str:
        """Describe one file as a wheel RECORD row."""
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        return f"{path.as_posix()},sha256={digest},{len(content)}\n"

    @classmethod
    def _distribution(cls, root: Path, *, entry_points: str) -> Path:
        """Install one minimal distribution with a recorded module under ``root``."""
        package, metadata = root / "fakeext", root / "fakeext-0.1.0.dist-info"
        package.mkdir(parents=True)
        metadata.mkdir()
        module = b'"""Provide nothing."""\n'
        (package / "__init__.py").write_bytes(module)
        (metadata / "METADATA").write_text("Metadata-Version: 2.4\nName: fakeext\nVersion: 0.1.0\n")
        (metadata / "entry_points.txt").write_text(entry_points)
        record = cls._record(Path("fakeext/__init__.py"), module)
        record += "fakeext-0.1.0.dist-info/RECORD,,\n"
        (metadata / "RECORD").write_text(record)
        return package / "__init__.py"

    def test_installed_identity_pins_record_and_provider_factories(self) -> None:
        """Identity is the RECORD digest; every factory carries it as its implementation."""
        extensions = InstalledExtensions()
        identity = extensions.identity(self.extension)
        record = distribution(self.extension).read_text("RECORD")
        assert record is not None
        assert identity == hashlib.sha256(record.encode()).hexdigest()
        assert extensions.identity(self.extension) == identity
        components = extensions.components(self.extension)
        parameters = CandidateArtifact(name="parameters", sha256="0" * 64)
        roles: tuple[tuple[ComponentRole, str], ...] = (
            ("feature", "smoothed-imbalance"),
            ("policy", "imbalance-target"),
            ("metric", "fold-net"),
            ("chart", "fold-net-path"),
        )
        selected = tuple(
            CandidateComponent(
                role=role,
                factory_key=key,
                identity=key,
                implementation_sha256=identity,
                parameters=parameters,
            )
            for role, key in roles
        )
        components.admit(selected)
        with pytest.raises(ValueError, match="implementation differs"):
            components.admit((replace(selected[0], implementation_sha256="f" * 64),))

    def test_altered_file_platform_name_and_absent_distribution_are_refused(
        self, tmp_path: Path
    ) -> None:
        """A recorded file changed after install, or a non-extension name, loads nothing."""
        module = self._distribution(
            tmp_path,
            entry_points="[alpha_research.candidate_components]\nfake = fakeext:Missing\n",
        )
        extensions = InstalledExtensions(search_paths=(tmp_path,))
        assert len(extensions.identity("fakeext")) == 64
        module.write_bytes(b'"""Provide something else."""\n')
        with pytest.raises(ValueError, match="differs from its record"):
            extensions.identity("fakeext")
        with pytest.raises(ValueError, match="platform"):
            InstalledExtensions().identity("alpha-research-execution")
        with pytest.raises(ValueError, match="not installed"):
            InstalledExtensions().components("absent-extension")

    def test_extension_must_register_exactly_one_provider(self, tmp_path: Path) -> None:
        """A distribution without one registered component provider is not an extension."""
        self._distribution(tmp_path, entry_points="[console_scripts]\nfake = fakeext:main\n")
        with pytest.raises(ValueError, match="exactly one component provider"):
            InstalledExtensions(search_paths=(tmp_path,)).components("fakeext")
