"""Persist the complete shared account state under one SQLite transaction."""

from __future__ import annotations

# standard library imports
import operator
import sqlite3
from collections.abc import Iterator
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
    native_fills: tuple[_SavedNativeFill, ...] = ()
    failed_native_fills: tuple[NativeFill, ...] = ()
    physical_reconciliations: tuple[_PhysicalReconciliation, ...] = ()
    paper_bindings: tuple[AccountPaperBinding, ...] = ()
    paper_traces: tuple[AccountPaperTrace, ...] = ()
    paper_activations: tuple[PaperActivation, ...] = ()
    paper_reductions: tuple[PaperReductionResult, ...] = ()
    paper_restore_quarantine: bool = False
    schema_version: Literal["account-journal-v2", "account-journal-v3"] = "account-journal-v2"

    def __post_init__(self) -> None:
        """Reject future or corrupted account-journal state versions."""
        if self.schema_version not in ("account-journal-v2", "account-journal-v3") or (
            bool(self.paper_activations) != (self.schema_version == "account-journal-v3")
        ):
            raise ValueError("unsupported account journal state schema")


class _AccountSnapshot:
    """Answer history lookups by identity without exposing collection storage."""

    def __init__(self, state: _FirmState) -> None:
        """Retain one immutable state value."""
        self.state = state

    def find_decision(self, instance_id: str, decision_identity: str) -> _SavedDecision | None:
        """Resolve one saved decision by instance and decision identity."""
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
        return None

    def find_batch(self, identity: str) -> _SavedPortfolioBatch | None:
        """Resolve one saved portfolio batch by its stable identity."""
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
        traces = self.state.paper_traces
        for trace in reversed(traces) if newest_first else traces:
            if (account_id is None or trace.account_id == account_id) and (
                instrument_id is None or trace.scenario.instrument_id == instrument_id
            ):
                yield trace


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


# The codec encodes struct fields in sorted wire-name order with no omitted defaults.
_FIRM_FIELD_KEYS: tuple[tuple[str, bytes], ...] = tuple(
    (name, msgspec.json.encode(wire_name) + b":")
    for wire_name, name in sorted(
        (field.encode_name, field.name) for field in msgspec.structs.fields(_FirmState)
    )
)


class AccountStateStore:
    """Own configuration pinning and atomic reads and writes of firm state."""

    def __init__(self, path: Path, config: AccountConfiguration, codec: DomainCodec) -> None:
        """Create or reopen the state document pinned to exact configuration bytes."""
        self.path = path
        self.config = config
        self.codec = codec
        self._configuration_payload = codec.encode_json(config)
        self._cached_snapshot: tuple[bytes, _FirmState] | None = None
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

    def snapshot(self) -> _AccountSnapshot:
        """Read one atomic firm snapshot with its history lookups."""
        return _AccountSnapshot(self.read())

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
                _FirmState.__post_init__(transaction.state)
                payload = self._encode(transaction.state)
                connection.execute(
                    "UPDATE firm SET payload=? WHERE id=1",
                    (payload,),
                )
                connection.commit()
                # Reuse only the immutable state whose exact bytes committed.
                # Every subsequent read still verifies the current SQLite row.
                self._cached_snapshot = payload, transaction.state
            except BaseException:
                connection.rollback()
                raise

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

    def _load(self, connection: sqlite3.Connection) -> _FirmState:
        """Read current bytes and reuse a typed decode only for an identical row."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT configuration, payload FROM firm WHERE id=1").fetchone(),
        )
        if row is None or type(row[0]) is not bytes or row[0] != self._configuration_payload:
            raise ValueError("account configuration or state schema differs")
        if type(row[1]) is not bytes:
            raise ValueError("firm account state is missing or malformed")
        payload = row[1]
        cached = self._cached_snapshot
        if cached is not None and payload == cached[0]:
            return cached[1]
        state = self.codec.decode_json(payload, _FirmState)
        self._cached_snapshot = payload, state
        return state
