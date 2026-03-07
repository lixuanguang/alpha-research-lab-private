"""ArtifactStore — object-store-style abstraction for run artifacts.

All research-plane runners (feature, backtest, evaluate, optimize, live)
should write artifacts through this interface rather than performing ad-hoc
filesystem writes.

Interface
---------
- :class:`ArtifactStore`      — structural ``Protocol`` (``put / get / exists / list``)
- :class:`FilesystemArtifactStore` — production implementation backed by the
  canonical run-artifact layout defined in :mod:`alpha_core.research.artifact_paths`.

Path contract
-------------
Every artifact is addressed by ``(run_id, key)`` and resolves to::

    {storage_root}/runs/{run_id}/stage_outputs/{key}

This matches :func:`alpha_core.research.artifact_paths.artifact_key_path` exactly,
keeping all existing artifact locations backward compatible.

Idempotency / overwrite semantics
----------------------------------
- ``put(..., overwrite=False)`` (default) raises :exc:`ArtifactExistsError`
  when the artifact already exists, enforcing immutable run outputs.
- ``put(..., overwrite=True)`` replaces the artifact atomically via a
  ``{path}.tmp`` rename so readers never observe a partial write.
- ``prepare_path(..., overwrite=False)`` similarly guards against accidental
  re-runs overwriting completed artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import alpha_core.research.artifact_paths as artifact_paths

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ArtifactExistsError(FileExistsError):
    """Raised when attempting to overwrite an artifact without ``overwrite=True``."""


class ArtifactNotFoundError(KeyError):
    """Raised by :meth:`ArtifactStore.get` when the key does not exist."""


# ---------------------------------------------------------------------------
# Protocol (abstract interface)
# ---------------------------------------------------------------------------


@runtime_checkable
class ArtifactStore(Protocol):
    """Minimal object-store contract for run artifacts.

    Implementations must be safe to share across runners within the same
    process; they must not assume a specific serialisation format.
    """

    def put(
        self,
        run_id: str,
        key: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> None:
        """Write raw bytes under ``(run_id, key)``.

        Parameters
        ----------
        run_id:
            Unique identifier for the run that produced this artifact.
        key:
            Logical artifact name (e.g. ``"features.parquet"``).  May use
            ``/`` to create subdirectories.
        data:
            Raw bytes to persist.
        overwrite:
            When ``False`` (default) raise :exc:`ArtifactExistsError` if the
            artifact already exists.  When ``True`` replace it atomically.
        """
        ...

    def get(self, run_id: str, key: str) -> bytes:
        """Return the raw bytes stored under ``(run_id, key)``.

        Raises
        ------
        ArtifactNotFoundError
            When the artifact does not exist.
        """
        ...

    def exists(self, run_id: str, key: str) -> bool:
        """Return ``True`` if ``(run_id, key)`` has been stored."""
        ...

    def list(self, run_id: str) -> list[str]:
        """Return all artifact keys stored under *run_id*, sorted."""
        ...


# ---------------------------------------------------------------------------
# Filesystem implementation
# ---------------------------------------------------------------------------


class FilesystemArtifactStore:
    """Artifacts stored under the canonical ``{storage_root}/runs/{run_id}/stage_outputs/``
    directory tree.

    Designed to be injected into runners so they never construct paths ad-hoc.

    Parameters
    ----------
    storage_root:
        Shared storage root used by all research runners (the same value
        passed to ``DatasetBuilder``, ``FeatureRunner``, etc.).
    """

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    # ------------------------------------------------------------------
    # ArtifactStore protocol
    # ------------------------------------------------------------------

    def put(
        self,
        run_id: str,
        key: str,
        data: bytes,
        *,
        overwrite: bool = False,
    ) -> None:
        """Write *data* atomically to the artifact path for ``(run_id, key)``.

        Uses a ``.tmp`` rename so partial writes are never visible.
        """
        path = self._resolve(run_id, key)
        if path.exists() and not overwrite:
            raise ArtifactExistsError(
                f"Artifact '{key}' already exists for run '{run_id}' at '{path}'. "
                "Pass overwrite=True to replace it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, run_id: str, key: str) -> bytes:
        """Return raw bytes for ``(run_id, key)``."""
        path = self._resolve(run_id, key)
        if not path.exists():
            raise ArtifactNotFoundError(
                f"Artifact '{key}' not found for run '{run_id}' (looked at '{path}')."
            )
        return path.read_bytes()

    def exists(self, run_id: str, key: str) -> bool:
        """Return whether ``(run_id, key)`` is present on disk."""
        return self._resolve(run_id, key).exists()

    def list(self, run_id: str) -> list[str]:
        """Return sorted artifact keys stored under *run_id*."""
        stage_outputs = artifact_paths.stage_outputs_path(self._storage_root, run_id)
        if not stage_outputs.exists():
            return []
        return sorted(
            str(p.relative_to(stage_outputs))
            for p in stage_outputs.rglob("*")
            if p.is_file()
        )

    # ------------------------------------------------------------------
    # Filesystem-specific helpers (not part of Protocol)
    # ------------------------------------------------------------------

    def prepare_path(
        self,
        run_id: str,
        key: str,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Return the resolved path for ``(run_id, key)`` with parent dirs created.

        Use this when you need to pass a :class:`~pathlib.Path` to a library
        (e.g. ``pyarrow.parquet.write_table``) rather than writing raw bytes.

        Parameters
        ----------
        overwrite:
            When ``False`` (default) raises :exc:`ArtifactExistsError` if the
            path already exists.

        Returns
        -------
        Path
            The destination path, guaranteed to have its parent directory.
        """
        path = self._resolve(run_id, key)
        if path.exists() and not overwrite:
            raise ArtifactExistsError(
                f"Artifact '{key}' already exists for run '{run_id}' at '{path}'. "
                "Pass overwrite=True to replace it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, run_id: str, key: str) -> Path:
        """Return the path for an **existing** artifact.

        Raises
        ------
        ArtifactNotFoundError
            When the artifact does not exist.
        """
        path = self._resolve(run_id, key)
        if not path.exists():
            raise ArtifactNotFoundError(
                f"Artifact '{key}' not found for run '{run_id}' (looked at '{path}')."
            )
        return path

    @property
    def storage_root(self) -> Path:
        """The storage root this store is backed by."""
        return self._storage_root

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _resolve(self, run_id: str, key: str) -> Path:
        return artifact_paths.artifact_key_path(self._storage_root, run_id, key)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "ArtifactExistsError",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "FilesystemArtifactStore",
]
