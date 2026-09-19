"""Exit an installed snapshot publisher at a selected persistence boundary."""

from __future__ import annotations

# standard library imports
import argparse
import os
from pathlib import Path
from unittest.mock import patch

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import DatasetManifest, SnapshotStore
from market_data.storage import RawStore
from serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Type saved input locations and the selected interruption boundary."""

    root: Path
    raw: Path
    inputs: Path
    point: str


class _InterruptedPublication:
    """Retain real filesystem operations and terminate without Python cleanup."""

    def __init__(self, point: str) -> None:
        """Bind a partial-write, before-rename or after-rename interruption.

        Args:
            point: One selected abrupt-exit boundary.
        """
        self._point = point
        self._rename = os.rename
        self._fsync = os.fsync

    def fsync(self, descriptor: int) -> None:
        """Synchronize a staged file and optionally die before writing the rest."""
        self._fsync(descriptor)
        if self._point == "partial":
            os._exit(75)

    def rename(self, source: Path, destination: Path) -> None:
        """Exit immediately before or after the single snapshot visibility boundary."""
        if self._point == "after":
            self._rename(source, destination)
        os._exit(75)


def main() -> None:
    """Run an installed publisher against explicit saved synthetic inputs.

    Raises:
        RuntimeError: The requested interruption did not occur.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "raw", "inputs"):
        parser.add_argument(name, type=Path)
    parser.add_argument("point", choices=("partial", "before", "after"))
    arguments = parser.parse_args(namespace=_Arguments())
    manifest = DomainCodec().decode_json(
        (arguments.inputs / "manifest.json").read_bytes(), DatasetManifest
    )
    payloads = tuple((arguments.inputs / part.sha256).read_bytes() for part in manifest.partitions)
    interruption = _InterruptedPublication(arguments.point)
    with (
        patch("market_data.datasets.snapshots.os.fsync", interruption.fsync),
        patch("market_data.datasets.snapshots.os.rename", interruption.rename),
    ):
        SnapshotStore(arguments.root, RawStore(arguments.raw), readers=SourceAdapters()).publish(
            manifest, payloads, max_bytes=262_144
        )
    raise RuntimeError("snapshot publication did not reach the requested interruption")


if __name__ == "__main__":
    main()
