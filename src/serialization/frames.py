"""Store newline-free records in bounded, independently decodable zstd frames."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterator
from compression import zstd
from typing import BinaryIO, ClassVar


class FrameWriter:
    """Write records into length-prefixed zstd frames with memory bounded by one frame.

    Each frame starts with an 8-byte header: the compressed and the uncompressed
    lengths, both big-endian. Its payload is the records joined by newlines, each
    ending with one. A frame closes after ``max_records`` records or once it holds
    ``target_bytes``, so a caller can see where the next frame starts
    (``at_frame_start``) before it encodes the next record.
    """

    max_record_bytes: ClassVar[int] = 16_777_216
    target_bytes: ClassVar[int] = 8_388_608
    max_records: ClassVar[int] = 4_096
    level: ClassVar[int] = 9

    def __init__(self, output: BinaryIO) -> None:
        """Bind an open binary output; the caller owns flushing and closing it."""
        self._output = output
        self._records: list[bytes] = []
        self._pending = 0
        self._digest = hashlib.sha256()
        self.stored_bytes = 0
        self.uncompressed_bytes = 0

    @property
    def at_frame_start(self) -> bool:
        """Return whether the next record is the first of a new frame."""
        return not self._records

    def add(self, record: bytes) -> None:
        """Append one record, closing the frame when it reaches a bound.

        Args:
            record: Encoded record without newlines.

        Raises:
            ValueError: The record is empty, contains a newline or exceeds the bound.
        """
        if not record or b"\n" in record or len(record) > self.max_record_bytes:
            raise ValueError("framed record must be nonempty, newline-free and bounded")
        self._records.append(record)
        self._pending += len(record) + 1
        if len(self._records) >= self.max_records or self._pending >= self.target_bytes:
            self._flush()

    def close(self) -> str:
        """Write any open frame and return the stored bytes' SHA-256."""
        self._flush()
        return self._digest.hexdigest()

    def _flush(self) -> None:
        """Compress and write the open frame, if any."""
        if not self._records:
            return
        payload = b"\n".join(self._records) + b"\n"
        compressed = zstd.compress(payload, level=self.level)
        header = len(compressed).to_bytes(4, "big") + len(payload).to_bytes(4, "big")
        for chunk in (header, compressed):
            self._output.write(chunk)
            self._digest.update(chunk)
        self.stored_bytes += len(header) + len(compressed)
        self.uncompressed_bytes += len(payload)
        self._records.clear()
        self._pending = 0


class FrameReader:
    """Read records written by ``FrameWriter``, refusing any frame outside its bounds."""

    max_frame_bytes: ClassVar[int] = 67_108_864

    @classmethod
    def records(cls, source: BinaryIO) -> Iterator[tuple[bool, bytes]]:
        """Yield each record with whether it starts a frame, until the end of the source.

        Args:
            source: Binary stream positioned at the first frame header.

        Yields:
            ``(frame_start, record)`` in stored order.

        Raises:
            ValueError: A header, length or frame payload is truncated or malformed.
        """
        while header := source.read(8):
            if len(header) != 8:
                raise ValueError("truncated frame header")
            stored = int.from_bytes(header[:4], "big")
            size = int.from_bytes(header[4:], "big")
            if not stored or not size or stored > cls.max_frame_bytes or size > cls.max_frame_bytes:
                raise ValueError("frame lengths outside bounds")
            compressed = source.read(stored)
            if len(compressed) != stored:
                raise ValueError("truncated frame")
            decompressor = zstd.ZstdDecompressor()
            try:
                payload = decompressor.decompress(compressed, max_length=size + 1)
            except zstd.ZstdError as error:
                raise ValueError("corrupt frame") from error
            if len(payload) != size or not decompressor.eof or decompressor.unused_data:
                raise ValueError("frame payload differs from its header")
            if not payload.endswith(b"\n"):
                raise ValueError("frame payload ends inside a record")
            for index, record in enumerate(payload[:-1].split(b"\n")):
                if not record:
                    raise ValueError("empty framed record")
                yield index == 0, record
