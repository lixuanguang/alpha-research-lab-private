"""Admit bounded saved native book histories without granting causal or execution use."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from itertools import zip_longest
from pathlib import Path

# project library imports
from configuration import CaptureConfig
from market_data.books import BookProjection, CaptureReplay, NativeBook
from market_data.contracts import BookObservation, CaptureRecord
from market_data.datasets import BookHistory, BookInput, DatasetReaders
from market_data.storage import RawStore


class BookCapture(CaptureReplay):
    """Retain a byte-capped live canonical prefix and diagnose its first saved-input divergence."""

    def __init__(
        self,
        config: CaptureConfig,
        max_records: int,
        *,
        readers: DatasetReaders,
        book_factory: Callable[[CaptureConfig], NativeBook],
    ) -> None:
        """Bind native reconstruction and a finite publication consumer.

        Args:
            book_factory: Explicit native state constructor reused for each capture epoch.
            readers: Selected readers and native re-decoders for complete verification.
            config: Validated capture settings, including the canonical byte budget.
            max_records: Maximum original raw positions in the compared prefix.

        Raises:
            ValueError: The prefix bound is unsupported.
        """
        config.__post_init__()
        if type(max_records) is not int or not 1 <= max_records <= 10_000:
            raise ValueError("book capture requires 1..10000 raw records")
        super().__init__(config, book_factory=book_factory)
        self._readers = readers
        self._limit = max_records
        self._observations: list[BookObservation] = []
        self._bytes = 0

    def apply(self, record: CaptureRecord) -> str:
        """Apply and normalize after durable append, retaining only the selected prefix.

        Args:
            record: Whole original frame or session transition.

        Returns:
            The unchanged native classification.

        Raises:
            ValueError: Retained canonical states exceed the configured byte budget.
        """
        outcome = super().apply(record)
        if len(self._observations) < self._limit:
            row = BookProjection.capture(len(self._observations), record, outcome, self)
            self._bytes += len(self._codec.encode_json(row))
            if self._bytes > self.config.max_bytes:
                raise ValueError("captured book prefix exceeds max_bytes")
            self._observations.append(row)
        return outcome

    def verify(self, root: Path) -> None:
        """Retain the live prefix and compare every field with independent saved normalization.

        Args:
            root: Completed recording directory containing exact raw bytes and request.

        Raises:
            ValueError: Admission fails or a boundary differs; first-divergence.json retains
                the original position and both observations beside the saved raw input.
        """
        selected = BookInput.read(root, max_records=self._limit)
        expected = BookHistory(input=selected, observations=tuple(self._observations))
        payload = self._codec.encode_json(expected)
        if len(payload) > self.config.max_bytes:
            raise ValueError("captured book envelope exceeds max_bytes")
        with (root / "book-prefix.json").open("xb") as output:
            output.write(payload)
        canonical = selected.admit(
            RawStore(root), readers=self._readers, max_bytes=self.config.max_bytes
        ).require_canonical()
        actual = self._codec.decode_json(canonical, BookHistory)
        for position, (left, right) in enumerate(
            zip_longest(expected.observations, actual.observations, fillvalue=None)
        ):
            if left != right:
                with (root / "first-divergence.json").open("xb") as output:
                    output.write(self._codec.encode_json((selected, position, left, right)))
                raise ValueError(f"captured book differs at raw position {position}")
