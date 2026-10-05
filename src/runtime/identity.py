"""Identify distribution-owned runtime files and the code a deployed candidate runs on."""

from __future__ import annotations

# standard library imports
import csv
import hashlib
import platform
from importlib.metadata import PackageNotFoundError, distribution, version
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from typing import ClassVar

# project library imports
from serialization import DomainCodec, WireRecord


class RuntimeFiles:
    """Bound installed identity to declared package files, excluding neighboring installations."""

    roots: ClassVar[tuple[str, ...]] = (
        "accounting",
        "execution",
        "portfolio",
        "risk",
        "simulation",
        "strategies",
        "applications",
        "configuration",
        "financial_units",
        "market_data",
        "reference_data",
        "research",
        "runtime",
        "serialization",
        "telemetry",
    )
    operating_roots: ClassVar[dict[str, tuple[str, ...]]] = {
        "alpha-research-contracts": (
            "configuration",
            "financial_units",
            "reference_data",
            "risk",
            "serialization",
            "strategies",
        ),
        "alpha-research-collector": ("applications", "market_data", "runtime", "telemetry"),
        "alpha-research-execution": (
            "applications",
            "execution",
            "accounting",
            "portfolio",
            "runtime",
            "telemetry",
        ),
    }

    @classmethod
    def distributions(cls) -> tuple[str, ...]:
        """Choose the complete research wheel or an independently installed operating pair."""
        try:
            distribution("alpha-research-lab")
        except PackageNotFoundError:
            try:
                distribution("alpha-research-collector")
            except PackageNotFoundError:
                return ("alpha-research-contracts", "alpha-research-execution")
            return ("alpha-research-contracts", "alpha-research-collector")
        return ("alpha-research-lab",)

    @classmethod
    def inputs(cls) -> tuple[tuple[str, Path], ...]:
        """Discover owned source and resources from installed distribution metadata.

        Returns:
            Stable relative names and absolute existing paths for owned runtime inputs.

        Raises:
            ValueError: Metadata is absent, a required file is missing or a root is shadowed.
        """
        files: dict[str, Path] = {}
        required: set[str] = set()
        selected = cls.distributions()
        for distribution_name in selected:
            installed = distribution(distribution_name)
            roots = (
                cls.roots
                if distribution_name == "alpha-research-lab"
                else cls.operating_roots[distribution_name]
            )
            required.update(
                f"{root}/{name}" for root in roots for name in ("__init__.py", "py.typed")
            )
            # Distribution.files in Python 3.14 silently filters missing files. Read
            # the wheel inventory itself so deletion cannot hide from the fingerprint.
            record = installed.read_text("RECORD")
            if not record:
                raise ValueError("runtime distribution has no installed wheel inventory")
            for row in csv.reader(record.splitlines(), strict=True):
                if len(row) != 3 or not row[0]:
                    raise ValueError("invalid runtime distribution inventory row")
                entry = PurePosixPath(row[0])
                if entry.parts[0] not in roots:
                    continue
                if entry.suffix not in {".py", ".json"} and entry.name != "py.typed":
                    continue
                if any(part in (".", "..") for part in entry.parts) or entry.is_absolute():
                    raise ValueError("runtime distribution contains an unsafe owned path")
                if entry.as_posix() in files:
                    raise ValueError(f"duplicate runtime identity input: {entry}")
                path = Path(str(installed.locate_file(entry)))
                if not path.is_file():
                    raise ValueError(f"missing runtime identity input: {entry}")
                files[entry.as_posix()] = path
        required.add("financial_units/default_currencies.json")
        if required - files.keys():
            raise ValueError(f"missing required runtime inputs: {sorted(required - files.keys())}")
        for root in {name.split("/", 1)[0] for name in required}:
            spec = find_spec(root)
            if (
                spec is None
                or spec.origin is None
                or Path(spec.origin).resolve() != files[f"{root}/__init__.py"].resolve()
            ):
                raise ValueError(f"runtime package is shadowed or absent: {root}")
        return tuple(sorted(files.items()))


class InstalledIdentity:
    """Fingerprint installed Python source used by capture, preserving its source-only contract."""

    @staticmethod
    def sha256() -> str:
        """Hash owned Python modules in stable relative-path order.

        Returns:
            SHA-256 of installed Python source bytes and relative paths.
        """
        digest = hashlib.sha256()
        for name, path in RuntimeFiles.inputs():
            if path.suffix == ".py":
                digest.update(name.encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()


class ImplementationIdentity:
    """Identify resolved-job source, resources and selected serialization dependencies."""

    @staticmethod
    def sha256() -> str:
        """Fingerprint owned Python, JSON and typing assets plus retained dependency versions.

        Returns:
            Deterministic SHA-256 for newly resolved jobs and canonical normalization.
        """
        inputs = [
            (name, hashlib.sha256(path.read_bytes()).hexdigest())
            for name, path in RuntimeFiles.inputs()
        ]
        dependencies = tuple(
            (name, version(name)) for name in (*RuntimeFiles.distributions(), "msgspec", "pydantic")
        )
        return hashlib.sha256(DomainCodec().encode_json((inputs, dependencies))).hexdigest()


class CandidateRuntimeManifest(WireRecord, frozen=True):
    """List the platform files and third-party distributions a deployed candidate runs on."""

    modules: tuple[str, ...]
    distributions: tuple[str, ...]


class CandidateRuntime:
    """Identify the platform code and dependency versions a packaged candidate runs on.

    A candidate is packaged in the research environment and runs in the signed
    paper-services release, which ships only part of the platform. Both identities
    cover exactly what that release ships, listed in ``candidate_runtime.json``:
    its platform files by name and bytes, and its third-party distribution versions
    with the interpreter and platform. They agree exactly when the candidate would
    run on the same code and dependency versions.
    """

    @staticmethod
    def manifest() -> CandidateRuntimeManifest:
        """Read the shipped list of candidate runtime files and distributions."""
        payload = (Path(__file__).parent / "candidate_runtime.json").read_bytes()
        return DomainCodec().decode_json(payload, CandidateRuntimeManifest)

    @classmethod
    def code_sha256(cls) -> str:
        """Hash every listed platform file's name and bytes as installed here.

        Raises:
            ValueError: A listed file is not installed in this environment.
        """
        digest = hashlib.sha256()
        for name in cls.manifest().modules:
            spec = find_spec(name.split("/", 1)[0])
            if spec is None or spec.origin is None:
                raise ValueError(f"candidate runtime package is absent: {name}")
            path = Path(spec.origin).parent.parent / name
            if not path.is_file():
                raise ValueError(f"candidate runtime file is not installed: {name}")
            digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    @classmethod
    def environment_sha256(cls) -> str:
        """Hash the interpreter, platform and listed distribution versions installed here."""
        versions = tuple((name, version(name)) for name in cls.manifest().distributions)
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    platform.python_implementation(),
                    platform.python_version(),
                    platform.platform(),
                    platform.machine(),
                    versions,
                )
            )
        ).hexdigest()
