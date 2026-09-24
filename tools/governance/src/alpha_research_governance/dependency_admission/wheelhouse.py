"""Acquire the exact external wheels selected by an admitted operating lock."""

from __future__ import annotations

# standard library imports
import hashlib
import http.client
import os
import re
import stat
import subprocess  # nosec B404  # [owner=platform; rationale=pinned offline uv export argv; expires=2027-03-01]
import tempfile
import time
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

# third party library imports
from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, sys_tags
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

# project library imports
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
)
from alpha_research_governance.dependency_admission.policy import (
    _locked_python_packages,
    validate_repository,
)
from alpha_research_governance.dependency_admission.selected_closure import (
    SelectedClosureAdmission,
)
from alpha_research_governance.dependency_admission.wheel_archive import WheelArchive

OperatingApplication = Literal["collector", "execution"]
_REGISTRY = {"registry": "https://pypi.org/simple"}
_MAX_WHEEL_BYTES = 256 * 1024 * 1024


class SelectedWheelhouse:
    """Materialize only the current target's verified external wheel inventory."""

    @classmethod
    def fetch(
        cls,
        repository_root: Path,
        application: OperatingApplication,
        destination: Path,
        uv_executable: Path,
    ) -> tuple[Path, ...]:
        """Export a locked operating graph and fetch its exact admitted wheels.

        Args:
            repository_root: Checkout with current full dependency admission.
            application: Collector or execution operating dependency graph.
            destination: Caller-selected directory for retained actual wheel bytes.
            uv_executable: Independently pinned uv executable used for offline export.

        Returns:
            Sorted external wheel paths suitable for a complete release wheelhouse.

        Raises:
            DependencyAdmissionError: Admission, export, artifact or inventory differs.
            OSError: Required local bytes or a requested pinned artifact are unavailable.
        """
        if application not in {"collector", "execution"}:
            raise DependencyAdmissionError(["unsupported operating application"])
        root = repository_root.resolve(strict=True)
        project = root / "packages" / application
        selected_lock = project / "uv.lock"
        relative_lock = selected_lock.relative_to(root).as_posix()
        environment = SelectedClosureAdmission._target_environment("darwin_arm64_cp314")
        policy = validate_repository(root)
        digests = dict(policy.lock_digests)
        if (
            relative_lock not in digests
            or hashlib.sha256(selected_lock.read_bytes()).hexdigest() != digests[relative_lock]
        ):
            raise DependencyAdmissionError(["operating lock is not admitted at exact bytes"])
        selected = _locked_python_packages(selected_lock)
        full = _locked_python_packages(root / "uv.lock")
        exported = cls._export(project, uv_executable, environment)
        if not exported:
            raise DependencyAdmissionError(["selected uv export has no external dependencies"])
        artifacts = cls._artifacts(exported, selected, full, policy)
        output = cls._destination(destination, set(artifacts))
        results: list[Path] = []
        for filename, (name, version, url, digest) in sorted(artifacts.items()):
            path = output / filename
            if path.is_symlink():
                raise DependencyAdmissionError([f"wheelhouse member is a symlink: {filename}"])
            if path.exists():
                payload = cls._existing_bytes(path)
            else:
                payload = cls._download(url)
            if len(payload) > _MAX_WHEEL_BYTES or hashlib.sha256(payload).hexdigest() != digest:
                raise DependencyAdmissionError([f"{name} wheel bytes differ from admitted digest"])
            if not path.exists():
                with tempfile.TemporaryDirectory(prefix=".wheel-", dir=output) as temporary:
                    staging = Path(temporary) / filename
                    staging.write_bytes(payload)
                    identity = WheelArchive.inspect(staging)
                    if identity.name != name or identity.version != version:
                        raise DependencyAdmissionError([f"{name} wheel metadata identity differs"])
                    os.replace(staging, path)
            identity = WheelArchive.inspect(path)
            if identity.name != name or identity.version != version or identity.sha256 != digest:
                raise DependencyAdmissionError([f"{name} wheel metadata identity differs"])
            results.append(path)
        return tuple(results)

    @staticmethod
    def _existing_bytes(path: Path) -> bytes:
        """Rehash bounded existing bytes without following a swapped leaf symlink."""
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_WHEEL_BYTES:
                raise DependencyAdmissionError([f"existing wheel is not bounded: {path.name}"])
            payload = stream.read(_MAX_WHEEL_BYTES + 1)
        if len(payload) > _MAX_WHEEL_BYTES:
            raise DependencyAdmissionError([f"existing wheel exceeds size limit: {path.name}"])
        return payload

    @staticmethod
    def _export(project: Path, uv_executable: Path, environment: dict[str, str]) -> dict[str, str]:
        """Ask pinned uv for active exact external requirements without resolution drift."""
        with tempfile.TemporaryDirectory(prefix="selected-uv-export-") as temporary:
            command = [
                str(uv_executable),
                "export",
                "--locked",
                "--offline",
                "--cache-dir",
                temporary,
                "--no-dev",
                "--no-emit-local",
                "--no-hashes",
                "--no-annotate",
                "--no-header",
                "--project",
                str(project),
            ]
            try:
                completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=exact offline locked export argv; expires=2027-03-01]
                    command,
                    cwd=project,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise DependencyAdmissionError(
                    ["locked operating uv export failed to start"]
                ) from error
        if completed.returncode != 0:
            raise DependencyAdmissionError(
                [f"locked operating uv export failed: {completed.stderr[-2000:]}"]
            )
        selected: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                requirement = Requirement(line)
            except InvalidRequirement as error:
                raise DependencyAdmissionError(["selected uv export is malformed"]) from error
            if requirement.url is not None or requirement.extras:
                raise DependencyAdmissionError(
                    ["selected uv export has an unsupported requirement"]
                )
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            name = canonicalize_name(requirement.name)
            specification = str(requirement.specifier)
            if re.fullmatch(r"==[^,;\s]+", specification) is None or name in selected:
                raise DependencyAdmissionError(
                    ["selected uv export has nonexact or duplicate pins"]
                )
            selected[name] = specification.removeprefix("==")
        return selected

    @classmethod
    def _artifacts(
        cls,
        exported: dict[str, str],
        selected: dict[str, dict[str, object]],
        full: dict[str, dict[str, object]],
        policy: DependencyAdmission,
    ) -> dict[str, tuple[str, str, str, str]]:
        """Select one highest-priority compatible artifact pinned in both locks."""
        admitted = {item.name: item.version for item in policy.packages}
        disallowed = {item.name for item in policy.wheel_only_allowances}
        priority = {tag: rank for rank, tag in enumerate(sys_tags())}
        artifacts: dict[str, tuple[str, str, str, str]] = {}
        for name, version in exported.items():
            package, full_package = selected.get(name), full.get(name)
            if name in disallowed:
                raise DependencyAdmissionError(
                    [f"selected export includes wheel-only allowance {name}"]
                )
            if (
                admitted.get(name) != version
                or package is None
                or full_package is None
                or package.get("version") != version
                or full_package.get("version") != version
                or package.get("source") != _REGISTRY
                or full_package.get("source") != _REGISTRY
            ):
                raise DependencyAdmissionError([f"{name} selected version/source is not admitted"])
            selected_wheel = cls._best_wheel(name, version, package, priority)
            full_wheel = cls._best_wheel(name, version, full_package, priority)
            if selected_wheel != full_wheel:
                raise DependencyAdmissionError([f"{name} selected artifact differs from root lock"])
            filename, url, digest = selected_wheel
            if filename in artifacts:
                raise DependencyAdmissionError([f"selected wheel filename collision: {filename}"])
            artifacts[filename] = (name, version, url, digest)
        return artifacts

    @staticmethod
    def _best_wheel(
        name: str,
        version: str,
        package: dict[str, object],
        priority: dict[Tag, int],
    ) -> tuple[str, str, str]:
        """Find the unique most compatible wheel without allowing an sdist fallback."""
        records = package.get("wheels")
        if not isinstance(records, list):
            raise DependencyAdmissionError([f"{name} has no locked wheel inventory"])
        best: tuple[int, str, str, str] | None = None
        for record in cast(list[object], records):
            if not isinstance(record, dict):
                raise DependencyAdmissionError([f"{name} has malformed locked wheel"])
            url, digest = record.get("url"), record.get("hash")
            if not isinstance(url, str) or not isinstance(digest, str):
                raise DependencyAdmissionError([f"{name} has malformed locked wheel"])
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "files.pythonhosted.org"
                or not parsed.path.startswith("/packages/")
                or parsed.query
                or parsed.fragment
                or not digest.startswith("sha256:")
            ):
                raise DependencyAdmissionError([f"{name} wheel source or digest is unapproved"])
            filename = parsed.path.rsplit("/", 1)[-1]
            try:
                wheel_name, wheel_version, _, tags = parse_wheel_filename(filename)
            except InvalidWheelFilename as error:
                raise DependencyAdmissionError(
                    [f"{name} locked wheel filename is malformed"]
                ) from error
            if wheel_name != name or str(wheel_version) != version:
                raise DependencyAdmissionError([f"{name} locked wheel filename identity differs"])
            ranks = [priority[tag] for tag in tags if tag in priority]
            if not ranks:
                continue
            candidate = (min(ranks), filename, url, digest.removeprefix("sha256:"))
            if best is None or candidate[0] < best[0]:
                best = candidate
            elif candidate[0] == best[0]:
                raise DependencyAdmissionError([f"{name} has ambiguous compatible wheels"])
        if best is None:
            raise DependencyAdmissionError([f"{name} has no current-target locked wheel"])
        return best[1], best[2], best[3]

    @staticmethod
    def _destination(destination: Path, expected: set[str]) -> Path:
        """Require a caller-selected wheelhouse with no unsafe preexisting files."""
        if destination.is_symlink():
            raise DependencyAdmissionError(["selected wheelhouse directory is a symlink"])
        resolved = destination.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        for item in resolved.iterdir():
            if item.is_symlink() or not item.is_file() or item.name not in expected:
                raise DependencyAdmissionError([f"unexpected selected wheelhouse member: {item}"])
        return resolved

    @staticmethod
    def _download(url: str) -> bytes:
        """Fetch one exact PyPI URL over bounded HTTPS without redirect following."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "files.pythonhosted.org"
            or not parsed.path.startswith("/packages/")
            or parsed.query
            or parsed.fragment
        ):
            raise DependencyAdmissionError(["selected wheel download origin is unapproved"])
        connection = http.client.HTTPSConnection("files.pythonhosted.org", timeout=15)
        started = time.monotonic()
        try:
            connection.request("GET", parsed.path, headers={"User-Agent": "alpha-wheelhouse"})
            response = connection.getresponse()
            if response.status != 200:
                raise DependencyAdmissionError(
                    [f"selected wheel download returned HTTP {response.status}"]
                )
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > _MAX_WHEEL_BYTES):
                raise DependencyAdmissionError(["selected wheel transfer exceeds size limit"])
            size = 0
            chunks: list[bytes] = []
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_WHEEL_BYTES or time.monotonic() - started > 60:
                    raise DependencyAdmissionError(
                        ["selected wheel transfer exceeded size/time bound"]
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        except (OSError, http.client.HTTPException) as error:
            raise DependencyAdmissionError(["selected wheel download unavailable"]) from error
        finally:
            connection.close()
