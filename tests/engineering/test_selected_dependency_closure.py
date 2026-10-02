"""Exercise actual wheel closure admission and fail-closed archive inspection."""

from __future__ import annotations

# standard library imports
import base64
import csv
import hashlib
import io
import platform
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
    PythonPackageAdmission,
    WheelOnlyAllowance,
)
from alpha_research_governance.dependency_admission.selected_closure import (
    SelectedClosureAdmission,
    SelectedClosureFacts,
)
from alpha_research_governance.dependency_admission.wheel_archive import WheelArchive
from alpha_research_governance.dependency_admission.wheelhouse import SelectedWheelhouse

# Selected admission refuses every host but its one supported release target, and
# evaluates dependency markers on the real interpreter, so these need that host.
_DARWIN_ARM64_HOST = pytest.mark.skipif(
    sys.platform != "darwin" or platform.machine() != "arm64",
    reason="the selected release target is darwin arm64; admission refuses other hosts",
)


class TestSelectedWheelArchive:
    """Reject installation surfaces and metadata tricks before dependency resolution."""

    @staticmethod
    def _wheel(
        directory: Path,
        name: str = "alpha-research-collector",
        version: str = "0.1.0",
        requirements: tuple[str, ...] = (),
        *,
        provides_extras: tuple[str, ...] = (),
        terminate_headers: bool = True,
        extra_file: tuple[str, bytes] | None = None,
        corrupt_record: bool = False,
    ) -> Path:
        """Build a tiny complete wheel with independently computed RECORD entries."""
        filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        path = directory / filename
        prefix = f"{name.replace('-', '_')}-{version}.dist-info/"
        metadata = (
            "Metadata-Version: 2.3\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
            "Requires-Python: ==3.14.*\n"
            + "".join(f"Requires-Dist: {requirement}\n" for requirement in requirements)
            + "".join(f"Provides-Extra: {extra}\n" for extra in provides_extras)
            + ("\n" if terminate_headers else "")
        ).encode()
        files = {
            name.replace("-", "_") + "/__init__.py": b"VALUE = 1\n",
            prefix + "METADATA": metadata,
            prefix + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        }
        if extra_file is not None:
            files[extra_file[0]] = extra_file[1]
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for member, payload in files.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
            writer.writerow((member, "sha256=" + digest, str(len(payload))))
        writer.writerow((prefix + "RECORD", "", ""))
        record = output.getvalue().encode()
        if corrupt_record:
            record = record.replace(b"sha256=", b"sha512=", 1)
        files[prefix + "RECORD"] = record
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, payload in files.items():
                info = zipfile.ZipInfo(member)
                info.external_attr = 0o100644 << 16
                archive.writestr(info, payload)
        return path

    def test_complete_wheel_has_serializable_identity(self, tmp_path: Path) -> None:
        """Inspect actual bytes and include exact declared requirements in release facts."""
        path = self._wheel(tmp_path, requirements=("alpha-research-contracts==0.1.0",))
        identity = WheelArchive.inspect(path)
        assert identity.name == "alpha-research-collector"
        assert identity.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert identity.requires_dist == ("alpha-research-contracts==0.1.0",)
        assert f'"filename":"{path.name}"' in identity.model_dump_json()

    def test_metadata_without_body_or_blank_separator_is_accepted(self, tmp_path: Path) -> None:
        """Accept the normal one-newline ending used by built metadata-only wheels."""
        path = self._wheel(tmp_path, terminate_headers=False)
        assert WheelArchive.inspect(path).name == "alpha-research-collector"

    @pytest.mark.parametrize(
        ("extra_file", "corrupt_record", "message"),
        [
            (("../escape.py", b"escape"), False, "unsafe wheel member path"),
            (("inject.pth", b"import os"), False, "installation hook"),
            (("sitecustomize.py", b"import os"), False, "installation hook"),
            (("alpha_research_collector-0.1.0.data/scripts/run", b"run"), False, "script"),
            (None, True, "RECORD digest"),
        ],
    )
    def test_unsafe_wheel_bytes_fail(
        self,
        tmp_path: Path,
        extra_file: tuple[str, bytes] | None,
        corrupt_record: bool,
        message: str,
    ) -> None:
        """Reject unsafe paths, activation hooks and content outside RECORD."""
        path = self._wheel(tmp_path, extra_file=extra_file, corrupt_record=corrupt_record)
        with pytest.raises(DependencyAdmissionError, match=message):
            WheelArchive.inspect(path)


@_DARWIN_ARM64_HOST
class TestSelectedClosureAdmission:
    """Prove the selected installed set matches actual metadata and both locks."""

    @staticmethod
    def _refresh_policy(policy: DependencyAdmission, selected_lock: Path) -> DependencyAdmission:
        """Bind deliberate selected-lock mutations without bypassing model validation."""
        return DependencyAdmission(
            schema_version=policy.schema_version,
            as_of_date=policy.as_of_date,
            review_due_on=policy.review_due_on,
            packages=policy.packages,
            wheel_only_allowances=policy.wheel_only_allowances,
            source_archives=policy.source_archives,
            lock_digests=(
                policy.lock_digests[0],
                (
                    "packages/collector/uv.lock",
                    hashlib.sha256(selected_lock.read_bytes()).hexdigest(),
                ),
            ),
        )

    @staticmethod
    def _fixture(tmp_path: Path) -> tuple[Path, Path, tuple[Path, ...], DependencyAdmission]:
        """Create an exact local root, contracts and external wheel graph."""
        root_wheel = TestSelectedWheelArchive._wheel(
            tmp_path,
            requirements=("alpha-research-contracts==0.1.0",),
        )
        contracts = TestSelectedWheelArchive._wheel(
            tmp_path,
            name="alpha-research-contracts",
            requirements=("pydantic==2.13.5",),
        )
        external = TestSelectedWheelArchive._wheel(
            tmp_path,
            name="pydantic",
            version="2.13.5",
        )
        digest = hashlib.sha256(external.read_bytes()).hexdigest()
        url = f"https://files.pythonhosted.org/packages/example/{external.name}"
        package_entry = (
            '[[package]]\nname = "pydantic"\nversion = "2.13.5"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            f'wheels = [{{ url = "{url}", hash = "sha256:{digest}" }}]\n'
        )
        header = 'version = 1\nrevision = 3\nrequires-python = "==3.14.*"\n'
        (tmp_path / "uv.lock").write_text(header + package_entry, encoding="utf-8")
        selected_dir = tmp_path / "packages/collector"
        selected_dir.mkdir(parents=True)
        selected_lock = selected_dir / "uv.lock"
        selected_lock.write_text(
            header
            + '[[package]]\nname = "alpha-research-collector"\nversion = "0.1.0"\n'
            + 'source = { editable = "." }\n'
            + 'dependencies = [{ name = "alpha-research-contracts" }]\n'
            + "[package.metadata]\n"
            + 'requires-dist = [{ name = "alpha-research-contracts", '
            'directory = "../contracts" }]\n'
            + '[[package]]\nname = "alpha-research-contracts"\nversion = "0.1.0"\n'
            + 'source = { directory = "../contracts" }\n'
            + 'dependencies = [{ name = "pydantic" }]\n'
            + "[package.metadata]\n"
            + 'requires-dist = [{ name = "pydantic", specifier = "==2.13.5" }]\n'
            + package_entry,
            encoding="utf-8",
        )
        (tmp_path / "docs/architecture").mkdir(parents=True)
        (tmp_path / "docs/architecture/dependency-admission.toml").write_text(
            "fixture policy\n", encoding="utf-8"
        )
        policy = DependencyAdmission(
            schema_version=5,
            as_of_date=date(2026, 9, 20),
            review_due_on=date(2026, 10, 4),
            packages=(
                PythonPackageAdmission(
                    name="pydantic",
                    version="2.13.5",
                    license_expression="MIT",
                    native_artifacts=False,
                ),
                PythonPackageAdmission(
                    name="nativepkg",
                    version="1.0",
                    license_expression="BSD-3-Clause",
                    native_artifacts=True,
                ),
            ),
            wheel_only_allowances=(
                WheelOnlyAllowance(
                    name="nativepkg",
                    version="1.0",
                    rationale="Unverified source binding retained for isolated development only.",
                    usage="isolated_development_and_ci",
                    source_to_wheel_binding="unverified",
                    reviewed_on=date(2026, 9, 4),
                    expires_on=date(2026, 10, 4),
                ),
            ),
            lock_digests=(
                ("uv.lock", hashlib.sha256((tmp_path / "uv.lock").read_bytes()).hexdigest()),
                (
                    "packages/collector/uv.lock",
                    hashlib.sha256(selected_lock.read_bytes()).hexdigest(),
                ),
            ),
        )
        return root_wheel, selected_lock, (root_wheel, contracts, external), policy

    def test_actual_closed_graph_is_admitted_and_serializable(self, tmp_path: Path) -> None:
        """Bind three verified wheels, two active edges and exact policy/lock bytes."""
        root, selected, inventory, policy = self._fixture(tmp_path)
        with patch(
            "alpha_research_governance.dependency_admission.selected_closure.validate_repository",
            return_value=policy,
        ) as validate:
            facts = SelectedClosureAdmission(tmp_path, selected).admit(
                root, inventory, target="darwin_arm64_cp314"
            )
        validate.assert_called_once_with(tmp_path.resolve())
        assert {wheel.name for wheel in facts.wheels} == {
            "alpha-research-collector",
            "alpha-research-contracts",
            "pydantic",
        }
        assert {(edge.parent, edge.child) for edge in facts.edges} == {
            ("alpha-research-collector", "alpha-research-contracts"),
            ("alpha-research-contracts", "pydantic"),
        }
        assert facts.selected_lock_sha256 == dict(policy.lock_digests)["packages/collector/uv.lock"]
        assert SelectedClosureFacts.model_validate_json(facts.model_dump_json()) == facts
        SelectedClosureAdmission.verify_retained(
            facts,
            root_lock=tmp_path / "uv.lock",
            selected_lock=selected,
            policy=policy,
            wheels=inventory,
        )

    def test_retained_graph_rejects_changed_wheels_and_edges(self, tmp_path: Path) -> None:
        """Require staged bytes and signed edges to describe the same actual closure."""
        root, selected, inventory, policy = self._fixture(tmp_path)
        with patch(
            "alpha_research_governance.dependency_admission.selected_closure.validate_repository",
            return_value=policy,
        ):
            facts = SelectedClosureAdmission(tmp_path, selected).admit(
                root, inventory, target="darwin_arm64_cp314"
            )
        changed = SelectedClosureFacts(
            root_name=facts.root_name,
            root_version=facts.root_version,
            target=facts.target,
            marker_environment=facts.marker_environment,
            policy_sha256=facts.policy_sha256,
            root_lock_sha256=facts.root_lock_sha256,
            selected_lock_sha256=facts.selected_lock_sha256,
            review_due_on=facts.review_due_on,
            wheels=facts.wheels,
            edges=(),
        )
        with pytest.raises(DependencyAdmissionError, match="graph differs"):
            SelectedClosureAdmission.verify_retained(
                changed,
                root_lock=tmp_path / "uv.lock",
                selected_lock=selected,
                policy=policy,
                wheels=inventory,
            )
        TestSelectedWheelArchive._wheel(
            tmp_path, name="pydantic", version="2.13.5", extra_file=("pydantic/new.py", b"x")
        )
        with pytest.raises(DependencyAdmissionError, match="wheel inventory differs"):
            SelectedClosureAdmission.verify_retained(
                facts,
                root_lock=tmp_path / "uv.lock",
                selected_lock=selected,
                policy=policy,
                wheels=inventory,
            )

    def test_requested_extra_activates_actual_metadata_requirements(self, tmp_path: Path) -> None:
        """Traverse requested extras and match the selected lock's extra edge."""
        root = WheelArchive.inspect(
            TestSelectedWheelArchive._wheel(
                tmp_path, requirements=("alpha-research-contracts[feature]==0.1.0",)
            )
        )
        contracts = WheelArchive.inspect(
            TestSelectedWheelArchive._wheel(
                tmp_path,
                name="alpha-research-contracts",
                requirements=("pydantic==2.13.5; extra == 'feature'",),
                provides_extras=("feature",),
            )
        )
        external = WheelArchive.inspect(
            TestSelectedWheelArchive._wheel(tmp_path, name="pydantic", version="2.13.5")
        )
        selected: dict[str, dict[str, object]] = {
            root.name: {"dependencies": [{"name": contracts.name, "extra": ["feature"]}]},
            contracts.name: {"dependencies": [{"name": external.name}]},
            external.name: {},
        }
        environment = SelectedClosureAdmission._target_environment("darwin_arm64_cp314")
        edges = SelectedClosureAdmission._resolve(
            root.name,
            {item.name: item for item in (root, contracts, external)},
            selected,
            environment,
        )
        assert {(edge.parent, edge.parent_extra, edge.child) for edge in edges} == {
            (root.name, "", contracts.name),
            (contracts.name, "feature", external.name),
        }

    def test_inactive_platform_requirement_needs_no_wheel(self, tmp_path: Path) -> None:
        """A Windows-only metadata and lock edge stays outside this Darwin closure."""
        root = WheelArchive.inspect(
            TestSelectedWheelArchive._wheel(
                tmp_path, requirements=("pydantic==2.13.5; sys_platform == 'win32'",)
            )
        )
        selected: dict[str, dict[str, object]] = {
            root.name: {"dependencies": [{"name": "pydantic", "marker": "sys_platform == 'win32'"}]}
        }
        environment = SelectedClosureAdmission._target_environment("darwin_arm64_cp314")
        assert not SelectedClosureAdmission._resolve(
            root.name, {root.name: root}, selected, environment
        )

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            ("missing", "requires missing wheel"),
            ("unexpected", "absent or version-drifted"),
            ("allowance", "wheel-only allowance"),
            ("pin", "wheel bytes or source differ"),
            ("source", "locked local requirement source drifted"),
            ("metadata", "METADATA differs"),
            ("lock", "selected lock differs"),
        ],
    )
    def test_incomplete_or_drifted_closure_fails(
        self, tmp_path: Path, mutation: str, message: str
    ) -> None:
        """Fail on omitted dependencies, extra wheels, wheel-only packages and identity drift."""
        root, selected, inventory, policy = self._fixture(tmp_path)
        wheels = list(inventory)
        if mutation == "missing":
            wheels.pop()
        elif mutation == "unexpected":
            wheels.append(TestSelectedWheelArchive._wheel(tmp_path, name="unneeded"))
        elif mutation == "allowance":
            wheels.append(
                TestSelectedWheelArchive._wheel(tmp_path, name="nativepkg", version="1.0")
            )
            selected.write_text(
                selected.read_text(encoding="utf-8")
                + '[[package]]\nname = "nativepkg"\nversion = "1.0"\n'
                + 'source = { registry = "https://pypi.org/simple" }\n',
                encoding="utf-8",
            )
            policy = self._refresh_policy(policy, selected)
        elif mutation == "pin":
            selected.write_text(
                selected.read_text(encoding="utf-8").replace(
                    "https://files.pythonhosted.org", "https://other.invalid"
                ),
                encoding="utf-8",
            )
            policy = self._refresh_policy(policy, selected)
        elif mutation == "source":
            selected.write_text(
                selected.read_text(encoding="utf-8").replace(
                    'source = { directory = "../contracts" }',
                    'source = { directory = "../other" }',
                ),
                encoding="utf-8",
            )
            policy = self._refresh_policy(policy, selected)
        elif mutation == "metadata":
            TestSelectedWheelArchive._wheel(tmp_path)
        elif mutation == "lock":
            selected.write_text(selected.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with patch(
            "alpha_research_governance.dependency_admission.selected_closure.validate_repository",
            return_value=policy,
        ):
            with pytest.raises(DependencyAdmissionError, match=message):
                SelectedClosureAdmission(tmp_path, selected).admit(
                    root, wheels, target="darwin_arm64_cp314"
                )


@_DARWIN_ARM64_HOST
class TestSelectedWheelhouse:
    """Fetch only exact compatible external wheels named by the selected export."""

    @pytest.mark.parametrize(
        ("output", "message"),
        [
            ("pydantic==2.13.5\npydantic==2.13.5\n", "duplicate pins"),
            ("pydantic>=2.0\n", "nonexact"),
            ("pydantic @ https://evil.invalid/wheel.whl\n", "unsupported requirement"),
            ("--index-url https://evil.invalid\n", "malformed"),
        ],
    )
    def test_malformed_or_mutable_uv_export_is_rejected(
        self, tmp_path: Path, output: str, message: str
    ) -> None:
        """Never let export text introduce a mutable source or ambiguous package."""
        completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=["uv"], returncode=0, stdout=output, stderr=""
        )
        with patch(
            "alpha_research_governance.dependency_admission.wheelhouse.subprocess.run",
            return_value=completed,
        ):
            with pytest.raises(DependencyAdmissionError, match=message):
                SelectedWheelhouse._export(
                    tmp_path,
                    Path("/usr/bin/uv"),
                    SelectedClosureAdmission._target_environment("darwin_arm64_cp314"),
                )

    def test_uv_export_filters_inactive_platform_pins(self, tmp_path: Path) -> None:
        """Choose Darwin requirements from the offline locked export text."""
        completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=["uv"],
            returncode=0,
            stdout=(
                "pydantic==2.13.5 ; sys_platform == 'darwin'\n"
                "colorama==0.4.6 ; sys_platform == 'win32'\n"
            ),
            stderr="",
        )
        with patch(
            "alpha_research_governance.dependency_admission.wheelhouse.subprocess.run",
            return_value=completed,
        ):
            exported = SelectedWheelhouse._export(
                tmp_path,
                Path("/usr/bin/uv"),
                SelectedClosureAdmission._target_environment("darwin_arm64_cp314"),
            )
        assert exported == {"pydantic": "2.13.5"}

    def test_exported_pin_downloads_verified_bytes(self, tmp_path: Path) -> None:
        """Retain a real complete wheel at its exact admitted filename and digest."""
        _, _, inventory, policy = TestSelectedClosureAdmission._fixture(tmp_path)
        expected = inventory[-1]
        exported: dict[str, str] = {"pydantic": "2.13.5"}
        with (
            patch(
                "alpha_research_governance.dependency_admission.wheelhouse.validate_repository",
                return_value=policy,
            ),
            patch.object(SelectedWheelhouse, "_export", return_value=exported),
            patch.object(
                SelectedWheelhouse, "_download", return_value=expected.read_bytes()
            ) as fetch,
        ):
            wheels = SelectedWheelhouse.fetch(
                tmp_path, "collector", tmp_path / "logs/wheels", Path("/usr/bin/uv")
            )
        assert wheels == (tmp_path / "logs/wheels" / expected.name,)
        assert wheels[0].read_bytes() == expected.read_bytes()
        fetch.assert_called_once()

    def test_download_hash_mismatch_leaves_no_wheel(self, tmp_path: Path) -> None:
        """A changed response cannot populate the approved wheelhouse."""
        _, _, _, policy = TestSelectedClosureAdmission._fixture(tmp_path)
        exported: dict[str, str] = {"pydantic": "2.13.5"}
        with (
            patch(
                "alpha_research_governance.dependency_admission.wheelhouse.validate_repository",
                return_value=policy,
            ),
            patch.object(SelectedWheelhouse, "_export", return_value=exported),
            patch.object(SelectedWheelhouse, "_download", return_value=b"tampered"),
        ):
            with pytest.raises(DependencyAdmissionError, match="admitted digest"):
                SelectedWheelhouse.fetch(
                    tmp_path, "collector", tmp_path / "logs/wheels", Path("/usr/bin/uv")
                )
        assert not tuple((tmp_path / "logs/wheels").iterdir())

    def test_selected_lock_drift_prevents_export(self, tmp_path: Path) -> None:
        """Check selected lock bytes before invoking uv or network acquisition."""
        _, selected, _, policy = TestSelectedClosureAdmission._fixture(tmp_path)
        selected.write_text(selected.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with (
            patch(
                "alpha_research_governance.dependency_admission.wheelhouse.validate_repository",
                return_value=policy,
            ),
            patch.object(SelectedWheelhouse, "_export") as export,
        ):
            with pytest.raises(DependencyAdmissionError, match="not admitted"):
                SelectedWheelhouse.fetch(
                    tmp_path, "collector", tmp_path / "logs/wheels", Path("/usr/bin/uv")
                )
        export.assert_not_called()

    def test_selected_artifact_source_drift_prevents_fetch(self, tmp_path: Path) -> None:
        """A new selected-lock URL cannot borrow a root-admitted wheel hash."""
        _, selected, _, policy = TestSelectedClosureAdmission._fixture(tmp_path)
        selected.write_text(
            selected.read_text(encoding="utf-8").replace(
                "https://files.pythonhosted.org", "https://other.invalid"
            ),
            encoding="utf-8",
        )
        policy = TestSelectedClosureAdmission._refresh_policy(policy, selected)
        exported: dict[str, str] = {"pydantic": "2.13.5"}
        with (
            patch(
                "alpha_research_governance.dependency_admission.wheelhouse.validate_repository",
                return_value=policy,
            ),
            patch.object(SelectedWheelhouse, "_export", return_value=exported),
            patch.object(SelectedWheelhouse, "_download") as download,
        ):
            with pytest.raises(DependencyAdmissionError, match="source or digest"):
                SelectedWheelhouse.fetch(
                    tmp_path, "collector", tmp_path / "logs/wheels", Path("/usr/bin/uv")
                )
        download.assert_not_called()
