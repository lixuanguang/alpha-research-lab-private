"""Define explicit source capabilities required to reproduce dataset admission."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

# project library imports
from market_data.contracts import (
    BookObservation,
    ByteReader,
    OccurrenceVerifier,
    PublicSources,
    SavedPartitionReader,
    SourceRequest,
)

if TYPE_CHECKING:
    # project library imports
    from market_data.acquisition import AcquisitionManifest
    from market_data.datasets.books import BookInput


class DatasetReaders(PublicSources, Protocol):
    """Supply selected saved readers and native verifiers without choosing an adapter."""

    def saved(self, manifest: AcquisitionManifest) -> tuple[SavedPartitionReader, ...]:
        """Bind validated readers to every selected source partition.

        Args:
            manifest: Retained acquisition and source-specific completion evidence.

        Returns:
            Explicit supported readers in original partition order.
        """
        ...

    def verifier(self, request: SourceRequest) -> OccurrenceVerifier:
        """Bind source re-decoding to one selected request.

        Args:
            request: Strict source selection and original identity.

        Returns:
            Verifier for the retained native bytes and clocks.
        """
        ...

    def books(self, selection: BookInput, store: ByteReader) -> Iterator[BookObservation]:
        """Reconstruct a bounded native prefix from fully verified original bytes.

        Args:
            selection: Explicit original recording or archive and prefix bound.
            store: Immutable byte reader verifying complete retained objects.

        Returns:
            Whole-message observations with original lineage and availability.
        """
        ...
