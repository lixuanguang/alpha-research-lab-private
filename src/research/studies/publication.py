"""Declare whether a retained study stays local or enters the ClearML outbox."""

from __future__ import annotations

# standard library imports
from typing import Literal

# project library imports
from research.studies.tracking import ClearMLDestination
from serialization import WireRecord


class PublicationPolicy(WireRecord, frozen=True):
    """Select local retention, deferred publication or immediate publication."""

    mode: Literal["local", "deferred", "immediate"]
    destination: ClearMLDestination | None = None

    def __post_init__(self) -> None:
        """Require a validated destination exactly when a ClearML outbox is requested."""
        if self.mode == "local":
            if self.destination is not None:
                raise ValueError("local publication must not select a destination")
        elif self.mode in ("deferred", "immediate"):
            if type(self.destination) is not ClearMLDestination:
                raise ValueError("deferred or immediate publication requires a destination")
            self.destination.__post_init__()
        else:
            raise ValueError("unsupported publication mode")
