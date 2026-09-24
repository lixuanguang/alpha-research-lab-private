"""Expose the market data storage public contract."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from market_data.storage.journal import CaptureJournal
from market_data.storage.objects import RawFiles
from market_data.storage.raw import RawStore

if TYPE_CHECKING:
    # project library imports
    from market_data.storage.versions import DatasetVersion, LakeFSStorage, VersionedObject


def __getattr__(name: str) -> object:
    """Load the optional lakeFS adapter only for versioned-store consumers."""
    if name in {"DatasetVersion", "LakeFSStorage", "VersionedObject"}:
        # project library imports
        from market_data.storage import versions

        exports: dict[str, object] = {
            "DatasetVersion": versions.DatasetVersion,
            "LakeFSStorage": versions.LakeFSStorage,
            "VersionedObject": versions.VersionedObject,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "CaptureJournal",
    "DatasetVersion",
    "LakeFSStorage",
    "RawFiles",
    "RawStore",
    "VersionedObject",
]
