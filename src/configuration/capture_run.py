"""Declare one finite public collection window separately from segment limits."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec

# project library imports
from serialization import DomainCodec


class CaptureRunConfig(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind fixed UTC start, readiness and stop instants with explicit whole-run ceilings.

    These collection limits grant no account or trading authority. ``max_bytes``
    bounds unique encoded journal bytes; publication can retain a second copy.
    Research profile budgets must also be checked across all selected sources.
    """

    start_at: datetime
    ready_by: datetime
    stop_at: datetime
    max_messages: int
    max_bytes: int
    max_segments: int
    max_reconnects: int
    schema_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        """Require a finite at-most-73-hour UTC window and bounded collection resources."""
        if self.schema_version != "1" or any(
            type(value) is not datetime
            or value.tzinfo is None
            or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.start_at, self.ready_by, self.stop_at)
        ):
            raise ValueError("capture run requires explicit UTC timestamps")
        if not self.start_at < self.ready_by <= self.stop_at or not (
            0 < (self.stop_at - self.start_at).total_seconds() <= 73 * 3600
        ):
            raise ValueError("capture run requires a fixed window of at most 73 hours")
        for value, minimum, maximum in (
            (self.max_messages, 1, 100_000_000),
            (self.max_bytes, 8192, 160 * 1024**3),
            (self.max_segments, 1, 512),
            (self.max_reconnects, 0, 32),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid finite capture run resource limit")

    @classmethod
    def read(cls, path: Path) -> CaptureRunConfig:
        """Read one exact collection-window configuration without starting a process."""
        return DomainCodec().decode_json(path.read_bytes(), cls)

    @staticmethod
    def unix_ns(value: datetime) -> int:
        """Convert the configured UTC microsecond clock without floating-point rounding."""
        delta = value - datetime(1970, 1, 1, tzinfo=UTC)
        return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
