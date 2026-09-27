"""Admit bounded saved native book histories without granting causal or execution use."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
import stat
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO, ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from market_data.contracts import BookObservation, CaptureRequest, OKXArchiveRequest, RawObject
from market_data.datasets.readers import DatasetReaders
from market_data.storage import RawStore
from market_data.validation import QualityReport
from serialization import DomainCodec


class BookInput(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Bind a selected raw prefix to native configuration, clocks and original provenance."""

    raw: RawObject
    max_records: int
    capture: CaptureRequest | None = None
    archive: OKXArchiveRequest | None = None
    index: bytes = b""

    def __post_init__(self) -> None:
        """Require exactly one supported request and preserve archive discovery evidence."""
        if (
            type(self.raw) is not RawObject
            or type(self.index) is not bytes
            or (self.capture is not None and type(self.capture) is not CaptureRequest)
            or (self.archive is not None and type(self.archive) is not OKXArchiveRequest)
        ):
            raise ValueError("book input requires typed native provenance")
        if (self.capture is None) == (self.archive is None) or (
            type(self.max_records) is not int or not 1 <= self.max_records <= 1_000_000
        ):
            raise ValueError("book admission requires one native input and a bounded prefix")
        request = self.request
        request.__post_init__()
        self.raw.__post_init__()
        if self.raw.request_identity != request.identity:
            raise ValueError("book raw object differs from selected request")
        if self.archive is not None and (
            hashlib.sha256(self.index).hexdigest() != self.archive.index_sha256
        ):
            raise ValueError("book archive discovery differs from retained request")
        if self.capture is not None and self.index:
            raise ValueError("live capture cannot acquire archive discovery evidence")

    @property
    def request(self) -> CaptureRequest | OKXArchiveRequest:
        """Return the single native binding used by immutable raw storage.

        Returns:
            Validated recording or archive request with its original implementation identity.

        Raises:
            ValueError: Neither supported binding is present.
        """
        if self.capture is not None:
            return self.capture
        if self.archive is not None:
            return self.archive
        raise ValueError("missing book source request")

    @classmethod
    def read(cls, directory: Path, *, max_records: int) -> BookInput:
        """Load a completed collector directory using its strict existing request schema.

        Args:
            directory: Original capture/archive directory; interrupted prefixes are refused.
            max_records: Explicit maximum raw positions to retain in this dataset partition.

        Returns:
            Location-independent selection; raw bytes are verified during admission.
        """
        codec = DomainCodec()
        payload = cls._read_bytes(directory / "request.json", 1_048_576)
        fields = msgspec.json.decode(payload, type=dict[str, msgspec.Raw])
        capture = "recording_id" in fields
        return cls(
            raw=codec.decode_json(
                cls._read_bytes(directory / "manifest.json", 1_048_576), RawObject
            ),
            max_records=max_records,
            capture=codec.decode_json(payload, CaptureRequest) if capture else None,
            archive=None if capture else codec.decode_json(payload, OKXArchiveRequest),
            index=b"" if capture else cls._read_bytes(directory / "index.json", 1_048_576),
        )

    def admit(self, store: RawStore, *, readers: DatasetReaders, max_bytes: int) -> QualityReport:
        """Reconstruct a bounded prefix, retaining controls and refusing malformed messages.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
            store: Immutable original objects; their full digests are verified before use.
            max_bytes: Positive bound on raw and canonical bytes; archive expansion also
                retains its original configuration's bound. Memory is proportional to
                bounded canonical bytes plus the configured native visible state.

        Returns:
            Existing quality/publication gate with deterministic exploratory bytes or
            retained rejection reasons. No trade revision operation is applied to books.

        Raises:
            ValueError: The input binding itself is malformed or incompatible.
        """
        self.__post_init__()
        if self.max_records > 10_000:
            raise ValueError(
                "legacy book envelope requires at most 10000 records; stream the input"
            )
        codec, rows, used, invalid, gaps, duplicates = DomainCodec(), [], 0, 0, 0, 0
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        try:
            if type(max_bytes) is not int or max_bytes <= 0 or self.raw.size_bytes > max_bytes:
                raise ValueError("book raw input exceeds max_bytes")
            for row in readers.books(self, store):
                used += len(codec.encode_json(row))
                if used > max_bytes:
                    raise ValueError("book canonical state exceeds max_bytes")
                rows.append(row)
                invalid += row.outcome == "invalid_frame"
                gaps += row.outcome in ("gap", "invalid_frame")
                duplicates += row.outcome == "duplicate"
            if invalid or not any(
                row.outcome in ("snapshot", "update") and (row.status in ("degraded", "stale"))
                for row in rows
            ):
                raise ValueError("book prefix contains invalid input or no admitted reconstruction")
            payload = codec.encode_json(BookHistory(input=self, observations=tuple(rows)))
            if len(payload) > max_bytes:
                raise ValueError("book canonical envelope exceeds max_bytes")
        except (ValueError, TypeError, OSError, OverflowError, EOFError, tarfile.TarError) as error:
            return QualityReport(
                scope="rejected",
                reasons=tuple([*reasons, str(error)]),
                invalid_count=max(1, invalid),
                gap_count=gaps,
                duplicate_count=duplicates,
                canonical=None,
            )
        if self.archive is not None:
            reasons.append("source continuity and original availability unknown")
        return QualityReport(
            scope="exploratory_degraded",
            reasons=tuple(reasons),
            invalid_count=0,
            gap_count=gaps,
            duplicate_count=duplicates,
            canonical=payload,
        )

    @staticmethod
    def _read_bytes(path: Path, max_bytes: int) -> bytes:
        """Read bounded metadata or canonical files before decoding them."""
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("book dataset file exceeds max_bytes")
        return payload


class BookHistory(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Expose typed message boundaries only with their complete input and degraded scope."""

    schema: Literal["canonical-book-prefix-v1"] = "canonical-book-prefix-v1"
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    input: BookInput
    observations: tuple[BookObservation, ...]

    def __post_init__(self) -> None:
        """Retain an explicit version and reject empty or malformed canonical histories."""
        if (
            self.schema != "canonical-book-prefix-v1"
            or self.scope != "exploratory_degraded"
            or type(self.input) is not BookInput
            or type(self.observations) is not tuple
            or not self.observations
            or len(self.observations) > self.input.max_records
            or any(type(row) is not BookObservation for row in self.observations)
        ):
            raise ValueError("invalid canonical book history")
        self.input.__post_init__()
        for position, row in enumerate(self.observations):
            BookStream.validate_row(self.input, position, row)


class BookStreamHeader(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Identify a line-delimited native history without changing the legacy envelope."""

    schema: Literal["canonical-book-stream-v2"] = "canonical-book-stream-v2"
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    input: BookInput

    def __post_init__(self) -> None:
        """Reject changed scope, schema or source evidence."""
        if self.schema != "canonical-book-stream-v2" or self.scope != "exploratory_degraded":
            raise ValueError("unsupported canonical book stream")
        if type(self.input) is not BookInput:
            raise ValueError("book stream requires a typed input")
        self.input.__post_init__()


class BookAdmissionReport(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain stream admission counts and digest without holding canonical bytes."""

    scope: Literal["exploratory_degraded", "rejected"]
    reasons: tuple[str, ...]
    invalid_count: int
    gap_count: int
    duplicate_count: int
    record_count: int
    sha256: str | None

    def __post_init__(self) -> None:
        """Reject contradictory stream gates and malformed counts or digest."""
        if (
            self.scope not in ("exploratory_degraded", "rejected")
            or type(self.reasons) is not tuple
            or not self.reasons
            or any(type(reason) is not str or not reason for reason in self.reasons)
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.invalid_count,
                    self.gap_count,
                    self.duplicate_count,
                    self.record_count,
                )
            )
            or (self.scope == "rejected") != (self.sha256 is None)
            or (self.sha256 is not None and re.fullmatch(r"[a-f0-9]{64}", self.sha256) is None)
        ):
            raise ValueError("invalid book stream admission report")
        if self.scope == "exploratory_degraded" and (self.invalid_count or not self.record_count):
            raise ValueError("admitted book stream requires nonempty valid input")

    def require_digest(self) -> str:
        """Release the admitted file identity or report the retained refusal."""
        self.__post_init__()
        if self.scope == "rejected" or self.sha256 is None:
            raise ValueError("partition publication refused: " + "; ".join(self.reasons))
        return self.sha256


class BookStream:
    """Write and verify exact native observations with memory bounded by one message."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    _max_line_bytes: ClassVar[int] = 16_777_216

    @staticmethod
    def validate_row(selection: BookInput, position: int, row: BookObservation) -> None:
        """Preserve original positions and source-specific clock absence or presence."""
        row.__post_init__()
        if row.position != position:
            raise ValueError("book history requires contiguous original positions")
        if selection.archive is not None and any(
            value is not None
            for value in (
                row.received_ns,
                row.epoch,
                row.sequence,
                row.transition_ns,
                row.last_durable_ns,
            )
        ):
            raise ValueError("archive book history cannot invent receipt or sequence")
        if selection.capture is not None and (
            row.received_ns is None or row.received_ns <= 0 or row.epoch is None
        ):
            raise ValueError("captured book history requires original receipt and epoch")

    @classmethod
    def _line(cls, value: object) -> bytes:
        """Encode one canonical bounded line with exact numeric strings."""
        line = cls._codec.encode_json(value) + b"\n"
        if len(line) > cls._max_line_bytes:
            raise ValueError("book canonical message exceeds line bound")
        return line

    @classmethod
    def _header_line(cls, selection: BookInput) -> bytes:
        """Bind a stream to the complete immutable source selection."""
        line = cls._line(BookStreamHeader(input=selection))
        if len(line) > 1_048_576:
            raise ValueError("book canonical header exceeds metadata bound")
        return line

    @classmethod
    def write(
        cls,
        selection: BookInput,
        store: RawStore,
        readers: DatasetReaders,
        output: BinaryIO,
        *,
        max_bytes: int,
    ) -> BookAdmissionReport:
        """Admit raw positions and write one canonical line at a time to a staged file."""
        selection.__post_init__()
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        digest = hashlib.sha256()
        used = invalid = gaps = duplicates = count = 0
        try:
            if type(max_bytes) is not int or max_bytes <= 0 or selection.raw.size_bytes > max_bytes:
                raise ValueError("book raw input exceeds max_bytes")
            header = cls._header_line(selection)
            output.write(header)
            digest.update(header)
            used += len(header)
            admitted = False
            for row in readers.books(selection, store):
                if count >= selection.max_records:
                    raise ValueError("book prefix exceeds selected record bound")
                cls.validate_row(selection, count, row)
                line = cls._line(row)
                used += len(line)
                if used > max_bytes:
                    raise ValueError("book canonical stream exceeds max_bytes")
                output.write(line)
                digest.update(line)
                count += 1
                invalid += row.outcome == "invalid_frame"
                gaps += row.outcome in ("gap", "invalid_frame")
                duplicates += row.outcome == "duplicate"
                admitted |= row.outcome in ("snapshot", "update") and row.status in (
                    "degraded",
                    "stale",
                )
            if invalid or not admitted:
                raise ValueError("book prefix contains invalid input or no admitted reconstruction")
        except (ValueError, TypeError, OSError, OverflowError, EOFError, tarfile.TarError) as error:
            return BookAdmissionReport(
                scope="rejected",
                reasons=(*reasons, str(error)),
                invalid_count=max(1, invalid),
                gap_count=gaps,
                duplicate_count=duplicates,
                record_count=count,
                sha256=None,
            )
        if selection.archive is not None:
            reasons.append("source continuity and original availability unknown")
        return BookAdmissionReport(
            scope="exploratory_degraded",
            reasons=tuple(reasons),
            invalid_count=0,
            gap_count=gaps,
            duplicate_count=duplicates,
            record_count=count,
            sha256=digest.hexdigest(),
        )

    @classmethod
    def verify(
        cls,
        path: Path,
        selection: BookInput,
        store: RawStore,
        readers: DatasetReaders,
        *,
        sha256: str,
        max_bytes: int,
    ) -> BookAdmissionReport:
        """Compare every saved line with fresh normalization of the immutable raw source."""
        with path.open("rb") as source:
            cls._check_digest(source, sha256, max_bytes=max_bytes)
            if source.readline(1_048_577) != cls._header_line(selection):
                raise ValueError("canonical book header differs from retained selection")
            invalid = gaps = duplicates = count = 0
            admitted = False
            for row in readers.books(selection, store):
                if count >= selection.max_records:
                    raise ValueError("book prefix exceeds selected record bound")
                cls.validate_row(selection, count, row)
                if source.readline(cls._max_line_bytes + 1) != cls._line(row):
                    raise ValueError("canonical book differs from retained admission inputs")
                count += 1
                invalid += row.outcome == "invalid_frame"
                gaps += row.outcome in ("gap", "invalid_frame")
                duplicates += row.outcome == "duplicate"
                admitted |= row.outcome in ("snapshot", "update") and row.status in (
                    "degraded",
                    "stale",
                )
            if source.read(1):
                raise ValueError("canonical book has unselected records")
            if invalid or not admitted:
                raise ValueError("book prefix contains invalid input or no admitted reconstruction")
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        if selection.archive is not None:
            reasons.append("source continuity and original availability unknown")
        return BookAdmissionReport(
            scope="exploratory_degraded",
            reasons=tuple(reasons),
            invalid_count=0,
            gap_count=gaps,
            duplicate_count=duplicates,
            record_count=count,
            sha256=sha256,
        )

    @staticmethod
    def _check_digest(source: BinaryIO, expected: str, *, max_bytes: int) -> os.stat_result:
        """Hash a regular pinned descriptor before exposing any observation."""
        original = os.fstat(source.fileno())
        if not stat.S_ISREG(original.st_mode):
            raise ValueError("book stream must be a regular file")
        digest = hashlib.sha256()
        used = 0
        while chunk := source.read(1_048_576):
            used += len(chunk)
            if used > max_bytes:
                raise ValueError("book canonical stream exceeds max_bytes")
            digest.update(chunk)
        current = os.fstat(source.fileno())
        if (current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (
            original.st_size,
            original.st_mtime_ns,
            original.st_ctime_ns,
        ):
            raise ValueError("book canonical stream changed during verification")
        if digest.hexdigest() != expected:
            raise ValueError("canonical book digest mismatch")
        source.seek(0)
        return original


class BookPartition(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Bind deterministic book bytes to the immutable input and explicit prefix selection."""

    sha256: str
    selection: BookInput

    def __post_init__(self) -> None:
        """Validate digest and native input identity before snapshot staging."""
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("invalid canonical book digest")
        if type(self.selection) is not BookInput:
            raise ValueError("book partition requires a typed input")
        self.selection.__post_init__()


class BookDatasetManifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Version exploratory book publication separately from the unchanged trade format."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["book-dataset-v1", "book-dataset-v2"] = "book-dataset-v1"
    scope: Literal["exploratory_degraded"] = "exploratory_degraded"
    normalization_identity: str
    partitions: tuple[BookPartition, ...]

    def __post_init__(self) -> None:
        """Require unique complete book selections and an identified normalizer."""
        if (
            self.schema_version not in ("book-dataset-v1", "book-dataset-v2")
            or self.scope != "exploratory_degraded"
            or not isinstance(self.normalization_identity, str)
            or not re.fullmatch(r"[a-f0-9]{64}", self.normalization_identity)
            or type(self.partitions) is not tuple
            or not self.partitions
        ):
            raise ValueError("unsupported book dataset version, scope or identity")
        selected: set[str] = set()
        for partition in self.partitions:
            if type(partition) is not BookPartition:
                raise ValueError("book manifest requires typed partitions")
            partition.__post_init__()
            identity = partition.selection.request.identity
            if identity in selected:
                raise ValueError("duplicate book source selection")
            selected.add(identity)

    @property
    def identity(self) -> str:
        """Identify the schema, ordered raw inputs, quality policy and canonical states.

        Returns:
            Stable SHA-256 independent of publication location and wall clock.
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
    ) -> BookDatasetManifest:
        """Reproduce all selected book boundaries before admitting a saved snapshot.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
            path: Explicit immutable manifest file.
            identity: Independently expected dataset SHA-256.
            partitions: Directory of canonical files addressed by digest.
            store: Retained original raw objects, protected from external mutation.
            max_bytes: Positive bound on each canonical file and original raw object.
            report: Optional sink for each reproduced partition's quality report.

        Returns:
            Verified exploratory manifest; this format grants no trade-query capability.

        Raises:
            ValueError: Identity, format, bytes, scope or reproduced admission differs.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("book dataset requires positive max_bytes")
        manifest = cls._codec.decode_json(BookInput._read_bytes(path, max_bytes), cls)
        if manifest.identity != identity:
            raise ValueError("book dataset identity mismatch")
        for partition in manifest.partitions:
            if manifest.schema_version == "book-dataset-v1":
                canonical = BookInput._read_bytes(partitions / partition.sha256, max_bytes)
                if hashlib.sha256(canonical).hexdigest() != partition.sha256:
                    raise ValueError("canonical book digest mismatch")
                outcome = partition.selection.admit(store, readers=readers, max_bytes=max_bytes)
                if outcome.require_canonical() != canonical:
                    raise ValueError("canonical book differs from retained admission inputs")
                if report is not None:
                    report(partition.selection.request.identity, outcome)
            else:
                if report is not None:
                    raise ValueError("stream admission reports require BookSnapshot.read")
                try:
                    BookStream.verify(
                        partitions / partition.sha256,
                        partition.selection,
                        store,
                        readers,
                        sha256=partition.sha256,
                        max_bytes=max_bytes,
                    )
                except (
                    ValueError,
                    TypeError,
                    OSError,
                    OverflowError,
                    EOFError,
                    tarfile.TarError,
                ) as error:
                    raise ValueError("partition publication refused: " + str(error)) from error
        return manifest


class BookSnapshot:
    """Hold a verified book manifest and stream selected immutable partition files."""

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        root: Path,
        manifest: BookDatasetManifest,
        files: dict[str, tuple[int, int, int, int, int]],
        *,
        max_bytes: int,
    ) -> None:
        """Bind validated metadata and verified file fingerprints without I/O."""
        manifest.__post_init__()
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or set(files) != {partition.sha256 for partition in manifest.partitions}
        ):
            raise ValueError("book snapshot requires pinned partitions and positive max_bytes")
        self._root = root
        self._identity = manifest.identity
        self._schema_version = manifest.schema_version
        self._partitions = {
            partition.selection.request.identity: self._codec.encode_json(partition)
            for partition in manifest.partitions
        }
        self._files = files.copy()
        self.max_bytes = max_bytes

    @classmethod
    def _from_verified(
        cls, root: Path, manifest: BookDatasetManifest, *, max_bytes: int
    ) -> BookSnapshot:
        """Pin file identities after whole-snapshot raw admission by the caller."""
        manifest.__post_init__()
        files: dict[str, tuple[int, int, int, int, int]] = {}
        for partition in manifest.partitions:
            path = root / manifest.identity / partition.sha256
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("book snapshot files must be regular files")
            files[partition.sha256] = cls._fingerprint(metadata)
        return cls(root, manifest, files, max_bytes=max_bytes)

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        identity: str,
        max_bytes: int,
        report: Callable[[str, BookAdmissionReport], None] | None = None,
    ) -> BookSnapshot:
        """Reproduce selected raw histories and open an optionally reported session."""
        # Local import keeps the storage format independent of its publication service.
        # project library imports
        from market_data.datasets.snapshots import SnapshotStore

        manifest = SnapshotStore(
            directory, raw, readers=readers, manifest_type=BookDatasetManifest
        ).read(identity, max_bytes=max_bytes)
        session = cls._from_verified(directory, manifest, max_bytes=max_bytes)
        if report is not None:
            for partition in manifest.partitions:
                request_identity = partition.selection.request.identity
                report(request_identity, session.admission_report(request_identity))
        return session

    @property
    def identity(self) -> str:
        """Return the exact admitted manifest digest."""
        return self._identity

    @property
    def schema_version(self) -> Literal["book-dataset-v1", "book-dataset-v2"]:
        """Distinguish legacy envelopes from bounded streams."""
        return self._schema_version

    def partition(self, request_identity: str) -> BookPartition:
        """Select an immutable partition by exact native request identity."""
        try:
            payload = self._partitions[request_identity]
        except KeyError as error:
            raise ValueError("book request absent from pinned snapshot") from error
        partition = self._codec.decode_json(payload, BookPartition)
        partition.__post_init__()
        return partition

    def selection(self, request_identity: str) -> BookInput:
        """Return the selected frozen native provenance record."""
        return self.partition(request_identity).selection

    def admission_report(self, request_identity: str) -> BookAdmissionReport:
        """Count validated stream outcomes without materializing canonical bytes."""
        partition = self.partition(request_identity)
        count = gaps = duplicates = 0
        for row in self.observations(request_identity):
            count += 1
            gaps += row.outcome in ("gap", "invalid_frame")
            duplicates += row.outcome == "duplicate"
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        if partition.selection.archive is not None:
            reasons.append("source continuity and original availability unknown")
        return BookAdmissionReport(
            scope="exploratory_degraded",
            reasons=tuple(reasons),
            invalid_count=0,
            gap_count=gaps,
            duplicate_count=duplicates,
            record_count=count,
            sha256=partition.sha256,
        )

    @staticmethod
    def _fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
        """Capture a cheap mutation signal under the protected immutable-store contract."""
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def verify_partition(self, request_identity: str) -> None:
        """Check a selected path still names the file verified at session opening."""
        partition = self.partition(request_identity)
        path = self._root / self.identity / partition.sha256
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or self._fingerprint(metadata) != self._files[partition.sha256]
        ):
            raise ValueError("book snapshot partition changed after admission")

    def require_limit(self, max_bytes: int) -> None:
        """Check an additional consumer limit against actual files and raw selections."""
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("book query max_bytes must be positive")
        directory = self._root / self.identity
        if (directory / "manifest.json").stat().st_size > max_bytes:
            raise ValueError("book manifest exceeds query max_bytes")
        for payload in self._partitions.values():
            partition = self._codec.decode_json(payload, BookPartition)
            self.verify_partition(partition.selection.request.identity)
            if (
                directory / partition.sha256
            ).stat().st_size > max_bytes or partition.selection.raw.size_bytes > max_bytes:
                raise ValueError("book snapshot file exceeds query max_bytes")

    def legacy_canonical(self, request_identity: str) -> bytes | None:
        """Return legacy envelope bytes only for v1 cursor identity compatibility."""
        if self._schema_version != "book-dataset-v1":
            return None
        partition = self.partition(request_identity)
        self.verify_partition(request_identity)
        path = self._root / self.identity / partition.sha256
        payload = BookInput._read_bytes(path, self.max_bytes)
        if hashlib.sha256(payload).hexdigest() != partition.sha256:
            raise ValueError("canonical book digest mismatch")
        return payload

    def observations(self, request_identity: str) -> Iterator[BookObservation]:
        """Yield fresh exact rows after verifying a pinned file before the first row."""
        partition = self.partition(request_identity)
        self.verify_partition(request_identity)
        path = self._root / self.identity / partition.sha256
        if self._schema_version == "book-dataset-v1":
            payload = BookInput._read_bytes(path, self.max_bytes)
            if hashlib.sha256(payload).hexdigest() != partition.sha256:
                raise ValueError("canonical book digest mismatch")
            history = self._codec.decode_json(payload, BookHistory)
            if history.input != partition.selection:
                raise ValueError("canonical book input differs from manifest")
            yield from history.observations
            return
        with path.open("rb") as source:
            original = BookStream._check_digest(source, partition.sha256, max_bytes=self.max_bytes)
            header = self._codec.decode_json(source.readline(1_048_577), BookStreamHeader)
            header.__post_init__()
            if header.input != partition.selection:
                raise ValueError("canonical book input differs from manifest")
            count = 0
            while line := source.readline(BookStream._max_line_bytes + 1):
                if len(line) > BookStream._max_line_bytes or not line.endswith(b"\n"):
                    raise ValueError("incomplete or oversized canonical book line")
                row = self._codec.decode_json(line, BookObservation)
                BookStream.validate_row(partition.selection, count, row)
                yield row
                count += 1
            if not count or count > partition.selection.max_records:
                raise ValueError("canonical book record count outside selected bound")
            current = os.fstat(source.fileno())
            if (current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (
                original.st_size,
                original.st_mtime_ns,
                original.st_ctime_ns,
            ):
                raise ValueError("book canonical stream changed during read")
