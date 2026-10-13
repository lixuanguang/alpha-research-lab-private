"""Store small records as zstd frames compressed against one retained reference record."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from compression import zstd
from typing import ClassVar


class ReferenceFrames:
    """Compress records against one retained reference so structure they share is kept once.

    Records of one store repeat most of their bytes: field names, identities,
    currencies and unchanged assumptions. Each record is one checksummed zstd frame
    whose raw-content dictionary is the store's reference record, so a frame keeps
    little beyond what differs from the reference. The reference is an exact record
    the store retains once; every frame decodes on its own given that reference, and
    no frame refers to another. Without a reference, a record is a plain frame.

    A frame must declare its content size and checksum. ``decode`` restores at most
    that many bytes within ``maximum_bytes`` and requires one complete frame with no
    trailing bytes. The checksum covers the restored bytes, so a damaged frame, or a
    reference that does not restore exactly the original record, fails. The stored
    bytes are reproducible only by the same zstd library; readers compare and hash
    the decoded bytes, never the frames.
    """

    # Level 3 with the content checksum, so restored bytes that differ fail to decode.
    _options: ClassVar[Mapping[int, int]] = {
        zstd.CompressionParameter.compression_level: 3,
        zstd.CompressionParameter.checksum_flag: 1,
    }
    # A frame starts with the zstd magic number, then a header descriptor whose bit 2
    # declares the content checksum; ``get_frame_info`` does not report that flag.
    _magic: ClassVar[bytes] = b"\x28\xb5\x2f\xfd"
    _checksum_flag: ClassVar[int] = 0x04

    def __init__(self, reference: bytes | None, *, maximum_bytes: int, label: str) -> None:
        """Bind an optional exact reference record and the decoded size bound.

        Args:
            reference: The store's retained reference record, or ``None`` for plain
                frames.
            maximum_bytes: Largest record encoded or decoded, in bytes.
            label: The store's name in error messages.

        Raises:
            ValueError: The reference is empty, or the bound is not positive.
        """
        if (reference is not None and (type(reference) is not bytes or not reference)) or (
            type(maximum_bytes) is not int or maximum_bytes <= 0
        ):
            raise ValueError(f"{label} reference frames require a record and a positive bound")
        self.reference = reference
        self.maximum_bytes = maximum_bytes
        self.label = label
        self._dictionary = None if reference is None else zstd.ZstdDict(reference, is_raw=True)

    def encode(self, payload: bytes) -> bytes:
        """Return one record's frame.

        Raises:
            ValueError: The record is empty or exceeds the bound, so it is never stored.
        """
        if type(payload) is not bytes or not payload or len(payload) > self.maximum_bytes:
            raise ValueError(f"{self.label} record is empty or exceeds its bound")
        if self._dictionary is None:
            return zstd.compress(payload, options=self._options)
        return zstd.compress(payload, options=self._options, zstd_dict=self._dictionary)

    def decode(self, frame: object) -> bytes:
        """Return a stored frame's exact record bytes.

        Raises:
            ValueError: The value is not one complete, bounded, checksummed frame of a
                nonempty record compressed against this reference.
        """
        malformed = f"{self.label} frame is malformed"
        if (
            type(frame) is not bytes
            or len(frame) < 6
            or frame[:4] != self._magic
            or not frame[4] & self._checksum_flag
        ):
            raise ValueError(malformed)
        try:
            size = zstd.get_frame_info(frame).decompressed_size
            if size is None or not 0 < size <= self.maximum_bytes:
                raise ValueError(malformed)
            decompressor = zstd.ZstdDecompressor(zstd_dict=self._dictionary)
            payload = decompressor.decompress(frame, max_length=size)
        except zstd.ZstdError as error:
            raise ValueError(malformed) from error
        if len(payload) != size or not decompressor.eof or decompressor.unused_data:
            raise ValueError(malformed)
        return payload
