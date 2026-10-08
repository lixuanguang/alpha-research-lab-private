"""Keep decoded account state reusable only while fresh SQLite bytes agree."""

from __future__ import annotations

# standard library imports
import gc
import sqlite3
import threading
import warnings
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import MethodType
from typing import cast

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace
from test_account_journal import TestAccountJournal as _AccountFixture

# project library imports
from configuration import AccountConfiguration
from execution import AccountJournal
from execution.account_state import AccountStateStore, FirmHead, StateRows
from serialization import DomainCodec


class TestAccountStateCache:
    """Reuse exact cached head bytes only while they match the committed journal."""

    def test_open_reader_reuses_exact_bytes_but_sees_another_writer(self, tmp_path: Path) -> None:
        """A warm reader observes the next committed account fact from another store."""
        fixture = _AccountFixture
        config = fixture._config()
        path = tmp_path / "shared.sqlite3"
        reader = AccountJournal(path, config)
        writer = AccountJournal(path, config)
        before = reader._store.read()
        assert reader._store.read() is before
        assert before.accounts[0].reconciled_at is None

        assert writer.reconcile(
            fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
        )
        changed = reader._store.read()
        assert changed is not before
        assert changed.accounts[0].reconciled_at == fixture.opening_at
        assert reader._store.read() is changed
        assert reader.accounts()[0] == changed.accounts[0]
        assert writer._store.read() is writer._store.read()

        with reader._store.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("alpha",))
        assert reader._store.read().stopped_instances == ("alpha",)
        assert writer._store.read() == reader._store.read()
        reopened = AccountJournal(path, config)
        assert reopened._store.read() == reader._store.read()

    def test_warm_cache_rejects_changed_configuration_and_malformed_payload(
        self, tmp_path: Path
    ) -> None:
        """The cached typed value never hides altered on-disk authority or state bytes."""
        fixture = _AccountFixture
        config = fixture._config()
        path = tmp_path / "tampered.sqlite3"
        codec = DomainCodec()
        store = AccountStateStore(path, config, codec)
        with store.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("alpha",))
        original = store.read()
        assert store.read() is original

        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE firm SET configuration=? WHERE id=1", (b"{}",))
            connection.commit()
        with pytest.raises(ValueError, match="configuration or state schema differs"):
            store.read()

        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE firm SET configuration=?, payload=? WHERE id=1",
                (codec.encode_json(config), b"{"),
            )
            connection.commit()
        with pytest.raises(msgspec.DecodeError):
            store.read()

    def test_rolled_back_stage_never_becomes_cached_state(self, tmp_path: Path) -> None:
        """An exception after staging cannot expose uncommitted selective controls."""
        store = AccountStateStore(
            tmp_path / "rollback.sqlite3", _AccountFixture._config(), DomainCodec()
        )
        original = store.read()
        with pytest.raises(RuntimeError, match="cancel staged mutation"):
            with store.write() as transaction:
                transaction.state = replace(transaction.state, stopped_instances=("alpha",))
                raise RuntimeError("cancel staged mutation")
        after = store.read()
        assert after is original
        assert after.stopped_instances == ()

        with store.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("alpha",))
        committed = store.read()
        assert committed.stopped_instances == ("alpha",)
        assert committed is store.read()

    @classmethod
    def _require_exact(
        cls, path: Path, store: AccountStateStore, config: AccountConfiguration, codec: DomainCodec
    ) -> None:
        """Compare stored bytes with an independent full encoding and fresh decode."""
        payload = cls.stored_payload(path)
        head = codec.decode_json(payload, FirmHead)
        assert codec.encode_json(head) == payload
        # The head holds the state without its row-kept fields and postings.
        assert head.state == StateRows.strip(store.read())
        assert store.read() == AccountStateStore(path, config, codec).read()

    def test_incremental_encoding_commits_exact_full_head_bytes(self, tmp_path: Path) -> None:
        """Reused field bytes never diverge from encoding the complete committed head."""
        fixture = _AccountFixture
        config = fixture._config()
        path = tmp_path / "incremental.sqlite3"
        codec = DomainCodec()
        journal = AccountJournal(path, config)
        store = journal._store

        assert journal.reconcile(
            fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
        )
        self._require_exact(path, store, config, codec)
        for staged in (("alpha",), ("alpha", "beta"), ("alpha", "beta", "gamma"), ("beta",), ()):
            with store.write() as transaction:
                transaction.state = replace(transaction.state, stopped_instances=staged)
            self._require_exact(path, store, config, codec)
        with store.write() as transaction:
            transaction.state = replace(transaction.state, crossing_policy="reject")
        self._require_exact(path, store, config, codec)
        with store.write() as transaction:
            first = transaction.state.accounts[0]
            transaction.state = replace(
                transaction.state, accounts=(replace(first, reconciled_at=None),)
            )
        self._require_exact(path, store, config, codec)
        with pytest.raises(RuntimeError, match="discard"):
            with store.write() as transaction:
                transaction.state = replace(transaction.state, stopped_instances=("staged",))
                raise RuntimeError("discard")
        with store.write() as transaction:
            extended: tuple[str, ...] = (*transaction.state.stopped_instances, "delta")
            transaction.state = replace(transaction.state, stopped_instances=extended)
        self._require_exact(path, store, config, codec)
        other = AccountStateStore(path, config, DomainCodec())
        with other.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("other",))
        with store.write() as transaction:
            followed: tuple[str, ...] = (*transaction.state.stopped_instances, "after")
            transaction.state = replace(transaction.state, stopped_instances=followed)
        self._require_exact(path, store, config, codec)
        assert store.read().stopped_instances == ("other", "after")

    @staticmethod
    def stored_payload(path: Path) -> bytes:
        """Read the exact committed firm head."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
        assert row is not None and type(row[0]) is bytes
        return row[0]


class _CountedConnections:
    """Count the connections an account store opens."""

    def __init__(self, connect: Callable[[AccountStateStore], sqlite3.Connection]) -> None:
        """Wrap the store's connection factory with no connection counted."""
        self._connect = connect
        self.opened = 0

    def __get__(self, store: AccountStateStore | None, owner: type[AccountStateStore]) -> object:
        """Bind to a store as the replaced method does."""
        return self if store is None else MethodType(self, store)

    def __call__(self, store: AccountStateStore) -> sqlite3.Connection:
        """Open and count one connection."""
        self.opened += 1
        return self._connect(store)


class TestAccountStoreConnection:
    """Reuse one SQLite connection a store, falling back to fresh ones when it is lent."""

    def test_one_connection_serves_every_sequential_transaction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After creating its schema, a store opens one connection for every read and write."""
        fixture = _AccountFixture
        counted = _CountedConnections(AccountStateStore._connect)
        monkeypatch.setattr(AccountStateStore, "_connect", counted)
        journal = AccountJournal(tmp_path / "reused.sqlite3", fixture._config())
        assert counted.opened == 1
        assert journal.reconcile(
            fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
        )
        for _ in range(5):
            journal.accounts()
            journal.paper_trace_history()
        with journal._store.write() as transaction:
            transaction.state = replace(transaction.state, stopped_instances=("alpha",))
        assert journal._store.read().stopped_instances == ("alpha",)
        assert counted.opened == 2

    def test_nested_and_concurrent_uses_get_their_own_connection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A use while the reused connection is lent opens its own and sees committed state."""
        fixture = _AccountFixture
        journal = AccountJournal(tmp_path / "nested.sqlite3", fixture._config())
        store = journal._store
        counted = _CountedConnections(AccountStateStore._connect)
        monkeypatch.setattr(AccountStateStore, "_connect", counted)
        with store.snapshot() as snapshot:
            with store.write() as transaction:
                transaction.state = replace(transaction.state, stopped_instances=("beta",))
            assert snapshot.state.stopped_instances == ()
            assert store.read().stopped_instances == ("beta",)
            other = _ThreadedRead(store)
            other.start()
            other.join(5)
            assert other.read == ("beta",)
        assert counted.opened == 4
        assert store.read().stopped_instances == ("beta",)
        assert counted.opened == 4

    def test_a_collected_store_closes_its_connection_and_checkpoints(self, tmp_path: Path) -> None:
        """Dropping a journal closes its reused connection without a resource warning."""
        fixture = _AccountFixture
        path = tmp_path / "collected.sqlite3"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            journal = AccountJournal(path, fixture._config())
            assert journal.reconcile(
                fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
            )
            assert path.with_name(path.name + "-wal").exists()
            del journal
            gc.collect()
        assert not [item for item in caught if issubclass(item.category, ResourceWarning)]
        assert not path.with_name(path.name + "-wal").exists()
        reopened = AccountJournal(path, fixture._config())
        assert reopened.accounts()[0].reconciled_at == fixture.opening_at


class _ThreadedRead(threading.Thread):
    """Read a store's stopped instances from another thread."""

    def __init__(self, store: AccountStateStore) -> None:
        """Bind the store; nothing is read until the thread runs."""
        super().__init__()
        self.store = store
        self.read: tuple[str, ...] | None = None

    def run(self) -> None:
        """Read the store's committed stopped instances."""
        self.read = self.store.read().stopped_instances
