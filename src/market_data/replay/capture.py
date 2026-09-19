"""Consume verified saved journals through shared message-boundary reconstruction."""

# standard library imports
from collections.abc import Callable
from pathlib import Path

# project library imports
from configuration import CaptureConfig
from market_data.books import CaptureReplay, NativeBook
from market_data.contracts import CaptureRequest
from market_data.storage import CaptureJournal
from serialization import DomainCodec


class SavedCapture:
    """Read durable completed or explicitly interrupted native recordings."""

    @classmethod
    def read(
        cls,
        root: Path,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        completed: bool = True,
    ) -> CaptureReplay:
        """Replay a verified completed capture, or explicitly inspect an interrupted prefix.

        Args:
            book_factory: Explicit native state constructor reused for every epoch.
            root: Unique caller-owned local recording directory.
            completed: Require a verified manifest, or explicitly inspect an interrupted prefix.

        Returns:
            Validated configuration, credentials or replay state owned by this boundary.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        replay = CaptureReplay(request.config, book_factory=book_factory)
        for record in CaptureJournal(root, request).records(completed=completed):
            if not completed and record.kind == "end":
                continue  # A journal end without verified publication is still interrupted.
            if not completed and replay.epoch < 0 and record.kind == "gap":
                replay.epoch = record.epoch  # Death before the first durable session.
            replay.apply(record)
        if completed and not replay.ended:
            raise ValueError("completed capture lacks terminal record")
        return replay
