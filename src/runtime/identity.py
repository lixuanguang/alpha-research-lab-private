"""Identify only distribution-owned runtime files under the two retained hash contracts."""

from __future__ import annotations

# standard library imports
import csv
import hashlib
from importlib.metadata import distribution, version
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from typing import ClassVar

# project library imports
from serialization import DomainCodec


class RuntimeFiles:
    """Bound installed identity to declared package files, excluding neighboring installations."""

    roots: ClassVar[tuple[str, ...]] = (
        "accounting",
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

    @classmethod
    def inputs(cls) -> tuple[tuple[str, Path], ...]:
        """Discover owned source and resources from installed distribution metadata.

        Returns:
            Stable relative names and absolute existing paths for owned runtime inputs.

        Raises:
            ValueError: Metadata is absent, a required file is missing or a root is shadowed.
        """
        installed = distribution("alpha-research-lab")
        # Distribution.files in Python 3.14 silently filters missing files. Read
        # the wheel inventory itself so a deleted implementation cannot disappear
        # from the fingerprint without an explicit failure.
        record = installed.read_text("RECORD")
        if not record:
            raise ValueError("runtime distribution has no installed wheel inventory")
        files: dict[str, Path] = {}
        for row in csv.reader(record.splitlines(), strict=True):
            if len(row) != 3 or not row[0]:
                raise ValueError("invalid runtime distribution inventory row")
            entry = PurePosixPath(row[0])
            if entry.parts[0] not in cls.roots:
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
        required = {f"{root}/{name}" for root in cls.roots for name in ("__init__.py", "py.typed")}
        required.add("financial_units/default_currencies.json")
        if required - files.keys():
            raise ValueError(f"missing required runtime inputs: {sorted(required - files.keys())}")
        for root in cls.roots:
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
            (name, version(name)) for name in ("alpha-research-lab", "msgspec", "pydantic")
        )
        return hashlib.sha256(DomainCodec().encode_json((inputs, dependencies))).hexdigest()
