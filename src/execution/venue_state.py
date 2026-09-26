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
from serialization import DomainCodec, WireRecord


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
    submission_rejected: bool = False


class VenueReceipt(WireRecord, frozen=True):
    """Retain protocol bytes before applying their idempotent economic effects."""

    identity: str
    kind: str
    received_at: datetime
    payload: bytes
    applied: bool = False


class VenueState(WireRecord, frozen=True):
    """Persist transport history independently of the authoritative account ledger."""

    schema_version: str = "venue-journal-v1"
    nonce: int = 0
    last_request_at: datetime | None = None
    dispatches: tuple[VenueDispatch, ...] = ()
    receipts: tuple[VenueReceipt, ...] = ()
    recovery_required: bool = True
    reason: str = "initial_reconciliation_required"
    reconciled_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse incompatible state rather than guessing a recovery migration."""
        if self.schema_version != "venue-journal-v1" or self.nonce < 0:
            raise ValueError("unsupported venue journal state")
        if len({item.client_id for item in self.dispatches}) != len(self.dispatches):
            raise ValueError("venue client identities collide")
        if len({item.order_id for item in self.dispatches}) != len(self.dispatches):
            raise ValueError("duplicate venue dispatch identity")


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
        """Read validated current state only while the external-send fence is held."""
        self._require_claim()
        with closing(sqlite3.connect(self.path)) as connection:
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT payload FROM state WHERE id=1").fetchone(),
            )
        payload = None if row is None else row[0]
        if not isinstance(payload, bytes):
            raise ValueError("venue journal state is missing")
        result = self._codec.decode_json(payload, VenueState)
        result.__post_init__()
        return result

    def save(self, state: VenueState) -> None:
        """Commit state durably before allowing the next protocol side effect."""
        self._require_claim()
        state.__post_init__()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "UPDATE state SET payload=? WHERE id=1", (self._codec.encode_json(state),)
            )

    def receipt(self, kind: str, payload: bytes, at: datetime) -> VenueReceipt:
        """Append exact receipt bytes or return the original immutable retry."""
        state = self.read()
        identity = hashlib.sha256(kind.encode() + b"\0" + payload).hexdigest()
        for receipt in state.receipts:
            if receipt.identity == identity:
                return receipt
        receipt = VenueReceipt(identity=identity, kind=kind, received_at=at, payload=payload)
        receipts: tuple[VenueReceipt, ...] = (*state.receipts, receipt)
        self.save(replace(state, receipts=receipts))
        return receipt

    def applied(self, identity: str) -> None:
        """Mark a retained receipt only after its ledger effects have committed."""
        state = self.read()
        if identity not in {receipt.identity for receipt in state.receipts}:
            raise ValueError("unknown venue receipt")
        receipts: tuple[VenueReceipt, ...] = tuple(
            replace(receipt, applied=True) if receipt.identity == identity else receipt
            for receipt in state.receipts
        )
        self.save(replace(state, receipts=receipts))

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
        """Create or verify the configuration binding while holding the OS fence."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), binding BLOB NOT NULL, payload BLOB NOT NULL)"
            )
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT binding FROM state WHERE id=1").fetchone(),
            )
            if row is None:
                connection.execute(
                    "INSERT INTO state VALUES (1, ?, ?)",
                    (self._binding, self._codec.encode_json(VenueState())),
                )
            elif row[0] != self._binding:
                raise ValueError("venue journal configuration or account binding differs")

    def _require_claim(self) -> None:
        """Reject accidental access outside the single execution-owner lifetime."""
        if not self._claimed:
            raise ValueError("venue journal requires the execution-owner fence")
