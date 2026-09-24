"""Declare explicit retained input capabilities for full decision studies."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from typing import Protocol

# project library imports
from research.experiments import Fingerprint, TimeWindow
from research.features import FeatureVector
from research.labels import Outcome
from serialization import WireRecord
from simulation import IntentMarket


class StudyArtifact(WireRecord, frozen=True):
    """Retain trusted extension source/package bytes with their configured fingerprint.

    Studies never import or install these artifacts. External component authors
    provide the bytes implementing their selected versions; the installed
    distribution has its separate code identity.
    """

    fingerprint: Fingerprint
    payload: bytes

    def __post_init__(self) -> None:
        """Reject missing or mutated implementation bytes before study input access."""
        self.fingerprint.__post_init__()
        if (
            type(self.payload) is not bytes
            or not self.payload
            or hashlib.sha256(self.payload).hexdigest() != self.fingerprint.sha256
        ):
            raise ValueError("study extension artifact differs from its fingerprint")


class StudyMarketSource(Protocol):
    """Read a pinned market sample without manufacturing event or knowledge clocks."""

    @property
    def identity(self) -> str:
        """Identify retained source bytes and the explicit execution-clock interpretation."""
        ...

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Return bounded canonical inputs through the terminal cutoff, preserving source order."""
        ...


class StudyOutcomeSource(Protocol):
    """Bind an authored label definition to its separately read outcome observations."""

    @property
    def identity(self) -> str:
        """Pin formula, input selection and outcome information horizon."""
        ...

    def read(self, row: FeatureVector, *, as_of: datetime) -> Outcome:
        """Return a label or explicit missing/pending outcome known by the declared cutoff."""
        ...
