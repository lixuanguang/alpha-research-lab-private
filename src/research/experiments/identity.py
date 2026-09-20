"""Separate reproducible experiment inputs from execution clocks and generated results."""

from __future__ import annotations

# standard library imports
import hashlib
import platform
from importlib.metadata import distributions
from typing import Literal

# project library imports
from research.experiments.splits import TemporalSplit
from serialization import DomainCodec, WireRecord


class Fingerprint(WireRecord, frozen=True, kw_only=True):
    """Name immutable input or component bytes using a SHA-256 digest."""

    name: str
    sha256: str

    def __post_init__(self) -> None:
        """Reject absent names and malformed content digests."""
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("fingerprint requires a nonempty name")
        if (
            type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError("fingerprint requires a lowercase SHA-256")


class ExperimentSpec(WireRecord, frozen=True, kw_only=True):
    """Retain semantic inputs without output paths, attempt clocks or generated results.

    Parameters are resolved non-secret strings (including exact numerical text).
    Named inputs/components, parameters and seeds are unordered mappings. Family
    scopes selection history and the frozen holdout in one retained store.
    """

    schema_version: Literal["experiment-spec-v1"] = "experiment-spec-v1"
    family: str
    inputs: tuple[Fingerprint, ...]
    components: tuple[Fingerprint, ...]
    parameters: tuple[tuple[str, str], ...]
    seeds: tuple[tuple[str, int], ...]
    environment_sha256: str
    split: TemporalSplit

    def __post_init__(self) -> None:
        """Validate complete semantic identity before any attempt is retained."""
        if self.schema_version != "experiment-spec-v1":
            raise ValueError("unsupported experiment schema")
        Fingerprint(name=self.family, sha256=self.environment_sha256)
        for items in (self.inputs, self.components):
            if type(items) is not tuple or not items:
                raise ValueError("experiment requires immutable inputs and components")
            for item in items:
                if type(item) is not Fingerprint:
                    raise TypeError("experiment requires Fingerprint records")
                item.__post_init__()
            if len({item.name for item in items}) != len(items):
                raise ValueError("fingerprint names must be unique within their role")
        self._validate_pairs(self.parameters, is_seed=False)
        self._validate_pairs(self.seeds, is_seed=True)
        if type(self.split) is not TemporalSplit:
            raise TypeError("experiment requires a temporal split")
        self.split.__post_init__()

    @staticmethod
    def _validate_pairs(pairs: object, *, is_seed: bool) -> None:
        """Validate direct construction as strictly as typed wire decoding."""
        if not isinstance(pairs, tuple):
            raise TypeError("named values must be a tuple")
        names: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("named values require name/value pairs")
            name, value = pair
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError("named values require unique nonempty names")
            names.add(name)
            if is_seed:
                if type(value) is not int or value < 0:
                    raise ValueError("seed must be a nonnegative integer")
            elif type(value) is not str:
                raise ValueError("parameters must retain explicit text values")

    @property
    def identity(self) -> str:
        """Hash semantic input choices, implementation, environment, split and random seeds.

        Returns:
            Reproducible SHA-256, independent of mapping order and execution location.
        """
        self.__post_init__()
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    self.schema_version,
                    self.family,
                    tuple(sorted((item.name, item.sha256) for item in self.inputs)),
                    tuple(sorted((item.name, item.sha256) for item in self.components)),
                    tuple(sorted(self.parameters)),
                    tuple(sorted(self.seeds)),
                    self.environment_sha256,
                    self.split.identity,
                )
            )
        ).hexdigest()

    @staticmethod
    def installed_environment() -> str:
        """Fingerprint the actual interpreter, platform and installed distribution versions.

        Returns:
            Environment SHA-256; the application separately fingerprints owned code bytes.
            This is reproducibility identity, not artifact trust or dependency admission.
        """
        versions = sorted((item.metadata["Name"].lower(), item.version) for item in distributions())
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
