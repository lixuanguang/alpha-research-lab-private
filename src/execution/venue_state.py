"""Retain one fenced venue owner's send intents, receipts and recovery state."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

# third party library imports
from msgspec.structs import replace

# project library imports
from serialization import DomainCodec, SqliteLayout, WireRecord


class VenueDispatch(WireRecord, frozen=True):
    """Bind an economic order to its immutable identity before a possible send."""

    order_id: str
    client_id: str
    symbol: str
    submitted_at: datetime
    request: bytes
    venue_order_id: str | None = None
    cancel_attempted: bool = False
    cancel_attempts: int = 0
    # The venue refused the submit, or the gateway refused it before any byte was sent.
    submission_rejected: bool = False
    # When a request that found the order open was sent: the order closed after this,
    # so venue retention of closed orders is measured from here, not from submission.
    open_seen_at: datetime | None = None


class VenueReceipt(WireRecord, frozen=True):
    """Retain protocol bytes before applying their idempotent economic effects."""

    identity: str
    kind: str
    received_at: datetime
    payload: bytes
    applied: bool = False


class VenueState(WireRecord, frozen=True):
    """Persist the transport's scalar recovery state beside its dispatch and receipt rows.

    ``fills_complete_through`` is the end of the last fill-history window whose
    reconciliation matched the physical account. Every execution the venue had
    published by then with an earlier source time has been applied. An absent
    mark keeps the full opening window.
    """

    schema_version: str = "venue-journal"
    nonce: int = 0
    last_request_at: datetime | None = None
    recovery_required: bool = True
    reason: str = "initial_reconciliation_required"
    reconciled_at: datetime | None = None
    fills_complete_through: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse incompatible state rather than guessing a recovery migration."""
        if self.schema_version != "venue-journal":
            raise ValueError("unsupported venue journal schema")
        if self.nonce < 0:
            raise ValueError("unsupported venue journal state")
        if self.fills_complete_through is not None:
            self._require_utc(self.fills_complete_through, field_name="venue fill mark")


# Dispatches and receipts are rows, so a frame or a flag costs one row, not a rewrite
# of the whole history. Opening refuses any other layout, including an earlier one.
_LAYOUT: tuple[str, ...] = (
    "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), binding BLOB NOT NULL, "
    "payload BLOB NOT NULL)",
    "CREATE TABLE dispatches (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "order_id TEXT NOT NULL UNIQUE, client_id TEXT NOT NULL UNIQUE, payload BLOB NOT NULL)",
    "CREATE TABLE receipts (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "identity TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, applied INTEGER NOT NULL, "
    "payload BLOB NOT NULL)",
    "CREATE INDEX receipts_kind ON receipts(kind, sequence)",
)


class VenueStateStore:
    """Serialize bounded network operations under a process-lifetime kernel fence.

    An owner holds the nonblocking OS lock throughout its request and subsequent
    journal update. A stalled owner cannot be replaced while its socket can still
    send. SQLite commits send intent before transport; a crash never authorizes
    resubmission. The lock belongs beside the account journal, so callers cannot
    select another transport-state path to bypass it.
    """

    def __init__(self, account_path: Path, account_id: str, binding: bytes) -> None:
        """Bind state to the exact account location and configured venue scope."""
        namespace = hashlib.sha256(account_id.encode()).hexdigest()[:16]
        self.path = account_path.with_suffix(f".{namespace}.venue.sqlite3")
        self.lock_path = account_path.with_suffix(".venue.lock")
        self.accounts_path = account_path.with_suffix(".venue-accounts.sqlite3")
        self.account_id = account_id
        self._binding = binding
        self._codec = DomainCodec()
        self._claimed = False

    @contextmanager
    def claim(self) -> Iterator[VenueStateStore]:
        """Acquire exclusive transport ownership or fail without network effects."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("venue execution owner is already active") from None
            try:
                self._claimed = True
                self._initialize()
                yield self
            finally:
                self._claimed = False
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self) -> VenueState:
        """Read validated scalar state only while the external-send fence is held."""
        row = self._one("SELECT payload FROM state WHERE id=1")
        payload = None if row is None else row[0]
        if not isinstance(payload, bytes):
            raise ValueError("venue journal state is missing")
        result = self._codec.decode_json(payload, VenueState)
        result.__post_init__()
        return result

    def save(self, state: VenueState) -> None:
        """Commit scalar state durably before allowing the next protocol side effect."""
        state.__post_init__()
        self._execute("UPDATE state SET payload=? WHERE id=1", (self._codec.encode_json(state),))

    def dispatches(self) -> tuple[VenueDispatch, ...]:
        """Read every dispatch in the order its intent was committed."""
        return tuple(
            self._dispatch_row(row)
            for row in self._all("SELECT payload FROM dispatches ORDER BY sequence")
        )

    def dispatch(
        self, *, order_id: str | None = None, client_id: str | None = None
    ) -> VenueDispatch | None:
        """Find one dispatch by its order or its client identity."""
        if (order_id is None) == (client_id is None):
            raise ValueError("venue dispatch lookup requires one identity")
        row = (
            self._one("SELECT payload FROM dispatches WHERE order_id=?", (order_id,))
            if order_id is not None
            else self._one("SELECT payload FROM dispatches WHERE client_id=?", (client_id,))
        )
        return None if row is None else self._dispatch_row(row)

    def add_dispatch(self, dispatch: VenueDispatch, *, state: VenueState) -> None:
        """Commit a new send intent with its scalar state in one transaction.

        A dispatch's order and client identities are never reused.
        """
        state.__post_init__()
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            try:
                connection.execute(
                    "INSERT INTO dispatches(order_id, client_id, payload) VALUES (?, ?, ?)",
                    (dispatch.order_id, dispatch.client_id, self._codec.encode_json(dispatch)),
                )
            except sqlite3.IntegrityError:
                raise ValueError("duplicate venue dispatch or client identity") from None
            connection.execute(
                "UPDATE state SET payload=? WHERE id=1", (self._codec.encode_json(state),)
            )

    def update_dispatch(self, dispatch: VenueDispatch, *, state: VenueState | None = None) -> None:
        """Replace one dispatch's mutable facts, and optionally scalar state, atomically.

        The dispatch's identities stay as committed.
        """
        if state is not None:
            state.__post_init__()
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            changed = connection.execute(
                "UPDATE dispatches SET payload=? WHERE order_id=? AND client_id=?",
                (self._codec.encode_json(dispatch), dispatch.order_id, dispatch.client_id),
            ).rowcount
            if changed != 1:
                raise ValueError("unowned or never-submitted venue order")
            if state is not None:
                connection.execute(
                    "UPDATE state SET payload=? WHERE id=1", (self._codec.encode_json(state),)
                )

    def receipt(self, kind: str, payload: bytes, at: datetime) -> VenueReceipt:
        """Append exact receipt bytes or return the original immutable retry."""
        identity = hashlib.sha256(kind.encode() + b"\0" + payload).hexdigest()
        prior = self._one("SELECT applied, payload FROM receipts WHERE identity=?", (identity,))
        if prior is not None:
            return self._receipt_row(prior)
        receipt = VenueReceipt(identity=identity, kind=kind, received_at=at, payload=payload)
        self._execute(
            "INSERT INTO receipts(identity, kind, applied, payload) VALUES (?, ?, 0, ?)",
            (identity, kind, self._codec.encode_json(receipt)),
        )
        return receipt

    def find_receipt(self, kind: str) -> VenueReceipt | None:
        """Return the first retained receipt of exactly this kind, if any."""
        row = self._one(
            "SELECT applied, payload FROM receipts WHERE kind=? ORDER BY sequence LIMIT 1",
            (kind,),
        )
        return None if row is None else self._receipt_row(row)

    def unapplied(self, prefix: str) -> tuple[VenueReceipt, ...]:
        """Return receipts whose kind starts with ``prefix`` and whose effects are pending."""
        if not prefix or prefix[-1] == "\U0010ffff":
            raise ValueError("venue receipt prefix must be bounded")
        # A kind range over the index: every kind starting with the prefix sorts below
        # the prefix with its last character incremented.
        end = prefix[:-1] + chr(ord(prefix[-1]) + 1)
        return tuple(
            self._receipt_row(row)
            for row in self._all(
                "SELECT applied, payload FROM receipts WHERE kind >= ? AND kind < ? "
                "AND applied = 0 ORDER BY sequence",
                (prefix, end),
            )
        )

    def receipt_count(self) -> int:
        """Count every retained receipt."""
        row = self._one("SELECT COUNT(*) FROM receipts")
        if row is None or type(row[0]) is not int:
            raise ValueError("venue journal receipts are malformed")
        return row[0]

    def applied(self, identity: str) -> None:
        """Mark a retained receipt only after its ledger effects have committed."""
        if self._execute("UPDATE receipts SET applied=1 WHERE identity=?", (identity,)) != 1:
            raise ValueError("unknown venue receipt")

    def bind_account(self, venue: str, environment: str, native_identity: str) -> None:
        """Prevent one physical wallet from funding two local account aliases."""
        self._require_claim()
        if not native_identity:
            raise ValueError("verified physical venue identity is required")
        with closing(sqlite3.connect(self.accounts_path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS bindings ("
                "account_id TEXT PRIMARY KEY, venue TEXT NOT NULL, environment TEXT NOT NULL, "
                "native_identity TEXT NOT NULL, UNIQUE(venue, environment, native_identity))"
            )
            expected = (self.account_id, venue, environment, native_identity)
            prior = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT account_id,venue,environment,native_identity "
                    "FROM bindings WHERE account_id=?",
                    (self.account_id,),
                ).fetchone(),
            )
            if prior is not None:
                if prior != expected:
                    raise ValueError("local account physical venue binding changed")
                return
            try:
                connection.execute("INSERT INTO bindings VALUES (?,?,?,?)", expected)
            except sqlite3.IntegrityError:
                raise ValueError(
                    "physical venue account already belongs to another local account"
                ) from None

    def _initialize(self) -> None:
        """Create the layout, or require it and the configuration binding, under the fence."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            existing = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone(),
            )
            if existing is None:
                for statement in _LAYOUT:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO state VALUES (1, ?, ?)",
                    (self._binding, self._codec.encode_json(VenueState())),
                )
                return
            SqliteLayout.require(connection, _LAYOUT, "unsupported venue journal schema")
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT binding FROM state WHERE id=1").fetchone(),
            )
            if row is None or row[0] != self._binding:
                raise ValueError("venue journal configuration or account binding differs")

    def _dispatch_row(self, row: tuple[object, ...]) -> VenueDispatch:
        """Decode one stored dispatch."""
        if type(row[0]) is not bytes:
            raise ValueError("venue journal dispatch is malformed")
        return self._codec.decode_json(row[0], VenueDispatch)

    def _receipt_row(self, row: tuple[object, ...]) -> VenueReceipt:
        """Decode one stored receipt with its applied flag."""
        applied, payload = row
        if applied not in (0, 1) or type(payload) is not bytes:
            raise ValueError("venue journal receipt is malformed")
        receipt = self._codec.decode_json(payload, VenueReceipt)
        return replace(receipt, applied=applied == 1)

    def _one(self, query: str, parameters: tuple[object, ...] = ()) -> tuple[object, ...] | None:
        """Read one row while holding the fence."""
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection:
            return cast(tuple[object, ...] | None, connection.execute(query, parameters).fetchone())

    def _all(self, query: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        """Read rows while holding the fence."""
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection:
            return cast(list[tuple[object, ...]], connection.execute(query, parameters).fetchall())

    def _execute(self, statement: str, parameters: tuple[object, ...]) -> int:
        """Commit one durable change while holding the fence; return the changed rows."""
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            return connection.execute(statement, parameters).rowcount

    def _require_claim(self) -> None:
        """Reject accidental access outside the single execution-owner lifetime."""
        if not self._claimed:
            raise ValueError("venue journal requires the execution-owner fence")
