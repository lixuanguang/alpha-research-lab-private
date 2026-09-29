"""Bind source segments to one immutable collection run and exact predecessor bytes."""

from __future__ import annotations

# standard library imports
import hashlib
import re

# third party library imports
import msgspec

# project library imports
from configuration import CaptureConfig, CaptureRunConfig, UniverseSelection
from serialization import DomainCodec


class CaptureSegment(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Identify one native journal segment without inventing a connection boundary."""

    run_identity: str
    ordinal: int
    previous_recording_id: str | None = None
    previous_request_identity: str | None = None
    previous_sha256: str | None = None

    def __post_init__(self) -> None:
        """Require a complete exact predecessor binding for every suffix segment."""
        if (
            type(self.run_identity) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", self.run_identity)
            or (type(self.ordinal) is not int or not 0 <= self.ordinal < 512)
        ):
            raise ValueError("invalid capture segment identity")
        predecessor = (
            self.previous_recording_id,
            self.previous_request_identity,
            self.previous_sha256,
        )
        if any(value is not None and type(value) is not str for value in predecessor):
            raise ValueError("capture segment predecessor identities must be strings")
        if self.ordinal == 0:
            if any(value is not None for value in predecessor):
                raise ValueError("initial capture segment cannot have a predecessor")
        elif (
            any(value is None for value in predecessor)
            or (
                self.previous_recording_id is not None
                and not re.fullmatch(r"[a-f0-9-]{36}", self.previous_recording_id)
            )
            or any(
                value is not None and not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in (self.previous_request_identity, self.previous_sha256)
            )
        ):
            raise ValueError("suffix segment requires exact predecessor identities")


class CaptureRunRequest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Pin one public source, finite window, implementation and run identity."""

    config: CaptureConfig
    window: CaptureRunConfig
    run_id: str
    implementation_identity: str
    universes: UniverseSelection | None = None

    def __post_init__(self) -> None:
        """Validate public-only source authority separately from segment resource limits."""
        if type(self.config) is not CaptureConfig or type(self.window) is not CaptureRunConfig:
            raise ValueError("capture run requires typed source and window configuration")
        if type(self.run_id) is not str or type(self.implementation_identity) is not str:
            raise ValueError("capture run requires exact string identities")
        self.config.__post_init__()
        self.window.__post_init__()
        if self.config.venue not in ("okx", "bitfinex"):
            raise ValueError("capture rollover supports public OKX and Bitfinex books")
        if not re.fullmatch(r"[a-f0-9-]{36}", self.run_id) or not re.fullmatch(
            r"[a-f0-9]{64}", self.implementation_identity
        ):
            raise ValueError("invalid capture run or implementation identity")
        if self.window.max_bytes < self.config.max_frame_bytes * 2 + 8192:
            raise ValueError("run byte budget must leave room for frames and terminal controls")
        if self.universes is not None:
            if type(self.universes) is not UniverseSelection:
                raise ValueError("capture run requires typed universe scopes")
            self.universes.require(self.config.instrument_id, "collection")

    @property
    def identity(self) -> str:
        """Return the immutable whole-run request identity."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
