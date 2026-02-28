"""F1 scaffold tests — verify the package is importable and versioned."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re

import alpha_core


def _raise_package_not_found(_: str) -> str:
    raise importlib_metadata.PackageNotFoundError


def test_alpha_core_importable() -> None:
    """alpha_core package can be imported."""
    assert hasattr(alpha_core, "__version__")


def test_version_format() -> None:
    """Version string follows a PEP 440-compatible pattern."""
    assert re.match(
        r"^\d+(\.\d+){1,2}((a|b|rc)\d+|\.post\d+|\.dev\d+)?(\+[a-z0-9][a-z0-9.]*)?$",
        alpha_core.__version__,
    ), (
        f"Version '{alpha_core.__version__}' does not look like a valid "
        "release/dev/build version"
    )


def test_extract_commit_hash_parses_local_version() -> None:
    """Commit hash is parsed when setuptools_scm local metadata is present."""
    assert alpha_core._extract_commit_hash("0.1.0.dev3+g1234abc.d20260228") == "1234abc"


def test_extract_commit_hash_returns_none_without_hash() -> None:
    """Commit hash is None when local version metadata has no git hash token."""
    assert alpha_core._extract_commit_hash("0.1.0.dev3+local") is None


def test_resolve_version_returns_fallback_when_dist_missing(monkeypatch) -> None:
    """Fallback version is used when package metadata is not installed."""
    monkeypatch.setattr(alpha_core.importlib_metadata, "version", _raise_package_not_found)

    assert alpha_core._resolve_version() == "0.0.0+unknown"


def test_resolve_version_uses_distribution_metadata(monkeypatch) -> None:
    """Version resolver returns metadata-provided version when available."""
    monkeypatch.setattr(alpha_core.importlib_metadata, "version", lambda _: "1.2.3")

    assert alpha_core._resolve_version() == "1.2.3"
