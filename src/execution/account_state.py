"""Persist the complete shared account state under one SQLite transaction."""

from __future__ import annotations

# standard library imports
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountState
from configuration import AccountConfiguration
from execution.account_records import (
    AccountControlResult,
    AccountDecision,
    AccountObservation,
    AccountQuote,
    AccountView,
    NetFeeAllocation,
    NetFeeCorrection,
    NetOrder,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.records import OrderEvent, OrderState, StepCommit
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


class _FirmState(WireRecord, frozen=True):
    """Persist the complete local transaction boundary in one SQLite document."""

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
    schema_version: Literal["account-journal-v2"] = "account-journal-v2"

    def __post_init__(self) -> None:
        """Reject future or corrupted account-journal state versions."""
        if self.schema_version != "account-journal-v2":
            raise ValueError("unsupported account journal state schema")


class _AccountTransaction:
    """Own the staged state of a single serialized firm transaction."""

    def __init__(self, state: _FirmState) -> None:
        """Retain only this transaction's immutable state value."""
        self.state = state

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


class AccountStateStore:
    """Own configuration pinning and atomic reads and writes of firm state."""

    def __init__(self, path: Path, config: AccountConfiguration, codec: DomainCodec) -> None:
        """Create or reopen the state document pinned to exact configuration bytes."""
        self.path = path
        self.config = config
        self.codec = codec
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
            payload = self.codec.encode_json(config)
            if row is None:
                connection.execute(
                    "INSERT INTO firm VALUES (1, ?, ?)",
                    (payload, self.codec.encode_json(self._initial())),
                )
            elif row[0] != payload:
                raise ValueError("account configuration or state schema differs")
            else:
                self._load(connection)
            connection.commit()

    def read(self) -> _FirmState:
        """Read one atomic firm snapshot."""
        with closing(self._connect()) as connection:
            return self._load(connection)

    @staticmethod
    def verify(
        path: Path,
        config: AccountConfiguration,
        codec: DomainCodec,
        *,
        storage: Literal["wal", "snapshot"] = "wal",
    ) -> tuple[AccountView, ...]:
        """Check live WAL state or a standalone immutable SQLite backup."""
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
                row = cast(
                    tuple[object, ...] | None,
                    connection.execute(
                        "SELECT configuration, payload FROM firm WHERE id=1"
                    ).fetchone(),
                )
                if row is None or row[0] != codec.encode_json(config) or type(row[1]) is not bytes:
                    raise ValueError("account configuration or state schema differs")
                state = codec.decode_json(row[1], _FirmState)
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
    def write(self) -> Iterator[_AccountTransaction]:
        """Serialize read/check/write so concurrent clients cannot over-admit capacity."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                transaction = _AccountTransaction(self._load(connection))
                yield transaction
                connection.execute(
                    "UPDATE firm SET payload=? WHERE id=1",
                    (self.codec.encode_json(transaction.state),),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

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

    def _load(self, connection: sqlite3.Connection) -> _FirmState:
        """Decode complete typed firm state and reject malformed storage."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
        )
        if row is None or type(row[0]) is not bytes:
            raise ValueError("firm account state is missing or malformed")
        return self.codec.decode_json(row[0], _FirmState)
