"""Identify saved exploratory partitions and verify their retained evidence before use."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Callable, Mapping
from contextlib import closing
from itertools import combinations
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from market_data.acquisition import AcquisitionManifest
from market_data.contracts import SourceRequest
from market_data.datasets.readers import DatasetReaders
from market_data.storage import RawStore
from market_data.validation import Correction, QualityPolicy, QualityReport
from reference_data.eligibility import EligibilityAssertions
from serialization import DomainCodec


class DatasetInput(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind one saved input to its own admission policy, catalog evidence and corrections.

    Assembly preserves each source/stream partition independently. This selection
    record does not merge economic streams or grant support to an uninstalled adapter.
    """

    acquisition: AcquisitionManifest
    policy: QualityPolicy
    eligibility: EligibilityAssertions
    corrections: tuple[Correction, ...] = ()

    def __post_init__(self) -> None:
        """Require explicit typed admission inputs without admitting their observations.

        Raises:
            ValueError: An input or evidence record has an unsupported type.
        """
        if (
            type(self.acquisition) is not AcquisitionManifest
            or type(self.policy) is not QualityPolicy
            or type(self.eligibility) is not EligibilityAssertions
            or type(self.corrections) is not tuple
            or any(type(item) is not Correction for item in self.corrections)
        ):
            raise ValueError("dataset input requires typed acquisition and admission evidence")

    @classmethod
    def resolve(
        cls,
        selections: tuple[DatasetInput, ...] | tuple[AcquisitionManifest, ...],
        *,
        policy: QualityPolicy | None,
        eligibility: EligibilityAssertions | None,
        corrections: Mapping[str, tuple[Correction, ...]] | None,
    ) -> tuple[DatasetInput, ...]:
        """Resolve per-input evidence or the existing explicit shared-evidence selection.

        Args:
            selections: Ordered per-input records, or acquisitions using shared evidence.
            policy: Shared policy only for an acquisition selection.
            eligibility: Shared catalog evidence only for an acquisition selection.
            corrections: Shared-selection correction map by acquisition run identity.

        Returns:
            Unique inputs in first-seen order, with independent source/stream bindings
            and one unambiguous admission policy for each acquisition.

        Raises:
            ValueError: Selection styles are mixed, shared evidence is missing, or
                correction keys name an unselected acquisition, or nonidentical
                selections overlap within one source/stream/instrument.
        """
        if type(selections) is not tuple:
            raise ValueError("dataset selections must be an ordered tuple")
        if policy is None and eligibility is None and corrections is None:
            if any(not isinstance(item, cls) for item in selections):
                raise ValueError(
                    "acquisitions require explicit policy, eligibility and corrections"
                )
            inputs = tuple(item for item in selections if isinstance(item, cls))
        elif (
            policy is None
            or eligibility is None
            or corrections is None
            or any(not isinstance(item, AcquisitionManifest) for item in selections)
        ):
            raise ValueError("use per-input evidence or complete shared evidence, not both")
        else:
            acquisitions = tuple(
                item for item in selections if isinstance(item, AcquisitionManifest)
            )
            if set(corrections) - {item.run.identity for item in acquisitions}:
                raise ValueError("dataset correction evidence names an unselected acquisition")
            inputs = tuple(
                cls(
                    acquisition=item,
                    policy=policy,
                    eligibility=eligibility,
                    corrections=corrections.get(item.run.identity, ()),
                )
                for item in acquisitions
            )
        unique = {DomainCodec().encode_json(item): item for item in inputs}
        for left, right in combinations(unique.values(), 2):
            left_run, right_run = left.acquisition.run, right.acquisition.run
            if (
                left_run.job.start < right_run.job.end
                and right_run.job.start < left_run.job.end
                and {
                    (item.source, left_run.job.stream, item.instrument_id)
                    for item in left_run.instruments
                }
                & {
                    (item.source, right_run.job.stream, item.instrument_id)
                    for item in right_run.instruments
                }
            ):
                raise ValueError("overlapping acquisitions require identical saved manifests")
        return tuple(unique.values())


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
            or self.acquisition.run.catalog.identity != self.eligibility.catalog.identity
            or self.policy.use != "exploratory"
        ):
            raise ValueError("dataset requires one complete exploratory archive partition")
        if self.acquisition.run.job.provider != "binance-archive":
            raise ValueError("unsupported saved source; only Binance daily archive is installed")
        for correction in self.corrections:
            if type(correction) is not Correction:
                raise ValueError("dataset corrections require explicit evidence records")
            correction.__post_init__()


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
        cls,
        path: Path,
        *,
        identity: str,
        partitions: Path,
        store: RawStore,
        max_bytes: int,
        readers: DatasetReaders,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> DatasetManifest:
        """Verify a selected manifest, canonical files and raw inputs before returning it.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
            path: Saved manifest file; absence never starts a new dataset.
            identity: Independently retained expected dataset SHA-256; no latest lookup.
            partitions: Directory of canonical files named by their lowercase digest.
            store: Raw objects under the caller's exclusion of mutation during this read.
            max_bytes: Positive per-file limit for manifest, canonical and raw/expanded bytes.
            report: Optional synchronous sink for each reproduced, byte-matched partition's
                run identity and quality report. Callback failures propagate; earlier
                partition reports do not certify a later partition or the whole snapshot.

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
            reader = readers.saved(partition.acquisition)[0]
            with closing(reader.read(store, max_bytes=max_bytes)) as occurrences:
                outcome = partition.policy.validate(
                    SourceRequest.partition(partition.acquisition.run)[0],
                    occurrences,
                    eligibility=partition.eligibility,
                    corrections=partition.corrections,
                    verifier=readers.verifier(reader.request),
                )
            if outcome.require_canonical() != canonical:
                raise ValueError("canonical partition differs from retained admission inputs")
            if report is not None:
                report(partition.acquisition.run.identity, outcome)
        return manifest
