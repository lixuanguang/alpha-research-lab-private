"""Persist fenced, single-account paper orders and candidate checkpoints in SQLite."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, cast

# project library imports
from accounting import Fill, Ledger, LedgerBalance, LedgerState
from configuration import InstrumentFeeRate, PaperExecutionScenario
from execution.lifecycle import SpotOrderLifecycle
from execution.records import (
    AccountReservations,
    JournalEvent,
    OrderDecision,
    OrderEvent,
    OrderState,
    StepCommit,
    StepRecord,
)
from financial_units import Money, Price, Quantity
from risk import SpotLimits
from serialization import DomainCodec, SqliteLayout
from strategies import ExposureIntent, TargetIntent

if TYPE_CHECKING:
    # project library imports
    from execution.paper import PaperMarket

# The complete journal layout. Opening refuses any other, including an earlier one.
# Applied fills are rows of ``fills``; the initial ledger is part of the binding.
_LAYOUT: tuple[str, ...] = (
    "CREATE TABLE journal (id INTEGER PRIMARY KEY CHECK (id = 1), binding BLOB NOT NULL, "
    "epoch INTEGER NOT NULL, owner TEXT NOT NULL)",
    "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK (id = 1), checkpoint BLOB, "
    "blocked_reason TEXT)",
    "CREATE TABLE steps (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "step_id TEXT NOT NULL UNIQUE, decision_id TEXT UNIQUE, payload BLOB NOT NULL)",
    "CREATE TABLE markets (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "market_id TEXT NOT NULL UNIQUE, payload BLOB NOT NULL)",
    "CREATE TABLE orders (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "order_id TEXT NOT NULL UNIQUE, terminal INTEGER NOT NULL, payload BLOB NOT NULL)",
    "CREATE INDEX orders_open ON orders(terminal, sequence)",
    "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "event_id TEXT NOT NULL UNIQUE, order_id TEXT NOT NULL, payload BLOB NOT NULL, "
    "order_state BLOB NOT NULL, balance BLOB NOT NULL)",
    "CREATE INDEX events_order ON events(order_id, sequence)",
    "CREATE TABLE fills (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "fill_id TEXT NOT NULL UNIQUE, order_id TEXT NOT NULL, payload BLOB NOT NULL)",
    "CREATE TABLE paper_scenario (id INTEGER PRIMARY KEY CHECK (id = 1), payload BLOB NOT NULL)",
    "CREATE TABLE paper_liquidity (id INTEGER PRIMARY KEY CHECK (id = 1), payload BLOB NOT NULL)",
    "CREATE TABLE paper_market_results (market_id TEXT PRIMARY KEY, payload BLOB NOT NULL)",
)


class PaperOrderJournal:
    """Own one paper/shadow account, its checkpoint, reservations and ordered events.

    An exclusive advisory lock and persisted epoch fence the single writer. The
    lock survives between transactions and is released by the OS on process
    death. Every mutation verifies the epoch under SQLite's write lock. The
    journal deliberately has no executable venue transport or credentials.
    """

    def __init__(
        self,
        path: Path,
        *,
        account: str,
        instance: str,
        binding_identity: str,
        mode: Literal["paper", "shadow"],
        limits: SpotLimits,
        ledger_state: LedgerState,
        fee_rate: Decimal,
    ) -> None:
        """Bind exact account, candidate, spot limits and initial economic state.

        ``fee_rate`` is the worst-case paper fee rate: admission refuses a reserve
        below it, and a matching scenario may not charge more.
        """
        if (
            not isinstance(path, Path)
            or not account
            or not instance
            or not binding_identity
            or mode not in ("paper", "shadow")
        ):
            raise ValueError("paper journal requires an account, instance and safe mode")
        limits.__post_init__()
        ledger_state.__post_init__()
        if (
            ledger_state.dimension != limits.maximum.dimension
            or ledger_state.initial_cash.currency != limits.tick.currency
        ):
            raise ValueError("paper account and spot limits have incompatible units")
        Ledger(ledger_state)
        self.path = path
        self.account = account
        self.instance = instance
        self.binding_identity = binding_identity
        self.mode = mode
        self.limits = limits
        self.fee_rate = InstrumentFeeRate(
            instrument_id=limits.maximum.dimension.instrument_id, rate=fee_rate
        )
        self._lifecycle = SpotOrderLifecycle(limits)
        self._codec = DomainCodec()
        self._lock: BinaryIO | None = None
        self._epoch: int | None = None
        # Decoded order states keyed by their exact stored bytes; see _orders.
        self._decoded_orders: dict[bytes, OrderState] = {}
        self._initial_ledger = ledger_state
        # The ledger after the committed fill rows through a sequence; see _ledger.
        self._ledger_cache: tuple[int, Ledger] | None = None
        # The open write transaction's connection and its uncommitted ledger.
        self._writing: sqlite3.Connection | None = None
        self._staged_ledger: tuple[int, Ledger] | None = None
        self._binding = self._codec.encode_json(
            (
                "paper-order-journal",
                account,
                instance,
                binding_identity,
                mode,
                limits,
                ledger_state,
                self.fee_rate,
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def qualification(self) -> Literal["fixture", "referenced"]:
        """Identify whether fixed authored grids or a selected reference version apply."""
        return "fixture" if self.limits.specification_identity is None else "referenced"

    def claim(self, owner: str) -> int:
        """Acquire the one writer lock without displacing an active process."""
        if type(owner) is not str or not owner:
            raise ValueError("paper owner requires an identity")
        if self._lock is not None:
            raise ValueError("paper journal already has a claimed owner")
        lock = self.path.with_name(self.path.name + ".lock").open("a+b")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = self._query_one(connection, "SELECT epoch FROM journal WHERE id = 1")
                if row is None:
                    raise ValueError("paper journal identity is missing")
                epoch = self._integer(row[0]) + 1
                connection.execute(
                    "UPDATE journal SET epoch = ?, owner = ? WHERE id = 1", (epoch, owner)
                )
                connection.commit()
            self._lock = lock
            self._epoch = epoch
            return epoch
        except BaseException:
            lock.close()
            raise

    def release(self, epoch: int) -> None:
        """Relinquish this process's claimed epoch; later writes must fail."""
        self._require_claim(epoch)
        if self._lock is None:
            raise ValueError("paper owner lock is missing")
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
        self._lock.close()
        self._lock = None
        self._epoch = None

    def close(self) -> None:
        """Release an owned writer lock; journal data remains durable."""
        if self._epoch is not None:
            self.release(self._epoch)

    def __enter__(self) -> PaperOrderJournal:
        """Allow deterministic lock cleanup around a paper run."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Relinquish the local lock even after a failed paper run."""
        self.close()

    def checkpoint(self) -> bytes | None:
        """Read the last atomically committed candidate continuation."""
        with closing(self._connect()) as connection:
            row = self._query_one(connection, "SELECT checkpoint FROM state WHERE id = 1")
        if row is None:
            raise ValueError("paper journal state is missing")
        return None if row[0] is None else self._blob(row[0])

    def ledger_state(self) -> LedgerState:
        """Read the exact fill ledger committed with lifecycle events."""
        with closing(self._connect()) as connection:
            return self._ledger(connection).state

    def ledger_balance(self) -> LedgerBalance:
        """Read exact current balances without rebuilding the committed fill ledger."""
        with closing(self._connect()) as connection:
            return self._ledger(connection).balance

    def blocked_reason(self) -> str | None:
        """Read a durable account break that prevents new order admission."""
        with closing(self._connect()) as connection:
            row = self._query_one(connection, "SELECT blocked_reason FROM state WHERE id = 1")
        if row is None:
            raise ValueError("paper journal state is missing")
        if row[0] is None:
            return None
        if type(row[0]) is not str:
            raise ValueError("paper journal account break is malformed")
        return row[0]

    def reconcile_account(
        self,
        *,
        epoch: int,
        expected_cash: Money,
        expected_holding: Quantity,
        open_order_ids: tuple[str, ...],
    ) -> bool:
        """Compare a paper account snapshot and fence new risk on any break.

        The caller supplies its independently observed paper account snapshot.
        Physical venue reconciliation belongs to the account/adapter increments.
        """
        expected_cash.model_copy()
        expected_holding.model_copy()
        if type(open_order_ids) is not tuple or any(
            type(value) is not str for value in open_order_ids
        ):
            raise TypeError("reconciliation requires a tuple of order identities")
        if len(set(open_order_ids)) != len(open_order_ids):
            raise ValueError("reconciliation repeats an open order identity")
        with self._write(epoch) as connection:
            row = self._query_one(connection, "SELECT blocked_reason FROM state WHERE id = 1")
            if row is None:
                raise ValueError("paper journal state is missing")
            if row[0] == "late_terminal_fill":
                return False
            balance = self._ledger(connection).balance
            open_ids = {order.identity for order in self._orders(connection, open_only=True)}
            matched = (
                expected_cash == balance.cash
                and expected_holding == balance.holding
                and set(open_order_ids) == open_ids
            )
            connection.execute(
                "UPDATE state SET blocked_reason = ? WHERE id = 1",
                (None if matched else "account_break",),
            )
            return matched

    def reservations(self) -> AccountReservations:
        """Read unresolved buy cash and sell inventory commitments."""
        with closing(self._connect()) as connection:
            return self._reservations_for(self._orders(connection, open_only=True))

    def order(self, order_id: str) -> OrderState | None:
        """Read one current child order by stable identity."""
        with closing(self._connect()) as connection:
            return self._order(connection, order_id)

    def orders(self) -> tuple[OrderState, ...]:
        """Read current child orders in their admission order."""
        with closing(self._connect()) as connection:
            return self._orders(connection)

    def step(self, step_id: str) -> StepRecord | None:
        """Read one committed candidate transition and original input bytes."""
        with closing(self._connect()) as connection:
            return self._step(connection, step_id)

    def has_step(self, step_id: str, input_bytes: bytes) -> bool:
        """Detect a saved step before re-evaluation, rejecting conflicting replay."""
        if type(input_bytes) is not bytes:
            raise TypeError("candidate input must be bytes")
        saved = self.step(step_id)
        if saved is None:
            return False
        if saved.input_bytes != input_bytes:
            raise ValueError("candidate step identity was reused with different input bytes")
        return True

    def claim_market(self, *, epoch: int, identity: str, payload: bytes) -> None:
        """Bind a shadow quote to exact bytes before its market step commits."""
        if type(identity) is not str or not identity or type(payload) is not bytes or not payload:
            raise ValueError("paper market claim requires an identity and immutable bytes")
        with self._write(epoch) as connection:
            if (
                self._query_one(connection, "SELECT id FROM paper_scenario WHERE id = 1")
                is not None
            ):
                raise ValueError("shadow quote claim cannot enter a scenario-bound journal")
            saved = self._query_one(
                connection, "SELECT payload FROM markets WHERE market_id = ?", (identity,)
            )
            if saved is None:
                connection.execute(
                    "INSERT INTO markets(market_id, payload) VALUES (?, ?)",
                    (identity, payload),
                )
            elif self._blob(saved[0]) != payload:
                raise ValueError("paper market identity was reused with different payload")

    def markets(self) -> tuple[tuple[str, bytes], ...]:
        """Replay claimed quotes in original order, including interrupted matching."""
        with closing(self._connect()) as connection:
            rows = self._query_all(
                connection, "SELECT market_id, payload FROM markets ORDER BY sequence"
            )
        claims: list[tuple[str, bytes]] = []
        for row in rows:
            identity = row[0]
            if type(identity) is not str:
                raise ValueError("paper market identity is malformed")
            claims.append((identity, self._blob(row[1])))
        return tuple(claims)

    def unfinished_markets(self) -> tuple[tuple[str, bytes], ...]:
        """Return claimed quotes, in original order, whose market step never committed.

        One read joins every claim to its ``market:`` step. Looking each step up
        separately opened a connection per claim, so a restart grew by about half
        a millisecond per retained quote. Committed steps are still decoded here,
        so a malformed one fails the restart as that lookup did.
        """
        with closing(self._connect()) as connection:
            rows = self._query_all(
                connection,
                "SELECT markets.market_id, markets.payload, steps.payload FROM markets "
                "LEFT JOIN steps ON steps.step_id = 'market:' || markets.market_id "
                "ORDER BY markets.sequence",
            )
        claims: list[tuple[str, bytes, object]] = []
        for row in rows:
            identity = row[0]
            if type(identity) is not str:
                raise ValueError("paper market identity is malformed")
            claims.append((identity, self._blob(row[1]), row[2]))
        unfinished: list[tuple[str, bytes]] = []
        for identity, payload, step in claims:
            if step is None:
                unfinished.append((identity, payload))
            else:
                self._codec.decode_json(self._blob(step), StepRecord)
        return tuple(unfinished)

    def match_scenario_market(
        self, *, epoch: int, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> tuple[OrderEvent, ...]:
        """Claim and apply a modeled quote, all fills and liquidity debt atomically.

        One complete transaction means a crash cannot publish a fill while losing
        the capacity consumed at that touch.
        """
        # project library imports
        from execution.paper import PaperLiquidityState, PaperMatchEvaluator, PaperMatchProjection

        market.__post_init__()
        scenario.__post_init__()
        if scenario.fee_rate > self.fee_rate.rate:
            raise ValueError("paper scenario fee rate exceeds the configured worst case")
        payload = self._codec.encode_json(market)
        scenario_payload = self._codec.encode_json(scenario)
        with self._write(epoch) as connection:
            saved_scenario = self._query_one(
                connection, "SELECT payload FROM paper_scenario WHERE id = 1"
            )
            if saved_scenario is None:
                if self._query_one(connection, "SELECT market_id FROM markets LIMIT 1") is not None:
                    raise ValueError("shadow market history cannot adopt an execution scenario")
                connection.execute(
                    "INSERT INTO paper_scenario(id, payload) VALUES (1, ?)",
                    (scenario_payload,),
                )
            elif self._blob(saved_scenario[0]) != scenario_payload:
                raise ValueError("paper execution scenario differs from retained journal")
            saved = self._query_one(
                connection, "SELECT payload FROM markets WHERE market_id = ?", (market.identity,)
            )
            completed = self._query_one(
                connection,
                "SELECT payload FROM paper_market_results WHERE market_id = ?",
                (market.identity,),
            )
            if saved is None:
                if completed is not None:
                    raise ValueError("paper market result lacks its original claim")
                connection.execute(
                    "INSERT INTO markets(market_id, payload) VALUES (?, ?)",
                    (market.identity, payload),
                )
            elif self._blob(saved[0]) != payload:
                raise ValueError("paper market identity was reused with different payload")
            elif completed is None:
                raise ValueError("paper market was claimed outside completed scenario matching")
            if completed is not None:
                original = self._codec.decode_json(self._blob(completed[0]), PaperMatchProjection)
                original.__post_init__()
                if (
                    original.liquidity.last_market_identity != market.identity
                    or original.liquidity.scenario_identity != scenario.identity
                ):
                    raise ValueError("paper market result differs from retained scenario")
                return original.events
            saved_liquidity = self._query_one(
                connection, "SELECT payload FROM paper_liquidity WHERE id = 1"
            )
            liquidity = (
                None
                if saved_liquidity is None
                else self._codec.decode_json(self._blob(saved_liquidity[0]), PaperLiquidityState)
            )
            # Only open orders can match, and a new market has no posted facts (its
            # claim, effects and result commit together), so terminal orders and
            # their events are not even read: both come through indexes.
            orders = self._orders(connection, open_only=True)
            rows: list[tuple[int, bytes]] = [
                (self._integer(row[0]), self._blob(row[1]))
                for order in orders
                for row in self._query_all(
                    connection,
                    "SELECT sequence, payload FROM events WHERE order_id = ? ORDER BY sequence",
                    (order.identity,),
                )
            ]
            rows.sort()
            prior = tuple(self._codec.decode_json(self._blob(row[1]), OrderEvent) for row in rows)
            projection = PaperMatchEvaluator(
                scenario, lot=self.limits.lot, tick=self.limits.tick
            ).project(
                market,
                account_id=self.account,
                orders=orders,
                prior_events=prior,
                liquidity=liquidity,
            )
            for event in projection.events:
                _, is_terminal_break = self._apply_event_fact(connection, event)
                if is_terminal_break:
                    raise ValueError("terminal order cannot receive a late paper fill")
            connection.execute(
                "INSERT INTO paper_liquidity(id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (self._codec.encode_json(projection.liquidity),),
            )
            connection.execute(
                "INSERT INTO paper_market_results(market_id, payload) VALUES (?, ?)",
                (market.identity, self._codec.encode_json(projection)),
            )
            return projection.events

    def steps(self) -> tuple[StepRecord, ...]:
        """Read decision/checkpoint commits in durable sequence."""
        with closing(self._connect()) as connection:
            rows = self._query_all(connection, "SELECT payload FROM steps ORDER BY sequence")
        return tuple(self._codec.decode_json(self._blob(row[0]), StepRecord) for row in rows)

    def events(self, after_sequence: int = 0) -> tuple[JournalEvent, ...]:
        """Replay lifecycle facts after a stored callback cursor."""
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("event cursor must be a nonnegative integer")
        with closing(self._connect()) as connection:
            rows = self._query_all(
                connection,
                "SELECT sequence, payload, order_state, balance FROM events "
                "WHERE sequence > ? ORDER BY sequence",
                (after_sequence,),
            )
        return tuple(
            JournalEvent(
                sequence=self._integer(row[0]),
                event=self._codec.decode_json(self._blob(row[1]), OrderEvent),
                order=self._codec.decode_json(self._blob(row[2]), OrderState),
                balance=self._codec.decode_json(self._blob(row[3]), LedgerBalance),
            )
            for row in rows
        )

    def commit_step(
        self,
        *,
        epoch: int,
        step_id: str,
        checkpoint: bytes,
        decision: OrderDecision | None,
        reference: Price | None,
        maximum_fee: Money,
        input_bytes: bytes = b"",
        result_bytes: bytes = b"",
    ) -> StepCommit:
        """Atomically retain a candidate checkpoint, risk result and child orders."""
        with self._write(epoch) as connection:
            return self._commit_step(
                connection,
                step_id=step_id,
                checkpoint=checkpoint,
                decision=decision,
                reference=reference,
                maximum_fee=maximum_fee,
                input_bytes=input_bytes,
                result_bytes=result_bytes,
                replace_of=None,
            )

    def replace(
        self,
        *,
        epoch: int,
        old_order_id: str,
        step_id: str,
        checkpoint: bytes,
        decision: OrderDecision,
        reference: Price | None,
        maximum_fee: Money,
        input_bytes: bytes = b"",
        result_bytes: bytes = b"",
    ) -> StepCommit:
        """Admit a replacement only after the old order is terminal and confirmed."""
        with self._write(epoch) as connection:
            old = self._order(connection, old_order_id)
            if old is None or not old.is_terminal:
                raise ValueError("replacement requires a confirmed terminal old order")
            return self._commit_step(
                connection,
                step_id=step_id,
                checkpoint=checkpoint,
                decision=decision,
                reference=reference,
                maximum_fee=maximum_fee,
                input_bytes=input_bytes,
                result_bytes=result_bytes,
                replace_of=old_order_id,
            )

    def request_cancel(
        self, *, epoch: int, order_id: str, event_id: str, at: datetime
    ) -> OrderState:
        """Durably mark cancellation requested without releasing its reservation."""
        return self.apply_event(
            epoch=epoch,
            event=OrderEvent(identity=event_id, order_id=order_id, at=at, kind="cancel_requested"),
        )

    def apply_event(self, *, epoch: int, event: OrderEvent) -> OrderState:
        """Apply an identified lifecycle fact and any fill posting exactly once."""
        event.__post_init__()
        if self.mode == "shadow" and event.kind == "fill":
            raise ValueError("shadow mode cannot post modeled fills")
        with self._write(epoch) as connection:
            current, is_terminal_break = self._apply_event_fact(connection, event)
        if is_terminal_break:
            raise ValueError("terminal order cannot receive a late fill; account is blocked")
        return current

    def _apply_event_fact(
        self, connection: sqlite3.Connection, event: OrderEvent
    ) -> tuple[OrderState, bool]:
        """Commit a lifecycle fact or record a terminal-fill account break."""
        payload = self._codec.encode_json(event)
        existing = self._query_one(
            connection,
            "SELECT payload, order_state FROM events WHERE event_id = ?",
            (event.identity,),
        )
        if existing is not None:
            if self._blob(existing[0]) != payload:
                raise ValueError("order event identity was reused with different content")
            return self._codec.decode_json(self._blob(existing[1]), OrderState), False
        previous = self._order(connection, event.order_id)
        if previous is None:
            raise ValueError("order event references an unknown child order")
        if event.at < previous.decision_at:
            raise ValueError("order event precedes its decision")
        ledger = self._ledger(connection)
        if event.fill is not None:
            duplicate = self._query_one(
                connection,
                "SELECT order_id, payload FROM fills WHERE fill_id = ?",
                (event.fill.identity,),
            )
            if duplicate is not None:
                if duplicate[0] != event.order_id or self._blob(
                    duplicate[1]
                ) != self._codec.encode_json(event.fill):
                    raise ValueError("fill identity was reused with different order or economics")
                return previous, False
            if previous.is_terminal:
                connection.execute(
                    "UPDATE state SET blocked_reason = 'late_terminal_fill' WHERE id = 1"
                )
                return previous, True
        current = self._lifecycle.transition(
            previous,
            event,
            last_fill_at=ledger.state.fills[-1].filled_at if ledger.state.fills else None,
        )
        if event.fill is not None:
            ledger.apply(event.fill)
            inserted = connection.execute(
                "INSERT INTO fills(fill_id, order_id, payload) VALUES (?, ?, ?)",
                (event.fill.identity, event.order_id, self._codec.encode_json(event.fill)),
            )
            if inserted.lastrowid is None:
                raise ValueError("paper journal fill sequence is missing")
            self._staged_ledger = (inserted.lastrowid, ledger.copy())
        connection.execute(
            "UPDATE orders SET payload = ?, terminal = ? WHERE order_id = ?",
            (self._codec.encode_json(current), int(current.is_terminal), current.identity),
        )
        connection.execute(
            "INSERT INTO events(event_id, order_id, payload, order_state, balance) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                event.identity,
                event.order_id,
                payload,
                self._codec.encode_json(current),
                self._codec.encode_json(ledger.balance),
            ),
        )
        return current, False

    def _initialize(self) -> None:
        """Create the journal, or require its exact layout and immutable account inputs."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._query_one(connection, "SELECT 1 FROM sqlite_master LIMIT 1") is None:
                for statement in _LAYOUT:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO journal(id, binding, epoch, owner) VALUES (1, ?, 0, '')",
                    (self._binding,),
                )
                connection.execute(
                    "INSERT INTO state(id, checkpoint, blocked_reason) VALUES (1, NULL, NULL)"
                )
            else:
                SqliteLayout.require(connection, _LAYOUT, "unsupported paper journal schema")
                row = self._query_one(connection, "SELECT binding FROM journal WHERE id = 1")
                if row is None:
                    raise ValueError("paper journal binding is missing")
                if self._blob(row[0]) != self._binding:
                    raise ValueError(
                        "paper journal account, candidate, mode or initial state differs"
                    )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        """Open a short transaction with durable local SQLite settings."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _write(self, epoch: int) -> Iterator[sqlite3.Connection]:
        """Verify process lock and persisted epoch inside the write transaction."""
        self._require_claim(epoch)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._writing, self._staged_ledger = connection, None
            try:
                row = self._query_one(connection, "SELECT epoch FROM journal WHERE id = 1")
                if row is None or self._integer(row[0]) != epoch:
                    raise ValueError("paper owner epoch was fenced")
                yield connection
                connection.commit()
                # Only a committed ledger may serve later transactions.
                if self._staged_ledger is not None:
                    self._ledger_cache = self._staged_ledger
            except BaseException:
                connection.rollback()
                raise
            finally:
                self._writing, self._staged_ledger = None, None

    def _require_claim(self, epoch: int) -> None:
        """Reject an absent or locally stale owner before opening a transaction."""
        if type(epoch) is not int or self._epoch != epoch or self._lock is None:
            raise ValueError("paper journal write requires its active fenced owner")

    def _commit_step(
        self,
        connection: sqlite3.Connection,
        *,
        step_id: str,
        checkpoint: bytes,
        decision: OrderDecision | None,
        reference: Price | None,
        maximum_fee: Money,
        input_bytes: bytes,
        result_bytes: bytes,
        replace_of: str | None,
    ) -> StepCommit:
        """Admit all child legs or none under one account-reservation transaction."""
        if (
            type(step_id) is not str
            or not step_id
            or type(checkpoint) is not bytes
            or type(input_bytes) is not bytes
            or type(result_bytes) is not bytes
        ):
            raise ValueError("paper step requires stable identity and immutable bytes")
        maximum_fee.model_copy()
        if maximum_fee.value < 0:
            raise ValueError("paper maximum fee cannot be negative")
        if decision is not None:
            decision.__post_init__()
        if reference is not None:
            reference.model_copy()
        saved = self._step(connection, step_id)
        if saved is not None:
            if (
                saved.checkpoint != checkpoint
                or saved.input_bytes != input_bytes
                or saved.result_bytes != result_bytes
                or saved.decision != decision
                or saved.reference != reference
                or saved.maximum_fee != maximum_fee
            ):
                raise ValueError("candidate step identity was reused with different state or input")
            return saved.commit
        if decision is not None:
            duplicate = self._query_one(
                connection, "SELECT step_id FROM steps WHERE decision_id = ?", (decision.identity,)
            )
            if duplicate is not None:
                raise ValueError("decision identity was committed under another step")
        result = self._admit(
            connection,
            step_id=step_id,
            decision=decision,
            reference=reference,
            maximum_fee=maximum_fee,
            replace_of=replace_of,
        )
        record = StepRecord(
            step_id=step_id,
            checkpoint=checkpoint,
            input_bytes=input_bytes,
            result_bytes=result_bytes,
            decision=decision,
            reference=reference,
            maximum_fee=maximum_fee,
            commit=result,
        )
        connection.execute(
            "INSERT INTO steps(step_id, decision_id, payload) VALUES (?, ?, ?)",
            (
                step_id,
                None if decision is None else decision.identity,
                self._codec.encode_json(record),
            ),
        )
        for order in result.orders:
            connection.execute(
                "INSERT INTO orders(order_id, terminal, payload) VALUES (?, ?, ?)",
                (order.identity, int(order.is_terminal), self._codec.encode_json(order)),
            )
        connection.execute("UPDATE state SET checkpoint = ? WHERE id = 1", (checkpoint,))
        return result

    def _admit(
        self,
        connection: sqlite3.Connection,
        *,
        step_id: str,
        decision: OrderDecision | None,
        reference: Price | None,
        maximum_fee: Money,
        replace_of: str | None,
    ) -> StepCommit:
        """Convert a portable intent and reserve every child against actual state."""
        row = self._query_one(connection, "SELECT blocked_reason FROM state WHERE id = 1")
        if row is None:
            raise ValueError("paper journal state is missing")
        if row[0] is not None:
            if type(row[0]) is not str:
                raise ValueError("paper journal account break is malformed")
            return StepCommit(status="rejected", reason=row[0], orders=())
        if decision is None:
            return StepCommit(status="committed", reason="no_intent", orders=())
        ledger = self._ledger(connection)
        # Terminal orders reserve nothing and block nothing, so only open ones are read.
        existing = self._orders(connection, open_only=True)
        if any(order.status == "unknown" for order in existing):
            return StepCommit(status="rejected", reason="order_outcome_unknown", orders=())
        try:
            legs = self._lifecycle.lower(decision.intent, ledger.balance.holding, reference)
        except ValueError as error:
            return StepCommit(status="rejected", reason=str(error), orders=())
        if not legs:
            return StepCommit(status="committed", reason="target_matched", orders=())
        if maximum_fee.currency != self.limits.tick.currency:
            return StepCommit(status="rejected", reason="incompatible_fee_currency", orders=())
        if isinstance(decision.intent, (TargetIntent, ExposureIntent)) and existing:
            return StepCommit(status="rejected", reason="pending_target", orders=())
        admitted: list[OrderState] = []
        for leg_name, intent in legs:
            reason = self._lifecycle.order_reason(intent)
            if reason is not None:
                return StepCommit(status="rejected", reason=reason, orders=())
            if Fraction(maximum_fee.value) < self.fee_rate.paper_minimum_reserve(
                intent.quantity, intent.limit, self.limits.lot
            ):
                return StepCommit(
                    status="rejected", reason="fee_reserve_below_worst_case", orders=()
                )
            identity = hashlib.sha256(
                self._codec.encode_json(
                    (
                        "paper-child-order",
                        self.account,
                        self.instance,
                        self.binding_identity,
                        step_id,
                        decision,
                        leg_name,
                    )
                )
            ).hexdigest()
            admitted.append(
                OrderState(
                    identity=identity,
                    decision_identity=decision.identity,
                    decision_at=decision.at,
                    intent=intent,
                    status="intent",
                    filled=Quantity(value=Decimal(0), dimension=intent.quantity.dimension),
                    paid_fee=Money(value=Decimal(0), currency=intent.limit.currency),
                    maximum_fee=maximum_fee,
                    replace_of=replace_of,
                )
            )
        commitments = self._reservations_for((*existing, *admitted))
        balance = ledger.balance
        if (balance.holding + commitments.buy_quantity).value > self.limits.maximum.value:
            return StepCommit(status="rejected", reason="holding_limit", orders=())
        if commitments.sell_quantity.value > balance.holding.value:
            return StepCommit(status="rejected", reason="insufficient_holding", orders=())
        if commitments.cash.value > balance.cash.value:
            return StepCommit(status="rejected", reason="insufficient_cash", orders=())
        return StepCommit(status="committed", reason="reserved", orders=tuple(admitted))

    def _ledger(self, connection: sqlite3.Connection) -> Ledger:
        """Rebuild the exact economic state from the initial ledger and the fill rows.

        The ledger built through a fill sequence is reused, so only rows appended
        since are decoded and applied. Inside a write transaction, rows it wrote are
        staged and become reusable only once it commits. Callers receive an
        independent copy they may post to.
        """
        writing = connection is self._writing
        base = self._staged_ledger if writing else None
        if base is None:
            base = self._ledger_cache
        after, ledger = (0, Ledger(self._initial_ledger)) if base is None else base
        ledger = ledger.copy()
        rows = self._query_all(
            connection,
            "SELECT sequence, payload FROM fills WHERE sequence > ? ORDER BY sequence",
            (after,),
        )
        for row in rows:
            ledger.apply(self._codec.decode_json(self._blob(row[1]), Fill))
            after = self._integer(row[0])
        if rows or base is None:
            if writing:
                self._staged_ledger = (after, ledger.copy())
            else:
                self._ledger_cache = (after, ledger.copy())
        return ledger

    def _reservations_for(self, orders: tuple[OrderState, ...]) -> AccountReservations:
        """Reserve full remaining limit notional and conservative fee allowance."""
        cash = Money(value=Decimal(0), currency=self.limits.tick.currency)
        buy = Quantity(value=Decimal(0), dimension=self.limits.maximum.dimension)
        sell = Quantity(value=Decimal(0), dimension=self.limits.maximum.dimension)
        for order in orders:
            if order.is_terminal:
                continue
            remaining = order.remaining
            cash += order.maximum_fee - order.paid_fee
            if order.intent.side == "buy":
                cash += order.intent.limit.amount(remaining)
                buy += remaining
            else:
                sell += remaining
        return AccountReservations(cash=cash, buy_quantity=buy, sell_quantity=sell)

    def _order(self, connection: sqlite3.Connection, order_id: str) -> OrderState | None:
        """Decode one current child order at the persistence boundary."""
        row = self._query_one(
            connection, "SELECT payload FROM orders WHERE order_id = ?", (order_id,)
        )
        return None if row is None else self._codec.decode_json(self._blob(row[0]), OrderState)

    def _orders(
        self, connection: sqlite3.Connection, *, open_only: bool = False
    ) -> tuple[OrderState, ...]:
        """Decode the account's current order states, or only its open ones, in admission order.

        A stored order's bytes change with every update, so an unchanged order
        reuses its earlier validated decode instead of being decoded again on
        every market. Only the latest read is retained. An open-only read uses the
        ``terminal`` column and refuses a row whose state disagrees with it.
        """
        rows = self._query_all(
            connection,
            "SELECT payload FROM orders WHERE terminal = 0 ORDER BY sequence"
            if open_only
            else "SELECT payload FROM orders ORDER BY sequence",
        )
        decoded: dict[bytes, OrderState] = {}
        for row in rows:
            payload = self._blob(row[0])
            order = self._decoded_orders.get(payload)
            if order is None:
                order = self._codec.decode_json(payload, OrderState)
            if open_only and order.is_terminal:
                raise ValueError("paper journal order state differs from its terminal flag")
            decoded[payload] = order
        if len(decoded) != len(rows):
            raise ValueError("paper journal repeats an order payload")
        self._decoded_orders = decoded
        return tuple(decoded.values())

    def _step(self, connection: sqlite3.Connection, step_id: str) -> StepRecord | None:
        """Decode one saved candidate step at the persistence boundary."""
        row = self._query_one(connection, "SELECT payload FROM steps WHERE step_id = ?", (step_id,))
        return None if row is None else self._codec.decode_json(self._blob(row[0]), StepRecord)

    @staticmethod
    def _query_one(
        connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> tuple[object, ...] | None:
        """Narrow an untyped SQLite row before interpreting its fields."""
        raw = cast(object, connection.execute(query, params).fetchone())
        if raw is None:
            return None
        if not isinstance(raw, tuple):
            raise ValueError("paper journal returned a malformed row")
        return cast(tuple[object, ...], raw)

    @staticmethod
    def _query_all(
        connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> tuple[tuple[object, ...], ...]:
        """Narrow a SQLite result set before decoding immutable domain records."""
        raw = cast(object, connection.execute(query, params).fetchall())
        if not isinstance(raw, list):
            raise ValueError("paper journal returned a malformed result set")
        rows: list[tuple[object, ...]] = []
        for value in raw:
            if not isinstance(value, tuple):
                raise ValueError("paper journal returned a malformed row")
            rows.append(cast(tuple[object, ...], value))
        return tuple(rows)

    @staticmethod
    def _blob(value: object) -> bytes:
        """Require an exact persisted BLOB without coercion."""
        if type(value) is not bytes:
            raise ValueError("paper journal BLOB is malformed")
        return value

    @staticmethod
    def _integer(value: object) -> int:
        """Require an exact persisted INTEGER without coercion."""
        if type(value) is not int:
            raise ValueError("paper journal integer is malformed")
        return value
