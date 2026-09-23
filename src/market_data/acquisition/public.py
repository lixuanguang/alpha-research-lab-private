"""Checkpoint public responses and resume ingestion without changing original clocks."""

from __future__ import annotations

# standard library imports
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import PublicDataJob
from market_data.contracts import (
    PublicReceipt,
    PublicRequest,
    PublicSources,
    PublicTransport,
    RequestBinding,
)
from market_data.storage import RawFiles, RawStore
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class PendingResponse(WireRecord, frozen=True, kw_only=True):
    """Persist original bytes and receipt before validation or raw publication."""

    request: PublicRequest
    payload: bytes
    received: datetime

    def __post_init__(self) -> None:
        """Reject unsafe pending metadata without interpreting source bytes."""
        if type(self.request) is not PublicRequest or type(self.payload) is not bytes:
            raise ValueError("invalid pending public response")
        self.request.__post_init__()
        self._require_utc(self.received, field_name="received")


class PublicAcquisition(WireRecord, frozen=True, kw_only=True):
    """Pin job, installed implementation, retained responses and explicit completion state."""

    schema_version: Literal["public-acquisition-v1"] = "public-acquisition-v1"
    job: PublicDataJob
    implementation_identity: str
    receipts: tuple[PublicReceipt, ...] = ()
    pending: PendingResponse | None = None
    complete: bool = False
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        """Check source membership, response budgets and immutable request linkage."""
        if (
            self.schema_version != "public-acquisition-v1"
            or type(self.job) is not PublicDataJob
            or type(self.complete) is not bool
        ):
            raise ValueError("invalid public acquisition")
        self.job.__post_init__()
        RequestBinding(self.implementation_identity)
        if type(self.receipts) is not tuple or (
            self.pending is not None and type(self.pending) is not PendingResponse
        ):
            raise ValueError("invalid public acquisition receipts")
        if self.complete and self.pending is not None:
            raise ValueError("completed acquisition cannot have pending bytes")
        if self.complete != (self.finished_at is not None):
            raise ValueError("completion requires its original observation clock")
        if self.finished_at is not None:
            self._require_utc(self.finished_at, field_name="finished_at")
            if self.job.mode == "capture" and self.finished_at < self.job.end:
                raise ValueError("capture cannot complete before its selected end")
        if len(self.receipts) > self.job.max_pages + len(self.job.universes.collection):
            raise ValueError("public acquisition exceeds page budget")
        last: datetime | None = None
        for receipt in self.receipts:
            if type(receipt) is not PublicReceipt:
                raise ValueError("invalid public receipt record")
            receipt.__post_init__()
            self._request(receipt.request)
            if last is not None and receipt.raw.ts_received < last:
                raise ValueError("public receipt clock regressed")
            last = receipt.raw.ts_ingested
            if self.finished_at is not None and receipt.raw.ts_ingested > self.finished_at:
                raise ValueError("completion precedes durable input")
        used = sum(r.raw.size_bytes for r in self.receipts)
        if self.pending is not None:
            self.pending.__post_init__()
            self._request(self.pending.request)
            used += len(self.pending.payload)
            if last is not None and self.pending.received < last:
                raise ValueError("pending receipt clock regressed")
        if used > self.job.max_bytes:
            raise ValueError("public acquisition exceeds aggregate raw budget")

    def _request(self, request: PublicRequest) -> None:
        """Ensure requests cannot escape the selected collection or implementation."""
        if (
            request.job_identity != self.job.identity
            or request.implementation_identity != self.implementation_identity
            or request.instrument not in self.job.instruments
        ):
            raise ValueError("public request differs from resolved job")
        self.job.universes.require(request.instrument.instrument_id, "collection")

    def save(self, path: Path) -> None:
        """Atomically fsync the single-writer checkpoint; uncertain writes must be reopened."""
        self.__post_init__()
        with NamedTemporaryFile(dir=path.parent, prefix=".public-", delete=False) as output:
            staging = Path(output.name)
            try:
                output.write(DomainCodec().encode_json(self))
                output.flush()
                os.fsync(output.fileno())
                os.replace(staging, path)
                descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                staging.unlink(missing_ok=True)


class PublicIngestion:
    """Verify saved prefixes and advance one bounded multi-listing public acquisition.

    The caller owns the checkpoint and excludes concurrent writers. Reopening a
    pending response uses its saved bytes and clock, never a refetch. A committed
    page is verified and re-decoded before requesting its successor.
    """

    def __init__(self, sources: PublicSources, store: RawStore) -> None:
        """Bind explicit adapters and the existing verified raw-byte store."""
        self._sources, self._store = sources, store

    def resume(
        self,
        job: PublicDataJob,
        *,
        implementation_identity: str,
        path: Path,
        transport: PublicTransport,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> PublicAcquisition:
        """Resume retained pages, preserving failed responses and original receipt clocks.

        Validation failures leave the pending response for diagnosis. Page/byte
        exhaustion is an error, not a completed interval. Capture polls in round
        robin order and reports unknown loss across outages through dataset quality.
        """
        job.__post_init__()
        initial = PublicAcquisition(job=job, implementation_identity=implementation_identity)
        # Admit every selected binding before touching files or opening a connection.
        for instrument in job.instruments:
            if instrument.instrument_id in job.universes.collection:
                admission = PublicRequest(
                    job_identity=job.identity,
                    implementation_identity=implementation_identity,
                    instrument=instrument,
                    kind="reference",
                    cursor=None,
                    ordinal=0,
                )
                self._sources.public(instrument).endpoint(job, admission)
        state = initial
        if path.exists():
            with path.open("rb") as source:
                payload = source.read(job.max_bytes * 2 + 8_000_001)
            if len(payload) > job.max_bytes * 2 + 8_000_000:
                raise ValueError("public checkpoint exceeds bound")
            state = DomainCodec().decode_json(payload, PublicAcquisition)
            if state.job != job or state.implementation_identity != implementation_identity:
                raise ValueError("resume requires identical job and installed implementation")
        while True:
            request = self.next_request(state)
            if state.complete:
                if request is not None:
                    raise ValueError("completed public acquisition has unfinished requests")
                return state
            now = clock()
            PublicDataJob._require_utc(now, field_name="clock")
            if job.mode == "capture" and state.pending is None:
                if now < job.start:
                    sleep(min(job.poll_seconds, (job.start - now).total_seconds()))
                    continue
                if now >= job.end:
                    if not self._has_pages(state):
                        raise ValueError(
                            "capture interval expired before all bindings were observed"
                        )
                    state = replace(state, complete=True, finished_at=now)
                    state.save(path)
                    return state
            if request is None:
                state = replace(state, complete=True, finished_at=now)
                state.save(path)
                return state
            if (
                request.kind == "trades"
                and sum(r.request.kind == "trades" for r in state.receipts) >= job.max_pages
            ):
                raise ValueError("public ingestion page budget exhausted; saved prefix retained")
            adapter = self._sources.public(request.instrument)
            if state.pending is None:
                host, endpoint = adapter.endpoint(job, request)
                payload = transport.get(host, endpoint)
                state = replace(
                    state,
                    pending=PendingResponse(request=request, payload=payload, received=clock()),
                )
                state.save(path)
            pending = state.pending
            if pending is None or pending.request != request:
                raise ValueError("pending public request differs from verified continuation")
            if request.kind == "reference":
                adapter.reference(request.instrument, pending.payload, pending.received)
            else:
                adapter.trades(job, request, pending.payload)
            with TemporaryDirectory(dir=path.parent, prefix=".public-raw-") as temporary:
                saved = Path(temporary) / "response"
                saved.write_bytes(pending.payload)
                raw = RawFiles.describe(
                    saved,
                    request=request.binding,
                    retrieval_reference=f"public:{request.instrument.venue}:{request.kind}",
                    ts_received=pending.received,
                    ts_ingested=clock(),
                )
                self._store.publish(saved, descriptor=raw, request=request.binding)
                ingested = clock()
                if ingested < raw.ts_ingested:
                    raise ValueError("public ingestion clock regressed during publication")
                raw = replace(raw, ts_ingested=ingested)
            receipts: tuple[PublicReceipt, ...] = (
                *state.receipts,
                PublicReceipt(request=request, raw=raw),
            )
            state = replace(
                state,
                receipts=receipts,
                pending=None,
            )
            state.save(path)
            if request.kind == "trades":
                sleep(job.poll_seconds)

    def next_request(self, state: PublicAcquisition) -> PublicRequest | None:
        """Reproduce all saved continuation decisions before exposing a next request.

        This verification also protects dataset readers from forged completion or
        reordered/foreign response descriptors. Capture completion proves only a
        bounded sample, never continuity between polling receipts.
        """
        state.__post_init__()
        cursors: dict[InstrumentId, str | None] = {}
        counts: dict[InstrumentId, int] = {}
        done: set[InstrumentId] = set()
        for receipt in state.receipts:
            request = receipt.request
            instrument = request.instrument.instrument_id
            adapter = self._sources.public(request.instrument)
            adapter.endpoint(state.job, request)
            with self._store.open(descriptor=receipt.raw, request=request.binding) as source:
                payload = source.read(state.job.max_bytes + 1)
            if request.kind == "reference":
                if instrument in counts:
                    raise ValueError("duplicate or reordered reference receipt")
                adapter.reference(request.instrument, payload, receipt.raw.ts_received)
                counts[instrument], cursors[instrument] = 0, None
            else:
                if (
                    instrument not in counts
                    or instrument in done
                    or request.ordinal != counts[instrument]
                    or request.cursor != cursors[instrument]
                ):
                    raise ValueError("public page is not the verified source continuation")
                page = adapter.trades(state.job, request, payload)
                counts[instrument] += 1
                cursors[instrument] = page.next_cursor
                if state.job.mode == "backfill" and page.next_cursor is None:
                    done.add(instrument)
        selected = tuple(
            i for i in state.job.instruments if i.instrument_id in state.job.universes.collection
        )
        if state.complete and state.job.mode == "capture":
            if not self._has_pages(state):
                raise ValueError("completed capture lacks selected input receipts")
            return None
        remaining = [i for i in selected if i.instrument_id not in done]
        if not remaining:
            return None
        # Round robin guarantees each selected capture gets an observation.
        definition = min(remaining, key=_RequestPriority(counts))
        identity = definition.instrument_id
        return PublicRequest(
            job_identity=state.job.identity,
            implementation_identity=state.implementation_identity,
            instrument=definition,
            kind="reference" if identity not in counts else "trades",
            cursor=cursors.get(identity),
            ordinal=counts.get(identity, 0),
        )

    def references(self, state: PublicAcquisition) -> ReferenceHistory:
        """Reopen original reference responses into a pinned bitemporal history."""
        self.next_request(state)
        specifications = []
        for receipt in state.receipts:
            if receipt.request.kind != "reference":
                continue
            with self._store.open(
                descriptor=receipt.raw, request=receipt.request.binding
            ) as source:
                payload = source.read(state.job.max_bytes + 1)
            specifications.append(
                self._sources.public(receipt.request.instrument).reference(
                    receipt.request.instrument, payload, receipt.raw.ts_ingested
                )
            )
        return ReferenceHistory(specifications=tuple(specifications))

    @staticmethod
    def _has_pages(state: PublicAcquisition) -> bool:
        """Require one trade response for every selected listing, including empty pages."""
        return set(state.job.universes.collection) <= {
            r.request.instrument.instrument_id for r in state.receipts if r.request.kind == "trades"
        }


class _RequestPriority:
    """Order pending collection bindings by their own durable response count."""

    def __init__(self, counts: dict[InstrumentId, int]) -> None:
        """Bind invocation-local counts without retaining cross-run state."""
        self._counts = counts

    def __call__(self, instrument: InstrumentDefinition) -> int:
        """Prefer unobserved reference bindings, then the fewest captured pages."""
        return self._counts.get(instrument.instrument_id, -1)
