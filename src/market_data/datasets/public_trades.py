"""Publish and verify public trades through the existing immutable snapshot boundary."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# project library imports
from market_data.acquisition import PublicAcquisition, PublicIngestion
from market_data.contracts import PublicReceipt, PublicTrade, RequestBinding
from market_data.datasets.readers import DatasetReaders
from market_data.storage import RawStore
from market_data.validation import QualityReport
from reference_data.catalogs import ReferenceHistory
from serialization import DomainCodec, WireRecord


class PublicTradeObservation(WireRecord, frozen=True, kw_only=True):
    """Bind exact trade values to the first usable local response and applicable reference.

    Original historical availability remains unknown; ts_knowledge is the local
    durable observation, never a reconstructed exchange or historical receipt clock.
    """

    receipt: PublicReceipt
    position: int
    trade: PublicTrade
    specification_identity: str | None

    def __post_init__(self) -> None:
        """Validate immutable lineage and an optional proven reference version."""
        if type(self.receipt) is not PublicReceipt or type(self.trade) is not PublicTrade:
            raise ValueError("invalid public trade observation")
        self.receipt.__post_init__()
        self.trade.__post_init__()
        if (
            self.receipt.request.kind != "trades"
            or type(self.position) is not int
            or self.position < 0
        ):
            raise ValueError("invalid public trade source position")
        if self.specification_identity is not None:
            RequestBinding(self.specification_identity)

    @property
    def ts_event(self) -> datetime:
        """Project original integer milliseconds exactly to aware UTC."""
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=self.trade.event_ms)

    @property
    def ts_knowledge(self) -> datetime:
        """Expose local durable observation time, with no original-availability claim."""
        return self.receipt.raw.ts_ingested


class PublicTradeHistory(WireRecord, frozen=True, kw_only=True):
    """Keep all observed versions and duplicates beside retained reference facts."""

    references: ReferenceHistory
    observations: tuple[PublicTradeObservation, ...]

    def __post_init__(self) -> None:
        """Require typed immutable histories; source verification is owned by publication."""
        if type(self.references) is not ReferenceHistory or type(self.observations) is not tuple:
            raise ValueError("invalid public trade history")
        self.references.__post_init__()
        for row in self.observations:
            if type(row) is not PublicTradeObservation:
                raise ValueError("invalid public trade observation")
            row.__post_init__()


class PublicTradePartition(WireRecord, frozen=True, kw_only=True):
    """Bind the complete canonical history to its exact acquisition and raw responses."""

    acquisition: PublicAcquisition
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        """Reject incomplete ingestion and malformed canonical identities."""
        if type(self.acquisition) is not PublicAcquisition or not self.acquisition.complete:
            raise ValueError("public dataset requires complete ingestion")
        self.acquisition.__post_init__()
        RequestBinding(self.sha256)
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("invalid public canonical size")


class PublicTradeManifest(WireRecord, frozen=True, kw_only=True):
    """Pin a bounded public-trade snapshot without claiming historical completeness."""

    schema_version: Literal["public-trades"] = "public-trades"
    partitions: tuple[PublicTradePartition, ...]
    normalization_identity: str
    scope: Literal["locally_observed"] = "locally_observed"

    def __post_init__(self) -> None:
        """Keep one complete multi-instrument job under its existing admission limits."""
        if (
            self.schema_version != "public-trades"
            or self.scope != "locally_observed"
            or type(self.partitions) is not tuple
            or len(self.partitions) != 1
            or type(self.partitions[0]) is not PublicTradePartition
        ):
            raise ValueError("invalid public trade manifest")
        self.partitions[0].__post_init__()
        RequestBinding(self.normalization_identity)

    @property
    def identity(self) -> str:
        """Identify complete acquisition, reference lineage and canonical bytes."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    @classmethod
    def assemble(
        cls,
        acquisition: PublicAcquisition,
        store: RawStore,
        *,
        readers: DatasetReaders,
        max_bytes: int,
        normalization_identity: str,
    ) -> tuple[PublicTradeManifest, bytes]:
        """Verify every raw response and bind normalized output before atomic publication."""
        payload = cls.canonical(acquisition, store, readers=readers, max_bytes=max_bytes)
        return cls(
            partitions=(
                PublicTradePartition(
                    acquisition=acquisition,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                ),
            ),
            normalization_identity=normalization_identity,
        ), payload

    @staticmethod
    def canonical(
        acquisition: PublicAcquisition, store: RawStore, *, readers: DatasetReaders, max_bytes: int
    ) -> bytes:
        """Re-decode every page; preserve duplicates/corrections with independent local clocks."""
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("public dataset requires positive max_bytes")
        acquisition.__post_init__()
        ingestion = PublicIngestion(readers, store)
        if not acquisition.complete or ingestion.next_request(acquisition) is not None:
            raise ValueError("public dataset requires verified completed ingestion")
        references = ingestion.references(acquisition)
        observations: list[PublicTradeObservation] = []
        used = len(DomainCodec().encode_json(references))
        for receipt in acquisition.receipts:
            if receipt.request.kind != "trades":
                continue
            if receipt.raw.size_bytes > max_bytes:
                raise ValueError("public raw page exceeds max_bytes")
            with store.open(descriptor=receipt.raw, request=receipt.request.binding) as source:
                payload = source.read(max_bytes + 1)
            page = readers.public(receipt.request.instrument).trades(
                acquisition.job, receipt.request, payload
            )
            for position, trade in enumerate(page.trades):
                event = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=trade.event_ms)
                # Retain the whole observed page: an out-of-window correction must
                # still retire an earlier version before a query filters event time.
                spec = references.resolve(
                    receipt.request.instrument.instrument_id,
                    valid_at=event,
                    known_at=receipt.raw.ts_ingested,
                )
                row = PublicTradeObservation(
                    receipt=receipt,
                    position=position,
                    trade=trade,
                    specification_identity=None if spec is None else spec.identity,
                )
                used += len(DomainCodec().encode_json(row))
                if used > max_bytes:
                    raise ValueError("public canonical observations exceed aggregate max_bytes")
                observations.append(row)
        payload = DomainCodec().encode_json(
            PublicTradeHistory(references=references, observations=tuple(observations))
        )
        if len(payload) > max_bytes:
            raise ValueError("public canonical envelope exceeds max_bytes")
        return payload

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
    ) -> PublicTradeManifest:
        """Verify a pinned snapshot against retained raw responses and source pagination.

        The shared SnapshotStore owns file-kind, atomic publication and filesystem
        guarantees. A changed raw response, canonical file or source decoder fails.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("public snapshot requires positive byte limit")
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("public manifest exceeds max_bytes")
        manifest = DomainCodec().decode_json(payload, cls)
        if manifest.identity != identity:
            raise ValueError("public manifest identity mismatch")
        partition = manifest.partitions[0]
        with (partitions / partition.sha256).open("rb") as source:
            canonical = source.read(max_bytes + 1)
        if (
            len(canonical) != partition.size_bytes
            or len(canonical) > max_bytes
            or hashlib.sha256(canonical).hexdigest() != partition.sha256
        ):
            raise ValueError("public canonical bytes differ from manifest")
        if canonical != cls.canonical(
            partition.acquisition, store, readers=readers, max_bytes=max_bytes
        ):
            raise ValueError("public canonical history differs from retained source responses")
        if report is not None:
            report(
                identity,
                QualityReport(
                    scope="exploratory_degraded",
                    reasons=(
                        "local observation only; original availability and "
                        "source completeness unknown",
                    ),
                    invalid_count=0,
                    gap_count=0,
                    duplicate_count=0,
                    canonical=None,
                ),
            )
        return manifest
