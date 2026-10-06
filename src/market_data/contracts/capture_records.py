"""Define immutable capture messages and committed-prefix cursor records."""

from __future__ import annotations

# standard library imports
import re
from typing import Literal

# third party library imports
import msgspec

# project library imports


class CaptureRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Preserve exact received message bytes and local UTC receipt order/precision.

    Receipt is Unix nanoseconds observed immediately after a complete WebSocket
    message reaches the application. Source clocks remain in raw bytes and may
    be absent. Control records carry fixed local reasons, never exception bodies.
    A ``clock`` record states only that nothing was received between the previous
    record and its receipt instant; it carries no market content.
    """

    kind: Literal["session", "frame", "snapshot", "gap", "session_end", "end", "clock"]
    epoch: int
    received_ns: int
    raw: bytes = b""
    reason: str = ""

    def __post_init__(self) -> None:
        """Require valid control scope and a positive UTC receipt instant."""
        if (
            type(self.epoch) is not int
            or type(self.received_ns) is not int
            or self.epoch < 0
            or self.received_ns <= 0
            or self.kind
            not in ("session", "frame", "snapshot", "gap", "session_end", "end", "clock")
            or not isinstance(self.raw, bytes)
            or not isinstance(self.reason, str)
            or (self.kind not in ("frame", "snapshot") and self.raw)
            or (self.kind == "clock" and self.reason)
        ):
            raise ValueError("invalid capture record, epoch or receipt timestamp")


class CaptureCursor(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Bind an acknowledged append boundary to its request, byte prefix and record count."""

    request_identity: str
    offset: int
    records: int
    sha256: str

    def __post_init__(self) -> None:
        """Reject malformed identities and noninteger or inconsistent prefix coordinates."""
        if any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (self.request_identity, self.sha256)
        ) or any(type(value) is not int or value < 0 for value in (self.offset, self.records)):
            raise ValueError("invalid capture cursor")
        if (self.offset == 0) != (self.records == 0) or self.records > self.offset:
            raise ValueError("inconsistent capture cursor")
