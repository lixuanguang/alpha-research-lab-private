"""Checkpoint public responses and resume ingestion without changing original clocks."""

from __future__ import annotations

# standard library imports
import copy
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Literal

# third party library imports
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import PublicDataJob
from market_data.contracts import (
    PublicReceipt,
    PublicRequest,
    PublicSources,
    PublicTransport,
    RequestBinding,
    TradePage,
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

    schema_version: Literal["public-acquisition"] = "public-acquisition"
    job: PublicDataJob
    implementation_identity: str
    receipts: tuple[PublicReceipt, ...] = ()
    pending: PendingResponse | None = None
    complete: bool = False
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        """Check source membership, response budgets and immutable request linkage."""
        if (
            self.schema_version != "public-acquisition"
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
        if len(self.receipts) > self._page_budget():
            raise ValueError("public acquisition exceeds page budget")
        # The job identity hashes the whole job; compute it once, not per receipt.
        job_identity = self.job.identity
        last: datetime | None = None
        for receipt in self.receipts:
            self._check_receipt(receipt, job_identity, last)
            last = receipt.raw.ts_ingested
        used = self._receipt_bytes()
        if self.pending is not None:
            self._check_pending(self.pending, job_identity, last)
            used += len(self.pending.payload)
        self._check_budget(used)

    def _request(self, request: PublicRequest, job_identity: str) -> None:
        """Ensure requests cannot escape the selected collection or implementation."""
        if (
            request.job_identity != job_identity
            or request.implementation_identity != self.implementation_identity
            or request.instrument not in self.job.instruments
        ):
            raise ValueError("public request differs from resolved job")
        self.job.universes.require(request.instrument.instrument_id, "collection")

    def _page_budget(self) -> int:
        """Return the most receipts the job may retain."""
        return self.job.max_pages + len(self.job.universes.collection)

    def _check_receipt(
        self, receipt: PublicReceipt, job_identity: str, last: datetime | None
    ) -> None:
        """Check one receipt after the receipts before it, whose last was ingested at ``last``."""
        if type(receipt) is not PublicReceipt:
            raise ValueError("invalid public receipt record")
        receipt.__post_init__()
        self._request(receipt.request, job_identity)
        if last is not None and receipt.raw.ts_received < last:
            raise ValueError("public receipt clock regressed")
        if self.finished_at is not None and receipt.raw.ts_ingested > self.finished_at:
            raise ValueError("completion precedes durable input")

    def _check_pending(
        self, pending: PendingResponse, job_identity: str, last: datetime | None
    ) -> None:
        """Check a pending response after the receipts, whose last was ingested at ``last``."""
        if type(pending) is not PendingResponse:
            raise ValueError("invalid public acquisition receipts")
        pending.__post_init__()
        self._request(pending.request, job_identity)
        if last is not None and pending.received < last:
            raise ValueError("pending receipt clock regressed")

    def _check_budget(self, used: int) -> None:
        """Refuse retained raw bytes beyond the job's aggregate budget."""
        if used > self.job.max_bytes:
            raise ValueError("public acquisition exceeds aggregate raw budget")

    def _with_pending(self, pending: PendingResponse) -> PublicAcquisition:
        """Return this validated state holding a new pending response.

        Only the new response is checked, with the same checks __post_init__
        applies to it. Every retained receipt was checked when it was added;
        checking all of them again made each page cost grow with the saved history.
        """
        if self.complete:
            raise ValueError("completed acquisition cannot have pending bytes")
        self._check_pending(pending, self.job.identity, self._last_ingested())
        self._check_budget(self._receipt_bytes() + len(pending.payload))
        successor = copy.copy(self)
        force_setattr(successor, "pending", pending)
        return successor

    def _with_receipt(self, receipt: PublicReceipt) -> PublicAcquisition:
        """Return this validated state with its pending response committed as a receipt.

        Only the new receipt and the budgets it changes are checked, with the
        same checks __post_init__ applies to it.
        """
        if len(self.receipts) + 1 > self._page_budget():
            raise ValueError("public acquisition exceeds page budget")
        self._check_receipt(receipt, self.job.identity, self._last_ingested())
        self._check_budget(self._receipt_bytes() + receipt.raw.size_bytes)
        receipts: tuple[PublicReceipt, ...] = (*self.receipts, receipt)
        successor = copy.copy(self)
        force_setattr(successor, "receipts", receipts)
        force_setattr(successor, "pending", None)
        return successor

    def _last_ingested(self) -> datetime | None:
        """Return when the last retained receipt was ingested, if any."""
        return self.receipts[-1].raw.ts_ingested if self.receipts else None

    def _receipt_bytes(self) -> int:
        """Sum the retained raw bytes of committed receipts."""
        return sum(r.raw.size_bytes for r in self.receipts)

    def save(self, path: Path) -> None:
        """Atomically fsync the single-writer checkpoint; uncertain writes must be reopened."""
        self.__post_init__()
        self._write(path)

    def _write(self, path: Path) -> None:
        """Atomically fsync this already validated state as the checkpoint."""
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
        # Verify the saved prefix once; each page committed below is verified as it lands.
        continuation = self._continuation(state)
        while True:
            request = continuation.next_request(state)
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
            if request.kind == "trades" and continuation.trade_pages >= job.max_pages:
                raise ValueError("public ingestion page budget exhausted; saved prefix retained")
            adapter = self._sources.public(request.instrument)
            if state.pending is None:
                host, endpoint = adapter.endpoint(job, request)
                payload = transport.get(host, endpoint)
                state = state._with_pending(
                    PendingResponse(request=request, payload=payload, received=clock())
                )
                state._write(path)
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
            state = state._with_receipt(PublicReceipt(request=request, raw=raw))
            state._write(path)
            self._verify(state.job, continuation, state.receipts[-1])
            if request.kind == "trades":
                sleep(job.poll_seconds)

    def next_request(self, state: PublicAcquisition) -> PublicRequest | None:
        """Reproduce all saved continuation decisions before exposing a next request.

        This verification also protects dataset readers from forged completion or
        reordered/foreign response descriptors. Capture completion proves only a
        bounded sample, never continuity between polling receipts.
        """
        return self._continuation(state).next_request(state)

    def _continuation(self, state: PublicAcquisition) -> _Continuation:
        """Validate a whole acquisition and replay every saved response in order."""
        state.__post_init__()
        continuation = _Continuation(state.job)
        for receipt in state.receipts:
            self._verify(state.job, continuation, receipt)
        return continuation

    def _verify(
        self, job: PublicDataJob, continuation: _Continuation, receipt: PublicReceipt
    ) -> None:
        """Reopen one committed response from the raw store, re-decode it and advance."""
        request = receipt.request
        adapter = self._sources.public(request.instrument)
        adapter.endpoint(job, request)
        with self._store.open(descriptor=receipt.raw, request=request.binding) as source:
            payload = source.read(job.max_bytes + 1)
        continuation.require(request)
        if request.kind == "reference":
            adapter.reference(request.instrument, payload, receipt.raw.ts_received)
            continuation.advance(request, None)
        else:
            continuation.advance(request, adapter.trades(job, request, payload))

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


class _Continuation:
    """Track each listing's verified page count, cursor and backfill completion.

    Built by replaying every saved response once on resume, then advanced by one
    committed response at a time, so choosing the next request does not reopen and
    re-decode the whole saved prefix for every new page.
    """

    def __init__(self, job: PublicDataJob) -> None:
        """Start before any reference or trade response of the job."""
        self._job = job
        self._cursors: dict[InstrumentId, str | None] = {}
        self._counts: dict[InstrumentId, int] = {}
        self._done: set[InstrumentId] = set()

    @property
    def trade_pages(self) -> int:
        """Count the trade responses advanced so far across every listing."""
        return sum(self._counts.values())

    def require(self, request: PublicRequest) -> None:
        """Refuse a response that is not its listing's next reference or trade page.

        Raises:
            ValueError: The response repeats a reference or breaks page continuity.
        """
        instrument = request.instrument.instrument_id
        if request.kind == "reference":
            if instrument in self._counts:
                raise ValueError("duplicate or reordered reference receipt")
        elif (
            instrument not in self._counts
            or instrument in self._done
            or request.ordinal != self._counts[instrument]
            or request.cursor != self._cursors[instrument]
        ):
            raise ValueError("public page is not the verified source continuation")

    def advance(self, request: PublicRequest, page: TradePage | None) -> None:
        """Move a listing past a required response that its adapter has decoded.

        Args:
            request: Response request already accepted by require().
            page: Decoded trade page, or None for a reference response.
        """
        instrument = request.instrument.instrument_id
        if page is None:
            self._counts[instrument], self._cursors[instrument] = 0, None
            return
        self._counts[instrument] += 1
        self._cursors[instrument] = page.next_cursor
        if self._job.mode == "backfill" and page.next_cursor is None:
            self._done.add(instrument)

    def next_request(self, state: PublicAcquisition) -> PublicRequest | None:
        """Choose the next request from the verified continuation of this state.

        Args:
            state: Acquisition whose committed receipts have all been advanced here.

        Returns:
            Next reference or trade request, or None when nothing remains.

        Raises:
            ValueError: A completed capture lacks a trade response for a listing.
        """
        selected = tuple(
            i for i in state.job.instruments if i.instrument_id in state.job.universes.collection
        )
        if state.complete and state.job.mode == "capture":
            if not PublicIngestion._has_pages(state):
                raise ValueError("completed capture lacks selected input receipts")
            return None
        remaining = [i for i in selected if i.instrument_id not in self._done]
        if not remaining:
            return None
        # Round robin guarantees each selected capture gets an observation.
        definition = min(remaining, key=_RequestPriority(self._counts))
        identity = definition.instrument_id
        return PublicRequest(
            job_identity=state.job.identity,
            implementation_identity=state.implementation_identity,
            instrument=definition,
            kind="reference" if identity not in self._counts else "trades",
            cursor=self._cursors.get(identity),
            ordinal=self._counts.get(identity, 0),
        )
