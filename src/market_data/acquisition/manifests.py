"""Validate and durably checkpoint a sequential raw-acquisition manifest."""

from __future__ import annotations

# standard library imports
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import ClassVar, Literal

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from configuration import ResolvedManifest
from market_data.contracts import RawObject, SourceRequest
from market_data.storage import RawStore
from serialization import DomainCodec, DurableDirectory


class AcquisitionManifest(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Retain an ordered completion prefix and at most one unpublished receipt.

    A single caller owns the manifest path throughout read/modify/checkpoint.
    Completed descriptors retain original clocks. A pending descriptor preserves
    receipt time; its ingestion time is provisional until durable publication.
    Atomic replacement retains the full completion history, not attempt history.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()
    schema_version: Literal["1"] = "1"
    run: ResolvedManifest
    completed: tuple[RawObject, ...] = ()
    pending: RawObject | None = None

    def __post_init__(self) -> None:
        """Reject malformed records, duplicate/out-of-order completions and foreign inputs.

        Raises:
            ValueError: Schema, run, descriptor or sequential-prefix binding is invalid.
        """
        if self.schema_version != "1" or type(self.run) is not ResolvedManifest:
            raise ValueError("invalid acquisition manifest schema or run")
        requests = SourceRequest.partition(self.run)
        if (self.run.job.mode, self.run.job.pipeline) != ("historical", "acquisition.fetch"):
            raise ValueError("acquisition manifest requires historical/acquisition.fetch")
        if type(self.completed) is not tuple:
            raise ValueError("completed descriptors must be a tuple")
        descriptors = self.completed + (() if self.pending is None else (self.pending,))
        if len(descriptors) > len(requests):
            raise ValueError("acquisition manifest exceeds the selected partitions")
        for descriptor, request in zip(descriptors, requests):
            if type(descriptor) is not RawObject:
                raise ValueError("acquisition checkpoint requires a RawObject")
            descriptor.__post_init__()
            if descriptor.request_identity != request.identity:
                raise ValueError("acquisition checkpoints must form the selected request prefix")

    @classmethod
    def read(cls, path: Path, *, run: ResolvedManifest, store: RawStore) -> AcquisitionManifest:
        """Read a saved checkpoint and verify every completed object before new work.

        Args:
            path: Caller-controlled manifest file; absence starts an empty run.
            run: Independently resolved expected run, including code and policies.
            store: Store containing every previously completed object.

        Returns:
            Validated immutable state; a pending receipt is reconciled by the pipeline.

        Raises:
            ValueError: Saved schema, run identity or completed bytes conflict.
            OSError: Manifest or a completed object cannot be read.
        """
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return cls(run=run)
        state = cls._codec.decode_json(payload, cls)
        if state.run.identity != run.identity:
            raise ValueError("acquisition manifest run identity mismatch")
        for descriptor, request in zip(state.completed, SourceRequest.partition(run)):
            with store.open(descriptor=descriptor, request=request.binding):
                pass
        return state

    def save(self, path: Path) -> None:
        """Persist the entire checkpoint history using atomic durable replacement.

        Args:
            path: Single-writer file in an existing durably provisioned directory.

        Raises:
            ValueError: This state violates the sequential manifest contract.
            OSError: Checkpoint I/O fails; reopen before retrying an uncertain write.
        """
        self.__post_init__()
        with NamedTemporaryFile(dir=path.parent, prefix=".checkpoint-", delete=False) as output:
            staging = Path(output.name)
            try:
                output.write(self._codec.encode_json(self))
                output.flush()
                os.fsync(output.fileno())
                os.replace(staging, path)
                DurableDirectory.sync(path.parent)
            finally:
                staging.unlink(missing_ok=True)

    def partitions(self) -> tuple[AcquisitionManifest, ...]:
        """Project a complete daily acquisition into ordered single-instrument views.

        Keep each original descriptor, job, catalog and implementation binding. Only
        the resolved instrument tuple narrows; source-request identity excludes other
        universe members. The original acquisition remains the resume checkpoint.

        Returns:
            Complete immutable partition views in the original request order. A
            single-partition acquisition is returned unchanged.

        Raises:
            ValueError: The acquisition is incomplete, pending or not daily partitioned.
        """
        self.__post_init__()
        requests = SourceRequest.partition(self.run)
        if (
            self.run.job.partition != "utc-day"
            or self.pending is not None
            or len(self.completed) != len(requests)
        ):
            raise ValueError("dataset requires a complete daily acquisition without pending input")
        if len(requests) == 1:
            return (self,)
        return tuple(
            replace(
                self,
                run=replace(self.run, instruments=(request.instrument,)),
                completed=(descriptor,),
            )
            for request, descriptor in zip(requests, self.completed, strict=True)
        )

    def prepare(self, path: Path, descriptor: RawObject) -> None:
        """Persist original receipt metadata before the pipeline publishes raw bytes.

        Args:
            path: Single-writer manifest destination.
            descriptor: Next receipt, whose ingestion timestamp remains provisional.
        """
        replace(self, pending=descriptor).save(path)
