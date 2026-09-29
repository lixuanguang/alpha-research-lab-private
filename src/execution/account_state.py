"""Persist the shared account state and its history under one SQLite transaction."""

from __future__ import annotations

# standard library imports
import hashlib
import operator
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

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
from execution.records import OrderEvent, OrderState, StepCommit
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class _SavedDecision(WireRecord, frozen=True):
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


class _SavedPortfolioBatch(WireRecord, frozen=True):
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


_DOCUMENT_SCHEMAS = ("account-journal-v2", "account-journal-v3")
_TABLES_SCHEMA = "account-journal-v4"
_HISTORY_FIELDS = ("decisions", "portfolio_batches", "paper_traces")
# New journals stay single-document until governance admits v4 (plan phase 3).
_NEW_JOURNAL_HISTORY: Literal["document", "tables"] = "document"


class _FirmState(WireRecord, frozen=True):
    """Hold the complete local transaction boundary.

    A v2/v3 document stores every history item in the three history tuples. Under
    v4 they hold only the items staged by the current transaction; committed items
    live in their own tables and are reached through the history lookups.
    """

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...] = ()
    quotes: tuple[AccountQuote, ...] = ()
    decisions: tuple[_SavedDecision, ...] = ()
    events: tuple[_SavedEvent, ...] = ()
    reconciliations: tuple[_Reconciliation, ...] = ()
    failed_events: tuple[OrderEvent, ...] = ()
    failed_postings: tuple[AccountPosting, ...] = ()
    portfolio_batches: tuple[_SavedPortfolioBatch, ...] = ()
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
    schema_version: Literal["account-journal-v2", "account-journal-v3", "account-journal-v4"] = (
        "account-journal-v2"
    )

    def __post_init__(self) -> None:
        """Reject future or corrupted account-journal state versions.

        v2/v3 record activation in the schema version; v4 records it only as the
        presence of ``paper_activations``.
        """
        if self.schema_version == _TABLES_SCHEMA:
            return
        if self.schema_version not in _DOCUMENT_SCHEMAS or (
            bool(self.paper_activations) != (self.schema_version == "account-journal-v3")
        ):
            raise ValueError("unsupported account journal state schema")


class _HistoryDigest(WireRecord, frozen=True):
    """Bind one history table's row count to a hash chain over its item bytes."""

    count: int
    sha256: str

    def __post_init__(self) -> None:
        """Require an empty chain for no rows and a sha256 digest otherwise."""
        if (
            type(self.count) is not int
            or self.count < 0
            or type(self.sha256) is not str
            or (self.sha256 == "") != (self.count == 0)
            or (self.count and (len(self.sha256) != 64 or self.sha256 != self.sha256.lower()))
        ):
            raise ValueError("invalid account history digest")
        bytes.fromhex(self.sha256)

    def extend(self, item: bytes) -> _HistoryDigest:
        """Chain one more item's exact bytes after the current rows."""
        digest = hashlib.sha256(bytes.fromhex(self.sha256) + item).hexdigest()
        return _HistoryDigest(count=self.count + 1, sha256=digest)


class _InstanceCheckpoint(WireRecord, frozen=True):
    """Retain an instance's latest continuation so restart needs no history scan."""

    instance_id: str
    checkpoint: bytes


class _HistorySummary(WireRecord, frozen=True):
    """Summarize the v4 history tables committed with one head."""

    decisions: _HistoryDigest
    portfolio_batches: _HistoryDigest
    paper_traces: _HistoryDigest
    checkpoints: tuple[_InstanceCheckpoint, ...]

    def __post_init__(self) -> None:
        """Require one checkpoint entry per instance."""
        if len({item.instance_id for item in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("invalid account history checkpoints")


class _FirmHead(WireRecord, frozen=True):
    """Persist the v4 live head: current state without history, plus its summary."""

    history: _HistorySummary
    state: _FirmState
    schema_version: Literal["account-journal-v4"] = "account-journal-v4"

    def __post_init__(self) -> None:
        """Keep committed history out of the head and its state on the v4 schema."""
        if (
            self.schema_version != _TABLES_SCHEMA
            or self.state.schema_version != _TABLES_SCHEMA
            or self.state.decisions
            or self.state.portfolio_batches
            or self.state.paper_traces
        ):
            raise ValueError("unsupported account journal state schema")


class _SchemaProbe(msgspec.Struct, frozen=True):
    """Read only the top-level schema version of a firm payload."""

    schema_version: str = ""


_EMPTY_HISTORY = _HistorySummary(
    decisions=_HistoryDigest(count=0, sha256=""),
    portfolio_batches=_HistoryDigest(count=0, sha256=""),
    paper_traces=_HistoryDigest(count=0, sha256=""),
    checkpoints=(),
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
    "payload BLOB NOT NULL, UNIQUE(account_id, venue, instrument_id, market_identity))",
    "CREATE INDEX paper_traces_market ON paper_traces(market_identity, seq)",
    "CREATE INDEX paper_traces_account ON paper_traces(account_id, seq)",
    "CREATE INDEX paper_traces_instrument ON paper_traces(account_id, instrument_id, seq)",
)


def _decision_key(saved: _SavedDecision) -> tuple[str, ...]:
    """Return the decisions table lookup columns."""
    return saved.request.instance_id, saved.request.decision.identity


def _batch_key(saved: _SavedPortfolioBatch) -> tuple[str, ...]:
    """Return the portfolio batches table lookup column."""
    return (saved.batch.identity,)


def _trace_key(trace: AccountPaperTrace) -> tuple[str, ...]:
    """Return the paper traces table lookup columns."""
    return (
        trace.account_id,
        trace.scenario.venue,
        str(trace.scenario.instrument_id.uuid_value),
        trace.market.identity,
    )


_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "decisions": ("instance_id", "decision_identity"),
    "portfolio_batches": ("batch_identity",),
    "paper_traces": ("account_id", "venue", "instrument_id", "market_identity"),
}


class _HistoryTables:
    """Read committed v4 history rows inside one open SQLite transaction."""

    def __init__(
        self, connection: sqlite3.Connection, codec: DomainCodec, summary: _HistorySummary
    ) -> None:
        """Bind the connection whose transaction fixes the visible rows."""
        self.connection = connection
        self.codec = codec
        self.summary = summary
        self._checkpoints: dict[str, bytes] | None = None

    def find_decision(self, instance_id: str, decision_identity: str) -> _SavedDecision | None:
        """Resolve one committed decision by its unique key."""
        payload = self._payload(
            "SELECT payload FROM decisions WHERE instance_id=? AND decision_identity=?",
            (instance_id, decision_identity),
        )
        return None if payload is None else self.codec.decode_json(payload, _SavedDecision)

    def latest_checkpoint(self, instance_id: str) -> bytes | None:
        """Read the instance's latest committed continuation from the head."""
        if self._checkpoints is None:
            self._checkpoints = {
                item.instance_id: item.checkpoint for item in self.summary.checkpoints
            }
        return self._checkpoints.get(instance_id)

    def find_batch(self, identity: str) -> _SavedPortfolioBatch | None:
        """Resolve one committed portfolio batch by its unique identity."""
        payload = self._payload(
            "SELECT payload FROM portfolio_batches WHERE batch_identity=?", (identity,)
        )
        return None if payload is None else self.codec.decode_json(payload, _SavedPortfolioBatch)

    def find_trace(
        self,
        market_identity: str,
        *,
        account_id: str | None,
        venue: str | None,
        instrument_id: InstrumentId | None,
    ) -> AccountPaperTrace | None:
        """Return the earliest committed trace of a market identity within the given keys."""
        clauses, parameters = self._trace_filter(account_id, venue, instrument_id)
        payload = self._payload(
            "SELECT payload FROM paper_traces WHERE market_identity=?"
            + "".join(f" AND {clause}" for clause in clauses)
            + " ORDER BY seq LIMIT 1",
            (market_identity, *parameters),
        )
        return None if payload is None else self.codec.decode_json(payload, AccountPaperTrace)

    def iter_traces(
        self, account_id: str | None, instrument_id: InstrumentId | None, *, newest_first: bool
    ) -> Iterator[AccountPaperTrace]:
        """Yield committed traces in commit order, or reversed."""
        clauses, parameters = self._trace_filter(account_id, None, instrument_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "DESC" if newest_first else "ASC"
        cursor = self.connection.execute(
            f"SELECT payload FROM paper_traces{where} ORDER BY seq {order}", parameters
        )
        for row in cast(Iterator[tuple[object, ...]], cursor):
            yield self.codec.decode_json(self._blob(row[0]), AccountPaperTrace)

    def append(self, state: _FirmState) -> _HistorySummary:
        """Insert the state's staged history items and return the extended summary."""
        decisions = self._insert(
            "decisions", self.summary.decisions, state.decisions, _decision_key
        )
        batches = self._insert(
            "portfolio_batches", self.summary.portfolio_batches, state.portfolio_batches, _batch_key
        )
        traces = self._insert(
            "paper_traces", self.summary.paper_traces, state.paper_traces, _trace_key
        )
        checkpoints = {item.instance_id: item.checkpoint for item in self.summary.checkpoints}
        for saved in state.decisions:
            checkpoints[saved.request.instance_id] = saved.request.checkpoint
        return _HistorySummary(
            decisions=decisions,
            portfolio_batches=batches,
            paper_traces=traces,
            checkpoints=tuple(
                _InstanceCheckpoint(instance_id=instance_id, checkpoint=checkpoint)
                for instance_id, checkpoint in checkpoints.items()
            ),
        )

    def verify(self) -> None:
        """Check every row, its key columns and the head's counts, digests and checkpoints."""
        decisions = self._verify_table("decisions", _SavedDecision, _decision_key)
        self._verify_table("portfolio_batches", _SavedPortfolioBatch, _batch_key)
        self._verify_table("paper_traces", AccountPaperTrace, _trace_key)
        checkpoints: dict[str, bytes] = {}
        for saved in decisions:
            checkpoints[saved.request.instance_id] = saved.request.checkpoint
        expected = tuple(
            _InstanceCheckpoint(instance_id=instance_id, checkpoint=checkpoint)
            for instance_id, checkpoint in checkpoints.items()
        )
        if expected != self.summary.checkpoints:
            raise ValueError("account journal history differs from its head")

    def rows(self, table: str) -> list[bytes]:
        """Return one table's exact item bytes in commit order."""
        cursor = self.connection.execute(f"SELECT payload FROM {table} ORDER BY seq")
        return [self._blob(row[0]) for row in cast(Iterator[tuple[object, ...]], cursor)]

    def _insert[T](
        self,
        table: str,
        digest: _HistoryDigest,
        items: tuple[T, ...],
        key: Callable[[T], tuple[str, ...]],
    ) -> _HistoryDigest:
        """Append staged items after the committed rows, extending the table's chain."""
        columns = _TABLE_COLUMNS[table]
        statement = (
            f"INSERT INTO {table} (seq, {', '.join(columns)}, payload) "
            f"VALUES ({', '.join('?' * (len(columns) + 2))})"
        )
        for item in items:
            payload = self.codec.encode_json(item)
            self.connection.execute(statement, (digest.count, *key(item), payload))
            digest = digest.extend(payload)
        return digest

    def _verify_table[T](
        self, table: str, target: type[T], key: Callable[[T], tuple[str, ...]]
    ) -> list[T]:
        """Decode one table in order and compare it with the head's digest."""
        columns = _TABLE_COLUMNS[table]
        cursor = self.connection.execute(
            f"SELECT seq, {', '.join(columns)}, payload FROM {table} ORDER BY seq"
        )
        digest = _HistoryDigest(count=0, sha256="")
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
    def _trace_filter(
        account_id: str | None, venue: str | None, instrument_id: InstrumentId | None
    ) -> tuple[list[str], list[str]]:
        """Build equality clauses for the supplied trace keys."""
        clauses: list[str] = []
        parameters: list[str] = []
        for column, value in (
            ("account_id", account_id),
            ("venue", venue),
            ("instrument_id", None if instrument_id is None else str(instrument_id.uuid_value)),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                parameters.append(value)
        return clauses, parameters

    def _payload(self, statement: str, parameters: tuple[str, ...]) -> bytes | None:
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


class _AccountSnapshot:
    """Answer history lookups by identity without exposing collection storage.

    Committed v4 rows precede the items staged in ``state``; a v2/v3 document has
    no tables and keeps all history in ``state``.
    """

    def __init__(self, state: _FirmState, tables: _HistoryTables | None = None) -> None:
        """Retain one immutable state value and its committed history, if separate."""
        self.state = state
        self._tables = tables

    def find_decision(self, instance_id: str, decision_identity: str) -> _SavedDecision | None:
        """Resolve one saved decision by instance and decision identity."""
        if self._tables is not None:
            committed = self._tables.find_decision(instance_id, decision_identity)
            if committed is not None:
                return committed
        for saved in self.state.decisions:
            if (saved.request.instance_id, saved.request.decision.identity) == (
                instance_id,
                decision_identity,
            ):
                return saved
        return None

    def latest_checkpoint(self, instance_id: str) -> bytes | None:
        """Return the continuation of the instance's latest admitted or rejected decision."""
        for saved in reversed(self.state.decisions):
            if saved.request.instance_id == instance_id:
                return saved.request.checkpoint
        return None if self._tables is None else self._tables.latest_checkpoint(instance_id)

    def find_batch(self, identity: str) -> _SavedPortfolioBatch | None:
        """Resolve one saved portfolio batch by its stable identity."""
        if self._tables is not None:
            committed = self._tables.find_batch(identity)
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
        if self._tables is not None:
            committed = self._tables.find_trace(
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
        committed: Iterator[AccountPaperTrace] = (
            iter(())
            if self._tables is None
            else self._tables.iter_traces(account_id, instrument_id, newest_first=newest_first)
        )
        if newest_first:
            yield from staged
            yield from committed
        else:
            yield from committed
            yield from staged


class _AccountTransaction(_AccountSnapshot):
    """Own the staged state of a single serialized firm transaction."""

    def append_decisions(self, *saved: _SavedDecision) -> None:
        """Append saved decisions after all existing history."""
        decisions: tuple[_SavedDecision, ...] = (*self.state.decisions, *saved)
        self.state = replace(self.state, decisions=decisions)

    def append_batch(self, saved: _SavedPortfolioBatch) -> None:
        """Append one saved portfolio batch after all existing history."""
        batches: tuple[_SavedPortfolioBatch, ...] = (*self.state.portfolio_batches, saved)
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

    def order(self, order_id: str) -> TaggedOrder:
        """Resolve exact persisted order identity."""
        for tagged in self.state.orders:
            if tagged.order.identity == order_id:
                return tagged
        raise ValueError("unknown child order")

    def save_order(self, tagged: TaggedOrder) -> None:
        """Replace an existing tagged order preserving stable sequence."""
        orders: tuple[TaggedOrder, ...] = tuple(
            tagged if item.order.identity == tagged.order.identity else item
            for item in self.state.orders
        )
        self.state = replace(self.state, orders=orders)

    def net_order(self, order_id: str) -> NetOrder:
        """Resolve a physical order without confusing it with child ownership."""
        for parent in self.state.net_orders:
            if parent.order.identity == order_id:
                return parent
        raise ValueError("unknown physical order")

    def save_net_order(self, parent: NetOrder) -> None:
        """Replace one physical lifecycle and allocation snapshot in place."""
        net_orders: tuple[NetOrder, ...] = tuple(
            parent if item.order.identity == parent.order.identity else item
            for item in self.state.net_orders
        )
        self.state = replace(self.state, net_orders=net_orders)


def _field_keys(record: type[msgspec.Struct]) -> tuple[tuple[str, bytes], ...]:
    """Return each field's name and encoded key prefix in the codec's sorted order."""
    return tuple(
        (name, msgspec.json.encode(wire_name) + b":")
        for wire_name, name in sorted(
            (field.encode_name, field.name) for field in msgspec.structs.fields(record)
        )
    )


# The codec encodes struct fields in sorted wire-name order with no omitted defaults.
_FIRM_FIELD_KEYS = _field_keys(_FirmState)
_HEAD_FIELD_KEYS = _field_keys(_FirmHead)


class _FirmRow:
    """Own the single reader of the ``firm`` row and the decoding of its payload."""

    @staticmethod
    def payload(connection: sqlite3.Connection, configuration: bytes) -> bytes:
        """Read the payload pinned to exact configuration bytes."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT configuration, payload FROM firm WHERE id=1").fetchone(),
        )
        if row is None or type(row[0]) is not bytes or row[0] != configuration:
            raise ValueError("account configuration or state schema differs")
        if type(row[1]) is not bytes:
            raise ValueError("firm account state is missing or malformed")
        return row[1]

    @staticmethod
    def is_head(payload: bytes) -> bool:
        """Tell a v4 head from a v2/v3 document by its declared schema version."""
        probe = msgspec.json.decode(payload, type=_SchemaProbe)
        return probe.schema_version == _TABLES_SCHEMA

    @staticmethod
    def decode(
        codec: DomainCodec, payload: bytes, *, head: bool
    ) -> tuple[_FirmState, _FirmHead | None]:
        """Decode a document or a head, never accepting one format as the other."""
        if head:
            decoded = codec.decode_json(payload, _FirmHead)
            return decoded.state, decoded
        state = codec.decode_json(payload, _FirmState)
        if state.schema_version not in _DOCUMENT_SCHEMAS:
            raise ValueError("unsupported account journal state schema")
        return state, None


class AccountStateStore:
    """Own configuration pinning and atomic reads and writes of firm state.

    A v2/v3 journal stores the whole state as one ``firm`` document. A v4 journal
    stores a head in ``firm`` and decisions, portfolio batches and paper traces in
    their own tables, so a commit writes the head and new rows and an open decodes
    only the head. The journal's own payload decides its format; ``history``
    chooses the format only when this store creates the journal, defaulting to
    ``_NEW_JOURNAL_HISTORY``.
    """

    def __init__(
        self,
        path: Path,
        config: AccountConfiguration,
        codec: DomainCodec,
        *,
        history: Literal["document", "tables"] | None = None,
    ) -> None:
        """Create or reopen the state document pinned to exact configuration bytes."""
        history = _NEW_JOURNAL_HISTORY if history is None else history
        if history not in ("document", "tables"):
            raise ValueError("unknown account journal history storage")
        self.path = path
        self.config = config
        self.codec = codec
        self._configuration_payload = codec.encode_json(config)
        self._cached_snapshot: tuple[bytes, _FirmState, _FirmHead | None] | None = None
        self._encoded: dict[str, tuple[object, bytes, list[bytes] | None]] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS firm (id INTEGER PRIMARY KEY CHECK(id=1), "
                "configuration BLOB NOT NULL, payload BLOB NOT NULL)"
            )
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT configuration FROM firm WHERE id=1").fetchone(),
            )
            payload = self._configuration_payload
            if row is None:
                self._separate_history = history == "tables"
                initial = self._initial()
                if self._separate_history:
                    for statement in _HISTORY_TABLES:
                        connection.execute(statement)
                    state = replace(initial, schema_version=_TABLES_SCHEMA)
                    content = self._encode_head(_FirmHead(history=_EMPTY_HISTORY, state=state))
                else:
                    content = self.codec.encode_json(initial)
                connection.execute("INSERT INTO firm VALUES (1, ?, ?)", (payload, content))
            elif row[0] != payload:
                raise ValueError("account configuration or state schema differs")
            else:
                self._separate_history = _FirmRow.is_head(_FirmRow.payload(connection, payload))
                self._load(connection)
            connection.commit()

    def read(self) -> _FirmState:
        """Read one atomic firm snapshot; under v4 its history tuples are empty."""
        with closing(self._connect()) as connection:
            return self._load(connection)[0]

    @contextmanager
    def snapshot(self) -> Iterator[_AccountSnapshot]:
        """Hold one read transaction so state and history lookups agree."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            try:
                state, head = self._load(connection)
                yield _AccountSnapshot(state, self._tables(connection, head))
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

        A v4 journal also checks every history row against the head's counts,
        digests and checkpoints.
        """
        with AccountStateStore._read_only(path, config, storage=storage) as connection:
            payload = _FirmRow.payload(connection, codec.encode_json(config))
            state, head = _FirmRow.decode(codec, payload, head=_FirmRow.is_head(payload))
            if head is not None:
                _HistoryTables(connection, codec, head.history).verify()
            return state.accounts

    @staticmethod
    def materialize(
        path: Path,
        config: AccountConfiguration,
        codec: DomainCodec,
        *,
        storage: Literal["wal", "snapshot"] = "wal",
    ) -> bytes:
        """Return the complete single-document state bytes of a journal.

        A v2/v3 journal returns its stored document. A v4 journal returns the
        document a v3 journal would hold, except that ``schema_version`` stays v4.
        """
        with AccountStateStore._read_only(path, config, storage=storage) as connection:
            payload = _FirmRow.payload(connection, codec.encode_json(config))
            state, head = _FirmRow.decode(codec, payload, head=_FirmRow.is_head(payload))
            if head is None:
                return payload
            tables = _HistoryTables(connection, codec, head.history)
            fields: list[bytes] = []
            for name, key in _FIRM_FIELD_KEYS:
                if name in _HISTORY_FIELDS:
                    fields.append(key + b"[" + b",".join(tables.rows(name)) + b"]")
                else:
                    value: object = getattr(state, name)
                    fields.append(key + codec.encode_json(value))
            return b"{" + b",".join(fields) + b"}"

    @staticmethod
    @contextmanager
    def _read_only(
        path: Path, config: AccountConfiguration, *, storage: Literal["wal", "snapshot"]
    ) -> Iterator[sqlite3.Connection]:
        """Open an integrity-checked read transaction on a live journal or a snapshot."""
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
                yield connection
                connection.rollback()
                if storage == "snapshot":
                    AccountStateStore._require_standalone_snapshot(path)
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
    def write(self) -> Iterator[_AccountTransaction]:
        """Serialize read/check/write so concurrent clients cannot over-admit capacity."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                state, head = self._load(connection)
                tables = self._tables(connection, head)
                transaction = _AccountTransaction(state, tables)
                yield transaction
                staged = transaction.state
                _FirmState.__post_init__(staged)
                if (staged.schema_version == _TABLES_SCHEMA) != self._separate_history:
                    raise ValueError("unsupported account journal state schema")
                committed: tuple[_FirmState, _FirmHead | None]
                if tables is None:
                    payload = self._encode(staged)
                    committed = staged, None
                else:
                    written = _FirmHead(
                        history=tables.append(staged),
                        state=replace(staged, decisions=(), portfolio_batches=(), paper_traces=()),
                    )
                    payload = self._encode_head(written)
                    committed = written.state, written
                connection.execute("UPDATE firm SET payload=? WHERE id=1", (payload,))
                connection.commit()
                # Reuse only the immutable state whose exact bytes committed.
                # Every subsequent read still verifies the current SQLite row.
                self._cached_snapshot = payload, *committed
            except BaseException:
                connection.rollback()
                raise

    def _tables(
        self, connection: sqlite3.Connection, head: _FirmHead | None
    ) -> _HistoryTables | None:
        """Bind v4 history lookups to this connection's transaction."""
        return None if head is None else _HistoryTables(connection, self.codec, head.history)

    def _encode_head(self, head: _FirmHead) -> bytes:
        """Return exactly ``codec.encode_json(head)``, reusing the state's field cache."""
        fields: list[bytes] = []
        for name, key in _HEAD_FIELD_KEYS:
            value: object = getattr(head, name)
            encoded = self._encode(head.state) if name == "state" else self.codec.encode_json(value)
            fields.append(key + encoded)
        return b"{" + b",".join(fields) + b"}"

    def _encode(self, state: _FirmState) -> bytes:
        """Return exactly ``codec.encode_json(state)`` without re-encoding unchanged history.

        The codec writes every field in sorted-name order. Each cache entry maps an
        immutable value to its bytes, so reuse requires object identity: an
        unchanged field, or a tuple whose previous items are the same objects with
        only new items appended. Anything else is encoded afresh. An entry left by a
        rolled-back or superseded state can only miss, never return other bytes.
        """
        fields: list[bytes] = []
        for name, key in _FIRM_FIELD_KEYS:
            value: object = getattr(state, name)
            cached = self._encoded.get(name)
            if cached is not None and cached[0] is value:
                fields.append(key + cached[1])
                continue
            items: list[bytes] | None = None
            if type(value) is tuple:
                previous = cached[0] if cached is not None else None
                if (
                    cached is not None
                    and cached[2] is not None
                    and type(previous) is tuple
                    and len(value) >= len(previous)
                    and all(map(operator.is_, value, previous))
                ):
                    items = cached[2] + [
                        self.codec.encode_json(item) for item in value[len(previous) :]
                    ]
                else:
                    items = [self.codec.encode_json(item) for item in value]
                encoded = b"[" + b",".join(items) + b"]"
            else:
                encoded = self.codec.encode_json(value)
            self._encoded[name] = value, encoded, items
            fields.append(key + encoded)
        return b"{" + b",".join(fields) + b"}"

    def _initial(self) -> _FirmState:
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
        return _FirmState(accounts=tuple(accounts))

    def _connect(self) -> sqlite3.Connection:
        """Open a durable bounded SQLite connection shared by all firm clients."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _load(self, connection: sqlite3.Connection) -> tuple[_FirmState, _FirmHead | None]:
        """Read current bytes and reuse a typed decode only for an identical row."""
        payload = _FirmRow.payload(connection, self._configuration_payload)
        cached = self._cached_snapshot
        if cached is not None and payload == cached[0]:
            return cached[1], cached[2]
        state, head = _FirmRow.decode(self.codec, payload, head=self._separate_history)
        self._cached_snapshot = payload, state, head
        return state, head
