"""Persist the shared account head and its history tables under one SQLite transaction."""

from __future__ import annotations

# standard library imports
import hashlib
import operator
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from itertools import chain, compress
from pathlib import Path
from typing import Literal, NamedTuple, cast

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountState
from configuration import AccountConfiguration
from execution.account_records import (
    AccountControlResult,
    AccountDecision,
    AccountObservation,
    AccountPaperBinding,
    AccountPaperTrace,
    AccountQuote,
    AccountView,
    NativeFeeAllocation,
    NativeFill,
    NetFeeAllocation,
    NetFeeCorrection,
    NetOrder,
    PhysicalAccountObservation,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.account_reduction import PaperReductionResult
from execution.paper_authority import PaperActivation
from execution.records import ORDER_EVENT_KINDS, OrderEvent, OrderState, StepCommit
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, SqliteLayout, WireRecord


class SavedDecision(WireRecord, frozen=True):
    """Retain original request and outcome for restart-safe idempotent admission."""

    request: AccountDecision
    result: StepCommit


class _SavedEvent(WireRecord, frozen=True):
    """Bind normalized receipt identity to exact bytes and original outcome."""

    event: OrderEvent
    result: OrderState


class _Reconciliation(WireRecord, frozen=True):
    """Retain both matching and broken observation attempts."""

    observation: AccountObservation
    matched: bool


class SavedPortfolioBatch(WireRecord, frozen=True):
    """Retain exact coordination input and outcome for transport retry."""

    batch: PortfolioBatch
    result: PortfolioCommit


class _SavedNetEvent(WireRecord, frozen=True):
    """Retain one physical event, parent result and child fill identities."""

    event: OrderEvent
    result: NetOrder
    child_fill_ids: tuple[str, ...]
    fee_only_ids: tuple[str, ...] = ()
    fee_allocations: tuple[NetFeeAllocation, ...] = ()


class _SavedNativeFill(WireRecord, frozen=True):
    """Retain exact external trade bytes and independent native cost lineage."""

    request: NativeFill
    allocations: tuple[NativeFeeAllocation, ...] = ()


class _PhysicalReconciliation(WireRecord, frozen=True):
    """Retain an attempted venue wallet/open-order comparison and its outcome."""

    observation: PhysicalAccountObservation
    matched: bool


class _InstanceControl(WireRecord, frozen=True):
    """Retain a selective stop or restart clock even without outstanding orders."""

    instance_id: str
    at: datetime
    state: Literal["stopped", "running"]

    def __post_init__(self) -> None:
        """Require a known UTC control transition."""
        self._require_utc(self.at, field_name="instance control")
        if not self.instance_id or self.state not in ("stopped", "running"):
            raise ValueError("invalid instance control")


class FirmState(WireRecord, frozen=True):
    """Hold the complete local transaction boundary.

    The three history tuples hold only the items staged by the current
    transaction; committed items live in their own tables and are reached through
    the history lookups.
    """

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...] = ()
    quotes: tuple[AccountQuote, ...] = ()
    decisions: tuple[SavedDecision, ...] = ()
    events: tuple[_SavedEvent, ...] = ()
    reconciliations: tuple[_Reconciliation, ...] = ()
    failed_events: tuple[OrderEvent, ...] = ()
    failed_postings: tuple[AccountPosting, ...] = ()
    portfolio_batches: tuple[SavedPortfolioBatch, ...] = ()
    net_orders: tuple[NetOrder, ...] = ()
    net_events: tuple[_SavedNetEvent, ...] = ()
    failed_net_events: tuple[OrderEvent, ...] = ()
    stopped_instances: tuple[str, ...] = ()
    crossing_policy: str | None = None
    net_fee_corrections: tuple[NetFeeCorrection, ...] = ()
    instance_controls: tuple[_InstanceControl, ...] = ()
    residuals: tuple[PortfolioResidual, ...] = ()
    account_controls: tuple[AccountControlResult, ...] = ()
    native_fills: tuple[_SavedNativeFill, ...] = ()
    failed_native_fills: tuple[NativeFill, ...] = ()
    physical_reconciliations: tuple[_PhysicalReconciliation, ...] = ()
    paper_bindings: tuple[AccountPaperBinding, ...] = ()
    paper_traces: tuple[AccountPaperTrace, ...] = ()
    paper_activations: tuple[PaperActivation, ...] = ()
    paper_reductions: tuple[PaperReductionResult, ...] = ()
    paper_restore_quarantine: bool = False


class HistoryDigest(WireRecord, frozen=True):
    """Bind one history table's row count to a hash chain over its item bytes."""

    count: int
    sha256: str

    def __post_init__(self) -> None:
        """Require an empty chain for no rows and a sha256 digest otherwise."""
        HistoryDigest.require_shape(self.count, self.sha256, "invalid account history digest")

    def extend(self, item: bytes) -> HistoryDigest:
        """Chain one more item's exact bytes after the current rows."""
        digest = hashlib.sha256(bytes.fromhex(self.sha256) + item).hexdigest()
        return HistoryDigest(count=self.count + 1, sha256=digest)

    @staticmethod
    def require_shape(count: object, sha256: object, message: str) -> None:
        """Require a row count, with no digest for no rows and lowercase hex sha256 otherwise."""
        if (
            type(count) is not int
            or count < 0
            or type(sha256) is not str
            or (sha256 == "") != (count == 0)
            or (count and (len(sha256) != 64 or sha256 != sha256.lower()))
        ):
            raise ValueError(message)
        try:
            bytes.fromhex(sha256)
        except ValueError:
            raise ValueError(message) from None


class _InstanceCheckpoint(WireRecord, frozen=True):
    """Retain an instance's latest continuation so restart needs no history scan."""

    instance_id: str
    checkpoint: bytes


class RowSummary(WireRecord, frozen=True):
    """Bind one row-kept state field to its row count and a digest of its row digests."""

    field: str
    count: int
    sha256: str

    def __post_init__(self) -> None:
        """Require a field name, an empty digest for no rows and a sha256 digest otherwise."""
        if type(self.field) is not str or not self.field:
            raise ValueError("invalid account state row summary")
        HistoryDigest.require_shape(self.count, self.sha256, "invalid account state row summary")

    @staticmethod
    def of(field: str, digests: list[bytes]) -> RowSummary:
        """Summarize rows from their sha256 digests in position order."""
        return RowSummary(
            field=field,
            count=len(digests),
            sha256=hashlib.sha256(b"".join(digests)).hexdigest() if digests else "",
        )


class HistorySummary(WireRecord, frozen=True):
    """Summarize the history tables and state rows committed with one head."""

    decisions: HistoryDigest
    portfolio_batches: HistoryDigest
    paper_traces: HistoryDigest
    checkpoints: tuple[_InstanceCheckpoint, ...]
    rows: tuple[RowSummary, ...]

    def __post_init__(self) -> None:
        """Require one checkpoint entry per instance and one summary per row field."""
        if len({item.instance_id for item in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("invalid account history checkpoints")
        if len({item.field for item in self.rows}) != len(self.rows):
            raise ValueError("invalid account state row summaries")


class FirmHead(WireRecord, frozen=True):
    """Persist the live head: current state without history, plus its summary.

    Paper activation is recorded only by the presence of ``paper_activations``.
    ``event_kinds`` names the order-event vocabulary the journal's facts are
    written in. A head without it, or with another vocabulary, belongs to another
    journal format: the facts' meaning differs, so it is refused, not reread.
    """

    history: HistorySummary
    state: FirmState
    # Strings, not EventKind: a head written under any other vocabulary must reach
    # the refusal below instead of failing as a malformed literal.
    event_kinds: tuple[str, ...] = ()
    schema_version: Literal["account-journal"] = "account-journal"

    def __post_init__(self) -> None:
        """Reject other schemas and keep committed history and row fields out of the head."""
        if (
            self.schema_version != "account-journal"
            or self.event_kinds != ORDER_EVENT_KINDS
            or self.state.decisions
            or self.state.portfolio_batches
            or self.state.paper_traces
            or any(cast(tuple[object, ...], getattr(self.state, name)) for name, _ in _ROW_FIELDS)
            or any(account.ledger.postings for account in self.state.accounts)
        ):
            raise ValueError("unsupported account journal state schema")


# State fields that grow with history. Each is kept as rows keyed by tuple
# position, with a sha256 per row; each account's postings are kept the same way.
_ROW_FIELDS: tuple[tuple[str, type[msgspec.Struct]], ...] = (
    ("events", _SavedEvent),
    ("net_events", _SavedNetEvent),
    ("reconciliations", _Reconciliation),
    ("orders", TaggedOrder),
    ("net_orders", NetOrder),
    ("native_fills", _SavedNativeFill),
    ("physical_reconciliations", _PhysicalReconciliation),
)
_POSTINGS = "postings:"
_ROWS_TABLE = (
    "CREATE TABLE state_rows (field TEXT NOT NULL, seq INTEGER NOT NULL, "
    "sha256 TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(field, seq))"
)


class _LoadedHead(NamedTuple):
    """A committed head's history summary with its complete in-memory state."""

    history: HistorySummary
    state: FirmState


class _CachedRows(NamedTuple):
    """One row field's committed items, their row digests and its summary."""

    items: tuple[object, ...]
    digests: list[bytes]
    summary: RowSummary


class StateRows:
    """Keep row-kept state fields in ``state_rows`` and reuse decoded rows in process.

    A commit skips a field whose tuple is unchanged, writes only rows whose item
    changed (by object identity, then by bytes) and deletes rows past a
    shortened tuple. A read compares each field's summary with the cached rows
    and decodes only rows whose digest differs, so another process's commit
    costs one digest scan plus its changed rows.
    """

    def __init__(self, codec: DomainCodec) -> None:
        """Start with no cached rows."""
        self.codec = codec
        self._cache: dict[str, _CachedRows] = {}

    def write(
        self,
        connection: sqlite3.Connection,
        committed: dict[str, tuple[object, ...]],
        staged: dict[str, tuple[object, ...]],
    ) -> tuple[tuple[RowSummary, ...], dict[str, _CachedRows]]:
        """Write changed rows; return the summaries and the cache entries to keep on commit."""
        summaries: list[RowSummary] = []
        updates: dict[str, _CachedRows] = {}
        for field in sorted(staged):
            items = staged[field]
            before = committed.get(field, ())
            cached = self._cache.get(field)
            if cached is not None and cached.items is before:
                if items is before:
                    # An untouched field keeps its rows and summary.
                    summaries.append(cached.summary)
                    continue
                digests = list(cached.digests)
            else:
                digests = self._digests(connection, field)
            if len(digests) != len(before):
                raise ValueError("account journal state rows differ from its head")
            # Positions whose item is another object, then appended positions.
            replaced: Iterable[bool] = map(operator.is_not, items, before)
            kept = min(len(items), len(before))
            positions: Iterable[int] = chain(
                compress(range(kept), replaced), range(len(before), len(items))
            )
            for index in positions:
                item = items[index]
                payload = self.codec.encode_json(item)
                digest = hashlib.sha256(payload).digest()
                if index < len(digests):
                    if digests[index] == digest:
                        continue
                    digests[index] = digest
                    connection.execute(
                        "UPDATE state_rows SET sha256=?, payload=? WHERE field=? AND seq=?",
                        (digest.hex(), payload, field, index),
                    )
                else:
                    digests.append(digest)
                    connection.execute(
                        "INSERT INTO state_rows VALUES (?, ?, ?, ?)",
                        (field, index, digest.hex(), payload),
                    )
            if len(items) < len(digests):
                connection.execute(
                    "DELETE FROM state_rows WHERE field=? AND seq>=?", (field, len(items))
                )
                del digests[len(items) :]
            summary = RowSummary.of(field, digests)
            updates[field] = _CachedRows(items, digests, summary)
            summaries.append(summary)
        return tuple(summaries), updates

    def accept(self, updates: dict[str, _CachedRows]) -> None:
        """Cache rows whose commit succeeded."""
        self._cache.update(updates)

    def load(
        self, connection: sqlite3.Connection, summary: HistorySummary
    ) -> dict[str, tuple[object, ...]]:
        """Return every row-kept tuple, decoding only rows the cache does not hold."""
        values: dict[str, tuple[object, ...]] = {}
        for expected in summary.rows:
            field = expected.field
            cached = self._cache.get(field)
            if cached is not None and cached.summary == expected:
                values[field] = cached.items
                continue
            target = self._target(field)
            items: list[object] = []
            if cached is None:
                rows = cast(
                    list[tuple[object, ...]],
                    connection.execute(
                        "SELECT seq, sha256, payload FROM state_rows WHERE field=? ORDER BY seq",
                        (field,),
                    ).fetchall(),
                )
                digests = [self._digest(row, index) for index, row in enumerate(rows)]
                for row, digest in zip(rows, digests, strict=True):
                    items.append(self._decode(row[2], digest, target))
            else:
                digests = self._digests(connection, field)
                for index, digest in enumerate(digests):
                    if index < len(cached.digests) and cached.digests[index] == digest:
                        items.append(cached.items[index])
                        continue
                    stored = cast(
                        tuple[object, ...] | None,
                        connection.execute(
                            "SELECT payload FROM state_rows WHERE field=? AND seq=?",
                            (field, index),
                        ).fetchone(),
                    )
                    if stored is None:
                        raise ValueError("account journal state rows differ from its head")
                    items.append(self._decode(stored[0], digest, target))
            loaded = RowSummary.of(field, digests)
            if loaded != expected:
                raise ValueError("account journal state rows differ from its head")
            values[field] = tuple(items)
            self._cache[field] = _CachedRows(values[field], digests, loaded)
        return values

    def verify(self, connection: sqlite3.Connection, summary: HistorySummary) -> None:
        """Require stored row fields to be exactly those the head summarizes."""
        stored = cast(
            list[tuple[object, ...]],
            connection.execute("SELECT DISTINCT field FROM state_rows").fetchall(),
        )
        present = {item.field for item in summary.rows}
        if any(row[0] not in present for row in stored):
            raise ValueError("account journal state rows differ from its head")

    def _digests(self, connection: sqlite3.Connection, field: str) -> list[bytes]:
        """Read one field's row digests in position order."""
        rows = cast(
            list[tuple[object, ...]],
            connection.execute(
                "SELECT seq, sha256 FROM state_rows WHERE field=? ORDER BY seq", (field,)
            ).fetchall(),
        )
        return [self._digest(row, index) for index, row in enumerate(rows)]

    @staticmethod
    def _digest(row: tuple[object, ...], index: int) -> bytes:
        """Require contiguous positions and a well-formed stored digest."""
        if row[0] != index or type(row[1]) is not str or len(row[1]) != 64:
            raise ValueError("account journal state rows differ from its head")
        return bytes.fromhex(row[1])

    def _decode(self, payload: object, digest: bytes, target: type[msgspec.Struct]) -> object:
        """Decode one row after checking its bytes against its digest."""
        if type(payload) is not bytes or hashlib.sha256(payload).digest() != digest:
            raise ValueError("account journal state rows differ from its head")
        return self.codec.decode_json(payload, target)

    @staticmethod
    def _target(field: str) -> type[msgspec.Struct]:
        """Return the element type of a row field."""
        if field.startswith(_POSTINGS) and len(field) > len(_POSTINGS):
            return AccountPosting
        for name, target in _ROW_FIELDS:
            if name == field:
                return target
        raise ValueError("account journal state rows differ from its head")

    @staticmethod
    def row_values(state: FirmState) -> dict[str, tuple[object, ...]]:
        """Return every row-kept tuple of a complete state by its row field name."""
        values: dict[str, tuple[object, ...]] = {
            name: cast(tuple[object, ...], getattr(state, name)) for name, _ in _ROW_FIELDS
        }
        for account in state.accounts:
            values[_POSTINGS + account.ledger.account_id] = account.ledger.postings
        return values

    @staticmethod
    def strip(state: FirmState) -> FirmState:
        """Return the head part of a complete state: row-kept fields and postings emptied."""
        accounts: list[AccountView] = []
        for account in state.accounts:
            ledger: AccountState = replace(account.ledger, postings=())
            accounts.append(replace(account, ledger=ledger))
        views: tuple[AccountView, ...] = tuple(accounts)
        emptied: dict[str, object] = {name: () for name, _ in _ROW_FIELDS}
        return replace(state, accounts=views, **emptied)

    @staticmethod
    def assemble(state: FirmState, values: dict[str, tuple[object, ...]]) -> FirmState:
        """Restore a head state's row-kept fields and postings from decoded rows."""
        expected = {name for name, _ in _ROW_FIELDS} | {
            _POSTINGS + account.ledger.account_id for account in state.accounts
        }
        if set(values) != expected:
            raise ValueError("account journal state rows differ from its head")
        accounts: list[AccountView] = []
        for account in state.accounts:
            postings = cast(
                tuple[AccountPosting, ...], values[_POSTINGS + account.ledger.account_id]
            )
            # Decoding validated each posting row; attach reuses or extends a remembered
            # fold instead of validating and replaying the whole history again.
            ledger = AccountLedger.attach(account.ledger, postings)
            accounts.append(replace(account, ledger=ledger))
        views: tuple[AccountView, ...] = tuple(accounts)
        rows: dict[str, object] = {name: values[name] for name, _ in _ROW_FIELDS}
        return replace(state, accounts=views, **rows)


_EMPTY_HISTORY = HistorySummary(
    decisions=HistoryDigest(count=0, sha256=""),
    portfolio_batches=HistoryDigest(count=0, sha256=""),
    paper_traces=HistoryDigest(count=0, sha256=""),
    checkpoints=(),
    rows=(),
)

_HISTORY_TABLES = (
    "CREATE TABLE decisions (seq INTEGER PRIMARY KEY, instance_id TEXT NOT NULL, "
    "decision_identity TEXT NOT NULL, payload BLOB NOT NULL, "
    "UNIQUE(instance_id, decision_identity))",
    "CREATE INDEX decisions_instance ON decisions(instance_id, seq)",
    "CREATE TABLE portfolio_batches (seq INTEGER PRIMARY KEY, "
    "batch_identity TEXT NOT NULL UNIQUE, payload BLOB NOT NULL)",
    "CREATE TABLE paper_traces (seq INTEGER PRIMARY KEY, account_id TEXT NOT NULL, "
    "venue TEXT NOT NULL, instrument_id TEXT NOT NULL, market_identity TEXT NOT NULL, "
    "filled INTEGER NOT NULL CHECK(filled IN (0, 1)), "
    "payload BLOB NOT NULL, UNIQUE(account_id, venue, instrument_id, market_identity))",
    "CREATE INDEX paper_traces_market ON paper_traces(market_identity, seq)",
    "CREATE INDEX paper_traces_account ON paper_traces(account_id, seq)",
    "CREATE INDEX paper_traces_instrument ON paper_traces(account_id, instrument_id, seq)",
    # Only the few traces that posted fills: report facts never decode the rest.
    "CREATE INDEX paper_traces_filled ON paper_traces(account_id, seq) WHERE filled=1",
)


# A dispatch lease is transient coordination, not history: no digest covers it.
_LEASE_TABLE = (
    "CREATE TABLE dispatch_leases (order_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, "
    "instance_ids BLOB NOT NULL, holder TEXT NOT NULL, armed_at TEXT NOT NULL)"
)
_FIRM_TABLE = (
    "CREATE TABLE IF NOT EXISTS firm (id INTEGER PRIMARY KEY CHECK(id=1), "
    "configuration BLOB NOT NULL, payload BLOB NOT NULL)"
)
# The complete journal layout: every table, column, constraint and index.
_LAYOUT = (_FIRM_TABLE, *_HISTORY_TABLES, _LEASE_TABLE, _ROWS_TABLE)


class DispatchLease(WireRecord, frozen=True):
    """Hold one physical send outside the journal transaction until it is released.

    Arming commits the final dispatch checks and this lease together; the send
    runs with no transaction open; release deletes it. While the lease exists its
    holder process holds an OS lock named by ``holder``. A stop-type writer for the
    same account or instance waits until the lease is released or that lock is
    free (its holder died), so no stop commits while a send it did not precede is
    pending. ``armed_at`` is informational; no clock expires a lease.
    """

    order_id: str
    account_id: str
    instance_ids: tuple[str, ...]
    holder: str
    armed_at: datetime

    def __post_init__(self) -> None:
        """Require identities and a UTC arming time."""
        self._require_utc(self.armed_at, field_name="lease armed_at")
        if (
            not self.order_id
            or not self.account_id
            or not self.holder.isalnum()
            or type(self.instance_ids) is not tuple
        ):
            raise ValueError("invalid dispatch lease")


# Each table's insert and ordered full read, as (seq, *key columns, payload).
_TABLE_STATEMENTS: dict[str, tuple[str, str]] = {
    "decisions": (
        "INSERT INTO decisions (seq, instance_id, decision_identity, payload) VALUES (?, ?, ?, ?)",
        "SELECT seq, instance_id, decision_identity, payload FROM decisions ORDER BY seq",
    ),
    "portfolio_batches": (
        "INSERT INTO portfolio_batches (seq, batch_identity, payload) VALUES (?, ?, ?)",
        "SELECT seq, batch_identity, payload FROM portfolio_batches ORDER BY seq",
    ),
    "paper_traces": (
        "INSERT INTO paper_traces (seq, account_id, venue, instrument_id, market_identity, "
        "filled, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
        "SELECT seq, account_id, venue, instrument_id, market_identity, filled, payload "
        "FROM paper_traces ORDER BY seq",
    ),
}
# Repeating the partial index's filled=1 term lets SQLite read only fill-bearing rows.
_FILLED_TRACES_AFTER = (
    "SELECT seq, payload FROM paper_traces "
    "WHERE account_id=? AND filled=1 AND seq>? ORDER BY seq ASC"
)
# Optional trace keys match any value when their parameter is NULL.
_FIND_TRACE = (
    "SELECT payload FROM paper_traces WHERE market_identity=?1 "
    "AND (?2 IS NULL OR account_id=?2) AND (?3 IS NULL OR venue=?3) "
    "AND (?4 IS NULL OR instrument_id=?4) ORDER BY seq LIMIT 1"
)
# One statement per present filter and order, keyed (account, instrument, newest
# first), so SQLite can use paper_traces_account or paper_traces_instrument. An
# "?1 IS NULL OR account_id=?1" parameter would force a full scan of every account.
_ITER_TRACES = {
    (False, False, False): "SELECT payload FROM paper_traces ORDER BY seq ASC",
    (False, False, True): "SELECT payload FROM paper_traces ORDER BY seq DESC",
    (True, False, False): "SELECT payload FROM paper_traces WHERE account_id=? ORDER BY seq ASC",
    (True, False, True): "SELECT payload FROM paper_traces WHERE account_id=? ORDER BY seq DESC",
    (False, True, False): (
        "SELECT payload FROM paper_traces WHERE instrument_id=? ORDER BY seq ASC"
    ),
    (False, True, True): (
        "SELECT payload FROM paper_traces WHERE instrument_id=? ORDER BY seq DESC"
    ),
    (True, True, False): (
        "SELECT payload FROM paper_traces WHERE account_id=? AND instrument_id=? ORDER BY seq ASC"
    ),
    (True, True, True): (
        "SELECT payload FROM paper_traces WHERE account_id=? AND instrument_id=? ORDER BY seq DESC"
    ),
}


class _HistoryTables:
    """Read committed history rows inside one open SQLite transaction."""

    def __init__(
        self, connection: sqlite3.Connection, codec: DomainCodec, summary: HistorySummary
    ) -> None:
        """Bind the connection whose transaction fixes the visible rows."""
        self.connection = connection
        self.codec = codec
        self.summary = summary
        self._checkpoints: dict[str, bytes] | None = None

    def find_decision(self, instance_id: str, decision_identity: str) -> SavedDecision | None:
        """Resolve one committed decision by its unique key."""
        payload = self._payload(
            "SELECT payload FROM decisions WHERE instance_id=? AND decision_identity=?",
            (instance_id, decision_identity),
        )
        return None if payload is None else self.codec.decode_json(payload, SavedDecision)

    def latest_checkpoint(self, instance_id: str) -> bytes | None:
        """Read the instance's latest committed continuation from the head."""
        if self._checkpoints is None:
            self._checkpoints = {
                item.instance_id: item.checkpoint for item in self.summary.checkpoints
            }
        return self._checkpoints.get(instance_id)

    def find_batch(self, identity: str) -> SavedPortfolioBatch | None:
        """Resolve one committed portfolio batch by its unique identity."""
        payload = self._payload(
            "SELECT payload FROM portfolio_batches WHERE batch_identity=?", (identity,)
        )
        return None if payload is None else self.codec.decode_json(payload, SavedPortfolioBatch)

    def find_trace(
        self,
        market_identity: str,
        *,
        account_id: str | None,
        venue: str | None,
        instrument_id: InstrumentId | None,
    ) -> AccountPaperTrace | None:
        """Return the earliest committed trace of a market identity within the given keys."""
        payload = self._payload(
            _FIND_TRACE, (market_identity, account_id, venue, self._instrument(instrument_id))
        )
        return None if payload is None else self.codec.decode_json(payload, AccountPaperTrace)

    def iter_traces(
        self, account_id: str | None, instrument_id: InstrumentId | None, *, newest_first: bool
    ) -> Iterator[AccountPaperTrace]:
        """Yield committed traces in commit order, or reversed."""
        instrument = self._instrument(instrument_id)
        cursor = self.connection.execute(
            _ITER_TRACES[(account_id is not None, instrument is not None, newest_first)],
            tuple(item for item in (account_id, instrument) if item is not None),
        )
        for row in cast(Iterator[tuple[object, ...]], cursor):
            yield self.codec.decode_json(self._blob(row[0]), AccountPaperTrace)

    def iter_decisions(self) -> Iterator[SavedDecision]:
        """Yield committed decisions in commit order."""
        cursor = self.connection.execute("SELECT payload FROM decisions ORDER BY seq ASC")
        for row in cast(Iterator[tuple[object, ...]], cursor):
            yield self.codec.decode_json(self._blob(row[0]), SavedDecision)

    def iter_filled_traces_after(
        self, account_id: str, after_seq: int
    ) -> Iterator[tuple[int, AccountPaperTrace]]:
        """Yield one account's committed fill-bearing traces after a sequence, in order."""
        cursor = self.connection.execute(_FILLED_TRACES_AFTER, (account_id, after_seq))
        for row in cast(Iterator[tuple[object, ...]], cursor):
            yield cast(int, row[0]), self.codec.decode_json(self._blob(row[1]), AccountPaperTrace)

    def append(self, state: FirmState) -> HistorySummary:
        """Insert the state's staged history items and return the extended summary."""
        decisions = self._insert(
            "decisions", self.summary.decisions, state.decisions, _HistoryTables._decision_key
        )
        batches = self._insert(
            "portfolio_batches",
            self.summary.portfolio_batches,
            state.portfolio_batches,
            _HistoryTables._batch_key,
        )
        traces = self._insert(
            "paper_traces", self.summary.paper_traces, state.paper_traces, _HistoryTables._trace_key
        )
        checkpoints = {item.instance_id: item.checkpoint for item in self.summary.checkpoints}
        for saved in state.decisions:
            checkpoints[saved.request.instance_id] = saved.request.checkpoint
        return HistorySummary(
            decisions=decisions,
            portfolio_batches=batches,
            paper_traces=traces,
            checkpoints=tuple(
                _InstanceCheckpoint(instance_id=instance_id, checkpoint=checkpoint)
                for instance_id, checkpoint in checkpoints.items()
            ),
            rows=self.summary.rows,
        )

    def verify(self) -> None:
        """Check every row, its key columns and the head's counts, digests and checkpoints."""
        decisions = self._verify_table("decisions", SavedDecision, _HistoryTables._decision_key)
        self._verify_table("portfolio_batches", SavedPortfolioBatch, _HistoryTables._batch_key)
        self._verify_table("paper_traces", AccountPaperTrace, _HistoryTables._trace_key)
        checkpoints: dict[str, bytes] = {}
        for saved in decisions:
            checkpoints[saved.request.instance_id] = saved.request.checkpoint
        expected = tuple(
            _InstanceCheckpoint(instance_id=instance_id, checkpoint=checkpoint)
            for instance_id, checkpoint in checkpoints.items()
        )
        if expected != self.summary.checkpoints:
            raise ValueError("account journal history differs from its head")

    def _insert[T](
        self,
        table: str,
        digest: HistoryDigest,
        items: tuple[T, ...],
        key: Callable[[T], tuple[str | int, ...]],
    ) -> HistoryDigest:
        """Append staged items after the committed rows, extending the table's chain."""
        statement = _TABLE_STATEMENTS[table][0]
        for item in items:
            payload = self.codec.encode_json(item)
            self.connection.execute(statement, (digest.count, *key(item), payload))
            digest = digest.extend(payload)
        return digest

    def _verify_table[T](
        self, table: str, target: type[T], key: Callable[[T], tuple[str | int, ...]]
    ) -> list[T]:
        """Decode one table in order and compare it with the head's digest."""
        cursor = self.connection.execute(_TABLE_STATEMENTS[table][1])
        digest = HistoryDigest(count=0, sha256="")
        items: list[T] = []
        for row in cast(Iterator[tuple[object, ...]], cursor):
            payload = self._blob(row[-1])
            item = self.codec.decode_json(payload, target)
            if row[0] != digest.count or row[1:-1] != key(item):
                raise ValueError("account journal history differs from its head")
            digest = digest.extend(payload)
            items.append(item)
        expected: object = getattr(self.summary, table)
        if digest != expected:
            raise ValueError("account journal history differs from its head")
        return items

    @staticmethod
    def _instrument(instrument_id: InstrumentId | None) -> str | None:
        """Return the stored text of an optional instrument key."""
        return None if instrument_id is None else str(instrument_id.uuid_value)

    def _payload(self, statement: str, parameters: tuple[str | None, ...]) -> bytes | None:
        """Fetch one optional payload."""
        row = cast(
            tuple[object, ...] | None, self.connection.execute(statement, parameters).fetchone()
        )
        return None if row is None else self._blob(row[0])

    @staticmethod
    def _blob(value: object) -> bytes:
        """Require an exact stored item payload."""
        if type(value) is not bytes:
            raise ValueError("account journal history row is malformed")
        return value

    @staticmethod
    def _decision_key(saved: SavedDecision) -> tuple[str, ...]:
        """Return the decisions table lookup columns."""
        return saved.request.instance_id, saved.request.decision.identity

    @staticmethod
    def _batch_key(saved: SavedPortfolioBatch) -> tuple[str, ...]:
        """Return the portfolio batches table lookup column."""
        return (saved.batch.identity,)

    @staticmethod
    def _trace_key(trace: AccountPaperTrace) -> tuple[str | int, ...]:
        """Return the paper traces table lookup columns, including the fill flag."""
        return (
            trace.account_id,
            trace.scenario.venue,
            str(trace.scenario.instrument_id.uuid_value),
            trace.market.identity,
            int(trace.filled),
        )


class _AccountSnapshot:
    """Answer history lookups by identity without exposing collection storage.

    Committed rows precede the items staged in ``state``.
    """

    def __init__(self, state: FirmState, tables: _HistoryTables) -> None:
        """Retain one immutable state value and its committed history."""
        self.state = state
        self.tables = tables

    def iter_committed_filled_traces_after(
        self, account_id: str, after_seq: int
    ) -> Iterator[tuple[int, AccountPaperTrace]]:
        """Yield one account's committed fill-bearing traces after a sequence; no staged ones."""
        return self.tables.iter_filled_traces_after(account_id, after_seq)

    def find_decision(self, instance_id: str, decision_identity: str) -> SavedDecision | None:
        """Resolve one saved decision by instance and decision identity."""
        committed = self.tables.find_decision(instance_id, decision_identity)
        if committed is not None:
            return committed
        for saved in self.state.decisions:
            if (saved.request.instance_id, saved.request.decision.identity) == (
                instance_id,
                decision_identity,
            ):
                return saved
        return None

    def iter_decisions(self) -> Iterator[SavedDecision]:
        """Yield saved decisions in commit order, committed rows before staged ones."""
        yield from self.tables.iter_decisions()
        yield from self.state.decisions

    def latest_checkpoint(self, instance_id: str) -> bytes | None:
        """Return the continuation of the instance's latest admitted or rejected decision."""
        for saved in reversed(self.state.decisions):
            if saved.request.instance_id == instance_id:
                return saved.request.checkpoint
        return self.tables.latest_checkpoint(instance_id)

    def find_batch(self, identity: str) -> SavedPortfolioBatch | None:
        """Resolve one saved portfolio batch by its stable identity."""
        committed = self.tables.find_batch(identity)
        if committed is not None:
            return committed
        for saved in self.state.portfolio_batches:
            if saved.batch.identity == identity:
                return saved
        return None

    def find_trace(
        self,
        market_identity: str,
        *,
        account_id: str | None = None,
        venue: str | None = None,
        instrument_id: InstrumentId | None = None,
    ) -> AccountPaperTrace | None:
        """Return the earliest trace of one market identity, narrowed by the given keys."""
        committed = self.tables.find_trace(
            market_identity, account_id=account_id, venue=venue, instrument_id=instrument_id
        )
        if committed is not None:
            return committed
        for trace in self.state.paper_traces:
            if (
                trace.market.identity == market_identity
                and (account_id is None or trace.account_id == account_id)
                and (venue is None or trace.scenario.venue == venue)
                and (instrument_id is None or trace.scenario.instrument_id == instrument_id)
            ):
                return trace
        return None

    def iter_traces(
        self,
        account_id: str | None = None,
        *,
        instrument_id: InstrumentId | None = None,
        newest_first: bool = False,
    ) -> Iterator[AccountPaperTrace]:
        """Yield traces in commit order, or reversed, optionally within one account/instrument."""
        staged = (
            trace
            for trace in (
                reversed(self.state.paper_traces) if newest_first else self.state.paper_traces
            )
            if (account_id is None or trace.account_id == account_id)
            and (instrument_id is None or trace.scenario.instrument_id == instrument_id)
        )
        committed = self.tables.iter_traces(account_id, instrument_id, newest_first=newest_first)
        if newest_first:
            yield from staged
            yield from committed
        else:
            yield from committed
            yield from staged


class AccountTransaction(_AccountSnapshot):
    """Own the staged state of a single serialized firm transaction."""

    # Identity lookups of the current order tuples; see find_order and find_net_order.
    _order_index: tuple[tuple[TaggedOrder, ...], dict[str, TaggedOrder]] | None = None
    _net_order_index: tuple[tuple[NetOrder, ...], dict[str, NetOrder]] | None = None

    def append_decisions(self, *saved: SavedDecision) -> None:
        """Append saved decisions after all existing history."""
        decisions: tuple[SavedDecision, ...] = (*self.state.decisions, *saved)
        self.state = replace(self.state, decisions=decisions)

    def append_batch(self, saved: SavedPortfolioBatch) -> None:
        """Append one saved portfolio batch after all existing history."""
        batches: tuple[SavedPortfolioBatch, ...] = (*self.state.portfolio_batches, saved)
        self.state = replace(self.state, portfolio_batches=batches)

    def append_trace(self, trace: AccountPaperTrace) -> None:
        """Append one paper trace after all existing history."""
        traces: tuple[AccountPaperTrace, ...] = (*self.state.paper_traces, trace)
        self.state = replace(self.state, paper_traces=traces)

    def account(self, account_id: str) -> AccountView:
        """Resolve a configured account without creating implicit authority."""
        for account in self.state.accounts:
            if account.ledger.account_id == account_id:
                return account
        raise ValueError("unknown account")

    def save_account(self, account: AccountView) -> None:
        """Replace one staged account without disturbing other accounts."""
        accounts: tuple[AccountView, ...] = tuple(
            account if item.ledger.account_id == account.ledger.account_id else item
            for item in self.state.accounts
        )
        self.state = replace(self.state, accounts=accounts)

    def find_order(self, order_id: str) -> TaggedOrder | None:
        """Return the child order with this identity, through an index of the current tuple."""
        orders = self.state.orders
        if self._order_index is None or self._order_index[0] is not orders:
            # Reversed, so the first order with an identity wins, as a scan would.
            self._order_index = orders, {item.order.identity: item for item in reversed(orders)}
        return self._order_index[1].get(order_id)

    def order(self, order_id: str) -> TaggedOrder:
        """Resolve exact persisted order identity."""
        tagged = self.find_order(order_id)
        if tagged is None:
            raise ValueError("unknown child order")
        return tagged

    def save_order(self, tagged: TaggedOrder) -> None:
        """Replace an existing tagged order preserving stable sequence."""
        orders: tuple[TaggedOrder, ...] = tuple(
            tagged if item.order.identity == tagged.order.identity else item
            for item in self.state.orders
        )
        self.state = replace(self.state, orders=orders)

    def find_net_order(self, order_id: str) -> NetOrder | None:
        """Return the physical order with this identity, through an index of the current tuple."""
        parents = self.state.net_orders
        if self._net_order_index is None or self._net_order_index[0] is not parents:
            self._net_order_index = (
                parents,
                {item.order.identity: item for item in reversed(parents)},
            )
        return self._net_order_index[1].get(order_id)

    def net_order(self, order_id: str) -> NetOrder:
        """Resolve a physical order without confusing it with child ownership."""
        parent = self.find_net_order(order_id)
        if parent is None:
            raise ValueError("unknown physical order")
        return parent

    def save_net_order(self, parent: NetOrder) -> None:
        """Replace one physical lifecycle and allocation snapshot in place."""
        net_orders: tuple[NetOrder, ...] = tuple(
            parent if item.order.identity == parent.order.identity else item
            for item in self.state.net_orders
        )
        self.state = replace(self.state, net_orders=net_orders)

    def leases(self) -> tuple[DispatchLease, ...]:
        """Read every dispatch lease visible to this transaction."""
        rows = cast(
            list[tuple[object, ...]],
            self.tables.connection.execute(
                "SELECT order_id, account_id, instance_ids, holder, armed_at "
                "FROM dispatch_leases ORDER BY order_id"
            ).fetchall(),
        )
        return tuple(self._lease(row) for row in rows)

    @staticmethod
    def _lease(row: tuple[object, ...]) -> DispatchLease:
        """Convert one lease row; DispatchLease checks each column's type and its rules."""
        try:
            order_id, account_id, instance_ids, holder, armed_at = row
            fields: dict[str, object] = {
                "order_id": order_id,
                "account_id": account_id,
                "instance_ids": msgspec.json.decode(cast(bytes, instance_ids), type=list[str]),
                "holder": holder,
                "armed_at": armed_at,
            }
            return msgspec.convert(fields, DispatchLease)
        except (msgspec.MsgspecError, TypeError, ValueError) as error:
            raise ValueError("invalid dispatch lease row") from error

    def lease_held(self, *, account_id: str | None = None, instance_id: str | None = None) -> bool:
        """Report whether a lease covers the account, the instance, or both when both are given."""
        return any(
            (account_id is None or lease.account_id == account_id)
            and (instance_id is None or instance_id in lease.instance_ids)
            for lease in self.leases()
        )

    def arm_lease(self, lease: DispatchLease) -> None:
        """Insert a lease; an order holds at most one."""
        lease.__post_init__()
        self.tables.connection.execute(
            "INSERT INTO dispatch_leases VALUES (?, ?, ?, ?, ?)",
            (
                lease.order_id,
                lease.account_id,
                self.tables.codec.encode_json(lease.instance_ids),
                lease.holder,
                lease.armed_at.isoformat(timespec="microseconds"),
            ),
        )

    def release_lease(self, order_id: str, holder: str) -> None:
        """Delete this holder's lease on an order, if it still exists."""
        self.tables.connection.execute(
            "DELETE FROM dispatch_leases WHERE order_id=? AND holder=?", (order_id, holder)
        )


class _FirmRow:
    """Own the single reader of the ``firm`` row."""

    @staticmethod
    def payload(connection: sqlite3.Connection, configuration: bytes) -> bytes:
        """Read the head payload pinned to exact configuration bytes."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT configuration, payload FROM firm WHERE id=1").fetchone(),
        )
        if row is None or type(row[0]) is not bytes or row[0] != configuration:
            raise ValueError("account configuration or state schema differs")
        if type(row[1]) is not bytes:
            raise ValueError("firm account state is missing or malformed")
        return row[1]


class AccountStateStore:
    """Own configuration pinning and atomic reads and writes of firm state.

    The ``firm`` row holds the head; decisions, portfolio batches and paper traces
    live in their own tables. A commit writes the head and new rows, and an open
    decodes only the head.
    """

    def __init__(self, path: Path, config: AccountConfiguration, codec: DomainCodec) -> None:
        """Create or reopen the journal pinned to exact configuration bytes."""
        self.path = path
        self.config = config
        self.codec = codec
        self._configuration_payload = codec.encode_json(config)
        self._cached_snapshot: tuple[bytes, _LoadedHead] | None = None
        self._rows = StateRows(codec)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_FIRM_TABLE)
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT configuration FROM firm WHERE id=1").fetchone(),
            )
            payload = self._configuration_payload
            if row is None:
                for statement in (*_HISTORY_TABLES, _LEASE_TABLE, _ROWS_TABLE):
                    connection.execute(statement)
                initial = self._initial()
                rows, updates = self._rows.write(connection, {}, StateRows.row_values(initial))
                head = FirmHead(
                    history=replace(_EMPTY_HISTORY, rows=rows),
                    state=StateRows.strip(initial),
                    event_kinds=ORDER_EVENT_KINDS,
                )
                connection.execute(
                    "INSERT INTO firm VALUES (1, ?, ?)", (payload, self.codec.encode_json(head))
                )
                connection.commit()
                self._rows.accept(updates)
                return
            elif row[0] != payload:
                raise ValueError("account configuration or state schema differs")
            else:
                self._require_layout(connection)
                self._load(connection)
            connection.commit()

    @staticmethod
    def _require_layout(connection: sqlite3.Connection) -> None:
        """Refuse a journal whose schema is not exactly the current layout.

        Names alone are not enough: a layout that kept every table name but
        changed a column, constraint or index would otherwise open as current.
        """
        SqliteLayout.require(connection, _LAYOUT, "unsupported account journal schema")

    def read(self) -> FirmState:
        """Read one atomic firm snapshot; its history tuples are empty."""
        with closing(self._connect()) as connection:
            # The head and its rows are separate selects; one transaction keeps
            # them on one WAL snapshot while another process commits.
            connection.execute("BEGIN")
            try:
                return self._load(connection).state
            finally:
                connection.rollback()

    @contextmanager
    def snapshot(self) -> Iterator[_AccountSnapshot]:
        """Hold one read transaction so state and history lookups agree."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            try:
                head = self._load(connection)
                yield _AccountSnapshot(head.state, self._tables(connection, head.history))
            finally:
                connection.rollback()

    @staticmethod
    def verify(
        path: Path,
        config: AccountConfiguration,
        codec: DomainCodec,
        *,
        storage: Literal["wal", "snapshot"] = "wal",
    ) -> tuple[AccountView, ...]:
        """Check live WAL state or a standalone immutable SQLite backup.

        Every history row, its key columns and the head's counts, digests and
        checkpoints must agree.
        """
        config.__post_init__()
        if not path.is_file():
            raise ValueError("account journal is missing")
        if storage not in ("wal", "snapshot"):
            raise ValueError("unknown account journal storage mode")
        if storage == "snapshot":
            AccountStateStore._require_standalone_snapshot(path)
        uri = f"{path.resolve().as_uri()}?mode=ro"
        if storage == "snapshot":
            uri += "&immutable=1"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
                integrity = cast(
                    tuple[object, ...] | None,
                    connection.execute("PRAGMA integrity_check").fetchone(),
                )
                if integrity != ("ok",):
                    raise ValueError("account journal integrity check failed")
                connection.execute("BEGIN")
                AccountStateStore._require_layout(connection)
                payload = _FirmRow.payload(connection, codec.encode_json(config))
                head = codec.decode_json(payload, FirmHead)
                _HistoryTables(connection, codec, head.history).verify()
                rows = StateRows(codec)
                rows.verify(connection, head.history)
                state = StateRows.assemble(head.state, rows.load(connection, head.history))
                for account in state.accounts:
                    AccountLedger(account.ledger)
                connection.rollback()
                if storage == "snapshot":
                    AccountStateStore._require_standalone_snapshot(path)
                return state.accounts
        except sqlite3.DatabaseError as error:
            raise ValueError("account journal is not a valid SQLite database") from error

    @staticmethod
    def _require_standalone_snapshot(path: Path) -> None:
        """Refuse a snapshot whose current bytes depend on external SQLite files."""
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = path.with_name(f"{path.name}{suffix}")
            if sidecar.exists() or sidecar.is_symlink():
                raise ValueError("account snapshot has SQLite sidecars")

    @contextmanager
    def write(self) -> Iterator[AccountTransaction]:
        """Serialize read/check/write so concurrent clients cannot over-admit capacity."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                head = self._load(connection)
                tables = self._tables(connection, head.history)
                transaction = AccountTransaction(head.state, tables)
                yield transaction
                staged = transaction.state
                if staged is head.state:
                    # Nothing was staged (a guard or an idempotent request): keep the
                    # committed head instead of re-encoding and rewriting its bytes.
                    connection.commit()
                    return
                history = tables.append(staged)
                complete = replace(staged, decisions=(), portfolio_batches=(), paper_traces=())
                rows, updates = self._rows.write(
                    connection, StateRows.row_values(head.state), StateRows.row_values(complete)
                )
                written = FirmHead(
                    history=replace(history, rows=rows),
                    state=StateRows.strip(complete),
                    event_kinds=ORDER_EVENT_KINDS,
                )
                payload = self.codec.encode_json(written)
                connection.execute("UPDATE firm SET payload=? WHERE id=1", (payload,))
                connection.commit()
                self._rows.accept(updates)
                # Reuse only the immutable state whose exact bytes committed.
                # Every subsequent read still verifies the current SQLite row.
                self._cached_snapshot = payload, _LoadedHead(written.history, complete)
            except BaseException:
                connection.rollback()
                raise

    def _tables(self, connection: sqlite3.Connection, history: HistorySummary) -> _HistoryTables:
        """Bind history lookups to this connection's transaction."""
        return _HistoryTables(connection, self.codec, history)

    def _initial(self) -> FirmState:
        """Create explicit initial funding postings; require reconciliation before admission."""
        accounts: list[AccountView] = []
        for opening in self.config.accounts:
            ledger = AccountLedger(
                AccountState(
                    account_id=opening.account_id,
                    currencies=tuple(money.currency for money in opening.cash),
                )
            )
            for money in opening.cash:
                if money.value:
                    ledger.post(
                        AccountPosting(
                            identity=f"opening:{money.currency.code}",
                            account_id=opening.account_id,
                            kind="transfer",
                            event_at=self.config.opening_at,
                            known_at=self.config.opening_at,
                            cash=money,
                        )
                    )
            accounts.append(AccountView(ledger=ledger.state))
        return FirmState(accounts=tuple(accounts))

    def _connect(self) -> sqlite3.Connection:
        """Open a durable bounded SQLite connection shared by all firm clients."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _load(self, connection: sqlite3.Connection) -> _LoadedHead:
        """Read current bytes and reuse a typed state only for an identical head row."""
        payload = _FirmRow.payload(connection, self._configuration_payload)
        cached = self._cached_snapshot
        if cached is not None and payload == cached[0]:
            return cached[1]
        head = self.codec.decode_json(payload, FirmHead)
        loaded = _LoadedHead(
            head.history, StateRows.assemble(head.state, self._rows.load(connection, head.history))
        )
        self._cached_snapshot = payload, loaded
        return loaded
