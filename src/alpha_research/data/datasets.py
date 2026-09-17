"""Identify saved exploratory partitions and verify their retained evidence before use."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Generator
from contextlib import closing
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.rows import BinanceArchiveRows
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction
from alpha_research.serialization import DomainCodec


class DatasetPartition(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind one canonical digest to complete raw, reference and admission inputs.

    The embedded acquisition contains the resolved job, selected universe, catalog,
    raw descriptors and original acquisition clocks. Paths and build clocks are not
    fields. Corrections and eligibility retain complete histories, including exclusions.
    """

    sha256: str
    acquisition: AcquisitionManifest
    policy: QualityPolicy
    eligibility: EligibilityAssertions
    corrections: tuple[Correction, ...] = ()

    def __post_init__(self) -> None:
        """Reject incomplete, foreign or unsupported partition declarations.

        Raises:
            ValueError: A digest, binding, admission input or completion is invalid.
        """
        if type(self.sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("canonical partition requires a lowercase SHA-256 digest")
        if (
            type(self.acquisition) is not AcquisitionManifest
            or type(self.policy) is not QualityPolicy
            or type(self.eligibility) is not EligibilityAssertions
            or type(self.corrections) is not tuple
        ):
            raise ValueError("dataset partition requires typed admission inputs")
        self.acquisition.__post_init__()
        self.policy.__post_init__()
        self.eligibility.__post_init__()
        if (
            len(SourceRequest.partition(self.acquisition.run)) != 1
            or len(self.acquisition.completed) != 1
            or self.acquisition.pending is not None
            or self.acquisition.run.job.provider != "binance-archive"
            or self.acquisition.run.catalog.identity != self.eligibility.catalog.identity
            or self.policy.use != "exploratory"
        ):
            raise ValueError("dataset requires one complete exploratory archive partition")
        for correction in self.corrections:
            if type(correction) is not Correction:
                raise ValueError("dataset corrections require explicit evidence records")
            correction.__post_init__()

    def _occurrences(self, store: RawStore, max_bytes: int) -> Generator[Occurrence]:
        """Reconstruct the retained input to verify admission independently of saved claims."""
        partition = BinanceArchiveRows.from_manifest(self.acquisition)[0]
        with closing(partition.read(store, max_bytes=max_bytes)) as rows:
            for row in rows:
                event = ArchiveTrade.from_row(row, partition.request)
                if row.selection_start <= event.ts_event < row.selection_end:
                    yield Occurrence(
                        request=partition.request,
                        origin=row.origin,
                        position=row.position,
                        raw=row.payload,
                        event=event,
                    )


class DatasetManifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Identify ordered admitted partitions without claiming atomic snapshot publication.

    Version 1 fixes canonical-trade-partition-v1, evidenced corrections and original
    availability extended only by evidenced later corrections. Changing those rules
    requires another supported format version. This reader supports exploratory use.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    canonical_schema: Literal["canonical-trade-partition-v1"] = "canonical-trade-partition-v1"
    correction_policy: Literal["evidenced-v1"] = "evidenced-v1"
    availability_policy: Literal["original-or-evidenced-later-v1"] = (
        "original-or-evidenced-later-v1"
    )
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    normalization_identity: str
    partitions: tuple[DatasetPartition, ...]

    def __post_init__(self) -> None:
        """Validate explicit versions, normalization identity and ordered unique partitions.

        Raises:
            ValueError: The format, scope, code identity or partition selection is invalid.
        """
        if (
            self.schema_version != "1"
            or self.canonical_schema != "canonical-trade-partition-v1"
            or self.correction_policy != "evidenced-v1"
            or self.availability_policy != "original-or-evidenced-later-v1"
            or self.scope != "exploratory_degraded"
            or type(self.normalization_identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.normalization_identity) is None
            or type(self.partitions) is not tuple
            or not self.partitions
        ):
            raise ValueError("unsupported dataset manifest version, scope or identity")
        selected: set[str] = set()
        for partition in self.partitions:
            if type(partition) is not DatasetPartition:
                raise ValueError("dataset requires DatasetPartition records")
            partition.__post_init__()
            identity = SourceRequest.partition(partition.acquisition.run)[0].identity
            if identity in selected:
                raise ValueError("dataset contains a duplicate source partition")
            selected.add(identity)

    @property
    def identity(self) -> str:
        """Hash complete resolved inputs and ordered canonical digests.

        Returns:
            SHA-256 independent of file locations, JSON formatting and build wall clock.
        """
        self.__post_init__()
        return hashlib.sha256(self._codec.encode_json(self)).hexdigest()

    @classmethod
    def read(
        cls, path: Path, *, identity: str, partitions: Path, store: RawStore, max_bytes: int
    ) -> DatasetManifest:
        """Verify a selected manifest, canonical files and raw inputs before returning it.

        Args:
            path: Saved manifest file; absence never starts a new dataset.
            identity: Independently retained expected dataset SHA-256; no latest lookup.
            partitions: Directory of canonical files named by their lowercase digest.
            store: Raw objects under the caller's exclusion of mutation during this read.
            max_bytes: Positive per-file limit for manifest, canonical and raw/expanded bytes.

        Returns:
            Validated manifest after every partition reproduces its declared quality scope.
            This bounded in-memory verification does not expose query or publication APIs.

        Raises:
            ValueError: Size, version, identity, bytes or reproduced admission disagrees.
            OSError: A required file is missing or unreadable.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("dataset max_bytes must be a positive integer")
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("dataset manifest exceeds max_bytes")
        manifest = cls._codec.decode_json(payload, cls)
        if manifest.identity != identity:
            raise ValueError("dataset manifest identity mismatch")
        for partition in manifest.partitions:
            with (partitions / partition.sha256).open("rb") as source:
                canonical = source.read(max_bytes + 1)
            if (
                len(canonical) > max_bytes
                or hashlib.sha256(canonical).hexdigest() != partition.sha256
            ):
                raise ValueError("canonical partition size or SHA-256 mismatch")
            with closing(partition._occurrences(store, max_bytes)) as occurrences:
                report = partition.policy.validate(
                    SourceRequest.partition(partition.acquisition.run)[0],
                    occurrences,
                    eligibility=partition.eligibility,
                    corrections=partition.corrections,
                )
            if report.require_canonical() != canonical:
                raise ValueError("canonical partition differs from retained admission inputs")
        return manifest
