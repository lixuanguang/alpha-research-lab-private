"""Verify a sealed native segment chain independently of its live collector."""

from __future__ import annotations

# standard library imports
import time
from collections.abc import Callable
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from configuration import CaptureConfig
from market_data.books import CaptureReplay, NativeBook
from market_data.contracts import CaptureRunRequest
from market_data.storage import CaptureRunJournal
from serialization import DomainCodec


class SavedCaptureRun:
    """Replay exact original journals and compare every live summary identity and count."""

    @classmethod
    def read(
        cls,
        root: Path,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        max_seconds: int,
    ) -> CaptureReplay:
        """Verify a complete saved run under an explicit finite offline deadline.

        Args:
            root: Original immutable run request, segment chain and final live summary.
            book_factory: Installed native reconstruction capability for every connection epoch.
            max_seconds: Explicit 1..7200-second verification envelope, separate from collection.

        Returns:
            Independently reconstructed state equal to every retained live summary boundary.

        Raises:
            ValueError: A chain, terminal boundary or exact summary differs.
            TimeoutError: Verification exceeds its declared offline envelope.
        """
        if type(max_seconds) is not int or not 1 <= max_seconds <= 7200:
            raise ValueError("capture run verification requires a finite 1..7200-second limit")
        deadline = time.monotonic() + max_seconds
        codec = DomainCodec()
        request = codec.decode_json((root / "run-request.json").read_bytes(), CaptureRunRequest)
        fields = msgspec.json.decode(
            (root / "run-summary.json").read_bytes(), type=dict[str, msgspec.Raw]
        )
        if fields.get("run_identity") != msgspec.Raw(codec.encode_json(request.identity)):
            raise ValueError("capture run summary differs from its original request")
        replay = CaptureReplay(request.config, book_factory=book_factory)
        total_bytes = total_records = 0
        for journal in CaptureRunJournal(root, request).segments():
            total_bytes += journal.committed_cursor().offset
            for record in journal.records(completed=True):
                if time.monotonic() > deadline:
                    raise TimeoutError("capture run verification deadline")
                replay.apply(record)
                total_records += 1
        if (
            not replay.ended
            or total_bytes > request.window.max_bytes
            or replay.messages > request.window.max_messages
        ):
            raise ValueError("saved capture run lacks an admitted finite terminal boundary")
        for key, value in {
            **replay.summary(),
            "saved_bytes": total_bytes,
            "saved_records": total_records,
        }.items():
            if fields.get(key) != msgspec.Raw(codec.encode_json(value)):
                raise ValueError(f"saved capture run differs from live summary at {key}")
        return replay
