"""Discover bounded published snapshot metadata without silently admitting its raw inputs."""

from __future__ import annotations

# standard library imports
import re
import stat
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from market_data.datasets.books import BookDatasetManifest
from market_data.datasets.manifests import DatasetManifest
from serialization import DomainCodec


class SnapshotCatalog:
    """List immutable manifest identities; complete source verification belongs to readers.

    The caller excludes external mutation during discovery, as for SnapshotStore.
    Hidden staging entries are ignored. No latest alias or acquisition is performed.
    """

    def __init__(self, root: Path) -> None:
        """Bind an existing local snapshot directory.

        Args:
            root: Provisioned publication root containing content-addressed directories.
        """
        self._root = root

    def discover(
        self, *, max_entries: int, max_bytes: int
    ) -> tuple[DatasetManifest | BookDatasetManifest, ...]:
        """Inspect supported manifests in deterministic identity order within explicit bounds.

        Args:
            max_entries: Positive directory-entry scan cap, including ignored staging entries.
            max_bytes: Positive aggregate manifest-byte budget, excluding raw/canonical files.

        Returns:
            Typed manifests with instruments, requests, policies and native units. These are
            metadata candidates, not proof that referenced inputs remain available or valid.

        Raises:
            ValueError: Bounds, file kinds, manifest schemas or content identities are invalid.
            OSError: The root or a committed manifest is unavailable.
        """
        if any(type(value) is not int or value <= 0 for value in (max_entries, max_bytes)):
            raise ValueError("catalog requires positive entry and manifest-byte limits")
        manifests: list[DatasetManifest | BookDatasetManifest] = []
        remaining = max_bytes
        codec = DomainCodec()
        for count, directory in enumerate(self._root.iterdir(), 1):
            if count > max_entries:
                raise ValueError("catalog exceeds max_entries; narrow the publication root")
            if re.fullmatch(r"[0-9a-f]{64}", directory.name) is None:
                continue
            path = directory / "manifest.json"
            if not stat.S_ISDIR(directory.lstat().st_mode) or not stat.S_ISREG(
                path.lstat().st_mode
            ):
                raise ValueError("catalog requires regular manifests in non-symlink directories")
            with path.open("rb") as source:
                payload = source.read(remaining + 1)
            remaining -= len(payload)
            if remaining < 0:
                raise ValueError("catalog exceeds aggregate max_bytes")
            fields = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
            version = codec.decode_json(fields.get("schema_version", b"null"), str)
            manifest: DatasetManifest | BookDatasetManifest
            if version == "book-dataset-v1":
                manifest = codec.decode_json(payload, BookDatasetManifest)
            else:
                manifest = codec.decode_json(payload, DatasetManifest)
            if manifest.identity != directory.name:
                raise ValueError("catalog manifest identity mismatch")
            manifests.append(manifest)
        return tuple(sorted(manifests, key=self._identity))

    @staticmethod
    def _identity(manifest: DatasetManifest | BookDatasetManifest) -> str:
        """Order candidate metadata without implying chronology or availability."""
        return manifest.identity
