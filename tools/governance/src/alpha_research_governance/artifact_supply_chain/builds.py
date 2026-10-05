"""Build operating wheels once and retain signed source, audit and installation inputs."""

from __future__ import annotations

# standard library imports
import re
import subprocess  # nosec B404  # [owner=platform; rationale=explicit local build and source identity commands; expires=2027-03-01]
import tomllib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, cast

# third party library imports
from pydantic import TypeAdapter

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.artifact_supply_chain.audit import ReleaseAudit
from alpha_research_governance.artifact_supply_chain.bundles import ReleaseRegistry, VerifiedRelease
from alpha_research_governance.artifact_supply_chain.installation import LocalInstallation
from alpha_research_governance.artifact_supply_chain.provenance import (
    ReleaseProvenance,
    SourceSnapshot,
)
from alpha_research_governance.artifact_supply_chain.records import (
    Identity,
    InstallationPolicy,
    ReleaseFile,
    ReleaseManifest,
    ReleaseRuntime,
    StateEnvelope,
)
from alpha_research_governance.artifact_supply_chain.signatures import ReleaseSignatures
from alpha_research_governance.dependency_admission import DependencyRepository
from alpha_research_governance.dependency_admission.selected_closure import SelectedClosureAdmission
from alpha_research_governance.engineering_standards import ImportAudit


class ReleaseBuild(ImmutableModel):
    """Select release identity and compatibility without embedding paths or credentials."""

    name: Identity
    builder: Identity
    origin: str
    valid_until: datetime
    runtime: ReleaseRuntime


class ExternalExtension(ImmutableModel):
    """Retain one external extension project's identity and exact source bytes."""

    name: str
    path: Path
    files: tuple[tuple[str, bytes], ...]

    NAME: ClassVar[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")
    GROUP: ClassVar[str] = "alpha_research.candidate_components"

    @staticmethod
    def shipped(repository: Path) -> frozenset[str]:
        """Return the platform source files the paper-services release ships.

        They are the candidate runtime's manifest, which an engineering test keeps
        equal to the operating wheels' include tables.
        """
        manifest = TypeAdapter(dict[str, list[str]]).validate_json(
            ReleaseRegistry.read_regular(
                repository / "src/runtime/candidate_runtime.json", 1_048_576
            )
        )
        return frozenset(manifest["modules"])

    @classmethod
    def read(cls, path: Path, shipped: frozenset[str]) -> ExternalExtension:
        """Read and audit an extension project outside the repository.

        It must declare exactly one candidate component provider, no scripts and no
        uv sources, and its ``src`` tree must import only supported platform names
        from modules the release ships.

        Raises:
            ValueError: The project layout, metadata or imports are not admissible.
        """
        if not path.is_absolute() or not (path / "pyproject.toml").is_file():
            raise ValueError(f"external extension requires an absolute project: {path}")
        table = TypeAdapter(dict[str, object]).validate_python(
            cast(object, tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8")))
        )
        project = TypeAdapter(dict[str, object]).validate_python(table.get("project"))
        groups = TypeAdapter(dict[str, dict[str, str]]).validate_python(
            project.get("entry-points", {})
        )
        tool = TypeAdapter(dict[str, object]).validate_python(table.get("tool", {}))
        uv = TypeAdapter(dict[str, object]).validate_python(tool.get("uv", {}))
        name = project.get("name")
        if (
            not isinstance(name, str)
            or cls.NAME.fullmatch(name) is None
            or name.startswith("alpha-research-")
            or "scripts" in project
            or set(groups) != {cls.GROUP}
            or len(groups[cls.GROUP]) != 1
            or "sources" in uv
        ):
            raise ValueError(f"external extension metadata is not admissible: {path}")
        audit = ImportAudit(shipped=shipped)
        findings = audit.audit(path / "src")
        if findings:
            raise ValueError("external extension imports: " + "; ".join(audit.report(findings)))
        files = [
            ("pyproject.toml", ReleaseRegistry.read_regular(path / "pyproject.toml", 1_048_576))
        ]
        for item in sorted((path / "src").rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts:
                files.append(
                    (
                        item.relative_to(path).as_posix(),
                        ReleaseRegistry.read_regular(item, 16_777_216),
                    )
                )
        return cls(name=name, path=path, files=tuple(files))


class ReleaseBuilder:
    """Build selected monorepo distributions and sign their verified retained inputs."""

    def __init__(self, repository: Path, policy: InstallationPolicy) -> None:
        """Bind a repository and independently provisioned builder/target policy."""
        self.repository = repository.resolve(strict=True)
        self.policy = InstallationPolicy.model_validate(policy)

    def build(
        self,
        request: ReleaseBuild,
        *,
        configuration: Path,
        dependency_wheels: Path,
        audit_report: Path,
        private_key: Path,
        registry: Path,
        now: datetime,
        state: Path | None = None,
        candidates: Path | None = None,
        extensions: Path | None = None,
    ) -> Path:
        """Publish a signed release after build, complete admission and source comparison.

        Args:
            request: Explicit identity, origin, target, mode and schema compatibility.
            configuration: Actual application configuration bytes, excluding secret values.
            dependency_wheels: Complete selected external wheelhouse; no local project wheels.
            audit_report: Absent output path for a fresh complete pip-audit JSON and scanner log.
            private_key: Protected local Ed25519 builder key; never copied into the release.
            registry: Local immutable registry destination.
            now: Aware UTC build observation time.
            state: Optional quiesced initial state directory; absent means an empty state.
            candidates: Paper services only: a directory of candidate bundle roots,
                signed under ``candidates/`` and verified by the installed application.
            extensions: Paper services only: a directory of external extension
                projects, one per subdirectory. Each is audited, built and admitted
                only if its requirements are already in the locked closure; its
                source is signed under ``source/external/<name>/``.

        Returns:
            Content-addressed bundle path, ready for separate local installation.

        Raises:
            ValueError: Build inputs, source correspondence, trust or admission fail.
            OSError: Required inputs or build tools are unavailable.
        """
        request = ReleaseBuild.model_validate(request)
        policy = DependencyRepository.validate(self.repository)
        # Pinned tools and target are checked before any build process runs.
        LocalInstallation(registry, self.policy)._require_tools(request.runtime)
        backend = self._run(
            [
                self.policy.python_executable,
                "-I",
                "-c",
                "from importlib.metadata import version; print(version('hatchling'))",
            ]
        )
        if backend.strip() != b"1.32.0":
            raise ValueError("release build requires admitted hatchling 1.32.0")
        audit_bytes = ReleaseAudit.run(policy, audit_report)
        if (candidates is not None) != (request.runtime.application == "paper-services"):
            raise ValueError("candidate bundles are signed only into paper services releases")
        if extensions is not None and request.runtime.application != "paper-services":
            raise ValueError("external extensions are signed only into paper services releases")
        external = (
            ()
            if extensions is None
            else tuple(
                ExternalExtension.read(path, ExternalExtension.shipped(self.repository))
                for path in sorted(extensions.iterdir())
                if path.is_dir() and not path.name.startswith(".")
            )
        )
        if len({item.name for item in external}) != len(external):
            raise ValueError("external extension names must be unique")
        before = self._source_inputs()
        selected = self.repository / "packages" / request.runtime.application
        root_name = "alpha-research-" + request.runtime.application
        commands: list[tuple[str, ...]] = []
        with TemporaryDirectory(prefix="ar-build-") as temporary:
            directory = Path(temporary)
            wheels = directory / "wheels"
            wheels.mkdir()
            for project in self._local_projects(selected):
                command = [
                    self.policy.uv_executable,
                    "build",
                    "--no-config",
                    "--offline",
                    "--no-build-isolation",
                    "--wheel",
                    "--no-sources",
                    "--python",
                    self.policy.python_executable,
                    str(project),
                    "--out-dir",
                    str(wheels),
                ]
                self._run(command)
                commands.append(tuple(command))
            extension_wheels: list[Path] = []
            for item in external:
                built = directory / "external" / item.name
                built.mkdir(parents=True)
                command = [
                    self.policy.uv_executable,
                    "build",
                    "--no-config",
                    "--offline",
                    "--no-build-isolation",
                    "--wheel",
                    "--no-sources",
                    "--python",
                    self.policy.python_executable,
                    str(item.path),
                    "--out-dir",
                    str(built),
                ]
                self._run(command)
                commands.append(tuple(command))
                (wheel,) = tuple(built.glob("*.whl"))
                extension_wheels.append(wheels / wheel.name)
                (wheels / wheel.name).write_bytes(wheel.read_bytes())
            for name in ReleaseRegistry.inventory(dependency_wheels):
                if "/" in name or not name.endswith(".whl") or name.startswith("alpha_research_"):
                    raise ValueError("dependency wheelhouse must contain only external wheels")
                (wheels / name).write_bytes(
                    ReleaseRegistry.read_regular(dependency_wheels / name, 268_435_456)
                )
            actual_wheels = tuple(sorted(wheels.glob("*.whl")))
            roots = [
                path
                for path in actual_wheels
                if path.name.startswith(root_name.replace("-", "_") + "-")
            ]
            if len(roots) != 1:
                raise ValueError("build did not produce exactly one operating root")
            facts = SelectedClosureAdmission(self.repository, selected / "uv.lock").admit(
                roots[0], actual_wheels, target="darwin_arm64_cp314", extensions=extension_wheels
            )
            if self._source_inputs() != before or any(
                ExternalExtension.read(item.path, ExternalExtension.shipped(self.repository))
                != item
                for item in external
            ):
                raise ValueError("source changed during release build; retain a stable snapshot")
            before = self.release_sources(
                before,
                tuple(
                    (f"external/{item.name}/{name}", content)
                    for item in external
                    for name, content in item.files
                ),
            )
            contents: dict[str, bytes] = {
                "provenance/closure.json": facts.model_dump_json().encode(),
                "provenance/uv.lock": (self.repository / "uv.lock").read_bytes(),
                "provenance/selected.lock": (selected / "uv.lock").read_bytes(),
                "provenance/dependency-admission.toml": (
                    self.repository / "docs/architecture/dependency-admission.toml"
                ).read_bytes(),
                "provenance/audit.json": audit_bytes,
                "provenance/source.json": SourceSnapshot(
                    files=tuple(ReleaseFile.describe(name, content) for name, content in before)
                )
                .model_dump_json()
                .encode(),
                "configuration/config.json": configuration.read_bytes(),
            }
            contents.update(("source/" + name, content) for name, content in before)
            contents.update(("wheels/" + path.name, path.read_bytes()) for path in actual_wheels)
            if candidates is not None:
                for name in ReleaseRegistry.inventory(candidates):
                    contents["candidates/" + name] = ReleaseRegistry.read_regular(
                        candidates / name, 67_108_864
                    )
            initial: list[ReleaseFile] = []
            if state is not None:
                for name in ReleaseRegistry.inventory(state):
                    if name == "state.json":
                        raise ValueError("initial state must not contain the installer's envelope")
                    content = ReleaseRegistry.read_regular(state / name, 268_435_456)
                    contents["state/" + name] = content
                    initial.append(ReleaseFile.describe(name, content))
            contents["state/state.json"] = (
                StateEnvelope(
                    schema_version=request.runtime.state_schema,
                    application=request.runtime.application,
                    files=tuple(initial),
                )
                .model_dump_json()
                .encode()
            )
            manifest = ReleaseManifest(
                name=request.name,
                builder=request.builder,
                origin=request.origin,
                created_at=now,
                valid_until=request.valid_until,
                source_commit=self._run(["git", "rev-parse", "HEAD"]).decode().strip(),
                source_dirty=bool(self._run(["git", "status", "--porcelain"]).strip()),
                build_commands=tuple(commands),
                runtime=request.runtime,
                root_distribution=(
                    "alpha-research-collector"
                    if request.runtime.application == "collector"
                    else "alpha-research-execution"
                    if request.runtime.application == "execution"
                    else "alpha-research-paper-services"
                ),
                files=tuple(
                    ReleaseFile.describe(name, content)
                    for name, content in sorted(contents.items())
                ),
            )
            ReleaseProvenance.verify(
                VerifiedRelease(manifest, manifest.encoded(), b"", tuple(sorted(contents.items()))),
                now=now,
            )
            signatures = ReleaseSignatures(
                Path(self.policy.ssh_keygen_executable), self.policy.ssh_keygen_sha256
            )
            signature = signatures.sign(manifest.encoded(), private_key)
            published = ReleaseRegistry.publish(
                registry, manifest, signature, tuple(sorted(contents.items()))
            )
            verified = ReleaseRegistry.verify(published, self.policy, now=now)
            ReleaseProvenance.verify(verified, now=now)
            return published

    def _local_projects(self, selected: Path) -> tuple[Path, ...]:
        """Return every local project the selected lock installs, root last.

        Directory sources resolve against the selected project and must stay inside
        ``packages/`` or ``extensions/`` of this repository.
        """
        locked = DependencyRepository.locked_packages(selected / "uv.lock")
        projects: list[Path] = []
        for name in sorted(locked):
            source = locked[name].get("source")
            if not isinstance(source, dict):
                continue
            entries = cast(dict[str, object], source)
            if set(entries) != {"directory"}:
                continue
            directory = (selected / str(entries["directory"])).resolve(strict=True)
            relative = directory.relative_to(self.repository).as_posix()
            if relative.split("/", 1)[0] not in {"packages", "extensions"}:
                raise ValueError("local release project lies outside packages or extensions")
            projects.append(directory)
        return (*projects, selected)

    @staticmethod
    def release_sources(
        repository: tuple[tuple[str, bytes], ...], external: tuple[tuple[str, bytes], ...]
    ) -> tuple[tuple[str, bytes], ...]:
        """Order every signed source file by name, as verification reads them back.

        External extensions sort among the repository's files: ``external/`` falls
        between ``extensions/`` and ``packages/``, not after them.
        """
        return tuple(sorted((*repository, *external)))

    def _source_inputs(self) -> tuple[tuple[str, bytes], ...]:
        """Capture maintained build/runtime inputs, including uncommitted source bytes."""
        paths: set[Path] = set()
        for root in (self.repository / "src", self.repository / "tools/governance/src"):
            paths.update(
                path
                for path in root.rglob("*")
                if path.suffix in {".py", ".json", ".md"} or path.name == "py.typed"
            )
        paths.update(
            self.repository / name
            for name in (
                "pyproject.toml",
                "uv.lock",
                "tools/governance/pyproject.toml",
                "docs/README.md",
                "docs/architecture/dependency-admission.toml",
            )
        )
        for package in ("contracts", "collector", "execution", "paper-services"):
            paths.add(self.repository / "packages" / package / "pyproject.toml")
            lock = self.repository / "packages" / package / "uv.lock"
            if lock.exists():
                paths.add(lock)
        extensions = self.repository / "extensions"
        if extensions.is_dir():
            for project in sorted(path for path in extensions.iterdir() if path.is_dir()):
                paths.add(project / "pyproject.toml")
                paths.update(
                    path
                    for path in (project / "src").rglob("*")
                    if path.suffix in {".py", ".json"} or path.name == "py.typed"
                )
        return tuple(
            (
                path.relative_to(self.repository).as_posix(),
                ReleaseRegistry.read_regular(path, 16_777_216),
            )
            for path in sorted(paths)
        )

    def _run(self, arguments: list[str]) -> bytes:
        """Run bounded build/provenance argv with a fresh HOME and no inherited credentials."""
        with TemporaryDirectory(prefix="ar-build-home-") as home:
            result = subprocess.run(  # nosec B603  # [owner=platform; rationale=fixed source and build argv with pinned tool; expires=2027-03-01]
                arguments,
                cwd=self.repository,
                check=False,
                capture_output=True,
                timeout=180,
                env={"PATH": "/usr/bin:/bin", "HOME": home, "LC_ALL": "C"},
            )
        if result.returncode != 0:
            raise ValueError(
                f"release build failed: {result.stderr.decode(errors='replace')[-2000:]}"
            )
        return result.stdout
