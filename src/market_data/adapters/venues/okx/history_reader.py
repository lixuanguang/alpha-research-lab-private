"""Verify bounded native archives and replay original L2 rows in stored order."""

from __future__ import annotations

# standard library imports
import gzip
import hashlib
import tarfile
import time
from pathlib import Path

# project library imports
from configuration import OKXHistoryConfig
from market_data.adapters.venues.okx.book import OKXBook
from serialization import DomainCodec


class OKXArchiveReader:
    """Validate a single regular tar member; no filesystem extraction or clock fabrication."""

    def __init__(self, config: OKXHistoryConfig) -> None:
        """Bind native identity and compressed, expanded, row and replay bounds.

        Args:
            config: Explicit single-day archive and bounded replay selection.
        """
        self.config = config

    def validate(self, path: Path, deadline: float) -> int:
        """Read through gzip EOF to verify CRC and expanded size, then validate tar structure.

        Args:
            path: Original complete compressed archive file.
            deadline: Monotonic deadline shared with acquisition or replay.

        Returns:
            Total expanded representation size, including tar framing.

        Raises:
            ValueError: Size, compression, member count, type or native filename is invalid.
            TimeoutError: The bounded validation duration expires.
        """
        if not 0 < path.stat().st_size <= self.config.max_bytes:
            raise ValueError("OKX compressed archive size outside budget")
        size = 0
        with gzip.open(path, "rb") as source:
            while chunk := source.read(min(1_048_576, self.config.max_expanded_bytes - size + 1)):
                size += len(chunk)
                if size > self.config.max_expanded_bytes:
                    raise ValueError("OKX expanded archive exceeds byte budget")
                if time.monotonic() > deadline:
                    raise TimeoutError("OKX archive validation duration exhausted")
        members = 0
        with tarfile.open(path, mode="r|gz") as archive:
            for member in archive:
                members += 1
                if time.monotonic() > deadline:
                    raise TimeoutError("OKX tar validation duration exhausted")
                if (
                    members != 1
                    or not member.isfile()
                    or member.name != self.config.filename.removesuffix(".tar.gz") + ".data"
                    or not 0 < member.size <= self.config.max_expanded_bytes
                ):
                    raise ValueError(
                        "OKX archive must contain exactly the selected regular data file"
                    )
        if members != 1:
            raise ValueError("empty OKX archive")
        return size

    def replay(self, path: Path) -> dict[str, object]:
        """Replay a bounded prefix after verifying the entire saved archive's integrity.

        Args:
            path: Verified raw-store artifact or explicit complete source file.

        Returns:
            Exact state/trace identities, source interval and explicit coverage limitations.

        Raises:
            ValueError: A source row, file boundary or day identity is invalid.
            TimeoutError: The bounded replay duration expires before verification finishes.
        """
        deadline = time.monotonic() + self.config.duration_seconds
        expanded = self.validate(path, deadline)
        book, trace, codec = OKXBook(self.config.symbol), hashlib.sha256(), DomainCodec()
        count, snapshots, updates = 0, 0, 0
        first: str | None = None
        reason = "archive_end"
        with tarfile.open(path, mode="r|gz") as archive:
            member = archive.next()
            source = None if member is None else archive.extractfile(member)
            if source is None:
                raise ValueError("missing OKX archive data")
            with source:
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("OKX replay duration exhausted before selected prefix")
                    raw = source.readline(self.config.max_line_bytes + 1)
                    if not raw:
                        break
                    if count == self.config.max_records:
                        reason = "record_limit"
                        break
                    if len(raw) > self.config.max_line_bytes or not raw.endswith(b"\n"):
                        raise ValueError("OKX archive row exceeds budget or has interrupted tail")
                    outcome = book.apply_archive(raw)
                    if (
                        book.source_time is not None
                        and not self.config.start_ms
                        <= int(book.source_time)
                        < self.config.start_ms + 86_400_000
                    ):
                        raise ValueError("OKX archive source time outside requested UTC day")
                    count += 1
                    snapshots += outcome == "snapshot"
                    updates += outcome == "update"
                    if count == 1:
                        first = book.source_time
                    trace.update(codec.encode_json((count, raw, outcome, book.identity)))
        return {
            "venue": "okx",
            "symbol": self.config.symbol,
            "instrument_id": str(self.config.instrument_id),
            "representation": "L2",
            "mode": "historical",
            "depth": 400,
            "orders": None,
            "records": count,
            "snapshots": snapshots,
            "updates": updates,
            "levels": len(book.bids) + len(book.asks),
            "source_sequence": None,
            "first_source_ms": first,
            "last_source_ms": book.source_time,
            "record_receipt_time": None,
            "continuity": "unproven_no_source_sequences",
            "gaps": None,
            "state_available": book.ready,
            "expanded_bytes": expanded,
            "stop_reason": reason,
            "entire_archive_replayed": reason == "archive_end",
            "book_identity": book.identity,
            "trace_identity": trace.hexdigest(),
        }
