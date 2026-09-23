"""Bind retained capture requests to validated configuration and implementation."""

from __future__ import annotations

# standard library imports
import hashlib
import re

# third party library imports
import msgspec

# project library imports
from configuration import CaptureConfig, UniverseSelection
from market_data.contracts.raw import RequestBinding
from serialization import DomainCodec


class CaptureRequest(
    msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True, omit_defaults=True
):
    """Bind a unique recording to config and installed implementation identity."""

    config: CaptureConfig
    recording_id: str
    implementation_identity: str
    universes: UniverseSelection | None = None

    def __post_init__(self) -> None:
        """Validate the immutable identity used by shared raw-object storage."""
        self.config.__post_init__()
        if self.universes is not None:
            if type(self.universes) is not UniverseSelection:
                raise ValueError("capture requires typed universe scopes")
            self.universes.require(self.config.instrument_id, "collection")
        if not re.fullmatch(r"[a-f0-9-]{36}", self.recording_id):
            raise ValueError("invalid recording identity")
        if not re.fullmatch(r"[a-f0-9]{64}", self.implementation_identity):
            raise ValueError("implementation identity must be SHA-256")

    @property
    def binding(self) -> RequestBinding:
        """Revalidate the complete source request before admitting its storage identity.

        Returns:
            Neutral immutable binding after source-specific invariants have passed.
        """
        return RequestBinding(self.identity)

    @property
    def identity(self) -> str:
        """Return deterministic identity for this selected recording and implementation.

        Returns:
            Stable SHA-256 of the current bound identity or visible state.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()
