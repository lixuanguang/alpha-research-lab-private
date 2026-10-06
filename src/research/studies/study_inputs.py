"""Declare explicit retained input capabilities for full decision studies."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Protocol

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

    def read(self, window: TimeWindow) -> Iterable[IntentMarket]:
        """Yield canonical inputs through the terminal cutoff in source order.

        A study consumes the rows once, in nondecreasing availability order, and
        retains a ``StudyMarketManifest`` of them rather than the rows themselves.
        """
        ...


class StudyMarketManifest(WireRecord, frozen=True):
    """Identify the market rows one fold consumed without retaining a copy of them.

    The rows are reproducible from the pinned market source and window; ``sha256``
    is over each row's canonical encoding followed by a newline, in consumed order.
    """

    source_identity: str
    window: TimeWindow
    rows: int
    first_available_at: datetime | None
    last_available_at: datetime | None
    last_source_at: datetime | None
    sha256: str
    schema_version: Literal["study-market-manifest"] = "study-market-manifest"

    def __post_init__(self) -> None:
        """Require consistent counts and clocks."""
        self.window.__post_init__()
        clocks = (self.first_available_at, self.last_available_at, self.last_source_at)
        if (
            self.schema_version != "study-market-manifest"
            or type(self.rows) is not int
            or self.rows < 0
            or (self.rows == 0) != all(clock is None for clock in clocks)
            or (self.rows > 0 and any(clock is None for clock in clocks))
            or len(self.sha256) != 64
        ):
            raise ValueError("invalid study market manifest")


class StudyOutcomeSource(Protocol):
    """Bind an authored label definition to its separately read outcome observations."""

    @property
    def identity(self) -> str:
        """Pin formula, input selection and outcome information horizon."""
        ...

    def read(self, row: FeatureVector, *, as_of: datetime) -> Outcome:
        """Return a label or explicit missing/pending outcome known by the declared cutoff."""
        ...
